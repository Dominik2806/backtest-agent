"""Parquet cache that wraps any provider (see docs/data.md)."""

import logging
import os
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from backtest_agent.data.errors import OfflineCacheMissError
from backtest_agent.data.provider import FIELDS, DataProvider, assemble_frame, check_request

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("data/cache")


class CachedProvider(DataProvider):
    """Serves repeated requests from Parquet files, one per (provider, symbol, start, end).

    Requests whose ``end`` is today or later are never cached, because the current day's bar is still partial.
    ``today`` is injectable so this is testable. ``refresh=True`` re-downloads and overwrites; ``offline=True`` never
    calls the inner provider and raises ``OfflineCacheMissError`` when data is not cached.
    """

    def __init__(
        self,
        inner: DataProvider,
        cache_dir: Path | str = DEFAULT_CACHE_DIR,
        offline: bool = False,
        refresh: bool = False,
        today: Callable[[], date] = date.today,
    ) -> None:
        if offline and refresh:
            raise ValueError("offline and refresh cannot both be set")
        self.inner = inner
        self.name = inner.name
        self.cache_dir = Path(cache_dir)
        self.offline = offline
        self.refresh = refresh
        self.today = today

    def get_prices(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        symbols = check_request(symbols, start, end)
        if end >= self.today():
            # Partial bar of the current day: always fresh, never written.
            if self.offline:
                raise OfflineCacheMissError(
                    f"offline mode: end {end} is today or later, such requests are never cached"
                )
            return self.inner.get_prices(symbols, start, end)

        cached: dict[str, pd.DataFrame] = {}
        if not self.refresh:
            for symbol in symbols:
                frame = self._read(symbol, start, end)
                if frame is not None:
                    cached[symbol] = frame
        missing = [s for s in symbols if s not in cached]
        if missing:
            if self.offline:
                raise OfflineCacheMissError(
                    f"offline mode: {missing} not cached for {start} to {end} in {self.cache_dir / self.name}"
                )
            fetched = self.inner.get_prices(missing, start, end)
            for symbol in missing:
                # Drop rows that exist only because another symbol traded that day.
                frame = fetched[symbol].dropna(how="all")
                self._write(symbol, start, end, frame)
                cached[symbol] = frame
        return assemble_frame({symbol: cached[symbol] for symbol in symbols})

    def _path(self, symbol: str, start: date, end: date) -> Path:
        return self.cache_dir / self.name / f"{quote(symbol, safe='')}_{start.isoformat()}_{end.isoformat()}.parquet"

    def _read(self, symbol: str, start: date, end: date) -> pd.DataFrame | None:
        path = self._path(symbol, start, end)
        if not path.exists():
            return None
        try:
            frame = pd.read_parquet(path)
            if list(frame.columns) != list(FIELDS) or frame.empty:
                raise ValueError("unexpected columns or no rows")
        except Exception as error:  # noqa: BLE001 - any unreadable file is a miss
            logger.warning("ignoring unreadable cache file %s: %s", path, error)
            return None
        return frame

    def _write(self, symbol: str, start: date, end: date, frame: pd.DataFrame) -> None:
        path = self._path(symbol, start, end)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        frame.to_parquet(tmp)
        os.replace(tmp, path)
