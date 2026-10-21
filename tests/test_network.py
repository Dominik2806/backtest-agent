from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from backtest_agent.data import hash_frame, validate_prices, validate_standard_frame
from backtest_agent.data.cache import CachedProvider
from backtest_agent.data.yfinance_provider import YFinanceProvider

SYMBOLS = ["AAPL", "SAP.DE", "SPY"]  # US stock, German stock (tz-aware Europe/Berlin index), US ETF
START = date(2023, 1, 2)
END = date(2023, 3, 31)


@pytest.mark.network
def test_live_yfinance_three_tickers_second_call_comes_from_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inner = YFinanceProvider()
    fetches: list[tuple[str, ...]] = []
    real_get_prices = inner.get_prices

    def counting(symbols, start, end):
        fetches.append(tuple(symbols))
        return real_get_prices(symbols, start, end)

    monkeypatch.setattr(inner, "get_prices", counting)
    provider = CachedProvider(inner, cache_dir=tmp_path)

    first = provider.get_prices(SYMBOLS, START, END)
    validate_standard_frame(first, SYMBOLS)
    assert fetches == [tuple(SYMBOLS)]
    assert len(list((tmp_path / "yfinance").glob("*.parquet"))) == 3

    second = provider.get_prices(SYMBOLS, START, END)
    assert fetches == [tuple(SYMBOLS)]  # no second download
    pd.testing.assert_frame_equal(first, second, check_exact=True)

    # Real data can be messy, so warnings are allowed; errors are not.
    result = validate_prices(first, start=START, end=END)
    assert not result.has_errors, result.to_json()
    assert hash_frame(first) == hash_frame(second)
