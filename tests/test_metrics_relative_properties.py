"""Property tests of the relative metrics: swap, self comparison, flags, no NaN or inf on random and degenerate data."""

import json
import math

import numpy as np
import pandas as pd
import pytest

from backtest_agent.metrics import MetricAssumptions, compare_equity

TOLERANCE = 1e-9
P4 = MetricAssumptions(periods_per_year=4)
DAYS = pd.bdate_range("2024-01-02", periods=30).astype("datetime64[ns]").rename("date")


def equity(rng: np.random.Generator, index: pd.DatetimeIndex, *, ruin: bool = False) -> pd.Series:
    values = 1000.0 * np.cumprod(1.0 + rng.uniform(-0.3, 0.4, len(index)))
    if ruin and len(index):
        values[int(rng.integers(len(index))) :] = 0.0
    return pd.Series(values, index=index)


def assert_finite_or_none(value) -> None:
    if isinstance(value, dict):
        for item in value.values():
            assert_finite_or_none(item)
    elif isinstance(value, float):
        assert math.isfinite(value), value


def check(rel) -> None:
    d = rel.to_dict()
    assert_finite_or_none(d)
    json.dumps(d)
    al = rel.alignment
    expected = al.n_common if al.base == "initial_equity" and al.n_common else max(al.n_common - 1, 0)
    assert al.n_compared == expected
    assert al.n_dropped_strategy == al.n_strategy_bars - al.n_common
    assert al.n_dropped_benchmark == al.n_benchmark_bars - al.n_common
    assert al.dates_dropped == (al.n_dropped_strategy > 0 or al.n_dropped_benchmark > 0)
    assert al.insufficient_overlap == (al.n_compared < 2)
    if al.insufficient_overlap:
        assert (rel.excess_return, rel.tracking_error, rel.information_ratio) == (None, None, None)
    if rel.tracking_error == 0.0:
        assert rel.information_ratio is None


@pytest.mark.parametrize("seed", range(40))
def test_random_pairs_on_different_calendars(seed: int) -> None:
    rng = np.random.default_rng(seed)
    keep_s, keep_b = rng.random(len(DAYS)) > 0.25, rng.random(len(DAYS)) > 0.25
    s_index, b_index = DAYS[keep_s], DAYS[keep_b]
    strategy, benchmark = equity(rng, s_index, ruin=seed % 5 == 0), equity(rng, b_index, ruin=seed % 7 == 0)
    rel = compare_equity(strategy, 1000.0, benchmark, 1000.0, P4)
    check(rel)

    swapped = compare_equity(benchmark, 1000.0, strategy, 1000.0, P4)
    check(swapped)
    assert rel.alignment.n_compared == swapped.alignment.n_compared
    if rel.excess_return is None:
        assert swapped.excess_return is None
        return
    assert swapped.excess_return == pytest.approx(-rel.excess_return, rel=TOLERANCE, abs=TOLERANCE)
    assert swapped.tracking_error == pytest.approx(rel.tracking_error, rel=TOLERANCE, abs=TOLERANCE)
    if rel.information_ratio is None:
        assert swapped.information_ratio is None
    else:
        assert swapped.information_ratio == pytest.approx(-rel.information_ratio, rel=TOLERANCE, abs=TOLERANCE)


@pytest.mark.parametrize("seed", range(10))
def test_a_strategy_against_itself(seed: int) -> None:
    rng = np.random.default_rng(100 + seed)
    path = equity(rng, DAYS, ruin=seed % 3 == 0)
    rel = compare_equity(path, 1000.0, path.copy(), 1000.0, P4)
    check(rel)
    assert rel.excess_return == 0.0 and rel.tracking_error == 0.0 and rel.information_ratio is None
    assert not rel.alignment.dates_dropped


def test_swapping_the_roles_of_the_r2a_fixture_flips_the_signs() -> None:
    def s(dates, values):
        return pd.Series(values, index=pd.DatetimeIndex(dates, name="date"), dtype="float64")

    strategy = s(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"], [1000, 1100, 1210, 1089])
    benchmark = s(["2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"], [1000, 1050, 1102.5, 1157.625])
    rel = compare_equity(benchmark, 1000.0, strategy, 1000.0, P4)
    assert rel.excess_return == pytest.approx(0.1125, rel=TOLERANCE)
    assert rel.tracking_error == pytest.approx(0.282842712475, rel=TOLERANCE)
    assert rel.information_ratio == pytest.approx(0.707106781187, rel=TOLERANCE)
    assert (rel.alignment.n_dropped_strategy, rel.alignment.n_dropped_benchmark) == (1, 1)


def series(values: list[float], n: int | None = None) -> pd.Series:
    n = len(values) if n is None else n
    return pd.Series(values, index=DAYS[:n], dtype="float64")


@pytest.mark.parametrize(
    ("strategy", "benchmark"),
    [
        (series([]), series([])),  # empty
        (series([1000.0]), series([1000.0])),  # a single bar
        (series([1000.0] * 5), series([1000.0] * 5)),  # constant equity (all returns 0)
        (series([1000.0, 1010.0, 1020.1, 1030.301]), series([1000.0, 1010.0, 1020.1, 1030.301])),  # constant 1 percent
        (series([1000.0, 500.0, 0.0, 0.0]), series([1000.0, 1100.0, 1210.0, 1331.0])),  # ruined strategy
        (series([1000.0, 1100.0, 1210.0, 1331.0]), series([1000.0, 500.0, 0.0, 0.0])),  # ruined benchmark
        (series([0.0, 0.0, 0.0]), series([0.0, 0.0, 0.0])),  # both ruined before the first bar
        (series([1e300, 1e300, 1e300]), series([1.0, 1e300, 1.0])),  # huge numbers
    ],
)
def test_degenerate_inputs_have_no_nan_or_inf(strategy: pd.Series, benchmark: pd.Series) -> None:
    check(compare_equity(strategy, 1000.0, benchmark, 1000.0, P4))


def test_no_common_date_and_disjoint_calendars_do_not_raise() -> None:
    rel = compare_equity(series([1000.0, 1100.0], 2), 1000.0, series([1.0, 2.0]).set_axis(DAYS[5:7]), 1.0, P4)
    check(rel)
    assert rel.alignment.n_common == 0 and rel.alignment.n_compared == 0


def test_a_ruin_before_the_base_date_gives_zero_returns_not_nan() -> None:
    strategy = series([1000.0, 0.0, 0.0, 0.0])
    benchmark = series([1000.0, 1100.0, 1210.0, 1331.0]).iloc[1:]  # starts one bar later: base is the second bar
    rel = compare_equity(strategy, 1000.0, benchmark, 1000.0, P4)
    check(rel)
    assert rel.alignment.base == "first_common_date" and rel.alignment.n_compared == 2
    assert rel.strategy_return_compared == 0.0  # from a base of 0 nothing is gained or lost
