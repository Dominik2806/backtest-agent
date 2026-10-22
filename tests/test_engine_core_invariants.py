"""Invariants of the simulation on seeded random worlds, plus input validation of the core.

Every random world uses a fixed seed, so a failure is reproducible. The expected values of the hand-calculated
fixtures are in test_engine_hand_calculated.py; here only properties are checked.
"""

import numpy as np
import pandas as pd
import pytest

from backtest_agent.engine import EngineError, EngineInvariantError, simulate, simulate_signals
from backtest_agent.spec.schema import ExecutionSpec, SizingSpec
from engine_helpers import NAN, run

SEEDS = range(8)
CONFIGS = [(0, "close"), (1, "open"), (1, "close"), (2, "open")]
RULES = ["daily", "weekly", "monthly", "on_signal"]
SYMBOLS = ["A", "B", "C"]
N_BARS = 120


def world(seed: int):
    """Random prices with holidays (never on the first bar) and piecewise constant, partly fractional signals."""
    rng = np.random.default_rng(seed)
    k = len(SYMBOLS)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.02, (N_BARS, k)), axis=0))
    open_ = close * np.exp(rng.normal(0.0, 0.005, (N_BARS, k)))
    holidays = rng.random((N_BARS, k)) < 0.1
    holidays[0] = False
    close[holidays] = np.nan
    open_[holidays] = np.nan
    blocks = rng.random((N_BARS // 6 + 1, k))
    raw = np.repeat(blocks, 6, axis=0)[:N_BARS]
    signal = np.where(raw > 0.5, 1.0, 0.0)
    signal = np.where((raw > 0.3) & (raw <= 0.5), 0.5, signal)  # some fractional exposure
    index = pd.bdate_range("2024-01-02", periods=N_BARS, name="date")
    columns = pd.Index(SYMBOLS, name="symbol")
    return (
        pd.DataFrame(open_, index=index, columns=columns),
        pd.DataFrame(close, index=index, columns=columns),
        pd.DataFrame(signal, index=index, columns=columns),
    )


def simulate_world(
    opens,
    closes,
    signals,
    *,
    rebalance="on_signal",
    delay=1,
    price="open",
    method="equal_weight",
    capital=1000.0,
    first=20,
):
    sizing = SizingSpec(method=method, fraction=0.4 if method == "fixed_fraction" else None)
    execution = ExecutionSpec(delay_bars=delay, price=price, allow_same_bar_execution=delay == 0)
    return simulate_signals(opens, closes, signals, sizing, execution, rebalance, capital, closes.index[first])


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("rebalance", RULES)
@pytest.mark.parametrize(("delay", "price"), CONFIGS)
@pytest.mark.parametrize("method", ["equal_weight", "fixed_fraction"])
def test_portfolio_rules_hold_on_random_worlds(seed, rebalance, delay, price, method) -> None:
    opens, closes, signals = world(seed)
    p = simulate_world(opens, closes, signals, rebalance=rebalance, delay=delay, price=price, method=method)
    assert (p.cash >= 0).all()
    assert (p.positions.to_numpy() >= 0).all()
    assert (p.weights.to_numpy() >= 0).all()
    assert (p.weights.sum(axis=1) <= 1.0 + 1e-9).all()
    assert (p.equity > 0).all()
    np.testing.assert_allclose(p.weights.sum(axis=1) + p.cash / p.equity, 1.0, rtol=0, atol=1e-9)
    assert (p.turnover >= 0).all()
    assert p.deferred_orders >= p.unfilled_orders >= 0
    np.testing.assert_allclose(p.trades["notional"], p.trades["shares"] * p.trades["price"], rtol=1e-12)


@pytest.mark.parametrize("seed", SEEDS)
def test_nothing_happens_before_the_first_bar(seed) -> None:
    opens, closes, signals = world(seed)
    p = simulate_world(opens, closes, signals, first=30)
    assert p.equity.index[0] == closes.index[30]
    assert len(p.equity) == N_BARS - 30
    assert (p.trades["date"] >= closes.index[30]).all()


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("rebalance", RULES)
def test_the_same_input_gives_identical_results(seed, rebalance) -> None:
    opens, closes, signals = world(seed)
    a = simulate_world(opens, closes, signals, rebalance=rebalance)
    b = simulate_world(opens.copy(), closes.copy(), signals.copy(), rebalance=rebalance)
    pd.testing.assert_series_equal(a.equity, b.equity, check_exact=True)
    pd.testing.assert_frame_equal(a.positions, b.positions, check_exact=True)
    pd.testing.assert_frame_equal(a.trades, b.trades, check_exact=True)
    assert (a.deferred_orders, a.unfilled_orders) == (b.deferred_orders, b.unfilled_orders)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("rebalance", RULES)
def test_permuting_the_symbols_does_not_change_the_equity(seed, rebalance) -> None:
    opens, closes, signals = world(seed)
    order = ["C", "A", "B"]
    a = simulate_world(opens, closes, signals, rebalance=rebalance)
    b = simulate_world(opens[order], closes[order], signals[order], rebalance=rebalance)
    np.testing.assert_allclose(a.equity, b.equity, rtol=1e-9)
    np.testing.assert_allclose(a.cash, b.cash, rtol=1e-9, atol=1e-9)
    assert (a.deferred_orders, a.unfilled_orders) == (b.deferred_orders, b.unfilled_orders)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("rebalance", RULES)
def test_doubling_the_capital_doubles_everything_in_money(seed, rebalance) -> None:
    opens, closes, signals = world(seed)
    one = simulate_world(opens, closes, signals, rebalance=rebalance, capital=1000.0)
    two = simulate_world(opens, closes, signals, rebalance=rebalance, capital=2000.0)
    np.testing.assert_allclose(two.equity, 2 * one.equity, rtol=1e-9)
    np.testing.assert_allclose(two.positions, 2 * one.positions, rtol=1e-9, atol=1e-12)
    np.testing.assert_allclose(two.turnover, one.turnover, rtol=1e-9, atol=1e-12)
    np.testing.assert_allclose(two.returns, one.returns, rtol=1e-9, atol=1e-12)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("rebalance", RULES)
@pytest.mark.parametrize(("delay", "price"), CONFIGS)
def test_prices_after_a_date_do_not_change_the_past(seed, rebalance, delay, price) -> None:
    """Causality of the engine: with the signals given, changing prices after T leaves everything up to T alone."""
    opens, closes, signals = world(seed)
    cut = 70
    factor = np.random.default_rng(1000 + seed).uniform(0.5, 1.5, (N_BARS - cut - 1, len(SYMBOLS)))
    changed_opens, changed_closes = opens.copy(), closes.copy()
    changed_opens.iloc[cut + 1 :] = opens.iloc[cut + 1 :].to_numpy() * factor
    changed_closes.iloc[cut + 1 :] = closes.iloc[cut + 1 :].to_numpy() * factor
    a = simulate_world(opens, closes, signals, rebalance=rebalance, delay=delay, price=price)
    b = simulate_world(changed_opens, changed_closes, signals, rebalance=rebalance, delay=delay, price=price)
    last = closes.index[cut]
    pd.testing.assert_series_equal(a.equity.loc[:last], b.equity.loc[:last], check_exact=True)
    pd.testing.assert_series_equal(a.cash.loc[:last], b.cash.loc[:last], check_exact=True)
    pd.testing.assert_frame_equal(a.positions.loc[:last], b.positions.loc[:last], check_exact=True)
    pd.testing.assert_frame_equal(
        a.trades[a.trades["date"] <= last], b.trades[b.trades["date"] <= last], check_exact=True
    )


def test_an_order_that_never_gets_a_price_is_reported_as_unfilled() -> None:
    p = run({"A": [100, 100, NAN]}, {"A": [100, 100, NAN]}, {"A": [1, 0, 0]})
    assert list(p.positions["A"]) == [0, 10, 10]  # the sale on the last bar cannot happen
    assert (p.deferred_orders, p.unfilled_orders) == (1, 1)


def test_a_symbol_that_never_had_a_price_cannot_get_an_order() -> None:
    prices = {"A": [100, 100, 100], "B": [NAN, NAN, 50]}
    with pytest.raises(EngineError, match="never had a price"):
        run(prices, prices, {"A": [1, 1, 1], "B": [1, 1, 1]})


class _FixedCost:
    """A custom model that is not to be trusted: it returns whatever it was given."""

    def __init__(self, value: float) -> None:
        self.value = value

    def cost(self, symbol: str, notional: float) -> float:
        return self.value


# The test below relies on the funding rule calling the model once for planning (the fee of the buy at the cap) before
# the fill is booked: the first call is free, every later call is expensive.
class _ChangesItsMind:
    """Says trading is free while the core plans the fill and charges a fortune when the fill is booked."""

    def __init__(self) -> None:
        self.calls = 0

    def cost(self, symbol: str, notional: float) -> float:
        self.calls += 1
        return 0.0 if self.calls == 1 else 10 * notional


def _run_with(model) -> None:
    opens, closes, signals = world(0)
    sizing, execution = SizingSpec(method="equal_weight"), ExecutionSpec()
    simulate_signals(opens, closes, signals, sizing, execution, "daily", 1000.0, closes.index[0], model)


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf"), float("-inf")])
def test_a_cost_model_that_returns_an_invalid_cost_is_an_invariant_error(value: float) -> None:
    with pytest.raises(EngineInvariantError, match="cost model returned"):
        _run_with(_FixedCost(value))


def test_a_cost_model_that_makes_cash_negative_is_an_invariant_error() -> None:
    with pytest.raises(EngineInvariantError, match="cash became negative"):
        _run_with(_ChangesItsMind())


def _inputs():
    idx = pd.bdate_range("2024-01-02", periods=3, name="date")
    cols = pd.Index(["A"], name="symbol")
    prices = pd.DataFrame({"A": [100.0, 100.0, 100.0]}, index=idx)
    prices.columns = cols
    weights = pd.DataFrame({"A": [1.0, 1.0, 1.0]}, index=idx)
    weights.columns = cols
    return prices, prices.copy(), weights, pd.Series([False, True, False], index=idx)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda o, c, w, r: (o, c, w, r, {"price_rule": "mid"}), "price_rule"),
        (lambda o, c, w, r: (o, c, w, r, {"initial_capital": 0.0}), "initial_capital"),
        (lambda o, c, w, r: (o, c, w, r, {"initial_capital": float("nan")}), "initial_capital"),
        (lambda o, c, w, r: (o, c, w * 1.5, r, {}), "between 0 and 1"),
        (lambda o, c, w, r: (o, c, w * -0.5, r, {}), "between 0 and 1"),
        (lambda o, c, w, r: (o.iloc[:2], c, w, r, {}), "same bars and symbols"),
        (lambda o, c, w, r: (o, c, w, r.iloc[:2], {}), "same bars"),
        (lambda o, c, w, r: (o, c, w, r.astype(int), {}), "boolean"),
        (lambda o, c, w, r: (o.assign(A=[100.0, NAN, 100.0]), c, w, r, {}), "NaN on exactly the same bars"),
        (lambda o, c, w, r: (o, c.assign(A=[100.0, -1.0, 100.0]), w, r, {}), "positive and finite"),
        (lambda o, c, w, r: (o.iloc[:0], c.iloc[:0], w.iloc[:0], r.iloc[:0], {}), "at least one bar"),
    ],
)
def test_bad_inputs_are_rejected(change, message) -> None:
    o, c, w, r, extra = change(*_inputs())
    kwargs = {"initial_capital": 1000.0, "price_rule": "open"} | extra
    with pytest.raises(EngineError, match=message):
        simulate(o, c, w, r, **kwargs)


def test_weights_that_add_up_to_more_than_one_are_rejected() -> None:
    idx = pd.bdate_range("2024-01-02", periods=2, name="date")
    cols = pd.Index(["A", "B"], name="symbol")
    prices = pd.DataFrame(100.0, index=idx, columns=cols)
    weights = pd.DataFrame(0.6, index=idx, columns=cols)
    with pytest.raises(EngineError, match="more than 1"):
        simulate(prices, prices, weights, pd.Series([True, False], index=idx), 1000.0, "open")


def test_a_first_bar_after_the_last_bar_is_rejected() -> None:
    opens, closes, signals = world(0)
    sizing, execution = SizingSpec(method="equal_weight"), ExecutionSpec()
    with pytest.raises(EngineError, match="no bar on or after"):
        simulate_signals(opens, closes, signals, sizing, execution, "daily", 1000.0, pd.Timestamp("2030-01-01"))
