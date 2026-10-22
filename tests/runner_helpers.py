"""Helpers for the runner tests: spec builder, providers around fixed or perturbed frames, literal price frames.

They build inputs only; no expected value of a test is computed here.
"""

import zlib
from collections.abc import Sequence
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from backtest_agent.data import FIELDS, DataProvider, DataUnavailableError, FakeProvider
from backtest_agent.data.provider import check_request
from backtest_agent.spec import SIGNALS, Signal, SignalParams, StrategySpec, parse_spec
from backtest_agent.spec.signals import per_symbol_signal
from specs import to_yaml, valid


def make_spec(
    *,
    universe: Sequence[str] = ("AAA", "BBB"),
    start: str = "2024-03-01",
    end: str = "2024-04-30",
    signal: str = "sma_crossover",
    params: dict[str, Any] | None = None,
    delay: int = 1,
    price: str = "open",
    rebalance: str = "on_signal",
    method: str = "equal_weight",
    fraction: float | None = None,
    costs: tuple[float, float, float] = (1.0, 2.0, 2.0),
    capital: float = 100000,
    benchmark: str | None = None,
) -> StrategySpec:
    """A valid spec; the defaults are an SMA crossover with short windows (warm-up 19 rows) on two fake symbols.

    The benchmark is the first symbol of the universe unless given.
    """
    data = valid()
    data["universe"] = list(universe)
    data["period"] = {"start": start, "end": end}
    if params is None:
        params = {"fast": 5, "slow": 20} if signal == "sma_crossover" else {}
    data["signal"] = {"id": signal, "params": params}
    data["execution"] = {"delay_bars": delay, "price": price, "allow_same_bar_execution": delay == 0}
    data["sizing"] = {"method": method} | ({} if fraction is None else {"fraction": fraction})
    data["rebalance"] = rebalance
    data["costs"] = dict(zip(("commission_bps", "spread_bps", "slippage_bps"), costs, strict=True))
    data["benchmark"] = universe[0] if benchmark is None else benchmark
    data["initial_capital"] = capital
    return parse_spec(to_yaml(data))


def fake_frame(symbols: Sequence[str], start: date, end: date, seed: int = 0) -> pd.DataFrame:
    return FakeProvider(symbols=symbols, seed=seed).get_prices(symbols, start, end)


def price_frame(
    opens: dict[str, list[float]], closes: dict[str, list[float]], start: str = "2024-01-02"
) -> pd.DataFrame:
    """Standard frame from literal opens and closes (NaN where a symbol did not trade); high and low follow."""
    rows = len(next(iter(closes.values())))
    index = pd.bdate_range(start, periods=rows).astype("datetime64[ns]").rename("date")
    data = {}
    for symbol in closes:
        open_, close = np.array(opens[symbol], dtype="float64"), np.array(closes[symbol], dtype="float64")
        data[(symbol, "open")] = open_
        data[(symbol, "high")] = np.maximum(open_, close)
        data[(symbol, "low")] = np.minimum(open_, close)
        data[(symbol, "close")] = close
        data[(symbol, "volume")] = np.where(np.isnan(close), np.nan, 1000.0)
    frame = pd.DataFrame(data, index=index)
    frame.columns = pd.MultiIndex.from_tuples(frame.columns, names=["symbol", "field"])
    return frame


def nan_rows(
    frame: pd.DataFrame, symbol: str, *, before: str | None = None, between: tuple[str, str] | None = None
) -> pd.DataFrame:
    """Copy of ``frame`` with all fields of ``symbol`` NaN before a date, or between two dates (both inclusive)."""
    result = frame.copy()
    if before is not None:
        result.loc[result.index < pd.Timestamp(before), symbol] = np.nan
    if between is not None:
        result.loc[pd.Timestamp(between[0]) : pd.Timestamp(between[1]), symbol] = np.nan
    return result


class LiteralProvider(DataProvider):
    """Serves a fixed frame, cut to the requested range. Records ``calls`` and the ``last_frame`` it delivered.

    ``strict=False`` returns the frame whatever symbols were asked for; ``clip_end=False`` ignores the end date.
    Both exist to simulate a provider that breaks its contract.
    """

    name = "literal"

    def __init__(self, frame: pd.DataFrame, *, strict: bool = True, clip_end: bool = True) -> None:
        self.frame = frame
        self.strict = strict
        self.clip_end = clip_end
        self.calls: list[tuple[tuple[str, ...], date, date]] = []
        self.last_frame: pd.DataFrame | None = None

    def get_prices(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        symbols = check_request(symbols, start, end)
        self.calls.append((symbols, start, end))
        frame = self.frame
        if self.strict:
            unknown = [s for s in symbols if s not in frame.columns.get_level_values("symbol")]
            if unknown:
                raise DataUnavailableError(f"unknown symbols in literal provider: {unknown}")
            frame = frame.loc[:, [(s, f) for s in symbols for f in FIELDS]]
        part = frame.loc[pd.Timestamp(start) : pd.Timestamp(end) if self.clip_end else None]
        if part.empty:
            raise DataUnavailableError(f"no data between {start} and {end}")
        self.last_frame = part.copy()
        return part.copy()


class HolidayProvider(DataProvider):
    """Wraps a provider and blanks whole rows of single symbols (all fields NaN), seeded; never the first row."""

    name = "holiday"

    def __init__(self, inner: DataProvider, seed: int = 0, rate: float = 0.05) -> None:
        self.inner, self.seed, self.rate = inner, seed, rate
        self.last_frame: pd.DataFrame | None = None

    def get_prices(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        frame = self.inner.get_prices(symbols, start, end).copy()
        for symbol in dict.fromkeys(frame.columns.get_level_values("symbol")):
            rng = np.random.default_rng([self.seed, zlib.crc32(symbol.encode())])
            holiday = rng.random(len(frame)) < self.rate
            holiday[0] = False
            frame.loc[holiday, symbol] = np.nan
        self.last_frame = frame.copy()
        return frame


class PerturbedProvider(DataProvider):
    """Wraps a provider and multiplies the four price fields of every row after ``after`` by a seeded random factor."""

    name = "perturbed"

    def __init__(self, inner: DataProvider, after: pd.Timestamp, seed: int = 0) -> None:
        self.inner, self.after, self.seed = inner, pd.Timestamp(after), seed

    def get_prices(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        frame = self.inner.get_prices(symbols, start, end).copy()
        later = np.flatnonzero(frame.index > self.after)
        for symbol in dict.fromkeys(frame.columns.get_level_values("symbol")):
            rng = np.random.default_rng([self.seed, zlib.crc32(symbol.encode())])
            factor = rng.uniform(0.7, 1.4, len(later))
            for field in ("open", "high", "low", "close"):
                column = frame.columns.get_loc((symbol, field))
                frame.iloc[later, column] = frame.iloc[later, column].to_numpy() * factor
        return frame


class UpDayParams(SignalParams):
    """Params of the test signal ``fixture_up_day``: it needs one row of history."""

    def warmup_rows(self) -> int:
        return 1


def up_day(prices: pd.DataFrame, params: UpDayParams) -> pd.DataFrame:
    """1.0 where the close is above the symbol's previous own close, else 0.0 (the fixture H14 signal)."""
    return per_symbol_signal(prices, lambda close: (close > close.shift(1)).astype("float64"))


def register_up_day(monkeypatch) -> None:
    """Register ``fixture_up_day`` for one test only: other tests pin the registry to the built-in signals."""
    signal = Signal("fixture_up_day", UpDayParams, up_day, "test signal of fixture H14")
    monkeypatch.setitem(SIGNALS._signals, signal.id, signal)
