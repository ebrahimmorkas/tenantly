"""Subscription lifecycle.

* **subscribe** - starts a trial (if the plan has one) or bills the first period.
* **change_plan** - upgrades apply immediately with proration (credit for the
  unused part of the old price, charge for the rest of the period at the new
  price); downgrades are scheduled for the end of the period, which avoids
  issuing refunds.
* **cancel / resume** - cancel now or at period end.
* **renew** - roll a subscription into its next period (called by the billing run).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import InvoiceItem, Plan, Subscription
from .money import add_interval, format_money, next_period_end, prorate


class BillingError(Exception):
    """A billing rule was violated. The message is safe to show to API clients."""


@dataclass(frozen=True)
class ProrationLine:
    description: str
    amount: int


def _fee_item(subscription: Subscription, plan: Plan, start, end) -> InvoiceItem:
    return InvoiceItem.objects.create(
        organization=subscription.organization,
        subscription=subscription,
        kind=InvoiceItem.Kind.SUBSCRIPTION,
        description=f"{plan.name} ({start:%b %d, %Y} - {end:%b %d, %Y})",
        unit_amount=plan.amount,
        amount=plan.amount,
        currency=plan.currency,
        period_start=start,
        period_end=end,
    )


@transaction.atomic
def subscribe(*, organization, plan: Plan, now: datetime | None = None) -> Subscription:
    now = now or timezone.now()
    if not plan.is_active:
        raise BillingError("This plan is no longer available.")
    if plan.currency != organization.currency:
        raise BillingError(f"This plan is billed in {plan.currency.upper()}.")

    if plan.trial_days:
        trial_end = now + timedelta(days=plan.trial_days)
        fields = {
            "status": Subscription.Status.TRIALING,
            "billing_anchor": trial_end,
            "current_period_start": now,
            "current_period_end": trial_end,
            "trial_end": trial_end,
        }
    else:
        fields = {
            "status": Subscription.Status.ACTIVE,
            "billing_anchor": now,
            "current_period_start": now,
            "current_period_end": add_interval(now, plan.interval, 1),
        }

    try:
        with transaction.atomic():
            subscription = Subscription.objects.create(
                organization=organization, plan=plan, **fields
            )
    except IntegrityError:
        raise BillingError("This organization already has a subscription.") from None

    if subscription.status == Subscription.Status.ACTIVE:
        _fee_item(
            subscription, plan, subscription.current_period_start, subscription.current_period_end
        )
    return subscription


def preview_change(
    subscription: Subscription, new_plan: Plan, now: datetime | None = None
) -> tuple[str, list[ProrationLine]]:
    """Return ``("immediate" | "scheduled", lines)`` without changing anything."""
    now = now or timezone.now()
    _validate_change(subscription, new_plan)
    old = subscription.plan

    if subscription.status == Subscription.Status.TRIALING:
        return "immediate", []
    if new_plan.amount <= old.amount:
        return "scheduled", []

    start, end = subscription.current_period_start, subscription.current_period_end
    credit = prorate(old.amount, start, end, now)
    charge = prorate(new_plan.amount, start, end, now)
    return "immediate", [
        ProrationLine(f"Unused time on {old.name}", -credit),
        ProrationLine(f"Remaining time on {new_plan.name}", charge),
    ]


@transaction.atomic
def change_plan(
    *, subscription: Subscription, new_plan: Plan, now: datetime | None = None
) -> tuple[str, list[ProrationLine]]:
    now = now or timezone.now()
    subscription = (
        Subscription.objects.select_for_update().select_related("plan").get(pk=subscription.pk)
    )
    mode, lines = preview_change(subscription, new_plan, now)

    if mode == "scheduled":
        subscription.pending_plan = new_plan
        subscription.save(update_fields=["pending_plan", "updated_at"])
        return mode, lines

    for line in lines:
        InvoiceItem.objects.create(
            organization=subscription.organization,
            subscription=subscription,
            kind=InvoiceItem.Kind.PRORATION,
            description=line.description,
            unit_amount=line.amount,
            amount=line.amount,
            currency=new_plan.currency,
            period_start=now,
            period_end=subscription.current_period_end,
        )
    subscription.plan = new_plan
    subscription.pending_plan = None
    subscription.save(update_fields=["plan", "pending_plan", "updated_at"])
    return mode, lines


def _validate_change(subscription: Subscription, new_plan: Plan) -> None:
    if not subscription.is_live:
        raise BillingError("Canceled subscriptions cannot change plans.")
    if not new_plan.is_active:
        raise BillingError("This plan is no longer available.")
    if new_plan.pk == subscription.plan_id:
        raise BillingError("Already on this plan.")
    old = subscription.plan
    if (new_plan.interval, new_plan.currency) != (old.interval, old.currency):
        raise BillingError("Plans must share the same billing interval and currency.")


@transaction.atomic
def cancel(*, subscription: Subscription, at_period_end: bool = True, now=None) -> Subscription:
    now = now or timezone.now()
    if not subscription.is_live:
        raise BillingError("Subscription is already canceled.")
    if at_period_end and subscription.status != Subscription.Status.TRIALING:
        subscription.cancel_at_period_end = True
        subscription.save(update_fields=["cancel_at_period_end", "updated_at"])
    else:
        subscription.status = Subscription.Status.CANCELED
        subscription.canceled_at = now
        subscription.save(update_fields=["status", "canceled_at", "updated_at"])
    return subscription


def resume(*, subscription: Subscription) -> Subscription:
    if not subscription.is_live:
        raise BillingError("Canceled subscriptions cannot be resumed; subscribe again.")
    subscription.cancel_at_period_end = False
    subscription.save(update_fields=["cancel_at_period_end", "updated_at"])
    return subscription


@transaction.atomic
def renew(*, subscription: Subscription, now: datetime | None = None) -> Subscription:
    """Move a subscription whose period has ended into the next period.

    Applies a scheduled downgrade, ends trials, honours ``cancel_at_period_end``
    and creates the in-advance fee for the new period.
    """
    now = now or timezone.now()
    subscription = (
        Subscription.objects.select_for_update().select_related("plan").get(pk=subscription.pk)
    )
    if not subscription.is_live or subscription.current_period_end > now:
        return subscription

    if subscription.cancel_at_period_end:
        subscription.status = Subscription.Status.CANCELED
        subscription.canceled_at = subscription.current_period_end
        subscription.save(update_fields=["status", "canceled_at", "updated_at"])
        return subscription

    if subscription.pending_plan_id:
        subscription.plan = subscription.pending_plan
        subscription.pending_plan = None

    start = subscription.current_period_end
    end = next_period_end(subscription.billing_anchor, subscription.plan.interval, start)
    if subscription.status == Subscription.Status.TRIALING:
        subscription.status = Subscription.Status.ACTIVE
    subscription.current_period_start, subscription.current_period_end = start, end
    subscription.save()
    _fee_item(subscription, subscription.plan, start, end)
    return subscription


def describe(lines: list[ProrationLine], currency: str) -> list[dict]:
    return [
        {
            "description": line.description,
            "amount": line.amount,
            "display": format_money(line.amount, currency),
        }
        for line in lines
    ]
