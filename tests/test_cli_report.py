"""``bt report``: re-evaluate, compare, then write the same report again (docs/cli.md, ADR 0016).

The world is fixture R3b (the literals of docs/cli.md); the data hashes were computed with hashlib from the layout of
docs/data.md. A report of an unchanged run is byte-identical to the original; everything else is a refusal.
"""

import io
import json
import re
import shutil
from pathlib import Path

import pytest

from backtest_agent import experiment
from backtest_agent.cli import main
from backtest_agent.data import DataUnavailableError
from backtest_agent.journal.identity import variant_hash_of_dict
from cli_helpers import at, run_cli, write_spec
from report_helpers import A_CLOSE, A_OPEN, B_CLOSE, B_OPEN, P5, spec_for, world
from runner_helpers import LiteralProvider, price_frame

HASH_A = "61669f6e7476623e1289ff7dad8c8b767f36be44961c05ec4def3f45c15dd090"
HASH_A_LAST_CLOSE_150 = "84cff02fdbf6860d463ec79c2cebba456c5dac2a6331d47831eb2f9602ea01d7"
RUN_ID = re.compile(r"20260115T1030(?P<second>\d\d)Z-buy-and-hold-a-[0-9a-f]{8}")
REPORT_FILES = ("report.md", "report.html", "equity.svg", "drawdown.svg")


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    write_spec(tmp_path, spec_for(), "spec.yaml")
    return tmp_path


def provider() -> LiteralProvider:
    return LiteralProvider(world())


def changed_provider() -> LiteralProvider:
    """The world with another last close of A: other prices, the same dates."""
    return LiteralProvider(price_frame({"A": A_OPEN, "B": B_OPEN}, {"A": [*A_CLOSE[:-1], 150], "B": B_CLOSE}))


def run_id_of(out: str) -> str:
    match = RUN_ID.search(out)
    assert match, out
    return match.group(0)


def logged_run(*args: str, seconds: int = 0) -> str:
    result = run_cli(["run", "spec.yaml", *args], provider=provider(), clock=at(seconds))
    assert result.code == 0, result.err
    return run_id_of(result.out)


def report_bytes(workdir: Path, run_id: str, root: str = "reports") -> dict[str, bytes]:
    folder = workdir / root / run_id
    return {name: (folder / name).read_bytes() for name in REPORT_FILES}


def edit_run_json(workdir: Path, run_id: str, edit) -> None:
    path = workdir / "runs" / run_id / "run.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data)
    path.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def test_the_report_of_an_unchanged_second_run_is_byte_identical_and_the_journal_is_untouched(workdir: Path) -> None:
    logged_run(seconds=0)
    second = logged_run(seconds=1)  # a repeat of variant 1: run 2 of its family
    logged_run(seconds=2)  # a third run is logged before the report: the stored trial must still say run 2 of 2
    original = report_bytes(workdir, second)
    assert b"as of this run. This run is run 2, a repeat of variant 1." in original["report.md"]
    assert b"1 distinct variant in 2 runs as of this run" in original["report.md"]
    run_json = (workdir / "runs" / second / "run.json").read_bytes()
    index = (workdir / "runs" / "index.sqlite").read_bytes()
    shutil.rmtree(workdir / "reports" / second)

    result = run_cli(["report", second], provider=provider(), clock=at(99))

    assert result.code == 0
    assert result.err == ""
    assert result.out.splitlines() == [
        f"Run:        {second}",
        "Checked:    spec, evaluation, trades and costs equal the journal record",
        f"Journal:    runs/{second}/run.json (unchanged)",
        f"Report:     reports/{second}/report.md and report.html",
    ]
    assert report_bytes(workdir, second) == original
    assert (workdir / "runs" / second / "run.json").read_bytes() == run_json
    assert (workdir / "runs" / "index.sqlite").read_bytes() == index
    assert len(list((workdir / "runs").iterdir())) == 4  # three run folders and the index: nothing was logged


def test_the_first_run_of_a_run_without_report_gets_the_report_a_normal_run_writes(workdir: Path) -> None:
    run_id = logged_run("--no-report")
    assert not (workdir / "reports").exists()
    result = run_cli(["report", run_id], provider=provider())
    assert result.code == 0
    other = workdir / "other"
    other.mkdir()
    shutil.copy(workdir / "spec.yaml", other / "spec.yaml")
    import os

    os.chdir(other)
    again = run_cli(["run", "spec.yaml"], provider=provider(), clock=at(0))
    assert run_id_of(again.out) == run_id
    assert report_bytes(workdir, run_id) == report_bytes(other, run_id)


def test_the_options_of_the_folders(workdir: Path) -> None:
    run_id = logged_run("--runs-dir", "journal")
    seen = []

    def factory(cache_dir):
        seen.append(cache_dir)
        return provider()

    code = main(
        ["report", run_id, "--runs-dir", "journal", "--reports-dir", "out", "--cache-dir", "my-cache"],
        provider_factory=factory,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert code == 0
    assert seen == [Path("my-cache")]
    assert (workdir / "out" / run_id / "report.md").is_file()


def test_other_prices_are_exit_7_data_changed_and_nothing_is_written(workdir: Path) -> None:
    run_id = logged_run()
    shutil.rmtree(workdir / "reports")
    result = run_cli(["report", run_id], provider=changed_provider())
    assert result.code == 7
    assert result.out == ""
    lines = result.err.splitlines()
    assert re.fullmatch(rf"bt: error: run {run_id} no longer reproduces: data changed \(\d+ differences\)", lines[0])
    new_hash = re.fullmatch(
        rf"  evaluation\.strategy\.data_hash: stored {HASH_A}, now ({HASH_A_LAST_CLOSE_150})", lines[1]
    )
    assert new_hash
    assert len(lines) == 1 + 5 + 1 + 1  # five paths, "... and N more", the hint
    assert re.fullmatch(r"  \.\.\. and \d+ more", lines[6])
    assert lines[7] == (
        "hint: the stored run is untouched; use the cache the run was made with (--cache-dir) "
        "or log a new run with bt run"
    )
    assert not (workdir / "reports").exists()


def test_the_benchmark_hash_comes_before_the_strategy_hash_when_both_changed(workdir: Path) -> None:
    run_id = logged_run("--no-report")
    other = price_frame({"A": A_OPEN, "B": B_OPEN}, {"A": [*A_CLOSE[:-1], 150], "B": [*B_CLOSE[:-1], 40]})
    lines = run_cli(["report", run_id], provider=LiteralProvider(other)).err.splitlines()
    assert lines[1].startswith("  evaluation.benchmark.data_hash: stored ")
    assert lines[2].startswith(f"  evaluation.strategy.data_hash: stored {HASH_A}, now ")


def test_an_edited_metric_is_exit_7_metrics_changed(workdir: Path) -> None:
    run_id = logged_run()
    shutil.rmtree(workdir / "reports")
    edit_run_json(workdir, run_id, lambda d: d["evaluation"]["strategy"]["metrics"].update(total_return=0.5))
    result = run_cli(["report", run_id], provider=provider())
    assert result.code == 7
    lines = result.err.splitlines()
    assert lines[0] == f"bt: error: run {run_id} no longer reproduces: metrics changed (1 difference)"
    stored, now = re.fullmatch(
        r"  evaluation\.strategy\.metrics\.total_return: stored (.+), now (.+)", lines[1]
    ).groups()
    assert stored == "0.5"
    assert float(now) == pytest.approx(0.17128, abs=1e-12)  # R3b: 1171.28 / 1000 - 1
    assert lines[2] == (
        "hint: the stored run is untouched; the metric code or the stored values changed; log a new run with bt run"
    )
    assert len(lines) == 3
    assert not (workdir / "reports").exists()


def test_a_difference_in_trades_or_costs_is_metrics_changed_and_all_are_listed(workdir: Path) -> None:
    run_id = logged_run("--no-report")

    def edit(data: dict) -> None:
        data["costs"]["strategy"]["total_costs"] = 1.0
        data["costs"]["benchmark"]["cost_share"] = 0.5
        data["evaluation"]["extra_key"] = None

    edit_run_json(workdir, run_id, edit)
    lines = run_cli(["report", run_id], provider=provider()).err.splitlines()
    assert lines[0].endswith("metrics changed (3 differences)")
    assert [line.split(":")[0].strip() for line in lines[1:4]] == [
        "evaluation.extra_key",
        "costs.benchmark.cost_share",
        "costs.strategy.total_costs",
    ]
    assert lines[1] == "  evaluation.extra_key: stored null, now (missing)"
    assert lines[2].startswith("  costs.benchmark.cost_share: stored 0.5, now ")
    assert lines[3] == "  costs.strategy.total_costs: stored 1.0, now 200.0"  # R3b: one buy with a fee of 200


def test_a_removed_assumption_key_is_a_difference_not_a_crash(workdir: Path) -> None:
    run_id = logged_run("--no-report")
    edit_run_json(workdir, run_id, lambda d: d["evaluation"]["assumptions"].pop("periods_per_year"))
    result = run_cli(["report", run_id], provider=provider())
    assert result.code == 7
    assert result.err.splitlines()[1].startswith("  evaluation.assumptions.periods_per_year: stored (missing), now 252")


def test_an_existing_report_folder_is_exit_5_before_any_fetch(workdir: Path) -> None:
    run_id = logged_run()
    before = report_bytes(workdir, run_id)
    result = run_cli(["report", run_id])  # the default provider raises AssertionError if it is reached
    assert result.code == 5
    assert result.out == ""
    assert result.err == (
        f"bt: error: report folder already exists: reports/{run_id}\n"
        "hint: pass --overwrite to replace the files in it, or choose another --reports-dir\n"
    )
    assert report_bytes(workdir, run_id) == before


def test_overwrite_replaces_the_files_and_keeps_the_rest_of_the_folder(workdir: Path) -> None:
    run_id = logged_run()
    folder = workdir / "reports" / run_id
    original = report_bytes(workdir, run_id)
    (folder / "report.md").write_text("tampered", encoding="utf-8")
    (folder / "notes.txt").write_text("mine", encoding="utf-8")
    result = run_cli(["report", run_id, "--overwrite"], provider=provider())
    assert result.code == 0
    assert report_bytes(workdir, run_id) == original
    assert (folder / "notes.txt").read_text(encoding="utf-8") == "mine"


def test_a_race_for_the_report_folder_is_the_same_error(workdir: Path, monkeypatch) -> None:
    run_id = logged_run()
    shutil.rmtree(workdir / "reports")

    def raced(*args, **kwargs):
        raise FileExistsError("appeared meanwhile")

    monkeypatch.setattr("backtest_agent.cli.commands.write_report", raced)
    result = run_cli(["report", run_id], provider=provider())
    assert result.code == 5
    assert result.err.startswith(f"bt: error: report folder already exists: reports/{run_id}\nhint: pass --overwrite")


def test_an_unknown_run_is_exit_5(workdir: Path) -> None:
    result = run_cli(["report", "20260115T103005Z-nothing-00000000"])
    assert result.code == 5
    assert result.err.startswith("bt: error: no run '20260115T103005Z-nothing-00000000' in runs\n")


def test_an_unsafe_run_id_is_a_usage_error(workdir: Path) -> None:
    assert run_cli(["report", "../x"]).code == 2


def test_a_run_without_costs_is_reproduced_with_costs_off(workdir: Path) -> None:
    run_id = logged_run("--no-costs")
    original = report_bytes(workdir, run_id)
    costed = logged_run(seconds=1)
    assert report_bytes(workdir, costed)["report.md"] != original["report.md"]  # the costs make a difference here
    shutil.rmtree(workdir / "reports" / run_id)
    result = run_cli(["report", run_id], provider=provider())
    assert result.code == 0, result.err
    assert report_bytes(workdir, run_id) == original


def test_a_run_made_with_other_metric_assumptions_is_reproduced_with_them(workdir: Path) -> None:
    # the command line only runs with the defaults, the library can do more: 5 bars a year instead of 252
    made = experiment.run_experiment(
        spec_for(), provider(), runs_dir=workdir / "runs", generated_at=at(0)(), assumptions=P5
    )
    run_id = made.record.run_id
    assert made.record.evaluation["assumptions"] == {"periods_per_year": 5, "risk_free_rate": 0.0}
    result = run_cli(["report", run_id], provider=provider())
    assert result.code == 0, result.err
    assert (workdir / "reports" / run_id / "report.md").is_file()


def test_a_failed_report_after_logging_is_written_by_bt_report(workdir: Path, monkeypatch) -> None:
    real = experiment.write_report
    failing = [True]

    def flaky(*args, **kwargs):
        if failing[0]:
            raise OSError("disk full")
        return real(*args, **kwargs)

    monkeypatch.setattr("backtest_agent.experiment.write_report", flaky)
    failed = run_cli(["run", "spec.yaml"], provider=provider(), clock=at(0))
    assert failed.code == 6
    run_id = run_id_of(failed.err)
    assert f"bt report {run_id} writes the report again" in failed.err
    failing[0] = False
    result = run_cli(["report", run_id], provider=provider())
    assert result.code == 0, result.err
    assert (workdir / "reports" / run_id / "report.md").is_file()
    assert len(list((workdir / "runs").iterdir())) == 2  # the run folder and the index: nothing was logged twice


def test_a_spec_that_no_longer_validates_is_exit_3(workdir: Path) -> None:
    run_id = logged_run()

    def edit(data: dict) -> None:
        data["spec"]["sizing"]["method"] = "no_such_method"
        data["trial"]["variant_hash"] = variant_hash_of_dict(data["spec"])

    edit_run_json(workdir, run_id, edit)
    shutil.rmtree(workdir / "reports")
    result = run_cli(["report", run_id])
    assert result.code == 3
    lines = result.err.splitlines()
    assert lines[0] == f"bt: error: the stored spec of run {run_id} no longer validates (1 problem):"
    assert lines[1].startswith("  - sizing.method: ")
    assert lines[2].startswith("hint: the run folder is untouched; the spec schema or a signal changed since the run")
    assert not (workdir / "reports").exists()


def test_a_signal_that_is_gone_is_exit_3(workdir: Path) -> None:
    run_id = logged_run("--no-report")

    def edit(data: dict) -> None:
        data["spec"]["signal"]["id"] = "no_such_signal"
        data["family"] = "no_such_signal"
        data["trial"]["variant_hash"] = variant_hash_of_dict(data["spec"])

    edit_run_json(workdir, run_id, edit)
    result = run_cli(["report", run_id])
    assert result.code == 3
    assert result.err.splitlines()[0].startswith(f"bt: error: the stored spec of run {run_id} no longer validates")


def test_unequal_stored_costs_applied_are_a_journal_error_exit_5(workdir: Path) -> None:
    run_id = logged_run("--no-report")
    edit_run_json(workdir, run_id, lambda d: d["evaluation"]["benchmark"].update(costs_applied=False))
    result = run_cli(["report", run_id])
    assert result.code == 5
    assert result.err.splitlines()[0] == (
        f"bt: error: run {run_id}: the stored costs_applied differ (strategy true, benchmark false), "
        "so the run cannot be reproduced"
    )


@pytest.mark.parametrize("bad", [{"periods_per_year": 252, "risk_free_rate": 0.0, "extra": 1}, {"periods_per_year": 0}])
def test_unreadable_stored_assumptions_are_a_journal_error_exit_5(workdir: Path, bad: dict) -> None:
    run_id = logged_run("--no-report")
    edit_run_json(workdir, run_id, lambda d: d["evaluation"].update(assumptions=bad))
    result = run_cli(["report", run_id])
    assert result.code == 5
    assert result.err.startswith(f"bt: error: run {run_id}: the stored metric assumptions cannot be read (")


def test_a_costs_applied_that_is_not_a_bool_is_exit_5(workdir: Path) -> None:
    run_id = logged_run("--no-report")

    def edit(data: dict) -> None:
        data["evaluation"]["strategy"]["costs_applied"] = 1
        data["evaluation"]["benchmark"]["costs_applied"] = 1

    edit_run_json(workdir, run_id, edit)
    assert run_cli(["report", run_id]).code == 5


class FailingProvider(LiteralProvider):
    def get_prices(self, symbols, start, end):
        raise DataUnavailableError("the cache is empty and the network is down")


def test_an_empty_cache_and_no_network_is_exit_4_and_nothing_is_written(workdir: Path) -> None:
    run_id = logged_run()
    shutil.rmtree(workdir / "reports")
    result = run_cli(["report", run_id], provider=FailingProvider(world()))
    assert result.code == 4
    assert result.out == ""
    assert result.err.startswith("bt: error: the cache is empty and the network is down\nhint: ")
    assert not (workdir / "reports").exists()


def test_the_help_names_the_options() -> None:
    result = run_cli(["report", "--help"])
    assert result.code == 0
    assert result.out.startswith("usage: bt report ")
    for option in ("RUN_ID", "--runs-dir DIR", "--reports-dir DIR", "--cache-dir DIR", "--overwrite", "--debug"):
        assert option in result.out


def test_the_top_level_help_lists_report() -> None:
    assert "\n    report " in run_cli(["--help"]).out
