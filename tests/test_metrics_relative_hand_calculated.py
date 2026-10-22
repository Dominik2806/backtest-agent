"""Fixtures R1 and R2 of docs/metrics.md ("Benchmark fixtures R1 to R3"): relative metrics and the alignment.

The expected values are literals taken from that document; no test computes one with project code.
"""

import pandas as pd
import pytest

from backtest_agent.metrics import Alignment, MetricAssumptions, compare_equity, relative_from_returns

TOLERANCE = 1e-9
P4 = MetricAssumptions(periods_per_year=4)


def approx(value):
    return pytest.approx(value, rel=TOLERANCE, abs=TOLERANCE)


def series(dates: list[str], values: list[float]) -> pd.Series:
    return pd.Series(values, index=pd.DatetimeIndex(dates, name="date"), dtype="float64")


JAN = {d: f"2024-01-{d:02d}" for d in (2, 3, 4, 5, 8)}


def test_r1_pure_relative_numbers() -> None:
    dates = [JAN[d] for d in (2, 3, 4, 5, 8)]
    strategy = series(dates, [0.14, 0.16, 0.14, 0.16, 0.15])
    benchmark = series(dates, [0.10] * 5)
    excess, tracking_error, information = relative_from_returns(strategy, benchmark, P4)
    assert excess == approx(0.400543024)
    assert tracking_error == approx(0.02)
    assert information == approx(10.0)


def test_r1_needs_the_same_index() -> None:
    with pytest.raises(ValueError, match="same index"):
        relative_from_returns(series([JAN[2], JAN[3]], [0.1, 0.1]), series([JAN[3], JAN[4]], [0.1, 0.1]), P4)


def test_r1_with_fewer_than_two_observations_is_none() -> None:
    assert relative_from_returns(series([JAN[2]], [0.1]), series([JAN[2]], [0.05]), P4) == (None, None, None)
    empty = series([], [])
    assert relative_from_returns(empty, empty, P4) == (None, None, None)


def test_r2a_calendar_mismatch() -> None:
    strategy = series([JAN[2], JAN[3], JAN[4], JAN[5]], [1000, 1100, 1210, 1089])
    benchmark = series([JAN[3], JAN[4], JAN[5], JAN[8]], [1000, 1050, 1102.5, 1157.625])
    rel = compare_equity(strategy, 1000.0, benchmark, 1000.0, P4)
    assert rel.alignment == Alignment(
        n_strategy_bars=4,
        n_benchmark_bars=4,
        n_common=3,
        n_compared=2,
        n_dropped_strategy=1,
        n_dropped_benchmark=1,
        dates_dropped=True,
        insufficient_overlap=False,
        base="first_common_date",
        base_date="2024-01-03",
        first_compared_date="2024-01-04",
        last_compared_date="2024-01-05",
    )
    assert rel.strategy_return_compared == approx(-0.01)
    assert rel.benchmark_return_compared == approx(0.1025)
    assert rel.excess_return == approx(-0.1125)
    assert rel.tracking_error == approx(0.282842712475)
    assert rel.information_ratio == approx(-0.707106781187)


def test_r2b_fewer_than_two_observations_has_only_none_and_the_flags() -> None:
    strategy = series([JAN[2], JAN[3], JAN[4]], [1000, 1100, 1210])
    benchmark = series([JAN[3], JAN[4], JAN[5]], [1000, 1050, 1102.5])
    rel = compare_equity(strategy, 1000.0, benchmark, 1000.0, P4)
    assert rel.alignment == Alignment(
        n_strategy_bars=3,
        n_benchmark_bars=3,
        n_common=2,
        n_compared=1,
        n_dropped_strategy=1,
        n_dropped_benchmark=1,
        dates_dropped=True,
        insufficient_overlap=True,
        base="first_common_date",
        base_date="2024-01-03",
        first_compared_date="2024-01-04",
        last_compared_date="2024-01-04",
    )
    assert (rel.excess_return, rel.tracking_error, rel.information_ratio) == (None, None, None)
    assert (rel.strategy_return_compared, rel.benchmark_return_compared) == (None, None)


def test_r2b_prime_no_common_date_does_not_raise() -> None:
    strategy = series([JAN[2], JAN[3]], [1000, 1100])
    benchmark = series([JAN[4], JAN[5]], [1000, 1050])
    rel = compare_equity(strategy, 1000.0, benchmark, 1000.0, P4)
    assert rel.alignment == Alignment(
        n_strategy_bars=2,
        n_benchmark_bars=2,
        n_common=0,
        n_compared=0,
        n_dropped_strategy=2,
        n_dropped_benchmark=2,
        dates_dropped=True,
        insufficient_overlap=True,
        base="first_common_date",
        base_date=None,
        first_compared_date=None,
        last_compared_date=None,
    )
    assert (rel.excess_return, rel.tracking_error, rel.information_ratio) == (None, None, None)


def test_r2c_identical_calendars_lose_nothing_and_start_at_the_initial_equity() -> None:
    dates = [JAN[d] for d in (2, 3, 4, 5)]
    benchmark = series(dates, [1100, 1210, 1331, 1464.1])
    strategy = series(dates, [1200, 1392, 1670.4, 1937.664])
    rel = compare_equity(strategy, 1000.0, benchmark, 1000.0, P4)
    assert rel.alignment == Alignment(
        n_strategy_bars=4,
        n_benchmark_bars=4,
        n_common=4,
        n_compared=4,
        n_dropped_strategy=0,
        n_dropped_benchmark=0,
        dates_dropped=False,
        insufficient_overlap=False,
        base="initial_equity",
        base_date=None,
        first_compared_date="2024-01-02",
        last_compared_date="2024-01-05",
    )
    assert rel.strategy_return_compared == approx(0.937664)
    assert rel.benchmark_return_compared == approx(0.4641)
    assert rel.excess_return == approx(0.473564)
    assert rel.tracking_error == approx(0.046188021535)
    assert rel.information_ratio == approx(6.928203230276)


def test_r2d_the_first_common_date_is_the_first_bar_of_only_one_run() -> None:
    benchmark = series([JAN[2], JAN[3], JAN[4], JAN[5]], [1000, 1100, 1210, 1331])
    strategy = series([JAN[3], JAN[4], JAN[5]], [1000, 1200, 1440])
    rel = compare_equity(strategy, 1000.0, benchmark, 1000.0, P4)
    assert rel.alignment == Alignment(
        n_strategy_bars=3,
        n_benchmark_bars=4,
        n_common=3,
        n_compared=2,
        n_dropped_strategy=0,
        n_dropped_benchmark=1,
        dates_dropped=True,
        insufficient_overlap=False,
        base="first_common_date",
        base_date="2024-01-03",
        first_compared_date="2024-01-04",
        last_compared_date="2024-01-05",
    )
    assert rel.strategy_return_compared == approx(0.44)
    assert rel.benchmark_return_compared == approx(0.21)
    assert rel.excess_return == approx(0.23)
    assert rel.tracking_error == 0.0
    assert rel.information_ratio is None


def test_outputs_are_plain_python_types() -> None:
    strategy = series([JAN[3], JAN[4], JAN[5]], [1000, 1200, 1440])
    benchmark = series([JAN[2], JAN[3], JAN[4], JAN[5]], [1000, 1100, 1210, 1331])
    rel = compare_equity(strategy, 1000.0, benchmark, 1000.0, P4)
    for value in (rel.excess_return, rel.tracking_error, rel.strategy_return_compared, rel.benchmark_return_compared):
        assert type(value) is float
    d = rel.to_dict()
    assert d["alignment"]["base"] == "first_common_date" and type(d["alignment"]["dates_dropped"]) is bool


@pytest.mark.parametrize(
    "bad",
    [
        pd.Series([1.0, 2.0]),  # no DatetimeIndex
        series([JAN[3], JAN[2]], [1.0, 2.0]),  # not sorted
        series([JAN[2], JAN[2]], [1.0, 2.0]),  # not unique
    ],
)
def test_a_bad_equity_index_raises(bad: pd.Series) -> None:
    good = series([JAN[2], JAN[3]], [1.0, 2.0])
    with pytest.raises(ValueError):
        compare_equity(bad, 1.0, good, 1.0, P4)
