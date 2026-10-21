from datetime import date, datetime

import pandas as pd
import pytest

from backtest_agent.data import DataUnavailableError, FakeProvider, validate_standard_frame
from backtest_agent.data.provider import FIELDS
from contract import check_provider_contract

START = date(2024, 1, 2)  # Tuesday
END = date(2024, 3, 29)  # Friday


def test_fake_provider_passes_contract() -> None:
    check_provider_contract(FakeProvider(), ["AAA", "BBB", "CCC"], START, END)


def test_same_seed_gives_identical_frames_and_other_seed_differs() -> None:
    a = FakeProvider(seed=1).get_prices(["AAA"], START, END)
    b = FakeProvider(seed=1).get_prices(["AAA"], START, END)
    c = FakeProvider(seed=2).get_prices(["AAA"], START, END)
    pd.testing.assert_frame_equal(a, b)
    assert not a.equals(c)


def test_symbols_have_different_prices_and_keep_request_order() -> None:
    frame = FakeProvider().get_prices(["CCC", "AAA"], START, END)
    validate_standard_frame(frame, ["CCC", "AAA"])
    assert not frame["CCC"]["close"].equals(frame["AAA"]["close"])


def test_prices_do_not_depend_on_the_requested_range() -> None:
    provider = FakeProvider()
    wide = provider.get_prices(["AAA"], date(2024, 1, 2), date(2024, 6, 28))
    narrow = provider.get_prices(["AAA"], date(2024, 2, 1), date(2024, 2, 29))
    pd.testing.assert_frame_equal(narrow, wide.loc["2024-02-01":"2024-02-29"])


def test_only_weekdays() -> None:
    frame = FakeProvider().get_prices(["AAA"], START, END)
    assert (frame.index.dayofweek < 5).all()


def test_unknown_symbol_raises() -> None:
    with pytest.raises(DataUnavailableError, match="ZZZ"):
        FakeProvider().get_prices(["AAA", "ZZZ"], START, END)


def test_weekend_only_range_raises() -> None:
    with pytest.raises(DataUnavailableError):
        FakeProvider().get_prices(["AAA"], date(2024, 1, 6), date(2024, 1, 7))


def test_calls_are_recorded() -> None:
    provider = FakeProvider()
    provider.get_prices(["AAA", "BBB"], START, END)
    assert provider.calls == [(("AAA", "BBB"), START, END)]


@pytest.mark.parametrize(
    ("symbols", "start", "end"),
    [
        ("AAA", START, END),
        ([], START, END),
        (["AAA", "AAA"], START, END),
        (["AAA"], END, START),
        (["AAA"], datetime(2024, 1, 2), END),
        (["AAA"], "2024-01-02", END),
    ],
)
def test_bad_arguments_raise_value_error(symbols, start, end) -> None:
    with pytest.raises(ValueError):
        FakeProvider().get_prices(symbols, start, end)


def test_frame_has_standard_fields_and_float64_volume() -> None:
    frame = FakeProvider().get_prices(["AAA"], START, END)
    assert list(frame["AAA"].columns) == list(FIELDS)
    assert frame["AAA"]["volume"].dtype == "float64"
    assert frame.index.name == "date"
    assert list(frame.columns.names) == ["symbol", "field"]
