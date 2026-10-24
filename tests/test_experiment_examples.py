"""The example of docs/journal.md ("Example: the three example strategies"): run_experiment on the fake provider.

The code of ``run_three`` is the code of the docs, with the temporary folders and a fixed code version added. The
expected Trials lines are literals worked out from the wording rules of docs/report.md. Offline: the socket guard of
test_report_examples.py blocks every connection.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import backtest_agent.experiment as experiment
from backtest_agent.data import FakeProvider
from backtest_agent.experiment import run_experiment
from backtest_agent.journal import get_run, run_count, trial_count
from backtest_agent.spec import load_spec
from html_helpers import parse, text_of
from journal_helpers import CODE
from test_report_examples import NAMES, PERIOD, STRATEGIES, install_guard

START = datetime(2026, 1, 15, 10, 30, 5, tzinfo=UTC)
TAIL = " Counts cover only runs logged in this journal."


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    install_guard(monkeypatch)
    monkeypatch.setattr(experiment, "detect_code_version", lambda: CODE)  # never depend on the real commit


def run_three(name: str, runs: Path, reports: Path) -> list:
    """Three runs of one example strategy: the spec, the same spec again, and the spec with another initial capital."""
    spec = load_spec(STRATEGIES / f"{name}.yaml").model_copy(update={"period": PERIOD})
    provider = FakeProvider(symbols=spec.universe)
    larger = spec.model_copy(update={"initial_capital": 2 * spec.initial_capital})
    return [
        run_experiment(s, provider, runs_dir=runs, reports_dir=reports, generated_at=START + timedelta(seconds=second))
        for second, s in enumerate((spec, spec, larger))
    ]


def expected(family: str) -> list[str]:
    return [
        f"family {family}: 1 distinct variant in 1 run as of this run. This run is run 1, a new variant (variant 1)."
        + TAIL,
        f"family {family}: 1 distinct variant in 2 runs as of this run. This run is run 2, a repeat of variant 1."
        + TAIL,
        f"family {family}: 2 distinct variants in 3 runs as of this run. This run is run 3, a new variant (variant 2)."
        + TAIL,
    ]


@pytest.mark.parametrize("name", NAMES)
def test_the_trial_lines_of_the_three_runs_of_an_example_strategy(name: str, tmp_path: Path) -> None:
    runs, reports = tmp_path / "runs", tmp_path / "reports"
    results = run_three(name, runs, reports)

    markdown = [r.report.markdown.read_text(encoding="utf-8") for r in results]
    for text, line in zip(markdown, expected(name), strict=True):
        assert f"- **Trials:** {line}\n" in text
    for result, line in zip(results, expected(name), strict=True):
        items = [
            " ".join(text_of(li).split()) for li in parse(result.report.html.read_text(encoding="utf-8")).iter("li")
        ]
        assert f"Trials: {line}" in items

    assert (run_count(runs, name), trial_count(runs, name)) == (3, 2)
    for result in results:  # report folder, run folder and the trial of run.json agree
        assert result.report.directory == reports / result.record.run_id
        assert get_run(runs, result.record.run_id).trial == result.record.trial


def test_the_three_example_strategies_are_three_families_in_one_journal(tmp_path: Path) -> None:
    runs, reports = tmp_path / "runs", tmp_path / "reports"
    for name in NAMES:
        results = run_three(name, runs, reports)
        assert [r.record.trial.run_number for r in results] == [1, 2, 3]  # counted per family, not together
    assert [(run_count(runs, n), trial_count(runs, n)) for n in NAMES] == [(3, 2)] * 3
