"""Characters that XML 1.0 forbids (NUL and other control characters) are replaced once, in ``text()`` of the model.

So the Markdown, the HTML and the standalone SVG files are all well-formed for a strategy name or a validation message
that contains them.
"""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from backtest_agent.data.validation import Severity, ValidationIssue, ValidationResult
from backtest_agent.reporting.charts import line_chart_svg
from backtest_agent.reporting.html_renderer import render_html
from backtest_agent.reporting.markdown_renderer import render_markdown
from backtest_agent.reporting.model import build_report_model, text
from html_helpers import parse
from report_helpers import all_cells, equal_start

WHEN = datetime(2026, 1, 15, 10, 30, 5, tzinfo=UTC)
REPLACEMENT = "\ufffd"


@pytest.mark.parametrize(
    "raw, shown",
    [
        ("a\x00b", f"a{REPLACEMENT}b"),
        ("\x00", REPLACEMENT),
        ("x\x01\x08y", f"x{REPLACEMENT}{REPLACEMENT}y"),
        ("x\x0ey\x1bz", f"x{REPLACEMENT}y{REPLACEMENT}z"),
        ("x\ud800y", f"x{REPLACEMENT}y"),
        ("x\ufffey\uffff", f"x{REPLACEMENT}y{REPLACEMENT}"),
        ("tab\tnew\nline", "tab new line"),  # whitespace is collapsed as before
        ("a\x0bb\x0cc\x1dd", "a b c d"),  # these control characters are whitespace for \s: spaces, not replaced
        ("\x7f ok \u00e4\U0001f600", "\x7f ok \u00e4\U0001f600"),  # allowed characters stay
        ("   ", "(none)"),
    ],
)
def test_text_replaces_what_xml_forbids(raw, shown) -> None:
    assert text(raw) == shown


def hostile_evaluation():
    evaluation = equal_start()
    spec = evaluation.result.spec.model_copy(update={"name": "Nul\x00 strategy\x01"})
    issue = ValidationIssue(Severity.WARNING, "gap", "A\x00", "close", 2, (date(2024, 1, 3),), "bad \x00 message\x1b")
    result = replace(evaluation.result, spec=spec, validation=ValidationResult((issue,)))
    return replace(evaluation, result=result)


def test_a_nul_in_a_name_or_message_leaves_markdown_html_and_both_svg_files_clean_and_well_formed() -> None:
    model = build_report_model(hostile_evaluation(), run_id="r1", generated_at=WHEN)
    markdown, html = render_markdown(model), render_html(model)
    equity = line_chart_svg(model.charts.equity, standalone=True)
    drawdown = line_chart_svg(model.charts.drawdown, standalone=True)

    for name, content in {
        "report.md": markdown,
        "report.html": html,
        "equity.svg": equity,
        "drawdown.svg": drawdown,
    }.items():
        assert not any(c < " " and c not in "\n\t" for c in content), name
        assert REPLACEMENT in content or name == "drawdown.svg" or "message" in content, name
    assert f"Nul{REPLACEMENT} strategy{REPLACEMENT}" in markdown and f"bad {REPLACEMENT} message" in markdown
    parse(html)
    parse(equity)
    parse(drawdown)
    assert not [cell for cell in all_cells(model) if any(c < " " for c in cell)]
