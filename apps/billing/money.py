"""Money and billing-period helpers.

All amounts are integer minor units (cents). Fractions are computed with
``Decimal`` and rounded half-up exactly once, at the end, so proration never
accumulates floating-point error.
"""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta


def round_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def prorate(amount: int, period_start: datetime, period_end: datetime, at: datetime) -> int:
    """Portion of ``amount`` covering ``[at, period_end)`` of the period."""
    total = Decimal((period_end - period_start).total_seconds())
    remaining = Decimal(max((period_end - at).total_seconds(), 0))
    if total <= 0:
        return 0
    return round_cents(Decimal(amount) * remaining / total)


def add_interval(anchor: datetime, interval: str, count: int) -> datetime:
    """``anchor`` plus ``count`` billing intervals.

    Always computed from the original anchor so month-end dates don't drift:
    Jan 31 -> Feb 28 -> Mar 31 (not Mar 28).
    """
    if interval == "month":
        return anchor + relativedelta(months=count)
    if interval == "year":
        return anchor + relativedelta(years=count)
    raise ValueError(f"Unknown interval: {interval}")


def next_period_end(anchor: datetime, interval: str, current_end: datetime) -> datetime:
    count = 1
    while add_interval(anchor, interval, count) <= current_end:
        count += 1
    return add_interval(anchor, interval, count)


def format_money(amount: int, currency: str) -> str:
    sign = "-" if amount < 0 else ""
    return f"{sign}{abs(amount) / 100:,.2f} {currency.upper()}"
