"""Strategy spec: Pydantic schema for YAML specs and the signal interface."""

from backtest_agent.spec import builtin_signals  # noqa: F401  (importing it registers the built-in signals)
from backtest_agent.spec.errors import SignalContractError, SpecError, SpecProblem, UnknownSignalError
from backtest_agent.spec.loader import load_spec, parse_spec
from backtest_agent.spec.schema import RiskFlag, StrategySpec
from backtest_agent.spec.signals import (
    SIGNALS,
    Signal,
    SignalParams,
    SignalRegistry,
    get_signal,
    list_signals,
    register_signal,
    validate_signal_output,
)

__all__ = [
    "SIGNALS",
    "RiskFlag",
    "Signal",
    "SignalContractError",
    "SignalParams",
    "SignalRegistry",
    "SpecError",
    "SpecProblem",
    "StrategySpec",
    "UnknownSignalError",
    "get_signal",
    "list_signals",
    "load_spec",
    "parse_spec",
    "register_signal",
    "validate_signal_output",
]
