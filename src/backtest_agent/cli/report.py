"""``bt report``: re-evaluate a stored run on the cached data and check that it reproduces (ADR 0016, docs/cli.md).

``run.json`` holds dictionaries, not an ``Evaluation``, so the report is rendered from a fresh evaluation of the stored
spec, with the stored ``costs_applied`` and metric assumptions, and only after that evaluation has been shown to equal
the journal record. Nothing here writes or logs anything.
"""

from pathlib import Path

from pydantic import ValidationError

from backtest_agent.cli.compare import differences, prioritized
from backtest_agent.cli.errors import RunChangedError, StoredSpecError
from backtest_agent.coded.loader import resolve_coded
from backtest_agent.data import DataProvider
from backtest_agent.journal import JournalFormatError, RunRecord
from backtest_agent.journal.models import build_record
from backtest_agent.metrics import Evaluation, MetricAssumptions, evaluate
from backtest_agent.spec import SpecError, SpecProblem, StrategySpec, UnknownSignalError
from backtest_agent.spec.loader import problems_of


def stored_spec(record: RunRecord) -> StrategySpec:
    """The spec of ``run.json``. A spec that no longer validates (the schema or a signal changed) is exit code 3."""
    try:
        return StrategySpec.model_validate(record.spec)
    except ValidationError as error:
        raise StoredSpecError(record.run_id, problems_of(error, record.spec)) from None
    except UnknownSignalError as error:
        raise StoredSpecError(
            record.run_id, [SpecProblem("signal.id", str(error.args[0] if error.args else error))]
        ) from None


def stored_settings(record: RunRecord) -> tuple[bool, MetricAssumptions]:
    """``costs_applied`` and the metric assumptions of the stored run. ``evaluate`` takes one ``apply_costs`` flag for
    the strategy and the benchmark, so two different stored values mean a record that cannot be reproduced."""

    def fail(reason: str) -> JournalFormatError:
        return JournalFormatError(f"run {record.run_id}: {reason}")

    evaluation = record.evaluation
    try:
        strategy_flag = evaluation["strategy"]["costs_applied"]
        benchmark_flag = evaluation["benchmark"]["costs_applied"]
        raw = evaluation["assumptions"]
    except (KeyError, TypeError):
        raise fail("the stored evaluation lacks costs_applied or assumptions") from None
    if not isinstance(strategy_flag, bool) or not isinstance(benchmark_flag, bool):
        raise fail("the stored costs_applied values must be true or false")
    if strategy_flag != benchmark_flag:
        raise fail(
            "the stored costs_applied differ (strategy "
            f"{str(strategy_flag).lower()}, benchmark {str(benchmark_flag).lower()}), so the run cannot be reproduced"
        )
    if not isinstance(raw, dict):
        raise fail("the stored metric assumptions must be an object")
    try:
        return strategy_flag, MetricAssumptions(**raw)
    except (TypeError, ValueError) as error:
        raise fail(f"the stored metric assumptions cannot be read ({error})") from None


def stored_coded_spec(record: RunRecord, spec: StrategySpec, approvals_dir: Path | str) -> StrategySpec:
    """A stored coded spec through the gate in stored mode: the archived code it pins is loaded, the editable file is
    never read. A missing record or archive is ``RecordError`` (exit code 5), params that no longer fit the code are
    a stored spec that no longer validates (exit code 3)."""
    try:
        return resolve_coded(spec, approvals_dir=approvals_dir, strategies_dir=None)
    except SpecError as error:
        raise StoredSpecError(record.run_id, error.problems) from None


def reproduce(record: RunRecord, provider: DataProvider, approvals_dir: Path | str = Path("approvals")) -> Evaluation:
    """Evaluate the stored spec again; return the evaluation if it equals the record, else raise ``RunChangedError``.

    ``approvals_dir`` is only used for a coded spec (stored mode of the gate, see ``stored_coded_spec``).
    """
    spec = stored_spec(record)
    if spec.signal.coded is not None:
        spec = stored_coded_spec(record, spec, approvals_dir)
    apply_costs, assumptions = stored_settings(record)
    evaluation = evaluate(spec, provider, apply_costs=apply_costs, assumptions=assumptions)
    fresh = build_record(
        evaluation,
        run_id=record.run_id,
        generated_at=record.generated_at,
        code_version=record.code_version,
        trial=record.trial,
    )
    found = differences(record.to_dict(), fresh.to_dict())
    if found:
        raise RunChangedError(record.run_id, prioritized(found))
    return evaluation
