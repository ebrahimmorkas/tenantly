"""Translate internal domain signals into public webhook events."""

from django.dispatch import receiver

from apps.invoicing.signals import invoice_finalized, invoice_paid, invoice_payment_failed

from .models import EventType
from .services import publish


def invoice_data(invoice) -> dict:
    return {
        "number": invoice.number,
        "status": invoice.status,
        "currency": invoice.currency,
        "total": invoice.total,
        "amount_due": invoice.amount_due,
        "due_at": invoice.due_at,
    }


@receiver(invoice_finalized, dispatch_uid="webhooks.invoice_created")
def on_invoice_created(sender, invoice, **kwargs) -> None:
    publish(invoice.organization, EventType.INVOICE_CREATED, invoice_data(invoice))


@receiver(invoice_paid, dispatch_uid="webhooks.invoice_paid")
def on_invoice_paid(sender, invoice, **kwargs) -> None:
    publish(invoice.organization, EventType.INVOICE_PAID, invoice_data(invoice))


@receiver(invoice_payment_failed, dispatch_uid="webhooks.invoice_payment_failed")
def on_invoice_payment_failed(sender, invoice, attempt, **kwargs) -> None:
    data = invoice_data(invoice) | {"attempt": attempt}
    publish(invoice.organization, EventType.INVOICE_PAYMENT_FAILED, data)
