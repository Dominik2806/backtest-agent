"""The exit-7 example of docs/cli.md end to end: the 18 paths in their printed order and the values of the first five.

The world is fixture R3b with the last close of A at 150 instead of 146.41. The hash, the excess return and
``strategy_return_compared`` are derived by hand in the docs; ``information_ratio`` and ``tracking_error`` are the
values of the program (docs/metrics.md has their formulas), pinned here as the docs print them.
"""

import warnings
from pathlib import Path

import pytest

from backtest_agent.cli.errors import RunChangedError
from backtest_agent.cli.report import reproduce
from backtest_agent.engine import InsufficientWarmupWarning
from backtest_agent.journal import get_run
from cli_helpers import at, run_cli, write_spec
from report_helpers import A_CLOSE, A_OPEN, B_CLOSE, B_OPEN, spec_for, world
from runner_helpers import LiteralProvider, price_frame

HASH_A = "61669f6e7476623e1289ff7dad8c8b767f36be44961c05ec4def3f45c15dd090"
HASH_A_LAST_CLOSE_150 = "84cff02fdbf6860d463ec79c2cebba456c5dac2a6331d47831eb2f9602ea01d7"

# docs/cli.md, "Example: bt report, unchanged and with other prices": 1 + 4 + 8 + 5 paths, in the printed order
EXPECTED_PATHS = [
    "evaluation.strategy.data_hash",
    "evaluation.relative.excess_return",
    "evaluation.relative.information_ratio",
    "evaluation.relative.strategy_return_compared",
    "evaluation.relative.tracking_error",
    "evaluation.strategy.metrics.best_month",
    "evaluation.strategy.metrics.cagr",
    "evaluation.strategy.metrics.calmar",
    "evaluation.strategy.metrics.sharpe",
    "evaluation.strategy.metrics.sortino",
    "evaluation.strategy.metrics.total_return",
    "evaluation.strategy.metrics.volatility",
    "evaluation.strategy.metrics.worst_month",
    "costs.strategy.cost_drag",
    "costs.strategy.cost_share",
    "costs.strategy.gross_final_equity",
    "costs.strategy.gross_return",
    "costs.strategy.net_return",
]
# lines 2 to 5 of the example: (path, stored, now); relative tolerance 1e-9
EXAMPLE_VALUES = [
    ("evaluation.relative.excess_return", 0.3872, 0.41592),  # 0.17128 - (-0.21592) and 0.2 - (-0.21592)
    ("evaluation.relative.information_ratio", 11.59310139695154, 11.554740195295285),  # the program's
    ("evaluation.relative.strategy_return_compared", 0.17128, 0.2),  # 1171.28 / 1000 - 1 and 1200 / 1000 - 1
    ("evaluation.relative.tracking_error", 1.738965209542734, 1.8623870882809872),  # the program's
]


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def changed_provider() -> LiteralProvider:
    return LiteralProvider(price_frame({"A": A_OPEN, "B": B_OPEN}, {"A": [*A_CLOSE[:-1], 150], "B": B_CLOSE}))


def test_the_18_paths_of_the_example_in_the_printed_order_and_the_values_of_lines_2_to_5(workdir: Path) -> None:
    write_spec(workdir, spec_for(), "spec.yaml")
    ran = run_cli(["run", "spec.yaml", "--no-report"], provider=LiteralProvider(world()), clock=at(0))
    assert ran.code == 0, ran.err
    record = get_run(workdir / "runs", ran.out.splitlines()[0].split()[1])
    with pytest.raises(RunChangedError) as raised:
        reproduce(record, changed_provider())

    found = raised.value.found
    assert [difference.path for difference in found] == EXPECTED_PATHS
    assert raised.value.kind == "data"
    assert (found[0].stored, found[0].fresh) == (HASH_A, HASH_A_LAST_CLOSE_150)
    by_path = {difference.path: difference for difference in found}
    for path, stored, now in EXAMPLE_VALUES:
        assert by_path[path].stored == pytest.approx(stored, rel=1e-9), path
        assert by_path[path].fresh == pytest.approx(now, rel=1e-9), path


def test_warnings_of_the_evaluation_come_before_the_exit_7_block(workdir: Path) -> None:
    # an SMA with a slow window of 8 on a world of 5 rows: the history is too short, which is a warning, not an error
    short = spec_for("B", signal="sma_crossover", params={"fast": 2, "slow": 8}, name="SMA too long for 5 rows")
    write_spec(workdir, short, "sma.yaml")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", InsufficientWarmupWarning)
        ran = run_cli(["run", "sma.yaml", "--no-report"], provider=LiteralProvider(world()), clock=at(0))
    assert ran.code == 0, ran.err
    assert ran.err.startswith("warning: ")
    run_id = ran.out.splitlines()[0].split()[1]

    unchanged = run_cli(["report", run_id], provider=LiteralProvider(world()))
    assert unchanged.code == 0, unchanged.err
    assert unchanged.err.startswith("warning: ") and "bt: error" not in unchanged.err

    result = run_cli(["report", run_id, "--overwrite"], provider=changed_provider())
    assert result.code == 7
    lines = result.err.splitlines()
    first_error = next(i for i, line in enumerate(lines) if line.startswith("bt: error: "))
    assert first_error >= 1
    assert all(line.startswith("warning: ") for line in lines[:first_error])
    assert not any(line.startswith("warning: ") for line in lines[first_error:])
