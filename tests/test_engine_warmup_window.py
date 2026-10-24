"""warmup_window: the formula of docs/engine.md with literal windows (no expected value is computed by code)."""

from datetime import date
from pathlib import Path

import pytest

from backtest_agent.engine import WarmupWindow, warmup_window
from backtest_agent.metrics import benchmark_spec
from backtest_agent.spec import load_spec
from runner_helpers import make_spec

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_the_benchmark_window_is_16_days_for_delay_1_and_warm_up_0() -> None:
    # buy_and_hold has no warm-up; N = 0 + 1 = 1; 2 * 1 + 14 = 16 days before 2024-01-02 is 2023-12-17
    spec = make_spec(universe=("A",), start="2024-01-02", end="2024-01-08", signal="buy_and_hold", params={})
    assert warmup_window(spec) == WarmupWindow(
        required_rows=0, delay_bars=1, rows_needed=1, buffer_days=16, fetch_start=date(2023, 12, 17)
    )


def test_the_window_of_the_benchmark_of_a_spec_ignores_the_warm_up_of_the_spec() -> None:
    spec = make_spec(universe=("A", "B"), start="2024-01-02", end="2024-01-08", benchmark="B")  # sma 5 / 20
    assert warmup_window(spec) == WarmupWindow(
        required_rows=19, delay_bars=1, rows_needed=20, buffer_days=54, fetch_start=date(2023, 11, 9)
    )
    assert warmup_window(benchmark_spec(spec)) == WarmupWindow(
        required_rows=0, delay_bars=1, rows_needed=1, buffer_days=16, fetch_start=date(2023, 12, 17)
    )


def test_fixture_h14_is_18_days_for_n_2() -> None:
    # docs/engine.md H14: warm-up 1, delay 1, N = 2, 2 * 2 + 14 = 18 days before 2024-01-06 is 2023-12-19
    spec = make_spec(
        universe=("A", "B"),
        start="2024-01-06",
        end="2024-01-15",
        params={"fast": 1, "slow": 2},
    )
    assert warmup_window(spec) == WarmupWindow(
        required_rows=1, delay_bars=1, rows_needed=2, buffer_days=18, fetch_start=date(2023, 12, 19)
    )


def test_sma_crossover_of_the_example_is_414_days() -> None:
    # slow 200 gives 199 warm-up rows, delay 1, N = 200, 2 * 200 + 14 = 414 days before 2010-01-01 is 2008-11-13
    spec = load_spec(REPO_ROOT / "strategies" / "sma_crossover.yaml")
    assert warmup_window(spec) == WarmupWindow(
        required_rows=199, delay_bars=1, rows_needed=200, buffer_days=414, fetch_start=date(2008, 11, 13)
    )


def test_a_longer_delay_widens_the_window() -> None:
    # buy_and_hold with delay 3: N = 3, 2 * 3 + 14 = 20 days before 2024-01-02 is 2023-12-13
    spec = make_spec(universe=("A",), start="2024-01-02", end="2024-01-08", signal="buy_and_hold", params={}, delay=3)
    assert warmup_window(spec) == WarmupWindow(
        required_rows=0, delay_bars=3, rows_needed=3, buffer_days=20, fetch_start=date(2023, 12, 13)
    )


def test_the_window_is_frozen() -> None:
    window = warmup_window(make_spec())
    with pytest.raises(AttributeError):
        window.buffer_days = 1  # type: ignore[misc]
