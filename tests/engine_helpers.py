"""Helpers for engine tests: tiny literal worlds. They build inputs only; no expected value is computed here."""

import numpy as np
import pandas as pd

from backtest_agent.engine import CostModel, Portfolio, simulate_signals
from backtest_agent.spec.schema import ExecutionSpec, SizingSpec

NAN = float("nan")


def frame(values: dict[str, list[float]], start: str = "2024-01-02") -> pd.DataFrame:
    """A frame with a business-day ``date`` index from ``start`` and one column per symbol (``symbol``)."""
    rows = len(next(iter(values.values())))
    index = pd.bdate_range(start, periods=rows).astype("datetime64[ns]").rename("date")
    result = pd.DataFrame({symbol: np.array(v, dtype="float64") for symbol, v in values.items()}, index=index)
    result.columns = result.columns.rename("symbol")
    return result


def run(
    opens: dict[str, list[float]],
    closes: dict[str, list[float]],
    signals: dict[str, list[float]],
    *,
    start: str = "2024-01-02",
    first_bar: str | None = None,
    rebalance: str = "on_signal",
    delay_bars: int = 1,
    price: str = "open",
    method: str = "equal_weight",
    fraction: float | None = None,
    capital: float = 1000.0,
    cost_model: CostModel | None = None,
) -> Portfolio:
    """Run ``simulate_signals`` on literal frames. ``first_bar`` defaults to the first bar of the frames."""
    open_frame, close_frame, signal_frame = frame(opens, start), frame(closes, start), frame(signals, start)
    return simulate_signals(
        open_frame,
        close_frame,
        signal_frame,
        SizingSpec(method=method, fraction=fraction),
        ExecutionSpec(delay_bars=delay_bars, price=price, allow_same_bar_execution=delay_bars == 0),
        rebalance,
        capital,
        pd.Timestamp(first_bar or start),
        cost_model,
    )
