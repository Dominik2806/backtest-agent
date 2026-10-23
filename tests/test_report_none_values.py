"""None never prints as "nan", "None" or an empty cell; NaN and infinity are bugs and raise with the field name."""

import dataclasses
import re
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from backtest_agent.metrics.performance import PerformanceMetrics
from backtest_agent.metrics.relative import RelativeMetrics
from backtest_agent.reporting.markdown_renderer import render_markdown
from backtest_agent.reporting.model import build_report_model
from report_helpers import all_kinds, equal_start, insufficient_overlap

WHEN = datetime(2026, 1, 15, 10, 30, 5, tzinfo=UTC)
COUNTS = {"assumptions", "n_bars", "n_months"}


def markdown_of(evaluation) -> str:
    return render_markdown(build_report_model(evaluation, run_id="run-1", generated_at=WHEN))


def all_none_metrics(metrics: PerformanceMetrics) -> PerformanceMetrics:
    names = [f.name for f in dataclasses.fields(metrics) if f.name not in COUNTS]
    return replace(metrics, **dict.fromkeys(names))


def assert_no_bad_text(text: str) -> None:
    assert not re.search(r"\b(nan|None|inf|-inf)\b", text), re.findall(r".*\b(?:nan|None|inf)\b.*", text)
    assert not re.search(r"\|[ \t]*\|", text), "an empty table cell"  # two pipes with only blanks on the line between
    assert "None" not in text and "nan%" not in text


@pytest.mark.parametrize("kind", list(all_kinds()))
def test_no_kind_of_run_prints_nan_none_or_an_empty_cell(kind) -> None:
    assert_no_bad_text(markdown_of(all_kinds()[kind]))


def test_every_undefined_metric_prints_as_na() -> None:
    evaluation = equal_start()
    undefined = replace(
        evaluation,
        metrics=all_none_metrics(evaluation.metrics),
        benchmark_metrics=all_none_metrics(evaluation.benchmark_metrics),
    )
    text = markdown_of(undefined)
    assert_no_bad_text(text)
    performance = text.split("### Performance")[1].split("### Relative")[0]
    rows = [line for line in performance.splitlines() if line.startswith("| ") and "---" not in line][1:]
    assert len(rows) == 14
    for row in rows:
        label, strategy, benchmark = [c.strip() for c in row.strip("|").split("|")]
        if label in {"Bars"}:
            continue  # counts stay numbers
        assert strategy == "n/a" and benchmark == "n/a", row


def test_insufficient_overlap_prints_the_relative_metrics_as_na() -> None:
    evaluation = insufficient_overlap()
    assert evaluation.relative.excess_return is None  # the premise: nothing to compare
    text = markdown_of(evaluation)
    relative = text.split("### Relative to the benchmark")[1].split("## Benchmark alignment")[0]
    values = [
        line.split("|")[2].strip() for line in relative.splitlines() if line.startswith("| ") and "---" not in line
    ]
    assert values[1:] == ["n/a"] * 5
    assert "share too few dates" in text
    assert_no_bad_text(text)


def test_a_fully_undefined_relative_block_prints_as_na() -> None:
    evaluation = equal_start()
    empty = RelativeMetrics(None, None, None, None, None, evaluation.relative.alignment)
    text = markdown_of(replace(evaluation, relative=empty))
    relative = text.split("### Relative to the benchmark")[1].split("## Benchmark alignment")[0]
    assert relative.count("n/a") == 5
    assert_no_bad_text(text)


def test_the_cost_share_that_is_none_has_no_percent_sign() -> None:
    text = markdown_of(equal_start())
    row = next(line for line in text.splitlines() if line.startswith("| Cost share"))
    assert row.endswith("| 63.09% | n/a (gross return is not positive) |")
    assert "%" not in row.split("|")[3]


def test_the_cost_share_above_100_percent_or_negative_is_printed_as_a_percentage() -> None:
    evaluation = equal_start()
    # Gross return 10%, net return -5%: the drag is 0.15 and the costs ate 0.15 / 0.1 = 150% of the gross return.
    result = replace(
        evaluation.result,
        equity=evaluation.result.equity * 0 + [1000, 1000, 1000, 1000, 950],
        gross_equity=evaluation.result.gross_equity * 0 + [1000, 1000, 1000, 1000, 1100],
    )
    text = markdown_of(replace(evaluation, result=result))
    row = next(line for line in text.splitlines() if line.startswith("| Cost share"))
    assert row.split("|")[2].strip() == "150.00%"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nan_and_infinity_raise_a_value_error_that_names_the_field(bad) -> None:
    evaluation = equal_start()
    broken = replace(evaluation, metrics=replace(evaluation.metrics, total_return=bad))
    with pytest.raises(ValueError, match="strategy.total_return"):
        markdown_of(broken)
    broken = replace(evaluation, relative=replace(evaluation.relative, tracking_error=bad))
    with pytest.raises(ValueError, match="tracking_error"):
        markdown_of(broken)
