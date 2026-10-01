from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from apps.billing.money import format_money

from .models import Invoice
from .services import run_billing_cycle


@shared_task
def run_billing_cycle_task() -> int:
    return run_billing_cycle()


@shared_task(autoretry_for=(ConnectionError,), retry_backoff=True, retry_kwargs={"max_retries": 5})
def email_invoice(invoice_id: int) -> None:
    invoice = (
        Invoice.objects.select_related("organization")
        .prefetch_related("items")
        .filter(pk=invoice_id)
        .first()
    )
    if invoice is None:
        return
    body = render_to_string(
        "invoicing/invoice_email.txt",
        {
            "invoice": invoice,
            "lines": [
                (item, format_money(item.amount, item.currency)) for item in invoice.items.all()
            ],
            "total": format_money(invoice.total, invoice.currency),
        },
    )
    send_mail(
        f"Invoice {invoice.number} from Tenantly",
        body,
        settings.DEFAULT_FROM_EMAIL,
        [invoice.organization.billing_email],
    )
