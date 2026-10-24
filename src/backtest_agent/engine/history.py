"""The history a run needs: the warm-up window (see docs/engine.md, "Running a spec")."""

from dataclasses import dataclass
from datetime import date, timedelta

from backtest_agent.spec.schema import StrategySpec


@dataclass(frozen=True)
class WarmupWindow:
    """How far before ``period.start`` the history of a spec is fetched."""

    required_rows: int
    delay_bars: int
    rows_needed: int
    buffer_days: int
    fetch_start: date


def warmup_window(spec: StrategySpec) -> WarmupWindow:
    """The window of ``spec``: ``rows_needed = warmup_rows + delay_bars``, ``buffer_days = 2 * rows_needed + 14``.

    The history starts ``buffer_days`` calendar days before ``period.start``. The benchmark of a spec has its own
    window (``benchmark_spec(spec)`` has no warm-up).
    """
    required = spec.warmup_rows
    rows_needed = required + spec.execution.delay_bars
    buffer_days = 2 * rows_needed + 14
    return WarmupWindow(
        required_rows=required,
        delay_bars=spec.execution.delay_bars,
        rows_needed=rows_needed,
        buffer_days=buffer_days,
        fetch_start=spec.period.start - timedelta(days=buffer_days),
    )
