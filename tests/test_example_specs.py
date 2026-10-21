"""Every spec in strategies/ is loaded here, so a broken example (or a broken future spec) fails CI."""

from pathlib import Path

import pytest

from backtest_agent.spec import StrategySpec, get_signal, load_spec

STRATEGIES = Path(__file__).resolve().parents[1] / "strategies"
SPEC_FILES = sorted(STRATEGIES.glob("*.yaml"))
EXAMPLES = ["sma_crossover.yaml", "momentum_12_1.yaml", "buy_and_hold.yaml"]


def test_the_example_specs_exist() -> None:
    assert set(EXAMPLES) <= {path.name for path in SPEC_FILES}


@pytest.mark.parametrize("path", SPEC_FILES, ids=lambda path: path.name)
def test_every_spec_in_strategies_loads(path: Path) -> None:
    spec = load_spec(path)
    assert isinstance(spec, StrategySpec)
    assert spec.universe and spec.benchmark
    assert get_signal(spec.signal.id)
    assert spec.warmup_rows >= 0


@pytest.mark.parametrize("name", EXAMPLES)
def test_the_examples_are_honest_specs(name: str) -> None:
    spec = load_spec(STRATEGIES / name)
    assert spec.risk_flags() == (), "an example must not carry a risk flag"
    assert spec.execution.delay_bars >= 1
    assert spec.signal.id == name.removesuffix(".yaml")


def test_the_example_signals_and_warmups() -> None:
    specs = {name.removesuffix(".yaml"): load_spec(STRATEGIES / name) for name in EXAMPLES}
    assert specs["sma_crossover"].warmup_rows == 199
    assert specs["momentum_12_1"].warmup_rows == 252
    assert specs["buy_and_hold"].warmup_rows == 0
    assert specs["momentum_12_1"].signal.params["top_n"] == 3
