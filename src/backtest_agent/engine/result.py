"""The result of a backtest run (see docs/engine.md).

Both classes hold plain Python types and standard pandas frames (``DatetimeIndex`` named ``date``, columns named
``symbol``), so the journal (Phase 8) can serialize them without a change of shape. Treat the frames as read-only.
"""

from dataclasses import dataclass
from datetime import date

import pandas as pd

from backtest_agent.data.validation import ValidationResult
from backtest_agent.spec.schema import RiskFlag, StrategySpec


@dataclass(frozen=True)
class WarmupInfo:
    """How much history the run had before its first decision.

    ``rows_before[s]`` is the number of rows of symbol ``s`` (its own trading rows, where its close is not NaN) strictly
    before the first decision bar; the run is ``sufficient`` when every symbol has at least ``required_rows``.
    The first decision bar is the bar that executes on the first bar of the period (see "Initial decision" in
    docs/engine.md); ``initial_target_weights`` are the target weights of that bar, so what the first trade was
    based on stays visible although ``signals`` and ``target_weights`` of the result start on the first bar.
    """

    required_rows: int  # StrategySpec.warmup_rows
    delay_bars: int
    rows_needed: int  # required_rows + delay_bars
    fetch_start: date
    buffer_days: int  # calendar days subtracted from period.start (2 * rows_needed + 14)
    first_bar: date
    first_decision_date: date
    initial_target_weights: dict[str, float]
    rows_before: dict[str, int]
    first_data: dict[str, date]  # first own trading date of each symbol in the loaded frame
    short_symbols: tuple[str, ...]
    sufficient: bool


@dataclass(frozen=True, eq=False)  # frames have no unambiguous equality, so compare fields explicitly
class BacktestResult:
    """Everything a run produced, trimmed to the period (first bar on or after ``period.start`` up to ``period.end``).

    ``signals`` and ``target_weights`` are the values at decision time (before the shift by ``delay_bars``).
    ``costs_applied`` is False in Phase 4: the costs of the spec are not deducted yet.
    """

    spec: StrategySpec
    data_hash: str
    validation: ValidationResult
    risk_flags: tuple[RiskFlag, ...]
    warmup: WarmupInfo
    costs_applied: bool
    initial_equity: float
    equity: pd.Series
    cash: pd.Series
    positions: pd.DataFrame  # shares per symbol
    weights: pd.DataFrame  # share of equity per symbol, cash is the rest
    trades: pd.DataFrame  # date, symbol, shares (signed), price, notional (signed)
    turnover: pd.Series  # two-sided
    signals: pd.DataFrame
    target_weights: pd.DataFrame
    deferred_orders: int
    unfilled_orders: int

    @property
    def returns(self) -> pd.Series:
        """Return per bar; the first bar is measured against ``initial_equity``."""
        return self.equity / self.equity.shift(1, fill_value=self.initial_equity) - 1.0
