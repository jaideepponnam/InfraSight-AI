from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from infrasight.analytics.schemas import (
    AnalyticsReport,
    Comparison,
    Scope,
    Underutilization,
    Window,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "fields",
    [
        {"as_of": "2026-01-01T00:00:00"},
        {"freshness_seconds": 0},
        {"limit": 101},
        {"source_id": " "},
        {"environment": "unknown"},
        {"arbitrary_sql": "SELECT 1"},
    ],
)
def test_invalid_scope(fields):
    with pytest.raises(ValidationError):
        Scope(**fields)


@pytest.mark.parametrize(
    "start,end",
    [
        (START, START),
        (START + timedelta(minutes=1), START),
        (START, START + timedelta(days=8)),
    ],
)
def test_bounded_window(start, end):
    with pytest.raises(ValidationError):
        Window(start=start, end=end, as_of=START + timedelta(days=10))


def test_window_must_end_by_reference():
    with pytest.raises(ValidationError):
        Window(start=START, end=START + timedelta(minutes=1), as_of=START)


def test_comparison_requires_nonoverlapping_equal_periods():
    with pytest.raises(ValidationError):
        Comparison(
            as_of=START + timedelta(days=3),
            current_start=START,
            current_end=START + timedelta(days=2),
            previous_start=START - timedelta(days=1),
            previous_end=START,
        )
    with pytest.raises(ValidationError):
        Comparison(
            as_of=START + timedelta(days=3),
            current_start=START,
            current_end=START + timedelta(days=1),
            previous_start=START - timedelta(hours=1),
            previous_end=START + timedelta(hours=23),
        )


def test_unknown_currency_and_nonfinite_policy_rejected():
    values = dict(start=START, end=START + timedelta(minutes=1), as_of=START + timedelta(minutes=1))
    with pytest.raises(ValidationError):
        Window(**values, currency="usd")
    with pytest.raises(ValidationError):
        Underutilization(**values, min_cost=Decimal("NaN"))


def test_money_serializes_as_precise_decimal_string():
    report = AnalyticsReport(
        reference_time=START, rows=[{"cost": Decimal("0.00001234")}], parameters={}
    )
    assert '"0.00001234"' in report.model_dump_json()
