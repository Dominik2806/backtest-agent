import warnings

import pandas as pd

from backtest_agent.data import FIELDS, validate_standard_frame
from backtest_agent.data.provider import assemble_frame


def _prices(dates: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({field: range(1, len(dates) + 1) for field in FIELDS}, index=dates, dtype="float64")


def test_different_calendars_do_not_raise_the_concat_sorting_warning() -> None:
    us = pd.bdate_range("2024-03-25", "2024-03-29")
    de = us.delete(1)  # German holiday on 2024-03-26
    with warnings.catch_warnings():
        warnings.filterwarnings("error", message="Sorting by default when concatenating")
        frame = assemble_frame({"SAP.DE": _prices(de), "AAPL": _prices(us)})
    validate_standard_frame(frame, ["SAP.DE", "AAPL"])
    assert list(frame.index) == list(us)
    assert frame.loc["2024-03-26", "SAP.DE"].isna().all()


def test_result_is_sorted_even_if_the_second_symbol_has_earlier_dates() -> None:
    late = pd.bdate_range("2024-03-27", "2024-03-29")
    early = pd.bdate_range("2024-03-25", "2024-03-28")
    with warnings.catch_warnings():
        warnings.filterwarnings("error", message="Sorting by default when concatenating")
        frame = assemble_frame({"LATE": _prices(late), "EARLY": _prices(early)})
    validate_standard_frame(frame, ["LATE", "EARLY"])
    assert frame.index.is_monotonic_increasing
