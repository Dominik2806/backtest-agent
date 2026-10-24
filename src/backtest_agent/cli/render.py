"""What ``bt`` prints on stdout: the only place with output formats (docs/cli.md).

Every number goes through ``reporting.format`` and every free text (names, symbols) through ``reporting.model.text``,
so a value looks the same here as in the report and a hostile name cannot break a line. The labels of the metric rows
are the report's own. The CLI's own words are plain ASCII.
"""

from pathlib import Path

from backtest_agent.journal import CodeVersion, RunRecord, RunSummary
from backtest_agent.reporting import format as fmt
from backtest_agent.reporting.model import text, trial_line
from backtest_agent.spec import StrategySpec

LABEL_WIDTH = 12  # "Risk flags:" plus one space


def line(label: str, value: str) -> str:
    return f"{label + ':':<{LABEL_WIDTH}}{value}"


def period_text(spec: StrategySpec) -> str:
    return f"{fmt.iso_date(spec.period.start, 'period.start')} to {fmt.iso_date(spec.period.end, 'period.end')}"


def codes_text(codes: list[str]) -> str:
    return ", ".join(text(code) for code in codes) or "none"


COSTS_NOT_APPLIED = "NOT applied (the result overstates what trading would return)"
# (label of the report, key of PerformanceMetrics.to_dict(), formatter); the labels are the report's own
KEY_METRICS = (
    ("Total return", "total_return", fmt.percent),
    ("CAGR", "cagr", fmt.percent),
    ("Sharpe ratio", "sharpe", fmt.ratio),
    ("Maximum drawdown", "max_drawdown", fmt.percent),
)


def metric_table(strategy: dict, benchmark: dict, symbol: str) -> list[str]:
    """The key metrics of the strategy next to the benchmark, from two ``PerformanceMetrics.to_dict()`` dictionaries."""
    rows = [("Metric", "Strategy", f"Benchmark ({text(symbol)})")]
    for label, key, render in KEY_METRICS:
        rows.append((label, render(strategy[key], f"strategy.{key}"), render(benchmark[key], f"benchmark.{key}")))
    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    return [f"{a:<{widths[0]}}  {b:>{widths[1]}}  {c:>{widths[2]}}" for a, b, c in rows]


def flags_text(strategy_codes: list[str], benchmark_codes: list[str]) -> str:
    parts = [
        f"{who} run: {codes_text(codes)}"
        for who, codes in (("strategy", strategy_codes), ("benchmark", benchmark_codes))
        if codes
    ]
    return "; ".join(parts) or "none"


def record_lines(record: RunRecord) -> list[str]:
    """The block that ``bt run`` and ``bt journal show`` both print, down to the risk flags, from the stored record."""
    spec, evaluation = record.spec, record.evaluation
    strategy, benchmark = evaluation["strategy"], evaluation["benchmark"]
    first, last = spec["period"]["start"], spec["period"]["end"]
    period = f"{fmt.iso_date(first, 'period.start')} to {fmt.iso_date(last, 'period.end')}"
    bars = fmt.integer(strategy["metrics"]["n_bars"], "n_bars")
    excess = fmt.percent(evaluation["relative"]["excess_return"], "excess_return", signed=True)
    return [
        line("Run", text(record.run_id)),
        line("Strategy", f"{text(spec['name'])} (family {text(record.family)})"),
        line("Trials", trial_line(record.trial)),
        line("Period", f"{period}, {bars} bars"),
        line("Costs", "applied" if strategy["costs_applied"] else COSTS_NOT_APPLIED),
        "",
        *metric_table(strategy["metrics"], benchmark["metrics"], benchmark["symbol"]),
        "",
        f"Excess return (compared window): {excess}",
        "",
        line("Risk flags", flags_text(strategy["risk_flags"], benchmark["risk_flags"])),
    ]


NAME_LIMIT = 40


def plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _short_name(name: str) -> str:
    cleaned = text(name)
    return cleaned if len(cleaned) <= NAME_LIMIT else cleaned[: NAME_LIMIT - 3] + "..."


def journal_lines(runs: tuple[RunSummary, ...], runs_dir: Path, family: str | None) -> list[str]:
    """The table of ``bt journal list``: newest first, one row per run."""
    if not runs:
        of_family = f" of family {text(family)}" if family else ""
        return [f"No runs{of_family} in {runs_dir.as_posix()}."]
    rows = [("RUN ID", "FAMILY", "RUN", "VARIANT", "NEW", "NAME")]
    for run in runs:
        rows.append(
            (
                text(run.run_id),
                text(run.family),
                str(run.run_number),
                str(run.trial_number),
                fmt.yes_no(run.new_variant),
                _short_name(run.strategy_name),
            )
        )
    widths = [max(len(row[i]) for row in rows) for i in range(6)]
    table = ["  ".join(f"{cell:<{widths[i]}}" for i, cell in enumerate(row)).rstrip() for row in rows]
    return [*table, "", f"{plural(len(runs), 'run')} listed"]


def _code_text(code: CodeVersion) -> str:
    state = {True: "has uncommitted changes", False: "clean", None: "state unknown"}[code.dirty]
    return f"{text(code.commit[:12])} ({state})"


def show_lines(record: RunRecord, runs_dir: Path, reports_dir: Path) -> list[str]:
    """The answer of ``bt journal show``: the block of ``bt run`` and the facts only the stored record has."""
    run_id = record.run_id
    evaluation = record.evaluation
    lines = [
        *record_lines(record),
        line("Generated", fmt.utc_timestamp(record.generated_at)),
        line("Code", _code_text(record.code_version)),
        line("Data", f"strategy {text(evaluation['strategy']['data_hash'])}"),
        " " * LABEL_WIDTH + f"benchmark {text(evaluation['benchmark']['data_hash'])}",
        line("Spec", (runs_dir / run_id / "spec.yaml").as_posix()),
        line("Journal", (runs_dir / run_id / "run.json").as_posix()),
    ]
    report = reports_dir / run_id / "report.md"
    if report.is_file():
        lines.append(line("Report", f"{report.as_posix()} and report.html"))
    return lines


def validate_lines(spec: StrategySpec, path: str) -> list[str]:
    """The answer of ``bt validate``: the spec is valid, and the facts a reader checks before running it."""
    return [
        f"OK: {text(path)} is a valid spec",
        line("Name", text(spec.name)),
        line("Family", text(spec.signal.id)),
        line("Universe", ", ".join(text(s) for s in spec.universe)),
        line("Benchmark", text(spec.benchmark)),
        line("Period", period_text(spec)),
        line("Warm-up", f"{fmt.integer(spec.warmup_rows, 'warmup_rows')} rows"),
        line("Risk flags", codes_text([flag.code for flag in spec.risk_flags()])),
    ]
