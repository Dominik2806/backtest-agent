"""Data quality checks (see docs/data.md): ``validate_prices`` reports issues and never modifies the frame."""

from datetime import date

import numpy as np
import pandas as pd

from backtest_agent.data.provider import COLUMN_LEVELS, FIELDS
from backtest_agent.data.validation import Severity, ValidationConfig, ValidationIssue, ValidationResult

PRICE_FIELDS = ("open", "high", "low", "close")
ONE_DAY = np.timedelta64(1, "D")


def validate_prices(
    frame: pd.DataFrame,
    config: ValidationConfig | None = None,
    start: date | None = None,
    end: date | None = None,
) -> ValidationResult:
    """Check the data quality of a price frame and return all findings.

    ``frame`` needs the standard structure (tz-naive ``DatetimeIndex``, ``(symbol, field)`` columns with all five
    fields), otherwise ``ValueError`` is raised. Unsorted or duplicate dates are reported, not raised. Every
    per-symbol check only looks at rows where that symbol has data (at least one non-NaN field), because all-NaN
    rows are expected after the outer join of different trading calendars. ``start`` and ``end`` are the requested
    range, used for ``starts_late`` and ``ends_early``; without them these two checks are skipped.
    """
    config = config or ValidationConfig()
    _check_structure(frame)
    if start is not None and end is not None and start > end:
        raise ValueError(f"start {start} is after end {end}")

    issues: list[ValidationIssue] = []
    index = frame.index
    issues += _flag(
        Severity.ERROR,
        "unsorted_dates",
        None,
        None,
        index[1:],
        np.asarray(index[1:] < index[:-1]),
        config,
        "date(s) earlier than the row before",
    )
    issues += _flag(
        Severity.ERROR, "duplicate_dates", None, None, index, np.asarray(index.duplicated()), config, "repeated date(s)"
    )

    # Working copy: sorted, first occurrence of a duplicate date. The caller's frame is never touched.
    work = frame[~index.duplicated(keep="first")].sort_index()
    for symbol in dict.fromkeys(work.columns.get_level_values("symbol")):
        values = work.xs(symbol, axis=1, level="symbol")[list(FIELDS)].astype("float64")
        rows = values[values.notna().any(axis=1)]
        issues += _symbol_issues(str(symbol), rows, config, start, end)
    return ValidationResult(tuple(issues), config)


def _check_structure(frame: pd.DataFrame) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("frame must be a pandas DataFrame")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is not None:
        raise ValueError("index must be a timezone-naive DatetimeIndex")
    columns = frame.columns
    if not isinstance(columns, pd.MultiIndex) or list(columns.names) != COLUMN_LEVELS:
        raise ValueError(f"columns must be a MultiIndex named {COLUMN_LEVELS}")
    if not columns.is_unique:
        raise ValueError("columns must be unique")
    for symbol in dict.fromkeys(columns.get_level_values("symbol")):
        if set(columns[columns.get_level_values("symbol") == symbol].get_level_values("field")) != set(FIELDS):
            raise ValueError(f"symbol {symbol!r} must have exactly the fields {list(FIELDS)}")
    if not all(pd.api.types.is_numeric_dtype(dtype) for dtype in frame.dtypes):
        raise ValueError("all columns must be numeric")
    if len(frame) == 0:
        raise ValueError("frame must not be empty")


def _flag(
    severity: Severity,
    code: str,
    symbol: str | None,
    field: str | None,
    dates: pd.DatetimeIndex,
    mask: np.ndarray,
    config: ValidationConfig,
    what: str,
    what_all: str | None = None,
) -> list[ValidationIssue]:
    """One summary issue for all rows in ``mask`` (none if the mask is empty), never one issue per row."""
    count = int(np.count_nonzero(mask))
    if count == 0:
        return []
    first = tuple(ts.date() for ts in dates[mask][: config.max_dates_per_issue])
    label = " ".join(part for part in (symbol, field) if part) or "frame"
    text = what_all if what_all is not None and count == len(mask) else what
    message = f"{label}: {count} {text}; first on {first[0].isoformat()}"
    return [ValidationIssue(severity, code, symbol, field, count, first, message)]


def _symbol_issues(
    symbol: str, rows: pd.DataFrame, config: ValidationConfig, start: date | None, end: date | None
) -> list[ValidationIssue]:
    if rows.empty:
        message = f"{symbol}: no data in any row"
        return [ValidationIssue(Severity.ERROR, "no_data", symbol, None, 0, (), message)]

    dates = rows.index
    v = {field: rows[field].to_numpy() for field in FIELDS}
    issues: list[ValidationIssue] = []

    def flag(severity: Severity, code: str, field: str | None, d, mask, what: str, what_all: str | None = None):
        issues.extend(_flag(severity, code, symbol, field, d, np.asarray(mask), config, what, what_all))

    for field in FIELDS:
        flag(Severity.ERROR, "non_finite_value", field, dates, np.isinf(v[field]), "infinite value(s)")
    for field in PRICE_FIELDS:
        flag(
            Severity.ERROR,
            "nan_in_history",
            field,
            dates,
            np.isnan(v[field]),
            "row(s) with missing value inside the history",
        )
    flag(
        Severity.WARNING,
        "nan_volume",
        "volume",
        dates,
        np.isnan(v["volume"]),
        "row(s) without volume",
        "row(s) without volume (volume is NaN on every row)",
    )
    for field in PRICE_FIELDS:
        flag(Severity.ERROR, "non_positive_price", field, dates, v[field] <= 0, "row(s) with price <= 0")
    flag(Severity.ERROR, "negative_volume", "volume", dates, v["volume"] < 0, "row(s) with negative volume")

    # OHLC consistency, only on rows whose four prices are usable. High and low are ordered first, so a row
    # with high < low is reported once and does not also make open and close look outside the range.
    usable = np.all([np.isfinite(v[f]) & (v[f] > 0) for f in PRICE_FIELDS], axis=0)
    tol = config.ohlc_tolerance
    hi, lo = np.maximum(v["high"], v["low"]), np.minimum(v["high"], v["low"])
    with np.errstate(invalid="ignore"):
        flag(
            Severity.WARNING,
            "ohlc_high_below_low",
            "high",
            dates,
            usable & (v["high"] < v["low"] * (1 - tol)),
            "row(s) with high below low",
        )
        for field in ("close", "open"):
            outside = usable & ((v[field] > hi * (1 + tol)) | (v[field] < lo * (1 - tol)))
            flag(
                Severity.WARNING,
                f"ohlc_{field}_outside_range",
                field,
                dates,
                outside,
                f"row(s) with {field} outside the high-low range",
            )

    issues += _calendar_gap(symbol, dates, config)

    close_ok = np.isfinite(v["close"]) & (v["close"] > 0)
    close, close_dates = v["close"][close_ok], dates[close_ok]
    if len(close) > 1:
        ratio = close[1:] / close[:-1]
        flag(
            Severity.WARNING,
            "extreme_move",
            "close",
            close_dates[1:],
            np.abs(ratio - 1) > config.max_daily_move,
            f"daily move(s) above {config.max_daily_move:.0%}",
        )
    issues += _stale(symbol, close, close_dates, config)
    if len(close) > 1:
        targets = np.asarray(config.split_ratios)
        near_split = (np.abs(ratio[:, None] / targets[None, :] - 1) <= config.split_tolerance).any(axis=1)
        flag(
            Severity.WARNING,
            "split_artifact",
            "close",
            close_dates[1:],
            near_split,
            "daily move(s) close to a split ratio (possible unadjusted split)",
        )

    flag(
        Severity.INFO,
        "zero_volume",
        "volume",
        dates,
        v["volume"] == 0,
        "row(s) with zero volume",
        "row(s) with zero volume (volume is zero on every row)",
    )
    issues += _range_issues(symbol, dates, config, start, end)
    return issues


def _calendar_gap(symbol: str, dates: pd.DatetimeIndex, config: ValidationConfig) -> list[ValidationIssue]:
    """Runs of missing Mon-Fri days between a symbol's own consecutive data dates (no exchange calendar)."""
    if len(dates) < 2:
        return []
    days = dates.values.astype("datetime64[D]")
    missing = np.busday_count(days[:-1] + ONE_DAY, days[1:])  # business days strictly between two data dates
    mask = missing > config.max_gap_business_days
    if not mask.any():
        return []
    what = f"gap(s) of more than {config.max_gap_business_days} missing business days (longest {missing.max()})"
    return _flag(Severity.WARNING, "calendar_gap", symbol, None, dates[1:], mask, config, what)


def _stale(symbol: str, close: np.ndarray, dates: pd.DatetimeIndex, config: ValidationConfig) -> list[ValidationIssue]:
    """Rows inside runs of ``stale_run_length`` or more identical closes."""
    if len(close) < config.stale_run_length:
        return []
    group = np.cumsum(np.r_[True, close[1:] != close[:-1]]) - 1
    run_length = np.bincount(group)[group]
    mask = run_length >= config.stale_run_length
    what = f"row(s) in runs of {config.stale_run_length} or more identical closes (longest {run_length.max()})"
    return _flag(Severity.WARNING, "stale_price", symbol, "close", dates, mask, config, what)


def _range_issues(
    symbol: str, dates: pd.DatetimeIndex, config: ValidationConfig, start: date | None, end: date | None
) -> list[ValidationIssue]:
    """Info if the symbol's data starts late or ends early; the count is the number of missing business days."""
    issues: list[ValidationIssue] = []
    first, last = dates[0], dates[-1]
    if start is not None:
        missing = int(np.busday_count(np.datetime64(start), first.to_datetime64().astype("datetime64[D]")))
        if missing > config.range_tolerance_business_days:
            message = f"{symbol}: data starts on {first.date()}, {missing} business days after the requested {start}"
            issues.append(
                ValidationIssue(Severity.INFO, "starts_late", symbol, None, missing, (first.date(),), message)
            )
    if end is not None:
        last_day = last.to_datetime64().astype("datetime64[D]")
        missing = int(np.busday_count(last_day + ONE_DAY, np.datetime64(end) + ONE_DAY))
        if missing > config.range_tolerance_business_days:
            message = f"{symbol}: data ends on {last.date()}, {missing} business days before the requested {end}"
            issues.append(ValidationIssue(Severity.INFO, "ends_early", symbol, None, missing, (last.date(),), message))
    return issues
