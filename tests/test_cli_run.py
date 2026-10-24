"""``bt run``: the standard run through ``run_experiment``, its output and every exit code it can end with.

The expected lines are the literals of docs/cli.md (the world of fixture R3b in docs/metrics.md, the counters of
docs/journal.md); the 8 hex characters of a run id are a hash and are only matched by pattern.
"""

import io
import re
import shutil
import sqlite3
from pathlib import Path

import pytest

from backtest_agent.cli import main
from backtest_agent.data import DataUnavailableError, FakeProvider
from backtest_agent.journal import index
from backtest_agent.spec import SIGNALS, Signal
from cli_helpers import at, run_cli, write_spec
from report_helpers import spec_for, world
from runner_helpers import LiteralProvider, UpDayParams, make_spec, price_frame

RUN_ID = re.compile(r"20260115T1030(?P<second>\d\d)Z-buy-and-hold-a-(?P<hash>[0-9a-f]{8})")


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch) -> Path:
    """An empty working directory: the default folders (runs, reports, data/cache) are relative to it."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def spec_path(workdir: Path) -> Path:
    return write_spec(workdir, spec_for())


def provider() -> LiteralProvider:
    return LiteralProvider(world())


def run_id_of(out: str) -> str:
    match = RUN_ID.search(out)
    assert match, out
    return match.group(0)


def expected_summary(run_id: str, trials: str) -> list[str]:
    return [
        f"Run:        {run_id}",
        "Strategy:   Buy and hold A (family buy_and_hold)",
        f"Trials:     {trials}",
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
        f"Journal:    runs/{run_id}/run.json",
        f"Report:     reports/{run_id}/report.md and report.html",
    ]


FIRST = (
    "family buy_and_hold: 1 distinct variant in 1 run as of this run. This run is run 1, a new variant (variant 1). "
    "Counts cover only runs logged in this journal."
)
REPEAT = (
    "family buy_and_hold: 1 distinct variant in 2 runs as of this run. This run is run 2, a repeat of variant 1. "
    "Counts cover only runs logged in this journal."
)
NEW_VARIANT = (
    "family buy_and_hold: 2 distinct variants in 3 runs as of this run. This run is run 3, a new variant (variant 2). "
    "Counts cover only runs logged in this journal."
)


def test_run_prints_the_literal_summary_and_writes_journal_and_report(spec_path: Path, workdir: Path) -> None:
    result = run_cli(["run", "spec.yaml"], provider=provider(), clock=at(0))
    assert result.code == 0
    assert result.err == ""
    run_id = run_id_of(result.out)
    assert run_id.startswith("20260115T103005Z-buy-and-hold-a-")
    assert result.out.splitlines() == expected_summary(run_id, FIRST)
    assert (workdir / "runs" / run_id / "run.json").is_file()
    assert (workdir / "runs" / "index.sqlite").is_file()
    for name in ("report.md", "report.html", "equity.svg", "drawdown.svg"):
        assert (workdir / "reports" / run_id / name).is_file()
    assert f"- **Trials:** {FIRST}" in (workdir / "reports" / run_id / "report.md").read_text(encoding="utf-8")


def test_run_uses_the_folders_it_is_given(spec_path: Path, workdir: Path) -> None:
    result = run_cli(
        ["run", "spec.yaml", "--runs-dir", "journal", "--reports-dir", "out/reports", "--cache-dir", "cache"],
        provider=provider(),
    )
    assert result.code == 0
    run_id = run_id_of(result.out)
    assert f"Journal:    journal/{run_id}/run.json" in result.out.splitlines()
    assert f"Report:     out/reports/{run_id}/report.md and report.html" in result.out.splitlines()
    assert (workdir / "journal" / run_id / "run.json").is_file()
    assert (workdir / "out" / "reports" / run_id / "report.html").is_file()
    assert not (workdir / "runs").exists()


def test_the_cache_dir_goes_to_the_provider_factory(spec_path: Path) -> None:
    seen = []

    def factory(cache_dir):
        seen.append(cache_dir)
        return provider()

    assert main(["run", "spec.yaml", "--cache-dir", "my-cache"], provider_factory=factory, stdout=io.StringIO()) == 0
    assert seen == [Path("my-cache")]


def test_no_report_logs_the_run_and_writes_no_report(spec_path: Path, workdir: Path) -> None:
    result = run_cli(["run", "spec.yaml", "--no-report"], provider=provider(), clock=at(0))
    assert result.code == 0
    run_id = run_id_of(result.out)
    assert result.out.splitlines() == expected_summary(run_id, FIRST)[:-1]
    assert (workdir / "runs" / run_id / "run.json").is_file()
    assert not (workdir / "reports").exists()


def test_running_twice_in_the_same_second_is_refused_and_logs_nothing_twice(spec_path: Path, workdir: Path) -> None:
    first = run_cli(["run", "spec.yaml"], provider=provider(), clock=at(0))
    run_id = run_id_of(first.out)
    again = run_cli(["run", "spec.yaml"], provider=provider(), clock=at(0))
    assert again.code == 5
    assert again.out == ""
    assert again.err.splitlines() == [
        f"bt: error: run id already exists; use a later generated_at: {run_id}",
        "hint: wait one second and run again (the run id has a resolution of one second)",
    ]
    assert sorted(p.name for p in (workdir / "runs").iterdir() if p.is_dir()) == [run_id]
    assert len(list((workdir / "reports").iterdir())) == 1


def test_later_runs_raise_the_counters_as_in_the_journal_doc(spec_path: Path, workdir: Path) -> None:
    run_cli(["run", "spec.yaml"], provider=provider(), clock=at(0))
    repeat = run_cli(["run", "spec.yaml"], provider=provider(), clock=at(1))
    assert repeat.code == 0
    assert f"Trials:     {REPEAT}" in repeat.out.splitlines()
    larger = write_spec(workdir, spec_for().model_copy(update={"initial_capital": 2000.0}), "larger.yaml")
    new = run_cli(["run", str(larger)], provider=provider(), clock=at(2))
    assert new.code == 0
    assert f"Trials:     {NEW_VARIANT}" in new.out.splitlines()


def test_no_costs_is_visible_in_the_output_and_in_the_journal(spec_path: Path, workdir: Path) -> None:
    result = run_cli(["run", "spec.yaml", "--no-costs"], provider=provider(), clock=at(0))
    assert result.code == 0
    lines = result.out.splitlines()
    assert "Costs:      NOT applied (the result overstates what trading would return)" in lines
    assert "Risk flags: strategy run: costs_not_applied; benchmark run: costs_not_applied" in lines
    rows = {tuple(line.split())[:2]: line.split() for line in lines if line.startswith(("Total", "Maximum"))}
    assert rows[("Total", "return")][2:] == ["46.41%", "-1.99%"]
    assert "Excess return (compared window): +48.40%" in lines
    run_json = next((workdir / "runs").glob("*/run.json")).read_text(encoding="utf-8")
    assert '"costs_applied":false' in run_json
    assert '"costs_applied":true' not in run_json


def test_a_short_history_is_reported_as_a_warning_without_a_path(workdir: Path) -> None:
    spec = make_spec(universe=("AAA", "BBB"), start="2015-01-05", end="2015-03-31", benchmark="AAA")
    path = write_spec(workdir, spec)
    result = run_cli(["run", str(path)], provider=FakeProvider(symbols=("AAA", "BBB")), clock=at(0))
    assert result.code == 0
    assert result.err.startswith("warning: ['AAA', 'BBB'] have fewer than 19 rows before the first decision on ")
    assert result.err.count("warning:") == 1
    assert ".py" not in result.err
    assert "Risk flags: strategy run: insufficient_warmup" in result.out.splitlines()


def test_a_spec_that_cannot_be_loaded_is_exit_3_and_creates_nothing(workdir: Path) -> None:
    result = run_cli(["run", "missing.yaml"], provider=provider())
    assert result.code == 3
    assert result.out == ""
    assert "cannot read missing.yaml" in result.err
    assert list(workdir.iterdir()) == []


def test_exit_4_when_the_provider_has_no_data(spec_path: Path, workdir: Path) -> None:
    class NoData(LiteralProvider):
        def get_prices(self, symbols, start, end):
            raise DataUnavailableError("yfinance returned no data for ['A']")

    result = run_cli(["run", "spec.yaml"], provider=NoData(world()))
    assert result.code == 4
    assert result.out == ""
    assert result.err.splitlines()[0] == "bt: error: yfinance returned no data for ['A']"
    assert result.err.splitlines()[1].startswith("hint: check the symbols, the dates and your connection")
    assert not (workdir / "runs").exists()


def test_exit_4_when_the_network_is_down(spec_path: Path, workdir: Path) -> None:
    class Offline(LiteralProvider):
        def get_prices(self, symbols, start, end):
            raise ConnectionError("Failed to resolve query1.finance.yahoo.com")

    result = run_cli(["run", "spec.yaml"], provider=Offline(world()))
    assert result.code == 4
    assert result.err.splitlines()[0] == (
        "bt: error: the data provider failed (ConnectionError: Failed to resolve query1.finance.yahoo.com)"
    )
    assert not (workdir / "runs").exists()


def test_exit_4_when_the_data_has_a_validation_error(spec_path: Path, workdir: Path) -> None:
    closes = {"A": [100, 110, 0.0, 133.1, 146.41], "B": [50, 55, 49.5, 54.45, 49.005]}
    opens = {"A": [100, 100, 110, 121, 133.1], "B": [50, 50, 55, 49.5, 54.45]}
    result = run_cli(["run", "spec.yaml"], provider=LiteralProvider(price_frame(opens, closes)))
    assert result.code == 4
    assert result.out == ""
    lines = result.err.splitlines()
    issues = [line for line in lines if line.startswith("  - [non_positive_price] A:")]
    assert issues  # the code is documented in docs/data.md; the wording of the message is not asserted
    assert lines[0] == f"bt: error: data validation failed with {len(issues)} error(s):"
    assert len(lines) == len(issues) + 2
    assert lines[-1].startswith("hint: check the symbols")
    assert not (workdir / "runs").exists()


def test_exit_5_when_the_index_is_stale(spec_path: Path, workdir: Path) -> None:
    first = run_cli(["run", "spec.yaml"], provider=provider(), clock=at(0))
    shutil.copytree(workdir / "runs" / run_id_of(first.out), workdir / "runs" / "copied-by-hand")
    result = run_cli(["run", "spec.yaml"], provider=provider(), clock=at(5))
    assert result.code == 5
    assert result.out == ""
    lines = result.err.splitlines()
    assert lines[0].startswith("bt: error: the journal in runs and its index disagree")
    assert lines[1] == (
        'hint: run "bt journal rebuild --runs-dir runs" (a run folder that was deleted is forgotten by the rebuild)'
    )
    assert len(list((workdir / "reports").iterdir())) == 1


def test_exit_5_when_the_index_is_busy(spec_path: Path, workdir: Path, monkeypatch) -> None:
    run_cli(["run", "spec.yaml"], provider=provider(), clock=at(0))
    original = index.connect
    monkeypatch.setattr(index, "connect", lambda path, timeout: original(path, 0.05))
    holder = sqlite3.connect(str(workdir / "runs" / "index.sqlite"), isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        result = run_cli(["run", "spec.yaml"], provider=provider(), clock=at(5))
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert result.code == 5
    assert result.out == ""
    assert result.err.splitlines()[0].startswith("bt: error: the journal index is locked by another process")
    assert result.err.splitlines()[1] == "hint: another process is writing to the journal; try again in a moment"
    assert len(list((workdir / "reports").iterdir())) == 1


def test_exit_5_when_only_the_report_folder_exists(spec_path: Path, workdir: Path) -> None:
    first = run_cli(["run", "spec.yaml"], provider=provider(), clock=at(0))
    run_id = run_id_of(first.out)
    shutil.rmtree(workdir / "runs")
    result = run_cli(["run", "spec.yaml"], provider=provider(), clock=at(0))
    assert result.code == 5
    assert result.err.splitlines()[0].startswith("bt: error: report folder already exists: ")
    assert run_id in result.err.splitlines()[0]
    assert result.err.splitlines()[1].startswith("hint: remove that folder or choose another --reports-dir")
    assert not (workdir / "runs").exists()


def test_exit_6_when_the_report_fails_after_the_run_was_logged(spec_path: Path, workdir: Path, monkeypatch) -> None:
    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("backtest_agent.experiment.write_report", broken)
    result = run_cli(["run", "spec.yaml"], provider=provider(), clock=at(0))
    assert result.code == 6
    assert result.out == ""
    run_id = next(p.name for p in (workdir / "runs").iterdir() if p.is_dir())
    assert result.err.splitlines() == [
        f"bt: error: run {run_id} is logged but its report could not be written (OSError: disk full)",
        f"hint: bt report {run_id} writes the report again without logging the run twice",
    ]
    assert (workdir / "runs" / run_id / "run.json").is_file()
    assert not (workdir / "reports").exists()


def test_exit_1_when_a_signal_has_a_bug(workdir: Path, monkeypatch) -> None:
    def boom(prices, params):
        raise ZeroDivisionError("division by zero in the signal")

    monkeypatch.setitem(SIGNALS._signals, "fixture_boom", Signal("fixture_boom", UpDayParams, boom, "a buggy signal"))
    spec = spec_for(signal="fixture_boom")
    path = write_spec(workdir, spec)
    result = run_cli(["run", str(path)], provider=provider())
    assert result.code == 1
    assert result.out == ""
    assert result.err.splitlines()[0] == (
        "bt: error: unexpected error (ZeroDivisionError): division by zero in the signal"
    )
    assert "Traceback" not in result.err
    assert "Traceback" in run_cli(["run", str(path), "--debug"], provider=provider()).err


def test_exit_130_when_interrupted_and_nothing_is_logged(spec_path: Path, workdir: Path) -> None:
    class Interrupted(LiteralProvider):
        def get_prices(self, symbols, start, end):
            raise KeyboardInterrupt

    result = run_cli(["run", "spec.yaml"], provider=Interrupted(world()))
    assert (result.code, result.out, result.err) == (130, "", "bt: error: interrupted\n")
    assert not (workdir / "runs").exists()


def test_exit_2_for_a_missing_spec_argument_and_an_unknown_option() -> None:
    assert run_cli(["run"]).code == 2
    unknown = run_cli(["run", "spec.yaml", "--turbo"])
    assert unknown.code == 2
    assert "unrecognized arguments: --turbo" in unknown.err


def test_a_non_ascii_name_does_not_crash_a_cp1252_console(workdir: Path) -> None:
    spec = spec_for(name="Café 中文 A")
    path = write_spec(workdir, spec)
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="cp1252", errors="strict", newline="\n")
    code = main(["run", str(path)], provider_factory=lambda cache_dir: provider(), clock=at(0), stdout=out)
    out.flush()
    text = raw.getvalue().decode("cp1252")
    assert code == 0
    assert "Strategy:   Café \\u4e2d\\u6587 A (family buy_and_hold)" in text.splitlines()
    run_json = next((workdir / "runs").glob("*/run.json")).read_bytes().decode("utf-8")
    assert "Caf\\u00e9" in run_json
