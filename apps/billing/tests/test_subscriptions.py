from datetime import UTC, datetime, timedelta

import pytest
from django.urls import reverse

from apps.apikeys.models import APIKey
from apps.billing import services
from apps.billing.models import InvoiceItem, Subscription
from apps.billing.services import BillingError
from apps.billing.tests.factories import PlanFactory
from apps.organizations.models import Role

pytestmark = pytest.mark.django_db

APRIL_1 = datetime(2026, 4, 1, tzinfo=UTC)


@pytest.fixture
def starter():
    return PlanFactory(code="starter", amount=3000)


@pytest.fixture
def pro():
    return PlanFactory(code="pro", amount=9000)


def url(org, name="subscription-list"):
    return reverse(name, kwargs={"org_slug": org.slug})


# --- services ---------------------------------------------------------------------------


def test_subscribe_bills_first_period_in_advance(org, starter):
    sub = services.subscribe(organization=org, plan=starter, now=APRIL_1)

    assert sub.status == Subscription.Status.ACTIVE
    assert sub.current_period_end == datetime(2026, 5, 1, tzinfo=UTC)
    item = InvoiceItem.objects.get()
    assert (item.kind, item.amount) == ("subscription", 3000)


def test_trial_creates_no_charge(org):
    plan = PlanFactory(code="trial", trial_days=14)

    sub = services.subscribe(organization=org, plan=plan, now=APRIL_1)

    assert sub.status == Subscription.Status.TRIALING
    assert sub.trial_end == APRIL_1 + timedelta(days=14)
    assert not InvoiceItem.objects.exists()


def test_only_one_live_subscription(org, starter, pro):
    services.subscribe(organization=org, plan=starter)

    with pytest.raises(BillingError, match="already has"):
        services.subscribe(organization=org, plan=pro)


def test_resubscribe_after_cancel(org, starter):
    sub = services.subscribe(organization=org, plan=starter)
    services.cancel(subscription=sub, at_period_end=False)

    assert services.subscribe(organization=org, plan=starter).is_live


def test_currency_mismatch(org):
    with pytest.raises(BillingError, match="EUR"):
        services.subscribe(organization=org, plan=PlanFactory(code="eu", currency="eur"))


def test_upgrade_mid_period_prorates(org, starter, pro):
    sub = services.subscribe(organization=org, plan=starter, now=APRIL_1)
    halfway = APRIL_1 + timedelta(days=15)  # April has 30 days

    mode, lines = services.change_plan(subscription=sub, new_plan=pro, now=halfway)

    assert mode == "immediate"
    assert [line.amount for line in lines] == [-1500, 4500]
    sub.refresh_from_db()
    assert sub.plan == pro
    assert InvoiceItem.objects.filter(kind="proration").count() == 2


def test_downgrade_is_scheduled_for_period_end(org, starter, pro):
    sub = services.subscribe(organization=org, plan=pro, now=APRIL_1)

    mode, lines = services.change_plan(subscription=sub, new_plan=starter, now=APRIL_1)

    sub.refresh_from_db()
    assert (mode, lines) == ("scheduled", [])
    assert sub.plan == pro and sub.pending_plan == starter


def test_upgrade_during_trial_has_no_proration(org, pro):
    trial = PlanFactory(code="trial", trial_days=7)
    sub = services.subscribe(organization=org, plan=trial)

    mode, lines = services.change_plan(subscription=sub, new_plan=pro)

    assert (mode, lines) == ("immediate", [])


def test_interval_mismatch_rejected(org, starter):
    sub = services.subscribe(organization=org, plan=starter)
    yearly = PlanFactory(code="yearly", interval="year", amount=30000)

    with pytest.raises(BillingError, match="interval"):
        services.change_plan(subscription=sub, new_plan=yearly)


def test_renew_applies_pending_plan_and_bills_next_period(org, starter, pro):
    sub = services.subscribe(organization=org, plan=pro, now=APRIL_1)
    services.change_plan(subscription=sub, new_plan=starter, now=APRIL_1)

    sub = services.renew(subscription=sub, now=datetime(2026, 5, 1, 0, 1, tzinfo=UTC))

    assert sub.plan == starter and sub.pending_plan is None
    assert sub.current_period_end == datetime(2026, 6, 1, tzinfo=UTC)
    assert InvoiceItem.objects.latest("id").amount == 3000


def test_renew_ends_trial(org):
    plan = PlanFactory(code="trial", trial_days=14, amount=2000)
    sub = services.subscribe(organization=org, plan=plan, now=APRIL_1)

    sub = services.renew(subscription=sub, now=APRIL_1 + timedelta(days=14))

    assert sub.status == Subscription.Status.ACTIVE
    assert sub.current_period_end == datetime(2026, 5, 15, tzinfo=UTC)  # trial end + 1 month
    assert InvoiceItem.objects.get().amount == 2000


def test_renew_honours_cancel_at_period_end(org, starter):
    sub = services.subscribe(organization=org, plan=starter, now=APRIL_1)
    services.cancel(subscription=sub, at_period_end=True)

    sub = services.renew(subscription=sub, now=datetime(2026, 5, 2, tzinfo=UTC))

    assert sub.status == Subscription.Status.CANCELED
    assert InvoiceItem.objects.count() == 1  # no new fee


def test_renew_is_noop_before_period_end(org, starter):
    sub = services.subscribe(organization=org, plan=starter, now=APRIL_1)

    services.renew(subscription=sub, now=APRIL_1 + timedelta(days=3))

    assert InvoiceItem.objects.count() == 1


# --- API ---------------------------------------------------------------------------------


def test_plan_catalog_is_public(api_client, starter):
    response = api_client.get(reverse("plan-list"))

    assert response.json()["results"][0]["price"] == "30.00 USD"


def test_billing_manager_subscribes(member_client, org, starter):
    response = member_client(Role.BILLING).post(url(org), {"plan": "starter"}, format="json")

    assert response.status_code == 201
    assert response.json()["plan"]["code"] == "starter"


def test_plain_member_cannot_subscribe_but_can_read(member_client, org, starter):
    client = member_client(Role.MEMBER)

    assert client.post(url(org), {"plan": "starter"}, format="json").status_code == 403
    services.subscribe(organization=org, plan=starter)
    assert client.get(url(org)).status_code == 200


def test_no_subscription_returns_404(member_client, org):
    assert member_client(Role.MEMBER).get(url(org)).status_code == 404


def test_duplicate_subscription_returns_409(member_client, org, starter):
    client = member_client(Role.OWNER)
    client.post(url(org), {"plan": "starter"}, format="json")

    response = client.post(url(org), {"plan": "starter"}, format="json")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "billing_error"


def test_preview_then_change_plan(member_client, org, starter, pro):
    client = member_client(Role.OWNER)
    client.post(url(org), {"plan": "starter"}, format="json")

    preview = client.get(url(org, "subscription-preview-change"), {"plan": "pro"}).json()
    change = client.post(url(org, "subscription-change-plan"), {"plan": "pro"}, format="json")

    assert preview["mode"] == "immediate"
    assert preview["total"] > 0
    assert change.json()["subscription"]["plan"]["code"] == "pro"


def test_cancel_and_resume(member_client, org, starter):
    client = member_client(Role.OWNER)
    client.post(url(org), {"plan": "starter"}, format="json")

    canceled = client.post(url(org, "subscription-cancel"), {}, format="json").json()
    resumed = client.post(url(org, "subscription-resume")).json()

    assert canceled["cancel_at_period_end"] is True
    assert resumed["cancel_at_period_end"] is False


def test_api_key_with_billing_read_can_only_read(org, starter, api_client):
    services.subscribe(organization=org, plan=starter)
    _, raw = APIKey.generate(organization=org, name="x", scopes=["billing:read"])

    assert api_client.get(url(org), HTTP_X_API_KEY=raw).status_code == 200
    assert (
        api_client.post(
            url(org, "subscription-cancel"), {}, format="json", HTTP_X_API_KEY=raw
        ).status_code
        == 403
    )


def test_api_key_without_scope_is_denied(org, starter, api_client):
    services.subscribe(organization=org, plan=starter)
    _, raw = APIKey.generate(organization=org, name="x", scopes=["usage:write"])

    assert api_client.get(url(org), HTTP_X_API_KEY=raw).status_code == 403
