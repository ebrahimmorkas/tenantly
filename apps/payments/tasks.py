from contextlib import suppress

from celery import shared_task

from .services import PaymentError, attempt_payment, retry_due_payments


@shared_task
def charge_invoice(invoice_id: int) -> None:
    # No card on file: the invoice simply stays open until the customer pays.
    with suppress(PaymentError):
        attempt_payment(invoice_id)


@shared_task
def retry_failed_payments() -> int:
    return retry_due_payments()
