"""Exit codes and the mapping from an exception to one error message (docs/cli.md, "Exit codes", ADR 0016).

``classify`` is the only place that decides which code an error class gets. The order of the checks matters:
``JournalFormatError`` is both a ``JournalError`` and a ``ValueError`` and ``ExperimentReportError`` a
``RuntimeError``, so the specific classes come first and everything unknown is code 1.
"""

import re
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from backtest_agent.data.errors import DataError, DataValidationError
from backtest_agent.experiment import ExperimentReportError
from backtest_agent.journal import (
    JournalBusyError,
    JournalError,
    JournalIndexStale,
    RunNotFoundError,
)
from backtest_agent.spec.errors import SpecError, UnknownSignalError

MAX_ISSUES_SHOWN = 10
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class ExitCode(IntEnum):
    OK = 0
    UNEXPECTED = 1
    USAGE = 2
    SPEC = 3
    DATA = 4
    JOURNAL = 5
    REPORT_FAILED = 6
    INTERRUPTED = 130


@dataclass(frozen=True)
class Failure:
    """What `main` prints on stderr (`bt: error: <message>`, then `hint: <hint>` if there is one) and returns."""

    code: ExitCode
    message: str
    hint: str | None = None


def clean(message: str) -> str:
    """Control characters (a terminal escape in a spec name, for example) become `?`; newlines and tabs stay."""
    return _CONTROL.sub("?", message)


def _validation_message(error: DataValidationError) -> str:
    issues = getattr(error.result, "errors", None)
    if not issues:
        return str(error)
    lines = [f"data validation failed with {len(issues)} error(s):"]
    for issue in issues[:MAX_ISSUES_SHOWN]:
        where = issue.symbol or "all symbols"
        lines.append(f"  - [{issue.code}] {where}: {issue.message}")
    if len(issues) > MAX_ISSUES_SHOWN:
        lines.append(f"  ... and {len(issues) - MAX_ISSUES_SHOWN} more")
    return "\n".join(lines)


def _journal_hint(error: Exception, runs_dir: Path | None) -> str | None:
    where = f" --runs-dir {runs_dir.as_posix()}" if runs_dir is not None else ""
    if isinstance(error, JournalIndexStale):
        return f'run "bt journal rebuild{where}" (a run folder that was deleted is forgotten by the rebuild)'
    if isinstance(error, JournalBusyError):
        return "another process is writing to the journal; try again in a moment"
    if isinstance(error, RunNotFoundError):
        return f"bt journal list{where} shows the runs of this journal"
    if isinstance(error, FileExistsError):
        text = str(error)
        if "run id already exists" in text:
            return "wait one second and run again (the run id has a resolution of one second)"
        if "report folder already exists" in text:
            return "remove that folder or choose another --reports-dir; nothing was logged"
    return None


def classify(error: BaseException, *, runs_dir: Path | None = None) -> Failure:
    """The exit code, message and hint for an exception that escaped a command."""
    if isinstance(error, KeyboardInterrupt):
        return Failure(ExitCode.INTERRUPTED, "interrupted")
    if isinstance(error, ExperimentReportError):
        run_id = error.record.run_id
        cause = error.__cause__ if error.__cause__ is not None else error
        return Failure(
            ExitCode.REPORT_FAILED,
            f"run {run_id} is logged but its report could not be written ({type(cause).__name__}: {cause})",
            f"bt report {run_id} writes the report again without logging the run twice",
        )
    if isinstance(error, SpecError):
        return Failure(ExitCode.SPEC, str(error), "the fields of a spec are described in docs/strategy-spec.md")
    if isinstance(error, UnknownSignalError):
        return Failure(ExitCode.SPEC, str(error.args[0]) if error.args else "unknown signal")
    if isinstance(error, DataError):
        message = _validation_message(error) if isinstance(error, DataValidationError) else str(error)
        return Failure(ExitCode.DATA, message, "check the symbols, the dates and your connection (--cache-dir)")
    if isinstance(error, JournalError | FileExistsError):
        return Failure(ExitCode.JOURNAL, str(error), _journal_hint(error, runs_dir))
    return Failure(
        ExitCode.UNEXPECTED,
        f"unexpected error ({type(error).__name__}): {error}",
        "run again with --debug for the traceback; if it keeps happening it is a bug",
    )
