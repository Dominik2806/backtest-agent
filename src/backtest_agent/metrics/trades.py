"""Trade statistics of a run (F-14; definitions and fixtures T1 to T6 in docs/metrics.md, "Trade statistics").

A **trade** is one fill: one row of ``BacktestResult.trades`` (one symbol on one bar). The functions are pure and
take the ``trades`` table; results are plain ``int``, ``float``, ``str`` or ``None``, never NaN or inf.
"""

import math
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

REQUIRED_COLUMNS = ("symbol", "shares", "cost")


@dataclass(frozen=True)
class SymbolTrades:
    """Fill counts of one symbol; ``trades == buys + sells``."""

    trades: int
    buys: int  # fills with shares above 0
    sells: int  # fills with shares below 0


@dataclass(frozen=True)
class TradeStatistics:
    """Counts and costs of the fills of one run.

    ``per_symbol`` lists only symbols that were traded, sorted by symbol. ``total_cost`` is the sum of the ``cost``
    column of the fills (equal to ``BacktestResult.total_costs``). ``average_cost_per_trade`` is
    ``total_cost / n_trades`` and ``None`` without trades; with trades that cost nothing it is 0.0.
    """

    n_trades: int
    n_buys: int
    n_sells: int
    per_symbol: dict[str, SymbolTrades]
    total_cost: float
    average_cost_per_trade: float | None

    def to_dict(self) -> dict[str, Any]:
        """Plain dict (int, float, None and nested dicts), for the report and the journal."""
        return asdict(self)


def trade_statistics(trades: pd.DataFrame) -> TradeStatistics:
    """Number of fills, buys and sells (total and per symbol), total cost and average cost per fill.

    Raises ``ValueError`` if a required column is missing, if ``shares`` is 0, NaN or infinite, or if ``cost`` is
    negative, NaN or infinite: such a table is a bug upstream and is not summarized.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in trades.columns]
    if missing:
        raise ValueError(f"the trades table has no column {missing}")
    shares = trades["shares"].to_numpy(dtype="float64")
    costs = trades["cost"].to_numpy(dtype="float64")
    if not all(math.isfinite(x) and x != 0.0 for x in shares):
        raise ValueError("every fill needs finite shares other than 0")
    if not all(math.isfinite(x) and x >= 0.0 for x in costs):
        raise ValueError("every fill needs a finite cost of 0 or more")

    per_symbol: dict[str, SymbolTrades] = {}
    for symbol in sorted(set(trades["symbol"])):
        signs = shares[(trades["symbol"] == symbol).to_numpy()]
        buys = int((signs > 0).sum())
        per_symbol[str(symbol)] = SymbolTrades(trades=len(signs), buys=buys, sells=len(signs) - buys)
    n_trades = len(trades)
    n_buys = int((shares > 0).sum())
    total_cost = math.fsum(costs)
    return TradeStatistics(
        n_trades=n_trades,
        n_buys=n_buys,
        n_sells=n_trades - n_buys,
        per_symbol=per_symbol,
        total_cost=total_cost,
        average_cost_per_trade=total_cost / n_trades if n_trades else None,
    )
