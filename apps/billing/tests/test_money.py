from datetime import UTC, datetime

import pytest

from apps.billing.money import add_interval, format_money, next_period_end, prorate


def dt(*args):
    return datetime(*args, tzinfo=UTC)


def test_prorate_half_period():
    assert prorate(3000, dt(2026, 4, 1), dt(2026, 5, 1), dt(2026, 4, 16)) == 1500


def test_prorate_rounds_half_up_once():
    # 1000 * 1/3 = 333.33 -> 333 ; 1000 * 2/3 = 666.67 -> 667
    start, end = dt(2026, 1, 1), dt(2026, 1, 4)
    assert prorate(1000, start, end, dt(2026, 1, 3)) == 333
    assert prorate(1000, start, end, dt(2026, 1, 2)) == 667


def test_prorate_outside_period():
    start, end = dt(2026, 1, 1), dt(2026, 2, 1)
    assert prorate(1000, start, end, dt(2026, 3, 1)) == 0
    assert prorate(1000, start, end, start) == 1000


@pytest.mark.parametrize(
    ("count", "expected"),
    [(1, dt(2026, 2, 28)), (2, dt(2026, 3, 31)), (3, dt(2026, 4, 30)), (12, dt(2027, 1, 31))],
)
def test_month_end_anchor_does_not_drift(count, expected):
    assert add_interval(dt(2026, 1, 31), "month", count) == expected


def test_next_period_end_from_anchor():
    anchor = dt(2026, 1, 31)

    assert next_period_end(anchor, "month", dt(2026, 2, 28)) == dt(2026, 3, 31)
    assert next_period_end(anchor, "year", dt(2026, 1, 31)) == dt(2027, 1, 31)


def test_format_money():
    assert format_money(123456, "usd") == "1,234.56 USD"
    assert format_money(-250, "eur") == "-2.50 EUR"
