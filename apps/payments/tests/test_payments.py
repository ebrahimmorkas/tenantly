from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.billing import services as billing
from apps.billing.models import Subscription
from apps.billing.tests.factories import PlanFactory
from apps.invoicing.models import Invoice
from apps.invoicing.services import create_invoice
from apps.organizations.models import Role
from apps.payments import services
from apps.payments.models import Payment
from apps.payments.services import PaymentError, attempt_payment, retry_due_payments

pytestmark = pytest.mark.django_db


@pytest.fixture
def invoice(org):
    billing.subscribe(organization=org, plan=PlanFactory(code="pro", amount=4900))
    return create_invoice(org)


def test_successful_charge_marks_invoice_paid(org, invoice):
    services.set_payment_method(org, "pm_card_visa")

    payment = attempt_payment(invoice.pk)

    invoice.refresh_from_db()
    assert payment.status == Payment.Status.SUCCEEDED
    assert (invoice.status, invoice.amount_paid, invoice.amount_due) == ("paid", 4900, 0)


def test_failed_charge_schedules_retry_and_marks_past_due(org, invoice, settings):
    settings.TENANTLY_DUNNING_SCHEDULE_DAYS = [1, 3, 5]
    services.set_payment_method(org, "pm_card_declined")
    now = timezone.now()

    payment = attempt_payment(invoice.pk, now=now)

    invoice.refresh_from_db()
    assert payment.failure_reason == "card_declined"
    assert invoice.status == Invoice.Status.OPEN
    assert invoice.next_payment_attempt == now + timedelta(days=1)
    assert Subscription.objects.get().status == Subscription.Status.PAST_DUE


def test_exhausted_retries_cancel_subscription(org, invoice, settings):
    settings.TENANTLY_DUNNING_SCHEDULE_DAYS = [1, 3]
    services.set_payment_method(org, "pm_card_insufficient_funds")

    for _ in range(3):
        attempt_payment(invoice.pk)

    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.UNCOLLECTIBLE
    assert invoice.attempt_count == 3
    assert Subscription.objects.get().status == Subscription.Status.CANCELED


def test_updating_card_and_retry_recovers_past_due(org, invoice):
    services.set_payment_method(org, "pm_card_declined")
    attempt_payment(invoice.pk)
    services.set_payment_method(org, "pm_card_mastercard")

    attempt_payment(invoice.pk)

    assert Subscription.objects.get().status == Subscription.Status.ACTIVE
    assert Invoice.objects.get().status == Invoice.Status.PAID


def test_retry_job_only_picks_due_invoices(org, invoice):
    services.set_payment_method(org, "pm_card_declined")
    now = timezone.now()
    attempt_payment(invoice.pk, now=now)
    services.set_payment_method(org, "pm_card_visa")

    assert retry_due_payments(now=now + timedelta(hours=12)) == 0
    assert retry_due_payments(now=now + timedelta(days=1, minutes=1)) == 1
    assert Invoice.objects.get().status == Invoice.Status.PAID


def test_paid_invoice_is_not_charged_again(org, invoice):
    services.set_payment_method(org, "pm_card_visa")
    attempt_payment(invoice.pk)

    assert attempt_payment(invoice.pk) is None
    assert Payment.objects.count() == 1


def test_no_payment_method(invoice):
    with pytest.raises(PaymentError, match="No payment method"):
        attempt_payment(invoice.pk)


def test_invoice_is_charged_automatically_when_card_on_file(
    org, django_capture_on_commit_callbacks
):
    services.set_payment_method(org, "pm_card_visa")
    billing.subscribe(organization=org, plan=PlanFactory(code="pro", amount=4900))

    with django_capture_on_commit_callbacks(execute=True):
        invoice = create_invoice(org)

    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.PAID


def test_unknown_token_rejected(org):
    with pytest.raises(PaymentError):
        services.set_payment_method(org, "pm_card_fake")


# --- API --------------------------------------------------------------------------------


def test_set_and_read_payment_method(member_client, org):
    url = reverse("payment-method-list", kwargs={"org_slug": org.slug})
    billing_client = member_client(Role.BILLING)

    created = billing_client.post(url, {"token": "pm_card_visa"}, format="json")
    read = member_client(Role.MEMBER).get(url)

    assert created.status_code == 201
    assert read.json() == {
        "brand": "visa",
        "last4": "4242",
        "updated_at": read.json()["updated_at"],
    }
    assert "token" not in read.json()


def test_member_cannot_change_payment_method(member_client, org):
    url = reverse("payment-method-list", kwargs={"org_slug": org.slug})

    assert member_client(Role.MEMBER).post(url, {"token": "pm_card_visa"}).status_code == 403


def test_manual_pay_endpoint(member_client, org, invoice):
    services.set_payment_method(org, "pm_card_visa")
    url = reverse("payment-pay", kwargs={"org_slug": org.slug, "number": invoice.number})

    response = member_client(Role.BILLING).post(url)
    again = member_client(Role.BILLING).post(url)

    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
    assert again.status_code == 409
