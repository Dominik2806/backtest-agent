"""The fixed caveats, the run-specific caveats and the explanation of every risk flag."""

import inspect
import re
from pathlib import Path

import backtest_agent
from backtest_agent.reporting import caveats
from backtest_agent.reporting.caveats import FLAG_EXPLANATIONS, UNKNOWN_FLAG_EXPLANATION, explain_flag, fixed_caveats
from report_helpers import (
    all_kinds,
    equal_start,
    insufficient_overlap,
    insufficient_warmup,
    late_benchmark,
    with_flags,
)

SOURCE = Path(backtest_agent.__file__).parent


def test_fixed_caveats_has_no_parameter() -> None:
    assert list(inspect.signature(fixed_caveats).parameters) == []


def test_fixed_caveats_are_the_same_text_every_time_and_cover_what_the_roadmap_asks() -> None:
    first, second = fixed_caveats(), fixed_caveats()
    assert first == second
    titles = [c.title for c in first]
    assert titles == [
        "Execution",
        "Costs",
        "Adjusted prices",
        "Survivorship",
        "Annualization of short runs",
        "Partial months",
        "Selection bias",
        "Not investment advice",
    ]
    text = " ".join(c.text for c in first).lower()
    for phrase in (
        "delay_bars",
        "look-ahead",
        "commission",
        "adjusted close",
        "today's constituents",
        "delisted",
        "cagr",
        "strongly extrapolated",
        "first and the last calendar month",
        "not investment advice",
    ):
        assert phrase in text, phrase
    assert all(c.title and c.text for c in first)


def test_no_text_contains_a_url() -> None:
    texts = [c.text for c in fixed_caveats()] + list(FLAG_EXPLANATIONS.values()) + [UNKNOWN_FLAG_EXPLANATION]
    for evaluation in all_kinds().values():
        texts += list(caveats.run_caveats(evaluation))
    for text in texts:
        assert "http" not in text.lower() and "www." not in text.lower() and "://" not in text


def test_every_risk_flag_code_in_the_source_has_an_explanation() -> None:
    # Fails when someone adds RiskFlag("new_code", ...) without adding its explanation to FLAG_EXPLANATIONS.
    codes = set()
    for path in SOURCE.rglob("*.py"):
        codes |= set(re.findall(r'RiskFlag\(\s*"([a-z_]+)"', path.read_text(encoding="utf-8")))
    assert codes == {"same_bar_execution", "zero_costs", "costs_not_applied", "insufficient_warmup"}
    assert codes <= set(FLAG_EXPLANATIONS)


def test_the_flags_of_real_runs_are_explained() -> None:
    seen = set()
    for evaluation in (with_flags(), insufficient_warmup(), all_kinds()["costs_off"]):
        for result in (evaluation.result, evaluation.benchmark_result):
            for flag in result.risk_flags:
                seen.add(flag.code)
                assert explain_flag(flag.code) == FLAG_EXPLANATIONS[flag.code] != UNKNOWN_FLAG_EXPLANATION
    assert seen == {"same_bar_execution", "zero_costs", "costs_not_applied", "insufficient_warmup"}


def test_an_unknown_code_gets_the_fallback_sentence() -> None:
    assert explain_flag("some_future_flag") == UNKNOWN_FLAG_EXPLANATION


def test_run_caveats_of_an_equal_start() -> None:
    lines = caveats.run_caveats(equal_start())
    assert lines[0] == "Execution in this run: delay of 1 bar(s), fills at the open."
    assert any("covers 5 bars (1.00 years at 5 bars a year)" in line for line in lines)  # P5 world: a very short run
    assert not any("benchmark starts" in line or "benchmark ends" in line for line in lines)
    assert not any("risk flags" in line for line in lines)


def test_run_caveats_of_a_late_benchmark() -> None:
    lines = caveats.run_caveats(late_benchmark())
    assert any("The benchmark starts on 2024-01-04, after the strategy (2024-01-02)" in line for line in lines)


def test_run_caveats_of_flags_and_same_bar_execution() -> None:
    lines = caveats.run_caveats(with_flags())
    assert lines[0] == (
        "Execution in this run: delay of 0 bar(s), fills at the close (same-bar execution was allowed explicitly)."
    )
    assert any("risk flags (same_bar_execution, zero_costs)" in line for line in lines)


def test_run_caveats_of_insufficient_overlap() -> None:
    lines = caveats.run_caveats(insufficient_overlap())
    assert any("share too few dates" in line for line in lines)
