from django.dispatch import receiver

from .signals import invoice_finalized
from .tasks import email_invoice


@receiver(invoice_finalized, dispatch_uid="invoicing.email_invoice")
def send_invoice_email(sender, invoice, **kwargs) -> None:
    email_invoice.delay(invoice.pk)
