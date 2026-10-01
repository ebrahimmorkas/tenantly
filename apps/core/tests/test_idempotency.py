from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.apikeys.models import APIKey
from apps.billing.models import Subscription
from apps.billing.tests.factories import PlanFactory
from apps.core.idempotency import IdempotencyRecord, purge_expired
from apps.metering.models import UsageRecord
from apps.organizations.models import Role

pytestmark = pytest.mark.django_db


@pytest.fixture
def plan():
    return PlanFactory(code="starter")


def subscribe(client, org, key, plan_code="starter"):
    return client.post(
        reverse("subscription-list", kwargs={"org_slug": org.slug}),
        {"plan": plan_code},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )


def test_retry_replays_original_response(member_client, org, plan):
    client = member_client(Role.OWNER)

    first = subscribe(client, org, "sub-1")
    retry = subscribe(client, org, "sub-1")

    assert first.status_code == retry.status_code == 201
    assert retry.json() == first.json()
    assert retry["Idempotent-Replayed"] == "true"
    assert Subscription.objects.count() == 1


def test_without_key_second_request_conflicts(member_client, org, plan):
    client = member_client(Role.OWNER)
    url = reverse("subscription-list", kwargs={"org_slug": org.slug})

    client.post(url, {"plan": "starter"}, format="json")

    assert client.post(url, {"plan": "starter"}, format="json").status_code == 409


def test_same_key_different_body_is_rejected(member_client, org, plan):
    PlanFactory(code="pro")
    client = member_client(Role.OWNER)
    subscribe(client, org, "k")

    response = subscribe(client, org, "k", plan_code="pro")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "idempotency_key_reused"


def test_in_flight_request_returns_409(member_client, org, plan):
    client = member_client(Role.OWNER)
    subscribe(client, org, "k")
    IdempotencyRecord.objects.update(status_code=None, response_body=None)  # simulate in-flight

    assert subscribe(client, org, "k").status_code == 409


def test_keys_are_scoped_per_caller(member_client, org, plan):
    alice, bob = member_client(Role.OWNER), member_client(Role.OWNER)

    subscribe(alice, org, "same-key")
    response = subscribe(bob, org, "same-key")

    assert response.status_code == 409  # processed (not replayed): org already subscribed
    assert IdempotencyRecord.objects.count() == 2


def test_denied_requests_do_not_consume_key(member_client, org, plan):
    subscribe(member_client(Role.MEMBER), org, "k")

    assert not IdempotencyRecord.objects.exists()


def test_works_with_api_keys(api_client, org):
    _, raw = APIKey.generate(organization=org, name="b", scopes=["usage:write"])
    url = reverse("usage-list", kwargs={"org_slug": org.slug})

    for _ in range(2):
        api_client.post(
            url,
            {"quantity": 1, "idempotency_key": "u-1"},
            format="json",
            HTTP_X_API_KEY=raw,
            HTTP_IDEMPOTENCY_KEY="req-1",
        )

    assert UsageRecord.objects.count() == 1
    assert IdempotencyRecord.objects.get().scope.startswith("key:")


def test_get_requests_ignore_the_header(member_client, org):
    member_client(Role.MEMBER).get(
        reverse("member-list", kwargs={"org_slug": org.slug}), HTTP_IDEMPOTENCY_KEY="x"
    )

    assert not IdempotencyRecord.objects.exists()


def test_purge_expired_records(member_client, org, plan):
    subscribe(member_client(Role.OWNER), org, "old")
    IdempotencyRecord.objects.update(created_at=timezone.now() - timedelta(days=2))

    assert purge_expired() == 1
