"""Signals to portfolio path: sizing, rebalance schedule, delay shift and the core in one call."""

import pandas as pd

from backtest_agent.engine.core import Portfolio, simulate
from backtest_agent.engine.costs import CostModel
from backtest_agent.engine.errors import EngineError
from backtest_agent.engine.schedule import decision_bars, execution_orders
from backtest_agent.engine.sizing import target_weights
from backtest_agent.spec.schema import ExecutionSpec, SizingSpec


def simulate_signals(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    signals: pd.DataFrame,
    sizing: SizingSpec,
    execution: ExecutionSpec,
    rebalance: str,
    initial_capital: float,
    first_bar: pd.Timestamp,
    cost_model: CostModel | None = None,
) -> Portfolio:
    """Run a strategy given as a signal frame over the full timeline and return the path from ``first_bar`` on.

    ``opens``, ``closes`` and ``signals`` cover the same bars (warm-up bars before ``first_bar`` included) and the
    same symbols. Decisions on warm-up bars may execute on or after the first bar; nothing is traded or valued
    before it (see docs/engine.md).
    """
    for name, frame in (("opens", opens), ("signals", signals)):
        if not frame.index.equals(closes.index) or not frame.columns.equals(closes.columns):
            raise EngineError(f"{name} must have the same bars and symbols as closes")
    first_pos = int(closes.index.searchsorted(pd.Timestamp(first_bar)))
    if first_pos >= len(closes):
        raise EngineError(f"there is no bar on or after {pd.Timestamp(first_bar).date()}")

    targets = target_weights(signals, sizing)
    decisions = decision_bars(closes.index, rebalance, targets)
    execution_targets, executes = execution_orders(targets, decisions, execution.delay_bars, first_pos)
    return simulate(
        opens.iloc[first_pos:],
        closes.iloc[first_pos:],
        execution_targets.iloc[first_pos:],
        executes.iloc[first_pos:],
        initial_capital,
        execution.price,
        cost_model,
    )
