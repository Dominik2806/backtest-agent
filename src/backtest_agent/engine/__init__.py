"""Engine: deterministic portfolio simulation with execution delay (see docs/engine.md).

Part 1 of Phase 4 is the pure simulation: sizing, rebalance schedule, cost hook and the portfolio core.
"""

from backtest_agent.engine.core import Portfolio, simulate
from backtest_agent.engine.costs import CostModel, NoCosts
from backtest_agent.engine.errors import EngineError, EngineInvariantError
from backtest_agent.engine.schedule import decision_bars, execution_orders
from backtest_agent.engine.simulation import simulate_signals
from backtest_agent.engine.sizing import target_weights

__all__ = [
    "CostModel",
    "EngineError",
    "EngineInvariantError",
    "NoCosts",
    "Portfolio",
    "decision_bars",
    "execution_orders",
    "simulate",
    "simulate_signals",
    "target_weights",
]
