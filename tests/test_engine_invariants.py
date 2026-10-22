"""Invariants of whole runs (provider, warm-up, signals, engine) with the built-in signals on seeded fake worlds.

Every world has a fixed seed, so a failure is reproducible. The hand-calculated expected values are in
test_engine_hand_calculated.py and test_engine_runner.py; here only properties are checked.
"""

import functools
import itertools
from datetime import date

import numpy as np
import pandas as pd
import pytest

from backtest_agent.data import FakeProvider
from backtest_agent.engine import BacktestResult, run_backtest
from runner_helpers import HolidayProvider, LiteralProvider, PerturbedProvider, make_spec

SYMBOLS = ("AAA", "BBB", "CCC")
START, END = "2023-03-01", "2023-08-31"
SIGNALS = {
    "sma_crossover": {"fast": 5, "slow": 20},
    "momentum_12_1": {"lookback_days": 30, "skip_days": 5, "top_n": 2, "positive_only": False},
    "buy_and_hold": {},
}
RULES = ["daily", "weekly", "monthly", "on_signal"]
CONFIGS = [(0, "close"), (1, "open"), (1, "close"), (2, "open")]
SEEDS = [0, 1]


def spec_for(signal: str, rebalance: str, delay: int, price: str, universe=SYMBOLS, capital: float = 100000):
    return make_spec(
        universe=universe,
        start=START,
        end=END,
        signal=signal,
        params=SIGNALS[signal],
        rebalance=rebalance,
        delay=delay,
        price=price,
        capital=capital,
    )


def world(seed: int, universe=SYMBOLS) -> HolidayProvider:
    """Fake prices with random holidays of single symbols, so orders get deferred through the runner too."""
    return HolidayProvider(FakeProvider(symbols=SYMBOLS, seed=seed), seed=seed)


@functools.cache
def cached_run(signal: str, rebalance: str, delay: int, price: str, seed: int) -> BacktestResult:
    return run_backtest(spec_for(signal, rebalance, delay, price), world(seed))


CASES = list(itertools.product(SIGNALS, RULES, CONFIGS, SEEDS))
CASE_IDS = [f"{s}-{r}-d{c[0]}-{c[1]}-seed{seed}" for s, r, c, seed in CASES]


@pytest.mark.parametrize(("signal", "rebalance", "config", "seed"), CASES, ids=CASE_IDS)
def test_cash_is_never_negative_and_weights_never_exceed_100_percent(signal, rebalance, config, seed) -> None:
    result = cached_run(signal, rebalance, *config, seed)
    assert (result.cash >= 0).all()
    assert (result.positions.to_numpy() >= 0).all()
    weights = result.weights.to_numpy()
    assert (weights >= 0).all() and (weights <= 1 + 1e-9).all()
    assert (weights.sum(axis=1) <= 1 + 1e-9).all()
    np.testing.assert_allclose(result.cash / result.equity + result.weights.sum(axis=1), 1.0, rtol=1e-9)
    assert (result.turnover >= 0).all() and result.deferred_orders >= 0 and result.unfilled_orders >= 0


@pytest.mark.parametrize(("signal", "rebalance", "config", "seed"), CASES, ids=CASE_IDS)
def test_nothing_happens_before_period_start(signal, rebalance, config, seed) -> None:
    result = cached_run(signal, rebalance, *config, seed)
    start = pd.Timestamp(START)
    frames = (result.equity, result.cash, result.positions, result.weights, result.turnover, result.signals)
    assert all(frame.index.min() >= start for frame in frames)
    assert result.target_weights.index.min() >= start
    assert result.trades.empty or result.trades["date"].min() >= start
    assert result.equity.index[0] == result.equity.index[result.equity.index >= start][0]


@pytest.mark.parametrize(("signal", "rebalance", "config", "seed"), CASES, ids=CASE_IDS)
def test_identical_repeat_runs_give_identical_results_including_the_hash(signal, rebalance, config, seed) -> None:
    first = cached_run(signal, rebalance, *config, seed)
    second = run_backtest(spec_for(signal, rebalance, *config), world(seed))
    assert first.data_hash == second.data_hash
    assert_same_path(first, second)
    assert first.warmup == second.warmup
    assert first.risk_flags == second.risk_flags
    assert first.validation == second.validation


def assert_same_path(a: BacktestResult, b: BacktestResult) -> None:
    pd.testing.assert_series_equal(a.equity, b.equity)
    pd.testing.assert_series_equal(a.cash, b.cash)
    pd.testing.assert_series_equal(a.turnover, b.turnover)
    for name in ("positions", "weights", "trades", "signals", "target_weights"):
        pd.testing.assert_frame_equal(getattr(a, name), getattr(b, name))
    assert (a.deferred_orders, a.unfilled_orders) == (b.deferred_orders, b.unfilled_orders)


@pytest.mark.parametrize("seed", [0, 1, 2])
@pytest.mark.parametrize("rebalance", RULES)
@pytest.mark.parametrize(("delay", "price"), CONFIGS)
def test_buy_and_hold_of_one_asset_equals_the_asset_return(delay: int, price: str, rebalance: str, seed: int) -> None:
    provider = LiteralProvider(
        FakeProvider(symbols=("AAA",), seed=seed).get_prices(["AAA"], date(2015, 1, 1), date(2030, 1, 1))
    )
    spec = make_spec(
        universe=("AAA",), start=START, end=END, signal="buy_and_hold", rebalance=rebalance, delay=delay, price=price
    )
    result = run_backtest(
        spec, provider, apply_costs=False
    )  # the exact asset return; with costs see test_engine_runner_costs
    frame = provider.last_frame
    prices = frame["AAA"]
    first = result.equity.index[0]
    # Independent calculation from the delivered frame: the initial decision executes on the first bar.
    fill = prices.loc[first, price]
    expected = spec.initial_capital * prices["close"].loc[first:] / fill
    np.testing.assert_allclose(result.equity, expected, rtol=1e-9)
    asset_return = prices["close"].iloc[-1] / fill - 1.0
    assert result.equity.iloc[-1] / spec.initial_capital - 1.0 == pytest.approx(asset_return, rel=1e-9)
    assert result.trades["shares"].iloc[0] == pytest.approx(spec.initial_capital / fill, rel=1e-12)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("signal", SIGNALS)
@pytest.mark.parametrize("rebalance", RULES)
@pytest.mark.parametrize(("delay", "price"), [(1, "open"), (0, "close")])
def test_permuting_the_universe_does_not_change_the_equity(signal, rebalance, delay, price, seed) -> None:
    ordered = run_backtest(spec_for(signal, rebalance, delay, price, SYMBOLS), world(seed))
    permuted = run_backtest(spec_for(signal, rebalance, delay, price, SYMBOLS[::-1]), world(seed))
    np.testing.assert_allclose(ordered.equity, permuted.equity, rtol=1e-10)
    np.testing.assert_allclose(ordered.cash, permuted.cash, rtol=1e-10, atol=1e-8)
    assert ordered.data_hash == permuted.data_hash  # the hash does not depend on the symbol order
    key = ["date", "symbol"]
    # A deferred buy scaled down to float residue of cash can fill a few 1e-14 shares in one order of summation and
    # none in the other; trades below one millionth of a currency unit are float dust and not compared.
    real = lambda trades: trades[trades["notional"].abs() > 1e-6].sort_values(key).reset_index(drop=True)  # noqa: E731
    left, right = real(ordered.trades), real(permuted.trades)
    pd.testing.assert_frame_equal(left[key], right[key])
    np.testing.assert_allclose(
        left["shares"], right["shares"], rtol=1e-9, atol=1e-7
    )  # rebalance trades are differences


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("signal", SIGNALS)
@pytest.mark.parametrize("rebalance", RULES)
@pytest.mark.parametrize(("delay", "price"), [(1, "open"), (2, "open")])
def test_doubling_the_initial_capital_doubles_the_equity(signal, rebalance, delay, price, seed) -> None:
    base = run_backtest(spec_for(signal, rebalance, delay, price, capital=100000), world(seed))
    double = run_backtest(spec_for(signal, rebalance, delay, price, capital=200000), world(seed))
    np.testing.assert_allclose(double.equity, 2 * base.equity, rtol=1e-9)
    np.testing.assert_allclose(double.cash, 2 * base.cash, rtol=1e-9, atol=1e-6)
    np.testing.assert_allclose(double.positions, 2 * base.positions, rtol=1e-9, atol=1e-9)
    np.testing.assert_allclose(double.weights, base.weights, rtol=1e-9, atol=1e-12)
    np.testing.assert_allclose(double.turnover, base.turnover, rtol=1e-9, atol=1e-12)
    pd.testing.assert_frame_equal(double.trades[["date", "symbol"]], base.trades[["date", "symbol"]])
    pd.testing.assert_frame_equal(double.signals, base.signals)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("signal", SIGNALS)
@pytest.mark.parametrize("rebalance", RULES)
@pytest.mark.parametrize(("delay", "price"), CONFIGS)
def test_changing_all_prices_after_a_date_changes_nothing_up_to_it(signal, rebalance, delay, price, seed) -> None:
    """Causality of the whole run: the perturbed provider makes the future different, the past must not notice."""
    spec = spec_for(signal, rebalance, delay, price)
    original = run_backtest(spec, world(seed))
    cutoff = original.equity.index[len(original.equity) // 2]
    perturbed = run_backtest(spec, PerturbedProvider(world(seed), after=cutoff, seed=seed + 100))

    assert perturbed.data_hash != original.data_hash  # the perturbation really happened
    up_to = slice(None, cutoff)
    pd.testing.assert_series_equal(perturbed.equity.loc[up_to], original.equity.loc[up_to])
    pd.testing.assert_series_equal(perturbed.cash.loc[up_to], original.cash.loc[up_to])
    pd.testing.assert_series_equal(perturbed.turnover.loc[up_to], original.turnover.loc[up_to])
    for name in ("positions", "weights", "signals", "target_weights"):
        pd.testing.assert_frame_equal(getattr(perturbed, name).loc[up_to], getattr(original, name).loc[up_to])
    before = lambda result: result.trades[result.trades["date"] <= cutoff].reset_index(drop=True)  # noqa: E731
    pd.testing.assert_frame_equal(before(perturbed), before(original))
    assert perturbed.warmup == original.warmup


def test_the_causality_test_has_teeth() -> None:
    """After the cutoff a buy-and-hold portfolio does notice the changed prices (the check above can fail)."""
    spec = spec_for("buy_and_hold", "daily", 1, "open")
    original = run_backtest(spec, world(0))
    cutoff = original.equity.index[len(original.equity) // 2]
    perturbed = run_backtest(spec, PerturbedProvider(world(0), after=cutoff, seed=100))
    assert not perturbed.equity.loc[cutoff:].iloc[1:].equals(original.equity.loc[cutoff:].iloc[1:])
