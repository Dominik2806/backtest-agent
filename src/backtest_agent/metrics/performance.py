"""Performance and risk metrics of a run (F-12; formulas, assumptions and fixtures in docs/metrics.md, ADR 0012).

The functions are pure: they take a series of returns (``DatetimeIndex``, the first bar measured against the initial
equity), and for exposure and turnover the weights and the turnover of the run. Results are plain ``float``, ``int``,
``str`` or ``None``; a metric that is not defined is ``None``, never NaN or inf.
"""

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from backtest_agent.engine.result import BacktestResult

EPS = 1e-12  # a per-bar deviation below this counts as zero (the std of [0.01] * 4 is about 1e-18, not 0)
DRAWDOWN_TOLERANCE = 1e-12  # a drawdown above -DRAWDOWN_TOLERANCE is no drawdown
EXPOSURE_TOLERANCE = 1e-9  # a sum of weights at or below this is no position (float dust of a fill)


@dataclass(frozen=True)
class MetricAssumptions:
    """What the annualized metrics assume. ``risk_free_rate`` is annual and converted per bar by compounding."""

    periods_per_year: int = 252
    risk_free_rate: float = 0.0

    def __post_init__(self) -> None:
        if isinstance(self.periods_per_year, bool) or not isinstance(self.periods_per_year, int):
            raise ValueError(f"periods_per_year must be an integer, got {self.periods_per_year!r}")
        if self.periods_per_year < 1:
            raise ValueError(f"periods_per_year must be at least 1, got {self.periods_per_year}")
        if not math.isfinite(self.risk_free_rate) or self.risk_free_rate <= -1.0:
            raise ValueError(f"risk_free_rate must be finite and above -1, got {self.risk_free_rate}")

    @property
    def per_bar_risk_free(self) -> float:
        """``(1 + rf) ** (1 / periods_per_year) - 1``; exactly 0.0 when ``rf`` is 0."""
        if self.risk_free_rate == 0.0:
            return 0.0
        return (1.0 + self.risk_free_rate) ** (1.0 / self.periods_per_year) - 1.0


DEFAULT_ASSUMPTIONS = MetricAssumptions()


@dataclass(frozen=True)
class PerformanceMetrics:
    """The metrics of one run. Every number except the counts can be ``None`` (see "When a metric is None")."""

    assumptions: MetricAssumptions
    n_bars: int
    years: float | None  # n_bars / periods_per_year
    total_return: float | None  # BacktestResult.net_return
    cagr: float | None
    volatility: float | None  # annualized, sample std
    sharpe: float | None
    sortino: float | None
    max_drawdown: float | None  # a negative fraction, 0.0 if never below the peak
    current_drawdown: float | None
    longest_drawdown_bars: int | None  # peak to recovery (or to the end), in bars
    longest_drawdown_days: int | None  # the same stretch in calendar days
    calmar: float | None
    hit_rate: float | None  # share of bars with a positive return, over all bars
    turnover_two_sided_annual: float | None  # the engine's definition: buying everything is 1.0
    turnover_one_sided_annual: float | None  # half of the two-sided figure
    exposure_mean: float | None  # mean over bars of the sum of the weights
    exposure_invested_share: float | None  # share of bars with a position
    best_month: float | None
    best_month_label: str | None  # "YYYY-MM"
    worst_month: float | None
    worst_month_label: str | None
    n_months: int  # months with at least one bar; the first and last can be partial

    def to_dict(self) -> dict[str, Any]:
        """Plain dict (float, int, str, None and one nested dict), for the report and the journal."""
        return asdict(self)


def _values(returns: pd.Series) -> np.ndarray:
    """Validated returns as a float array; anything that is not a clean return series is a bug upstream."""
    if not isinstance(returns.index, pd.DatetimeIndex):
        raise ValueError("returns must have a DatetimeIndex")
    if not returns.index.is_monotonic_increasing or not returns.index.is_unique:
        raise ValueError("the index of returns must be sorted and unique")
    values = returns.to_numpy(dtype="float64")
    if not np.isfinite(values).all():
        raise ValueError("returns must not contain NaN or infinity")
    if (values < -1.0).any():
        raise ValueError("a return below -1 is impossible (equity cannot go below 0)")
    return values


def _finite(value: float) -> float | None:
    return float(value) if math.isfinite(value) else None


def _sample_std(values: np.ndarray) -> float | None:
    """Sample standard deviation (ddof 1); None for fewer than 2 values, exactly 0.0 below ``EPS``."""
    if len(values) < 2:
        return None
    std = float(np.std(values, ddof=1))
    return 0.0 if std < EPS else std


def total_return(returns: pd.Series) -> float | None:
    """Compounded return of the series, ``prod(1 + r) - 1``; None for an empty series."""
    values = _values(returns)
    return float(np.prod(1.0 + values) - 1.0) if len(values) else None


def _cagr(total: float, n_bars: int, periods_per_year: int) -> float | None:
    if n_bars == 0:
        return None
    growth = 1.0 + total
    if growth <= 0.0:
        return -1.0  # ruined
    try:
        return _finite(math.exp(math.log(growth) * periods_per_year / n_bars) - 1.0)
    except OverflowError:
        return None


def cagr(returns: pd.Series, periods_per_year: int = 252) -> float | None:
    """``(1 + total) ** (periods_per_year / n_bars) - 1``, counted in bars; -1.0 after a ruin."""
    total = total_return(returns)
    return None if total is None else _cagr(total, len(returns), periods_per_year)


def volatility(returns: pd.Series, periods_per_year: int = 252) -> float | None:
    """Sample standard deviation times ``sqrt(periods_per_year)``; None for fewer than 2 bars."""
    std = _sample_std(_values(returns))
    return None if std is None else float(std * math.sqrt(periods_per_year))


def sharpe(returns: pd.Series, periods_per_year: int = 252, risk_free_rate: float = 0.0) -> float | None:
    """Mean excess return over the standard deviation, annualized; None if the deviation is (about) 0."""
    assumptions = MetricAssumptions(periods_per_year, risk_free_rate)
    values = _values(returns)
    std = _sample_std(values)
    if std is None or std == 0.0:
        return None
    excess = float(np.mean(values)) - assumptions.per_bar_risk_free
    return _finite(excess / std * math.sqrt(periods_per_year))


def sortino(returns: pd.Series, periods_per_year: int = 252, risk_free_rate: float = 0.0) -> float | None:
    """Mean excess return over the downside deviation (against the risk-free target, over all bars), annualized."""
    assumptions = MetricAssumptions(periods_per_year, risk_free_rate)
    values = _values(returns)
    if len(values) < 2:
        return None
    target = assumptions.per_bar_risk_free
    downside = float(np.sqrt(np.mean(np.minimum(values - target, 0.0) ** 2)))
    if downside < EPS:
        return None
    return _finite((float(np.mean(values)) - target) / downside * math.sqrt(periods_per_year))


def drawdown_path(returns: pd.Series) -> np.ndarray:
    """Drawdown of every point of the equity path (``n + 1`` points, point 0 is the initial equity), 0 or less."""
    values = _values(returns)
    equity = np.concatenate(([1.0], np.cumprod(1.0 + values)))
    drawdown = equity / np.maximum.accumulate(equity) - 1.0
    return np.where(drawdown > -DRAWDOWN_TOLERANCE, 0.0, drawdown)


def max_drawdown(returns: pd.Series) -> float | None:
    """The lowest drawdown (a negative fraction, 0.0 if never below the peak); None for an empty series."""
    return float(drawdown_path(returns).min()) if len(returns) else None


def current_drawdown(returns: pd.Series) -> float | None:
    """The drawdown after the last bar; None for an empty series."""
    return float(drawdown_path(returns)[-1]) if len(returns) else None


def longest_drawdown(returns: pd.Series) -> tuple[int, int] | None:
    """Bars and calendar days of the underwater stretch with the most bars, from its peak to its recovery.

    A stretch that never recovers runs to the last point. Point ``k >= 1`` is dated on bar ``k``, point 0 (the initial
    equity) on the first bar. (0, 0) if the portfolio is never below its peak; None for an empty series.
    """
    path = drawdown_path(returns)
    n = len(path) - 1
    if n == 0:
        return None
    dates = returns.index[np.maximum(np.arange(n + 1) - 1, 0)]
    underwater = path < 0.0
    best = (0, 0)
    k = 1
    while k <= n:
        if not underwater[k]:
            k += 1
            continue
        peak = k - 1
        while k <= n and underwater[k]:
            k += 1
        end = k if k <= n else n  # the recovery point, or the last point if there is none
        bars = end - peak
        if bars > best[0]:
            best = (bars, int((dates[end] - dates[peak]).days))
    return best


def hit_rate(returns: pd.Series) -> float | None:
    """Share of bars with a return above 0, over all bars; None for an empty series."""
    values = _values(returns)
    return float(np.count_nonzero(values > 0.0) / len(values)) if len(values) else None


def calmar(cagr_value: float | None, max_drawdown_value: float | None) -> float | None:
    """CAGR over the absolute maximum drawdown; None if either is missing or the drawdown is 0."""
    if cagr_value is None or max_drawdown_value is None or max_drawdown_value == 0.0:
        return None
    return _finite(cagr_value / abs(max_drawdown_value))


def monthly_returns(returns: pd.Series) -> pd.Series:
    """Compounded return per calendar month (index: ``Period`` "M") of the months that have a bar."""
    values = pd.Series(_values(returns), index=returns.index)
    return (1.0 + values).groupby(values.index.to_period("M")).prod() - 1.0


def exposure(weights: pd.DataFrame) -> tuple[float, float] | None:
    """Mean sum of the weights per bar and the share of bars with a position; None without bars."""
    if len(weights) == 0:
        return None
    invested = weights.sum(axis=1).to_numpy(dtype="float64")
    return float(np.mean(invested)), float(np.count_nonzero(invested > EXPOSURE_TOLERANCE) / len(invested))


def turnover_annual(turnover: pd.Series | Sequence[float], periods_per_year: int = 252) -> tuple[float, float] | None:
    """(two-sided, one-sided) turnover per year: ``sum(turnover) / years``, and half of it; None without bars.

    The engine's turnover is two-sided (buying the whole portfolio from cash is 1.0).
    """
    values = np.asarray(turnover, dtype="float64")
    if len(values) == 0:
        return None
    two_sided = float(values.sum() / (len(values) / periods_per_year))
    return two_sided, two_sided / 2.0


def compute_metrics(result: BacktestResult, assumptions: MetricAssumptions = DEFAULT_ASSUMPTIONS) -> PerformanceMetrics:
    """All metrics of the net run of ``result``. Total return is ``result.net_return``."""
    returns = result.returns
    values = _values(returns)
    n = len(values)
    periods = assumptions.periods_per_year
    total = result.net_return if n else None
    cagr_value = None if total is None else _cagr(total, n, periods)
    drawdown = max_drawdown(returns)
    longest = longest_drawdown(returns)
    months = monthly_returns(returns)
    exposures = exposure(result.weights)
    turnovers = turnover_annual(result.turnover, periods)
    return PerformanceMetrics(
        assumptions=assumptions,
        n_bars=n,
        years=n / periods if n else None,
        total_return=total,
        cagr=cagr_value,
        volatility=volatility(returns, periods),
        sharpe=sharpe(returns, periods, assumptions.risk_free_rate),
        sortino=sortino(returns, periods, assumptions.risk_free_rate),
        max_drawdown=drawdown,
        current_drawdown=current_drawdown(returns),
        longest_drawdown_bars=None if longest is None else longest[0],
        longest_drawdown_days=None if longest is None else longest[1],
        calmar=calmar(cagr_value, drawdown),
        hit_rate=hit_rate(returns),
        turnover_two_sided_annual=None if turnovers is None else turnovers[0],
        turnover_one_sided_annual=None if turnovers is None else turnovers[1],
        exposure_mean=None if exposures is None else exposures[0],
        exposure_invested_share=None if exposures is None else exposures[1],
        best_month=float(months.max()) if n else None,
        best_month_label=str(months.idxmax()) if n else None,
        worst_month=float(months.min()) if n else None,
        worst_month_label=str(months.idxmin()) if n else None,
        n_months=len(months),
    )
