"""The counter table of docs/journal.md ("Counter table"), as literals, step by step.

Every number below was written out by hand from the definitions in the document: a run is a repeat of an earlier variant
if the spec is the same apart from name and description; the family is the signal id.
"""

import pytest

from backtest_agent.journal import get_run, list_runs, record_run, run_count, trial_count
from journal_helpers import (
    CODE,
    at,
    evaluation_of,
    hold_spec,
    no_repo_runs,  # noqa: F401 - fixture used through pytestmark
    other_data_provider,
    sma_spec,
)

pytestmark = pytest.mark.usefixtures("no_repo_runs")

F1, F2 = "sma_crossover", "buy_and_hold"

# step, how to build (spec, provider, evaluate kwargs), run_number, trial_number, trial_count as of the run,
# new_variant, then the counters after the step: F1 runs, F1 trials, F2 runs, F2 trials
STEPS = [
    ("S1", lambda: (sma_spec(), None, {}), F1, 1, 1, 1, True, (1, 1, 0, 0)),
    (
        "S2",
        lambda: (sma_spec(name="Renamed run", description="Changed text"), None, {}),
        F1,
        2,
        1,
        1,
        False,
        (2, 1, 0, 0),
    ),
    ("S3", lambda: (sma_spec(slow=4), None, {}), F1, 3, 2, 2, True, (3, 2, 0, 0)),
    ("S4", lambda: (sma_spec(start="2024-01-03"), None, {}), F1, 4, 3, 3, True, (4, 3, 0, 0)),
    ("S5", lambda: (hold_spec(), None, {}), F2, 1, 1, 1, True, (4, 3, 1, 1)),
    ("S6", lambda: (sma_spec(), None, {}), F1, 5, 1, 3, False, (5, 3, 1, 1)),
    ("S7", lambda: (sma_spec(), other_data_provider(), {}), F1, 6, 1, 3, False, (6, 3, 1, 1)),
    ("S8", lambda: (sma_spec(), None, {"apply_costs": False}), F1, 7, 1, 3, False, (7, 3, 1, 1)),
    ("S9", lambda: (sma_spec(commission=900.0), None, {}), F1, 8, 4, 4, True, (8, 4, 1, 1)),
]


def test_the_counter_table_step_by_step(tmp_path) -> None:
    runs = tmp_path / "runs"
    logged = []
    for second, (step, build, family, run_number, trial_number, trials_then, new, after) in enumerate(STEPS, start=1):
        spec, provider, kwargs = build()
        record = record_run(evaluation_of(spec, provider, **kwargs), runs, generated_at=at(second), code_version=CODE)
        logged.append(record)
        trial = record.trial
        assert (trial.family, trial.run_number, trial.trial_number, trial.trial_count, trial.new_variant) == (
            family,
            run_number,
            trial_number,
            trials_then,
            new,
        ), step
        assert trial.run_count == run_number, step
        assert (run_count(runs, F1), trial_count(runs, F1), run_count(runs, F2), trial_count(runs, F2)) == after, step
    assert len(list_runs(runs)) == 9
    # what was stored is what was returned
    assert [get_run(runs, record.run_id) for record in logged] == logged


def test_a_repeat_has_the_same_variant_hash_and_a_new_variant_a_different_one(tmp_path) -> None:
    runs = tmp_path / "runs"
    a1 = record_run(evaluation_of(sma_spec()), runs, generated_at=at(1), code_version=CODE)
    a2 = record_run(
        evaluation_of(sma_spec(name="Other", description="Other")), runs, generated_at=at(2), code_version=CODE
    )
    b = record_run(evaluation_of(sma_spec(slow=4)), runs, generated_at=at(3), code_version=CODE)
    assert a1.trial.variant_hash == a2.trial.variant_hash != b.trial.variant_hash


def test_list_runs_of_a_family_and_the_limit(tmp_path) -> None:
    runs = tmp_path / "runs"
    for second, (_, build, *_rest) in enumerate(STEPS[:5], start=1):
        spec, provider, kwargs = build()
        record_run(evaluation_of(spec, provider, **kwargs), runs, generated_at=at(second), code_version=CODE)
    assert [r.run_number for r in list_runs(runs, family=F1)] == [4, 3, 2, 1]  # newest first
    assert [r.run_number for r in list_runs(runs, family=F2)] == [1]
    assert [r.family for r in list_runs(runs, limit=2)] == [F2, F1]
    assert list_runs(runs, family="unknown") == ()
    assert (run_count(runs, "unknown"), trial_count(runs, "unknown")) == (0, 0)


def test_a_missing_journal_is_empty(tmp_path) -> None:
    runs = tmp_path / "never-made"
    assert list_runs(runs) == ()
    assert (run_count(runs, F1), trial_count(runs, F1)) == (0, 0)
    assert not runs.exists()


def test_the_limit_must_be_positive(tmp_path) -> None:
    for bad in (0, -1):
        with pytest.raises(ValueError, match="limit"):
            list_runs(tmp_path, limit=bad)
