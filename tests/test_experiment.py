"""run_experiment: evaluate, log, report (docs/journal.md, "run_experiment").

Expected numbers are the literals of the counter table in docs/journal.md and the trial lines of docs/report.md.
"""

import re
from pathlib import Path

import pytest

import backtest_agent.experiment as experiment
from backtest_agent.experiment import Experiment, ExperimentReportError, run_experiment
from backtest_agent.journal import JournalIndexStale, get_run, list_runs, run_count, trial_count
from backtest_agent.run_id import make_run_id
from html_helpers import parse, text_of
from journal_helpers import (
    CODE,
    at,
    hold_spec,
    no_repo_runs,  # noqa: F401 - fixture used through pytestmark
    other_data_provider,
    sma_spec,
    standard_provider,
)

pytestmark = [
    pytest.mark.usefixtures("no_repo_runs"),
    pytest.mark.filterwarnings("ignore::backtest_agent.engine.InsufficientWarmupWarning"),  # the world is 5 bars long
]

TAIL = "Counts cover only runs logged in this journal."


def go(tmp_path: Path, spec, second: int, *, reports: bool = False, provider=None, **kwargs) -> Experiment:
    return run_experiment(
        spec,
        provider if provider is not None else standard_provider(),
        runs_dir=tmp_path / "runs",
        generated_at=at(second),
        reports_dir=tmp_path / "reports" if reports else None,
        code_version=CODE,
        **kwargs,
    )


# --- one call, one run -----------------------------------------------------------------------------------------------


def test_one_call_logs_exactly_one_run_and_no_report_without_a_reports_dir(tmp_path: Path) -> None:
    result = go(tmp_path, sma_spec(), 1)
    assert result.report is None
    assert not (tmp_path / "reports").exists()
    assert [r.run_id for r in list_runs(tmp_path / "runs")] == [result.record.run_id]
    assert result.record.run_id == make_run_id(result.evaluation, at(1))
    assert result.record.run_id.startswith("20260115T103001Z-sma-a-")
    assert (tmp_path / "runs" / result.record.run_id / "run.json").is_file()


def test_the_report_gets_the_run_id_the_time_and_the_trial_of_the_journal(tmp_path: Path) -> None:
    result = go(tmp_path, sma_spec(), 1, reports=True)
    assert result.report is not None
    assert result.report.run_id == result.record.run_id
    assert result.report.directory == tmp_path / "reports" / result.record.run_id
    markdown = result.report.markdown.read_text(encoding="utf-8")
    assert f"- **Run id:** `{result.record.run_id}`" in markdown
    assert "- **Generated at:** 2026-01-15 10:30:01 UTC" in markdown
    assert (
        "- **Trials:** family sma_crossover: 1 distinct variant in 1 run as of this run. "
        f"This run is run 1, a new variant (variant 1). {TAIL}\n"
    ) in markdown
    assert len(list_runs(tmp_path / "runs")) == 1


# --- the counters of docs/journal.md ---------------------------------------------------------------------------------

# (step, spec, provider kwargs, run options, family, run_number, trial_number, trial_count, new_variant)
TABLE = [
    ("S1", sma_spec(), {}, {}, "sma_crossover", 1, 1, 1, True),
    ("S2", sma_spec(name="Renamed run", description="Changed text"), {}, {}, "sma_crossover", 2, 1, 1, False),
    ("S3", sma_spec(slow=4), {}, {}, "sma_crossover", 3, 2, 2, True),
    ("S4", sma_spec(start="2024-01-03"), {}, {}, "sma_crossover", 4, 3, 3, True),
    ("S5", hold_spec(), {}, {}, "buy_and_hold", 1, 1, 1, True),
    ("S6", sma_spec(), {}, {}, "sma_crossover", 5, 1, 3, False),
    ("S7", sma_spec(), {"other": True}, {}, "sma_crossover", 6, 1, 3, False),
    ("S8", sma_spec(), {}, {"apply_costs": False}, "sma_crossover", 7, 1, 3, False),
    ("S9", sma_spec(commission=900.0), {}, {}, "sma_crossover", 8, 4, 4, True),
]
AFTER = {  # step -> (F1 run_count, F1 trial_count, F2 run_count, F2 trial_count) after the step
    "S1": (1, 1, 0, 0),
    "S2": (2, 1, 0, 0),
    "S3": (3, 2, 0, 0),
    "S4": (4, 3, 0, 0),
    "S5": (4, 3, 1, 1),
    "S6": (5, 3, 1, 1),
    "S7": (6, 3, 1, 1),
    "S8": (7, 3, 1, 1),
    "S9": (8, 4, 1, 1),
}


def test_the_counters_rise_as_in_the_counter_table(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    for second, (step, spec, extra, options, family, run_n, trial_n, count, new) in enumerate(TABLE, start=1):
        provider = other_data_provider() if extra else None
        trial = go(tmp_path, spec, second, provider=provider, **options).record.trial
        assert (trial.family, trial.run_number, trial.trial_number, trial.trial_count, trial.new_variant) == (
            family,
            run_n,
            trial_n,
            count,
            new,
        ), step
        f1_runs, f1_trials, f2_runs, f2_trials = AFTER[step]
        assert (
            run_count(runs, "sma_crossover"),
            trial_count(runs, "sma_crossover"),
            run_count(runs, "buy_and_hold"),
            trial_count(runs, "buy_and_hold"),
        ) == (f1_runs, f1_trials, f2_runs, f2_trials), step


def test_options_reach_the_evaluation(tmp_path: Path) -> None:
    result = go(tmp_path, sma_spec(), 1, apply_costs=False)
    assert get_run(tmp_path / "runs", result.record.run_id).costs["strategy"]["costs_applied"] is False


# --- the same run id twice -------------------------------------------------------------------------------------------


def snapshot(base: Path) -> list[str]:
    return sorted(str(p.relative_to(base)) for p in base.rglob("*") if p.is_file() and p.suffix != ".sqlite-journal")


@pytest.mark.parametrize("reports", [False, True])
def test_the_same_second_twice_gives_the_clear_message_and_changes_nothing(tmp_path: Path, reports: bool) -> None:
    first = go(tmp_path, sma_spec(), 1, reports=reports)
    before = snapshot(tmp_path)
    with pytest.raises(FileExistsError, match="run id already exists; use a later generated_at") as caught:
        go(tmp_path, sma_spec(), 1, reports=reports)
    assert first.record.run_id in str(caught.value)
    assert snapshot(tmp_path) == before
    assert (run_count(tmp_path / "runs", "sma_crossover"), trial_count(tmp_path / "runs", "sma_crossover")) == (1, 1)
    if not reports:  # the original error stays the cause when record_run raised it
        assert isinstance(caught.value.__cause__, FileExistsError)


def test_only_a_report_folder_stops_before_logging(tmp_path: Path) -> None:
    probe = go(tmp_path / "probe", sma_spec(), 1)
    (tmp_path / "reports" / probe.record.run_id).mkdir(parents=True)
    with pytest.raises(FileExistsError, match="report folder already exists") as caught:
        go(tmp_path, sma_spec(), 1, reports=True)
    assert "nothing was logged" in str(caught.value)
    assert not (tmp_path / "runs").exists()


def test_only_the_run_id_error_is_reworded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def other(*args, **kwargs):
        raise FileExistsError("some other file exists")

    monkeypatch.setattr(experiment, "record_run", other)
    with pytest.raises(FileExistsError) as caught:
        go(tmp_path, sma_spec(), 1)
    assert str(caught.value) == "some other file exists"
    assert caught.value.__cause__ is None


# --- failures --------------------------------------------------------------------------------------------------------


def block_reports(tmp_path: Path) -> Path:
    """A plain file where the reports folder should be, so that writing a report fails."""
    blocker = tmp_path / "reports"
    blocker.write_text("not a folder", encoding="utf-8")
    return blocker


def test_a_failing_report_keeps_the_journal_entry_and_carries_what_retry_needs(tmp_path: Path) -> None:
    blocker = block_reports(tmp_path)
    with pytest.raises(ExperimentReportError) as caught:
        go(tmp_path, sma_spec(), 1, reports=True)
    error = caught.value
    assert isinstance(error.__cause__, OSError)
    assert str(error.record.run_id) in str(error) and "logged" in str(error)
    assert error.record.run_id == make_run_id(error.evaluation, at(1)) and error.generated_at == at(1)
    assert error.reports_dir == tmp_path / "reports"
    runs = tmp_path / "runs"
    assert [r.run_id for r in list_runs(runs)] == [error.record.run_id]
    assert (run_count(runs, "sma_crossover"), trial_count(runs, "sma_crossover")) == (1, 1)

    blocker.unlink()
    paths = error.retry()  # writes the report; logs nothing
    assert paths.run_id == error.record.run_id and paths.directory.name == error.record.run_id
    assert (run_count(runs, "sma_crossover"), trial_count(runs, "sma_crossover")) == (1, 1)
    assert len(list_runs(runs)) == 1
    stored = get_run(runs, error.record.run_id).trial
    assert (stored.run_number, stored.trial_number, stored.trial_count, stored.new_variant) == (1, 1, 1, True)
    assert (
        "- **Trials:** family sma_crossover: 1 distinct variant in 1 run as of this run. "
        f"This run is run 1, a new variant (variant 1). {TAIL}\n"
    ) in paths.markdown.read_text(encoding="utf-8")


def test_a_second_failure_of_retry_is_the_plain_error_and_still_logs_nothing(tmp_path: Path) -> None:
    block_reports(tmp_path)
    with pytest.raises(ExperimentReportError) as caught:
        go(tmp_path, sma_spec(), 1, reports=True)
    with pytest.raises(OSError) as second:
        caught.value.retry()
    assert not isinstance(second.value, ExperimentReportError)
    assert len(list_runs(tmp_path / "runs")) == 1
    with pytest.raises(OSError):  # and again: the error object stays usable
        caught.value.retry()


def test_any_exception_of_the_report_step_is_wrapped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args, **kwargs):
        raise ValueError("a NaN reached the formatter")

    monkeypatch.setattr(experiment, "write_report", broken)
    with pytest.raises(ExperimentReportError, match="a NaN reached the formatter") as caught:
        go(tmp_path, sma_spec(), 1, reports=True)
    assert isinstance(caught.value.__cause__, ValueError)
    assert len(list_runs(tmp_path / "runs")) == 1


def test_a_failing_journal_writes_no_report(tmp_path: Path) -> None:
    (tmp_path / "runs" / "stray-folder").mkdir(parents=True)  # a run folder without a row: the index is stale
    with pytest.raises(JournalIndexStale):
        go(tmp_path, sma_spec(), 1, reports=True)
    assert not (tmp_path / "reports").exists()


# --- order and wiring ------------------------------------------------------------------------------------------------


def spy_on_steps(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []
    for name in ("evaluate", "record_run", "write_report"):
        real = getattr(experiment, name)

        def wrapper(*args, _real=real, _name=name, **kwargs):
            calls.append((_name, kwargs))
            return _real(*args, **kwargs)

        monkeypatch.setattr(experiment, name, wrapper)
    return calls


def test_the_steps_run_in_the_order_evaluate_record_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = spy_on_steps(monkeypatch)
    result = go(tmp_path, sma_spec(), 1, reports=True)
    assert [name for name, _ in calls] == ["evaluate", "record_run", "write_report"]
    report_kwargs = calls[2][1]
    assert report_kwargs["run_id"] == result.record.run_id
    assert report_kwargs["trial"] is result.record.trial
    assert report_kwargs["generated_at"] == at(1)
    assert calls[1][1]["generated_at"] == at(1)


def test_no_reports_dir_means_no_report_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = spy_on_steps(monkeypatch)
    go(tmp_path, sma_spec(), 1)
    assert [name for name, _ in calls] == ["evaluate", "record_run"]


def test_the_code_version_is_detected_only_when_none_is_given(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int] = []
    monkeypatch.setattr(experiment, "detect_code_version", lambda: seen.append(1) or CODE)
    given = go(tmp_path, sma_spec(), 1)
    assert seen == [] and given.record.code_version == CODE
    detected = run_experiment(
        sma_spec(), standard_provider(), runs_dir=tmp_path / "runs", generated_at=at(2), code_version=None
    )
    assert seen == [1] and detected.record.code_version == CODE


# --- reproducibility (Phase 8 "Done when") ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec", [hold_spec(), sma_spec()], ids=["buy_and_hold", "sma_crossover"])
def test_the_same_spec_on_the_same_data_gives_identical_metrics(tmp_path: Path, spec) -> None:
    first = go(tmp_path, spec, 1, reports=True)
    second = go(tmp_path, spec, 61, reports=True)
    one, two = get_run(tmp_path / "runs", first.record.run_id), get_run(tmp_path / "runs", second.record.run_id)
    assert one.evaluation == two.evaluation
    assert one.evaluation["strategy"]["data_hash"] == two.evaluation["strategy"]["data_hash"]
    assert one.evaluation["strategy"]["metrics"] == two.evaluation["strategy"]["metrics"]
    assert one.evaluation["relative"] == two.evaluation["relative"]
    assert one.costs == two.costs and one.trades == two.trades and one.spec == two.spec
    assert (two.trial.run_number, two.trial.trial_number, two.trial.new_variant) == (2, 1, False)


# --- report and journal agree ----------------------------------------------------------------------------------------

LINE = re.compile(
    r"family (\w+): (\d+) distinct variants? in (\d+) runs? as of this run\. "
    r"This run is run (\d+), a (?:new variant \(variant (\d+)\)|repeat of variant (\d+))\."
)


def numbers_of(line: str) -> tuple[str, int, int, int, int, bool]:
    match = LINE.search(line)
    assert match, line
    family, variants, runs, run, new, repeat = match.groups()
    return family, int(variants), int(runs), int(run), int(new or repeat), new is not None


@pytest.mark.parametrize(
    ("spec", "second", "expected"),
    [(sma_spec(), 1, ("sma_crossover", 1, 1, 1, 1, True)), (sma_spec(), 2, ("sma_crossover", 1, 2, 2, 1, False))],
    ids=["new_variant", "repeat"],
)
def test_the_report_and_run_json_have_the_same_folder_name_and_trial_numbers(
    tmp_path: Path, spec, second: int, expected
) -> None:
    for step in range(1, second + 1):
        result = go(tmp_path, spec, step, reports=True)
    run_id = result.record.run_id
    assert (tmp_path / "runs" / run_id).is_dir() and result.report.directory == tmp_path / "reports" / run_id
    trial = get_run(tmp_path / "runs", run_id).trial
    stored = (
        trial.family,
        trial.trial_count,
        trial.run_number,
        trial.run_number,
        trial.trial_number,
        trial.new_variant,
    )
    assert stored == expected
    markdown_line = next(
        line for line in result.report.markdown.read_text(encoding="utf-8").splitlines() if "**Trials:**" in line
    )
    html_line = next(
        " ".join(text_of(li).split())
        for li in parse(result.report.html.read_text(encoding="utf-8")).iter("li")
        if text_of(li).startswith("Trials:")
    )
    assert numbers_of(markdown_line) == numbers_of(html_line) == stored
