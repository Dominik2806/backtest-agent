from datetime import date

import numpy as np
import pandas as pd
import pytest

from backtest_agent.data import FIELDS, FakeProvider, Severity, ValidationConfig, ValidationIssue
from backtest_agent.data.checks import validate_prices

START = date(2024, 1, 2)  # Tuesday
END = date(2024, 6, 28)  # Friday
SYMBOLS = ["AAA", "BBB", "CCC"]
OHLC = ("open", "high", "low", "close")


def clean() -> pd.DataFrame:
    """Fresh clean frame from the fake provider: 129 Mon-Fri rows, three symbols."""
    return FakeProvider().get_prices(SYMBOLS, START, END)


def literal(closes: list[float], symbol: str = "AAA") -> pd.DataFrame:
    """Tiny frame with open = high = low = close, so OHLC is consistent by construction."""
    c = np.array(closes, dtype="float64")
    dates = pd.DatetimeIndex(pd.bdate_range("2024-01-02", periods=len(c)).values, name="date")
    columns = pd.MultiIndex.from_product([[symbol], FIELDS], names=["symbol", "field"])
    return pd.DataFrame(np.column_stack([c, c, c, c, np.full(len(c), 1000.0)]), index=dates, columns=columns)


def run(frame: pd.DataFrame, **config):
    return validate_prices(frame, ValidationConfig(**config) if config else None, START, END)


def codes(result) -> list[tuple[str, str | None, str | None]]:
    return [(i.code, i.symbol, i.field) for i in result.issues]


def only(result) -> ValidationIssue:
    assert len(result.issues) == 1, codes(result)
    return result.issues[0]


def scale_from(frame: pd.DataFrame, symbol: str, position: int, factor: float) -> pd.DataFrame:
    """Multiply all OHLC of one symbol by ``factor`` from row ``position`` on (a consistent price jump)."""
    for field in OHLC:
        frame.loc[frame.index[position] :, (symbol, field)] *= factor
    return frame


# --- baseline ---


def test_clean_fake_data_has_no_issues_at_all() -> None:
    result = run(clean())
    assert result.issues == ()
    result.raise_for_errors()


def test_clean_data_without_range_has_no_issues() -> None:
    assert validate_prices(clean()).issues == ()


# --- frame level: unsorted and duplicate dates (errors) ---


def test_unsorted_dates() -> None:
    frame = clean()
    order = list(range(len(frame)))
    order[20], order[21] = order[21], order[20]
    shuffled = frame.iloc[order]
    issue = only(run(shuffled))
    assert (issue.severity, issue.code, issue.symbol, issue.field) == (Severity.ERROR, "unsorted_dates", None, None)
    assert issue.count == 1
    assert issue.first_dates == (frame.index[20].date(),)


def test_duplicate_dates() -> None:
    frame = clean()
    order = list(range(len(frame)))
    order.insert(6, 5)  # row 5 appears twice, in place, so the index stays sorted
    issue = only(run(frame.iloc[order]))
    assert (issue.severity, issue.code, issue.symbol, issue.field) == (Severity.ERROR, "duplicate_dates", None, None)
    assert issue.count == 1
    assert issue.first_dates == (frame.index[5].date(),)


def test_duplicate_and_unsorted_are_both_reported_and_other_checks_use_the_cleaned_copy() -> None:
    frame = clean()
    broken = pd.concat([frame, frame.iloc[[5]]])  # duplicate appended at the end: also unsorted
    result = run(broken)
    assert codes(result) == [("unsorted_dates", None, None), ("duplicate_dates", None, None)]
    assert result.has_errors


# --- per symbol: errors ---


def test_symbol_without_any_data_is_an_error() -> None:
    frame = clean()
    frame["BBB"] = np.nan
    issue = only(run(frame))
    assert (issue.severity, issue.code, issue.symbol) == (Severity.ERROR, "no_data", "BBB")


def test_infinite_value() -> None:
    frame = clean()
    frame.loc[frame.index[3], ("AAA", "high")] = np.inf
    issue = only(run(frame))
    assert (issue.severity, issue.code, issue.symbol, issue.field) == (
        Severity.ERROR,
        "non_finite_value",
        "AAA",
        "high",
    )


@pytest.mark.parametrize("field", OHLC)
def test_nan_in_price_field_inside_history_is_an_error(field: str) -> None:
    frame = clean()
    frame.loc[frame.index[10], ("AAA", field)] = np.nan
    issue = only(run(frame))
    assert (issue.severity, issue.code, issue.symbol, issue.field) == (Severity.ERROR, "nan_in_history", "AAA", field)
    assert issue.count == 1
    assert issue.first_dates == (frame.index[10].date(),)


@pytest.mark.parametrize("value", [0.0, -5.0])
def test_non_positive_price(value: float) -> None:
    frame = clean()
    frame.loc[frame.index[7], ("CCC", "close")] = value
    issue = only(run(frame))
    assert (issue.severity, issue.code, issue.symbol, issue.field) == (
        Severity.ERROR,
        "non_positive_price",
        "CCC",
        "close",
    )


def test_negative_volume() -> None:
    frame = clean()
    frame.loc[frame.index[7], ("AAA", "volume")] = -1.0
    issue = only(run(frame))
    assert (issue.severity, issue.code, issue.field) == (Severity.ERROR, "negative_volume", "volume")


# --- volume: NaN is a warning, zero is info, always one summary issue per symbol and field ---


def test_nan_volume_is_a_warning_not_an_error() -> None:
    frame = clean()
    frame.loc[frame.index[10], ("AAA", "volume")] = np.nan
    result = run(frame)
    issue = only(result)
    assert (issue.severity, issue.code, issue.symbol, issue.field) == (Severity.WARNING, "nan_volume", "AAA", "volume")
    assert issue.count == 1
    assert not result.has_errors
    result.raise_for_errors()


def test_volume_nan_on_every_row_gives_one_summary_issue_and_no_error() -> None:
    frame = clean()
    frame[("BBB", "volume")] = np.nan  # an index or an FX pair without volume
    result = run(frame)
    issue = only(result)
    assert (issue.severity, issue.code, issue.symbol, issue.field) == (Severity.WARNING, "nan_volume", "BBB", "volume")
    assert issue.count == len(frame)
    assert "every row" in issue.message
    assert len(issue.first_dates) == 5
    assert not result.has_errors


def test_volume_zero_on_every_row_gives_one_summary_issue() -> None:
    frame = clean()
    frame[("CCC", "volume")] = 0.0
    issue = only(run(frame))
    assert (issue.severity, issue.code, issue.symbol, issue.field) == (Severity.INFO, "zero_volume", "CCC", "volume")
    assert issue.count == len(frame)
    assert "every row" in issue.message


def test_two_symbols_without_usable_volume_give_exactly_one_issue_each() -> None:
    frame = clean()
    frame[("AAA", "volume")] = np.nan
    frame[("CCC", "volume")] = 0.0
    result = run(frame)
    assert codes(result) == [("nan_volume", "AAA", "volume"), ("zero_volume", "CCC", "volume")]
    assert [i.count for i in result.issues] == [len(frame), len(frame)]
    assert not result.has_errors


def test_some_zero_volume_days_are_one_info_with_a_count() -> None:
    frame = clean()
    for position in (4, 9, 15):
        frame.loc[frame.index[position], ("AAA", "volume")] = 0.0
    issue = only(run(frame))
    assert (issue.severity, issue.code, issue.count) == (Severity.INFO, "zero_volume", 3)
    assert issue.first_dates == tuple(frame.index[p].date() for p in (4, 9, 15))
    assert "every row" not in issue.message


# --- OHLC consistency (warnings, with tolerance) ---


def test_high_below_low() -> None:
    frame = clean()
    position = 4
    high, low = frame.loc[frame.index[position], ("AAA", "high")], frame.loc[frame.index[position], ("AAA", "low")]
    frame.loc[frame.index[position], ("AAA", "high")] = low
    frame.loc[frame.index[position], ("AAA", "low")] = high  # swapped, open and close stay inside
    issue = only(run(frame))
    assert (issue.severity, issue.code, issue.symbol, issue.field) == (
        Severity.WARNING,
        "ohlc_high_below_low",
        "AAA",
        "high",
    )


@pytest.mark.parametrize(
    ("field", "reference", "factor", "code"),
    [("close", "high", 1.05, "ohlc_close_outside_range"), ("open", "low", 0.95, "ohlc_open_outside_range")],
)
def test_open_or_close_outside_high_low_range(field: str, reference: str, factor: float, code: str) -> None:
    frame = clean()
    row = frame.index[12]
    frame.loc[row, ("BBB", field)] = frame.loc[row, ("BBB", reference)] * factor
    issue = only(run(frame))
    assert (issue.severity, issue.code, issue.symbol, issue.field) == (Severity.WARNING, code, "BBB", field)


def test_ohlc_tolerance_boundary() -> None:
    frame = clean()
    row = frame.index[12]
    frame.loc[row, ("BBB", "close")] = frame.loc[row, ("BBB", "high")] * 1.0005  # inside the 0.1 percent tolerance
    assert run(frame).issues == ()
    frame.loc[row, ("BBB", "close")] = frame.loc[row, ("BBB", "high")] * 1.002
    assert codes(run(frame)) == [("ohlc_close_outside_range", "BBB", "close")]
    assert run(frame, ohlc_tolerance=0.01).issues == ()


# --- calendar gaps (heuristic: missing Mon-Fri days between a symbol's own data dates) ---


def blank(frame: pd.DataFrame, symbol: str, positions: range) -> pd.DataFrame:
    for field in FIELDS:
        frame.loc[frame.index[list(positions)], (symbol, field)] = np.nan
    return frame


def test_gap_of_more_than_four_business_days_in_a_multi_symbol_frame() -> None:
    frame = blank(clean(), "AAA", range(40, 45))  # 5 missing days, the rows stay in the index as all-NaN
    issue = only(run(frame))
    assert (issue.severity, issue.code, issue.symbol) == (Severity.WARNING, "calendar_gap", "AAA")
    assert issue.count == 1
    assert issue.first_dates == (frame.index[45].date(),)


def test_gap_of_exactly_four_business_days_is_fine() -> None:
    assert run(blank(clean(), "AAA", range(40, 44))).issues == ()


def test_gap_in_a_single_symbol_frame_where_rows_are_absent() -> None:
    frame = clean()[["AAA"]]
    assert codes(run(frame.drop(index=frame.index[40:45]))) == [("calendar_gap", "AAA", None)]
    assert run(frame.drop(index=frame.index[40:44])).issues == ()


def test_weekends_do_not_count_as_missing_days() -> None:
    frame = clean()[["AAA"]]
    thursday = int(np.flatnonzero(frame.index.dayofweek == 3)[3])
    four = frame.drop(index=frame.index[thursday : thursday + 4])  # Thu, Fri, Mon, Tue
    five = frame.drop(index=frame.index[thursday : thursday + 5])  # plus Wed
    assert run(four).issues == ()
    assert codes(run(five)) == [("calendar_gap", "AAA", None)]


def test_isolated_missing_days_of_one_exchange_are_not_issues() -> None:
    frame = clean()
    for position in (10, 20, 30, 40, 50):  # holidays of one market while the others trade
        blank(frame, "BBB", range(position, position + 1))
    assert run(frame).issues == ()


def test_gap_limit_is_configurable() -> None:
    frame = blank(clean(), "AAA", range(40, 43))  # 3 missing days
    assert run(frame).issues == ()
    assert codes(run(frame, max_gap_business_days=2)) == [("calendar_gap", "AAA", None)]


# --- extreme moves ---


def test_extreme_move_above_forty_percent() -> None:
    frame = scale_from(clean(), "AAA", 50, 1.5)
    issue = only(run(frame))
    assert (issue.severity, issue.code, issue.symbol, issue.field) == (Severity.WARNING, "extreme_move", "AAA", "close")
    assert issue.count == 1
    assert issue.first_dates == (frame.index[50].date(),)


@pytest.mark.parametrize(
    ("closes", "fires"),
    [([100.0, 140.0], False), ([100.0, 141.0], True), ([100.0, 61.0], False), ([100.0, 59.0], True)],
)
def test_extreme_move_boundary(closes: list[float], fires: bool) -> None:
    assert (codes(validate_prices(literal(closes))) == [("extreme_move", "AAA", "close")]) is fires


def test_extreme_move_threshold_is_configurable() -> None:
    frame = literal([100.0, 130.0])
    assert validate_prices(frame).issues == ()
    assert codes(validate_prices(frame, ValidationConfig(max_daily_move=0.25))) == [("extreme_move", "AAA", "close")]


# --- stale prices ---


def test_stale_run_of_five_identical_closes() -> None:
    result = validate_prices(literal([100.0, 101.0, 102.0, 102.0, 102.0, 102.0, 102.0, 103.0, 104.0]))
    issue = only(result)
    assert (issue.severity, issue.code, issue.symbol, issue.field) == (Severity.WARNING, "stale_price", "AAA", "close")
    assert issue.count == 5


def test_stale_run_of_four_is_fine_and_the_limit_is_configurable() -> None:
    frame = literal([100.0, 101.0, 102.0, 102.0, 102.0, 102.0, 103.0, 104.0])
    assert validate_prices(frame).issues == ()
    assert codes(validate_prices(frame, ValidationConfig(stale_run_length=4))) == [("stale_price", "AAA", "close")]


def test_stale_in_fake_data() -> None:
    frame = clean()
    for field in OHLC:
        frame.loc[frame.index[30:35], ("AAA", field)] = frame.loc[frame.index[30], ("AAA", "close")]
    issue = only(run(frame))
    assert (issue.code, issue.symbol, issue.count) == ("stale_price", "AAA", 5)
    assert issue.first_dates == tuple(d.date() for d in frame.index[30:35])


# --- split artifacts (a split-sized jump is also an extreme move) ---


@pytest.mark.parametrize("factor", [1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 10, 2.0, 3.0, 4.0, 5.0, 10.0])
def test_split_ratio_jump_fires_split_artifact_and_extreme_move(factor: float) -> None:
    frame = scale_from(clean(), "AAA", 60, factor)
    result = run(frame)
    assert codes(result) == [("extreme_move", "AAA", "close"), ("split_artifact", "AAA", "close")]
    assert all(i.severity is Severity.WARNING and i.count == 1 for i in result.issues)
    assert all(i.first_dates == (frame.index[60].date(),) for i in result.issues)


def test_a_jump_that_is_no_split_ratio_is_only_an_extreme_move() -> None:
    assert codes(run(scale_from(clean(), "AAA", 60, 1.5))) == [("extreme_move", "AAA", "close")]


def test_split_ratios_are_configurable() -> None:
    frame = scale_from(clean(), "AAA", 60, 1.5)
    result = run(frame, split_ratios=(1.5,))
    assert codes(result) == [("extreme_move", "AAA", "close"), ("split_artifact", "AAA", "close")]


# --- info: data starts late or ends early compared to the requested range ---


def test_starts_late_is_info_with_missing_business_days() -> None:
    frame = blank(clean(), "AAA", range(0, 10))  # leading all-NaN rows are not NaN errors
    issue = only(run(frame))
    assert (issue.severity, issue.code, issue.symbol) == (Severity.INFO, "starts_late", "AAA")
    assert issue.count == 10
    assert issue.first_dates == (frame.index[10].date(),)


def test_ends_early_is_info_with_missing_business_days() -> None:
    frame = blank(clean(), "AAA", range(len(clean()) - 10, len(clean())))
    issue = only(run(frame))
    assert (issue.severity, issue.code, issue.symbol, issue.count) == (Severity.INFO, "ends_early", "AAA", 10)
    assert issue.first_dates == (frame.index[-11].date(),)


def test_range_tolerance_boundary() -> None:
    assert run(blank(clean(), "AAA", range(0, 3))).issues == ()  # 3 business days late is tolerated
    assert codes(run(blank(clean(), "AAA", range(0, 4)))) == [("starts_late", "AAA", None)]


def test_range_checks_are_skipped_without_start_and_end() -> None:
    frame = blank(clean(), "AAA", range(0, 10))
    assert validate_prices(frame).issues == ()


# --- general behaviour ---


def test_first_dates_are_limited_and_ascending() -> None:
    frame = clean()
    for position in range(8):
        frame.loc[frame.index[position + 3], ("AAA", "volume")] = 0.0
    issue = only(run(frame))
    assert issue.count == 8
    assert issue.first_dates == tuple(frame.index[p].date() for p in range(3, 8))
    assert len(only(run(frame, max_dates_per_issue=2)).first_dates) == 2


def test_errors_come_first_and_the_frame_is_never_modified() -> None:
    frame = clean()
    frame.loc[frame.index[3], ("AAA", "volume")] = 0.0  # info
    scale_from(frame, "BBB", 50, 1.5)  # warning
    frame.loc[frame.index[7], ("CCC", "close")] = 0.0  # error
    frame = frame.iloc[[*range(10), 9, *range(10, len(frame))]]  # duplicate date, error
    before = frame.copy(deep=True)
    result = run(frame)
    assert [i.severity for i in result.issues] == [Severity.ERROR, Severity.ERROR, Severity.WARNING, Severity.INFO]
    pd.testing.assert_frame_equal(frame, before, check_exact=True)
    assert frame.index.equals(before.index)


def test_validation_is_deterministic() -> None:
    frame = scale_from(clean(), "AAA", 50, 1.5)
    first, second = run(frame), run(frame)
    assert first == second
    assert first.to_json() == second.to_json()


def test_input_errors_raise_value_error() -> None:
    frame = clean()
    flat = frame["AAA"].copy()
    missing_field = frame.drop(columns=[("AAA", "volume")])
    text = frame.astype(object)
    text.iloc[0, 0] = "x"
    for bad in (
        frame.tz_localize("UTC"),
        flat,
        missing_field,
        text,
        frame.iloc[:0],
        frame.rename_axis(columns=["a", "b"]),
        "not a frame",
    ):
        with pytest.raises(ValueError):
            validate_prices(bad)
    with pytest.raises(ValueError):
        validate_prices(frame, None, END, START)
