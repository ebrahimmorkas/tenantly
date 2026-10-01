from django.db import models

from apps.core.models import TimeStampedModel
from apps.invoicing.models import Invoice
from apps.organizations.models import Organization


class PaymentMethod(TimeStampedModel):
    """The organization's default card, stored as a gateway token (never raw card data)."""

    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name="payment_method"
    )
    gateway_token = models.CharField(max_length=120)
    brand = models.CharField(max_length=20)
    last4 = models.CharField(max_length=4)

    def __str__(self) -> str:
        return f"{self.brand} •••• {self.last4}"


class Payment(models.Model):
    class Status(models.TextChoices):
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    amount = models.PositiveIntegerField()
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=10, choices=Status.choices)
    gateway_reference = models.CharField(max_length=120, blank=True)
    failure_reason = models.CharField(max_length=120, blank=True)
    attempt = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.invoice.number} attempt {self.attempt}: {self.status}"
