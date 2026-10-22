"""Engine: deterministic portfolio simulation with execution delay (see docs/engine.md).

The pure simulation (sizing, rebalance schedule, costs, portfolio core) and ``run_backtest``, which loads data
with warm-up, validates and hashes it, runs the signal and returns a ``BacktestResult``.
"""

from backtest_agent.engine.core import Portfolio, simulate
from backtest_agent.engine.costs import BpsCosts, CostModel, NoCosts
from backtest_agent.engine.errors import (
    EngineError,
    EngineInvariantError,
    InsufficientHistoryError,
    InsufficientWarmupWarning,
)
from backtest_agent.engine.result import BacktestResult, WarmupInfo
from backtest_agent.engine.runner import run_backtest
from backtest_agent.engine.schedule import decision_bars, execution_orders
from backtest_agent.engine.simulation import simulate_signals
from backtest_agent.engine.sizing import target_weights

__all__ = [
    "BacktestResult",
    "BpsCosts",
    "CostModel",
    "EngineError",
    "EngineInvariantError",
    "InsufficientHistoryError",
    "InsufficientWarmupWarning",
    "NoCosts",
    "Portfolio",
    "WarmupInfo",
    "decision_bars",
    "execution_orders",
    "run_backtest",
    "simulate",
    "simulate_signals",
    "target_weights",
]
