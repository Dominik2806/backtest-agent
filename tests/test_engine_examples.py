"""The three example specs of strategies/ run end to end on FakeProvider with the period moved into the fake history."""

import warnings
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from backtest_agent.data import FakeProvider
from backtest_agent.engine import run_backtest
from backtest_agent.spec import load_spec
from backtest_agent.spec.schema import Period

STRATEGIES = Path(__file__).resolve().parents[1] / "strategies"
EXAMPLES = {"sma_crossover": 199, "momentum_12_1": 252, "buy_and_hold": 0}  # name -> warmup_rows
PERIOD = Period(start=date(2018, 1, 1), end=date(2019, 12, 31))  # the fake history starts in 2015


@pytest.mark.parametrize("name", EXAMPLES)
def test_example_spec_runs_end_to_end(name: str) -> None:
    spec = load_spec(STRATEGIES / f"{name}.yaml").model_copy(update={"period": PERIOD})
    provider = FakeProvider(symbols=spec.universe)
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # enough history: no warning of any kind
        result = run_backtest(spec, provider, allow_short_warmup=False)

    assert result.spec is spec
    assert result.warmup.required_rows == EXAMPLES[name] == spec.warmup_rows
    assert result.warmup.sufficient
    assert result.equity.index[0] == pd.Timestamp("2018-01-01")  # a Monday, and a fake business day
    assert result.equity.index[-1] == pd.Timestamp("2019-12-31")
    assert len(result.data_hash) == 64
    assert not result.validation.has_errors
    assert not result.trades.empty
    assert (result.cash >= 0).all() and (result.weights.sum(axis=1) <= 1 + 1e-9).all()
    assert list(result.positions.columns) == list(spec.universe)

    # The costs of the example specs are non-zero and applied: no flag, fees were paid.
    assert result.costs_applied is True
    assert result.risk_flags == ()
    assert result.total_costs > 0 and result.total_costs == pytest.approx(result.trades["cost"].sum())

    # Only the universe is requested; the benchmark is not loaded in this phase.
    assert [symbols for symbols, _, _ in provider.calls] == [tuple(spec.universe)]


def test_the_examples_trade_as_their_rebalance_rule_says() -> None:
    results = {}
    for name in EXAMPLES:
        spec = load_spec(STRATEGIES / f"{name}.yaml").model_copy(update={"period": PERIOD})
        results[name] = run_backtest(spec, FakeProvider(symbols=spec.universe))

    # buy_and_hold is rebalanced monthly: trading days are the first bar of a month (delay 1 after the month end),
    # plus the first bar of the run itself.
    days = pd.DatetimeIndex(results["buy_and_hold"].trades["date"].unique())
    first_bars = results["buy_and_hold"].equity.groupby(results["buy_and_hold"].equity.index.to_period("M")).head(1)
    assert set(days) <= set(first_bars.index) | {results["buy_and_hold"].equity.index[0]}
    # momentum_12_1 is also monthly; sma_crossover trades on signal changes, so it trades on more days.
    momentum_days = pd.DatetimeIndex(results["momentum_12_1"].trades["date"].unique())
    assert set(momentum_days) <= set(
        results["momentum_12_1"].equity.groupby(results["momentum_12_1"].equity.index.to_period("M")).head(1).index
    ) | {results["momentum_12_1"].equity.index[0]}
    assert results["momentum_12_1"].signals.sum(axis=1).max() == 3  # top_n 3
