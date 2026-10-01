from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.apikeys.models import APIKey
from apps.billing import services as billing
from apps.billing.tests.factories import PlanFactory
from apps.metering import services
from apps.metering.models import UsageRecord
from apps.organizations.models import Role

pytestmark = pytest.mark.django_db


@pytest.fixture
def usage_key(org):
    _, raw = APIKey.generate(organization=org, name="backend", scopes=["usage:write"])
    return raw


def usage_url(org, name="usage-list"):
    return reverse(name, kwargs={"org_slug": org.slug})


# --- services -------------------------------------------------------------------------


def test_record_is_idempotent(org):
    first, created = services.record_usage(organization=org, quantity=5, idempotency_key="k1")
    again, created_again = services.record_usage(organization=org, quantity=5, idempotency_key="k1")

    assert (created, created_again) == (True, False)
    assert first == again
    assert UsageRecord.objects.count() == 1


def test_reusing_key_with_different_payload_is_rejected(org):
    services.record_usage(organization=org, quantity=5, idempotency_key="k1")

    with pytest.raises(services.UsageError, match="different payload"):
        services.record_usage(organization=org, quantity=6, idempotency_key="k1")


def test_same_key_in_different_orgs_is_independent(org):
    from apps.organizations.tests.factories import OrganizationFactory

    services.record_usage(organization=org, quantity=1, idempotency_key="k")
    services.record_usage(organization=OrganizationFactory(), quantity=1, idempotency_key="k")

    assert UsageRecord.objects.count() == 2


@pytest.mark.parametrize("delta", [timedelta(hours=1), -timedelta(days=60)])
def test_timestamp_bounds(org, delta):
    with pytest.raises(services.UsageError):
        services.record_usage(
            organization=org, quantity=1, idempotency_key="k", timestamp=timezone.now() + delta
        )


def test_usage_between_sums_window(org):
    now = timezone.now()
    services.record_usage(organization=org, quantity=3, idempotency_key="a", timestamp=now)
    services.record_usage(
        organization=org, quantity=7, idempotency_key="b", timestamp=now - timedelta(days=10)
    )

    assert services.usage_between(org, now - timedelta(days=1), now + timedelta(seconds=1)) == 3


@pytest.mark.parametrize(
    ("units", "expected"),
    [(9_000, (0, 0)), (10_000, (0, 0)), (10_001, (1, 50)), (12_500, (3, 150))],
)
def test_overage_is_billed_per_started_block(units, expected):
    plan = PlanFactory.build(included_units=10_000, overage_unit_amount=50, overage_unit_size=1000)

    assert services.overage(plan, units) == expected


# --- API --------------------------------------------------------------------------------


def test_report_usage_with_api_key(api_client, org, usage_key):
    payload = {"quantity": 120, "idempotency_key": "req-001"}

    first = api_client.post(usage_url(org), payload, format="json", HTTP_X_API_KEY=usage_key)
    retry = api_client.post(usage_url(org), payload, format="json", HTTP_X_API_KEY=usage_key)

    assert first.status_code == 201
    assert retry.status_code == 200
    assert retry.json()["id"] == first.json()["id"]


def test_key_without_usage_scope_is_denied(api_client, org):
    _, raw = APIKey.generate(organization=org, name="ro", scopes=["billing:read"])

    response = api_client.post(
        usage_url(org), {"quantity": 1, "idempotency_key": "x"}, format="json", HTTP_X_API_KEY=raw
    )

    assert response.status_code == 403


def test_members_cannot_post_usage_but_can_list(member_client, org):
    client = member_client(Role.MEMBER)

    post = client.post(usage_url(org), {"quantity": 1, "idempotency_key": "x"}, format="json")

    assert post.status_code == 403
    assert client.get(usage_url(org)).status_code == 200


def test_invalid_metric_name(api_client, org, usage_key):
    response = api_client.post(
        usage_url(org),
        {"quantity": 1, "idempotency_key": "x", "metric": "Drop Table"},
        format="json",
        HTTP_X_API_KEY=usage_key,
    )

    assert response.status_code == 400


def test_summary_projects_overage(member_client, org):
    plan = PlanFactory(
        code="metered", included_units=1000, overage_unit_amount=200, overage_unit_size=100
    )
    billing.subscribe(organization=org, plan=plan)
    services.record_usage(organization=org, quantity=1250, idempotency_key="a")

    body = member_client(Role.MEMBER).get(usage_url(org, "usage-summary")).json()

    assert body["used"] == 1250
    assert body["overage_units"] == 250
    assert body["projected_overage_amount"] == 600  # 3 started blocks of 100 units
