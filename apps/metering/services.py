import math
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.billing.models import Plan

from .models import DEFAULT_METRIC, UsageRecord

MAX_CLOCK_SKEW = timedelta(minutes=5)
MAX_BACKDATE = timedelta(days=35)


class UsageError(Exception):
    pass


def record_usage(
    *,
    organization,
    quantity: int,
    idempotency_key: str,
    metric: str = DEFAULT_METRIC,
    timestamp: datetime | None = None,
) -> tuple[UsageRecord, bool]:
    """Store a usage event. Returns ``(record, created)``.

    Re-sending the same ``idempotency_key`` returns the original record. Sending
    the same key with a *different* payload is an error (it indicates a client bug).
    """
    now = timezone.now()
    timestamp = timestamp or now
    if timestamp > now + MAX_CLOCK_SKEW:
        raise UsageError("timestamp cannot be in the future.")
    if timestamp < now - MAX_BACKDATE:
        raise UsageError("timestamp is too far in the past.")

    existing = UsageRecord.objects.filter(
        organization=organization, idempotency_key=idempotency_key
    ).first()
    if existing is None:
        try:
            with transaction.atomic():
                return (
                    UsageRecord.objects.create(
                        organization=organization,
                        metric=metric,
                        quantity=quantity,
                        timestamp=timestamp,
                        idempotency_key=idempotency_key,
                    ),
                    True,
                )
        except IntegrityError:  # lost a race with a concurrent retry
            existing = UsageRecord.objects.get(
                organization=organization, idempotency_key=idempotency_key
            )

    if (existing.metric, existing.quantity) != (metric, quantity):
        raise UsageError("idempotency_key was already used with a different payload.")
    return existing, False


def usage_between(organization, start: datetime, end: datetime, metric=DEFAULT_METRIC) -> int:
    total = UsageRecord.objects.filter(
        organization=organization, metric=metric, timestamp__gte=start, timestamp__lt=end
    ).aggregate(total=Sum("quantity"))["total"]
    return total or 0


def overage(plan: Plan, units: int) -> tuple[int, int]:
    """Return ``(billable_blocks, amount_in_cents)`` for usage beyond the plan allowance."""
    extra = max(units - plan.included_units, 0)
    if extra == 0 or plan.overage_unit_amount == 0:
        return 0, 0
    blocks = math.ceil(extra / plan.overage_unit_size)
    return blocks, blocks * plan.overage_unit_amount
