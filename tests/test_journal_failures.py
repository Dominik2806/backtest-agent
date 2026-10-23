"""Failure paths of the journal: all or nothing, guards, locks, unreadable files (docs/journal.md)."""

import shutil
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest

from backtest_agent.journal import (
    JournalBusyError,
    JournalFormatError,
    JournalIndexStale,
    RunNotFoundError,
    get_run,
    list_runs,
    record_run,
    run_count,
    trial_count,
)
from backtest_agent.journal import index as journal_index
from backtest_agent.journal import store as journal_store
from backtest_agent.journal.models import RunRecord
from journal_helpers import (
    CODE,
    at,
    edit_run_json,
    evaluation_of,
    hold_spec,
    log,
    log_four,
    no_repo_runs,  # noqa: F401 - fixture used through pytestmark
    sma_spec,
)

pytestmark = pytest.mark.usefixtures("no_repo_runs")


def listing(runs: Path) -> list[str]:
    return sorted(p.name for p in runs.iterdir()) if runs.exists() else []


def only_an_empty_index_or_nothing(runs: Path) -> bool:
    names = listing(runs)
    return names in ([], ["index.sqlite"]) and (not names or (runs / "index.sqlite").stat().st_size == 0)


class Spy(sqlite3.Connection):
    closed = False

    def close(self) -> None:
        self.closed = True
        super().close()


@pytest.fixture
def connections(monkeypatch):
    """Every connection the journal opens, so a test can check that each one was closed."""
    opened: list[Spy] = []

    def connect(path, busy_timeout):
        conn = sqlite3.connect(str(path), timeout=busy_timeout, isolation_level=None, factory=Spy)
        opened.append(conn)
        return conn

    monkeypatch.setattr(journal_index, "connect", connect)
    return opened


# --- the write is all or nothing -------------------------------------------------------------------


def test_a_failing_index_insert_leaves_no_folder_and_no_row(tmp_path, monkeypatch) -> None:
    runs = tmp_path / "runs"

    def boom(conn, summary):
        raise RuntimeError("index insert failed")

    monkeypatch.setattr(journal_index, "insert_row", boom)
    with pytest.raises(RuntimeError, match="index insert failed"):
        log(runs, hold_spec(), 1)
    assert only_an_empty_index_or_nothing(runs)
    monkeypatch.undo()
    assert list_runs(runs) == ()


def test_a_failing_commit_leaves_no_folder_and_no_row(tmp_path, monkeypatch) -> None:
    runs = tmp_path / "runs"

    def boom(conn):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(journal_index, "commit", boom)
    with pytest.raises(sqlite3.OperationalError, match="disk full"):
        log(runs, hold_spec(), 1)
    assert only_an_empty_index_or_nothing(runs)
    monkeypatch.undo()
    assert list_runs(runs) == ()
    assert log(runs, hold_spec(), 1).trial.run_number == 1  # the number was not used up


def test_a_failure_does_not_touch_the_runs_that_exist(tmp_path, monkeypatch) -> None:
    records = log_four(tmp_path)
    before = (listing(tmp_path), list_runs(tmp_path))

    def boom(conn, summary):
        raise RuntimeError("index insert failed")

    monkeypatch.setattr(journal_index, "insert_row", boom)
    with pytest.raises(RuntimeError):
        log(tmp_path, sma_spec(slow=5), 10)
    monkeypatch.undo()
    assert (listing(tmp_path), list_runs(tmp_path)) == before
    assert [get_run(tmp_path, r.run_id) for r in records] == records
    assert (
        log(tmp_path, sma_spec(slow=5), 10).trial.run_number == 4
    )  # same second, same id: the failed try left no trace


def test_a_failure_while_writing_the_files_removes_the_temporary_folder(tmp_path, monkeypatch) -> None:
    runs = tmp_path / "runs"

    def boom(self, target):
        raise OSError("rename failed")

    monkeypatch.setattr(Path, "rename", boom)
    with pytest.raises(OSError, match="rename failed"):
        log(runs, hold_spec(), 1)
    assert only_an_empty_index_or_nothing(runs)  # no .tmp-* folder either


def test_a_record_that_cannot_be_rendered_writes_nothing(tmp_path, monkeypatch) -> None:
    runs = tmp_path / "runs"

    def boom(self):
        raise ValueError("Out of range float values are not JSON compliant")

    monkeypatch.setattr(RunRecord, "to_json", boom)
    with pytest.raises(ValueError, match="not JSON compliant"):
        log(runs, hold_spec(), 1)
    assert only_an_empty_index_or_nothing(runs)


# --- the run id ------------------------------------------------------------------------------------


def test_the_same_run_id_twice_raises_and_changes_nothing(tmp_path) -> None:
    first = log(tmp_path, hold_spec(), 1)
    folder = tmp_path / first.run_id
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    with pytest.raises(FileExistsError, match="run id already exists.*use a later generated_at"):
        log(tmp_path, hold_spec(), 1)
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before
    assert listing(tmp_path) == sorted(["index.sqlite", first.run_id])
    assert (run_count(tmp_path, "buy_and_hold"), trial_count(tmp_path, "buy_and_hold")) == (1, 1)
    assert log(tmp_path, hold_spec(), 2).trial.run_number == 2  # a later time works


def test_a_naive_time_is_refused_and_nothing_is_created(tmp_path) -> None:
    runs = tmp_path / "runs"
    with pytest.raises(ValueError, match="timezone-aware"):
        record_run(evaluation_of(hold_spec()), runs, generated_at=datetime(2026, 1, 15, 10, 30), code_version=CODE)
    assert not runs.exists()


@pytest.mark.parametrize(
    "bad",
    ["..", "../outside", "a/b", "a\\b", "C:x", "CON", "con.txt", "", ".hidden", "x" * 121, "ends-with.", "a..b"],
)
def test_an_unsafe_run_id_is_refused_and_nothing_is_created(tmp_path, monkeypatch, bad) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setattr(journal_store, "make_run_id", lambda evaluation, generated_at: bad)
    with pytest.raises(ValueError, match="not a safe run id"):
        log(runs, hold_spec(), 1)
    assert not runs.exists()
    assert not (tmp_path / "outside").exists()


def test_a_run_folder_must_be_a_direct_child_of_the_journal(tmp_path, monkeypatch) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setattr(journal_store, "check_run_id", lambda run_id: run_id)  # take the first guard away
    monkeypatch.setattr(journal_store, "make_run_id", lambda evaluation, generated_at: "../outside")
    with pytest.raises(ValueError, match="directly inside"):
        log(runs, hold_spec(), 1)
    assert not runs.exists()
    assert not (tmp_path / "outside").exists()


@pytest.mark.parametrize("bad", ["..", "../x", "a/b", "C:x", "CON", "", ".hidden"])
def test_get_run_refuses_an_unsafe_id(tmp_path, bad) -> None:
    log(tmp_path, hold_spec(), 1)
    with pytest.raises(ValueError, match="not a safe run id"):
        get_run(tmp_path, bad)


def test_get_run_of_an_unknown_run(tmp_path) -> None:
    log(tmp_path, hold_spec(), 1)
    with pytest.raises(RunNotFoundError, match="no run"):
        get_run(tmp_path, "20990101T000000Z-nothing-deadbeef")
    with pytest.raises(RunNotFoundError):
        get_run(tmp_path / "no-such-journal", "20990101T000000Z-nothing-deadbeef")


# --- reading run.json ------------------------------------------------------------------------------


def write_raw(tmp_path, text: str) -> str:
    record = log(tmp_path, hold_spec(), 1)
    (tmp_path / record.run_id / "run.json").write_bytes(text.encode("utf-8"))
    return record.run_id


@pytest.mark.parametrize("text", ["", "{not json", "[1, 2]", "null", '"text"', "﻿{}"], ids=repr)
def test_a_run_json_that_is_not_a_json_object_is_refused(tmp_path, text) -> None:
    run_id = write_raw(tmp_path, text)
    with pytest.raises(JournalFormatError, match="run.json"):
        get_run(tmp_path, run_id)


def test_a_run_json_that_is_not_utf8_is_refused(tmp_path) -> None:
    record = log(tmp_path, hold_spec(), 1)
    (tmp_path / record.run_id / "run.json").write_bytes(b"\xff\xfe{}")
    with pytest.raises(JournalFormatError, match="cannot be read"):
        get_run(tmp_path, record.run_id)


@pytest.mark.parametrize("version", [2, 0, "1", None, True, 1.5])
def test_an_unknown_schema_version_is_refused(tmp_path, version) -> None:
    record = log(tmp_path, hold_spec(), 1)
    edit_run_json(tmp_path, record.run_id, lambda d: d.update(schema_version=version))
    with pytest.raises(JournalFormatError, match="unsupported schema_version"):
        get_run(tmp_path, record.run_id)


def test_a_missing_or_an_unknown_key_is_refused(tmp_path) -> None:
    record = log(tmp_path, hold_spec(), 1)
    edit_run_json(tmp_path, record.run_id, lambda d: d.pop("trades"))
    with pytest.raises(JournalFormatError, match="keys must be exactly"):
        get_run(tmp_path, record.run_id)
    edit_run_json(tmp_path, record.run_id, lambda d: d.update(trades={}, extra=1))
    with pytest.raises(JournalFormatError, match="keys must be exactly"):
        get_run(tmp_path, record.run_id)


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda d: d.update(generated_at="2026-01-15 10:30:01"), "generated_at"),
        (lambda d: d.update(generated_at=5), "generated_at"),
        (lambda d: d.update(code_version={"commit": "x"}), "code_version"),
        (lambda d: d["code_version"].update(dirty="no"), "code_version"),
        (lambda d: d.update(trial={"variant_hash": "x"}), "trial must have exactly"),
        (lambda d: d["trial"].update(run_number=0), "trial holds a bad value"),
        (lambda d: d["trial"].update(run_number=True), "trial holds a bad value"),
        (lambda d: d["trial"].update(trial_count=1.5), "trial holds a bad value"),
        (lambda d: d["trial"].update(new_variant=1), "trial holds a bad value"),
        (lambda d: d.update(spec=[]), "must be JSON objects"),
        (lambda d: d["costs"].pop("benchmark"), "costs must have"),
        (lambda d: d["costs"]["strategy"].pop("cost_share"), "costs must have"),
        (lambda d: d["evaluation"]["strategy"].pop("data_hash"), "lacks signal.id"),
        (lambda d: d["evaluation"]["benchmark"].update(data_hash=5), "must be strings"),
        (lambda d: d.update(family="sma_crossover"), "is not the signal id of the stored spec"),
        (lambda d: d["spec"]["signal"].update(id="sma_crossover"), "is not the signal id of the stored spec"),
        (lambda d: d["spec"].update(initial_capital=999.0), "variant_hash does not match"),
        (lambda d: d.update(run_id="20990101T000000Z-other-deadbeef"), "differs from the folder name"),
    ],
)
def test_a_run_json_with_a_bad_value_is_refused(tmp_path, change, message) -> None:
    record = log(tmp_path, hold_spec(), 1)
    edit_run_json(tmp_path, record.run_id, change)
    with pytest.raises(JournalFormatError, match=message):
        get_run(tmp_path, record.run_id)


def test_a_format_error_names_the_file(tmp_path) -> None:
    record = log(tmp_path, hold_spec(), 1)
    edit_run_json(tmp_path, record.run_id, lambda d: d.update(schema_version=2))
    with pytest.raises(JournalFormatError) as error:
        get_run(tmp_path, record.run_id)
    assert str(tmp_path / record.run_id / "run.json") in str(error.value)
    assert isinstance(error.value, ValueError)


# --- the lock --------------------------------------------------------------------------------------


def test_a_busy_index_raises_a_clear_error_and_writes_nothing(tmp_path) -> None:
    first = log(tmp_path, hold_spec(), 1)
    before = listing(tmp_path)
    holder = sqlite3.connect(str(tmp_path / "index.sqlite"), isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")  # another process is writing
    try:
        with pytest.raises(JournalBusyError, match="locked by another process.*nothing was written"):
            record_run(evaluation_of(sma_spec()), tmp_path, generated_at=at(2), code_version=CODE, busy_timeout=0.05)
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert listing(tmp_path) == before
    assert [r.run_id for r in list_runs(tmp_path)] == [first.run_id]
    assert log(tmp_path, sma_spec(), 3).trial.run_number == 1  # the lock is free again; the family sma starts at 1


def test_two_writers_never_get_the_same_number(tmp_path) -> None:
    # Distinct specs and times, evaluated before the threads start; each thread opens its own connection. The assertion
    # does not depend on the order in which the threads run.
    evaluations = [evaluation_of(sma_spec(slow=slow)) for slow in (3, 4, 5, 6)]

    def write(item):
        second, evaluation = item
        return record_run(evaluation, tmp_path, generated_at=at(second), code_version=CODE, busy_timeout=60.0)

    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(write, enumerate(evaluations, start=1)))
    assert sorted(r.trial.run_number for r in records) == [1, 2, 3, 4]
    assert sorted(r.trial.trial_number for r in records) == [1, 2, 3, 4]
    assert sorted(r.trial.trial_count for r in records) == [1, 2, 3, 4]
    assert len(list_runs(tmp_path)) == 4
    assert (run_count(tmp_path, "sma_crossover"), trial_count(tmp_path, "sma_crossover")) == (4, 4)


# --- connections are closed (Windows keeps the file locked otherwise) ------------------------------


def test_every_connection_is_closed_after_a_successful_run_and_the_reads(tmp_path, connections) -> None:
    log(tmp_path, hold_spec(), 1)
    list_runs(tmp_path)
    run_count(tmp_path, "buy_and_hold")
    trial_count(tmp_path, "buy_and_hold")
    assert len(connections) == 4
    assert all(conn.closed for conn in connections)
    (tmp_path / "index.sqlite").replace(tmp_path / "moved.sqlite")  # fails on Windows if a connection is open


def test_every_connection_is_closed_after_a_failure(tmp_path, connections, monkeypatch) -> None:
    log(tmp_path, hold_spec(), 1)
    with pytest.raises(FileExistsError):
        log(tmp_path, hold_spec(), 1)

    def boom(conn, summary):
        raise RuntimeError("insert failed")

    monkeypatch.setattr(journal_index, "insert_row", boom)
    with pytest.raises(RuntimeError):
        log(tmp_path, sma_spec(), 5)
    assert len(connections) == 3
    assert all(conn.closed for conn in connections)


def test_every_connection_is_closed_after_a_busy_error_and_a_stale_index(tmp_path, connections) -> None:
    records = log_four(tmp_path)
    holder = sqlite3.connect(str(tmp_path / "index.sqlite"), isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(JournalBusyError):
            record_run(
                evaluation_of(sma_spec(slow=9)), tmp_path, generated_at=at(9), code_version=CODE, busy_timeout=0.05
            )
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    shutil.rmtree(tmp_path / records[0].run_id)  # now the index is stale
    with pytest.raises(JournalIndexStale):
        log(tmp_path, sma_spec(slow=9), 9)
    with pytest.raises(JournalIndexStale):
        list_runs(tmp_path)
    assert len(connections) == 7  # four runs, the busy attempt, the stale attempt and the stale read
    assert all(conn.closed for conn in connections)


def test_rebuild_closes_its_connection_also_when_it_fails(tmp_path, connections, monkeypatch) -> None:
    log_four(tmp_path)
    before = (tmp_path / "index.sqlite").read_bytes()

    def boom(conn, summary):
        raise RuntimeError("insert failed")

    monkeypatch.setattr(journal_index, "insert_row", boom)
    with pytest.raises(RuntimeError):
        journal_store.rebuild_index(tmp_path)
    assert all(conn.closed for conn in connections)
    assert not (tmp_path / "index.sqlite.tmp").exists()
    assert (tmp_path / "index.sqlite").read_bytes() == before  # the old index survives a failed rebuild


# --- readers and a running writer ------------------------------------------------------------------


def test_a_reader_during_a_write_waits_instead_of_reporting_a_stale_index(tmp_path, monkeypatch) -> None:
    log(tmp_path, hold_spec(), 1)
    monkeypatch.setattr(journal_index, "READ_BUSY_TIMEOUT", 0.05)
    real = journal_index.insert_row
    outcome: list[type] = []

    def reader_between_rename_and_commit(conn, summary):
        # the run folder exists, its row does not, and this writer still holds the lock
        try:
            list_runs(tmp_path)
        except Exception as error:  # noqa: BLE001 - the type is what the test is about
            outcome.append(type(error))
        real(conn, summary)

    monkeypatch.setattr(journal_index, "insert_row", reader_between_rename_and_commit)
    log(tmp_path, sma_spec(), 2)
    assert outcome == [JournalBusyError]
    assert len(list_runs(tmp_path)) == 2  # once the writer has committed, the journal is consistent again


def test_a_reader_during_a_write_ignores_the_temporary_folder(tmp_path, monkeypatch) -> None:
    log(tmp_path, hold_spec(), 1)
    monkeypatch.setattr(journal_index, "READ_BUSY_TIMEOUT", 0.05)
    real = Path.rename
    seen: list[int] = []

    def reader_before_the_rename(self, target):
        seen.append(len(list_runs(tmp_path)))  # the temporary folder exists; it must not count as a run
        return real(self, target)

    monkeypatch.setattr(Path, "rename", reader_before_the_rename)
    log(tmp_path, sma_spec(), 2)
    assert seen == [1]


# --- cleanup happens while the write lock is held --------------------------------------------------


@pytest.fixture
def watch_rollback(monkeypatch):
    """``watch(runs)`` records, each time the rollback runs, the temporary and the run folders that still exist."""
    seen: list[tuple[list[str], list[str]]] = []
    real = journal_index.rollback
    watched: list[Path] = []

    def rollback(conn):
        runs = watched[0]
        seen.append(
            (
                sorted(p.name for p in runs.glob(".tmp-*")),
                sorted(p.name for p in runs.iterdir() if p.is_dir() and not p.name.startswith(".")),
            )
        )
        real(conn)

    monkeypatch.setattr(journal_index, "rollback", rollback)

    def watch(runs: Path) -> list[tuple[list[str], list[str]]]:
        watched.append(runs)
        return seen

    return watch


def test_a_failure_before_the_rename_removes_the_temporary_folder_before_the_rollback(
    tmp_path, monkeypatch, watch_rollback
) -> None:
    seen = watch_rollback(tmp_path)

    def boom(self, target):
        assert list(tmp_path.glob(".tmp-*"))  # the temporary folder exists when the rename fails
        raise OSError("rename failed")

    monkeypatch.setattr(Path, "rename", boom)
    with pytest.raises(OSError, match="rename failed"):
        log(tmp_path, hold_spec(), 1)
    assert seen == [([], [])]  # no temporary folder and no run folder when the rollback ran


def test_a_failure_after_the_rename_removes_both_folders_before_the_rollback(
    tmp_path, monkeypatch, watch_rollback
) -> None:
    first = log(tmp_path, hold_spec(), 1)
    seen = watch_rollback(tmp_path)

    def boom(conn, summary):
        # at this point the new run folder has been renamed into place next to the first one
        assert len([p for p in tmp_path.iterdir() if p.is_dir() and not p.name.startswith(".")]) == 2
        raise RuntimeError("index insert failed")

    monkeypatch.setattr(journal_index, "insert_row", boom)
    with pytest.raises(RuntimeError, match="index insert failed"):
        log(tmp_path, sma_spec(), 2)
    assert seen == [([], [first.run_id])]  # only the earlier run is left when the rollback ran


def test_a_failing_commit_removes_both_folders_before_the_rollback(tmp_path, monkeypatch, watch_rollback) -> None:
    seen = watch_rollback(tmp_path)

    def boom(conn):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(journal_index, "commit", boom)
    with pytest.raises(sqlite3.OperationalError):
        log(tmp_path, hold_spec(), 1)
    assert seen == [([], [])]


# --- a reader that waits for the writer, then succeeds ---------------------------------------------


def test_a_reader_that_waits_for_the_writer_returns_both_runs(tmp_path, monkeypatch) -> None:
    log(tmp_path, hold_spec(), 1)
    monkeypatch.setattr(journal_index, "READ_BUSY_TIMEOUT", 30.0)
    saw_stale = threading.Event()
    real_check = journal_index.check_in_sync

    def check(conn, runs_dir):
        try:
            real_check(conn, runs_dir)
        except JournalIndexStale:
            if threading.current_thread().name == "reader":
                saw_stale.set()
            raise

    monkeypatch.setattr(journal_index, "check_in_sync", check)
    outcome: dict[str, object] = {}

    def read() -> None:
        try:
            outcome["runs"] = list_runs(tmp_path)
        except BaseException as error:  # noqa: BLE001 - reported by the assertions below
            outcome["error"] = error

    reader = threading.Thread(target=read, name="reader")
    real_insert = journal_index.insert_row

    def writer_inside_its_critical_section(conn, summary):
        # the run folder exists, its row does not, and this writer holds the lock
        reader.start()
        assert saw_stale.wait(20), "the reader never saw the folder without a row"
        time.sleep(0.3)  # let the reader block on the lock; the assertions below do not depend on this
        real_insert(conn, summary)

    monkeypatch.setattr(journal_index, "insert_row", writer_inside_its_critical_section)
    log(tmp_path, sma_spec(), 2)
    reader.join(30)
    assert not reader.is_alive()
    assert "error" not in outcome, outcome.get("error")
    assert len(outcome["runs"]) == 2
