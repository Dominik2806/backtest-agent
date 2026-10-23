"""Helpers for the journal tests: the strategies of the counter table in docs/journal.md and fixed times and versions.

They build inputs only; no expected value of a test is computed here.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backtest_agent.journal import CodeVersion
from backtest_agent.metrics import Evaluation
from backtest_agent.spec import StrategySpec
from report_helpers import A_CLOSE, A_OPEN, B_CLOSE, B_OPEN, make_evaluation, world
from runner_helpers import LiteralProvider, make_spec, price_frame

BASE_TIME = datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC)
CODE = CodeVersion("0123456789abcdef0123456789abcdef01234567", False)
COSTS = (1000.0, 1000.0, 500.0)


def at(seconds: int) -> datetime:
    """A fixed time: 2026-01-15 10:30:00 UTC plus ``seconds``."""
    return BASE_TIME + timedelta(seconds=seconds)


def sma_spec(
    *,
    fast: int = 2,
    slow: int = 3,
    name: str = "SMA A",
    description: str = "",
    start: str = "2024-01-02",
    commission: float = 1000.0,
) -> StrategySpec:
    """The strategy S1 of the counter table (family sma_crossover) with the given changes."""
    spec = make_spec(
        universe=("A",),
        benchmark="B",
        start=start,
        end="2024-01-08",
        signal="sma_crossover",
        params={"fast": fast, "slow": slow},
        costs=(commission, COSTS[1], COSTS[2]),
        capital=1000,
    )
    return spec.model_copy(update={"name": name, "description": description})


def hold_spec(*, name: str = "Buy and hold A") -> StrategySpec:
    """The strategy S5 of the counter table (family buy_and_hold)."""
    spec = make_spec(
        universe=("A",),
        benchmark="B",
        start="2024-01-02",
        end="2024-01-08",
        signal="buy_and_hold",
        params={},
        costs=COSTS,
        capital=1000,
    )
    return spec.model_copy(update={"name": name})


def standard_provider() -> LiteralProvider:
    return LiteralProvider(world())


def other_data_provider() -> LiteralProvider:
    """The same world with another last close of A, so the data hash differs."""
    closes = {"A": [*A_CLOSE[:-1], A_CLOSE[-1] + 1.0], "B": B_CLOSE}
    return LiteralProvider(price_frame({"A": A_OPEN, "B": B_OPEN}, closes))


def evaluation_of(spec: StrategySpec, provider: LiteralProvider | None = None, **kwargs) -> Evaluation:
    return make_evaluation(spec, provider if provider is not None else standard_provider(), **kwargs)


REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def no_repo_runs():
    """Fail a test that leaves a ``runs`` folder in the real repository: journal tests write to ``tmp_path`` only."""
    before = (REPO_ROOT / "runs").exists()
    yield
    assert (REPO_ROOT / "runs").exists() == before, "a journal test wrote into the real repository"


def log(runs, spec: StrategySpec, second: int, provider: LiteralProvider | None = None, **kwargs):
    """Evaluate ``spec`` and log it at ``at(second)``; returns the ``RunRecord``."""
    from backtest_agent.journal import record_run

    return record_run(evaluation_of(spec, provider, **kwargs), runs, generated_at=at(second), code_version=CODE)


def log_four(runs) -> list:
    """S1, S2, S3 and S5 of the counter table, in this order, one second apart."""
    return [
        log(runs, sma_spec(), 1),
        log(runs, sma_spec(name="Renamed run", description="Changed text"), 2),
        log(runs, sma_spec(slow=4), 3),
        log(runs, hold_spec(), 4),
    ]


def edit_run_json(runs, run_id: str, change) -> None:
    """Rewrite ``runs/<run-id>/run.json`` after ``change(data)`` changed the parsed content (canonical JSON)."""
    from backtest_agent.journal import canonical_json

    path = Path(runs) / run_id / "run.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_bytes((canonical_json(data) + "\n").encode("utf-8"))
