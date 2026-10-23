"""The Markdown report: structure (headings, table headers, links), escaping, and the caveats for every kind of run."""

import inspect
import re
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from backtest_agent.data.validation import Severity, ValidationIssue, ValidationResult
from backtest_agent.reporting.caveats import fixed_caveats
from backtest_agent.reporting.markdown_renderer import md_code, md_escape, render_markdown
from backtest_agent.reporting.model import build_report_model
from report_helpers import all_kinds, equal_start, make_evaluation, spec_for, with_flags

WHEN = datetime(2026, 1, 15, 10, 30, 5, tzinfo=UTC)
RUN_ID = "20260115T103005Z-buy-and-hold-a-a85a59ee"


def markdown_of(evaluation, run_id: str = RUN_ID) -> str:
    return render_markdown(build_report_model(evaluation, run_id=run_id, generated_at=WHEN))


def headings(text: str) -> list[str]:
    return [line for line in text.splitlines() if re.match(r"#{1,6} ", line)]


def table_blocks(text: str) -> list[list[str]]:
    blocks, current = [], []
    for line in text.splitlines():
        if line.startswith("|"):
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def cells(line: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]


# --- escaping ---------------


@pytest.mark.parametrize(
    "text, escaped",
    [
        ("plain text 12.34%", "plain text 12.34%"),
        ("a | b", r"a \| b"),
        ("<script>alert(1)</script>", r"\<script\>alert(1)\</script\>"),
        ("[link](x) *bold* `code`", r"\[link\](x) \*bold\* \`code\`"),
        ("back\\slash", r"back\\slash"),
        ("two\nlines\r\n  here", "two lines here"),
        ("R&D", r"R\&D"),
        ("buy_and_hold", "buy_and_hold"),
    ],
)
def test_md_escape(text, escaped) -> None:
    assert md_escape(text) == escaped


def test_md_code_uses_a_longer_fence_for_backticks() -> None:
    assert md_code("abc") == "`abc`"
    assert md_code("a`b") == "``a`b``"
    assert md_code("`a") == "`` `a ``"
    assert md_code("a\nb") == "`a b`"


# --- structure ---------------


def test_the_headings_are_in_the_documented_order() -> None:
    assert headings(markdown_of(equal_start())) == [
        "# Backtest report: Buy and hold A",
        "## Spec summary",
        "## Data",
        "### Strategy run",
        "### Benchmark run",
        "### Warm-up",
        "## Risk flags",
        "## Metrics",
        "### Assumptions",
        "### Performance",
        "### Relative to the benchmark",
        "## Benchmark alignment",
        "## Costs",
        "## Charts",
        "### Equity",
        "### Drawdown",
        "## Monthly returns",
        "## Trade statistics",
        "## Assumptions and caveats",
        "### Fixed caveats",
        "### This run",
    ]


def test_the_table_headers_are_the_documented_ones() -> None:
    headers = [cells(block[0]) for block in table_blocks(markdown_of(equal_start()))]
    month_header = ["Year", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    issue_header = ["Severity", "Code", "Symbol", "Field", "Rows", "First dates", "Message"]
    assert headers == [
        ["Item", "Value"],  # spec
        issue_header,  # strategy run
        issue_header,  # benchmark run
        ["Item", "Value"],  # warm-up
        ["Symbol", "Rows before the first decision", "First data date", "Target weight of the first decision"],
        ["Assumption", "Value"],
        ["Metric", "Strategy", "Benchmark"],
        ["Metric", "Value"],
        ["Item", "Value"],  # alignment
        ["Item", "Strategy", "Benchmark"],  # costs
        month_header,
        ["Item", "Value"],  # trade summary
        ["Symbol", "Trades", "Buys", "Sells"],
    ]


def test_every_table_has_one_separator_row_and_the_same_cell_count_in_every_row() -> None:
    for kind, evaluation in all_kinds().items():
        for block in table_blocks(markdown_of(evaluation)):
            width = len(cells(block[0]))
            assert set(cells(block[1])) == {"---"}, kind
            assert all(len(cells(line)) == width for line in block), (kind, block[0])


def test_the_chart_links_and_the_run_id_are_in_the_report() -> None:
    text = markdown_of(equal_start())
    assert re.findall(r"!\[[^\]]*\]\(([^)]*)\)", text) == ["equity.svg", "drawdown.svg"]
    assert f"- **Run id:** `{RUN_ID}`" in text
    assert "- **Generated at:** 2026-01-15 10:30:05 UTC" in text


def test_the_late_benchmark_caption_is_under_the_equity_chart_in_markdown() -> None:
    text = markdown_of(all_kinds()["late_benchmark"])
    equity_section = text.split("### Equity")[1].split("### Drawdown")[0]
    assert "![" in equity_section and "(equity.svg)" in equity_section
    assert "not comparable over the whole chart" in equity_section
    assert equity_section.index("(equity.svg)") < equity_section.index("not comparable over the whole chart")


def test_the_equal_start_caption_is_under_the_equity_chart_in_markdown() -> None:
    equity_section = markdown_of(equal_start()).split("### Equity")[1].split("### Drawdown")[0]
    assert "comparable from the first bar" in equity_section and "not comparable" not in equity_section


def test_flags_are_a_table_with_the_explanation() -> None:
    text = markdown_of(with_flags())
    assert "No risk flags." not in text
    assert "| Run | Flag | Engine message | What it means |" in text
    assert "| Strategy run | same_bar_execution |" in text and "look-ahead bias" in text
    assert "No risk flags." in markdown_of(equal_start())


def test_the_output_uses_unix_line_ends_and_ends_with_one_newline() -> None:
    text = markdown_of(equal_start())
    assert "\r" not in text and text.endswith("\n") and not text.endswith("\n\n")


def test_the_renderer_takes_the_model_and_nothing_else() -> None:
    assert list(inspect.signature(render_markdown).parameters) == ["model"]


# --- hostile text ---------------

HOSTILE = "<script>alert(1)</script> | [x](http://evil.example) *b* `c`"


def test_a_hostile_name_cannot_break_a_table_or_inject_markup() -> None:
    text = markdown_of(make_evaluation(spec=spec_for("B", name=HOSTILE)))
    assert "<script>" not in text and "</script>" not in text
    assert r"\<script\>alert(1)\</script\>" in text
    assert "[x](http" not in text and r"\[x\](http://evil.example)" in text
    for block in table_blocks(text):
        assert all(len(cells(line)) == len(cells(block[0])) for line in block)
    assert headings(text)[0].startswith("# Backtest report: \\<script\\>")


def test_a_validation_message_with_pipes_and_newlines_stays_in_its_row() -> None:
    evaluation = equal_start()
    issue = ValidationIssue(Severity.WARNING, "gap", "A|B", "close", 2, (date(2024, 1, 3),), "bad | row\n| injected |")
    result = replace(evaluation.result, validation=ValidationResult((issue,)))
    text = markdown_of(replace(evaluation, result=result))
    rows = [line for line in text.splitlines() if line.startswith("| warning |")]
    assert len(rows) == 1 and len(cells(rows[0])) == 7
    assert r"A\|B" in rows[0] and r"bad \| row \| injected \|" in rows[0]


# --- the caveats cannot be left out ---------------


@pytest.mark.parametrize("kind", list(all_kinds()))
def test_the_caveats_section_is_in_the_markdown_of_every_kind_of_run(kind) -> None:
    text = markdown_of(all_kinds()[kind])
    h2 = [h for h in headings(text) if h.startswith("## ")]
    assert h2[-1] == "## Assumptions and caveats"
    section = text.split("## Assumptions and caveats")[1]
    for caveat in fixed_caveats():
        assert f"- **{md_escape(caveat.title)}.** {md_escape(caveat.text)}" in section
    assert "### This run" in section and "Execution in this run" in section


# --- sections that depend on the run ----------------


def test_a_run_without_validation_findings_says_so_instead_of_an_empty_table() -> None:
    evaluation = equal_start()
    clean = replace(evaluation.result, validation=ValidationResult(()))
    text = markdown_of(replace(evaluation, result=clean))
    strategy_run = text.split("### Strategy run")[1].split("### Benchmark run")[0]
    assert "No validation warnings or infos." in strategy_run and "| Severity |" not in strategy_run
    assert "- **Validation:** 0 errors, 0 warnings, 0 infos" in strategy_run
    benchmark_run = text.split("### Benchmark run")[1].split("### Warm-up")[0]
    assert "| Severity |" in benchmark_run and "No validation warnings" not in benchmark_run


def test_the_notes_about_the_comparison_are_listed_when_there_are_some() -> None:
    late = markdown_of(all_kinds()["late_benchmark"]).split("## Benchmark alignment")[1].split("## Costs")[0]
    assert "- The benchmark starts later than the strategy: its first bar is 2024-01-04" in late
    assert "- Dates that only one of the two runs has are counted above" in late
    equal = markdown_of(equal_start()).split("## Benchmark alignment")[1].split("## Costs")[0]
    assert "\n- " not in equal
