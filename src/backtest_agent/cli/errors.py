"""Exit codes and the mapping from an exception to one error message (docs/cli.md, "Exit codes", ADR 0016).

``classify`` is the only place that decides which code an error class gets. The order of the checks matters:
``JournalFormatError`` is both a ``JournalError`` and a ``ValueError`` and ``ExperimentReportError`` a
``RuntimeError``, so the specific classes come first and everything unknown is code 1.
"""

import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from backtest_agent.cli import render
from backtest_agent.cli.compare import Difference, change_kind
from backtest_agent.data.errors import DataError, DataValidationError
from backtest_agent.experiment import ExperimentReportError
from backtest_agent.journal import (
    JournalBusyError,
    JournalError,
    JournalIndexStale,
    RunNotFoundError,
)
from backtest_agent.spec.errors import SpecError, SpecProblem, UnknownSignalError

MAX_ISSUES_SHOWN = 10
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class ReportedValidationErrors(DataError):
    """The data has validation errors that the command already printed in full (``bt validate --data``)."""

    def __init__(self, count: int) -> None:
        self.count = count
        plural = "error" if count == 1 else "errors"
        super().__init__(f"the data has {count} validation {plural} (listed above)")


class RunChangedError(Exception):
    """``bt report`` re-evaluated a stored run and the result is not the journal record (exit code 7)."""

    def __init__(self, run_id: str, found: Sequence[Difference]) -> None:
        self.run_id = run_id
        self.found = tuple(found)
        self.kind = change_kind(self.found)
        super().__init__(f"run {run_id} no longer reproduces: {self.kind} changed")


class StoredSpecError(SpecError):
    """The spec stored in a run no longer validates: the schema or a signal changed since the run (exit code 3)."""

    def __init__(self, run_id: str, problems: Sequence[SpecProblem]) -> None:
        super().__init__(problems)
        self.run_id = run_id
        count = len(self.problems)
        lines = [f"the stored spec of run {run_id} no longer validates ({count} problem{'s' if count != 1 else ''}):"]
        lines += [f"  - {problem.path}: {problem.message}" for problem in self.problems]
        Exception.__init__(self, "\n".join(lines))


class ReportFolderExistsError(FileExistsError):
    """``bt report`` refuses to write into an existing report folder without ``--overwrite`` (exit code 5)."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        super().__init__(f"report folder already exists: {folder.as_posix()}")


class ExitCode(IntEnum):
    OK = 0
    UNEXPECTED = 1
    USAGE = 2
    SPEC = 3
    DATA = 4
    JOURNAL = 5
    REPORT_FAILED = 6
    CHANGED = 7
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
    if isinstance(error, JournalIndexStale | sqlite3.Error):
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
    if isinstance(error, StoredSpecError):
        return Failure(
            ExitCode.SPEC,
            str(error),
            "the run folder is untouched; the spec schema or a signal changed since the run (docs/strategy-spec.md)",
        )
    if isinstance(error, SpecError):
        return Failure(ExitCode.SPEC, str(error), "the fields of a spec are described in docs/strategy-spec.md")
    if isinstance(error, UnknownSignalError):
        return Failure(ExitCode.SPEC, str(error.args[0]) if error.args else "unknown signal")
    if isinstance(error, RunChangedError):
        untouched = "the stored run is untouched; "
        hint = untouched + (
            "use the cache the run was made with (--cache-dir) or log a new run with bt run"
            if error.kind == "data"
            else "the metric code or the stored values changed; log a new run with bt run"
        )
        return Failure(ExitCode.CHANGED, render.changed_message(error.run_id, error.kind, error.found), hint)
    if isinstance(error, ReportedValidationErrors):
        return Failure(ExitCode.DATA, str(error))
    if isinstance(error, DataError):
        message = _validation_message(error) if isinstance(error, DataValidationError) else str(error)
        return Failure(ExitCode.DATA, message, "check the symbols, the dates and your connection (--cache-dir)")
    if isinstance(error, sqlite3.Error):  # the index file is not a database; the run folders are intact
        return Failure(
            ExitCode.JOURNAL,
            f"the journal index cannot be read ({type(error).__name__}: {error})",
            _journal_hint(error, runs_dir),
        )
    if isinstance(error, ReportFolderExistsError):
        return Failure(
            ExitCode.JOURNAL, str(error), "pass --overwrite to replace the files in it, or choose another --reports-dir"
        )
    if isinstance(error, JournalError | FileExistsError):
        return Failure(ExitCode.JOURNAL, str(error), _journal_hint(error, runs_dir))
    return Failure(
        ExitCode.UNEXPECTED,
        f"unexpected error ({type(error).__name__}): {error}",
        "run again with --debug for the traceback; if it keeps happening it is a bug",
    )
