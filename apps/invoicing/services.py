"""Invoice creation and the periodic billing run.

Billing model: the flat plan fee is charged in advance, metered overage in
arrears. At the end of each period the billing run, for every due subscription:

1. bills usage above the allowance for the period that just ended,
2. renews the subscription (fee for the new period, scheduled downgrade,
   end of trial, or cancellation),
3. collects every pending :class:`InvoiceItem` of the organization into one invoice.

Each subscription is processed in its own transaction and ``renew`` moves the
period forward, so running the job twice (or concurrently) never bills twice.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.billing import services as billing
from apps.billing.models import InvoiceItem, Subscription
from apps.metering.services import overage, usage_between

from .models import Invoice, InvoiceSequence
from .signals import invoice_finalized

logger = logging.getLogger(__name__)


def next_invoice_number(organization) -> str:
    sequence, _ = InvoiceSequence.objects.select_for_update().get_or_create(
        organization=organization
    )
    sequence.last_number += 1
    sequence.save(update_fields=["last_number"])
    prefix = organization.slug.upper().replace("-", "")[:8]
    return f"{prefix}-{sequence.last_number:05d}"


@transaction.atomic
def create_invoice(organization, *, subscription: Subscription | None = None, now=None):
    """Invoice all pending items of an organization. Returns ``None`` if nothing is pending."""
    now = now or timezone.now()
    items = list(
        InvoiceItem.objects.select_for_update()
        .filter(organization=organization, invoice__isnull=True)
        .order_by("created_at", "id")
    )
    if not items:
        return None

    currency = items[0].currency
    if subscription is None:
        subscription = next((i.subscription for i in items if i.subscription_id), None)
    subtotal = sum(item.amount for item in items)
    total = max(subtotal, 0)

    invoice = Invoice.objects.create(
        organization=organization,
        subscription=subscription,
        number=next_invoice_number(organization),
        currency=currency,
        subtotal=subtotal,
        total=total,
        period_start=min((i.period_start for i in items if i.period_start), default=None),
        period_end=max((i.period_end for i in items if i.period_end), default=None),
        issued_at=now,
        due_at=now + timedelta(days=settings.TENANTLY_INVOICE_DUE_DAYS),
    )
    InvoiceItem.objects.filter(pk__in=[i.pk for i in items]).update(invoice=invoice)

    if subtotal < 0:
        # More credit than charges: carry the remainder to the next invoice.
        InvoiceItem.objects.create(
            organization=organization,
            subscription=subscription,
            kind=InvoiceItem.Kind.CREDIT,
            description=f"Credit carried forward from {invoice.number}",
            unit_amount=subtotal,
            amount=subtotal,
            currency=currency,
        )
    if total == 0:
        invoice.status = Invoice.Status.PAID
        invoice.paid_at = now
        invoice.save(update_fields=["status", "paid_at", "updated_at"])

    transaction.on_commit(lambda: invoice_finalized.send(sender=Invoice, invoice=invoice))
    logger.info("Created invoice %s for %s (%s)", invoice.number, organization, total)
    return invoice


def _bill_usage(subscription: Subscription) -> None:
    plan = subscription.plan
    start, end = subscription.current_period_start, subscription.current_period_end
    used = usage_between(subscription.organization, start, end)
    blocks, amount = overage(plan, used)
    if amount:
        InvoiceItem.objects.create(
            organization=subscription.organization,
            subscription=subscription,
            kind=InvoiceItem.Kind.USAGE,
            description=(
                f"Usage overage: {used - plan.included_units:,} units above "
                f"{plan.included_units:,} included ({blocks} x {plan.overage_unit_size:,})"
            ),
            quantity=blocks,
            unit_amount=plan.overage_unit_amount,
            amount=amount,
            currency=plan.currency,
            period_start=start,
            period_end=end,
        )


@transaction.atomic
def bill_subscription(subscription: Subscription, now: datetime | None = None):
    now = now or timezone.now()
    subscription = (
        Subscription.objects.select_for_update()
        .select_related("plan", "organization")
        .get(pk=subscription.pk)
    )
    if not subscription.is_live or subscription.current_period_end > now:
        return None  # already processed by a concurrent or earlier run

    if subscription.status != Subscription.Status.TRIALING:
        _bill_usage(subscription)
    subscription = billing.renew(subscription=subscription, now=now)
    return create_invoice(subscription.organization, subscription=subscription, now=now)


def run_billing_cycle(now: datetime | None = None) -> int:
    now = now or timezone.now()
    due = Subscription.objects.filter(
        status__in=[
            Subscription.Status.ACTIVE,
            Subscription.Status.TRIALING,
            Subscription.Status.PAST_DUE,
        ],
        current_period_end__lte=now,
    ).values_list("pk", flat=True)

    invoices = 0
    for pk in due:
        subscription = Subscription.objects.get(pk=pk)
        # A subscription several periods behind (e.g. the job was down) catches up one
        # period per iteration so every period gets its own invoice.
        while subscription.is_live and subscription.current_period_end <= now:
            if bill_subscription(subscription, now=now):
                invoices += 1
            subscription.refresh_from_db()
    return invoices


def upcoming_invoice(organization) -> dict | None:
    """Preview of the next invoice: pending items plus projected usage overage."""
    subscription = (
        Subscription.objects.filter(organization=organization)
        .exclude(status=Subscription.Status.CANCELED)
        .select_related("plan")
        .first()
    )
    if subscription is None:
        return None
    plan = subscription.plan
    pending = InvoiceItem.objects.filter(organization=organization, invoice__isnull=True)
    lines = [
        {"kind": item.kind, "description": item.description, "amount": item.amount}
        for item in pending
    ]
    if subscription.status != Subscription.Status.TRIALING:
        used = usage_between(
            organization, subscription.current_period_start, subscription.current_period_end
        )
        _, overage_amount = overage(plan, used)
        if overage_amount:
            lines.append(
                {
                    "kind": "usage",
                    "description": "Projected usage overage",
                    "amount": overage_amount,
                }
            )
    if not subscription.cancel_at_period_end:
        next_plan = subscription.pending_plan or plan
        lines.append(
            {
                "kind": "subscription",
                "description": f"{next_plan.name} (next period)",
                "amount": next_plan.amount,
            }
        )
    return {
        "currency": plan.currency,
        "billing_date": subscription.current_period_end,
        "lines": lines,
        "total": max(sum(line["amount"] for line in lines), 0),
    }


def outstanding_balance(organization) -> int:
    open_invoices = Invoice.objects.filter(organization=organization, status=Invoice.Status.OPEN)
    totals = open_invoices.aggregate(total=Sum("total"), paid=Sum("amount_paid"))
    return (totals["total"] or 0) - (totals["paid"] or 0)
