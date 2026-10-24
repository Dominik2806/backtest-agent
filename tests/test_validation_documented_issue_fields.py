"""The claims of docs/data.md about the fields of an issue, its ``first_dates``, its count and the order of issues.

Pinned here because the command line prints them (docs/cli.md): the field of every code, the one date of ``starts_late``
and ``ends_early``, the date of a gap or a move, the counting rule of the range checks and the generation order.
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from backtest_agent.data import FIELDS, ValidationConfig
from backtest_agent.data.checks import validate_prices
from test_validation_checks import OHLC, blank, clean, codes, run, scale_from

# docs/data.md, "Details that matter": None for the frame-level issues and for these four codes, else the field named
FIELD_OF_CODE = {
    "unsorted_dates": None,
    "duplicate_dates": None,
    "no_data": None,
    "calendar_gap": None,
    "starts_late": None,
    "ends_early": None,
    "non_finite_value": "open",  # the affected field
    "nan_in_history": "high",  # the affected field
    "non_positive_price": "low",  # the affected field
    "negative_volume": "volume",
    "nan_volume": "volume",
    "zero_volume": "volume",
    "ohlc_high_below_low": "high",
    "ohlc_close_outside_range": "close",
    "ohlc_open_outside_range": "open",
    "extreme_move": "close",
    "stale_price": "close",
    "split_artifact": "close",
}
CHECK_TABLE_CODES = {  # the codes of the checks table of docs/data.md
    "unsorted_dates",
    "duplicate_dates",
    "no_data",
    "non_finite_value",
    "nan_in_history",
    "non_positive_price",
    "negative_volume",
    "nan_volume",
    "ohlc_high_below_low",
    "ohlc_close_outside_range",
    "ohlc_open_outside_range",
    "calendar_gap",
    "extreme_move",
    "stale_price",
    "split_artifact",
    "zero_volume",
    "starts_late",
    "ends_early",
}


def set_value(frame: pd.DataFrame, position: int, symbol: str, field: str, value: float) -> pd.DataFrame:
    frame.loc[frame.index[position], (symbol, field)] = value
    return frame


def unsorted() -> pd.DataFrame:
    frame = clean()
    order = list(range(len(frame)))
    order[20], order[21] = order[21], order[20]
    return frame.iloc[order]


def duplicated() -> pd.DataFrame:
    frame = clean()
    order = list(range(len(frame)))
    order.insert(6, 5)
    return frame.iloc[order]


def no_data() -> pd.DataFrame:
    frame = clean()
    frame["BBB"] = np.nan
    return frame


def stale() -> pd.DataFrame:
    frame = clean()
    for position in range(10, 15):
        for field in OHLC:
            set_value(frame, position, "AAA", field, 77.0)
    return frame


def high_below_low() -> pd.DataFrame:
    frame = clean()
    row = frame.index[3]
    low = frame.loc[row, ("AAA", "low")]
    frame.loc[row, ("AAA", "high")] = low * 0.5
    return frame


def outside(field: str) -> pd.DataFrame:
    frame = clean()
    row = frame.index[3]
    frame.loc[row, ("AAA", field)] = frame.loc[row, ("AAA", "high")] * 1.5
    return frame


BUILDERS = {
    "unsorted_dates": unsorted,
    "duplicate_dates": duplicated,
    "no_data": no_data,
    "non_finite_value": lambda: set_value(clean(), 3, "AAA", "open", np.inf),
    "nan_in_history": lambda: set_value(clean(), 3, "AAA", "high", np.nan),
    "non_positive_price": lambda: set_value(clean(), 3, "AAA", "low", 0.0),
    "negative_volume": lambda: set_value(clean(), 3, "AAA", "volume", -1.0),
    "nan_volume": lambda: set_value(clean(), 3, "AAA", "volume", np.nan),
    "zero_volume": lambda: set_value(clean(), 3, "AAA", "volume", 0.0),
    "ohlc_high_below_low": high_below_low,
    "ohlc_close_outside_range": lambda: outside("close"),
    "ohlc_open_outside_range": lambda: outside("open"),
    "calendar_gap": lambda: blank(clean(), "AAA", range(40, 45)),
    "extreme_move": lambda: scale_from(clean(), "AAA", 50, 1.5),
    "stale_price": stale,
    "split_artifact": lambda: scale_from(clean(), "AAA", 50, 2.0),
    "starts_late": lambda: blank(clean(), "AAA", range(0, 10)),
    "ends_early": lambda: blank(clean(), "AAA", range(len(clean()) - 10, len(clean()))),
}


def test_the_table_of_fields_covers_every_code_of_the_checks_table() -> None:
    assert set(FIELD_OF_CODE) == CHECK_TABLE_CODES == set(BUILDERS)


@pytest.mark.parametrize("code", sorted(CHECK_TABLE_CODES))
def test_every_code_names_the_documented_field(code: str) -> None:
    result = run(BUILDERS[code]())
    issues = [issue for issue in result.issues if issue.code == code]
    assert issues, f"the frame of {code} did not raise it: {codes(result)}"
    assert {issue.field for issue in issues} == {FIELD_OF_CODE[code]}
    frame_level = code in ("unsorted_dates", "duplicate_dates")
    assert all((issue.symbol is None) == frame_level for issue in issues)


@pytest.mark.parametrize("code", ["extreme_move", "split_artifact"])
def test_the_date_of_a_move_is_the_row_where_the_move_ends(code: str) -> None:
    frame = BUILDERS[code]()
    (issue,) = [i for i in run(frame).issues if i.code == code]
    assert issue.first_dates == (frame.index[50].date(),)  # the jump is between rows 49 and 50


def test_the_date_of_a_gap_is_the_row_where_the_gap_ends() -> None:
    frame = BUILDERS["calendar_gap"]()
    (issue,) = [i for i in run(frame).issues if i.code == "calendar_gap"]
    assert issue.first_dates == (frame.index[45].date(),)  # rows 40 to 44 are missing


def test_the_dates_of_a_stale_run_are_the_rows_in_the_run() -> None:
    frame = stale()
    (issue,) = [i for i in run(frame).issues if i.code == "stale_price"]
    assert issue.count == 5
    assert issue.first_dates == tuple(frame.index[p].date() for p in range(10, 15))


def test_a_symbol_without_data_has_no_dates() -> None:
    (issue,) = [i for i in run(no_data()).issues if i.code == "no_data"]
    assert (issue.count, issue.first_dates) == (0, ())


# --- starts_late and ends_early: one date, and the counting rule ---


def prices(dates: list[str]) -> pd.DataFrame:
    """One symbol with a row on each given date (open = high = low = close, volume 1000)."""
    index = pd.DatetimeIndex(pd.to_datetime(dates).values, name="date")
    values = np.arange(1, len(index) + 1, dtype="float64") + 100
    data = np.column_stack([values, values, values, values, np.full(len(index), 1000.0)])
    columns = pd.MultiIndex.from_product([["AAA"], FIELDS], names=["symbol", "field"])
    return pd.DataFrame(data, index=index, columns=columns)


STRICT = ValidationConfig(range_tolerance_business_days=0)  # so that the small counts below fire


def range_issues(frame: pd.DataFrame, start: str, end: str):
    result = validate_prices(frame, STRICT, date.fromisoformat(start), date.fromisoformat(end))
    return [(i.code, i.count, i.first_dates) for i in result.issues if i.code in ("starts_late", "ends_early")]


def test_starts_late_has_exactly_one_date_the_first_data_date_whatever_the_count() -> None:
    # data from Thursday 2024-01-11 (rows 11, 12, 15, 16, 17), requested from Tuesday 2024-01-02
    frame = prices(["2024-01-11", "2024-01-12", "2024-01-15", "2024-01-16", "2024-01-17"])
    assert range_issues(frame, "2024-01-02", "2024-01-17") == [("starts_late", 7, (date(2024, 1, 11),))]


def test_ends_early_has_exactly_one_date_the_last_data_date_whatever_the_count() -> None:
    frame = prices(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"])
    assert range_issues(frame, "2024-01-02", "2024-01-17") == [("ends_early", 7, (date(2024, 1, 8),))]


def test_starts_late_counts_from_start_included_to_the_first_data_date_not_included() -> None:
    days = ["2024-01-03", "2024-01-04"]  # data from Wednesday
    assert range_issues(prices(days), "2024-01-03", "2024-01-04") == []  # start itself is the first data date: 0
    assert range_issues(prices(days), "2024-01-02", "2024-01-04") == [("starts_late", 1, (date(2024, 1, 3),))]
    # start included: Tuesday 2024-01-02 counts, the first data date (Wednesday) does not
    assert range_issues(prices(days), "2024-01-01", "2024-01-04") == [("starts_late", 2, (date(2024, 1, 3),))]


def test_a_weekend_start_counts_no_business_day_of_its_own() -> None:
    days = ["2024-01-08", "2024-01-09"]  # data from Monday
    assert range_issues(prices(days), "2024-01-06", "2024-01-09") == []  # Saturday start: nothing missing
    assert range_issues(prices(days), "2024-01-05", "2024-01-09") == [("starts_late", 1, (date(2024, 1, 8),))]  # Friday


def test_ends_early_counts_from_the_day_after_the_last_data_date_to_end_included() -> None:
    days = ["2024-01-02", "2024-01-03"]  # data until Wednesday
    assert range_issues(prices(days), "2024-01-02", "2024-01-03") == []  # end is the last data date: 0
    assert range_issues(prices(days), "2024-01-02", "2024-01-04") == [("ends_early", 1, (date(2024, 1, 3),))]
    assert range_issues(prices(days), "2024-01-02", "2024-01-05") == [("ends_early", 2, (date(2024, 1, 3),))]


def test_a_weekend_end_counts_no_business_day_of_its_own() -> None:
    days = ["2024-01-04", "2024-01-05"]  # data until Friday
    assert range_issues(prices(days), "2024-01-04", "2024-01-07") == []  # Sunday end: Saturday and Sunday do not count
    assert range_issues(prices(days), "2024-01-04", "2024-01-08") == [("ends_early", 1, (date(2024, 1, 5),))]  # Monday


def test_the_issue_fires_only_above_the_tolerance() -> None:
    frame = prices(["2024-01-05", "2024-01-08"])  # starts Friday: 3 business days after Tuesday 2024-01-02
    default = validate_prices(frame, None, date(2024, 1, 2), date(2024, 1, 8))
    assert [i.code for i in default.issues] == []  # 3 is tolerated (default 3)
    strict = validate_prices(frame, STRICT, date(2024, 1, 2), date(2024, 1, 8))
    assert [(i.code, i.count) for i in strict.issues] == [("starts_late", 3)]
    late = validate_prices(frame, None, date(2024, 1, 1), date(2024, 1, 8))  # Monday: 4 business days, above 3
    assert [(i.code, i.count) for i in late.issues] == [("starts_late", 4)]


# --- the order of the issues ---


def test_generation_order_is_frame_level_then_symbol_by_symbol_then_table_order_sorted_by_severity_only() -> None:
    frame = pd.concat([clean(), clean().iloc[[5]]])  # a repeated last row: unsorted_dates and duplicate_dates
    set_value(frame, 7, "AAA", "open", np.nan)  # AAA: error nan_in_history (open)
    set_value(frame, 9, "AAA", "close", -1.0)  # AAA: error non_positive_price (close)
    set_value(frame, 12, "AAA", "volume", np.nan)  # AAA: warning nan_volume
    set_value(frame, 14, "AAA", "volume", 0.0)  # AAA: info zero_volume
    set_value(frame, 20, "CCC", "close", np.nan)  # CCC (third column): error nan_in_history (close)
    set_value(frame, 22, "CCC", "volume", np.nan)  # CCC: warning nan_volume
    assert codes(run(frame)) == [
        # errors: frame-level, then AAA in table order (nan_in_history before non_positive_price), then CCC
        ("unsorted_dates", None, None),
        ("duplicate_dates", None, None),
        ("nan_in_history", "AAA", "open"),
        ("non_positive_price", "AAA", "close"),
        ("nan_in_history", "CCC", "close"),
        # warnings: AAA, then CCC
        ("nan_volume", "AAA", "volume"),
        ("nan_volume", "CCC", "volume"),
        # infos
        ("zero_volume", "AAA", "volume"),
    ]


def test_the_column_order_decides_not_the_name_of_the_symbol() -> None:
    frame = clean()[["CCC", "AAA"]]  # CCC first
    set_value(frame, 3, "AAA", "volume", np.nan)
    set_value(frame, 4, "CCC", "volume", np.nan)
    assert [(i.code, i.symbol) for i in run(frame).issues] == [("nan_volume", "CCC"), ("nan_volume", "AAA")]


def test_the_sort_by_severity_is_stable_inside_a_symbol_too() -> None:
    frame = blank(clean(), "AAA", range(0, 10))  # info starts_late (the last check of a symbol)
    set_value(frame, 13, "AAA", "volume", 0.0)  # info zero_volume (late in the table)
    set_value(frame, 14, "AAA", "volume", np.nan)  # warning nan_volume
    result = run(frame)
    assert [(i.severity.value, i.code) for i in result.issues] == [
        ("warning", "nan_volume"),
        ("info", "zero_volume"),
        ("info", "starts_late"),
    ]
