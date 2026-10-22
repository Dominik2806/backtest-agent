"""Properties of the costs on seeded random worlds and on flat-price worlds (see "Costs" in docs/engine.md).

Only properties are checked here; the hand-calculated expected values are in test_engine_costs_hand_calculated.py.
"""

import numpy as np
import pandas as pd
import pytest

from backtest_agent.engine import BpsCosts, Portfolio, simulate_signals
from backtest_agent.spec.schema import ExecutionSpec, SizingSpec
from engine_helpers import frame
from test_engine_core_invariants import CONFIGS, RULES, SEEDS, world


def simulate_world(seed: int, rebalance: str, delay: int, price: str, model, method: str = "equal_weight") -> Portfolio:
    opens, closes, signals = world(seed)
    sizing = SizingSpec(method=method, fraction=0.4 if method == "fixed_fraction" else None)
    execution = ExecutionSpec(delay_bars=delay, price=price, allow_same_bar_execution=delay == 0)
    return simulate_signals(opens, closes, signals, sizing, execution, rebalance, 1000.0, closes.index[20], model)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("rebalance", RULES)
@pytest.mark.parametrize(("delay", "price"), CONFIGS)
def test_without_a_minimum_fee_costs_are_the_combined_rate_times_the_traded_notional(
    seed, rebalance, delay, price
) -> None:
    rate = (7 + 4 + 3) / 10_000
    p = simulate_world(seed, rebalance, delay, price, BpsCosts(7, 4, 3))
    assert not p.trades.empty
    traded = p.trades["notional"].abs()
    np.testing.assert_allclose(p.trades["cost"], rate * traded, rtol=1e-12)
    assert p.total_costs == pytest.approx(rate * traded.sum(), rel=1e-12)
    assert p.total_costs == pytest.approx(p.trades["cost"].sum(), rel=1e-12)
    # Every currency unit that left the cash went into shares or into fees.
    spent = p.trades["notional"].sum() + p.total_costs
    assert p.cash.iloc[-1] == pytest.approx(1000.0 - spent, abs=1e-8)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("rebalance", RULES)
@pytest.mark.parametrize(("delay", "price"), CONFIGS)
@pytest.mark.parametrize("method", ["equal_weight", "fixed_fraction"])
@pytest.mark.parametrize(
    "model", [BpsCosts(20, 10, 10), BpsCosts(500, 300, 200, min_commission=15), BpsCosts(0, 0, 0, min_commission=40)]
)
def test_cash_and_positions_are_never_negative_with_costs(seed, rebalance, delay, price, method, model) -> None:
    p = simulate_world(seed, rebalance, delay, price, model, method)
    assert (p.cash >= 0).all()
    assert (p.positions.to_numpy() >= 0).all()
    assert np.isfinite(p.weights.to_numpy()).all() and np.isfinite(p.turnover.to_numpy()).all()
    assert (p.weights.sum(axis=1) <= 1.0 + 1e-9).all()
    assert (p.costs >= 0).all() and (p.trades["cost"] >= 0).all()
    assert p.total_costs > 0
    assert p.deferred_orders >= p.unfilled_orders >= 0


def buy_and_hold(seed: int, model: BpsCosts) -> Portfolio:
    """Two assets on random prices without holidays, bought once on the second bar and held."""
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.02, (60, 2)), axis=0))
    open_ = close * np.exp(rng.normal(0.0, 0.005, (60, 2)))
    cols = {s: close[:, k] for k, s in enumerate("AB")}
    signals = {"A": [1.0] * 60, "B": [1.0] * 60}
    opens = frame({s: open_[:, k] for k, s in enumerate("AB")})
    return simulate_signals(
        opens,
        frame(cols),
        frame(signals),
        SizingSpec(method="equal_weight"),
        ExecutionSpec(),
        "on_signal",
        1000.0,
        opens.index[0],
        model,
    )


LEVELS = {
    "commission_bps": [0.0, 1.0, 5.0, 25.0, 100.0],
    "spread_bps": [0.0, 1.0, 5.0, 25.0, 100.0],
    "slippage_bps": [0.0, 1.0, 5.0, 25.0, 100.0],
    "min_commission": [0.0, 0.5, 2.0, 10.0, 40.0],  # the base commission of 5 bps is 0.25 on a trade of 500
}


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("component", LEVELS)
def test_buy_and_hold_final_equity_falls_strictly_with_each_cost_component(seed: int, component: str) -> None:
    base = {"commission_bps": 5.0, "spread_bps": 0.0, "slippage_bps": 0.0, "min_commission": 0.0}
    finals = [
        buy_and_hold(seed, BpsCosts(**(base | {component: level}))).equity.iloc[-1] for level in LEVELS[component]
    ]
    assert all(later < earlier for earlier, later in zip(finals, finals[1:], strict=False)), finals


# A flat price world: every round trip of the signal loses the same fraction of the equity, so more round trips mean
# strictly more turnover and strictly more costs, with nothing else changing between the runs.
FLAT_BARS = 24
MODELS = [
    BpsCosts(10, 0, 0),
    BpsCosts(0, 5, 5),
    BpsCosts(5, 5, 5, min_commission=0.5),
    BpsCosts(0, 0, 0, min_commission=1),
]


def round_trips(k: int, model: BpsCosts) -> Portfolio:
    price = {"A": [100.0] * FLAT_BARS}
    signal = {"A": [1.0, 0.0] * k + [0.0] * (FLAT_BARS - 2 * k)}
    return simulate_signals(
        frame(price),
        frame(price),
        frame(signal),
        SizingSpec(method="equal_weight"),
        ExecutionSpec(),
        "on_signal",
        1000.0,
        pd.Timestamp("2024-01-02"),
        model,
    )


@pytest.mark.parametrize("model", MODELS)
def test_adding_a_round_trip_strictly_raises_turnover_and_total_costs(model: BpsCosts) -> None:
    runs = [round_trips(k, model) for k in range(9)]
    turnover = [float(p.turnover.sum()) for p in runs]
    costs = [p.total_costs for p in runs]
    notional = [float(p.trades["notional"].abs().sum()) for p in runs]
    assert turnover[0] == 0.0 and costs[0] == 0.0
    for series in (turnover, costs, notional):
        assert all(later > earlier for earlier, later in zip(series, series[1:], strict=False)), series
    assert [len(p.trades) for p in runs] == [2 * k for k in range(9)]
