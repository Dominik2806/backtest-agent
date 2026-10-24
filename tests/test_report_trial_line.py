"""The Trials item of the report header (docs/report.md, "The trial line"): wording, plurals, refusals, both formats.

All expected texts are literals written out from the wording rules and the counter table of docs/journal.md.
"""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from backtest_agent.journal.models import TrialInfo
from backtest_agent.reporting import render_report
from backtest_agent.reporting.html_renderer import render_html
from backtest_agent.reporting.markdown_renderer import render_markdown
from backtest_agent.reporting.model import build_report_model, trial_line
from html_helpers import parse, text_of
from report_helpers import equal_start

WHEN = datetime(2026, 1, 15, 10, 30, 5, tzinfo=UTC)
RUN_ID = "20260115T103005Z-buy-and-hold-a-a85a59ee"
HASH = "a7b3d3b5b0e2a72814fcb465bc7d203f96ae332c45eff8880ac85e5a9a492cad"
FAMILY = "family sma_crossover: "
TAIL = "Counts cover only runs logged in this journal."
NOT_RECORDED = "not recorded (this report was not written through run_experiment)"


def trial(count: int, runs: int, number: int, new: bool, family: str = "sma_crossover") -> TrialInfo:
    return TrialInfo(family, HASH, run_number=runs, trial_number=number, trial_count=count, new_variant=new)


# (trial_count, run_number, trial_number, new_variant, expected value): S1, S3 and S6 of the counter table and more
CASES = [
    (
        1,
        1,
        1,
        True,
        FAMILY + "1 distinct variant in 1 run as of this run. This run is run 1, a new variant (variant 1). " + TAIL,
    ),
    (
        1,
        3,
        1,
        False,
        FAMILY + "1 distinct variant in 3 runs as of this run. This run is run 3, a repeat of variant 1. " + TAIL,
    ),
    (
        2,
        3,
        2,
        True,
        FAMILY + "2 distinct variants in 3 runs as of this run. This run is run 3, a new variant (variant 2). " + TAIL,
    ),
    (
        2,
        3,
        1,
        False,
        FAMILY + "2 distinct variants in 3 runs as of this run. This run is run 3, a repeat of variant 1. " + TAIL,
    ),
    (
        3,
        5,
        3,
        True,
        FAMILY + "3 distinct variants in 5 runs as of this run. This run is run 5, a new variant (variant 3). " + TAIL,
    ),
    (
        3,
        5,
        1,
        False,
        FAMILY + "3 distinct variants in 5 runs as of this run. This run is run 5, a repeat of variant 1. " + TAIL,
    ),
]


@pytest.mark.parametrize(("count", "runs", "number", "new", "expected"), CASES)
def test_the_wording_of_every_reachable_case(count: int, runs: int, number: int, new: bool, expected: str) -> None:
    assert trial_line(trial(count, runs, number, new)) == expected


def test_no_trial_says_not_recorded() -> None:
    assert trial_line(None) == NOT_RECORDED


# --- impossible values are refused, naming the field ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("bad", "field"),
    [
        (trial(1, 0, 1, True), "trial.run_number"),
        (trial(1, 1, 0, True), "trial.trial_number"),
        (trial(0, 1, 1, True), "trial.trial_count"),
        (trial(1, 1, -1, True), "trial.trial_number"),
    ],
)
def test_a_number_below_one_is_refused(bad: TrialInfo, field: str) -> None:
    with pytest.raises(ValueError, match=rf"{field} must be 1 or more"):
        trial_line(bad)


def test_a_trial_number_above_the_trial_count_is_refused() -> None:
    with pytest.raises(ValueError, match=r"trial\.trial_number \(3\) is above trial\.trial_count \(2\)"):
        trial_line(trial(2, 4, 3, False))


def test_a_trial_count_above_the_run_number_is_refused() -> None:
    with pytest.raises(ValueError, match=r"trial\.trial_count \(2\) is above trial\.run_number \(1\)"):
        trial_line(trial(2, 1, 2, True))


def test_a_new_variant_must_be_the_last_variant() -> None:
    with pytest.raises(ValueError, match=r"trial\.new_variant is true but trial\.trial_number \(1\) differs"):
        trial_line(trial(2, 3, 1, True))


def test_a_repeat_needs_an_earlier_run() -> None:
    with pytest.raises(ValueError, match=r"trial\.new_variant is false but trial\.trial_count equals"):
        trial_line(trial(2, 2, 1, False))


# --- Markdown and HTML ---------------------------------------------------------------------------------------------


def markdown(info: TrialInfo | None) -> str:
    return render_markdown(build_report_model(equal_start(), run_id=RUN_ID, generated_at=WHEN, trial=info))


def html(info: TrialInfo | None) -> str:
    return render_html(build_report_model(equal_start(), run_id=RUN_ID, generated_at=WHEN, trial=info))


def html_item(document: str) -> str:
    """The text of the list item that starts with the label Trials."""
    items = [" ".join(text_of(li).split()) for li in parse(document).iter("li")]
    found = [item for item in items if item.startswith("Trials:")]
    assert len(found) == 1
    return found[0]


@pytest.mark.parametrize(("count", "runs", "number", "new", "expected"), CASES)
def test_markdown_and_html_show_the_line(count: int, runs: int, number: int, new: bool, expected: str) -> None:
    info = trial(count, runs, number, new)
    assert f"- **Trials:** {expected}\n" in markdown(info)
    assert html_item(html(info)) == f"Trials: {expected}"


def test_markdown_and_html_without_a_trial() -> None:
    assert f"- **Trials:** {NOT_RECORDED}\n" in markdown(None)
    assert html_item(html(None)) == f"Trials: {NOT_RECORDED}"


def test_the_item_is_in_the_header_block_after_the_benchmark() -> None:
    lines = markdown(trial(1, 1, 1, True)).splitlines()
    start = lines.index("- **Benchmark:** B")
    assert lines[start + 1].startswith("- **Trials:** family sma_crossover: 1 distinct variant")
    assert lines[start + 2] == ""


def test_a_family_with_markup_characters_is_escaped_and_the_html_still_parses() -> None:
    info = trial(1, 1, 1, True, family="a&b<c_d")
    line = "family a&b<c_d: 1 distinct variant in 1 run as of this run. This run is run 1, a new variant (variant 1). "
    assert f"- **Trials:** {line.replace('&', chr(92) + '&').replace('<', chr(92) + '<')}{TAIL}\n" in markdown(info)
    document = html(info)
    assert "a&amp;b&lt;c_d" in document and "a&b<c" not in document
    assert html_item(document) == f"Trials: {line}{TAIL}"  # parse() ran: the page is well-formed XML


def test_the_family_name_keeps_its_underscores_in_markdown() -> None:
    # md_escape does not escape the underscore (it is not a structural character in the tables or lists used here)
    assert "family sma_crossover:" in markdown(trial(1, 1, 1, True))


# --- the writer and the caveat -------------------------------------------------------------------------------------

SELECTION_BIAS = (
    "This report does not know how many other variants were tried before this one. The more variants are "
    "tried, the more likely a good-looking result is luck."
)


def test_render_report_passes_the_trial_to_both_files() -> None:
    info = trial(2, 3, 1, False)
    files = render_report(equal_start(), run_id=RUN_ID, generated_at=WHEN, trial=info)
    expected = CASES[3][4]
    assert f"- **Trials:** {expected}\n" in files["report.md"]
    assert html_item(files["report.html"]) == f"Trials: {expected}"
    plain = render_report(equal_start(), run_id=RUN_ID, generated_at=WHEN)
    assert f"- **Trials:** {NOT_RECORDED}\n" in plain["report.md"]


def test_the_selection_bias_caveat_is_unchanged_next_to_the_line() -> None:
    text = markdown(trial(3, 5, 1, False))
    assert f"- **Selection bias.** {SELECTION_BIAS}\n" in text
    model = build_report_model(equal_start(), run_id=RUN_ID, generated_at=WHEN, trial=trial(3, 5, 1, False))
    assert [c.text for c in model.fixed_caveats if c.title == "Selection bias"] == [SELECTION_BIAS]
    assert replace(model, trials="x").fixed_caveats == model.fixed_caveats
