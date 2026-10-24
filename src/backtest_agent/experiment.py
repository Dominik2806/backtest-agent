"""The experiment entry point: evaluate, log, report (F-15; docs/journal.md, "run_experiment").

``run_experiment`` is how a standard run is made. ``evaluate()`` and ``run_backtest()`` stay pure; this module does the
three steps in a fixed order: evaluate, ``record_run`` (the journal commit), then, if a reports folder is given,
``write_report`` with the trial of the journal and the same run id and time. Once the journal has committed, the run
counts; a report that fails afterwards raises ``ExperimentReportError``, which can write the report again without
logging the run twice.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from backtest_agent.data.provider import DataProvider
from backtest_agent.journal import CodeVersion, RunRecord, detect_code_version, record_run
from backtest_agent.metrics import DEFAULT_ASSUMPTIONS, Evaluation, MetricAssumptions, evaluate
from backtest_agent.reporting import ReportPaths, write_report
from backtest_agent.run_id import make_run_id
from backtest_agent.spec import StrategySpec


@dataclass(frozen=True)
class Experiment:
    """What one call of ``run_experiment`` produced: the evaluation, its journal record and the report (if any)."""

    evaluation: Evaluation
    record: RunRecord
    report: ReportPaths | None


class ExperimentReportError(RuntimeError):
    """The run is logged but its report could not be written; the cause is chained (``__cause__``).

    Carries what is needed to write the report again for the same run id: ``retry()`` logs nothing.
    """

    def __init__(
        self, message: str, *, evaluation: Evaluation, record: RunRecord, generated_at: datetime, reports_dir: Path
    ) -> None:
        super().__init__(message)
        self.evaluation = evaluation
        self.record = record
        self.generated_at = generated_at
        self.reports_dir = reports_dir

    def retry(self) -> ReportPaths:
        """Write the report of the logged run again, with the same run id, time and trial. Nothing is logged.

        A second failure is not wrapped: the error of ``write_report`` propagates as it is (the caller already holds
        this error and can call ``retry()`` again).
        """
        return write_report(
            self.evaluation,
            self.reports_dir,
            generated_at=self.generated_at,
            run_id=self.record.run_id,
            trial=self.record.trial,
        )


def _run_id_exists(run_id: str) -> FileExistsError:
    return FileExistsError(f"run id already exists; use a later generated_at: {run_id}")


def run_experiment(
    spec: StrategySpec,
    provider: DataProvider,
    *,
    runs_dir: Path | str,
    generated_at: datetime,
    reports_dir: Path | str | None = None,
    code_version: CodeVersion | None = None,
    allow_short_warmup: bool = True,
    apply_costs: bool = True,
    assumptions: MetricAssumptions = DEFAULT_ASSUMPTIONS,
) -> Experiment:
    """Evaluate ``spec``, log the run in ``runs_dir`` and, if ``reports_dir`` is given, write its report.

    ``generated_at`` must be timezone-aware; the run id, the journal and the report all use it. ``code_version=None``
    detects the git commit of this package. Raises ``FileExistsError`` ("run id already exists; use a later
    generated_at") if the run folder exists, or if only the report folder exists (nothing is logged then). Journal
    errors propagate unchanged and no report is written. A report that fails after the run was logged raises
    ``ExperimentReportError``.
    """
    evaluation = evaluate(
        spec, provider, allow_short_warmup=allow_short_warmup, apply_costs=apply_costs, assumptions=assumptions
    )
    run_id = make_run_id(evaluation, generated_at)
    run_folder = Path(runs_dir) / run_id
    if reports_dir is not None:
        report_folder = Path(reports_dir) / run_id
        if report_folder.exists():
            if run_folder.exists():
                raise _run_id_exists(run_id)
            raise FileExistsError(f"report folder already exists: {report_folder}; nothing was logged")
    try:
        record = record_run(
            evaluation,
            runs_dir,
            generated_at=generated_at,
            code_version=detect_code_version() if code_version is None else code_version,
        )
    except FileExistsError as error:
        if run_folder.exists():  # only the run id; any other FileExistsError is not ours to reword
            raise _run_id_exists(run_id) from error
        raise
    if reports_dir is None:
        return Experiment(evaluation, record, None)
    try:
        report = write_report(
            evaluation, reports_dir, generated_at=generated_at, run_id=record.run_id, trial=record.trial
        )
    except Exception as error:
        raise ExperimentReportError(
            f"run {record.run_id} is logged but its report could not be written ({error}); "
            "call retry() on this error to write the report again without logging the run twice",
            evaluation=evaluation,
            record=record,
            generated_at=generated_at,
            reports_dir=Path(reports_dir),
        ) from error
    return Experiment(evaluation, record, report)
