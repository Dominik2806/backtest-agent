from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from backtest_agent.data import DataUnavailableError, FakeProvider, OfflineCacheMissError
from backtest_agent.data.cache import DEFAULT_CACHE_DIR, CachedProvider
from backtest_agent.data.yfinance_provider import YFinanceProvider
from yf_mock import MockYFinance

START = date(2024, 1, 2)
END = date(2024, 3, 29)  # Friday
TODAY = date(2024, 4, 15)  # after END, so END is cacheable
SYMBOLS = ["AAA", "BBB", "CCC"]


def make(tmp_path: Path, **kwargs) -> tuple[CachedProvider, FakeProvider]:
    fake = FakeProvider()
    kwargs.setdefault("today", lambda: TODAY)
    return CachedProvider(fake, cache_dir=tmp_path, **kwargs), fake


def test_round_trip_is_identical_to_uncached_frame(tmp_path: Path) -> None:
    cached, fake = make(tmp_path)
    expected = FakeProvider().get_prices(SYMBOLS, START, END)
    miss = cached.get_prices(SYMBOLS, START, END)
    hit = cached.get_prices(SYMBOLS, START, END)
    for frame in (miss, hit):
        # assert_frame_equal checks values, index and column names, index dtype and column dtypes.
        pd.testing.assert_frame_equal(frame, expected, check_exact=True)
        assert frame.index.name == "date"
        assert list(frame.columns.names) == ["symbol", "field"]
        assert frame.index.dtype == expected.index.dtype
        assert list(frame.dtypes.unique()) == ["float64"]
    assert hit["AAA"]["volume"].dtype == "float64"
    pd.testing.assert_frame_equal(miss, hit, check_exact=True)


def test_repeated_request_is_served_from_cache(tmp_path: Path) -> None:
    cached, fake = make(tmp_path)
    cached.get_prices(SYMBOLS, START, END)
    assert len(fake.calls) == 1
    cached.get_prices(SYMBOLS, START, END)
    cached.get_prices(SYMBOLS[::-1], START, END)
    assert len(fake.calls) == 1


def test_files_are_parquet_per_symbol_under_provider_dir(tmp_path: Path) -> None:
    cached, _ = make(tmp_path)
    cached.get_prices(["AAA", "BBB"], START, END)
    names = sorted(p.name for p in (tmp_path / "fake").iterdir())
    assert names == ["AAA_2024-01-02_2024-03-29.parquet", "BBB_2024-01-02_2024-03-29.parquet"]


def test_different_range_is_a_miss(tmp_path: Path) -> None:
    cached, fake = make(tmp_path)
    cached.get_prices(["AAA"], START, END)
    cached.get_prices(["AAA"], START, date(2024, 3, 28))
    assert len(fake.calls) == 2


def test_only_missing_symbols_are_fetched(tmp_path: Path) -> None:
    cached, fake = make(tmp_path)
    cached.get_prices(["AAA"], START, END)
    frame = cached.get_prices(["AAA", "BBB"], START, END)
    assert fake.calls[-1][0] == ("BBB",)
    pd.testing.assert_frame_equal(frame, FakeProvider().get_prices(["AAA", "BBB"], START, END))


def test_unknown_symbol_error_passes_through_and_nothing_is_cached(tmp_path: Path) -> None:
    cached, _ = make(tmp_path)
    with pytest.raises(DataUnavailableError):
        cached.get_prices(["AAA", "NOPE"], START, END)
    assert not list(tmp_path.rglob("*.parquet"))


def test_refresh_downloads_again_and_overwrites(tmp_path: Path) -> None:
    cached, fake = make(tmp_path)
    cached.get_prices(["AAA"], START, END)
    refreshing = CachedProvider(fake, cache_dir=tmp_path, refresh=True, today=lambda: TODAY)
    refreshing.get_prices(["AAA"], START, END)
    assert len(fake.calls) == 2
    # A new, non-refreshing provider still finds a valid file.
    CachedProvider(fake, cache_dir=tmp_path, today=lambda: TODAY).get_prices(["AAA"], START, END)
    assert len(fake.calls) == 2


def test_offline_miss_raises_clear_error_without_inner_call(tmp_path: Path) -> None:
    cached, fake = make(tmp_path, offline=True)
    with pytest.raises(OfflineCacheMissError, match="AAA"):
        cached.get_prices(["AAA"], START, END)
    assert fake.calls == []


def test_offline_serves_cached_data(tmp_path: Path) -> None:
    online, fake = make(tmp_path)
    expected = online.get_prices(SYMBOLS, START, END)
    offline = CachedProvider(fake, cache_dir=tmp_path, offline=True, today=lambda: TODAY)
    pd.testing.assert_frame_equal(offline.get_prices(SYMBOLS, START, END), expected)
    assert len(fake.calls) == 1


def test_offline_partial_cache_names_only_the_missing_symbols(tmp_path: Path) -> None:
    online, fake = make(tmp_path)
    online.get_prices(["AAA"], START, END)
    offline = CachedProvider(fake, cache_dir=tmp_path, offline=True, today=lambda: TODAY)
    with pytest.raises(OfflineCacheMissError) as info:
        offline.get_prices(["AAA", "BBB"], START, END)
    assert "['BBB']" in str(info.value)


def test_offline_and_refresh_are_exclusive(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        CachedProvider(FakeProvider(), cache_dir=tmp_path, offline=True, refresh=True)


def test_corrupt_cache_file_is_a_miss_online_and_an_error_offline(tmp_path: Path) -> None:
    cached, fake = make(tmp_path)
    cached.get_prices(["AAA"], START, END)
    (path,) = (tmp_path / "fake").glob("AAA_*.parquet")
    path.write_bytes(b"not parquet")
    offline = CachedProvider(fake, cache_dir=tmp_path, offline=True, today=lambda: TODAY)
    with pytest.raises(OfflineCacheMissError):
        offline.get_prices(["AAA"], START, END)
    cached.get_prices(["AAA"], START, END)
    assert len(fake.calls) == 2
    cached.get_prices(["AAA"], START, END)
    assert len(fake.calls) == 2


def test_cache_dir_is_configurable_and_defaults_to_data_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert DEFAULT_CACHE_DIR == Path("data/cache")
    monkeypatch.chdir(tmp_path)
    CachedProvider(FakeProvider(), today=lambda: TODAY).get_prices(["AAA"], START, END)
    assert (tmp_path / "data" / "cache" / "fake" / "AAA_2024-01-02_2024-03-29.parquet").exists()
    custom = tmp_path / "elsewhere" / "cache"
    CachedProvider(FakeProvider(), cache_dir=str(custom), today=lambda: TODAY).get_prices(["AAA"], START, END)
    assert (custom / "fake" / "AAA_2024-01-02_2024-03-29.parquet").exists()


def test_special_characters_in_symbols_are_safe_in_file_names(tmp_path: Path) -> None:
    cached = CachedProvider(FakeProvider(symbols=("^GSPC", "SAP.DE")), cache_dir=tmp_path, today=lambda: TODAY)
    cached.get_prices(["^GSPC", "SAP.DE"], START, END)
    names = sorted(p.name for p in (tmp_path / "fake").iterdir())
    assert names == ["%5EGSPC_2024-01-02_2024-03-29.parquet", "SAP.DE_2024-01-02_2024-03-29.parquet"]


def test_no_temp_files_are_left_behind(tmp_path: Path) -> None:
    cached, _ = make(tmp_path)
    cached.get_prices(SYMBOLS, START, END)
    assert not list(tmp_path.rglob("*.tmp"))


# Requests that end today or later are never cached: the bar of the current day is partial.


@pytest.mark.parametrize("today", [END, date(2024, 3, 28), date(2024, 1, 2)])
def test_end_today_or_in_the_future_is_never_cached(tmp_path: Path, today: date) -> None:
    cached, fake = make(tmp_path, today=lambda: today)
    cached.get_prices(["AAA"], START, END)
    cached.get_prices(["AAA"], START, END)
    assert len(fake.calls) == 2
    assert not list(tmp_path.rglob("*.parquet"))


def test_end_yesterday_is_cached(tmp_path: Path) -> None:
    cached, fake = make(tmp_path, today=lambda: date(2024, 3, 30))
    cached.get_prices(["AAA"], START, END)
    cached.get_prices(["AAA"], START, END)
    assert len(fake.calls) == 1


def test_today_is_evaluated_on_every_request(tmp_path: Path) -> None:
    clock = {"today": END}
    cached, fake = make(tmp_path, today=lambda: clock["today"])
    cached.get_prices(["AAA"], START, END)  # end == today: not written
    clock["today"] = date(2024, 3, 30)
    cached.get_prices(["AAA"], START, END)  # now a past request: fetched and written
    cached.get_prices(["AAA"], START, END)  # served from cache
    assert len(fake.calls) == 2


def test_uncacheable_request_goes_to_the_inner_provider_despite_existing_files(tmp_path: Path) -> None:
    cached, fake = make(tmp_path)
    cached.get_prices(["AAA"], START, END)
    later = CachedProvider(fake, cache_dir=tmp_path, today=lambda: END)
    later.get_prices(["AAA"], START, END)
    assert len(fake.calls) == 2


def test_offline_with_end_today_raises(tmp_path: Path) -> None:
    cached, fake = make(tmp_path, offline=True, today=lambda: END)
    with pytest.raises(OfflineCacheMissError, match="never cached"):
        cached.get_prices(["AAA"], START, END)
    assert fake.calls == []


def test_default_clock_is_the_real_today(tmp_path: Path) -> None:
    cached = CachedProvider(FakeProvider(), cache_dir=tmp_path)
    cached.get_prices(["AAA"], START, END)  # far in the past: cached with the real clock
    assert list(tmp_path.rglob("*.parquet"))


# The cache on top of the yfinance provider (mocked).


def test_yfinance_second_request_makes_no_network_call(tmp_path: Path, mock_yf: MockYFinance) -> None:
    cached = CachedProvider(YFinanceProvider(), cache_dir=tmp_path, today=lambda: TODAY)
    first = cached.get_prices(["AAA", "BBB.DE", "CCC"], START, END)
    assert len(mock_yf.calls) == 3
    second = cached.get_prices(["AAA", "BBB.DE", "CCC"], START, END)
    assert len(mock_yf.calls) == 3
    pd.testing.assert_frame_equal(first, second, check_exact=True)
    assert (tmp_path / "yfinance").is_dir()
