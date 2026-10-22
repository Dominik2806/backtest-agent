"""Zero-cost equivalence: an all-zero cost model changes nothing compared with free trading (Phase 4 behaviour).

The scenarios are the inputs of the part 1 fixtures H1 to H13 and H15 (inputs only, no expected values; those are in
test_engine_hand_calculated.py and test_engine_warmup_marks.py) and the random worlds of the core invariant tests. The
comparison is exact: no tolerance, bit-identical frames and trades.
"""

import pandas as pd
import pytest

from backtest_agent.engine import BpsCosts, NoCosts, Portfolio, simulate_signals
from backtest_agent.spec.schema import ExecutionSpec, SizingSpec
from engine_helpers import NAN, run
from test_engine_core_invariants import CONFIGS, RULES, SEEDS, world

H1_OPEN = [100, 100, 110, 121, 133.1]
H1_CLOSE = [100, 110, 121, 133.1, 146.41]
H5 = {"opens": {"A": [100, 100, 125, 150], "B": [50] * 4}, "closes": {"A": [100, 120, 150, 150], "B": [50] * 4}}
H5_SIGNAL = {"A": [1] * 4, "B": [1] * 4}
WEEK_PRICE = [100, 100, 110, 120, 130, 130, 130, 130, 130, 130, 130]
WEEK = {"opens": {"A": WEEK_PRICE}, "closes": {"A": WEEK_PRICE}, "signals": {"A": [1, 1] + [0] * 9}}
H9 = {"opens": {"A": [100] * 3, "B": [50] * 3}, "closes": {"A": [100] * 3, "B": [50] * 3}}


def scenario(opens, closes, signals, **kwargs):
    return {"opens": opens, "closes": closes, "signals": signals, **kwargs}


SCENARIOS = {
    "h1": scenario({"A": H1_OPEN}, {"A": H1_CLOSE}, {"A": [1] * 5}),
    "h2": scenario({"A": H1_OPEN}, {"A": H1_CLOSE}, {"A": [1, 1, 0, 0, 0]}),
    "h3": scenario(
        {"A": [100, 100, 125, 150, 200]}, {"A": [100, 120, 130, 160, 190]}, {"A": [1, 1, 0, 0, 0]}, delay_bars=2
    ),
    "h4": scenario({"A": H1_OPEN}, {"A": H1_CLOSE}, {"A": [1, 1, 0, 0, 0]}, delay_bars=0, price="close"),
    "h5_daily": scenario(**H5, signals=H5_SIGNAL, rebalance="daily"),
    "h5_on_signal": scenario(**H5, signals=H5_SIGNAL, rebalance="on_signal"),
    "h6": scenario(**WEEK, rebalance="weekly"),
    "h7": scenario(
        {"A": [100, 100, 100, 125, 150, 150, 175]},
        {"A": [100, 100, 100, 125, 150, 150, 175]},
        {"A": [0, 1, 1, 1, 0, 0, 0]},
        start="2024-01-29",
        rebalance="monthly",
    ),
    "h8_mid_week": scenario(**WEEK, rebalance="weekly", first_bar="2024-01-03"),
    "h8_dropped": scenario(**WEEK, rebalance="weekly", first_bar="2024-01-05"),
    "h9a": scenario(
        **H9, signals={"A": [1] * 3, "B": [1] * 3}, rebalance="daily", method="fixed_fraction", fraction=0.6
    ),
    "h9b": scenario(
        **H9, signals={"A": [1] * 3, "B": [0] * 3}, rebalance="daily", method="fixed_fraction", fraction=0.6
    ),
    "h9c": scenario(
        **H9, signals={"A": [1] * 3, "B": [1] * 3}, rebalance="daily", method="fixed_fraction", fraction=0.3
    ),
    "h10": scenario({"A": [100, 100, 120]}, {"A": [100, 120, 120]}, {"A": [0.5] * 3}),
    "h11": scenario(
        {"A": [100, 100, 120, 120], "B": [50, NAN, 50, 50]},
        {"A": [100, 120, 120, 120], "B": [50, NAN, 50, 60]},
        {"A": [1] * 4, "B": [1] * 4},
    ),
    "h12": scenario(
        {"A": [100, 100, NAN, 100, 100], "B": [50] * 5},
        {"A": [100, 100, NAN, 100, 100], "B": [50, 50, 50, 50, 60]},
        {"A": [1, 0, 0, 0, 0], "B": [1] * 5},
    ),
    "h13": scenario({"A": H1_OPEN}, {"A": H1_CLOSE}, {"A": [1] * 5}, first_bar="2024-01-03"),
    "h15": scenario(
        {"A": [100, 100, 100, 120], "B": [50, 50, NAN, 50]},
        {"A": [100, 100, 110, 120], "B": [50, 50, NAN, 70]},
        {"A": [1] * 4, "B": [1] * 4},
        first_bar="2024-01-04",
    ),
}


def assert_identical(a: Portfolio, b: Portfolio) -> None:
    for name in ("equity", "cash", "turnover", "costs"):
        pd.testing.assert_series_equal(getattr(a, name), getattr(b, name), check_exact=True)
    for name in ("positions", "weights", "trades"):
        pd.testing.assert_frame_equal(getattr(a, name), getattr(b, name), check_exact=True)
    assert (a.deferred_orders, a.unfilled_orders) == (b.deferred_orders, b.unfilled_orders)
    assert a.initial_equity == b.initial_equity


@pytest.mark.parametrize("name", SCENARIOS)
def test_an_all_zero_cost_model_equals_free_trading_on_the_fixture_inputs(name: str) -> None:
    free = run(**SCENARIOS[name], cost_model=NoCosts())
    zero = run(**SCENARIOS[name], cost_model=BpsCosts(0, 0, 0, 0))
    assert_identical(free, zero)
    assert (free.trades["cost"] == 0).all() and (zero.costs == 0).all()
    assert_identical(free, run(**SCENARIOS[name]))  # the default is free trading too


def simulate_world(seed: int, rebalance: str, delay: int, price: str, method: str, model) -> Portfolio:
    opens, closes, signals = world(seed)
    sizing = SizingSpec(method=method, fraction=0.4 if method == "fixed_fraction" else None)
    execution = ExecutionSpec(delay_bars=delay, price=price, allow_same_bar_execution=delay == 0)
    return simulate_signals(opens, closes, signals, sizing, execution, rebalance, 1000.0, closes.index[20], model)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("rebalance", RULES)
@pytest.mark.parametrize(("delay", "price"), CONFIGS)
@pytest.mark.parametrize("method", ["equal_weight", "fixed_fraction"])
def test_an_all_zero_cost_model_equals_free_trading_on_the_random_worlds(seed, rebalance, delay, price, method) -> None:
    free = simulate_world(seed, rebalance, delay, price, method, NoCosts())
    zero = simulate_world(seed, rebalance, delay, price, method, BpsCosts(0, 0, 0, 0))
    assert_identical(free, zero)
    assert not free.trades.empty
