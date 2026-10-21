"""Reusable contract every DataProvider must satisfy."""

from collections.abc import Sequence
from datetime import date

import pandas as pd
import pytest

from backtest_agent.data import DataProvider, DataUnavailableError, validate_standard_frame


def check_provider_contract(
    provider: DataProvider, symbols: Sequence[str], start: date, end: date, unknown: str = "NOPE"
) -> None:
    """Check format, determinism, inclusive dates, input validation and the unknown-symbol error."""
    frame = provider.get_prices(symbols, start, end)
    validate_standard_frame(frame, symbols)
    # Both bounds are inclusive when the source has a bar on that day (callers pick weekdays).
    assert frame.index[0].date() == start
    assert frame.index[-1].date() == end
    assert frame.index.min() >= pd.Timestamp(start) and frame.index.max() <= pd.Timestamp(end)

    # Prices are positive where present, and open/high/low/close are consistent.
    for symbol in symbols:
        sub = frame[symbol].dropna()
        assert (sub[["open", "high", "low", "close"]] > 0).all().all()
        assert (sub["high"] >= sub[["open", "close"]].max(axis=1)).all()
        assert (sub["low"] <= sub[["open", "close"]].min(axis=1)).all()

    # Same request, same frame.
    pd.testing.assert_frame_equal(frame, provider.get_prices(symbols, start, end))

    # A narrower request is a slice of the wider one.
    narrow = provider.get_prices(symbols[:1], frame.index[1].date(), frame.index[-2].date())
    pd.testing.assert_frame_equal(narrow, frame.iloc[1:-1][[symbols[0]]])

    with pytest.raises(DataUnavailableError):
        provider.get_prices([*symbols, unknown], start, end)
    with pytest.raises(ValueError):
        provider.get_prices([], start, end)
    with pytest.raises(ValueError):
        provider.get_prices([symbols[0], symbols[0]], start, end)
    with pytest.raises(ValueError):
        provider.get_prices(symbols, end, start)
