"""Writing and reading the journal: ``record_run``, the read API and ``rebuild_index`` (docs/journal.md).

This module and ``index.py`` are the only places of the journal that touch the file system.
"""

import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import yaml

from backtest_agent.journal import index
from backtest_agent.journal.code_version import CodeVersion
from backtest_agent.journal.errors import JournalFormatError, RunNotFoundError
from backtest_agent.journal.identity import family_of, variant_hash
from backtest_agent.journal.models import RunRecord, RunSummary, TrialInfo, build_record
from backtest_agent.metrics.evaluation import Evaluation
from backtest_agent.run_id import check_run_id, make_run_id

RUN_JSON = "run.json"
SPEC_YAML = "spec.yaml"
DEFAULT_BUSY_TIMEOUT = 30.0


def _inside(base: Path, directory: Path) -> None:
    if directory.resolve().parent != base.resolve():
        raise ValueError(f"the run folder {directory} would not be directly inside {base}")


def _spec_yaml(spec: dict) -> str:
    return yaml.safe_dump(spec, sort_keys=True, default_flow_style=False, allow_unicode=True)


def record_run(
    evaluation: Evaluation,
    runs_dir: Path | str,
    *,
    generated_at: datetime,
    code_version: CodeVersion,
    busy_timeout: float = DEFAULT_BUSY_TIMEOUT,
) -> RunRecord:
    """Log one run: ``runs/<run-id>/run.json`` and ``spec.yaml`` plus one row in the index, all or nothing.

    The run id is ``make_run_id(evaluation, generated_at)`` (``generated_at`` must be timezone-aware). Order: take
    the write lock of the index (``BEGIN IMMEDIATE``), refuse a stale index, refuse an existing run id, count, render
    the files in memory, write them into a temporary folder, rename it, insert the row, commit. Any failure rolls back
    and removes the folders this call created (an empty ``index.sqlite`` can remain: it is an empty journal). Raises
    ``FileExistsError`` for an id that exists, ``JournalIndexStale`` if the folders and the index disagree,
    ``JournalBusyError`` if the lock is not free within ``busy_timeout`` seconds.
    """
    run_id = check_run_id(make_run_id(evaluation, generated_at))
    base = Path(runs_dir)
    directory = base / run_id
    _inside(base, directory)

    base.mkdir(parents=True, exist_ok=True)
    path = index.index_path(base)
    temporary = base / f".tmp-{run_id}-{uuid.uuid4().hex[:8]}"
    moved = False
    conn = index.connect(path, busy_timeout)
    try:
        index.begin_immediate(conn)
        index.ensure_schema(conn, path)
        index.check_in_sync(conn, base)
        if directory.exists():
            raise FileExistsError(f"run id already exists: {directory}; use a later generated_at")
        spec = evaluation.result.spec
        family, variant = family_of(spec), variant_hash(spec)
        run_number, trial_number, trial_count, new_variant = index.numbers_for(conn, family, variant)
        record = build_record(
            evaluation,
            run_id=run_id,
            generated_at=generated_at,
            code_version=code_version,
            trial=TrialInfo(family, variant, run_number, trial_number, trial_count, new_variant),
        )
        files = {RUN_JSON: record.to_json(), SPEC_YAML: _spec_yaml(record.spec)}  # may raise: nothing on disk yet
        temporary.mkdir()
        for name, text in files.items():
            (temporary / name).write_bytes(text.encode("utf-8"))
        temporary.rename(directory)
        moved = True
        index.insert_row(conn, record.summary())
        index.commit(conn)
    except BaseException:
        # Remove the folders while the write lock is still held, so no reader can see an orphan folder after the
        # lock is released.
        shutil.rmtree(temporary, ignore_errors=True)
        if moved:
            shutil.rmtree(directory, ignore_errors=True)
        index.rollback(conn)
        conn.close()
        raise
    conn.close()
    return record


def get_run(runs_dir: Path | str, run_id: str) -> RunRecord:
    """The record stored in ``runs/<run-id>/run.json``.

    Raises ``ValueError`` for an unsafe id, ``RunNotFoundError`` if there is no such run, ``JournalFormatError`` if the
    file cannot be read as a run record of this version.
    """
    base = Path(runs_dir)
    run_json = base / check_run_id(run_id) / RUN_JSON
    if not run_json.is_file():
        raise RunNotFoundError(f"no run {run_id!r} in {base}")
    return _read_record(run_json, run_id)


def _read_record(run_json: Path, folder_name: str) -> RunRecord:
    try:
        data = json.loads(run_json.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise JournalFormatError(f"{run_json}: cannot be read as JSON ({error})") from error
    record = RunRecord.from_dict(data, run_json)
    if record.run_id != folder_name:
        raise JournalFormatError(f"{run_json}: run_id {record.run_id!r} differs from the folder name {folder_name!r}")
    return record


def list_runs(runs_dir: Path | str, *, family: str | None = None, limit: int | None = None) -> tuple[RunSummary, ...]:
    """The runs of the index, newest first (by ``generated_at``, then run id); optionally one family and a limit.

    A missing folder is an empty journal. Raises ``ValueError`` for a ``limit`` below 1, ``JournalIndexStale`` or
    ``JournalFormatError`` if the index cannot be trusted.
    """
    if limit is not None and limit < 1:
        raise ValueError(f"limit must be 1 or more, got {limit}")
    conn = index.open_for_reading(Path(runs_dir))
    if conn is None:
        return ()
    try:
        return index.select_summaries(conn, family, limit)
    finally:
        conn.close()


def run_count(runs_dir: Path | str, family: str) -> int:
    """Logged runs of the family, repeats included; 0 for an unknown family or an empty journal."""
    conn = index.open_for_reading(Path(runs_dir))
    if conn is None:
        return 0
    try:
        return index.count_runs(conn, family)
    finally:
        conn.close()


def trial_count(runs_dir: Path | str, family: str) -> int:
    """Distinct variants of the family; 0 for an unknown family or an empty journal."""
    conn = index.open_for_reading(Path(runs_dir))
    if conn is None:
        return 0
    try:
        return index.count_variants(conn, family)
    finally:
        conn.close()


def _check_numbers(records: list[RunRecord]) -> None:
    """Per family: run numbers are 1 to n without gaps; trial numbers follow the order of first appearance."""
    by_family: dict[str, list[RunRecord]] = {}
    for record in records:
        by_family.setdefault(record.family, []).append(record)
    for family, runs in sorted(by_family.items()):
        runs.sort(key=lambda r: (r.trial.run_number, r.run_id))
        numbers = [r.trial.run_number for r in runs]
        if numbers != list(range(1, len(runs) + 1)):
            raise JournalFormatError(
                f"family {family!r}: the run numbers must be 1 to {len(runs)} without gaps or repeats, got {numbers}"
            )
        seen: dict[str, int] = {}
        for run in runs:
            new = run.trial.variant_hash not in seen
            if new:
                seen[run.trial.variant_hash] = len(seen) + 1
            expected = (seen[run.trial.variant_hash], len(seen), new)
            stored = (run.trial.trial_number, run.trial.trial_count, run.trial.new_variant)
            if stored != expected:
                raise JournalFormatError(
                    f"family {family!r}, run {run.run_id}: (trial_number, trial_count, new_variant) is {stored} "
                    f"but the order of first appearance gives {expected}"
                )


def rebuild_index(runs_dir: Path | str) -> int:
    """Build the index again from the run folders and return the number of runs.

    Reads every ``run.json`` (the numbers come from the files, nothing is renumbered), checks them, writes
    ``index.sqlite.tmp`` and replaces ``index.sqlite``. Raises ``JournalFormatError`` naming every unreadable folder, or
    for numbers that are not consistent per family; the old index is untouched then. Run it when no other process
    writes to the journal. A missing folder has nothing to rebuild and returns 0.
    """
    base = Path(runs_dir)
    if not base.is_dir():
        return 0
    records: list[RunRecord] = []
    problems: list[str] = []
    for name in sorted(index.run_folders(base)):
        try:
            records.append(_read_record(base / name / RUN_JSON, name))
        except (JournalFormatError, OSError) as error:
            problems.append(f"{name}: {error}")
    if problems:
        raise JournalFormatError("cannot rebuild the index, unreadable run folders:\n" + "\n".join(problems))
    _check_numbers(records)

    target = index.index_path(base)
    temporary = target.with_name(target.name + ".tmp")
    temporary.unlink(missing_ok=True)
    conn = index.connect(temporary, DEFAULT_BUSY_TIMEOUT)
    try:
        index.begin_immediate(conn)
        index.ensure_schema(conn, temporary)
        for record in sorted(records, key=lambda r: (r.family, r.trial.run_number)):
            index.insert_row(conn, record.summary())
        index.commit(conn)
    except BaseException:
        conn.close()
        temporary.unlink(missing_ok=True)
        raise
    conn.close()
    os.replace(temporary, target)
    return len(records)
