"""Strategy spec: Pydantic schema for YAML specs and the signal interface."""

from backtest_agent.spec.errors import SignalContractError, SpecError, SpecProblem, UnknownSignalError
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
    "Signal",
    "SignalContractError",
    "SignalParams",
    "SignalRegistry",
    "SpecError",
    "SpecProblem",
    "UnknownSignalError",
    "get_signal",
    "list_signals",
    "register_signal",
    "validate_signal_output",
]
