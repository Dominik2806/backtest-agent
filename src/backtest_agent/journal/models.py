"""The records of the journal: what ``run.json`` holds and what the read API returns (docs/journal.md).

Plain frozen dataclasses. A ``RunRecord`` is built from an ``Evaluation`` plus the identity of the run, serialized to
canonical JSON and read back to an equal record; reading checks the structure and refuses anything it does not know.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backtest_agent.engine.result import BacktestResult
from backtest_agent.journal.code_version import CodeVersion
from backtest_agent.journal.errors import JournalFormatError
from backtest_agent.journal.identity import canonical_json, family_of, variant_hash_of_dict
from backtest_agent.metrics.evaluation import Evaluation
from backtest_agent.metrics.trades import trade_statistics

SCHEMA_VERSION = 1
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_KEYS = (
    "schema_version",
    "run_id",
    "generated_at",
    "code_version",
    "family",
    "trial",
    "spec",
    "evaluation",
    "trades",
    "costs",
)
_TRIAL_KEYS = ("variant_hash", "run_number", "trial_number", "trial_count", "new_variant")
_COST_KEYS = (
    "costs_applied",
    "total_costs",
    "gross_final_equity",
    "net_return",
    "gross_return",
    "cost_drag",
    "cost_share",
)


@dataclass(frozen=True)
class TrialInfo:
    """Where a run stands among the runs and variants of its family, **as of this run** (it counts itself).

    ``run_number`` is the place among the runs of the family, ``trial_number`` the place of its variant among the
    variants (a repeat keeps the number of its variant), ``trial_count`` the number of distinct variants so far.
    """

    family: str
    variant_hash: str
    run_number: int
    trial_number: int
    trial_count: int
    new_variant: bool

    @property
    def run_count(self) -> int:
        """Runs of the family as of this run: it is the run number."""
        return self.run_number


@dataclass(frozen=True)
class RunSummary:
    """One row of the index: enough to list and find a run without reading its folder."""

    run_id: str
    generated_at: datetime
    family: str
    variant_hash: str
    run_number: int
    trial_number: int
    trial_count: int
    new_variant: bool
    strategy_name: str
    strategy_data_hash: str
    benchmark_data_hash: str
    code_commit: str
    code_dirty: bool | None


@dataclass(frozen=True)
class RunRecord:
    """The content of ``run.json``. The dicts hold JSON types only; treat them as read-only."""

    run_id: str
    generated_at: datetime  # UTC, whole seconds
    code_version: CodeVersion
    trial: TrialInfo
    spec: dict[str, Any]
    evaluation: dict[str, Any]
    trades: dict[str, Any]
    costs: dict[str, dict[str, Any]]

    @property
    def family(self) -> str:
        return self.trial.family

    def summary(self) -> RunSummary:
        return RunSummary(
            run_id=self.run_id,
            generated_at=self.generated_at,
            family=self.trial.family,
            variant_hash=self.trial.variant_hash,
            run_number=self.trial.run_number,
            trial_number=self.trial.trial_number,
            trial_count=self.trial.trial_count,
            new_variant=self.trial.new_variant,
            strategy_name=self.evaluation["strategy"]["name"],
            strategy_data_hash=self.evaluation["strategy"]["data_hash"],
            benchmark_data_hash=self.evaluation["benchmark"]["data_hash"],
            code_commit=self.code_version.commit,
            code_dirty=self.code_version.dirty,
        )

    def to_dict(self) -> dict[str, Any]:
        trial = self.trial
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "generated_at": self.generated_at.strftime(TIMESTAMP_FORMAT),
            "code_version": self.code_version.to_dict(),
            "family": trial.family,
            "trial": {
                "variant_hash": trial.variant_hash,
                "run_number": trial.run_number,
                "trial_number": trial.trial_number,
                "trial_count": trial.trial_count,
                "new_variant": trial.new_variant,
            },
            "spec": self.spec,
            "evaluation": self.evaluation,
            "trades": self.trades,
            "costs": self.costs,
        }

    def to_json(self) -> str:
        """Canonical JSON plus one final newline; NaN or infinity raise ``ValueError``."""
        return canonical_json(self.to_dict()) + "\n"

    @classmethod
    def from_dict(cls, data: Any, source: Path | str) -> "RunRecord":
        """Check ``data`` (parsed ``run.json`` of ``source``) and build the record; ``JournalFormatError`` otherwise."""

        def fail(reason: str) -> JournalFormatError:
            return JournalFormatError(f"{source}: {reason}")

        if not isinstance(data, dict):
            raise fail("run.json must contain a JSON object")
        version = data.get("schema_version")
        if isinstance(version, bool) or version != SCHEMA_VERSION:
            raise fail(f"unsupported schema_version {version!r}; this version reads {SCHEMA_VERSION}")
        if set(data) != set(_KEYS):
            raise fail(f"the keys must be exactly {sorted(_KEYS)}, got {sorted(data)}")
        run_id, family = data["run_id"], data["family"]
        if not isinstance(run_id, str) or not isinstance(family, str):
            raise fail("run_id and family must be strings")
        try:
            generated_at = datetime.strptime(data["generated_at"], TIMESTAMP_FORMAT).replace(tzinfo=UTC)
        except (TypeError, ValueError):
            raise fail(f"generated_at must look like 2026-01-15T10:30:05Z, got {data['generated_at']!r}") from None
        code = data["code_version"]
        if not (
            isinstance(code, dict)
            and set(code) == {"commit", "dirty"}
            and isinstance(code["commit"], str)
            and (code["dirty"] is None or isinstance(code["dirty"], bool))
        ):
            raise fail("code_version must be {commit: string, dirty: boolean or null}")
        trial = data["trial"]
        if not (isinstance(trial, dict) and set(trial) == set(_TRIAL_KEYS)):
            raise fail(f"trial must have exactly the keys {sorted(_TRIAL_KEYS)}")
        numbers = (trial["run_number"], trial["trial_number"], trial["trial_count"])
        if (
            not isinstance(trial["variant_hash"], str)
            or any(isinstance(n, bool) or not isinstance(n, int) or n < 1 for n in numbers)
            or not isinstance(trial["new_variant"], bool)
        ):
            raise fail("trial holds a bad value: the numbers must be integers of 1 or more")
        spec, evaluation, trades, costs = data["spec"], data["evaluation"], data["trades"], data["costs"]
        if not all(isinstance(part, dict) for part in (spec, evaluation, trades, costs)):
            raise fail("spec, evaluation, trades and costs must be JSON objects")
        try:
            names = (evaluation["strategy"]["name"], evaluation["strategy"]["data_hash"])
            bench_hash = evaluation["benchmark"]["data_hash"]
            spec_family = spec["signal"]["id"]
        except (KeyError, TypeError):
            raise fail("spec or evaluation lacks signal.id, strategy.name or a data hash") from None
        if not all(isinstance(value, str) for value in (*names, bench_hash)):
            raise fail("the strategy name and both data hashes must be strings")
        if set(costs) != {"strategy", "benchmark"} or any(
            not isinstance(part, dict) or set(part) != set(_COST_KEYS) for part in costs.values()
        ):
            raise fail(f"costs must have strategy and benchmark, each with exactly the keys {sorted(_COST_KEYS)}")
        if spec_family != family:
            raise fail(f"family {family!r} is not the signal id of the stored spec ({spec_family!r})")
        if trial["variant_hash"] != variant_hash_of_dict(spec):
            raise fail("trial.variant_hash does not match the stored spec")
        return cls(
            run_id=run_id,
            generated_at=generated_at,
            code_version=CodeVersion(code["commit"], code["dirty"]),
            trial=TrialInfo(family, trial["variant_hash"], *numbers, trial["new_variant"]),
            spec=spec,
            evaluation=evaluation,
            trades=trades,
            costs=costs,
        )


def result_costs(result: BacktestResult) -> dict[str, Any]:
    """The cost scalars of a result, one by one (they are properties of ``BacktestResult``, not fields)."""
    return {
        "costs_applied": result.costs_applied,
        "total_costs": result.total_costs,
        "gross_final_equity": result.gross_final_equity,
        "net_return": result.net_return,
        "gross_return": result.gross_return,
        "cost_drag": result.cost_drag,
        "cost_share": result.cost_share,
    }


def _plain(value: Any) -> Any:
    """``value`` as JSON types only (what reading the file back gives); NaN or infinity raise ``ValueError``."""
    return json.loads(canonical_json(value))


def build_record(
    evaluation: Evaluation,
    *,
    run_id: str,
    generated_at: datetime,
    code_version: CodeVersion,
    trial: TrialInfo,
) -> RunRecord:
    """The record of an evaluation. ``generated_at`` is converted to UTC and cut to whole seconds, like the run id."""
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    result = evaluation.result
    if trial.family != family_of(result.spec):
        raise ValueError(f"trial.family {trial.family!r} is not the family of the spec ({family_of(result.spec)!r})")
    return RunRecord(
        run_id=run_id,
        generated_at=generated_at.astimezone(UTC).replace(microsecond=0),
        code_version=code_version,
        trial=trial,
        spec=_plain(result.spec.to_dict()),
        evaluation=_plain(evaluation.to_dict()),
        trades=_plain(trade_statistics(result.trades).to_dict()),
        costs=_plain({"strategy": result_costs(result), "benchmark": result_costs(evaluation.benchmark_result)}),
    )
