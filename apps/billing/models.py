from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel
from apps.organizations.models import Organization


class Plan(TimeStampedModel):
    """A price in the public catalog.

    Billing model: the flat ``amount`` is charged **in advance** for each period;
    usage above ``included_units`` is charged **in arrears** at
    ``overage_unit_amount`` cents per ``overage_unit_size`` units.
    """

    class Interval(models.TextChoices):
        MONTH = "month", "Monthly"
        YEAR = "year", "Yearly"

    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=255, blank=True)
    amount = models.PositiveIntegerField(help_text="Price per interval, in cents.")
    currency = models.CharField(max_length=3, default="usd")
    interval = models.CharField(max_length=5, choices=Interval.choices, default=Interval.MONTH)
    trial_days = models.PositiveSmallIntegerField(default=0)
    included_units = models.PositiveIntegerField(default=0)
    overage_unit_amount = models.PositiveIntegerField(default=0, help_text="Cents per unit block.")
    overage_unit_size = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    features = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "amount"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Subscription(TimeStampedModel):
    class Status(models.TextChoices):
        TRIALING = "trialing", "Trialing"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past due"
        CANCELED = "canceled", "Canceled"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="subscriptions"
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=10, choices=Status.choices)
    billing_anchor = models.DateTimeField(help_text="Periods are computed from this instant.")
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()
    trial_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    canceled_at = models.DateTimeField(null=True, blank=True)
    pending_plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="Downgrade that takes effect at the next renewal.",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization"],
                condition=~Q(status="canceled"),
                name="one_live_subscription_per_org",
            ),
        ]
        indexes = [models.Index(fields=["status", "current_period_end"])]

    def __str__(self) -> str:
        return f"{self.organization} on {self.plan.code} ({self.status})"

    @property
    def is_live(self) -> bool:
        return self.status != self.Status.CANCELED


class InvoiceItem(TimeStampedModel):
    """A billable line waiting to be invoiced (or already attached to an invoice)."""

    class Kind(models.TextChoices):
        SUBSCRIPTION = "subscription", "Subscription fee"
        PRORATION = "proration", "Proration"
        USAGE = "usage", "Usage"
        CREDIT = "credit", "Credit"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="invoice_items"
    )
    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, null=True, blank=True, related_name="items"
    )
    kind = models.CharField(max_length=12, choices=Kind.choices)
    description = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField(default=1)
    unit_amount = models.IntegerField()
    amount = models.IntegerField(help_text="Cents; negative for credits.")
    currency = models.CharField(max_length=3)
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"{self.description}: {self.amount}"
