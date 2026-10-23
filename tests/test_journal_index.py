"""The index: rebuild from the folders, never renumber, stale detection (docs/journal.md, "The index")."""

import shutil
import sqlite3
from datetime import UTC, datetime

import pytest

from backtest_agent.journal import (
    CodeVersion,
    JournalFormatError,
    JournalIndexStale,
    RunSummary,
    get_run,
    list_runs,
    rebuild_index,
    record_run,
    run_count,
    trial_count,
)
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


def snapshot(runs):
    return (
        list_runs(runs),
        [(f, run_count(runs, f), trial_count(runs, f)) for f in ("sma_crossover", "buy_and_hold")],
    )


def drop_row(runs, run_id) -> None:
    conn = sqlite3.connect(str(runs / "index.sqlite"))
    conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
    conn.commit()
    conn.close()


# --- rebuild ---------------------------------------------------------------------------------------


def test_the_rebuilt_index_is_the_same_index(tmp_path) -> None:
    log_four(tmp_path)
    before = snapshot(tmp_path)
    assert rebuild_index(tmp_path) == 4  # replaces the existing index
    assert snapshot(tmp_path) == before
    (tmp_path / "index.sqlite").unlink()
    assert rebuild_index(tmp_path) == 4  # creates a missing one
    assert snapshot(tmp_path) == before
    assert before[1] == [("sma_crossover", 3, 2), ("buy_and_hold", 1, 1)]


def test_rebuild_leaves_no_temporary_index_behind(tmp_path) -> None:
    log_four(tmp_path)
    rebuild_index(tmp_path)
    assert not (tmp_path / "index.sqlite.tmp").exists()


def test_rebuild_never_renumbers_by_time(tmp_path) -> None:
    late = log(tmp_path, sma_spec(), 50)  # logged first, but with the later clock time
    early = log(tmp_path, sma_spec(slow=4), 10)
    assert (late.trial.run_number, early.trial.run_number) == (1, 2)
    before = list_runs(tmp_path)
    rebuild_index(tmp_path)
    after = list_runs(tmp_path)
    assert after == before
    assert {r.run_id: (r.run_number, r.trial_number) for r in after} == {late.run_id: (1, 1), early.run_id: (2, 2)}


def test_rebuild_of_a_missing_folder_has_nothing_to_do(tmp_path) -> None:
    assert rebuild_index(tmp_path / "none") == 0
    assert not (tmp_path / "none").exists()


def test_rebuild_of_an_empty_folder_makes_an_empty_index(tmp_path) -> None:
    assert rebuild_index(tmp_path) == 0
    assert list_runs(tmp_path) == ()


def test_rebuild_ignores_dot_folders_and_plain_files(tmp_path) -> None:
    log_four(tmp_path)
    (tmp_path / ".tmp-left-over-1234").mkdir()
    (tmp_path / ".tmp-left-over-1234" / "run.json").write_text("not json")
    (tmp_path / "notes.txt").write_text("hello")
    assert rebuild_index(tmp_path) == 4


def test_rebuild_names_every_unreadable_folder_and_keeps_the_old_index(tmp_path) -> None:
    records = log_four(tmp_path)
    (tmp_path / records[0].run_id / "run.json").write_text("{broken", encoding="utf-8")
    (tmp_path / records[1].run_id / "run.json").unlink()
    (tmp_path / "stranger").mkdir()
    before = (tmp_path / "index.sqlite").read_bytes()
    with pytest.raises(JournalFormatError) as error:
        rebuild_index(tmp_path)
    for name in (records[0].run_id, records[1].run_id, "stranger"):
        assert name in str(error.value)
    assert (tmp_path / "index.sqlite").read_bytes() == before
    assert not (tmp_path / "index.sqlite.tmp").exists()


def test_rebuild_refuses_a_folder_whose_name_is_not_its_run_id(tmp_path) -> None:
    records = log_four(tmp_path)
    shutil.copytree(tmp_path / records[0].run_id, tmp_path / "copy-of-the-first-run")
    with pytest.raises(JournalFormatError, match="differs from the folder name"):
        rebuild_index(tmp_path)


def test_rebuild_refuses_a_gap_in_the_run_numbers(tmp_path) -> None:
    records = log_four(tmp_path)  # sma runs 1, 2, 3
    shutil.rmtree(tmp_path / records[1].run_id)  # run 2 of sma_crossover is gone
    with pytest.raises(JournalFormatError, match=r"run numbers must be 1 to 2 without gaps.*\[1, 3\]"):
        rebuild_index(tmp_path)


def test_rebuild_refuses_a_repeated_run_number(tmp_path) -> None:
    records = log_four(tmp_path)
    edit_run_json(tmp_path, records[1].run_id, lambda d: d["trial"].update(run_number=1))
    with pytest.raises(JournalFormatError, match=r"without gaps or repeats.*\[1, 1, 3\]"):
        rebuild_index(tmp_path)


def test_rebuild_refuses_run_numbers_that_do_not_start_at_one(tmp_path) -> None:
    records = log_four(tmp_path)
    shutil.rmtree(tmp_path / records[0].run_id)
    with pytest.raises(JournalFormatError, match="without gaps"):
        rebuild_index(tmp_path)


@pytest.mark.parametrize(
    "index, change, expected",
    [
        (2, {"trial_number": 1}, "(1, 2, True) but the order of first appearance gives (2, 2, True)"),  # new variant
        (1, {"trial_number": 2}, "(2, 1, False) but the order of first appearance gives (1, 1, False)"),  # repeat
        (2, {"trial_count": 3}, "(2, 3, True) but the order of first appearance gives (2, 2, True)"),
        (1, {"new_variant": True}, "(1, 1, True) but the order of first appearance gives (1, 1, False)"),
        (2, {"new_variant": False}, "(2, 2, False) but the order of first appearance gives (2, 2, True)"),
    ],
    ids=["new-variant-number", "repeat-number", "trial-count", "repeat-flag", "new-flag"],
)
def test_rebuild_refuses_trial_numbers_that_do_not_follow_the_first_appearance(
    tmp_path, index, change, expected
) -> None:
    records = log_four(tmp_path)
    edit_run_json(tmp_path, records[index].run_id, lambda d: d["trial"].update(change))
    with pytest.raises(
        JournalFormatError, match=r"family 'sma_crossover'.*" + expected.replace("(", r"\(").replace(")", r"\)")
    ):
        rebuild_index(tmp_path)


def test_rebuild_refuses_a_stored_variant_hash_that_does_not_match_the_spec(tmp_path) -> None:
    records = log_four(tmp_path)
    edit_run_json(tmp_path, records[2].run_id, lambda d: d["trial"].update(variant_hash="0" * 64))
    with pytest.raises(JournalFormatError, match="variant_hash does not match"):
        rebuild_index(tmp_path)


# --- the index must agree with the folders ---------------------------------------------------------


def calls(runs):
    return {
        "record_run": lambda: record_run(evaluation_of(hold_spec()), runs, generated_at=at(99), code_version=CODE),
        "list_runs": lambda: list_runs(runs),
        "run_count": lambda: run_count(runs, "sma_crossover"),
        "trial_count": lambda: trial_count(runs, "sma_crossover"),
    }


@pytest.mark.parametrize("call", ["record_run", "list_runs", "run_count", "trial_count"])
def test_an_orphan_folder_makes_the_index_stale(tmp_path, call) -> None:
    records = log_four(tmp_path)
    drop_row(tmp_path, records[3].run_id)  # the state after a crash between the rename and the commit
    with pytest.raises(JournalIndexStale, match=r"without a row in the index: " + records[3].run_id) as error:
        calls(tmp_path)[call]()
    assert "rebuild_index" in str(error.value)


@pytest.mark.parametrize("call", ["record_run", "list_runs", "run_count", "trial_count"])
def test_a_deleted_folder_makes_the_index_stale(tmp_path, call) -> None:
    records = log_four(tmp_path)
    shutil.rmtree(tmp_path / records[0].run_id)
    with pytest.raises(JournalIndexStale, match=r"without a run folder: " + records[0].run_id):
        calls(tmp_path)[call]()


@pytest.mark.parametrize("call", ["record_run", "list_runs", "run_count", "trial_count"])
def test_a_missing_index_with_run_folders_is_stale_and_does_not_restart_the_counter(tmp_path, call) -> None:
    log_four(tmp_path)
    (tmp_path / "index.sqlite").unlink()
    with pytest.raises(JournalIndexStale, match="without a row in the index"):
        calls(tmp_path)[call]()
    assert not (tmp_path / "index.sqlite").exists() or call == "record_run"
    names = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
    assert len(names) == 4  # no new run folder


@pytest.mark.parametrize("call", ["record_run", "list_runs", "run_count", "trial_count"])
def test_a_stray_directory_makes_the_index_stale(tmp_path, call) -> None:
    log_four(tmp_path)
    (tmp_path / "stranger").mkdir()
    with pytest.raises(JournalIndexStale, match=r"without a row in the index: stranger"):
        calls(tmp_path)[call]()
    assert (tmp_path / "stranger").is_dir() and not any((tmp_path / "stranger").iterdir())  # left alone


def test_a_stale_record_run_writes_no_folder(tmp_path) -> None:
    records = log_four(tmp_path)
    drop_row(tmp_path, records[3].run_id)
    before = sorted(p.name for p in tmp_path.iterdir())
    with pytest.raises(JournalIndexStale):
        calls(tmp_path)["record_run"]()
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_after_a_rebuild_the_journal_works_again_and_the_numbers_continue(tmp_path) -> None:
    records = log_four(tmp_path)
    drop_row(tmp_path, records[3].run_id)
    rebuild_index(tmp_path)
    assert run_count(tmp_path, "buy_and_hold") == 1  # the orphan is counted again
    again = log(tmp_path, hold_spec(), 20)
    assert (again.trial.run_number, again.trial.trial_number, again.trial.new_variant) == (2, 1, False)


def test_dot_folders_and_plain_files_do_not_make_the_index_stale(tmp_path) -> None:
    log_four(tmp_path)
    (tmp_path / ".tmp-left-over-1234").mkdir()
    (tmp_path / "notes.txt").write_text("hello")
    assert len(list_runs(tmp_path)) == 4
    assert log(tmp_path, hold_spec(), 30).trial.run_number == 2


def test_an_empty_index_file_is_an_empty_journal(tmp_path) -> None:
    (tmp_path / "index.sqlite").write_bytes(b"")
    assert list_runs(tmp_path) == ()
    assert log(tmp_path, hold_spec(), 1).trial.run_number == 1


# --- the version of the index ----------------------------------------------------------------------


@pytest.mark.parametrize("call", ["record_run", "list_runs", "run_count", "trial_count"])
def test_an_index_of_another_version_is_refused_until_it_is_rebuilt(tmp_path, call) -> None:
    log_four(tmp_path)
    conn = sqlite3.connect(str(tmp_path / "index.sqlite"))
    conn.execute("PRAGMA user_version = 2")
    conn.close()
    with pytest.raises(JournalFormatError, match="index version 2 is not 1.*rebuild_index"):
        calls(tmp_path)[call]()
    rebuild_index(tmp_path)
    assert len(list_runs(tmp_path)) == 4


def test_an_unrelated_sqlite_file_is_refused(tmp_path) -> None:
    conn = sqlite3.connect(str(tmp_path / "index.sqlite"))
    conn.execute("CREATE TABLE other (x INTEGER)")
    conn.commit()
    conn.close()
    with pytest.raises(JournalFormatError):
        list_runs(tmp_path)
    with pytest.raises(JournalFormatError):
        calls(tmp_path)["record_run"]()


def test_get_run_does_not_need_the_index(tmp_path) -> None:
    records = log_four(tmp_path)
    (tmp_path / "index.sqlite").unlink()
    assert get_run(tmp_path, records[0].run_id) == records[0]


# --- the rows of the index -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("dirty", [True, False, None])
def test_the_listed_summary_holds_every_field(tmp_path, dirty) -> None:
    code = CodeVersion("f" * 40 if dirty is not None else "unknown", dirty)
    first = record_run(evaluation_of(sma_spec()), tmp_path, generated_at=at(7), code_version=code)
    second = record_run(evaluation_of(sma_spec()), tmp_path, generated_at=at(8), code_version=code)
    newer, older = list_runs(tmp_path)
    assert older == RunSummary(
        run_id=first.run_id,
        generated_at=datetime(2026, 1, 15, 10, 30, 7, tzinfo=UTC),
        family="sma_crossover",
        variant_hash=first.trial.variant_hash,
        run_number=1,
        trial_number=1,
        trial_count=1,
        new_variant=True,
        strategy_name="SMA A",
        strategy_data_hash=first.evaluation["strategy"]["data_hash"],
        benchmark_data_hash=first.evaluation["benchmark"]["data_hash"],
        code_commit=code.commit,
        code_dirty=dirty,
    )
    assert (newer.run_id, newer.run_number, newer.trial_number, newer.trial_count, newer.new_variant) == (
        second.run_id,
        2,
        1,
        1,
        False,
    )
    assert older == first.summary()
