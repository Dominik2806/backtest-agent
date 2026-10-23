"""The report model: a pure function of an ``Evaluation`` plus ``run_id`` and ``generated_at`` (docs/report.md).

All decisions about what is shown and how it looks (n/a, number formats, explanations of flags, the sentences about the
benchmark comparison) are made here. The renderers only read this model and escape the text for their format; the
writer only does file I/O. Nothing here reads a clock, a locale, the environment or the file system.

Numbers come from the existing result and metrics objects; nothing is recomputed except the arrangement of the monthly
returns into a year-by-month grid. Text that comes from the spec or the data is kept as it is (not escaped) in the
model.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from backtest_agent.data.validation import ValidationResult
from backtest_agent.engine.result import BacktestResult
from backtest_agent.metrics.evaluation import Evaluation
from backtest_agent.metrics.performance import PerformanceMetrics, drawdown_path, monthly_returns
from backtest_agent.metrics.relative import Alignment
from backtest_agent.metrics.trades import trade_statistics
from backtest_agent.reporting import format as fmt
from backtest_agent.reporting.caveats import Caveat, explain_flag, fixed_caveats, run_caveats
from backtest_agent.reporting.facts import BenchmarkTiming, benchmark_timing

EQUITY_FILE = "equity.svg"
DRAWDOWN_FILE = "drawdown.svg"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
OUTSIDE_RUN = "·"  # a month before the first or after the last bar of the run
STRATEGY, BENCHMARK = "Strategy", "Benchmark"


_XML_ILLEGAL = re.compile(
    r"[\x00-\x08\x0e-\x1b\ud800-\udfff\ufffe\uffff]"
)  # what XML 1.0 forbids and \s does not match


def text(value: Any) -> str:
    """Spec or data text for display: characters that XML 1.0 forbids (such as NUL) become U+FFFD, whitespace is
    collapsed to single spaces, ``(none)`` if nothing is left.

    The replacement is here, once, so that the Markdown, the HTML and the standalone SVG files are all well-formed.
    """
    collapsed = re.sub(r"\s+", " ", str(value)).strip()  # also turns \x0b, \x0c and \x1c-\x1f into spaces
    return _XML_ILLEGAL.sub("\ufffd", collapsed) or "(none)"


@dataclass(frozen=True)
class Table:
    """A table of display strings. Every row has one cell per header and no cell is empty."""

    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def __post_init__(self) -> None:
        for row in self.rows:
            if len(row) != len(self.headers):
                raise ValueError(f"a row has {len(row)} cells for {len(self.headers)} headers: {row!r}")
            if any(not isinstance(cell, str) or not cell.strip() for cell in row):
                raise ValueError(f"a table cell is empty: {row!r}")


@dataclass(frozen=True)
class HeaderSection:
    strategy_name: str
    run_id: str
    generated_at: str
    period: str
    bars: str
    universe: str
    benchmark: str


@dataclass(frozen=True)
class IssueRow:
    severity: str
    code: str
    symbol: str
    field: str
    count: str
    first_dates: str
    message: str


@dataclass(frozen=True)
class DataRun:
    """The data of one run: its hash and its validation findings (errors cannot exist: they stop the run)."""

    label: str
    symbols: str
    data_hash: str
    summary: str
    issues: tuple[IssueRow, ...]


@dataclass(frozen=True)
class DataSection:
    runs: tuple[DataRun, ...]
    warmup: Table
    warmup_symbols: Table
    benchmark_warmup: str


@dataclass(frozen=True)
class FlagRow:
    run: str
    code: str
    message: str
    explanation: str


@dataclass(frozen=True)
class MetricsSection:
    assumptions: Table
    performance: Table  # Metric | Strategy | Benchmark
    relative: Table  # Metric | Value


@dataclass(frozen=True)
class AlignmentSection:
    table: Table
    base_rule: str
    notes: tuple[str, ...]


@dataclass(frozen=True)
class CostsSection:
    table: Table  # Item | Strategy | Benchmark
    notes: tuple[str, ...]


@dataclass(frozen=True)
class ChartSeries:
    label: str
    dates: tuple[str, ...]  # ISO dates
    values: tuple[float, ...]
    dashed: bool = False


@dataclass(frozen=True)
class LineChart:
    title: str
    kind: str  # "equity" (values in account currency) or "drawdown" (fractions, 0 or below)
    description: str
    series: tuple[ChartSeries, ...]


@dataclass(frozen=True)
class ChartsSection:
    equity: LineChart
    equity_file: str
    equity_caption: str
    drawdown: LineChart
    drawdown_file: str
    drawdown_caption: str


@dataclass(frozen=True)
class HeatmapCell:
    text: str  # shown in every format, so the grid is readable without colour
    value: float | None  # None outside the run
    partial: bool  # first or last month of the run


@dataclass(frozen=True)
class HeatmapSection:
    months: tuple[str, ...]
    years: tuple[int, ...]
    rows: tuple[tuple[HeatmapCell, ...], ...]  # one row per year, 12 cells each
    footnote: str


@dataclass(frozen=True)
class TradesSection:
    summary: Table
    per_symbol: Table
    notes: tuple[str, ...]


@dataclass(frozen=True)
class ReportModel:
    """Everything a report shows, in the order it is shown. Frozen display data; renderers add no content.

    The caveats are checked here: a model whose ``fixed_caveats`` differ in any way from ``fixed_caveats()`` (missing,
    empty or shortened text included) cannot be created, so no renderer or writer can drop them.
    """

    header: HeaderSection
    spec: Table
    data: DataSection
    flags: tuple[FlagRow, ...]
    metrics: MetricsSection
    alignment: AlignmentSection
    costs: CostsSection
    charts: ChartsSection
    heatmap: HeatmapSection
    trades: TradesSection
    fixed_caveats: tuple[Caveat, ...]
    run_caveats: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.fixed_caveats != fixed_caveats():
            raise ValueError("the fixed caveats of a report must be exactly the text of fixed_caveats()")


# --- builders ---------------------------------------------------------------------------------------------------------


def _param(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return format(value, ".10g")
    return text(value)


def _spec_table(result: BacktestResult) -> Table:
    spec = result.spec
    params = ", ".join(f"{key}={_param(value)}" for key, value in sorted(spec.signal.params.items()))
    execution = spec.execution
    sizing = spec.sizing.method + (
        f" (fraction {fmt.number(spec.sizing.fraction, 'sizing.fraction')})" if spec.sizing.fraction else ""
    )
    costs = spec.costs
    rows = (
        ("Name", text(spec.name)),
        ("Description", text(spec.description)),
        ("Universe", ", ".join(text(s) for s in spec.universe)),
        (
            "Period",
            f"{fmt.iso_date(spec.period.start, 'period.start')} to {fmt.iso_date(spec.period.end, 'period.end')}",
        ),
        ("Data provider", text(spec.data.provider)),
        ("Signal", text(spec.signal.id)),
        ("Signal parameters", params or "(none)"),
        ("Warm-up rows required", fmt.integer(result.warmup.required_rows, "warmup_rows")),
        ("Rebalance", text(spec.rebalance)),
        ("Sizing", text(sizing)),
        ("Execution delay (bars)", fmt.integer(execution.delay_bars, "execution.delay_bars")),
        ("Execution price", text(execution.price)),
        ("Same-bar execution allowed", fmt.yes_no(execution.allow_same_bar_execution)),
        ("Initial capital", fmt.money(spec.initial_capital, "initial_capital")),
        ("Commission", fmt.bps(costs.commission_bps, "costs.commission_bps")),
        ("Spread", fmt.bps(costs.spread_bps, "costs.spread_bps")),
        ("Slippage", fmt.bps(costs.slippage_bps, "costs.slippage_bps")),
        ("Minimum commission per trade", fmt.money(costs.min_commission, "costs.min_commission")),
        ("Benchmark", text(spec.benchmark)),
    )
    return Table(("Item", "Value"), rows)


def _header(evaluation: Evaluation, run_id: str, generated_at: datetime) -> HeaderSection:
    result = evaluation.result
    spec = result.spec
    first, last = result.equity.index[0].date(), result.equity.index[-1].date()
    return HeaderSection(
        strategy_name=text(spec.name),
        run_id=text(run_id),
        generated_at=fmt.utc_timestamp(generated_at),
        period=f"{fmt.iso_date(spec.period.start, 'period.start')} to {fmt.iso_date(spec.period.end, 'period.end')}",
        bars=f"{fmt.integer(len(result.equity), 'bars')} bars, first bar {fmt.iso_date(first, 'first bar')}, "
        f"last bar {fmt.iso_date(last, 'last bar')}",
        universe=", ".join(text(s) for s in spec.universe),
        benchmark=text(spec.benchmark),
    )


def _data_run(label: str, result: BacktestResult) -> DataRun:
    validation: ValidationResult = result.validation
    counts = ", ".join(
        f"{n} {word if n == 1 else word + 's'}"
        for n, word in (
            (len(validation.errors), "error"),
            (len(validation.warnings), "warning"),
            (len(validation.infos), "info"),
        )
    )
    issues = tuple(
        IssueRow(
            severity=issue.severity.value,
            code=text(issue.code),
            symbol=text(issue.symbol) if issue.symbol else "all",
            field=text(issue.field) if issue.field else "all",
            count=fmt.integer(issue.count, "issue.count"),
            first_dates=", ".join(fmt.iso_date(d, "issue.first_dates") for d in issue.first_dates) or "n/a",
            message=text(issue.message),
        )
        for issue in validation.issues
    )
    return DataRun(
        label=label,
        symbols=", ".join(text(s) for s in result.spec.universe),
        data_hash=text(result.data_hash),
        summary=counts,
        issues=issues,
    )


def _data_section(evaluation: Evaluation) -> DataSection:
    result, benchmark = evaluation.result, evaluation.benchmark_result
    warmup = result.warmup
    table = Table(
        ("Item", "Value"),
        (
            ("Warm-up rows required by the signal", fmt.integer(warmup.required_rows, "warmup.required_rows")),
            ("Execution delay (bars)", fmt.integer(warmup.delay_bars, "warmup.delay_bars")),
            ("Rows needed before the first bar", fmt.integer(warmup.rows_needed, "warmup.rows_needed")),
            ("History loaded from", fmt.iso_date(warmup.fetch_start, "warmup.fetch_start")),
            ("First bar of the run", fmt.iso_date(warmup.first_bar, "warmup.first_bar")),
            ("First decision date", fmt.iso_date(warmup.first_decision_date, "warmup.first_decision_date")),
            ("Warm-up sufficient", fmt.yes_no(warmup.sufficient)),
            ("Symbols with too little history", ", ".join(text(s) for s in warmup.short_symbols) or "none"),
        ),
    )
    symbols = Table(
        ("Symbol", "Rows before the first decision", "First data date", "Target weight of the first decision"),
        tuple(
            (
                text(symbol),
                fmt.integer(warmup.rows_before[symbol], "warmup.rows_before"),
                fmt.iso_date(warmup.first_data[symbol], "warmup.first_data"),
                fmt.percent(warmup.initial_target_weights[symbol], "warmup.initial_target_weights"),
            )
            for symbol in warmup.rows_before
        ),
    )
    bench = benchmark.warmup
    benchmark_warmup = (
        f"Benchmark {text(benchmark.spec.universe[0])}: "
        f"{fmt.integer(bench.required_rows, 'benchmark warm-up rows')} warm-up rows required, "
        f"warm-up sufficient: {fmt.yes_no(bench.sufficient)}, "
        f"first bar {fmt.iso_date(bench.first_bar, 'benchmark first bar')}."
    )
    return DataSection(
        runs=(_data_run("Strategy run", result), _data_run("Benchmark run", benchmark)),
        warmup=table,
        warmup_symbols=symbols,
        benchmark_warmup=benchmark_warmup,
    )


def _flags(evaluation: Evaluation) -> tuple[FlagRow, ...]:
    rows = []
    for label, result in (("Strategy run", evaluation.result), ("Benchmark run", evaluation.benchmark_result)):
        for flag in result.risk_flags:
            rows.append(FlagRow(label, text(flag.code), text(flag.message), explain_flag(flag.code)))
    return tuple(rows)


def _longest(metrics: PerformanceMetrics) -> str:
    if metrics.longest_drawdown_bars is None or metrics.longest_drawdown_days is None:
        return fmt.na()
    return (
        f"{fmt.integer(metrics.longest_drawdown_bars, 'longest_drawdown_bars')} bars / "
        f"{fmt.integer(metrics.longest_drawdown_days, 'longest_drawdown_days')} days"
    )


def _month(value: float | None, label: str | None, field: str) -> str:
    if value is None:
        return fmt.na()
    return f"{fmt.percent(value, field)} ({text(label)})"


def _metrics_section(evaluation: Evaluation) -> MetricsSection:
    s, b, rel = evaluation.metrics, evaluation.benchmark_metrics, evaluation.relative
    assumptions = Table(
        ("Assumption", "Value"),
        (
            (
                "Bars per year (periods_per_year)",
                fmt.integer(evaluation.assumptions.periods_per_year, "periods_per_year"),
            ),
            ("Risk-free rate (annual)", fmt.percent(evaluation.assumptions.risk_free_rate, "risk_free_rate")),
        ),
    )

    def row(label: str, render) -> tuple[str, str, str]:
        return (label, render(s, "strategy"), render(b, "benchmark"))

    def pct(attr: str):
        return lambda m, who: fmt.percent(getattr(m, attr), f"{who}.{attr}")

    def rat(attr: str):
        return lambda m, who: fmt.ratio(getattr(m, attr), f"{who}.{attr}")

    performance = Table(
        ("Metric", STRATEGY, BENCHMARK),
        (
            row("Total return", pct("total_return")),
            row("CAGR", pct("cagr")),
            row("Volatility (annualized)", pct("volatility")),
            row("Sharpe ratio", rat("sharpe")),
            row("Sortino ratio", rat("sortino")),
            row("Maximum drawdown", pct("max_drawdown")),
            row("Current drawdown", pct("current_drawdown")),
            row("Longest drawdown", lambda m, who: _longest(m)),
            row("Calmar ratio", rat("calmar")),
            row("Hit rate (share of bars with a gain)", pct("hit_rate")),
            row("Best month", lambda m, who: _month(m.best_month, m.best_month_label, f"{who}.best_month")),
            row("Worst month", lambda m, who: _month(m.worst_month, m.worst_month_label, f"{who}.worst_month")),
            row("Bars", lambda m, who: fmt.integer(m.n_bars, f"{who}.n_bars")),
            row("Years", lambda m, who: fmt.number(m.years, f"{who}.years")),
        ),
    )
    relative = Table(
        ("Metric", "Value"),
        (
            ("Excess return (compared window)", fmt.percent(rel.excess_return, "excess_return", signed=True)),
            ("Tracking error (annualized)", fmt.percent(rel.tracking_error, "tracking_error")),
            ("Information ratio", fmt.ratio(rel.information_ratio, "information_ratio")),
            (
                "Strategy return over the compared window",
                fmt.percent(rel.strategy_return_compared, "strategy_return_compared"),
            ),
            (
                "Benchmark return over the compared window",
                fmt.percent(rel.benchmark_return_compared, "benchmark_return_compared"),
            ),
        ),
    )
    return MetricsSection(assumptions, performance, relative)


def base_rule_text(alignment: Alignment) -> str:
    """The rule that fixed the starting point of the comparison, in words (docs/metrics.md, "Alignment")."""
    if alignment.base == "initial_equity":
        return (
            "The first common date is the first bar of both runs, so the return of the first bar is measured against "
            "the initial equity of each run."
        )
    if alignment.base_date is None:
        return "The two runs share no date, so there is no starting point and no relative metric."
    return (
        f"The first common date is not the first bar of both runs, so the equity of both runs on "
        f"{fmt.iso_date(alignment.base_date, 'base_date')} is the starting point and that date has no return."
    )


def _timing_notes(timing: BenchmarkTiming) -> list[str]:
    notes = []
    if timing.starts_later:
        notes.append(
            f"The benchmark starts later than the strategy: its first bar is {timing.benchmark_first.isoformat()}, the "
            f"first bar of the strategy is {timing.strategy_first.isoformat()}."
        )
    if timing.starts_earlier:
        notes.append(
            f"The benchmark starts earlier than the strategy: its first bar is "
            f"{timing.benchmark_first.isoformat()}, the "
            f"first bar of the strategy is {timing.strategy_first.isoformat()}."
        )
    if timing.ends_earlier:
        notes.append(
            f"The benchmark ends earlier than the strategy: its last bar is {timing.benchmark_last.isoformat()}, the "
            f"last bar of the strategy is {timing.strategy_last.isoformat()}."
        )
    if timing.ends_later:
        notes.append(
            f"The benchmark ends later than the strategy: its last bar is {timing.benchmark_last.isoformat()}, the "
            f"last bar of the strategy is {timing.strategy_last.isoformat()}."
        )
    return notes


def _alignment_section(evaluation: Evaluation) -> AlignmentSection:
    al = evaluation.relative.alignment
    table = Table(
        ("Item", "Value"),
        (
            ("Bars of the strategy", fmt.integer(al.n_strategy_bars, "n_strategy_bars")),
            ("Bars of the benchmark", fmt.integer(al.n_benchmark_bars, "n_benchmark_bars")),
            ("Common dates", fmt.integer(al.n_common, "n_common")),
            ("Compared return observations", fmt.integer(al.n_compared, "n_compared")),
            ("Dropped dates of the strategy", fmt.integer(al.n_dropped_strategy, "n_dropped_strategy")),
            ("Dropped dates of the benchmark", fmt.integer(al.n_dropped_benchmark, "n_dropped_benchmark")),
            ("Dates dropped", fmt.yes_no(al.dates_dropped)),
            ("Insufficient overlap (relative metrics are n/a)", fmt.yes_no(al.insufficient_overlap)),
            ("Base of the comparison", text(al.base)),
            ("Base date", fmt.iso_date(al.base_date, "base_date")),
            ("First compared date", fmt.iso_date(al.first_compared_date, "first_compared_date")),
            ("Last compared date", fmt.iso_date(al.last_compared_date, "last_compared_date")),
        ),
    )
    notes = _timing_notes(benchmark_timing(evaluation))
    if al.insufficient_overlap:
        notes.append(
            "The strategy and the benchmark share too few dates, so excess return, tracking error and "
            "information ratio are n/a."
        )
    if al.dates_dropped:
        notes.append(
            "Dates that only one of the two runs has are counted above and left out of the comparison; "
            "nothing is dropped silently."
        )
    return AlignmentSection(table, base_rule_text(al), tuple(notes))


def _cost_share(result: BacktestResult, field: str) -> str:
    share = result.cost_share
    if share is None:
        return fmt.na("gross return is not positive")
    return fmt.percent(share, field)


def _costs_section(evaluation: Evaluation) -> CostsSection:
    s, b = evaluation.result, evaluation.benchmark_result

    def both(label: str, render) -> tuple[str, str, str]:
        return (label, render(s, "strategy"), render(b, "benchmark"))

    table = Table(
        ("Item", STRATEGY, BENCHMARK),
        (
            both("Costs applied", lambda r, who: fmt.yes_no(r.costs_applied)),
            both("Total costs", lambda r, who: fmt.money(r.total_costs, f"{who}.total_costs")),
            both(
                "Final equity, net of costs", lambda r, who: fmt.money(float(r.equity.iloc[-1]), f"{who}.final_equity")
            ),
            both(
                "Final equity, without costs (gross)",
                lambda r, who: fmt.money(r.gross_final_equity, f"{who}.gross_final_equity"),
            ),
            both("Net return", lambda r, who: fmt.percent(r.net_return, f"{who}.net_return")),
            both("Gross return", lambda r, who: fmt.percent(r.gross_return, f"{who}.gross_return")),
            both(
                "Cost drag (gross return minus net return)", lambda r, who: fmt.percent(r.cost_drag, f"{who}.cost_drag")
            ),
            both(
                "Cost share (share of the gross return the costs ate)",
                lambda r, who: _cost_share(r, f"{who}.cost_share"),
            ),
        ),
    )
    notes = [
        "The cost share is n/a when the gross return is not positive. It can be negative or above 100%, because costs "
        "change the path of the portfolio (a fee can block a bad purchase).",
    ]
    if not s.costs_applied:
        notes.insert(0, "Costs were not applied in this run: the figures above are cost-free for both runs.")
    return CostsSection(table, tuple(notes))


def _chart_series(label: str, result: BacktestResult, kind: str, dashed: bool) -> ChartSeries:
    dates = tuple(ts.date().isoformat() for ts in result.equity.index)
    if kind == "equity":
        values = tuple(float(v) for v in result.equity)
    else:  # point 0 of the drawdown path is the initial equity, which has no bar of its own
        values = tuple(float(v) for v in drawdown_path(result.returns)[1:])
    return ChartSeries(label, dates, values, dashed)


def _equity_caption(evaluation: Evaluation) -> str:
    timing = benchmark_timing(evaluation)
    capital = fmt.money(evaluation.result.spec.initial_capital, "initial_capital")
    al = evaluation.relative.alignment
    if timing.same_start:
        return (
            f"Both curves start on {timing.strategy_first.isoformat()} with the same initial capital "
            f"({capital}), so they "
            f"are comparable from the first bar. {base_rule_text(al)}"
        )
    which = "later" if timing.starts_later else "earlier"
    return (
        f"The benchmark starts {which} than the strategy: its first bar is "
        f"{timing.benchmark_first.isoformat()}, the first "
        f"bar of the strategy is {timing.strategy_first.isoformat()}. Both curves start with the same initial capital "
        f"({capital}) but on their own first date, so they are not comparable over the whole chart. "
        f"{base_rule_text(al)}"
    )


def _charts_section(evaluation: Evaluation) -> ChartsSection:
    s, b = evaluation.result, evaluation.benchmark_result
    name, bench = text(s.spec.name), text(s.spec.benchmark)
    first, last = s.equity.index[0].date().isoformat(), s.equity.index[-1].date().isoformat()
    equity = LineChart(
        title="Equity: strategy and benchmark",
        kind="equity",
        description=(
            f"Equity of {name} (solid) and of the benchmark {bench} (dashed), net of costs, {first} to {last}. "
            f"The strategy ends at {fmt.money(float(s.equity.iloc[-1]), 'final equity')}, the benchmark at "
            f"{fmt.money(float(b.equity.iloc[-1]), 'benchmark final equity')}."
        ),
        series=(_chart_series(name, s, "equity", False), _chart_series(f"Benchmark {bench}", b, "equity", True)),
    )
    drawdown = LineChart(
        title="Drawdown: strategy and benchmark",
        kind="drawdown",
        description=(
            f"Drawdown from the highest equity so far of {name} (solid) and of the benchmark {bench} (dashed), "
            f"{first} to {last}. The deepest drawdown of the strategy is "
            f"{fmt.percent(evaluation.metrics.max_drawdown, 'max_drawdown')}, of the benchmark "
            f"{fmt.percent(evaluation.benchmark_metrics.max_drawdown, 'benchmark max_drawdown')}."
        ),
        series=(_chart_series(name, s, "drawdown", False), _chart_series(f"Benchmark {bench}", b, "drawdown", True)),
    )
    return ChartsSection(
        equity=equity,
        equity_file=EQUITY_FILE,
        equity_caption=_equity_caption(evaluation),
        drawdown=drawdown,
        drawdown_file=DRAWDOWN_FILE,
        drawdown_caption=(
            "Drawdown is the fall from the highest equity reached so far, the initial capital included. The "
            "benchmark is "
            "drawn on its own dates."
        ),
    )


def heatmap_section(returns: pd.Series) -> HeatmapSection:
    """Monthly returns of ``returns`` as a year-by-month grid; the first and last month of the run are marked partial.

    The returns per month come from ``monthly_returns``; this only arranges them.
    """
    months = monthly_returns(returns)
    first, last = months.index[0], months.index[-1]
    years = sorted({period.year for period in months.index})
    rows = []
    for year in years:
        cells = []
        for number in range(1, 13):
            period = pd.Period(year=year, month=number, freq="M")
            if period not in months.index:
                cells.append(HeatmapCell(OUTSIDE_RUN, None, False))
                continue
            value = float(months.loc[period])
            partial = period in (first, last)
            cells.append(
                HeatmapCell(fmt.percent(value, f"monthly return {period}") + ("*" if partial else ""), value, partial)
            )
        rows.append(tuple(cells))
    return HeatmapSection(
        months=MONTHS,
        years=tuple(years),
        rows=tuple(rows),
        footnote=(
            "* the first or the last month of the run, which can be partial. "
            f"{OUTSIDE_RUN} a month outside the run. Returns are compounded from the net returns of the bars."
        ),
    )


def _trades_section(evaluation: Evaluation) -> TradesSection:
    result, metrics = evaluation.result, evaluation.metrics
    stats = trade_statistics(result.trades)
    summary = Table(
        ("Item", "Value"),
        (
            ("Trades (fills)", fmt.integer(stats.n_trades, "n_trades")),
            ("Buys", fmt.integer(stats.n_buys, "n_buys")),
            ("Sells", fmt.integer(stats.n_sells, "n_sells")),
            ("Total cost of the trades", fmt.money(stats.total_cost, "trade total_cost")),
            (
                "Average cost per trade",
                fmt.money(stats.average_cost_per_trade, "average_cost_per_trade")
                if stats.average_cost_per_trade is not None
                else fmt.na("no trades"),
            ),
            (
                "Turnover per year, two-sided",
                fmt.percent(metrics.turnover_two_sided_annual, "turnover_two_sided_annual"),
            ),
            (
                "Turnover per year, one-sided",
                fmt.percent(metrics.turnover_one_sided_annual, "turnover_one_sided_annual"),
            ),
            ("Exposure (mean invested share of equity)", fmt.percent(metrics.exposure_mean, "exposure_mean")),
            ("Share of bars with a position", fmt.percent(metrics.exposure_invested_share, "exposure_invested_share")),
            ("Orders deferred to a later bar", fmt.integer(result.deferred_orders, "deferred_orders")),
            ("Orders unfilled at the end", fmt.integer(result.unfilled_orders, "unfilled_orders")),
        ),
    )
    symbols = [*result.spec.universe, *sorted(set(stats.per_symbol) - set(result.spec.universe))]
    per_symbol = Table(
        ("Symbol", "Trades", "Buys", "Sells"),
        tuple(
            (
                text(symbol),
                fmt.integer(stats.per_symbol[symbol].trades if symbol in stats.per_symbol else 0, "trades"),
                fmt.integer(stats.per_symbol[symbol].buys if symbol in stats.per_symbol else 0, "buys"),
                fmt.integer(stats.per_symbol[symbol].sells if symbol in stats.per_symbol else 0, "sells"),
            )
            for symbol in symbols
        ),
    )
    notes = (
        "A trade is one fill: one symbol on one bar. Turnover is two-sided (buying the whole portfolio from cash "
        "is 100%).",
        "Deferred and unfilled orders are fields of the backtest result (deferred_orders, unfilled_orders), not trade "
        "statistics: an order is deferred when its symbol has no price on the bar or cash is short, and unfilled if it "
        "is still open after the last bar.",
    )
    return TradesSection(summary, per_symbol, notes)


def build_report_model(evaluation: Evaluation, *, run_id: str, generated_at: datetime) -> ReportModel:
    """The model of one report. ``generated_at`` must be timezone-aware; it is the only time in the report."""
    return ReportModel(
        header=_header(evaluation, run_id, generated_at),
        spec=_spec_table(evaluation.result),
        data=_data_section(evaluation),
        flags=_flags(evaluation),
        metrics=_metrics_section(evaluation),
        alignment=_alignment_section(evaluation),
        costs=_costs_section(evaluation),
        charts=_charts_section(evaluation),
        heatmap=heatmap_section(evaluation.result.returns),
        trades=_trades_section(evaluation),
        fixed_caveats=fixed_caveats(),
        run_caveats=run_caveats(evaluation),
    )
