"""benchmark_spec: the derived buy-and-hold spec of docs/metrics.md, "The benchmark"."""

import pytest

from backtest_agent.metrics import benchmark_spec
from runner_helpers import make_spec


def test_the_derived_fields() -> None:
    spec = make_spec(universe=("AAA", "BBB"), benchmark="SPY", capital=12345, costs=(1.0, 2.0, 3.0))
    bench = benchmark_spec(spec)
    assert bench.universe == ["SPY"]
    assert bench.signal.id == "buy_and_hold" and bench.signal.params == {}
    assert bench.sizing.method == "equal_weight" and bench.sizing.fraction is None
    assert bench.rebalance == "on_signal"
    assert bench.benchmark == "SPY"
    assert bench.name == f"{spec.name} (benchmark SPY)"


def test_period_capital_execution_and_costs_are_copied() -> None:
    spec = make_spec(delay=1, price="close", capital=777, costs=(4.0, 5.0, 6.0))
    bench = benchmark_spec(spec)
    assert bench.period == spec.period
    assert bench.initial_capital == 777
    assert bench.execution == spec.execution
    assert bench.costs == spec.costs
    assert bench.data == spec.data and bench.description == spec.description
    assert bench.schema_version == spec.schema_version


def test_delay_zero_with_close_prices_and_the_same_bar_flag_are_copied() -> None:
    spec = make_spec(delay=0, price="close")
    bench = benchmark_spec(spec)
    assert (bench.execution.delay_bars, bench.execution.price) == (0, "close")
    assert bench.execution.allow_same_bar_execution is True
    assert bench.execution == spec.execution


def test_a_fixed_fraction_strategy_gets_a_fully_invested_benchmark() -> None:
    spec = make_spec(method="fixed_fraction", fraction=0.5)
    bench = benchmark_spec(spec)
    assert spec.sizing.method == "fixed_fraction"
    assert bench.sizing.method == "equal_weight" and bench.sizing.fraction is None


@pytest.mark.parametrize("rebalance", ["daily", "weekly", "monthly", "on_signal"])
def test_the_rebalance_is_on_signal_whatever_the_strategy_does(rebalance: str) -> None:
    assert benchmark_spec(make_spec(rebalance=rebalance)).rebalance == "on_signal"


def test_a_benchmark_inside_the_universe_has_no_special_case() -> None:
    spec = make_spec(universe=("AAA", "BBB"), benchmark="AAA")
    bench = benchmark_spec(spec)
    assert bench.universe == ["AAA"]
    assert bench.signal.id == "buy_and_hold"


def test_the_strategy_spec_is_not_changed() -> None:
    spec = make_spec(universe=("AAA", "BBB"), benchmark="SPY")
    before = spec.model_copy(deep=True)
    benchmark_spec(spec)
    assert spec == before
    assert spec.universe == ["AAA", "BBB"] and spec.signal.id == "sma_crossover"


def test_a_long_name_is_cut_to_the_length_the_spec_allows() -> None:
    spec = make_spec(benchmark="SPY").model_copy(update={"name": "x" * 100})
    bench = benchmark_spec(spec)
    assert len(bench.name) <= 100
    assert bench.name.endswith(" (benchmark SPY)")
    assert bench.name.startswith("x" * 10)


def test_the_result_is_a_valid_spec_with_the_signal_registered() -> None:
    bench = benchmark_spec(make_spec())
    assert bench.warmup_rows == 0
    assert type(bench) is type(make_spec())
