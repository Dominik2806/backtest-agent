"""Deterministic in-memory provider with seeded synthetic prices. Never touches the network."""

import zlib
from collections.abc import Sequence
from datetime import date

import numpy as np
import pandas as pd

from backtest_agent.data.errors import DataUnavailableError
from backtest_agent.data.provider import FIELDS, DataProvider, assemble_frame, check_request

# Synthetic history starts here, so the same date always has the same price for a given symbol and seed.
FAKE_HISTORY_START = date(2015, 1, 1)
FAKE_HISTORY_END = date(2030, 12, 31)


class FakeProvider(DataProvider):
    """Mon-Fri prices from a seeded geometric random walk. ``calls`` records every request."""

    name = "fake"

    def __init__(self, symbols: Sequence[str] = ("AAA", "BBB", "CCC"), seed: int = 0) -> None:
        self.symbols = tuple(symbols)
        self.seed = seed
        self.calls: list[tuple[tuple[str, ...], date, date]] = []

    def get_prices(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        symbols = check_request(symbols, start, end)
        self.calls.append((symbols, start, end))
        unknown = [s for s in symbols if s not in self.symbols]
        if unknown:
            raise DataUnavailableError(f"unknown symbols in fake provider: {unknown}")
        frames = {s: self._series(s).loc[pd.Timestamp(start) : pd.Timestamp(end)] for s in symbols}
        empty = [s for s, frame in frames.items() if frame.empty]
        if empty:
            raise DataUnavailableError(f"no data for {empty} between {start} and {end}")
        return assemble_frame(frames)

    def _series(self, symbol: str) -> pd.DataFrame:
        """Full synthetic history of one symbol, independent of the requested range."""
        rng = np.random.default_rng([self.seed, zlib.crc32(symbol.encode())])
        dates = pd.bdate_range(FAKE_HISTORY_START, FAKE_HISTORY_END)
        n = len(dates)
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n)))
        open_ = close * np.exp(rng.normal(0.0, 0.003, n))
        high = np.maximum(open_, close) * (1.0 + rng.uniform(0.0, 0.01, n))
        low = np.minimum(open_, close) * (1.0 - rng.uniform(0.0, 0.01, n))
        volume = rng.integers(100_000, 1_000_000, n).astype("float64")
        frame = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=dates)
        return frame.loc[:, list(FIELDS)]
