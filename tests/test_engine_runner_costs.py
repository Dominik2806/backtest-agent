"""run_backtest with costs: fixtures H23 and H23b of docs/engine.md, the flags, the opt-out and the gross twin.

The expected values of H23 and H23b are literals taken from that document. The other tests check identities that hold
exactly (bit-identical zero-cost runs, the twin equal to a run with zero costs) or by definition. No test asserts a sign
of ``cost_drag`` or a bound of ``cost_share`` in general: costs change the path, so neither is guaranteed.
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from backtest_agent.data import FakeProvider
from backtest_agent.engine import BacktestResult, InsufficientWarmupWarning, run_backtest
from backtest_agent.spec.schema import CostsSpec
from runner_helpers import LiteralProvider, make_spec, price_frame, register_up_day

TOLERANCE = 1e-9
COSTS_25_PERCENT = (1000.0, 1000.0, 500.0)  # commission, spread, slippage in bps: a total rate of 25 percent
DATES = [date(2024, 1, d) for d in (2, 3, 4, 5, 8)]


def approx(values):
    return pytest.approx(values, rel=TOLERANCE, abs=TOLERANCE)


def h23_spec(costs=COSTS_25_PERCENT):
    return make_spec(
        universe=("A",),
        start="2024-01-02",
        end="2024-01-08",
        signal="buy_and_hold",
        params={},
        costs=costs,
        capital=1000,
    )


H23_OPEN = {"A": [100, 100, 110, 121, 133.1]}
H23_CLOSE = {"A": [100, 110, 121, 133.1, 146.41]}
H23B_OPEN = {"A": [100, 100, 90, 81, 72.9]}
H23B_CLOSE = {"A": [100, 90, 81, 72.9, 65.61]}


def run(opens, closes, costs=COSTS_25_PERCENT, **kwargs) -> BacktestResult:
    return run_backtest(h23_spec(costs), LiteralProvider(price_frame(opens, closes)), **kwargs)


def test_h23_buy_and_hold_with_costs_net_and_gross() -> None:
    result = run(H23_OPEN, H23_CLOSE)
    assert [ts.date() for ts in result.equity.index] == DATES
    assert list(result.equity) == approx([1000, 880, 968, 1064.8, 1171.28])
    assert list(result.gross_equity) == approx([1000, 1100, 1210, 1331, 1464.1])
    assert list(result.cash) == approx([1000, 0, 0, 0, 0])
    assert list(result.positions["A"]) == approx([0, 8, 8, 8, 8])
    assert list(result.weights["A"]) == approx([0, 1, 1, 1, 1])
    assert list(result.turnover) == approx([0, 0.8, 0, 0, 0])
    assert list(result.costs) == approx([0, 200, 0, 0, 0])
    assert list(result.returns) == approx([0, -0.12, 0.1, 0.1, 0.1])
    (trade,) = result.trades.itertuples(index=False)
    assert trade.date == pd.Timestamp("2024-01-03") and trade.symbol == "A"
    assert [trade.shares, trade.price, trade.notional, trade.cost] == approx([8, 100, 800, 200])
    assert (result.deferred_orders, result.unfilled_orders) == (0, 0)
    assert result.costs_applied is True
    assert result.risk_flags == ()

    assert result.total_costs == pytest.approx(200, rel=TOLERANCE)
    assert result.gross_final_equity == pytest.approx(1464.1, rel=TOLERANCE)
    assert result.net_return == pytest.approx(0.17128, rel=TOLERANCE)
    assert result.gross_return == pytest.approx(0.4641, rel=TOLERANCE)
    assert result.cost_drag == pytest.approx(0.29282, rel=TOLERANCE)
    assert result.cost_share == pytest.approx(292.82 / 464.1, rel=TOLERANCE)


def test_h23b_a_falling_market_has_no_cost_share() -> None:
    result = run(H23B_OPEN, H23B_CLOSE)
    assert list(result.equity) == approx([1000, 720, 648, 583.2, 524.88])
    assert list(result.gross_equity) == approx([1000, 900, 810, 729, 656.1])
    assert result.total_costs == pytest.approx(200, rel=TOLERANCE)
    assert result.net_return == pytest.approx(-0.47512, rel=TOLERANCE)
    assert result.gross_return == pytest.approx(-0.3439, rel=TOLERANCE)
    assert result.cost_drag == pytest.approx(0.13122, rel=TOLERANCE)
    assert result.cost_share is None


def test_the_scalars_are_plain_python_types() -> None:
    result = run(H23_OPEN, H23_CLOSE)
    for name in ("total_costs", "gross_final_equity", "net_return", "gross_return", "cost_drag", "cost_share"):
        assert type(getattr(result, name)) is float, name
    assert isinstance(result.costs, pd.Series) and isinstance(result.gross_equity, pd.Series)
    assert result.costs.name == "costs" and result.gross_equity.name == "gross_equity"
    assert result.gross_equity.index.equals(result.equity.index)


# --- flags and the opt-out ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("apply_costs", "costs", "applied", "flags"),
    [
        (True, (0.0, 0.0, 0.0), True, ["zero_costs"]),
        (True, (0.0, 0.0, 0.5), True, []),
        (True, COSTS_25_PERCENT, True, []),
        (False, (0.0, 0.0, 0.0), False, ["zero_costs"]),
        (False, (0.0, 0.0, 0.5), False, ["costs_not_applied"]),
        (False, COSTS_25_PERCENT, False, ["costs_not_applied"]),
    ],
)
def test_the_cost_flags_for_every_combination(apply_costs, costs, applied, flags) -> None:
    result = run(H23_OPEN, H23_CLOSE, costs, apply_costs=apply_costs)
    assert result.costs_applied is applied
    assert [flag.code for flag in result.risk_flags] == flags


def test_the_opt_out_flag_comes_before_the_warmup_flag_and_after_the_spec_flags() -> None:
    spec = make_spec(delay=0, price="close", signal="sma_crossover", costs=(1.0, 2.0, 2.0))
    short = FakeProvider(symbols=("AAA", "BBB"))
    frame = short.get_prices(("AAA", "BBB"), date(2024, 2, 22), date(2024, 4, 30))
    with pytest.warns(Warning):
        result = run_backtest(spec, LiteralProvider(frame), apply_costs=False)
    assert [flag.code for flag in result.risk_flags] == [
        "same_bar_execution",
        "costs_not_applied",
        "insufficient_warmup",
    ]


def assert_same_run(a: BacktestResult, b: BacktestResult) -> None:
    for name in ("equity", "cash", "turnover", "costs", "gross_equity"):
        pd.testing.assert_series_equal(getattr(a, name), getattr(b, name), check_exact=True)
    for name in ("positions", "weights", "trades", "signals", "target_weights"):
        pd.testing.assert_frame_equal(getattr(a, name), getattr(b, name), check_exact=True)
    assert (a.deferred_orders, a.unfilled_orders) == (b.deferred_orders, b.unfilled_orders)


def test_a_zero_cost_spec_is_bit_identical_to_the_opt_out_and_gross_is_net() -> None:
    zero = run(H23_OPEN, H23_CLOSE, (0.0, 0.0, 0.0))
    off = run(H23_OPEN, H23_CLOSE, COSTS_25_PERCENT, apply_costs=False)
    assert_same_run(zero, off)
    for result in (zero, off):
        assert (result.costs == 0).all() and result.total_costs == 0.0
        pd.testing.assert_series_equal(result.gross_equity, result.equity.rename("gross_equity"), check_exact=True)
        assert result.cost_drag == 0.0 and result.net_return == result.gross_return
        assert result.cost_share == 0.0
    assert list(zero.equity) == approx([1000, 1100, 1210, 1331, 1464.1])  # the literals of H1


def test_the_gross_twin_is_the_run_with_zero_costs_bit_for_bit() -> None:
    costly = run(H23_OPEN, H23_CLOSE)
    zero = run(H23_OPEN, H23_CLOSE, (0.0, 0.0, 0.0))
    pd.testing.assert_series_equal(costly.gross_equity, zero.equity.rename("gross_equity"), check_exact=True)


@pytest.mark.parametrize("apply_costs", [True, False])
def test_gross_equity_is_an_independent_copy_when_no_twin_is_run(apply_costs: bool) -> None:
    result = run(H23_OPEN, H23_CLOSE, (0.0, 0.0, 0.0), apply_costs=apply_costs)
    equity, gross = result.equity.iloc[-1], result.gross_equity.iloc[-1]
    assert equity == gross
    result.gross_equity.iloc[-1] = -1.0
    assert result.equity.iloc[-1] == equity
    result.equity.iloc[0] = -2.0
    assert result.gross_equity.iloc[0] == 1000.0
    assert result.gross_equity.name == "gross_equity" and result.equity.name == "equity"


# --- identities and edge cases ------------------------------------------------------------------------------------


def test_per_bar_costs_are_the_fees_of_the_trades_of_that_bar() -> None:
    result = run_backtest(make_spec(rebalance="daily"), FakeProvider(symbols=("AAA", "BBB")))
    by_date = result.trades.groupby("date")["cost"].sum()
    np.testing.assert_allclose(result.costs.loc[by_date.index], by_date, rtol=1e-12)
    assert (result.costs.drop(by_date.index) == 0).all()
    assert result.total_costs == pytest.approx(result.trades["cost"].sum(), rel=1e-12)
    rate = (1.0 + 2.0 + 2.0) / 10_000
    np.testing.assert_allclose(result.trades["cost"], rate * result.trades["notional"].abs(), rtol=1e-12)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_buy_and_hold_net_equity_is_the_gross_equity_over_one_plus_the_rate(seed: int) -> None:
    """Exact for one purchase on a path without holidays: the same shares divided by 1 + r, from the purchase on."""
    spec = make_spec(
        universe=("AAA", "BBB"), start="2023-03-01", end="2023-08-31", signal="buy_and_hold", params={}, costs=(7, 4, 3)
    )
    spec = spec.model_copy(update={"rebalance": "on_signal"})
    result = run_backtest(spec, FakeProvider(symbols=("AAA", "BBB"), seed=seed))
    rate = (7 + 4 + 3) / 10_000
    # With history before the first bar the initial decision executes on the first bar, at its open.
    assert len(result.trades) == 2 and (result.trades["date"] == result.equity.index[0]).all()
    np.testing.assert_allclose(result.equity, result.gross_equity / (1 + rate), rtol=1e-12)
    assert result.net_return == pytest.approx((1 + result.gross_return) / (1 + rate) - 1, rel=1e-9)


@pytest.fixture
def fixture_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    register_up_day(monkeypatch)


def test_a_run_without_trades_has_no_costs_and_no_share(fixture_signal: None) -> None:
    falling = {"A": [100, 99, 98, 97, 96]}
    spec = make_spec(universe=("A",), start="2024-01-02", end="2024-01-08", signal="fixture_up_day", capital=1000)
    with pytest.warns(InsufficientWarmupWarning):  # the test signal needs one row of history that this world lacks
        result = run_backtest(spec, LiteralProvider(price_frame(falling, falling)))
    assert result.trades.empty and result.costs_applied
    assert result.total_costs == 0.0 and result.cost_drag == 0.0
    assert result.gross_return == result.net_return == 0.0
    assert result.cost_share is None  # the gross return is not positive


def test_h23c_a_portfolio_ruined_by_fees_has_a_net_return_of_minus_one(fixture_signal: None) -> None:
    spec = make_spec(universe=("A",), start="2024-01-02", end="2024-01-08", signal="fixture_up_day", capital=1000)
    costs = CostsSpec(commission_bps=0, spread_bps=0, slippage_bps=0, min_commission=500)
    opens = {"A": [100.0] * 5}
    closes = {"A": [100.0, 101.0, 100.0, 100.0, 100.0]}  # one up day, Jan 3: buy on Jan 4, sell on Jan 5
    with pytest.warns(InsufficientWarmupWarning):  # the test signal needs one row of history that this world lacks
        result = run_backtest(spec.model_copy(update={"costs": costs}), LiteralProvider(price_frame(opens, closes)))
    assert list(result.equity) == approx([1000, 1000, 500, 0, 0])
    assert list(result.gross_equity) == approx([1000] * 5)
    assert list(result.costs) == approx([0, 0, 500, 500, 0])
    assert not np.isnan(result.weights.to_numpy()).any() and not np.isnan(result.turnover.to_numpy()).any()
    assert result.total_costs == pytest.approx(1000)
    assert result.net_return == -1.0 and result.gross_return == 0.0
    assert result.cost_drag == 1.0
    assert result.cost_share is None  # the gross return is not positive
    assert list(result.returns) == approx([0, 0, -0.5, -1, 0])  # 0.0 after the ruin, not 0/0 = NaN
