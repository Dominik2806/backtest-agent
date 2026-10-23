"""The formats of docs/report.md ("Formats"): literal input and output pairs, and the guards."""

import math
import re
from datetime import date, datetime, timedelta, timezone

import pytest

from backtest_agent.reporting import format as fmt


@pytest.mark.parametrize(
    "value, text",
    [
        (0.17128, "17.13%"),
        (-0.12, "-12.00%"),
        (0.0, "0.00%"),
        (1.0, "100.00%"),
        (12.345, "1,234.50%"),
        (-0.00001, "0.00%"),  # rounds to zero: no "-0.00%"
        (0.000049, "0.00%"),
        (-0.0, "0.00%"),
        (0.00005, "0.01%"),
        (None, "n/a"),
    ],
)
def test_percent(value, text) -> None:
    assert fmt.percent(value, "x") == text


@pytest.mark.parametrize(
    "value, text",
    [(0.012, "+1.20%"), (-0.012, "-1.20%"), (0.0, "0.00%"), (-0.00001, "0.00%"), (0.00001, "0.00%"), (None, "n/a")],
)
def test_signed_percent(value, text) -> None:
    assert fmt.percent(value, "x", signed=True) == text


@pytest.mark.parametrize(
    "value, text",
    [(0.826767, "0.83"), (-1.5, "-1.50"), (1.0, "1.00"), (-0.001, "0.00"), (1234.5, "1,234.50"), (None, "n/a")],
)
def test_ratio(value, text) -> None:
    assert fmt.ratio(value, "x") == text


@pytest.mark.parametrize(
    "value, text", [(100000, "100,000.00"), (1171.28, "1,171.28"), (0.0, "0.00"), (-5.5, "-5.50"), (None, "n/a")]
)
def test_money(value, text) -> None:
    assert fmt.money(value, "x") == text


@pytest.mark.parametrize(
    "value, text", [(1.0, "1 bps"), (2.5, "2.5 bps"), (0.0, "0 bps"), (1000.0, "1,000 bps"), (0.25, "0.25 bps")]
)
def test_bps(value, text) -> None:
    assert fmt.bps(value, "x") == text


def test_integer_and_dates_and_timestamps() -> None:
    assert fmt.integer(1234567, "x") == "1,234,567"
    assert fmt.integer(0, "x") == "0"
    assert fmt.integer(None, "x") == "n/a"
    assert fmt.iso_date(date(2024, 1, 3), "x") == "2024-01-03"
    assert fmt.iso_date("2024-01-03", "x") == "2024-01-03"
    assert fmt.iso_date(None, "x") == "n/a"
    assert fmt.utc_timestamp(datetime(2026, 1, 15, 12, 30, 5, tzinfo=timezone(timedelta(hours=2)))) == (
        "2026-01-15 10:30:05 UTC"
    )
    assert fmt.na("gross return is not positive") == "n/a (gross return is not positive)"
    assert fmt.na() == "n/a"


@pytest.mark.parametrize("function", [fmt.percent, fmt.ratio, fmt.money, fmt.number, fmt.bps])
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_nan_and_infinity_raise_and_name_the_field(function, bad) -> None:
    with pytest.raises(ValueError, match="my_field"):
        function(bad, "my_field")


@pytest.mark.parametrize("bad", ["0.5", True, [1.0]])
def test_non_numbers_raise(bad) -> None:
    with pytest.raises(ValueError, match="my_field"):
        fmt.percent(bad, "my_field")


def test_integer_rejects_bool_and_float() -> None:
    for bad in (True, 1.5):
        with pytest.raises(ValueError, match="my_field"):
            fmt.integer(bad, "my_field")


def test_a_naive_timestamp_and_a_datetime_as_date_raise() -> None:
    with pytest.raises(ValueError, match="generated_at"):
        fmt.utc_timestamp(datetime(2026, 1, 15, 12, 0, 0))
    with pytest.raises(ValueError, match="my_field"):
        fmt.iso_date(datetime(2026, 1, 15), "my_field")


def test_no_format_ever_prints_nan_none_or_a_raw_repr() -> None:
    values = [0.1 + 0.2, 1 / 3, 1e-20, 1e20, -1e-9, 123456789.123456789]
    for value in values:
        for text in (fmt.percent(value, "x"), fmt.ratio(value, "x"), fmt.money(value, "x"), fmt.bps(value, "x")):
            assert re.fullmatch(r"-?[\d,]+(\.\d{1,2})?( bps|%)?", text), text
