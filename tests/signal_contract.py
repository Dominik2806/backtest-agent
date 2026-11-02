"""The reusable signal contract for the tests: the checks live in ``backtest_agent.coded.contract`` since Phase 10.

This module re-exports them. ``check_signal_contract`` and ``check_warmup_is_honest`` raise ``AssertionError``
here, as they always did for the tests of this repository; the package raises ``SignalContractError``.
"""

import pandas as pd

from backtest_agent.coded.contract import blank, contract_frames, fake_prices
from backtest_agent.coded.contract import check_signal_contract as _check_signal_contract
from backtest_agent.coded.contract import check_warmup_is_honest as _check_warmup_is_honest
from backtest_agent.spec import Signal, SignalContractError, SignalParams

__all__ = ["blank", "check_signal_contract", "check_warmup_is_honest", "contract_frames", "fake_prices"]


def check_signal_contract(signal: Signal, params: SignalParams, frames: dict[str, pd.DataFrame]) -> None:
    """Purity, determinism, the output rules and an honest warm-up on every frame (``AssertionError`` on failure)."""
    try:
        _check_signal_contract(signal, params, frames)
    except SignalContractError as error:
        raise AssertionError(str(error)) from error


def check_warmup_is_honest(signal: Signal, params: SignalParams, prices: pd.DataFrame) -> None:
    """The declared ``warmup_rows`` is true (``AssertionError`` on failure)."""
    try:
        _check_warmup_is_honest(signal, params, prices)
    except SignalContractError as error:
        raise AssertionError(str(error)) from error
