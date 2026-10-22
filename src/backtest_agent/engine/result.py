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
    Everything except ``gross_equity`` is the **net** run, with the costs of the spec deducted. ``costs_applied`` is
    True if a cost model was applied (also one that charges nothing) and False for ``run_backtest(apply_costs=False)``.
    ``gross_equity`` is the equity path of a twin run with all costs at zero; without costs it is a copy of ``equity``.
    The scalars below are properties, so a journal has to serialize them explicitly (see docs/engine.md).
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
    costs: pd.Series  # fees paid on each bar (0.0 without costs)
    gross_equity: pd.Series  # equity of the twin run without costs
    signals: pd.DataFrame
    target_weights: pd.DataFrame
    deferred_orders: int
    unfilled_orders: int

    @property
    def total_costs(self) -> float:
        """All fees paid over the run."""
        return float(self.costs.sum())

    @property
    def gross_final_equity(self) -> float:
        return float(self.gross_equity.iloc[-1])

    @property
    def net_return(self) -> float:
        """Return of the whole run: final equity over ``initial_equity`` minus 1."""
        return float(self.equity.iloc[-1]) / self.initial_equity - 1.0

    @property
    def gross_return(self) -> float:
        """Return of the whole run of the twin without costs."""
        return self.gross_final_equity / self.initial_equity - 1.0

    @property
    def cost_drag(self) -> float:
        """Gross return minus net return. Not guaranteed to be 0 or more: costs change the path."""
        return self.gross_return - self.net_return

    @property
    def cost_share(self) -> float | None:
        """The share of the gross return that the costs ate; None if the gross return is not positive.

        Not guaranteed to be 1 or less: with a negative net and a positive gross return it exceeds 1.
        """
        gross = self.gross_return
        return self.cost_drag / gross if gross > 0.0 else None

    @property
    def returns(self) -> pd.Series:
        """Return per bar; the first bar is measured against ``initial_equity``."""
        return self.equity / self.equity.shift(1, fill_value=self.initial_equity) - 1.0
