"""The portfolio core: executes orders bar by bar and returns the portfolio path (see docs/engine.md).

The input is prices and, for every bar on which the portfolio is rebalanced, target weights. Nothing here knows about
signals, delays, specs or data providers, so it can be checked by hand on tiny worlds.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtest_agent.engine.costs import CostModel, NoCosts
from backtest_agent.engine.errors import EngineError, EngineInvariantError

#: Orders and cash shortfalls smaller than this fraction of the portfolio value are float dust and are ignored.
DUST = 1e-9
#: Tolerance when the target weights of a bar are checked to add up to at most 1.
WEIGHT_SUM_TOLERANCE = 1e-9
_PRICE_RULES = ("open", "close")


@dataclass(frozen=True)
class Portfolio:
    """The path of a simulation. Every row is the end of a bar (after the close). Treat the frames as read-only."""

    equity: pd.Series
    initial_equity: float
    cash: pd.Series
    positions: pd.DataFrame  # shares per symbol
    weights: pd.DataFrame  # share of equity per symbol, cash is the rest
    trades: pd.DataFrame  # date, symbol, shares (signed), price, notional (signed)
    turnover: pd.Series  # two-sided: sum of absolute trade notionals / portfolio value at the execution mark
    deferred_orders: int  # orders carried past their execution bar (no price, or not enough cash)
    unfilled_orders: int  # orders still open after the last bar

    @property
    def returns(self) -> pd.Series:
        """Return per bar; the first bar is measured against ``initial_equity``."""
        return self.equity / self.equity.shift(1, fill_value=self.initial_equity) - 1.0


def simulate(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    target_weights: pd.DataFrame,
    rebalance_bars: pd.Series,
    initial_capital: float,
    price_rule: str,
    cost_model: CostModel | None = None,
    initial_last_close: pd.Series | None = None,
) -> Portfolio:
    """Run the portfolio over the bars of ``closes`` (all of them are valued, the first one starts in cash).

    ``initial_last_close`` is the last close of each symbol before the first bar (NaN if it never traded), used to
    value a symbol that has no price on the first bar. Nothing is traded or valued before the first bar.

    ``opens`` and ``closes`` have one row per bar and one column per symbol, NaN where a symbol has no price.
    ``target_weights`` and ``rebalance_bars`` are per **execution** bar: where ``rebalance_bars`` is True, the whole
    portfolio is brought to the weights of that row at the ``price_rule`` price (``open`` or ``close``) of that bar.
    """
    cost_model = NoCosts() if cost_model is None else cost_model
    _check_inputs(opens, closes, target_weights, rebalance_bars, initial_capital, price_rule, initial_last_close)

    index, symbols = closes.index, list(closes.columns)
    n_bars, n_symbols = closes.shape
    fills = (opens if price_rule == "open" else closes).to_numpy(dtype="float64")
    close_prices = closes.to_numpy(dtype="float64")
    targets = target_weights.to_numpy(dtype="float64")
    rebalance = rebalance_bars.to_numpy(dtype=bool)

    shares = np.zeros(n_symbols)
    cash = float(initial_capital)
    last_close = np.full(n_symbols, np.nan)
    if initial_last_close is not None:
        last_close = initial_last_close.to_numpy(dtype="float64", copy=True)
    open_orders = np.zeros(n_symbols)  # signed share quantity per symbol, 0 = no order
    carried = np.zeros(n_symbols, dtype=bool)  # order already counted as deferred
    deferred_orders = 0

    equity_path = np.empty(n_bars)
    cash_path = np.empty(n_bars)
    turnover_path = np.zeros(n_bars)
    shares_path = np.empty((n_bars, n_symbols))
    weights_path = np.empty((n_bars, n_symbols))
    trade_rows: list[tuple[pd.Timestamp, str, float, float, float]] = []

    for i in range(n_bars):
        price = fills[i]
        priced = ~np.isnan(price)

        # 1. Mark: execution price where there is one, else the last close.
        mark = np.where(priced, price, last_close)
        held = np.where(shares != 0.0, shares * mark, 0.0)
        value = cash + held.sum()

        # 2. New orders: share quantities that bring every symbol to its target weight.
        if rebalance[i]:
            open_orders = _new_orders(targets[i], shares, mark, held, value, symbols, index[i])
            carried[:] = False

        # 3. Fill the orders of symbols that have a price; sells first, buys scaled down if cash is short.
        fillable = (open_orders != 0.0) & priced
        safe_price = np.where(priced, price, 0.0)
        quantity = np.where(fillable, open_orders, 0.0)
        notional = quantity * safe_price
        cash_after_sells = cash - notional[notional < 0.0].sum()
        buy_total = notional[notional > 0.0].sum()
        factor = 1.0
        if buy_total > cash_after_sells:
            factor = max(cash_after_sells, 0.0) / buy_total
        filled = quantity * np.where(notional > 0.0, factor, 1.0)
        filled_notional = filled * safe_price
        remainder = open_orders - filled
        open_orders = np.where(np.abs(remainder * mark) <= DUST * value, 0.0, remainder)

        cost = sum(cost_model.cost(symbols[s], abs(float(filled_notional[s]))) for s in np.flatnonzero(filled))
        cash = cash - filled_notional.sum() - cost
        if cash < -DUST * value:
            raise EngineInvariantError(f"cash became negative ({cash}) on {index[i].date()}")
        cash = max(cash, 0.0)
        shares = shares + filled
        if (shares < 0.0).any():
            raise EngineInvariantError(f"a position became negative on {index[i].date()}")
        for s in np.flatnonzero(filled):
            trade_rows.append((index[i], symbols[s], float(filled[s]), float(price[s]), float(filled_notional[s])))
        turnover_path[i] = np.abs(filled_notional).sum() / value

        # 4. Carry: orders that are still open after this bar are counted once.
        pending = open_orders != 0.0
        deferred_orders += int((pending & ~carried).sum())
        carried |= pending

        # 5. Close: value everything at the last close.
        last_close = np.where(np.isnan(close_prices[i]), last_close, close_prices[i])
        held_at_close = np.where(shares != 0.0, shares * last_close, 0.0)
        equity = cash + held_at_close.sum()
        equity_path[i] = equity
        cash_path[i] = cash
        shares_path[i] = shares
        weights_path[i] = held_at_close / equity

    columns = closes.columns
    return Portfolio(
        equity=pd.Series(equity_path, index=index, name="equity"),
        initial_equity=float(initial_capital),
        cash=pd.Series(cash_path, index=index, name="cash"),
        positions=pd.DataFrame(shares_path, index=index, columns=columns),
        weights=pd.DataFrame(weights_path, index=index, columns=columns),
        trades=_trades_frame(trade_rows),
        turnover=pd.Series(turnover_path, index=index, name="turnover"),
        deferred_orders=deferred_orders,
        unfilled_orders=int((open_orders != 0.0).sum()),
    )


def _new_orders(
    weights: np.ndarray,
    shares: np.ndarray,
    mark: np.ndarray,
    held: np.ndarray,
    value: float,
    symbols: list[str],
    date: pd.Timestamp,
) -> np.ndarray:
    """Share quantities that bring the portfolio to ``weights``; orders below the dust limit are dropped."""
    wants_order = (weights > 0.0) | (shares != 0.0)
    unmarked = wants_order & np.isnan(mark)
    if unmarked.any():
        names = [symbols[s] for s in np.flatnonzero(unmarked)]
        raise EngineError(f"{names} get an order on {date.date()} but have never had a price")
    quantity = np.zeros(len(weights))
    quantity[wants_order] = (weights[wants_order] * value - held[wants_order]) / mark[wants_order]
    quantity = np.where(weights == 0.0, -shares, quantity)  # a full exit sells exactly the shares held
    traded_value = np.where(wants_order, np.abs(quantity * np.where(np.isnan(mark), 0.0, mark)), 0.0)
    return np.where(traded_value <= DUST * value, 0.0, quantity)


def _trades_frame(rows: list[tuple[pd.Timestamp, str, float, float, float]]) -> pd.DataFrame:
    columns = ["date", "symbol", "shares", "price", "notional"]
    frame = pd.DataFrame(rows, columns=columns)
    frame["date"] = frame["date"].astype("datetime64[ns]")
    for name in ("shares", "price", "notional"):
        frame[name] = frame[name].astype("float64")
    return frame


def _check_inputs(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    target_weights: pd.DataFrame,
    rebalance_bars: pd.Series,
    initial_capital: float,
    price_rule: str,
    initial_last_close: pd.Series | None = None,
) -> None:
    if price_rule not in _PRICE_RULES:
        raise EngineError(f"price_rule must be one of {_PRICE_RULES}, got {price_rule!r}")
    if not np.isfinite(initial_capital) or initial_capital <= 0:
        raise EngineError(f"initial_capital must be a positive number, got {initial_capital!r}")
    if closes.empty:
        raise EngineError("closes must have at least one bar and one symbol")
    index = closes.index
    if not isinstance(index, pd.DatetimeIndex) or not index.is_monotonic_increasing or not index.is_unique:
        raise EngineError("the bars must be a sorted, unique DatetimeIndex")
    for name, frame in (("opens", opens), ("target_weights", target_weights)):
        if not frame.index.equals(index) or not frame.columns.equals(closes.columns):
            raise EngineError(f"{name} must have the same bars and symbols as closes")
    if not rebalance_bars.index.equals(index):
        raise EngineError("rebalance_bars must have the same bars as closes")
    if rebalance_bars.dtype != bool:
        raise EngineError("rebalance_bars must be boolean")
    open_values, close_values = opens.to_numpy(dtype="float64"), closes.to_numpy(dtype="float64")
    if not np.array_equal(np.isnan(open_values), np.isnan(close_values)):
        raise EngineError("opens and closes must be NaN on exactly the same bars (a symbol that did not trade)")
    for name, values in (("opens", open_values), ("closes", close_values)):
        priced = values[~np.isnan(values)]
        if not np.isfinite(priced).all() or (priced <= 0).any():
            raise EngineError(f"{name} must be positive and finite where a symbol has a price")
    if initial_last_close is not None:
        if not initial_last_close.index.equals(closes.columns):
            raise EngineError("initial_last_close must have one entry per symbol of closes")
        known = initial_last_close.to_numpy(dtype="float64")
        known = known[~np.isnan(known)]
        if not np.isfinite(known).all() or (known <= 0).any():
            raise EngineError("initial_last_close must be positive and finite where a symbol had a price")
    weights = target_weights.to_numpy(dtype="float64")
    if not np.isfinite(weights).all() or (weights < 0).any() or (weights > 1).any():
        raise EngineError("target weights must be finite and between 0 and 1")
    if (weights.sum(axis=1) > 1.0 + WEIGHT_SUM_TOLERANCE).any():
        raise EngineError("target weights of a bar must not add up to more than 1 (no leverage)")
