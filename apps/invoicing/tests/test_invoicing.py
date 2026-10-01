from datetime import UTC, datetime, timedelta

import pytest
from django.core import mail
from django.core.management import call_command
from django.urls import reverse

from apps.apikeys.models import APIKey
from apps.billing import services as billing
from apps.billing.models import InvoiceItem, Subscription
from apps.billing.tests.factories import PlanFactory
from apps.invoicing.models import Invoice
from apps.invoicing.services import (
    create_invoice,
    outstanding_balance,
    run_billing_cycle,
    upcoming_invoice,
)
from apps.metering.models import UsageRecord
from apps.metering.services import record_usage
from apps.organizations.models import Role
from apps.organizations.tests.factories import OrganizationFactory

pytestmark = pytest.mark.django_db

APRIL_1 = datetime(2026, 4, 1, tzinfo=UTC)
MAY_1 = datetime(2026, 5, 1, tzinfo=UTC)


@pytest.fixture
def plan():
    return PlanFactory(
        code="growth",
        amount=5000,
        included_units=1000,
        overage_unit_amount=100,
        overage_unit_size=100,
    )


def historical_usage(org, quantity, timestamp):
    """Usage in a past period (bypasses the API's backdating guard on purpose)."""
    UsageRecord.objects.create(
        organization=org, quantity=quantity, timestamp=timestamp, idempotency_key=str(timestamp)
    )


def invoices_url(org, name="invoice-list", **kwargs):
    return reverse(name, kwargs={"org_slug": org.slug, **kwargs})


def test_invoice_collects_pending_items_and_numbers_sequentially(org, plan):
    billing.subscribe(organization=org, plan=plan, now=APRIL_1)

    first = create_invoice(org, now=APRIL_1)
    nothing = create_invoice(org, now=APRIL_1)

    assert first.number == "ACMEINC-00001"
    assert first.total == 5000
    assert first.due_at == APRIL_1 + timedelta(days=7)
    assert nothing is None  # no pending items left
    assert not InvoiceItem.objects.filter(invoice__isnull=True).exists()


def test_numbers_are_per_organization(org, plan):
    other = OrganizationFactory(name="Globex")
    for organization in (org, other, org):
        InvoiceItem.objects.create(
            organization=organization,
            kind="credit",
            description="x",
            unit_amount=100,
            amount=100,
            currency="usd",
        )
        create_invoice(organization)

    assert sorted(Invoice.objects.values_list("number", flat=True)) == [
        "ACMEINC-00001",
        "ACMEINC-00002",
        "GLOBEX-00001",
    ]


def test_negative_total_is_carried_forward_as_credit(org):
    InvoiceItem.objects.create(
        organization=org,
        kind="credit",
        description="Goodwill",
        unit_amount=-700,
        amount=-700,
        currency="usd",
    )
    InvoiceItem.objects.create(
        organization=org,
        kind="subscription",
        description="Fee",
        unit_amount=500,
        amount=500,
        currency="usd",
    )

    invoice = create_invoice(org)

    assert (invoice.subtotal, invoice.total, invoice.status) == (-200, 0, Invoice.Status.PAID)
    carried = InvoiceItem.objects.get(invoice__isnull=True)
    assert carried.amount == -200


def test_billing_cycle_bills_overage_in_arrears_and_fee_in_advance(org, plan):
    sub = billing.subscribe(organization=org, plan=plan, now=APRIL_1)
    create_invoice(org, now=APRIL_1)
    historical_usage(org, 1250, APRIL_1 + timedelta(days=3))
    Subscription.objects.filter(pk=sub.pk).update(current_period_end=MAY_1)

    assert run_billing_cycle(now=MAY_1 + timedelta(minutes=1)) == 1

    invoice = Invoice.objects.latest("id")
    kinds = {item.kind: item.amount for item in invoice.items.all()}
    assert kinds == {"usage": 300, "subscription": 5000}  # 250 units -> 3 blocks of 100
    assert invoice.total == 5300


def test_billing_cycle_is_idempotent(org, plan):
    billing.subscribe(organization=org, plan=plan, now=APRIL_1)
    create_invoice(org, now=APRIL_1)
    later = MAY_1 + timedelta(hours=1)

    assert run_billing_cycle(now=later) == 1
    assert run_billing_cycle(now=later) == 0
    assert Invoice.objects.count() == 2


def test_billing_cycle_catches_up_missed_periods(org, plan):
    billing.subscribe(organization=org, plan=plan, now=APRIL_1)
    create_invoice(org, now=APRIL_1)

    issued = run_billing_cycle(now=datetime(2026, 7, 2, tzinfo=UTC))

    assert issued == 3  # May, June and July periods
    assert Subscription.objects.get().current_period_end == datetime(2026, 8, 1, tzinfo=UTC)


def test_canceled_at_period_end_bills_final_usage_only(org, plan):
    sub = billing.subscribe(organization=org, plan=plan, now=APRIL_1)
    create_invoice(org, now=APRIL_1)
    historical_usage(org, 1100, APRIL_1 + timedelta(days=1))
    billing.cancel(subscription=sub, at_period_end=True)

    run_billing_cycle(now=MAY_1 + timedelta(minutes=1))

    final = Invoice.objects.latest("id")
    assert [item.kind for item in final.items.all()] == ["usage"]
    assert Subscription.objects.get().status == Subscription.Status.CANCELED


def test_upcoming_invoice_preview(org, plan):
    billing.subscribe(organization=org, plan=plan)
    create_invoice(org)
    record_usage(organization=org, quantity=1101, idempotency_key="u")

    preview = upcoming_invoice(org)

    assert [line["amount"] for line in preview["lines"]] == [200, 5000]
    assert preview["total"] == 5200


def test_outstanding_balance(org, plan):
    billing.subscribe(organization=org, plan=plan)
    create_invoice(org)

    assert outstanding_balance(org) == 5000


def test_invoice_is_emailed_to_billing_contact(org, plan, django_capture_on_commit_callbacks):
    billing.subscribe(organization=org, plan=plan)

    with django_capture_on_commit_callbacks(execute=True):
        invoice = create_invoice(org)

    assert mail.outbox[0].to == [org.billing_email]
    assert invoice.number in mail.outbox[0].subject
    assert "50.00 USD" in mail.outbox[0].body


def test_run_billing_command(capsys):
    call_command("run_billing")

    assert "Issued 0 invoice(s)." in capsys.readouterr().out


# --- API -----------------------------------------------------------------------------------


def test_subscribing_via_api_issues_first_invoice(member_client, org, plan):
    client = member_client(Role.OWNER)

    client.post(
        reverse("subscription-list", kwargs={"org_slug": org.slug}),
        {"plan": "growth"},
        format="json",
    )
    invoices = client.get(invoices_url(org)).json()["results"]

    assert len(invoices) == 1
    assert invoices[0]["items"][0]["kind"] == "subscription"


def test_upgrade_via_api_invoices_proration(member_client, org, plan):
    PlanFactory(code="scale", amount=15000)
    client = member_client(Role.OWNER)
    client.post(
        reverse("subscription-list", kwargs={"org_slug": org.slug}),
        {"plan": "growth"},
        format="json",
    )

    client.post(
        reverse("subscription-change-plan", kwargs={"org_slug": org.slug}),
        {"plan": "scale"},
        format="json",
    )

    latest = client.get(invoices_url(org)).json()["results"][0]
    assert {item["kind"] for item in latest["items"]} == {"proration"}


def test_invoice_detail_by_number_and_tenant_isolation(member_client, org, plan):
    billing.subscribe(organization=org, plan=plan)
    invoice = create_invoice(org)
    other = OrganizationFactory()
    InvoiceItem.objects.create(
        organization=other, kind="credit", description="x", unit_amount=1, amount=1, currency="usd"
    )
    foreign = create_invoice(other)
    client = member_client(Role.MEMBER)

    assert client.get(invoices_url(org, "invoice-detail", number=invoice.number)).status_code == 200
    assert client.get(invoices_url(org, "invoice-detail", number=foreign.number)).status_code == 404


def test_billing_read_key_lists_invoices(api_client, org, plan):
    billing.subscribe(organization=org, plan=plan)
    create_invoice(org)
    _, raw = APIKey.generate(organization=org, name="erp", scopes=["billing:read"])

    response = api_client.get(invoices_url(org), HTTP_X_API_KEY=raw)

    assert response.json()["count"] == 1


def test_upcoming_endpoint(member_client, org, plan):
    billing.subscribe(organization=org, plan=plan)

    response = member_client(Role.MEMBER).get(invoices_url(org, "invoice-upcoming"))

    assert response.status_code == 200
    assert response.json()["currency"] == "usd"
