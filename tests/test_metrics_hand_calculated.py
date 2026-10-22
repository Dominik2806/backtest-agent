"""Fixtures M1 to M14 of docs/metrics.md: the expected values are literals taken from that document.

No expected value is computed with project code or a helper that mirrors it. The tolerance is 1e-9 (relative and
absolute), as documented in docs/metrics.md.
"""

import numpy as np
import pandas as pd
import pytest

from backtest_agent.engine import InsufficientWarmupWarning, run_backtest
from backtest_agent.metrics import (
    MetricAssumptions,
    cagr,
    calmar,
    compute_metrics,
    current_drawdown,
    exposure,
    hit_rate,
    longest_drawdown,
    max_drawdown,
    monthly_returns,
    sharpe,
    sortino,
    total_return,
    turnover_annual,
    volatility,
)
from backtest_agent.spec.schema import CostsSpec
from runner_helpers import LiteralProvider, make_spec, price_frame, register_up_day

TOL = 1e-9


def approx(value):
    return pytest.approx(value, rel=TOL, abs=TOL)


def series(values, dates=None) -> pd.Series:
    index = pd.DatetimeIndex(dates) if dates is not None else pd.bdate_range("2024-01-02", periods=len(values))
    return pd.Series(values, index=index.astype("datetime64[ns]").rename("date"), dtype="float64")


def everything(returns: pd.Series, periods: int, rf: float = 0.0) -> dict:
    """The pure metrics of a series through the public functions."""
    cagr_value, drawdown = cagr(returns, periods), max_drawdown(returns)
    return {
        "total": total_return(returns),
        "cagr": cagr_value,
        "vol": volatility(returns, periods),
        "sharpe": sharpe(returns, periods, rf),
        "sortino": sortino(returns, periods, rf),
        "max_dd": drawdown,
        "current_dd": current_drawdown(returns),
        "longest": longest_drawdown(returns),
        "calmar": calmar(cagr_value, drawdown),
        "hit": hit_rate(returns),
    }


def check(got: dict, expected: dict) -> None:
    for key, value in expected.items():
        if value is None or isinstance(value, tuple):
            assert got[key] == value, key
        else:
            assert got[key] == approx(value), key


M1_R = [0.10, -0.20, 0.25, 0.10]


def test_m1_a_mixed_path() -> None:
    got = everything(series(M1_R), 4)
    check(
        got,
        {
            "total": 0.21,
            "cagr": 0.21,
            "vol": 0.377491721764,
            "sharpe": 0.662266178533,
            "sortino": 1.25,
            "max_dd": -0.2,
            "current_dd": 0.0,
            "longest": (2, 2),
            "calmar": 1.05,
            "hit": 0.75,
        },
    )
    months = monthly_returns(series(M1_R))
    assert list(months) == approx([0.21]) and [str(p) for p in months.index] == ["2024-01"]


def test_m2_the_same_series_with_a_risk_free_rate() -> None:
    returns = series(M1_R)
    assert MetricAssumptions(4, 0.4641).per_bar_risk_free == pytest.approx(0.1, rel=1e-12)
    assert sharpe(returns, 4, 0.4641) == approx(-0.397359707120)
    assert sortino(returns, 4, 0.4641) == approx(-0.5)
    assert volatility(returns, 4) == approx(0.377491721764)  # unchanged by the risk-free rate


def test_m3_starts_under_water_and_never_recovers() -> None:
    check(
        everything(series([-0.10, -0.10, 0.05]), 4),
        {
            "total": -0.1495,
            "cagr": -0.194190424329,
            "vol": 0.173205080757,
            "sharpe": -1.154700538379,
            "sortino": -1.224744871392,
            "max_dd": -0.19,
            "current_dd": -0.1495,
            "longest": (3, 2),
            "calmar": -1.022054864889,
            "hit": 1 / 3,
        },
    )


@pytest.mark.parametrize(("value", "total"), [(0.01, 0.04060401), (0.1, 0.4641)])
def test_m4_constant_returns(value: float, total: float) -> None:
    check(
        everything(series([value] * 4), 4),
        {
            "total": total,
            "cagr": total,
            "vol": 0.0,
            "sharpe": None,
            "sortino": None,
            "max_dd": 0.0,
            "current_dd": 0.0,
            "longest": (0, 0),
            "calmar": None,
            "hit": 1.0,
        },
    )


def test_m5_only_zeros() -> None:
    check(
        everything(series([0.0] * 4), 4),
        {
            "total": 0.0,
            "cagr": 0.0,
            "vol": 0.0,
            "sharpe": None,
            "sortino": None,
            "max_dd": 0.0,
            "longest": (0, 0),
            "calmar": None,
            "hit": 0.0,
        },
    )
    assert list(monthly_returns(series([0.0] * 4))) == [0.0]


def test_m6_a_single_bar() -> None:
    returns = series([0.10])
    check(
        everything(returns, 4),
        {
            "total": 0.1,
            "cagr": 0.4641,
            "vol": None,
            "sharpe": None,
            "sortino": None,
            "max_dd": 0.0,
            "longest": (0, 0),
            "calmar": None,
            "hit": 1.0,
        },
    )
    assert list(monthly_returns(returns)) == approx([0.1])


def test_m7_an_empty_series() -> None:
    returns = series([])
    assert all(value is None for value in everything(returns, 4).values())
    assert len(monthly_returns(returns)) == 0
    assert exposure(pd.DataFrame()) is None and turnover_annual(pd.Series(dtype="float64"), 4) is None


def test_m8_a_ruined_portfolio() -> None:
    check(
        everything(series([0.10, -1.0, 0.0, 0.0]), 4),
        {
            "total": -1.0,
            "cagr": -1.0,
            "vol": 1.037625494418,
            "sharpe": -0.867364964374,
            "sortino": -0.9,
            "max_dd": -1.0,
            "current_dd": -1.0,
            "longest": (3, 3),
            "calmar": -1.0,
            "hit": 0.25,
        },
    )


def test_m9_a_round_sharpe_ratio() -> None:
    check(
        everything(series([0.04, 0.06, 0.04, 0.06, 0.05]), 4),
        {
            "total": 0.276050048,
            "cagr": 0.215329854800,
            "vol": 0.02,
            "sharpe": 10.0,
            "sortino": None,
            "max_dd": 0.0,
            "calmar": None,
            "hit": 1.0,
        },
    )


def test_m10_calendar_months() -> None:
    dates = ["2024-01-30", "2024-01-31", "2024-02-01", "2024-02-28", "2024-03-01"]
    returns = series([0.10, -0.10, 0.20, 0.10, -0.50], dates)
    months = monthly_returns(returns)
    assert [str(p) for p in months.index] == ["2024-01", "2024-02", "2024-03"]
    assert list(months) == approx([-0.01, 0.32, -0.5])
    assert total_return(returns) == approx(-0.3466)


def test_m11_turnover_and_exposure() -> None:
    weights = pd.DataFrame({"A": [0.0, 1.0, 0.5, 1.0]})
    assert exposure(weights) == (approx(0.625), approx(0.75))
    assert turnover_annual([1.0, 0, 0.5, 0], 4) == (approx(1.5), approx(0.75))
    assert exposure(pd.DataFrame({"A": [1e-14, 1.0, 0.5, 1.0]})) == (approx(0.625), approx(0.75))
    assert turnover_annual([1.0, 1.0], 4) == (approx(4.0), approx(2.0))


# --- M12 and M13: whole runs through run_backtest ---------------------------------------------------------------------

COSTS_25_PERCENT = (1000.0, 1000.0, 500.0)


def test_m12_h23_through_run_backtest() -> None:
    spec = make_spec(
        universe=("A",),
        start="2024-01-02",
        end="2024-01-08",
        signal="buy_and_hold",
        params={},
        costs=COSTS_25_PERCENT,
        capital=1000,
    )
    frame = price_frame({"A": [100, 100, 110, 121, 133.1]}, {"A": [100, 110, 121, 133.1, 146.41]})
    metrics = compute_metrics(run_backtest(spec, LiteralProvider(frame)), MetricAssumptions(5, 0.0))
    assert metrics.n_bars == 5 and metrics.years == approx(1.0)
    expected = {
        "total_return": 0.17128,
        "cagr": 0.17128,
        "volatility": 0.217715410571,
        "sharpe": 0.826767381914,
        "sortino": 1.5,
        "max_drawdown": -0.12,
        "current_drawdown": 0.0,
        "calmar": 1.427333333333,
        "hit_rate": 0.6,
        "turnover_two_sided_annual": 0.8,
        "turnover_one_sided_annual": 0.4,
        "exposure_mean": 0.8,
        "exposure_invested_share": 0.8,
        "best_month": 0.17128,
        "worst_month": 0.17128,
    }
    for name, value in expected.items():
        assert getattr(metrics, name) == approx(value), name
    assert (metrics.longest_drawdown_bars, metrics.longest_drawdown_days) == (3, 3)
    assert (metrics.best_month_label, metrics.worst_month_label, metrics.n_months) == ("2024-01", "2024-01", 1)
    assert metrics.assumptions == MetricAssumptions(5, 0.0)


def test_m13_h23c_through_run_backtest(monkeypatch: pytest.MonkeyPatch) -> None:
    register_up_day(monkeypatch)
    spec = make_spec(universe=("A",), start="2024-01-02", end="2024-01-08", signal="fixture_up_day", capital=1000)
    costs = CostsSpec(commission_bps=0, spread_bps=0, slippage_bps=0, min_commission=500)
    frame = price_frame({"A": [100.0] * 5}, {"A": [100.0, 101.0, 100.0, 100.0, 100.0]})
    with pytest.warns(InsufficientWarmupWarning):
        result = run_backtest(spec.model_copy(update={"costs": costs}), LiteralProvider(frame))
    metrics = compute_metrics(result, MetricAssumptions(5, 0.0))
    expected = {
        "total_return": -1.0,
        "cagr": -1.0,
        "volatility": 1.0,
        "sharpe": -1.5,
        "sortino": -1.341640786500,
        "max_drawdown": -1.0,
        "current_drawdown": -1.0,
        "calmar": -1.0,
        "hit_rate": 0.0,
        "exposure_mean": 0.2,
        "exposure_invested_share": 0.2,
        "turnover_two_sided_annual": 1.5,
        "turnover_one_sided_annual": 0.75,
        "best_month": -1.0,
    }
    for name, value in expected.items():
        assert getattr(metrics, name) == approx(value), name
    assert (metrics.longest_drawdown_bars, metrics.longest_drawdown_days) == (3, 5)
    floats = [v for v in metrics.to_dict().values() if isinstance(v, float)]
    assert np.isfinite(floats).all()


@pytest.mark.parametrize(
    "returns",
    [
        series([0.1, float("nan")]),
        series([0.1, float("inf")]),
        series([0.1, -1.0001]),
        pd.Series([0.1, 0.2], index=pd.DatetimeIndex(["2024-01-03", "2024-01-02"])),
        pd.Series([0.1, 0.2], index=pd.DatetimeIndex(["2024-01-02", "2024-01-02"])),
        pd.Series([0.1, 0.2]),
    ],
)
def test_m14_invalid_returns_raise(returns: pd.Series) -> None:
    with pytest.raises(ValueError):
        volatility(returns, 4)
    with pytest.raises(ValueError):
        total_return(returns)


@pytest.mark.parametrize(
    ("periods", "rf"), [(0, 0.0), (-1, 0.0), (4.0, 0.0), (True, 0.0), (4, -1.0), (4, float("nan"))]
)
def test_m14_invalid_assumptions_raise(periods, rf) -> None:
    with pytest.raises(ValueError):
        MetricAssumptions(periods, rf)
