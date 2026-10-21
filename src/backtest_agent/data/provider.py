"""The DataProvider interface and the standard price frame format (see docs/data.md)."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date, datetime

import pandas as pd

FIELDS = ("open", "high", "low", "close", "volume")
INDEX_NAME = "date"
COLUMN_LEVELS = ["symbol", "field"]


class DataProvider(ABC):
    """Source of daily prices. All providers return the same standard frame."""

    #: Short identifier, used for example as the cache sub-directory.
    name: str = "provider"

    @abstractmethod
    def get_prices(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        """Return adjusted daily OHLCV for ``symbols`` from ``start`` to ``end``, both inclusive.

        The result has a tz-naive, sorted, unique ``DatetimeIndex`` named ``date`` and ``MultiIndex`` columns
        ``(symbol, field)`` with the fields in ``FIELDS``, all ``float64``. Raises ``DataUnavailableError`` if a
        symbol is unknown or has no rows in the range.
        """


def check_request(symbols: Sequence[str], start: date, end: date) -> tuple[str, ...]:
    """Validate request arguments and return the symbols as a tuple."""
    if isinstance(symbols, str):
        raise ValueError("symbols must be a sequence of strings, not a single string")
    symbols = tuple(symbols)
    if not symbols:
        raise ValueError("symbols must not be empty")
    if not all(isinstance(s, str) and s for s in symbols):
        raise ValueError("symbols must be non-empty strings")
    if len(set(symbols)) != len(symbols):
        raise ValueError(f"symbols must be unique, got {list(symbols)}")
    for name, value in (("start", start), ("end", end)):
        if not isinstance(value, date) or isinstance(value, datetime):
            raise ValueError(f"{name} must be a datetime.date, got {value!r}")
    if start > end:
        raise ValueError(f"start {start} is after end {end}")
    return symbols


def validate_standard_frame(frame: pd.DataFrame, symbols: Sequence[str] | None = None) -> None:
    """Raise ``ValueError`` if ``frame`` does not follow the standard format."""
    index = frame.index
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError("index must be a DatetimeIndex")
    if index.name != INDEX_NAME:
        raise ValueError(f"index must be named {INDEX_NAME!r}, got {index.name!r}")
    if index.tz is not None:
        raise ValueError("index must be timezone-naive")
    if index.dtype != "datetime64[ns]":
        raise ValueError(f"index must have dtype datetime64[ns], got {index.dtype}")
    if not (index == index.normalize()).all():
        raise ValueError("index must contain plain dates (midnight)")
    if not index.is_monotonic_increasing or not index.is_unique:
        raise ValueError("index must be sorted and unique")
    if len(frame) == 0:
        raise ValueError("frame must not be empty")
    columns = frame.columns
    if not isinstance(columns, pd.MultiIndex) or list(columns.names) != COLUMN_LEVELS:
        raise ValueError(f"columns must be a MultiIndex named {COLUMN_LEVELS}")
    present = list(dict.fromkeys(columns.get_level_values("symbol")))
    expected = list(symbols) if symbols is not None else present
    if present != expected:
        raise ValueError(f"symbols must be {expected} in this order, got {present}")
    if list(columns) != [(s, f) for s in expected for f in FIELDS]:
        raise ValueError(f"every symbol needs exactly the fields {list(FIELDS)} in this order")
    if not (frame.dtypes == "float64").all():
        raise ValueError("all columns must be float64")


def assemble_frame(per_symbol: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Join per-symbol frames (columns ``FIELDS``, date index) into one standard frame.

    Dates are the union over symbols; a symbol that did not trade on a date has NaN there (no forward fill).
    """
    frames = {symbol: frame.loc[:, list(FIELDS)].astype("float64") for symbol, frame in per_symbol.items()}
    result = pd.concat(frames, axis=1, names=COLUMN_LEVELS, sort=False).sort_index()
    result.index = result.index.astype("datetime64[ns]").rename(INDEX_NAME)
    return result
