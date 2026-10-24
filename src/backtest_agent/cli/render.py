"""What ``bt`` prints on stdout: the only place with output formats (docs/cli.md).

Every number goes through ``reporting.format`` and every free text (names, symbols) through ``reporting.model.text``,
so a value looks the same here as in the report and a hostile name cannot break a line. The labels of the metric rows
are the report's own. The CLI's own words are plain ASCII.
"""

from backtest_agent.reporting import format as fmt
from backtest_agent.reporting.model import text
from backtest_agent.spec import StrategySpec

LABEL_WIDTH = 12  # "Risk flags:" plus one space


def line(label: str, value: str) -> str:
    return f"{label + ':':<{LABEL_WIDTH}}{value}"


def period_text(spec: StrategySpec) -> str:
    return f"{fmt.iso_date(spec.period.start, 'period.start')} to {fmt.iso_date(spec.period.end, 'period.end')}"


def codes_text(codes: list[str]) -> str:
    return ", ".join(text(code) for code in codes) or "none"


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
