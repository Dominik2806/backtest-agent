"""yfinance provider: split and dividend adjusted daily prices (unofficial source, see docs/data.md)."""

from collections.abc import Sequence
from datetime import date, timedelta

import pandas as pd
import yfinance as yf
from yfinance import exceptions as yf_exceptions

from backtest_agent.data.errors import DataError, DataUnavailableError
from backtest_agent.data.provider import FIELDS, DataProvider, assemble_frame, check_request

_MISSING_ERRORS = (
    yf_exceptions.YFTickerMissingError,
    yf_exceptions.YFTzMissingError,
    yf_exceptions.YFPricesMissingError,
)


def normalize_yfinance_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Turn a raw yfinance history frame into lowercase OHLCV on a tz-naive daily date index.

    A timezone-aware index (for example Europe/Berlin for ``.DE`` tickers) keeps its exchange-local calendar date:
    ``tz_localize(None)`` drops the zone without converting, ``tz_convert("UTC")`` would shift dates.
    """
    frame = raw.rename(columns=str.lower)
    frame = frame.loc[:, list(FIELDS)].astype("float64")
    index = pd.DatetimeIndex(frame.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    frame.index = index.normalize().rename("date")
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    return frame.dropna(how="all")


class YFinanceProvider(DataProvider):
    """Daily prices from Yahoo Finance via yfinance with ``auto_adjust=True``."""

    name = "yfinance"

    def get_prices(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        symbols = check_request(symbols, start, end)
        frames: dict[str, pd.DataFrame] = {}
        failed: dict[str, str] = {}
        for symbol in symbols:
            try:
                frames[symbol] = self._fetch(symbol, start, end)
            except DataUnavailableError as error:
                failed[symbol] = str(error)
        if failed:
            details = "; ".join(f"{symbol}: {reason}" for symbol, reason in failed.items())
            raise DataUnavailableError(f"yfinance returned no data for {sorted(failed)} ({details})")
        return assemble_frame(frames)

    def _fetch(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        try:
            # yfinance treats `end` as exclusive, so ask for one more day to make it inclusive.
            raw = yf.Ticker(symbol).history(
                start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(), auto_adjust=True, actions=False
            )
        except _MISSING_ERRORS as error:
            raise DataUnavailableError(f"unknown symbol or no data ({error})") from error
        except yf_exceptions.YFException as error:
            raise DataError(f"yfinance failed for {symbol}: {error}") from error
        if raw is None or raw.empty:
            raise DataUnavailableError(f"empty result between {start} and {end}; is the symbol correct?")
        frame = normalize_yfinance_frame(raw)
        frame = frame.loc[pd.Timestamp(start) : pd.Timestamp(end)]
        if frame.empty:
            raise DataUnavailableError(f"no rows between {start} and {end}")
        return frame
