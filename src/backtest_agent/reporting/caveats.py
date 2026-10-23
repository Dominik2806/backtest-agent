"""The section "Assumptions and caveats" and the explanation of every risk flag (docs/report.md).

``fixed_caveats()`` has no parameter and returns constant text: nothing can switch it off or shorten it, and
``ReportModel`` refuses to exist without exactly this text. ``run_caveats`` adds lines that depend on the run; they
never replace the fixed text. The texts contain no URL (the HTML test relies on that).
"""

from dataclasses import dataclass

from backtest_agent.metrics.evaluation import Evaluation
from backtest_agent.reporting import format as fmt
from backtest_agent.reporting.facts import benchmark_timing


@dataclass(frozen=True)
class Caveat:
    title: str
    text: str


_FIXED = (
    Caveat(
        "Execution",
        "Orders are filled the number of bars after the signal that the spec names (delay_bars, default one "
        "bar) at the open or the close of that bar. A fill on the same bar as the signal can hide look-ahead "
        "bias. The data are daily bars: there is no intraday path, no partial fill and no market impact.",
    ),
    Caveat(
        "Costs",
        "Costs are commission, half-spread and slippage in basis points of the traded value plus an optional minimum "
        "commission, deducted as cash fees. Real costs depend on size, liquidity and time. Costs of zero "
        "overstate what trading would return. The benchmark is charged the same costs. Taxes are not "
        "modelled.",
    ),
    Caveat(
        "Adjusted prices",
        "Prices are adjusted for splits and dividends, and the close is the adjusted close, which is total "
        "return with dividends reinvested. Adjusted prices are not the prices quoted on the day, and the "
        "whole adjusted history changes whenever a new dividend or split is issued. Free data can also be "
        "wrong; the validation warnings of the run are listed in the section Data.",
    ),
    Caveat(
        "Survivorship",
        "The universe is today's constituents unless the spec states otherwise. Securities that were "
        "delisted, merged or dropped from an index are missing, which makes past results look better than "
        "they were.",
    ),
    Caveat(
        "Annualization of short runs",
        "CAGR, volatility, Sharpe, Sortino, Calmar and annualized turnover are scaled from the length of the "
        "run with the bars per year printed in the metrics table. For a run of a year or less they are "
        "strongly extrapolated, and CAGR and Calmar most of all.",
    ),
    Caveat(
        "Partial months",
        "The first and the last calendar month of a run can be partial. Their monthly returns cover fewer "
        "bars than a full month, and the best and worst month can be one of them.",
    ),
    Caveat(
        "Selection bias",
        "This report does not know how many other variants were tried before this one. The more variants are "
        "tried, the more likely a good-looking result is luck.",
    ),
    Caveat(
        "Not investment advice",
        "A backtest is a description of the past under the assumptions above, not a forecast. This project and this "
        "report are educational and are not investment advice.",
    ),
)


def fixed_caveats() -> tuple[Caveat, ...]:
    """The caveats that every report contains, word for word. There is deliberately no parameter."""
    return _FIXED


def run_caveats(evaluation: Evaluation) -> tuple[str, ...]:
    """Caveats that follow from this run (execution rule, flags, short window, benchmark timing)."""
    result, benchmark = evaluation.result, evaluation.benchmark_result
    lines: list[str] = []
    execution = result.spec.execution
    lines.append(
        f"Execution in this run: delay of {execution.delay_bars} bar(s), fills at the {execution.price}"
        + (" (same-bar execution was allowed explicitly)." if execution.delay_bars == 0 else ".")
    )
    codes = sorted({flag.code for flag in result.risk_flags} | {flag.code for flag in benchmark.risk_flags})
    if codes:
        lines.append(
            f"This run carries risk flags ({', '.join(codes)}); read the section Risk flags before the numbers."
        )
    years = evaluation.metrics.years
    periods = evaluation.assumptions.periods_per_year
    if years is not None and years <= 1.0:
        lines.append(
            f"The run covers {evaluation.metrics.n_bars} bars ({fmt.number(years, 'years')} years at {periods} bars a "
            "year): CAGR and Calmar are annualized from a very short window."
        )
    timing = benchmark_timing(evaluation)
    if timing.starts_later:
        lines.append(
            f"The benchmark starts on {timing.benchmark_first.isoformat()}, after the strategy "
            f"({timing.strategy_first.isoformat()}); the comparison covers the common dates only."
        )
    if timing.ends_earlier:
        lines.append(
            f"The benchmark ends on {timing.benchmark_last.isoformat()}, before the strategy "
            f"({timing.strategy_last.isoformat()}); the comparison covers the common dates only."
        )
    if evaluation.relative.alignment.insufficient_overlap:
        lines.append("The strategy and the benchmark share too few dates: the relative metrics are n/a.")
    return tuple(lines)


FLAG_EXPLANATIONS: dict[str, str] = {
    "same_bar_execution": (
        "The strategy trades on the same bar on which its signal is known (delay 0, allowed explicitly in the"
        " spec). A signal built from the close of a bar can only be traded after that close, so a result like"
        " this may contain look-ahead bias and is optimistic until it is re-run with a delay of one bar."
    ),
    "zero_costs": (
        "Every cost number of the spec is zero. Real trading always costs something (commission, spread, "
        "slippage), so the return shown is higher than what could have been earned, and trading more is free "
        "in this run."
    ),
    "costs_not_applied": (
        "The costs written in the spec were not deducted in this run, because it was made with costs switched"
        " off. The result is a cost-free result for the strategy and for the benchmark and overstates what "
        "trading would return."
    ),
    "insufficient_warmup": (
        "At least one symbol had fewer rows of history before the first decision than the signal needs. The first "
        "signals were computed without the full lookback, so the early positions are not what the signal would have "
        "chosen with enough history. The run went on because a short warm-up was allowed."
    ),
}

UNKNOWN_FLAG_EXPLANATION = "This report has no explanation for this flag. Read the message of the engine above."


def explain_flag(code: str) -> str:
    """The plain-language explanation of a risk flag code; a code without one gets a fixed fallback sentence."""
    return FLAG_EXPLANATIONS.get(code, UNKNOWN_FLAG_EXPLANATION)
