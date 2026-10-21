from datetime import date

import pandas as pd
import pytest

from backtest_agent.data import DataProvider, FakeProvider, validate_standard_frame

START = date(2024, 1, 2)
END = date(2024, 3, 29)


def _valid() -> pd.DataFrame:
    return FakeProvider().get_prices(["AAA", "BBB"], START, END)


def test_provider_is_abstract() -> None:
    with pytest.raises(TypeError):
        DataProvider()  # type: ignore[abstract]


def test_validator_accepts_standard_frame() -> None:
    validate_standard_frame(_valid(), ["AAA", "BBB"])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda f: f.rename_axis("when"),
        lambda f: f.tz_localize("UTC"),
        lambda f: f.iloc[::-1],
        lambda f: f.iloc[:0],
        lambda f: f.set_axis(f.index + pd.Timedelta(hours=1)),
        lambda f: f.set_axis(pd.RangeIndex(len(f))),
        lambda f: f.set_axis(f.columns.set_names(["a", "b"]), axis=1),
        lambda f: f.drop(columns=[("AAA", "volume")]),
        lambda f: f[["BBB", "AAA"]],
        lambda f: f.astype("float32"),
        lambda f: pd.concat([f.iloc[:1], f]),
    ],
)
def test_validator_rejects_broken_frames(mutate) -> None:
    with pytest.raises(ValueError):
        validate_standard_frame(mutate(_valid()), ["AAA", "BBB"])
