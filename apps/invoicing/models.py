from django.db import models

from apps.billing.models import Subscription
from apps.core.models import TimeStampedModel
from apps.organizations.models import Organization


class Invoice(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        PAID = "paid", "Paid"
        VOID = "void", "Void"
        UNCOLLECTIBLE = "uncollectible", "Uncollectible"

    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="invoices"
    )
    subscription = models.ForeignKey(
        Subscription, on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices"
    )
    number = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.OPEN)
    currency = models.CharField(max_length=3)
    subtotal = models.IntegerField()
    total = models.IntegerField()
    amount_paid = models.IntegerField(default=0)
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)
    issued_at = models.DateTimeField()
    due_at = models.DateTimeField()
    paid_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    next_payment_attempt = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-issued_at", "-id"]
        indexes = [models.Index(fields=["organization", "status"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total__gte=0), name="invoice_total_not_negative"
            ),
        ]

    def __str__(self) -> str:
        return self.number

    @property
    def amount_due(self) -> int:
        return max(self.total - self.amount_paid, 0)


class InvoiceSequence(models.Model):
    """Per-organization counter for gapless, human-friendly invoice numbers."""

    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name="invoice_sequence"
    )
    last_number = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return f"{self.organization}: {self.last_number}"
