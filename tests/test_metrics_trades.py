"""Fixtures T1 to T6 of docs/metrics.md ("Trade statistics"): the expected values are literals taken from that document.

No expected value is computed with project code. The tolerance is 1e-9 (relative and absolute); the counts are exact.
"""

import json
import warnings

import numpy as np
import pandas as pd
import pytest

from backtest_agent.data import FakeProvider
from backtest_agent.engine import InsufficientWarmupWarning, run_backtest
from backtest_agent.metrics import SymbolTrades, TradeStatistics, trade_statistics
from backtest_agent.spec.schema import CostsSpec
from runner_helpers import LiteralProvider, make_spec, price_frame, register_up_day

TOL = 1e-9
COLUMNS = ["date", "symbol", "shares", "price", "notional", "cost"]


def approx(value):
    return pytest.approx(value, rel=TOL, abs=TOL)


def table(rows) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=COLUMNS)
    frame["date"] = pd.to_datetime(frame["date"])
    return frame


# H22 of docs/engine.md: (date, symbol, shares, price, notional, cost)
H22 = [
    ("2024-01-03", "A", 4.0, 100.0, 400.0, 100.0),
    ("2024-01-03", "B", 8.0, 50.0, 400.0, 100.0),
    ("2024-01-04", "A", -0.4, 125.0, -50.0, 12.5),
    ("2024-01-04", "B", 0.6, 50.0, 30.0, 7.5),
    ("2024-01-05", "A", -11 / 30, 150.0, -55.0, 13.75),
    ("2024-01-05", "B", 0.66, 50.0, 33.0, 8.25),
]


def test_t1_no_trades() -> None:
    stats = trade_statistics(table([]))
    assert (stats.n_trades, stats.n_buys, stats.n_sells) == (0, 0, 0)
    assert stats.per_symbol == {}
    assert stats.total_cost == 0.0
    assert stats.average_cost_per_trade is None


def test_t2_one_trade() -> None:
    stats = trade_statistics(table([("2024-01-03", "A", 8.0, 100.0, 800.0, 200.0)]))
    assert (stats.n_trades, stats.n_buys, stats.n_sells) == (1, 1, 0)
    assert stats.per_symbol == {"A": SymbolTrades(1, 1, 0)}
    assert stats.total_cost == approx(200.0)
    assert stats.average_cost_per_trade == approx(200.0)


def test_t3_several_symbols_h22() -> None:
    stats = trade_statistics(table(H22))
    assert (stats.n_trades, stats.n_buys, stats.n_sells) == (6, 4, 2)
    assert stats.per_symbol == {"A": SymbolTrades(3, 1, 2), "B": SymbolTrades(3, 3, 0)}
    assert stats.total_cost == approx(242.0)
    assert stats.average_cost_per_trade == approx(40.333333333333)


def test_t3_the_order_of_the_rows_does_not_matter() -> None:
    forward = trade_statistics(table(H22))
    backward = trade_statistics(table(H22[::-1]))
    assert backward == forward
    assert list(backward.per_symbol) == ["A", "B"]  # sorted, not in order of appearance


def test_t4_trades_that_cost_nothing_have_an_average_of_zero_not_none() -> None:
    stats = trade_statistics(
        table([("2024-01-03", "A", 10.0, 100.0, 1000.0, 0.0), ("2024-01-05", "A", -10.0, 110.0, -1100.0, 0.0)])
    )
    assert (stats.n_trades, stats.n_buys, stats.n_sells) == (2, 1, 1)
    assert stats.per_symbol == {"A": SymbolTrades(2, 1, 1)}
    assert stats.total_cost == 0.0
    assert stats.average_cost_per_trade == 0.0


def test_t5_h23_through_run_backtest() -> None:
    spec = make_spec(
        universe=("A",),
        start="2024-01-02",
        end="2024-01-08",
        signal="buy_and_hold",
        params={},
        costs=(1000.0, 1000.0, 500.0),
        capital=1000,
    )
    frame = price_frame({"A": [100, 100, 110, 121, 133.1]}, {"A": [100, 110, 121, 133.1, 146.41]})
    result = run_backtest(spec, LiteralProvider(frame))
    stats = trade_statistics(result.trades)
    assert (stats.n_trades, stats.n_buys, stats.n_sells) == (1, 1, 0)
    assert stats.per_symbol == {"A": SymbolTrades(1, 1, 0)}
    assert stats.total_cost == approx(200.0)
    assert stats.average_cost_per_trade == approx(200.0)
    assert stats.total_cost == approx(result.total_costs)


def test_t5_h23c_through_run_backtest(monkeypatch: pytest.MonkeyPatch) -> None:
    register_up_day(monkeypatch)
    spec = make_spec(universe=("A",), start="2024-01-02", end="2024-01-08", signal="fixture_up_day", capital=1000)
    costs = CostsSpec(commission_bps=0, spread_bps=0, slippage_bps=0, min_commission=500)
    frame = price_frame({"A": [100.0] * 5}, {"A": [100.0, 101.0, 100.0, 100.0, 100.0]})
    with pytest.warns(InsufficientWarmupWarning):
        result = run_backtest(spec.model_copy(update={"costs": costs}), LiteralProvider(frame))
    stats = trade_statistics(result.trades)
    assert (stats.n_trades, stats.n_buys, stats.n_sells) == (2, 1, 1)
    assert stats.per_symbol == {"A": SymbolTrades(2, 1, 1)}
    assert stats.total_cost == approx(1000.0)
    assert stats.average_cost_per_trade == approx(500.0)


def test_t1_through_run_backtest_a_run_that_never_trades(monkeypatch: pytest.MonkeyPatch) -> None:
    register_up_day(monkeypatch)  # 1.0 where the close is above the previous close: never on flat prices
    spec = make_spec(universe=("A",), start="2024-01-02", end="2024-01-08", signal="fixture_up_day", capital=1000)
    frame = price_frame({"A": [100.0] * 5}, {"A": [100.0] * 5})
    with pytest.warns(InsufficientWarmupWarning):
        result = run_backtest(spec, LiteralProvider(frame))
    stats = trade_statistics(result.trades)
    assert (stats.n_trades, stats.per_symbol, stats.total_cost) == (0, {}, 0.0)
    assert stats.average_cost_per_trade is None


@pytest.mark.parametrize("bad", [0.0, np.nan, np.inf, -np.inf])
def test_t6_shares_must_be_finite_and_not_zero(bad: float) -> None:
    with pytest.raises(ValueError, match="shares"):
        trade_statistics(table([("2024-01-03", "A", bad, 100.0, 0.0, 1.0)]))


@pytest.mark.parametrize("bad", [-1.0, np.nan, np.inf])
def test_t6_cost_must_be_finite_and_not_negative(bad: float) -> None:
    with pytest.raises(ValueError, match="cost"):
        trade_statistics(table([("2024-01-03", "A", 1.0, 100.0, 100.0, bad)]))


@pytest.mark.parametrize("column", ["symbol", "shares", "cost"])
def test_t6_a_missing_column_raises(column: str) -> None:
    with pytest.raises(ValueError, match=column):
        trade_statistics(table(H22).drop(columns=[column]))


def test_to_dict_is_json_serializable_and_nested() -> None:
    stats = trade_statistics(table(H22))
    data = json.loads(json.dumps(stats.to_dict()))
    assert data["n_trades"] == 6
    assert data["per_symbol"]["A"] == {"trades": 3, "buys": 1, "sells": 2}
    assert isinstance(stats, TradeStatistics)


def test_total_cost_equals_the_total_costs_of_a_fake_run() -> None:
    spec = make_spec(universe=("AAA", "BBB"), start="2018-01-01", end="2018-06-30", rebalance="weekly")
    provider = FakeProvider(symbols=("AAA", "BBB"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", InsufficientWarmupWarning)
        result = run_backtest(spec, provider)
    stats = trade_statistics(result.trades)
    assert stats.n_trades == len(result.trades) > 0
    assert stats.total_cost == pytest.approx(result.total_costs, rel=TOL)
    assert sum(s.trades for s in stats.per_symbol.values()) == stats.n_trades
