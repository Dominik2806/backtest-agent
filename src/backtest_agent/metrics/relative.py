"""Alignment and relative metrics of a strategy against its benchmark (F-13; docs/metrics.md, ADR 0013).

The two runs are compared on the dates both have a bar. The returns are computed from the **equity levels** on that
grid, because a per-bar return across a date that exists in only one series covers a different holding period.
Results are plain ``float``, ``int``, ``str``, ``bool`` or ``None``; a metric that is not defined is ``None``, never
NaN or inf.
"""

import math
from dataclasses import asdict, dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from backtest_agent.engine.core import bar_returns

# Package-internal helpers of part 1: the sample std with the zero tolerance, and the finite-or-None conversion.
# performance.volatility is not reused: its input check rejects returns below -1, which an active return can be.
from backtest_agent.metrics.performance import DEFAULT_ASSUMPTIONS, MetricAssumptions, _finite, _sample_std


@dataclass(frozen=True)
class Alignment:
    """What the comparison did with the dates. Scalars only, so it serializes as it is."""

    n_strategy_bars: int
    n_benchmark_bars: int
    n_common: int
    n_compared: int  # return observations after the alignment
    n_dropped_strategy: int
    n_dropped_benchmark: int
    dates_dropped: bool  # either dropped count is above 0
    insufficient_overlap: bool  # n_compared < 2: the relative metrics are None
    base: Literal["initial_equity", "first_common_date"]
    base_date: str | None  # ISO date of the base point if base is "first_common_date"
    first_compared_date: str | None
    last_compared_date: str | None


@dataclass(frozen=True)
class AlignedReturns:
    """The two return series on the compared dates (same index) and the alignment that produced them."""

    strategy: pd.Series
    benchmark: pd.Series
    alignment: Alignment


@dataclass(frozen=True)
class RelativeMetrics:
    """Excess return, tracking error and information ratio over the compared window; ``None`` if undefined."""

    excess_return: float | None
    tracking_error: float | None  # annualized sample std of the active return
    information_ratio: float | None
    strategy_return_compared: float | None  # compounded return of the strategy over the window
    benchmark_return_compared: float | None
    alignment: Alignment

    def to_dict(self) -> dict[str, Any]:
        """Plain dict (float, int, str, bool, None and one nested dict), for the report and the journal."""
        return asdict(self)


def _check_equity(equity: pd.Series, name: str) -> None:
    if not isinstance(equity.index, pd.DatetimeIndex):
        raise ValueError(f"{name} must have a DatetimeIndex")
    if not equity.index.is_monotonic_increasing or not equity.index.is_unique:
        raise ValueError(f"the index of {name} must be sorted and unique")


def align_equity(
    equity: pd.Series, initial_equity: float, benchmark_equity: pd.Series, benchmark_initial_equity: float
) -> AlignedReturns:
    """Returns of both runs on their common dates, computed from the equity levels (rule in docs/metrics.md).

    If the first common date is the first bar of both runs, the first return is measured against the initial equity of
    each run. Otherwise the equity at the first common date is the base and that date has no return. Dates that are not
    common are counted, never dropped silently; different calendars never raise.
    """
    _check_equity(equity, "equity")
    _check_equity(benchmark_equity, "benchmark_equity")
    common = equity.index.intersection(benchmark_equity.index).sort_values()
    n_common = len(common)
    empty = pd.Series([], dtype="float64", index=common[:0])

    if n_common and common[0] == equity.index[0] and common[0] == benchmark_equity.index[0]:
        base, base_date = "initial_equity", None
        strategy = bar_returns(equity.loc[common].astype("float64"), initial_equity)
        benchmark = bar_returns(benchmark_equity.loc[common].astype("float64"), benchmark_initial_equity)
    elif n_common:
        base, base_date = "first_common_date", str(common[0].date())
        rest = common[1:]
        strategy = bar_returns(equity.loc[rest].astype("float64"), float(equity.loc[common[0]]))
        benchmark = bar_returns(benchmark_equity.loc[rest].astype("float64"), float(benchmark_equity.loc[common[0]]))
    else:
        base, base_date = "first_common_date", None
        strategy, benchmark = empty, empty

    n_compared = len(strategy)
    dropped_strategy, dropped_benchmark = len(equity) - n_common, len(benchmark_equity) - n_common
    alignment = Alignment(
        n_strategy_bars=len(equity),
        n_benchmark_bars=len(benchmark_equity),
        n_common=n_common,
        n_compared=n_compared,
        n_dropped_strategy=dropped_strategy,
        n_dropped_benchmark=dropped_benchmark,
        dates_dropped=dropped_strategy > 0 or dropped_benchmark > 0,
        insufficient_overlap=n_compared < 2,
        base=base,  # type: ignore[arg-type]
        base_date=base_date,
        first_compared_date=str(strategy.index[0].date()) if n_compared else None,
        last_compared_date=str(strategy.index[-1].date()) if n_compared else None,
    )
    return AlignedReturns(strategy, benchmark, alignment)


def _relative(
    strategy: pd.Series, benchmark: pd.Series, periods_per_year: int
) -> tuple[float | None, float | None, float | None, float | None, float | None]:
    """(strategy total, benchmark total, excess return, tracking error, information ratio) of aligned returns."""
    if not strategy.index.equals(benchmark.index):
        raise ValueError("the strategy and benchmark returns must have the same index")
    s, b = strategy.to_numpy(dtype="float64"), benchmark.to_numpy(dtype="float64")
    if not (np.isfinite(s).all() and np.isfinite(b).all()):
        raise ValueError("returns must not contain NaN or infinity")
    if len(s) < 2:
        return None, None, None, None, None
    with np.errstate(over="ignore", invalid="ignore"):  # an overflow gives inf, which _finite turns into None
        return _relative_values(s, b, periods_per_year)


def _relative_values(
    s: np.ndarray, b: np.ndarray, periods_per_year: int
) -> tuple[float | None, float | None, float | None, float | None, float | None]:
    strategy_total = _finite(float(np.prod(1.0 + s) - 1.0))
    benchmark_total = _finite(float(np.prod(1.0 + b) - 1.0))
    excess = None if strategy_total is None or benchmark_total is None else _finite(strategy_total - benchmark_total)
    active = s - b
    std = _sample_std(active)  # not None: at least 2 observations
    if std is None or std == 0.0:
        return strategy_total, benchmark_total, excess, 0.0, None
    tracking_error = _finite(std * math.sqrt(periods_per_year))
    information = (
        None if tracking_error is None else _finite(float(np.mean(active)) * periods_per_year / tracking_error)
    )
    return strategy_total, benchmark_total, excess, tracking_error, information


def relative_from_returns(
    strategy: pd.Series, benchmark: pd.Series, assumptions: MetricAssumptions = DEFAULT_ASSUMPTIONS
) -> tuple[float | None, float | None, float | None]:
    """(excess return, tracking error, information ratio) of two return series with the same index.

    ``None`` for all three with fewer than 2 observations; the information ratio is also ``None`` if the tracking error
    counts as zero (per-bar standard deviation below 1e-12, then the tracking error is exactly 0.0).
    """
    _, _, excess, tracking_error, information = _relative(strategy, benchmark, assumptions.periods_per_year)
    return excess, tracking_error, information


def compare_equity(
    equity: pd.Series,
    initial_equity: float,
    benchmark_equity: pd.Series,
    benchmark_initial_equity: float,
    assumptions: MetricAssumptions = DEFAULT_ASSUMPTIONS,
) -> RelativeMetrics:
    """Align the equity paths of strategy and benchmark and compute the relative metrics."""
    aligned = align_equity(equity, initial_equity, benchmark_equity, benchmark_initial_equity)
    s_total, b_total, excess, tracking_error, information = _relative(
        aligned.strategy, aligned.benchmark, assumptions.periods_per_year
    )
    return RelativeMetrics(excess, tracking_error, information, s_total, b_total, aligned.alignment)
