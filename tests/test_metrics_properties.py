"""Property tests of the metrics on seeded random series, and the result-level checks through ``run_backtest``.

Only properties that hold in general are asserted (see docs/metrics.md); no sign of a ratio beyond the documented one.
"""

import json
import math

import numpy as np
import pandas as pd
import pytest

from backtest_agent.data import FakeProvider
from backtest_agent.engine import run_backtest
from backtest_agent.metrics import (
    MetricAssumptions,
    PerformanceMetrics,
    cagr,
    compute_metrics,
    drawdown_path,
    hit_rate,
    longest_drawdown,
    max_drawdown,
    monthly_returns,
    sharpe,
    sortino,
    turnover_annual,
    volatility,
)
from runner_helpers import make_spec

SEEDS = range(25)


def random_returns(seed: int, n: int | None = None) -> pd.Series:
    rng = np.random.default_rng(seed)
    n = n if n is not None else int(rng.integers(2, 400))
    values = rng.normal(0.0004, 0.01, n)
    index = pd.bdate_range("2023-03-01", periods=n).astype("datetime64[ns]").rename("date")
    return pd.Series(values, index=index)


@pytest.mark.parametrize("seed", SEEDS)
def test_drawdown_is_between_minus_one_and_zero_and_zero_at_new_highs(seed: int) -> None:
    returns = random_returns(seed)
    path = drawdown_path(returns)
    assert len(path) == len(returns) + 1
    assert (path <= 0.0).all() and (path >= -1.0).all()
    equity = np.concatenate(([1.0], np.cumprod(1.0 + returns.to_numpy())))
    new_high = equity >= np.maximum.accumulate(equity)
    assert (path[new_high] == 0.0).all()
    assert -1.0 <= max_drawdown(returns) <= 0.0
    bars, days = longest_drawdown(returns)
    assert 0 <= bars <= len(returns) and days >= 0


@pytest.mark.parametrize("seed", SEEDS)
def test_the_sign_of_sharpe_is_the_sign_of_the_mean_excess_return(seed: int) -> None:
    returns = random_returns(seed)
    for rf in (0.0, 0.05, 0.4):
        target = (1.0 + rf) ** (1.0 / 252) - 1.0
        excess = returns.mean() - target
        value = sharpe(returns, 252, rf)
        assert value is not None and math.copysign(1.0, value) == math.copysign(1.0, excess)
        sortino_value = sortino(returns, 252, rf)
        assert sortino_value is None or math.copysign(1.0, sortino_value) == math.copysign(1.0, excess)


@pytest.mark.parametrize("value", [0.01, 0.1, 1 / 3, 0.0007, 0.25, -0.01, -0.1, 0.0])
@pytest.mark.parametrize("n", [2, 3, 4, 50, 252, 1000])
def test_a_constant_series_has_zero_volatility_and_no_ratios(value: float, n: int) -> None:
    returns = pd.Series(value, index=pd.bdate_range("2024-01-02", periods=n))
    assert volatility(returns, 252) == 0.0
    assert sharpe(returns, 252) is None
    if value >= 0.0:
        assert max_drawdown(returns) == 0.0 and longest_drawdown(returns) == (0, 0)
        assert sortino(returns, 252) is None
    assert hit_rate(returns) == (1.0 if value > 0.0 else 0.0)


@pytest.mark.parametrize("seed", SEEDS)
def test_best_month_is_at_least_the_worst_and_months_compound_to_the_total(seed: int) -> None:
    returns = random_returns(seed)
    months = monthly_returns(returns)
    assert months.max() >= months.min()
    assert math.prod(1.0 + months) - 1.0 == pytest.approx(math.prod(1.0 + returns) - 1.0, rel=1e-9, abs=1e-12)


@pytest.mark.parametrize("seed", SEEDS)
def test_one_sided_turnover_is_half_of_two_sided(seed: int) -> None:
    rng = np.random.default_rng(seed)
    turnover = rng.uniform(0.0, 2.0, int(rng.integers(1, 300)))
    two, one = turnover_annual(turnover, 252)
    assert one == two / 2.0 and two >= 0.0


@pytest.mark.parametrize(
    "returns",
    [
        pd.Series([], index=pd.DatetimeIndex([]), dtype="float64"),
        pd.Series([0.0], index=pd.bdate_range("2024-01-02", periods=1)),
        pd.Series([-1.0], index=pd.bdate_range("2024-01-02", periods=1)),
        pd.Series([-1.0, 0.0, 0.0], index=pd.bdate_range("2024-01-02", periods=3)),
        pd.Series([1e6, 1e6], index=pd.bdate_range("2024-01-02", periods=2)),
        pd.Series([0.5] * 3, index=pd.bdate_range("2024-01-02", periods=3)),
    ],
)
def test_no_output_is_nan_or_inf_for_degenerate_series(returns: pd.Series) -> None:
    values = [
        cagr(returns, 252),
        volatility(returns, 252),
        sharpe(returns, 252),
        sortino(returns, 252),
        max_drawdown(returns),
    ]
    assert all(v is None or math.isfinite(v) for v in values)


# --- through run_backtest ------------------------------------------------------------


def run_metrics(capital: float, seed: int = 3, rebalance: str = "weekly") -> PerformanceMetrics:
    spec = make_spec(
        universe=("AAA", "BBB"), start="2024-03-01", end="2024-08-30", rebalance=rebalance, capital=capital
    )
    provider = FakeProvider(symbols=("AAA", "BBB"), seed=seed)
    return compute_metrics(run_backtest(spec, provider))


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("rebalance", ["daily", "weekly", "on_signal"])
def test_scaling_the_capital_changes_no_metric(seed: int, rebalance: str) -> None:
    one = run_metrics(100000, seed, rebalance).to_dict()
    two = run_metrics(200000, seed, rebalance).to_dict()
    assert one.keys() == two.keys()
    for key, value in one.items():
        if isinstance(value, float):
            assert two[key] == pytest.approx(value, rel=1e-9, abs=1e-9), key
        else:
            assert two[key] == value, key


def test_to_dict_is_plain_and_json_serializable() -> None:
    metrics = run_metrics(100000)
    data = metrics.to_dict()
    assert data["assumptions"] == {"periods_per_year": 252, "risk_free_rate": 0.0}
    assert json.loads(json.dumps(data)) == data
    assert all(isinstance(v, (float, int, str, type(None), dict)) for v in data.values())
    assert metrics.assumptions == MetricAssumptions()
    assert metrics.turnover_one_sided_annual == metrics.turnover_two_sided_annual / 2.0
