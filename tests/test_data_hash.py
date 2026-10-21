import hashlib
import re
import struct
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest_agent.data import FIELDS, FakeProvider
from backtest_agent.data.cache import CachedProvider
from backtest_agent.data.hash import HASH_VERSION, hash_frame

START = date(2024, 1, 2)
END = date(2024, 3, 29)

# Digest of golden_frame(); hard-coded on purpose. If this test fails, the byte layout of hash_frame changed:
# bump HASH_VERSION, write an ADR, and only then update this value (see ADR 0005).
GOLDEN_HASH = "fc459a1ebd97e068d7594c64c5c06a328fc3cd05c29af5037c71d8a150c2806b"


def dates(*days: str) -> pd.DatetimeIndex:
    """Standard index: pandas 3 infers microseconds from strings, the standard format is nanoseconds."""
    return pd.DatetimeIndex(days, name="date").astype("datetime64[ns]")


def golden_frame() -> pd.DataFrame:
    """Small fixed frame from literal values: two symbols, three days, one NaN row (other calendar)."""
    index = dates("2024-01-02", "2024-01-03", "2024-01-04")
    columns = pd.MultiIndex.from_product([["AAA", "BBB.DE"], FIELDS], names=["symbol", "field"])
    nan = np.nan
    data = [
        [10.0, 11.0, 9.5, 10.5, 1000.0, 20.0, 21.0, 19.0, 20.5, 500.0],
        [10.5, 12.0, 10.0, 11.5, 1500.0, nan, nan, nan, nan, nan],
        [11.5, 11.75, 11.0, 11.25, 1250.0, 20.5, 22.0, 20.25, 21.75, 750.0],
    ]
    return pd.DataFrame(data, index=index, columns=columns)


def fake_frame(symbols: list[str] | None = None) -> pd.DataFrame:
    return FakeProvider().get_prices(symbols or ["AAA", "BBB", "CCC"], START, END)


def test_golden_hash_is_stable() -> None:
    assert hash_frame(golden_frame()) == GOLDEN_HASH


def test_golden_hash_matches_an_independent_implementation_of_the_documented_layout() -> None:
    """Re-derives the digest from the documented byte layout without using hash_frame."""
    frame = golden_frame()
    h = hashlib.sha256(b"backtest-agent/frame-hash/v1\n")
    h.update(struct.pack("<QQ", 3, 2))
    for symbol in ("AAA", "BBB.DE"):
        for field in ("open", "high", "low", "close", "volume"):
            for text in (symbol, field):
                h.update(struct.pack("<Q", len(text)) + text.encode())
    for day in ("2024-01-02", "2024-01-03", "2024-01-04"):
        h.update(struct.pack("<q", (date.fromisoformat(day) - date(1970, 1, 1)).days))
    canonical_nan = struct.pack("<Q", 0x7FF8000000000000)
    for column in frame.columns:
        for value in frame[column]:
            h.update(canonical_nan if np.isnan(value) else struct.pack("<d", value))
    assert h.hexdigest() == hash_frame(frame)


def test_hash_format_and_version() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", hash_frame(fake_frame()))
    assert HASH_VERSION == "1"


def test_identical_data_gives_identical_hash_also_when_rebuilt() -> None:
    first = hash_frame(fake_frame())
    assert hash_frame(fake_frame()) == first
    assert hash_frame(fake_frame().copy(deep=True)) == first
    assert hash_frame(golden_frame()) == hash_frame(golden_frame())


def test_a_single_changed_value_changes_the_hash() -> None:
    frame = fake_frame()
    original = hash_frame(frame)
    changed = frame.copy()
    changed.iloc[10, 3] = np.nextafter(changed.iloc[10, 3], np.inf)  # one bit of one value
    assert hash_frame(changed) != original


def test_a_changed_date_changes_the_hash() -> None:
    frame = golden_frame()
    moved = frame.set_axis(dates("2024-01-02", "2024-01-03", "2024-01-05"))
    assert hash_frame(moved) != hash_frame(frame)


def test_a_different_row_count_changes_the_hash() -> None:
    frame = fake_frame()
    assert hash_frame(frame.iloc[:-1]) != hash_frame(frame)
    assert hash_frame(frame.iloc[1:]) != hash_frame(frame)


def test_symbol_and_field_names_change_the_hash() -> None:
    frame = golden_frame()
    renamed = frame.rename(columns={"AAA": "AAB"}, level="symbol")
    assert hash_frame(renamed) != hash_frame(frame)
    assert hash_frame(frame[["AAA"]]) != hash_frame(frame)


def test_symbol_request_order_does_not_change_the_hash() -> None:
    forward = hash_frame(fake_frame(["AAA", "BBB", "CCC"]))
    assert hash_frame(fake_frame(["CCC", "AAA", "BBB"])) == forward


def test_negative_zero_and_positive_zero_hash_equal() -> None:
    plus, minus = golden_frame(), golden_frame()
    plus.iloc[0, 4], minus.iloc[0, 4] = 0.0, -0.0
    assert np.signbit(minus.iloc[0, 4])
    assert hash_frame(plus) == hash_frame(minus)


def test_nan_with_different_bit_patterns_hash_equal() -> None:
    frame = golden_frame()
    other = golden_frame()
    column = other[("BBB.DE", "close")].to_numpy().copy()
    column.view("<u8")[1] = 0xFFF8000000000123  # negative NaN with a payload
    other[("BBB.DE", "close")] = column
    assert np.isnan(other.iloc[1, 8])
    assert hash_frame(other) == hash_frame(frame)


def test_nan_is_different_from_a_number() -> None:
    frame = golden_frame()
    changed = golden_frame()
    changed.iloc[1, 5] = 0.0
    assert hash_frame(changed) != hash_frame(frame)


def test_index_unit_does_not_matter() -> None:
    frame = golden_frame()
    as_seconds = frame.set_axis(frame.index.astype("datetime64[s]"))
    as_seconds.index.name = "date"
    expected = hash_frame(frame)
    # A frame with another datetime unit is not standard, so convert it back the way a provider would.
    assert hash_frame(as_seconds.set_axis(as_seconds.index.astype("datetime64[ns]"))) == expected


def test_malformed_frames_are_rejected() -> None:
    frame = fake_frame()
    for bad in (frame.iloc[::-1], frame.rename_axis("when"), frame.iloc[:0], frame["AAA"], frame.astype("float32")):
        with pytest.raises(ValueError):
            hash_frame(bad)


def test_cache_round_trip_keeps_the_hash(tmp_path: Path) -> None:
    cached = CachedProvider(FakeProvider(), cache_dir=tmp_path, today=lambda: date(2024, 7, 1))
    miss = cached.get_prices(["AAA", "BBB", "CCC"], START, END)
    hit = cached.get_prices(["AAA", "BBB", "CCC"], START, END)
    assert hash_frame(miss) == hash_frame(hit) == hash_frame(fake_frame())
