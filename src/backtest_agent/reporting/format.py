"""The one place that decides how a number, a date or a missing value looks in a report (docs/report.md, "Formats").

Every function takes the ``field`` it formats, so an invalid value (NaN or infinity reaching the report is a bug
upstream, not an "n/a") raises a ``ValueError`` that names the field. ``None`` is the only value that prints as
``n/a``. Nothing here prints a raw float: every number has a fixed number of decimals, ASCII minus, and a negative
zero never appears.
"""

import math
from datetime import UTC, date, datetime

NA = "n/a"


def _check(value: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field}: expected a number or None, got {value!r}")
    if not math.isfinite(value):
        raise ValueError(f"{field}: expected a finite number, got {value!r} (NaN and infinity are bugs upstream)")
    return float(value)


def _fixed(value: float, decimals: int, *, signed: bool, grouping: bool) -> str:
    text = f"{abs(value):{',' if grouping else ''}.{decimals}f}"
    if text.strip("0.,") == "":  # rounds to zero: no sign, never "-0.00"
        return text
    if value < 0:
        return "-" + text
    return ("+" if signed else "") + text


def na(reason: str | None = None) -> str:
    """``n/a`` or ``n/a (reason)``."""
    return NA if not reason else f"{NA} ({reason})"


def number(value: float | None, field: str, *, decimals: int = 2, signed: bool = False) -> str:
    """A plain number with fixed decimals and thousands separators, e.g. ``1,234.50``; ``n/a`` for None."""
    if value is None:
        return NA
    return _fixed(_check(value, field), decimals, signed=signed, grouping=True)


def ratio(value: float | None, field: str) -> str:
    """A ratio such as Sharpe: 2 decimals, e.g. ``0.83`` or ``-1.50``; ``n/a`` for None."""
    return number(value, field, decimals=2)


def percent(value: float | None, field: str, *, signed: bool = False, decimals: int = 2) -> str:
    """A fraction as a percentage, 2 decimals: ``0.1713`` -> ``17.13%``; ``signed`` adds ``+``; ``n/a`` for None."""
    if value is None:
        return NA
    return _fixed(_check(value, field) * 100.0, decimals, signed=signed, grouping=True) + "%"


def money(value: float | None, field: str) -> str:
    """An amount in the account currency, 2 decimals, no currency symbol (the spec has none): ``100,000.00``."""
    return number(value, field, decimals=2)


def bps(value: float | None, field: str) -> str:
    """Basis points with up to 2 decimals, trailing zeros dropped: ``1.0`` -> ``1 bps``, ``2.5`` -> ``2.5 bps``."""
    if value is None:
        return NA
    return f"{_fixed(_check(value, field), 2, signed=False, grouping=True).rstrip('0').rstrip('.')} bps"


def integer(value: int | None, field: str) -> str:
    """A count with thousands separators; ``n/a`` for None."""
    if value is None:
        return NA
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field}: expected an integer or None, got {value!r}")
    return f"{value:,}"


def iso_date(value: date | str | None, field: str) -> str:
    """``YYYY-MM-DD``; accepts a date or an ISO string (as ``Alignment`` holds); ``n/a`` for None."""
    if value is None:
        return NA
    if isinstance(value, datetime):
        raise ValueError(f"{field}: expected a date without a time, got {value!r}")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return date.fromisoformat(value).isoformat()
    raise ValueError(f"{field}: expected a date, got {value!r}")


def utc_timestamp(value: datetime, field: str = "generated_at") -> str:
    """``YYYY-MM-DD HH:MM:SS UTC`` of a timezone-aware datetime (converted to UTC); naive raises ``ValueError``."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field}: must be timezone-aware, got the naive {value!r}")
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def yes_no(value: bool) -> str:
    return "yes" if value else "no"
