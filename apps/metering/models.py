from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.organizations.models import Organization

DEFAULT_METRIC = "api_calls"


class UsageRecord(models.Model):
    """One usage event reported by a tenant's backend.

    ``idempotency_key`` is unique per organization, so a client that retries a
    request after a timeout can never double-count usage.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="usage_records"
    )
    metric = models.CharField(max_length=40, default=DEFAULT_METRIC)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    idempotency_key = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"], name="unique_usage_idempotency_key"
            ),
        ]
        indexes = [models.Index(fields=["organization", "metric", "timestamp"])]

    def __str__(self) -> str:
        return f"{self.organization} {self.metric} +{self.quantity}"
