"""The history a run needs: the warm-up window and the loading of the data (see docs/engine.md, "Running a spec")."""

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from backtest_agent.data.checks import validate_prices
from backtest_agent.data.errors import DataUnavailableError
from backtest_agent.data.hash import hash_frame
from backtest_agent.data.provider import DataProvider, validate_standard_frame
from backtest_agent.data.validation import ValidationResult
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


@dataclass(frozen=True)
class LoadedHistory:
    """The data of one request of a run: the frame as loaded, its validation result and its hash."""

    window: WarmupWindow
    frame: pd.DataFrame
    validation: ValidationResult
    data_hash: str


def load_history(spec: StrategySpec, provider: DataProvider) -> LoadedHistory:
    """Load the universe of ``spec`` over ``warmup_window(spec).fetch_start`` to ``period.end`` and check the frame.

    Raises ``DataUnavailableError`` for a symbol the provider did not deliver and ``ValueError`` for a frame that is
    not in the standard format or has rows after ``period.end``. Validation errors are returned in ``validation``,
    never raised here (``run_backtest`` raises them). The hash is that of the whole frame, warm-up included.
    """
    window = warmup_window(spec)
    universe = list(spec.universe)
    frame = provider.get_prices(universe, window.fetch_start, spec.period.end)
    delivered = set(frame.columns.get_level_values("symbol"))
    missing = [s for s in universe if s not in delivered]
    if missing:
        raise DataUnavailableError(f"the provider returned no data for {missing}")
    validate_standard_frame(frame, universe)
    if frame.index[-1] > pd.Timestamp(spec.period.end):
        raise ValueError(
            f"the provider returned rows after period.end {spec.period.end} (last: {frame.index[-1].date()})"
        )
    validation = validate_prices(frame, start=window.fetch_start, end=spec.period.end)
    return LoadedHistory(window, frame, validation, hash_frame(frame))
