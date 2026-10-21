from datetime import date

import pandas as pd
import pytest

import backtest_agent.data.yfinance_provider as yfp
from backtest_agent.data import DataUnavailableError, validate_standard_frame
from backtest_agent.data.errors import DataError
from backtest_agent.data.yfinance_provider import YFinanceProvider, normalize_yfinance_frame
from yf_mock import MockYFinance, raw_history

START = date(2024, 1, 2)
END = date(2024, 3, 29)


def test_returns_standard_frame(mock_yf: MockYFinance) -> None:
    frame = YFinanceProvider().get_prices(["AAA", "BBB.DE", "CCC"], START, END)
    validate_standard_frame(frame, ["AAA", "BBB.DE", "CCC"])
    assert frame.index[0].date() == START
    assert frame.index[-1].date() == END


def test_end_is_inclusive_and_prices_are_auto_adjusted(mock_yf: MockYFinance) -> None:
    YFinanceProvider().get_prices(["AAA"], START, END)
    (call,) = mock_yf.calls
    assert call["start"] == "2024-01-02"
    assert call["end"] == "2024-03-30"  # yfinance end is exclusive, so end + 1 day
    assert call["auto_adjust"] is True


@pytest.mark.parametrize("tz", ["Europe/Berlin", "America/New_York", "Asia/Tokyo", "UTC"])
def test_timezone_aware_index_keeps_local_calendar_date(tz: str) -> None:
    dates = pd.DatetimeIndex(["2024-03-27", "2024-03-28", "2024-03-29"])
    frame = normalize_yfinance_frame(raw_history(dates, tz=tz))
    assert frame.index.tz is None
    assert list(frame.index) == list(dates)
    assert frame.index.name == "date"


def test_intraday_timestamps_are_normalized_to_dates() -> None:
    raw = raw_history(pd.DatetimeIndex(["2024-03-27", "2024-03-28"]), tz="Europe/Berlin")
    raw.index = raw.index + pd.Timedelta(hours=9)
    frame = normalize_yfinance_frame(raw)
    assert list(frame.index) == [pd.Timestamp("2024-03-27"), pd.Timestamp("2024-03-28")]


def test_normalize_sorts_and_drops_duplicates_and_empty_rows() -> None:
    raw = raw_history(pd.DatetimeIndex(["2024-03-28", "2024-03-27", "2024-03-28"]), tz=None)
    raw.iloc[0, :] = float("nan")  # first 03-28 row is empty, the later duplicate is kept
    frame = normalize_yfinance_frame(raw)
    assert frame.index.is_monotonic_increasing and frame.index.is_unique
    assert len(frame) == 2


def test_volume_is_float64(mock_yf: MockYFinance) -> None:
    frame = YFinanceProvider().get_prices(["CCC"], START, END)
    assert frame["CCC"]["volume"].dtype == "float64"


def test_empty_result_raises_clear_error(mock_yf: MockYFinance) -> None:
    with pytest.raises(DataUnavailableError, match="NOPE"):
        YFinanceProvider().get_prices(["AAA", "NOPE"], START, END)


def test_all_failing_symbols_are_named(mock_yf: MockYFinance) -> None:
    with pytest.raises(DataUnavailableError) as info:
        YFinanceProvider().get_prices(["X1", "AAA", "X2"], START, END)
    assert "X1" in str(info.value) and "X2" in str(info.value) and "AAA" not in str(info.value)


def test_range_without_trading_days_raises(mock_yf: MockYFinance) -> None:
    with pytest.raises(DataUnavailableError):
        YFinanceProvider().get_prices(["AAA"], date(2024, 1, 6), date(2024, 1, 7))


def test_yfinance_missing_ticker_exception_becomes_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    class Boom:
        def history(self, **kwargs):
            raise yfp.yf_exceptions.YFTickerMissingError("ZZZ", "delisted")

    monkeypatch.setattr(yfp.yf, "Ticker", lambda symbol: Boom())
    with pytest.raises(DataUnavailableError, match="ZZZ"):
        YFinanceProvider().get_prices(["ZZZ"], START, END)


def test_rate_limit_is_a_data_error_but_not_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    class Limited:
        def history(self, **kwargs):
            raise yfp.yf_exceptions.YFRateLimitError()

    monkeypatch.setattr(yfp.yf, "Ticker", lambda symbol: Limited())
    with pytest.raises(DataError) as info:
        YFinanceProvider().get_prices(["AAA"], START, END)
    assert not isinstance(info.value, DataUnavailableError)


def test_different_calendars_give_nan_not_fill(monkeypatch: pytest.MonkeyPatch) -> None:
    us = pd.bdate_range("2024-03-25", "2024-03-29")
    de = us.delete(1)  # German holiday on 2024-03-26
    mock = MockYFinance({"AAA": raw_history(us, 1, "America/New_York"), "BBB.DE": raw_history(de, 2)})
    monkeypatch.setattr(yfp.yf, "Ticker", mock.Ticker)
    frame = YFinanceProvider().get_prices(["AAA", "BBB.DE"], date(2024, 3, 25), date(2024, 3, 29))
    validate_standard_frame(frame, ["AAA", "BBB.DE"])
    assert len(frame) == 5
    assert frame.loc["2024-03-26", "BBB.DE"].isna().all()
    assert frame.loc["2024-03-26", "AAA"].notna().all()
