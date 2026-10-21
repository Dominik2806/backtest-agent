"""Built-in signals: sma_crossover, momentum_12_1 and buy_and_hold (see docs/strategy-spec.md).

All three follow the signal contract: they work on each symbol's own trading rows, are 0.0 during warm-up, carry
their value over the symbol's non-trading days and use only data up to and including the date.
"""

import pandas as pd
from pydantic import Field, ValidationInfo, field_validator

from backtest_agent.spec.signals import (
    SignalParams,
    carry_forward,
    close_frame,
    per_symbol_signal,
    register_signal,
)


class SmaCrossoverParams(SignalParams):
    """Windows of the two simple moving averages, counted in trading rows of each symbol."""

    fast: int = Field(50, ge=1, description="window of the fast average")
    slow: int = Field(200, ge=2, description="window of the slow average, larger than fast")

    @field_validator("slow")
    @classmethod
    def _slow_above_fast(cls, slow: int, info: ValidationInfo) -> int:
        fast = info.data.get("fast")
        if fast is not None and fast >= slow:
            raise ValueError(f"slow must be larger than fast (fast={fast}, slow={slow})")
        return slow

    def warmup_rows(self) -> int:
        return self.slow - 1  # the slow average of a row needs the row itself and slow - 1 rows before it


@register_signal("sma_crossover", params=SmaCrossoverParams)
def sma_crossover(prices: pd.DataFrame, params: SmaCrossoverParams) -> pd.DataFrame:
    """1.0 while the fast moving average of the close is above the slow one, else 0.0."""

    def compute(close: pd.Series) -> pd.Series:
        fast = close.rolling(params.fast, min_periods=params.fast).mean()
        slow = close.rolling(params.slow, min_periods=params.slow).mean()
        return (fast > slow).astype("float64").where(slow.notna())  # NaN while the slow average is undefined

    return per_symbol_signal(prices, compute)


class Momentum121Params(SignalParams):
    """Lookback and skip in trading rows (12 months is about 252 rows, 1 month about 21), and how many to hold."""

    lookback_days: int = Field(252, ge=1, description="rows back to the start price of the return")
    skip_days: int = Field(21, ge=0, description="most recent rows left out of the return, smaller than lookback")
    top_n: int = Field(3, ge=1, description="number of symbols to hold")
    positive_only: bool = Field(False, description="hold a symbol only if its return is above 0")

    @field_validator("skip_days")
    @classmethod
    def _skip_below_lookback(cls, skip_days: int, info: ValidationInfo) -> int:
        lookback = info.data.get("lookback_days")
        if lookback is not None and skip_days >= lookback:
            raise ValueError(
                f"skip_days must be smaller than lookback_days (lookback_days={lookback}, skip_days={skip_days})"
            )
        return skip_days

    def warmup_rows(self) -> int:
        return self.lookback_days  # the score of a row needs the close lookback_days rows before it


@register_signal("momentum_12_1", params=Momentum121Params)
def momentum_12_1(prices: pd.DataFrame, params: Momentum121Params) -> pd.DataFrame:
    """1.0 for the top_n symbols by return from lookback to skip rows ago, else 0.0."""
    closes = close_frame(prices)
    scores = {}
    for symbol in closes.columns:
        own = closes[symbol].dropna()
        score = own.shift(params.skip_days) / own.shift(params.lookback_days) - 1.0  # NaN during warm-up
        scores[symbol] = carry_forward(score, closes.index)
    score_frame = pd.DataFrame(scores, index=closes.index, columns=closes.columns)

    eligible = score_frame.notna()
    if params.positive_only:
        eligible &= score_frame > 0
    # Rank 1 is the best score; ties go to the symbol that comes first in the input, so the result is deterministic.
    ranks = score_frame.where(eligible).rank(axis=1, method="first", ascending=False)
    return (ranks <= params.top_n).astype("float64")


class BuyAndHoldParams(SignalParams):
    """Buy and hold has no parameters."""


@register_signal("buy_and_hold", params=BuyAndHoldParams)
def buy_and_hold(prices: pd.DataFrame, params: BuyAndHoldParams) -> pd.DataFrame:
    """1.0 for every symbol from its first trading row on."""
    return per_symbol_signal(prices, lambda close: pd.Series(1.0, index=close.index))
