"""Collecting payments and dunning.

* Invoices are charged automatically when finalized (if a card is on file).
* A failed charge marks the subscription ``past_due`` and schedules a retry
  according to ``TENANTLY_DUNNING_SCHEDULE_DAYS`` (default 1, 3 and 5 days).
* When every retry fails the invoice becomes ``uncollectible`` and the
  subscription is canceled.
* The gateway idempotency key is ``<invoice number>-<attempt>``, so a crashed
  worker re-running the same attempt can never charge the card twice.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.billing.models import Subscription
from apps.invoicing.models import Invoice
from apps.invoicing.signals import invoice_paid, invoice_payment_failed

from .gateways import get_gateway
from .models import Payment, PaymentMethod

logger = logging.getLogger(__name__)


class PaymentError(Exception):
    pass


def set_payment_method(organization, token: str) -> PaymentMethod:
    try:
        card = get_gateway().describe(token)
    except ValueError as exc:
        raise PaymentError(str(exc)) from exc
    method, _ = PaymentMethod.objects.update_or_create(
        organization=organization,
        defaults={"gateway_token": token, "brand": card.brand, "last4": card.last4},
    )
    return method


@transaction.atomic
def attempt_payment(invoice_id: int, now=None) -> Payment | None:
    now = now or timezone.now()
    invoice = (
        Invoice.objects.select_for_update()
        .select_related("organization", "subscription")
        .get(pk=invoice_id)
    )
    if invoice.status != Invoice.Status.OPEN or invoice.amount_due == 0:
        return None
    method = PaymentMethod.objects.filter(organization=invoice.organization).first()
    if method is None:
        raise PaymentError("No payment method on file.")

    attempt = invoice.attempt_count + 1
    result = get_gateway().charge(
        token=method.gateway_token,
        amount=invoice.amount_due,
        currency=invoice.currency,
        idempotency_key=f"{invoice.number}-{attempt}",
    )
    payment = Payment.objects.create(
        invoice=invoice,
        amount=invoice.amount_due,
        currency=invoice.currency,
        status=Payment.Status.SUCCEEDED if result.success else Payment.Status.FAILED,
        gateway_reference=result.reference,
        failure_reason=result.failure_reason,
        attempt=attempt,
    )
    invoice.attempt_count = attempt

    if result.success:
        _mark_paid(invoice, now)
    else:
        _handle_failure(invoice, attempt, now)
    return payment


def _mark_paid(invoice: Invoice, now) -> None:
    invoice.status = Invoice.Status.PAID
    invoice.amount_paid = invoice.total
    invoice.paid_at = now
    invoice.next_payment_attempt = None
    invoice.save()
    subscription = invoice.subscription
    if subscription and subscription.status == Subscription.Status.PAST_DUE:
        subscription.status = Subscription.Status.ACTIVE
        subscription.save(update_fields=["status", "updated_at"])
    transaction.on_commit(lambda: invoice_paid.send(sender=Invoice, invoice=invoice))


def _handle_failure(invoice: Invoice, attempt: int, now) -> None:
    schedule = settings.TENANTLY_DUNNING_SCHEDULE_DAYS
    subscription = invoice.subscription

    if attempt <= len(schedule):
        invoice.next_payment_attempt = now + timedelta(days=schedule[attempt - 1])
        if subscription and subscription.is_live:
            subscription.status = Subscription.Status.PAST_DUE
            subscription.save(update_fields=["status", "updated_at"])
    else:
        logger.warning("Invoice %s is uncollectible after %s attempts", invoice.number, attempt)
        invoice.status = Invoice.Status.UNCOLLECTIBLE
        invoice.next_payment_attempt = None
        if subscription and subscription.is_live:
            subscription.status = Subscription.Status.CANCELED
            subscription.canceled_at = now
            subscription.save(update_fields=["status", "canceled_at", "updated_at"])
    invoice.save()
    transaction.on_commit(
        lambda: invoice_payment_failed.send(sender=Invoice, invoice=invoice, attempt=attempt)
    )


def retry_due_payments(now=None) -> int:
    now = now or timezone.now()
    due = Invoice.objects.filter(
        status=Invoice.Status.OPEN, next_payment_attempt__lte=now
    ).values_list("pk", flat=True)
    count = 0
    for pk in due:
        try:
            if attempt_payment(pk, now=now):
                count += 1
        except PaymentError:
            logger.info("Skipping retry for invoice %s: no payment method", pk)
    return count
