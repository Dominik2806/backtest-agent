"""The SQLite index of the journal (docs/journal.md, "The index"). Standard library only.

The index is a cache of the run folders: it can always be rebuilt from them. Connections run in autocommit mode
(``isolation_level=None``) and every transaction is explicit, so ``BEGIN IMMEDIATE`` really is the first statement of a
write. Callers close their connections themselves.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from backtest_agent.journal.errors import JournalBusyError, JournalFormatError, JournalIndexStale
from backtest_agent.journal.models import TIMESTAMP_FORMAT, RunSummary

INDEX_FILE = "index.sqlite"
READ_BUSY_TIMEOUT = 5.0  # seconds a reader waits for a running writer before it reports a mismatch
USER_VERSION = 1
_COLUMNS = (
    "run_id",
    "generated_at",
    "family",
    "variant_hash",
    "run_number",
    "trial_number",
    "trial_count",
    "new_variant",
    "strategy_name",
    "strategy_data_hash",
    "benchmark_data_hash",
    "code_commit",
    "code_dirty",
)
_SCHEMA = """
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    generated_at TEXT NOT NULL,
    family TEXT NOT NULL,
    variant_hash TEXT NOT NULL,
    run_number INTEGER NOT NULL,
    trial_number INTEGER NOT NULL,
    trial_count INTEGER NOT NULL,
    new_variant INTEGER NOT NULL,
    strategy_name TEXT NOT NULL,
    strategy_data_hash TEXT NOT NULL,
    benchmark_data_hash TEXT NOT NULL,
    code_commit TEXT NOT NULL,
    code_dirty INTEGER,
    UNIQUE (family, run_number)
)
"""


def index_path(runs_dir: Path) -> Path:
    return runs_dir / INDEX_FILE


def run_folders(runs_dir: Path) -> set[str]:
    """Names of the run folders: every directory of ``runs_dir`` that does not start with a dot."""
    if not runs_dir.is_dir():
        return set()
    return {entry.name for entry in runs_dir.iterdir() if entry.is_dir() and not entry.name.startswith(".")}


def connect(path: Path, busy_timeout: float) -> sqlite3.Connection:
    return sqlite3.connect(str(path), timeout=busy_timeout, isolation_level=None)


def begin_immediate(conn: sqlite3.Connection) -> None:
    """Take the write lock; ``JournalBusyError`` if another connection keeps it longer than the busy timeout."""
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as error:
        if "locked" in str(error) or "busy" in str(error):
            raise JournalBusyError(
                "the journal index is locked by another process; nothing was written, try again later"
            ) from error
        raise


def commit(conn: sqlite3.Connection) -> None:
    conn.execute("COMMIT")


def rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ROLLBACK")
    except sqlite3.Error:  # no transaction is open (the lock was never taken)
        pass


def _has_runs_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'runs'").fetchone()
    return row is not None


def _is_blank(conn: sqlite3.Connection) -> bool:
    """True for a database without any table: a new file, which is an empty journal."""
    return conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0


def ensure_schema(conn: sqlite3.Connection, path: Path) -> None:
    """Inside a write transaction: create the schema of a new index, refuse an index of another version."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == 0 and _is_blank(conn):
        conn.execute(_SCHEMA)
        conn.execute(f"PRAGMA user_version = {USER_VERSION}")
    elif version != USER_VERSION or not _has_runs_table(conn):
        raise JournalFormatError(
            f"{path}: index version {version} is not {USER_VERSION}; call rebuild_index to create a new index"
        )


def check_in_sync(conn: sqlite3.Connection | None, runs_dir: Path) -> None:
    """``JournalIndexStale`` unless the run folders on disk are exactly the run ids of the rows of the index."""
    rows = set() if conn is None else {r[0] for r in conn.execute("SELECT run_id FROM runs")}
    folders = run_folders(runs_dir)
    if rows == folders:
        return
    without_row, without_folder = sorted(folders - rows), sorted(rows - folders)
    parts = []
    if without_row:
        parts.append(f"run folders without a row in the index: {', '.join(without_row[:5])}")
    if without_folder:
        parts.append(f"rows of the index without a run folder: {', '.join(without_folder[:5])}")
    if conn is None:
        parts.append("the index does not exist")
    raise JournalIndexStale(
        f"the journal in {runs_dir} and its index disagree ({'; '.join(parts)}); call rebuild_index(runs_dir)"
    )


def numbers_for(conn: sqlite3.Connection, family: str, variant: str) -> tuple[int, int, int, bool]:
    """``(run_number, trial_number, trial_count, new_variant)`` of the next run of ``family`` with this variant."""
    runs = conn.execute("SELECT COUNT(*) FROM runs WHERE family = ?", (family,)).fetchone()[0]
    distinct = conn.execute("SELECT COUNT(DISTINCT variant_hash) FROM runs WHERE family = ?", (family,)).fetchone()[0]
    known = conn.execute(
        "SELECT trial_number FROM runs WHERE family = ? AND variant_hash = ? LIMIT 1", (family, variant)
    ).fetchone()
    if known is not None:
        return runs + 1, known[0], distinct, False
    return runs + 1, distinct + 1, distinct + 1, True


def insert_row(conn: sqlite3.Connection, summary: RunSummary) -> None:
    values = (
        summary.run_id,
        summary.generated_at.astimezone(UTC).strftime(TIMESTAMP_FORMAT),
        summary.family,
        summary.variant_hash,
        summary.run_number,
        summary.trial_number,
        summary.trial_count,
        int(summary.new_variant),
        summary.strategy_name,
        summary.strategy_data_hash,
        summary.benchmark_data_hash,
        summary.code_commit,
        None if summary.code_dirty is None else int(summary.code_dirty),
    )
    conn.execute(f"INSERT INTO runs ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' * len(_COLUMNS))})", values)


def _summary(row: tuple) -> RunSummary:
    (
        run_id,
        stamp,
        family,
        variant,
        run_number,
        trial_number,
        trial_count,
        new,
        name,
        s_hash,
        b_hash,
        commit,
        dirty,
    ) = row
    return RunSummary(
        run_id=run_id,
        generated_at=datetime.strptime(stamp, TIMESTAMP_FORMAT).replace(tzinfo=UTC),
        family=family,
        variant_hash=variant,
        run_number=run_number,
        trial_number=trial_number,
        trial_count=trial_count,
        new_variant=bool(new),
        strategy_name=name,
        strategy_data_hash=s_hash,
        benchmark_data_hash=b_hash,
        code_commit=commit,
        code_dirty=None if dirty is None else bool(dirty),
    )


def open_for_reading(runs_dir: Path) -> sqlite3.Connection | None:
    """A connection to a checked index, or None for an empty journal (no folder, or no runs and no index).

    Raises ``JournalIndexStale`` if the folders and the rows differ (after waiting for a running writer, up to
    ``READ_BUSY_TIMEOUT`` seconds, then ``JournalBusyError``), ``JournalFormatError`` for another index version.
    The caller closes the connection.
    """
    path = index_path(runs_dir)
    if not path.is_file():
        check_in_sync(None, runs_dir)
        return None
    conn = connect(path, READ_BUSY_TIMEOUT)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0 and _is_blank(conn):
            check_in_sync(None, runs_dir)
            conn.close()
            return None
        if version != USER_VERSION or not _has_runs_table(conn):
            raise JournalFormatError(
                f"{path}: index version {version} is not {USER_VERSION}; call rebuild_index to create a new index"
            )
        try:
            check_in_sync(conn, runs_dir)
        except JournalIndexStale:
            # A writer between its rename and its commit shows a folder without a row: wait for it, then look again.
            begin_immediate(conn)
            try:
                check_in_sync(conn, runs_dir)
            finally:
                rollback(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def select_summaries(conn: sqlite3.Connection, family: str | None, limit: int | None) -> tuple[RunSummary, ...]:
    sql = f"SELECT {', '.join(_COLUMNS)} FROM runs"
    args: list[object] = []
    if family is not None:
        sql += " WHERE family = ?"
        args.append(family)
    sql += " ORDER BY generated_at DESC, run_id DESC"
    if limit is not None:
        sql += " LIMIT ?"
        args.append(limit)
    return tuple(_summary(row) for row in conn.execute(sql, args))


def count_runs(conn: sqlite3.Connection, family: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM runs WHERE family = ?", (family,)).fetchone()[0]


def count_variants(conn: sqlite3.Connection, family: str) -> int:
    return conn.execute("SELECT COUNT(DISTINCT variant_hash) FROM runs WHERE family = ?", (family,)).fetchone()[0]
