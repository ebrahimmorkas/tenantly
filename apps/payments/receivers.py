from django.dispatch import receiver

from apps.invoicing.models import Invoice
from apps.invoicing.signals import invoice_finalized

from .tasks import charge_invoice


@receiver(invoice_finalized, dispatch_uid="payments.auto_charge")
def auto_charge(sender, invoice, **kwargs) -> None:
    if invoice.status == Invoice.Status.OPEN:
        charge_invoice.delay(invoice.pk)
