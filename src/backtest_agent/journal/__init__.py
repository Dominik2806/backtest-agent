"""Journal: every run is stored under ``runs/<run-id>/`` and counted per strategy family (F-15; docs/journal.md)."""

from backtest_agent.journal.code_version import CodeVersion, detect_code_version
from backtest_agent.journal.errors import (
    JournalBusyError,
    JournalError,
    JournalFormatError,
    JournalIndexStale,
    RunNotFoundError,
)
from backtest_agent.journal.identity import canonical_json, family_of, variant_hash
from backtest_agent.journal.models import RunRecord, RunSummary, TrialInfo
from backtest_agent.journal.store import get_run, list_runs, rebuild_index, record_run, run_count, trial_count

__all__ = [
    "CodeVersion",
    "JournalBusyError",
    "JournalError",
    "JournalFormatError",
    "JournalIndexStale",
    "RunNotFoundError",
    "RunRecord",
    "RunSummary",
    "TrialInfo",
    "canonical_json",
    "detect_code_version",
    "family_of",
    "get_run",
    "list_runs",
    "rebuild_index",
    "record_run",
    "run_count",
    "trial_count",
    "variant_hash",
]
