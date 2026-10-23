"""The report model: literal display strings (docs/metrics.md R3b and T2, docs/engine.md H23),
the heatmap grid of a tiny case, the equity chart caption, the table guards and the caveats guard.
"""

import inspect
from dataclasses import replace
from datetime import UTC, date, datetime

import pandas as pd
import pytest

from backtest_agent.data.validation import Severity, ValidationIssue, ValidationResult
from backtest_agent.reporting.caveats import FLAG_EXPLANATIONS, Caveat, fixed_caveats
from backtest_agent.reporting.model import Table, build_report_model, heatmap_section
from report_helpers import (
    all_cells,
    all_kinds,
    benchmark_in_universe,
    costs_off,
    early_benchmark,
    equal_start,
    insufficient_overlap,
    insufficient_warmup,
    late_benchmark,
    make_evaluation,
    spec_for,
    with_flags,
)

WHEN = datetime(2026, 1, 15, 10, 30, 5, tzinfo=UTC)


def model_of(evaluation, **kwargs):
    return build_report_model(evaluation, run_id=kwargs.pop("run_id", "run-1"), generated_at=kwargs.pop("when", WHEN))


def rows(table: Table) -> dict[str, tuple[str, ...]]:
    return {row[0]: row[1:] for row in table.rows}


# --- the header and the spec ----------------------------------------------------------------------


def test_header_of_the_r3b_run() -> None:
    header = model_of(equal_start()).header
    assert header.strategy_name == "Buy and hold A"
    assert header.run_id == "run-1"
    assert header.generated_at == "2026-01-15 10:30:05 UTC"
    assert header.period == "2024-01-02 to 2024-01-08"
    assert header.bars == "5 bars, first bar 2024-01-02, last bar 2024-01-08"
    assert (header.universe, header.benchmark) == ("A", "B")


def test_spec_table_of_the_r3b_run() -> None:
    spec = rows(model_of(equal_start()).spec)
    assert spec["Universe"] == ("A",)
    assert spec["Signal"] == ("buy_and_hold",) and spec["Signal parameters"] == ("(none)",)
    assert spec["Rebalance"] == ("on_signal",) and spec["Sizing"] == ("equal_weight",)
    assert spec["Execution delay (bars)"] == ("1",) and spec["Execution price"] == ("open",)
    assert spec["Initial capital"] == ("1,000.00",)
    assert (spec["Commission"], spec["Spread"], spec["Slippage"]) == (("1,000 bps",), ("1,000 bps",), ("500 bps",))
    assert spec["Minimum commission per trade"] == ("0.00",)
    assert spec["Benchmark"] == ("B",)


def test_signal_parameters_are_sorted_and_formatted() -> None:
    spec = rows(model_of(insufficient_warmup()).spec)
    assert spec["Signal parameters"] == ("fast=5, slow=20",)


def test_text_from_the_spec_is_kept_raw_with_whitespace_collapsed() -> None:
    evaluation = make_evaluation(spec=spec_for("B", name="<b>x</b> | y"))
    spec = evaluation.result.spec.model_copy(update={"description": "line one\n  line   two"})
    model = model_of(replace(evaluation, result=replace(evaluation.result, spec=spec)))
    assert model.header.strategy_name == "<b>x</b> | y"
    assert rows(model.spec)["Description"] == ("line one line two",)
    assert rows(model.spec)["Name"] == ("<b>x</b> | y",)


def test_an_empty_description_is_shown_as_none() -> None:
    assert rows(model_of(equal_start()).spec)["Description"] == ("A spec used in tests.",)
    spec = equal_start().result.spec.model_copy(update={"description": ""})
    evaluation = equal_start()
    model = model_of(replace(evaluation, result=replace(evaluation.result, spec=spec)))
    assert rows(model.spec)["Description"] == ("(none)",)


# --- determinism and the time ---------------------------------------------------------------------


def test_the_model_is_a_pure_function_of_the_evaluation_and_the_arguments() -> None:
    evaluation = equal_start()
    assert model_of(evaluation) == model_of(evaluation)
    later = model_of(evaluation, when=datetime(2027, 6, 1, 8, 0, 0, tzinfo=UTC))
    assert later.header.generated_at == "2027-06-01 08:00:00 UTC"
    assert replace(later, header=model_of(evaluation).header) == model_of(
        evaluation
    )  # nothing else depends on the time


def test_a_naive_generated_at_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        model_of(equal_start(), when=datetime(2026, 1, 15, 10, 30, 5))


def test_the_signatures_have_no_way_to_touch_the_caveats() -> None:
    for function in (build_report_model, heatmap_section):
        assert not [name for name in inspect.signature(function).parameters if "caveat" in name.lower()]
    assert list(inspect.signature(build_report_model).parameters) == ["evaluation", "run_id", "generated_at"]


# --- data, flags ----------------------------------------------------------------------------------


def test_data_hashes_warm_up_and_issues() -> None:
    evaluation = equal_start()
    data = model_of(evaluation).data
    assert [run.label for run in data.runs] == ["Strategy run", "Benchmark run"]
    assert data.runs[0].data_hash == evaluation.result.data_hash
    assert data.runs[1].data_hash == evaluation.benchmark_result.data_hash
    assert data.runs[0].data_hash != data.runs[1].data_hash
    assert data.runs[0].summary == "0 errors, 0 warnings, 1 infos"
    assert rows(data.warmup)["Warm-up sufficient"] == ("yes",)
    assert rows(data.warmup)["Warm-up rows required by the signal"] == ("0",)
    assert data.warmup_symbols.rows[0][0] == "A"
    assert (
        "Benchmark B: 0 warm-up rows required, warm-up sufficient: yes, first bar 2024-01-02." == data.benchmark_warmup
    )


def test_validation_warnings_of_both_runs_are_listed() -> None:
    evaluation = equal_start()
    warning = ValidationIssue(
        Severity.WARNING, "gap", "A", "close", 2, (date(2024, 1, 3), date(2024, 1, 4)), "a | gap\nhere"
    )
    frame_level = ValidationIssue(Severity.WARNING, "stale", None, None, 7, (), "frame level")
    benchmark_warning = ValidationIssue(
        Severity.WARNING, "extreme_move", "B", "close", 1, (date(2024, 1, 5),), "big move"
    )
    result = replace(evaluation.result, validation=ValidationResult((warning, frame_level)))
    benchmark = replace(evaluation.benchmark_result, validation=ValidationResult((benchmark_warning,)))
    data = model_of(replace(evaluation, result=result, benchmark_result=benchmark)).data
    assert data.runs[0].summary == "0 errors, 2 warnings, 0 infos"
    first, second = data.runs[0].issues
    assert (first.severity, first.code, first.symbol, first.field, first.count) == ("warning", "gap", "A", "close", "2")
    assert first.first_dates == "2024-01-03, 2024-01-04" and first.message == "a | gap here"
    assert (second.symbol, second.field, second.first_dates) == ("all", "all", "n/a")
    assert [i.code for i in data.runs[1].issues] == ["extreme_move"]


def test_no_flags_without_flags_and_explanations_with_them() -> None:
    assert model_of(equal_start()).flags == ()
    flags = model_of(with_flags()).flags
    assert [(f.run, f.code) for f in flags] == [
        ("Strategy run", "same_bar_execution"),
        ("Strategy run", "zero_costs"),
        ("Benchmark run", "same_bar_execution"),
        ("Benchmark run", "zero_costs"),
    ]
    assert all(f.explanation == FLAG_EXPLANATIONS[f.code] and f.message for f in flags)
    assert [f.code for f in model_of(insufficient_warmup()).flags] == ["insufficient_warmup"]


# --- metrics, costs, trades: literals of docs/metrics.md (R3b, M12, T2), docs/engine.md (H23) ---


def test_the_performance_table_of_r3b() -> None:
    performance = rows(model_of(equal_start()).metrics.performance)
    assert performance["Total return"] == ("17.13%", "-21.59%")  # 0.17128 and -0.21592
    assert performance["Volatility (annualized)"] == ("21.77%", "20.83%")  # 0.217715410571
    assert performance["Sharpe ratio"] == ("0.83", "-1.06")  # 0.826767381914
    assert performance["Sortino ratio"][0] == "1.50"
    assert performance["Maximum drawdown"] == ("-12.00%", "-21.59%")
    assert performance["Longest drawdown"][0] == "3 bars / 3 days"  # M12
    assert performance["Calmar ratio"][0] == "1.43"  # 1.427333333333
    assert performance["Hit rate (share of bars with a gain)"] == ("60.00%", "20.00%")
    assert performance["Best month"][0] == "17.13% (2024-01)"
    assert performance["Bars"] == ("5", "5") and performance["Years"] == ("1.00", "1.00")


def test_the_relative_table_and_the_assumptions_of_r3b() -> None:
    metrics = model_of(equal_start()).metrics
    relative = rows(metrics.relative)
    assert relative["Excess return (compared window)"] == ("+38.72%",)  # 0.3872
    assert relative["Tracking error (annualized)"] == ("24.49%",)  # 0.244948974278
    assert relative["Information ratio"] == ("1.63",)  # 1.632993161855
    assert relative["Strategy return over the compared window"] == ("17.13%",)
    assert relative["Benchmark return over the compared window"] == ("-21.59%",)
    assumptions = rows(metrics.assumptions)
    assert assumptions["Bars per year (periods_per_year)"] == ("5",)
    assert assumptions["Risk-free rate (annual)"] == ("0.00%",)


def test_the_costs_table_of_h23_and_its_benchmark() -> None:
    costs = rows(model_of(equal_start()).costs.table)
    assert costs["Costs applied"] == ("yes", "yes")
    assert costs["Total costs"] == ("200.00", "200.00")
    assert costs["Final equity, net of costs"] == ("1,171.28", "784.08")
    assert costs["Final equity, without costs (gross)"] == ("1,464.10", "980.10")
    assert costs["Net return"] == ("17.13%", "-21.59%")
    assert costs["Gross return"] == ("46.41%", "-1.99%")  # 0.4641 and -0.0199
    assert costs["Cost drag (gross return minus net return)"] == ("29.28%", "19.60%")  # 0.29282 and 0.19602
    share = costs["Cost share (share of the gross return the costs ate)"]
    assert share == ("63.09%", "n/a (gross return is not positive)")  # 292.82 / 464.1 and None


def test_costs_not_applied_is_said_and_shown() -> None:
    model = model_of(costs_off())
    costs = model.costs
    assert rows(costs.table)["Costs applied"] == ("no", "no")
    assert rows(costs.table)["Total costs"] == ("0.00", "0.00")
    assert costs.notes[0].startswith("Costs were not applied in this run")


def test_the_trade_section_of_h23() -> None:
    trades = model_of(equal_start()).trades
    summary = rows(trades.summary)
    assert summary["Trades (fills)"] == ("1",) and summary["Buys"] == ("1",) and summary["Sells"] == ("0",)  # T2
    assert summary["Total cost of the trades"] == ("200.00",)
    assert summary["Average cost per trade"] == ("200.00",)
    assert summary["Turnover per year, two-sided"] == ("80.00%",)  # M12: 0.8 over one year
    assert summary["Turnover per year, one-sided"] == ("40.00%",)
    assert summary["Exposure (mean invested share of equity)"] == ("80.00%",)
    assert summary["Share of bars with a position"] == ("80.00%",)
    assert summary["Orders deferred to a later bar"] == ("0",) and summary["Orders unfilled at the end"] == ("0",)
    assert trades.per_symbol.rows == (("A", "1", "1", "0"),)
    assert "deferred_orders" in trades.notes[1]


def test_no_trades_gives_an_average_of_na_and_zero_rows_for_the_universe() -> None:
    trades = model_of(insufficient_warmup()).trades
    summary = rows(trades.summary)
    assert summary["Trades (fills)"] == ("0",)
    assert summary["Average cost per trade"] == ("n/a (no trades)",)
    assert trades.per_symbol.rows == (("A", "0", "0", "0"),)


def test_a_universe_symbol_that_never_traded_is_listed_with_zeros() -> None:
    trades = model_of(benchmark_in_universe()).trades
    assert [row[0] for row in trades.per_symbol.rows] == ["A", "B"]


# --- the alignment and the equity chart caption ---------------------------------------------------


def test_alignment_of_an_equal_start() -> None:
    alignment = model_of(equal_start()).alignment
    table = rows(alignment.table)
    assert table["Common dates"] == ("5",) and table["Compared return observations"] == ("5",)
    assert table["Dates dropped"] == ("no",) and table["Base of the comparison"] == ("initial_equity",)
    assert table["Base date"] == ("n/a",)
    assert alignment.base_rule.startswith("The first common date is the first bar of both runs")
    assert alignment.notes == ()


def test_alignment_of_a_late_benchmark() -> None:
    alignment = model_of(late_benchmark()).alignment
    table = rows(alignment.table)
    assert (table["Bars of the strategy"], table["Bars of the benchmark"], table["Common dates"]) == (
        ("5",),
        ("3",),
        ("3",),
    )
    assert table["Dropped dates of the strategy"] == ("2",) and table["Dates dropped"] == ("yes",)
    assert table["Base of the comparison"] == ("first_common_date",) and table["Base date"] == ("2024-01-04",)
    assert table["First compared date"] == ("2024-01-05",)
    assert "the equity of both runs on 2024-01-04 is the starting point" in alignment.base_rule
    assert alignment.notes[0] == (
        "The benchmark starts later than the strategy: its first bar is 2024-01-04, the first bar of the strategy is "
        "2024-01-02."
    )


def test_alignment_of_insufficient_overlap_and_of_an_early_benchmark() -> None:
    overlap = model_of(insufficient_overlap()).alignment
    assert rows(overlap.table)["Insufficient overlap (relative metrics are n/a)"] == ("yes",)
    assert any("share too few dates" in note for note in overlap.notes)
    assert any("starts earlier" in note for note in model_of(early_benchmark()).alignment.notes)


def test_the_equity_caption_of_an_equal_start() -> None:
    caption = model_of(equal_start()).charts.equity_caption
    assert caption.startswith("Both curves start on 2024-01-02 with the same initial capital (1,000.00)")
    assert "comparable from the first bar" in caption and "not comparable" not in caption
    assert "return of the first bar is measured against the initial equity of each run" in caption


def test_the_equity_caption_of_a_late_benchmark() -> None:
    caption = model_of(late_benchmark()).charts.equity_caption
    assert "The benchmark starts later than the strategy: its first bar is 2024-01-04" in caption
    assert "the first bar of the strategy is 2024-01-02" in caption
    assert "not comparable over the whole chart" in caption and "comparable from the first bar" not in caption
    assert "the equity of both runs on 2024-01-04 is the starting point and that date has no return" in caption


def test_the_equity_caption_of_an_early_benchmark() -> None:
    caption = model_of(early_benchmark()).charts.equity_caption
    assert "The benchmark starts earlier than the strategy: its first bar is 2024-01-02" in caption
    assert "not comparable over the whole chart" in caption


def test_the_chart_series_are_the_net_equity_and_the_drawdown() -> None:
    charts = model_of(equal_start()).charts
    strategy, benchmark = charts.equity.series
    assert strategy.dates == ("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08")
    assert strategy.values == pytest.approx((1000, 880, 968, 1064.8, 1171.28), rel=1e-9)
    assert benchmark.values == pytest.approx((1000, 880, 792, 871.2, 784.08), rel=1e-9)
    assert (strategy.dashed, benchmark.dashed) == (False, True)
    drawdown = charts.drawdown.series[0]
    assert drawdown.values == pytest.approx((0, -0.12, -0.032, 0, 0), abs=1e-9)  # M12: 0, 0, -0.12, -0.032, 0
    assert charts.equity_file == "equity.svg" and charts.drawdown_file == "drawdown.svg"


def test_a_late_benchmark_series_starts_on_its_own_date() -> None:
    strategy, benchmark = model_of(late_benchmark()).charts.equity.series
    assert strategy.dates[0] == "2024-01-02" and benchmark.dates[0] == "2024-01-04"


# --- the heatmap ----------------------------------------------------------------------------------


def series(dates, values) -> pd.Series:
    return pd.Series(values, index=pd.DatetimeIndex(dates))


def test_heatmap_with_a_partial_first_and_last_month() -> None:
    # Dec 2023: two bars of +10% -> 1.1 * 1.1 - 1 = 0.21. Jan 2024: -50% then +100% -> 0.5 * 2 - 1 = 0.
    # Feb 2024: one bar of +5% -> 0.05. The first month (Dec) and the last (Feb) are marked partial.
    returns = series(
        ["2023-12-28", "2023-12-29", "2024-01-02", "2024-01-03", "2024-02-01"], [0.1, 0.1, -0.5, 1.0, 0.05]
    )
    heatmap = heatmap_section(returns)
    assert heatmap.years == (2023, 2024) and heatmap.months[0] == "Jan" and heatmap.months[11] == "Dec"
    row_2023, row_2024 = heatmap.rows
    assert [c.text for c in row_2023] == ["·"] * 11 + ["21.00%*"]
    assert [c.text for c in row_2024] == ["0.00%", "5.00%*"] + ["·"] * 10
    assert [c.partial for c in row_2023] == [False] * 11 + [True]
    assert [c.partial for c in row_2024] == [False, True] + [False] * 10
    assert row_2023[11].value == pytest.approx(0.21, abs=1e-12) and row_2024[0].value == pytest.approx(0.0, abs=1e-12)
    assert row_2023[0].value is None
    assert "first or the last month" in heatmap.footnote


def test_heatmap_of_a_run_inside_one_month_marks_that_month_partial() -> None:
    heatmap = heatmap_section(series(["2024-01-03", "2024-01-04"], [0.1, -0.1]))
    (row,) = heatmap.rows
    assert row[0].text == "-1.00%*" and row[0].partial  # 1.1 * 0.9 - 1 = -0.01
    assert all(c.text == "·" for c in row[1:])


def test_heatmap_skips_nothing_between_years_that_have_bars() -> None:
    returns = series(["2022-12-30", "2024-01-02"], [0.02, 0.03])  # no bar in 2023 at all
    assert heatmap_section(returns).years == (2022, 2024)


# --- the guards -----------------------------------------------------------------------------------


def test_a_table_rejects_an_empty_cell_and_a_ragged_row() -> None:
    Table(("a", "b"), (("1", "2"),))
    with pytest.raises(ValueError, match="empty"):
        Table(("a", "b"), (("1", ""),))
    with pytest.raises(ValueError, match="empty"):
        Table(("a", "b"), (("1", "  "),))
    with pytest.raises(ValueError, match="cells"):
        Table(("a", "b"), (("1",),))


def test_no_model_has_an_empty_cell_or_a_nan_or_none_cell() -> None:
    for kind, evaluation in all_kinds().items():
        for cell in all_cells(model_of(evaluation)):
            assert cell.strip(), kind
            assert cell not in {"nan", "None", "inf", "-inf"}, kind


def test_the_model_refuses_missing_empty_or_shortened_caveats() -> None:
    model = model_of(equal_start())
    assert model.fixed_caveats == fixed_caveats()
    fixed = fixed_caveats()
    with pytest.raises(ValueError, match="fixed caveats"):  # missing
        replace(model, fixed_caveats=())
    with pytest.raises(ValueError, match="fixed caveats"):  # one caveat removed
        replace(model, fixed_caveats=fixed[:-1])
    with pytest.raises(ValueError, match="fixed caveats"):  # empty text
        replace(model, fixed_caveats=(Caveat(fixed[0].title, ""), *fixed[1:]))
    with pytest.raises(ValueError, match="fixed caveats"):  # shortened text
        replace(model, fixed_caveats=(Caveat(fixed[0].title, fixed[0].text[:-1]), *fixed[1:]))
    with pytest.raises(ValueError, match="fixed caveats"):  # changed title
        replace(model, fixed_caveats=(Caveat("Execution!", fixed[0].text), *fixed[1:]))
    with pytest.raises(ValueError, match="fixed caveats"):  # reordered
        replace(model, fixed_caveats=fixed[::-1])


def test_run_caveats_may_be_anything_but_the_fixed_ones_stay() -> None:
    model = model_of(equal_start())
    assert replace(model, run_caveats=()).fixed_caveats == fixed_caveats()
    assert model.run_caveats[0] == "Execution in this run: delay of 1 bar(s), fills at the open."
