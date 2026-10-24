"""``bt journal list``, ``show`` and ``rebuild``: literal output, filters, and the journal errors (exit 5)."""

import io
import re
import shutil
from pathlib import Path

import pytest

from backtest_agent.cli import main
from cli_helpers import at, run_cli, write_spec
from report_helpers import spec_for, world
from runner_helpers import LiteralProvider

RUN_ID = re.compile(r"20260115T1030\d\dZ-[a-z0-9-]+-[0-9a-f]{8}")
HEADER = "RUN ID                                    FAMILY        RUN  VARIANT  NEW  NAME"


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def provider() -> LiteralProvider:
    return LiteralProvider(world())


def log_run(spec_file: str, second: int, *extra: str) -> str:
    """Run ``bt run`` at ``second`` and return the run id."""
    result = run_cli(["run", spec_file, *extra], provider=provider(), clock=at(second))
    assert result.code == 0, result.err
    match = RUN_ID.search(result.out)
    assert match
    return match.group(0)


@pytest.fixture
def three_runs(workdir: Path) -> list[str]:
    """Run 1 (new variant), run 2 (a repeat), run 3 (twice the capital: a new variant), one second apart."""
    write_spec(workdir, spec_for(), "spec.yaml")
    write_spec(workdir, spec_for().model_copy(update={"initial_capital": 2000.0}), "larger.yaml")
    return [log_run("spec.yaml", 0), log_run("spec.yaml", 1), log_run("larger.yaml", 2)]


def test_list_prints_the_runs_newest_first(three_runs: list[str]) -> None:
    first, second, third = three_runs
    result = run_cli(["journal", "list"])
    assert result.code == 0
    assert result.err == ""
    assert result.out.splitlines() == [
        HEADER,
        f"{third}  buy_and_hold  3    2        yes  Buy and hold A",
        f"{second}  buy_and_hold  2    1        no   Buy and hold A",
        f"{first}  buy_and_hold  1    1        yes  Buy and hold A",
        "",
        "3 runs listed",
    ]


def test_list_filters_by_family_and_limits(workdir: Path, three_runs: list[str]) -> None:
    sma = spec_for(signal="sma_crossover", params={"fast": 2, "slow": 3}, name="SMA A")
    write_spec(workdir, sma, "sma.yaml")
    sma_id = log_run("sma.yaml", 3)
    only_sma = run_cli(["journal", "list", "--family", "sma_crossover"])
    assert only_sma.out.splitlines()[1:] == [f"{sma_id}  sma_crossover  1    1        yes  SMA A", "", "1 run listed"]
    limited = run_cli(["journal", "list", "--limit", "2"])
    rows = [row.split() for row in limited.out.splitlines()[1:3]]
    assert rows == [
        [sma_id, "sma_crossover", "1", "1", "yes", "SMA", "A"],
        [three_runs[2], "buy_and_hold", "3", "2", "yes", "Buy", "and", "hold", "A"],
    ]
    assert limited.out.splitlines()[-1] == "2 runs listed"
    none = run_cli(["journal", "list", "--family", "nope"])
    assert (none.code, none.out) == (0, "No runs of family nope in runs.\n")


def test_list_of_an_empty_journal_is_not_an_error(workdir: Path) -> None:
    result = run_cli(["journal", "list"])
    assert (result.code, result.out, result.err) == (0, "No runs in runs.\n", "")


def test_list_uses_the_runs_dir_it_is_given(workdir: Path) -> None:
    write_spec(workdir, spec_for(), "spec.yaml")
    run_id = log_run("spec.yaml", 0, "--runs-dir", "elsewhere", "--no-report")
    assert run_id in run_cli(["journal", "list", "--runs-dir", "elsewhere"]).out
    assert run_cli(["journal", "list"]).out == "No runs in runs.\n"


def test_list_cuts_a_long_name_and_survives_a_non_ascii_one(workdir: Path) -> None:
    name = "Café 中文 " + "x" * 50
    write_spec(workdir, spec_for(name=name), "spec.yaml")
    log_run("spec.yaml", 0)
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="cp1252", errors="strict", newline="\n")
    assert main(["journal", "list"], stdout=out) == 0
    out.flush()
    row = raw.getvalue().decode("cp1252").splitlines()[1]
    assert row.endswith("Café \\u4e2d\\u6587 " + "x" * 29 + "...")


def test_show_prints_the_run_block_and_the_stored_facts(workdir: Path, three_runs: list[str]) -> None:
    run_id = three_runs[0]
    result = run_cli(["journal", "show", run_id])
    assert result.code == 0
    assert result.err == ""
    lines = result.out.splitlines()
    assert lines[:15] == [
        f"Run:        {run_id}",
        "Strategy:   Buy and hold A (family buy_and_hold)",
        "Trials:     family buy_and_hold: 1 distinct variant in 1 run as of this run. This run is run 1, a new "
        "variant (variant 1). Counts cover only runs logged in this journal.",
        "Period:     2024-01-02 to 2024-01-08, 5 bars",
        "Costs:      applied",
        "",
        "Metric               Strategy  Benchmark (B)",
        "Total return           17.13%        -21.59%",
        "CAGR              288,635.82%       -100.00%",
        "Sharpe ratio             5.87          -7.50",
        "Maximum drawdown      -12.00%        -21.59%",
        "",
        "Excess return (compared window): +38.72%",
        "",
        "Risk flags: none",
    ]
    assert lines[15] == "Generated:  2026-01-15 10:30:05 UTC"
    assert re.fullmatch(
        r"Code:       [0-9a-f]{12} \((clean|has uncommitted changes|state unknown)\)|"
        r"Code:       unknown \(state unknown\)",
        lines[16],
    )
    assert re.fullmatch(r"Data:       strategy [0-9a-f]{64}", lines[17])
    assert re.fullmatch(r"            benchmark [0-9a-f]{64}", lines[18])
    assert lines[19:] == [
        f"Spec:       runs/{run_id}/spec.yaml",
        f"Journal:    runs/{run_id}/run.json",
        f"Report:     reports/{run_id}/report.md and report.html",
    ]


def test_show_and_run_print_the_same_block(workdir: Path) -> None:
    write_spec(workdir, spec_for(), "spec.yaml")
    ran = run_cli(["run", "spec.yaml"], provider=provider(), clock=at(0))
    run_id = RUN_ID.search(ran.out).group(0)
    shown = run_cli(["journal", "show", run_id])
    assert shown.out.splitlines()[:15] == ran.out.splitlines()[:15]


def test_show_without_a_report_folder_has_no_report_line(workdir: Path) -> None:
    write_spec(workdir, spec_for(), "spec.yaml")
    run_id = log_run("spec.yaml", 0, "--no-report")
    shown = run_cli(["journal", "show", run_id])
    assert shown.code == 0
    assert not any(line.startswith("Report:") for line in shown.out.splitlines())
    assert f"Journal:    runs/{run_id}/run.json" in shown.out.splitlines()


def test_show_shows_a_run_made_without_costs(workdir: Path) -> None:
    write_spec(workdir, spec_for(), "spec.yaml")
    run_id = log_run("spec.yaml", 0, "--no-costs")
    lines = run_cli(["journal", "show", run_id]).out.splitlines()
    assert "Costs:      NOT applied (the result overstates what trading would return)" in lines
    assert "Risk flags: strategy run: costs_not_applied; benchmark run: costs_not_applied" in lines


def test_show_an_unknown_run_is_exit_5(workdir: Path, three_runs: list[str]) -> None:
    result = run_cli(["journal", "show", "20990101T000000Z-nothing-00000000"])
    assert result.code == 5
    assert result.out == ""
    assert result.err.splitlines() == [
        "bt: error: no run '20990101T000000Z-nothing-00000000' in runs",
        "hint: bt journal list --runs-dir runs shows the runs of this journal",
    ]


def test_show_a_damaged_run_json_is_exit_5(workdir: Path, three_runs: list[str]) -> None:
    (workdir / "runs" / three_runs[0] / "run.json").write_text("{not json", encoding="utf-8")
    result = run_cli(["journal", "show", three_runs[0]])
    assert result.code == 5
    assert "cannot be read as JSON" in result.err.splitlines()[0]


@pytest.mark.parametrize("bad", ["../x", "..", "a/b", "C:evil", "CON"])
def test_show_an_unsafe_run_id_is_a_usage_error(bad: str) -> None:
    result = run_cli(["journal", "show", bad])
    assert result.code == 2
    assert "is not a safe run id" in result.err


@pytest.mark.parametrize("limit", ["0", "-1", "abc"])
def test_list_limit_must_be_a_whole_number_of_1_or_more(limit: str) -> None:
    result = run_cli(["journal", "list", "--limit", limit])
    assert result.code == 2
    assert "--limit" in result.err


def test_a_stale_index_is_exit_5_for_list_and_rebuild_repairs_it(workdir: Path, three_runs: list[str]) -> None:
    shutil.rmtree(workdir / "runs" / three_runs[2])
    stale = run_cli(["journal", "list"])
    assert stale.code == 5
    assert stale.out == ""
    assert stale.err.splitlines()[1] == (
        'hint: run "bt journal rebuild --runs-dir runs" (a run folder that was deleted is forgotten by the rebuild)'
    )
    rebuilt = run_cli(["journal", "rebuild"])
    assert rebuilt.code == 0
    assert rebuilt.out.splitlines() == ["Rebuilt the index in runs: 2 runs found.", "The old index had 3 rows."]
    assert rebuilt.err == (
        "warning: the new index has 2 runs, the old one had 3: the 1 missing run is forgotten and no longer counts "
        "as a trial\n"
    )
    listed = run_cli(["journal", "list"])
    assert listed.code == 0
    assert listed.out.splitlines()[-1] == "2 runs listed"


def test_rebuild_refuses_a_journal_with_a_gap_in_the_run_numbers(workdir: Path, three_runs: list[str]) -> None:
    shutil.rmtree(workdir / "runs" / three_runs[1])
    result = run_cli(["journal", "rebuild"])
    assert result.code == 5
    assert result.out == ""
    assert "the run numbers must be 1 to 2 without gaps or repeats, got [1, 3]" in result.err


def test_rebuild_after_the_loss_of_the_index_forgets_nothing(workdir: Path, three_runs: list[str]) -> None:
    (workdir / "runs" / "index.sqlite").unlink()
    assert run_cli(["journal", "list"]).code == 5
    rebuilt = run_cli(["journal", "rebuild"])
    assert (rebuilt.code, rebuilt.err) == (0, "")
    assert rebuilt.out == "Rebuilt the index in runs: 3 runs found.\n"
    assert run_cli(["journal", "list"]).out.splitlines()[-1] == "3 runs listed"


def test_rebuild_of_a_healthy_journal_changes_nothing(three_runs: list[str]) -> None:
    before = run_cli(["journal", "list"]).out
    rebuilt = run_cli(["journal", "rebuild"])
    assert rebuilt.out.splitlines() == ["Rebuilt the index in runs: 3 runs found.", "The old index had 3 rows."]
    assert rebuilt.err == ""
    assert run_cli(["journal", "list"]).out == before


def test_rebuild_with_an_unreadable_run_folder_is_exit_5_and_keeps_the_old_index(
    workdir: Path, three_runs: list[str]
) -> None:
    (workdir / "runs" / three_runs[2] / "run.json").write_text("[]", encoding="utf-8")
    result = run_cli(["journal", "rebuild"])
    assert result.code == 5
    assert result.out == ""
    assert "cannot rebuild the index, unreadable run folders" in result.err
    assert (workdir / "runs" / "index.sqlite").is_file()


def test_rebuild_of_a_missing_folder_finds_no_runs(workdir: Path) -> None:
    result = run_cli(["journal", "rebuild"])
    assert (result.code, result.out, result.err) == (0, "Rebuilt the index in runs: 0 runs found.\n", "")
