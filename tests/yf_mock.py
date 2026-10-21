"""A stand-in for yfinance.Ticker so tests never touch the network."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

import backtest_agent.data.yfinance_provider as yfp


def raw_history(dates: pd.DatetimeIndex, seed: int = 0, tz: str | None = "Europe/Berlin") -> pd.DataFrame:
    """Raw yfinance-style frame: capitalised columns, integer volume, tz-aware midnight index."""
    rng = np.random.default_rng(seed)
    close = 50.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, len(dates))))
    frame = pd.DataFrame(
        {
            "Open": close * 0.999,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": rng.integers(1_000, 9_000, len(dates)),
        },
        index=dates,
    )
    if tz is not None:
        frame.index = frame.index.tz_localize(tz)
    frame.index.name = "Date"
    return frame


class MockYFinance:
    """Installs a fake ``yf.Ticker`` serving ``data`` (symbol -> raw frame); records every history() call."""

    def __init__(self, data: dict[str, pd.DataFrame]) -> None:
        self.data = data
        self.calls: list[dict] = []

    def Ticker(self, symbol: str) -> "MockYFinance._Ticker":  # noqa: N802 - mirrors yfinance
        return self._Ticker(self, symbol)

    class _Ticker:
        def __init__(self, parent: "MockYFinance", symbol: str) -> None:
            self.parent = parent
            self.symbol = symbol

        def history(self, start: str, end: str, **kwargs) -> pd.DataFrame:
            self.parent.calls.append({"symbol": self.symbol, "start": start, "end": end, **kwargs})
            raw = self.parent.data.get(self.symbol)
            if raw is None:
                return pd.DataFrame()
            # Like yfinance: start inclusive, end exclusive, compared on the exchange-local date.
            local = raw.index.tz_localize(None) if raw.index.tz is not None else raw.index
            mask = (local >= pd.Timestamp(date.fromisoformat(start))) & (local < pd.Timestamp(date.fromisoformat(end)))
            return raw[mask]


@pytest.fixture
def mock_yf(monkeypatch: pytest.MonkeyPatch) -> MockYFinance:
    """Fake yfinance with AAA (US) and BBB, CCC (Berlin), all on the same Mon-Fri calendar."""
    dates = pd.bdate_range("2024-01-01", "2024-06-28")
    mock = MockYFinance(
        {
            "AAA": raw_history(dates, 1, "America/New_York"),
            "BBB.DE": raw_history(dates, 2, "Europe/Berlin"),
            "CCC": raw_history(dates, 3, None),
        }
    )
    monkeypatch.setattr(yfp.yf, "Ticker", mock.Ticker)
    return mock
