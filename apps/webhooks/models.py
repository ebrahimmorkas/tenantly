import secrets

from django.db import models

from apps.core.models import TimeStampedModel
from apps.organizations.models import Organization


class EventType(models.TextChoices):
    INVOICE_CREATED = "invoice.created", "Invoice created"
    INVOICE_PAID = "invoice.paid", "Invoice paid"
    INVOICE_PAYMENT_FAILED = "invoice.payment_failed", "Invoice payment failed"
    PING = "ping", "Test ping"


def generate_secret() -> str:
    return f"whsec_{secrets.token_urlsafe(32)}"


class WebhookEndpoint(TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="webhook_endpoints"
    )
    url = models.URLField(max_length=500)
    description = models.CharField(max_length=120, blank=True)
    secret = models.CharField(max_length=80, default=generate_secret)
    events = models.JSONField(default=list, blank=True, help_text="Empty list = all events.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.url

    def wants(self, event_type: str) -> bool:
        return self.is_active and (not self.events or event_type in self.events)


class WebhookEvent(models.Model):
    """An immutable record of something that happened, delivered to every matching endpoint."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="webhook_events"
    )
    type = models.CharField(max_length=40, choices=EventType.choices)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"evt_{self.pk} {self.type}"


class WebhookDelivery(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    event = models.ForeignKey(WebhookEvent, on_delete=models.CASCADE, related_name="deliveries")
    endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    last_error = models.CharField(max_length=255, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["event", "endpoint"], name="one_delivery_per_endpoint"),
        ]

    def __str__(self) -> str:
        return f"{self.event} -> {self.endpoint} ({self.status})"
