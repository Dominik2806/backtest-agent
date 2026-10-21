"""Result, issue and config types of the data quality validation (see docs/data.md)."""

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import StrEnum

from backtest_agent.data.errors import DataValidationError


class Severity(StrEnum):
    """Errors stop a run, warnings appear in the report, infos are context."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


_RANK = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}


@dataclass(frozen=True)
class ValidationConfig:
    """Thresholds of the checks. Frozen: use ``dataclasses.replace`` or a new instance to change one per run."""

    #: Relative tolerance of the OHLC consistency checks (adjustment rounding): 0.001 is 0.1 percent.
    ohlc_tolerance: float = 0.001
    #: A run of more than this many missing Mon-Fri days inside a symbol's own history is a gap.
    max_gap_business_days: int = 4
    #: Absolute close-to-close move above this is extreme (0.40 is 40 percent).
    max_daily_move: float = 0.40
    #: The same close on this many consecutive rows or more is stale.
    stale_run_length: int = 5
    #: Close-to-close ratios that look like an unadjusted split.
    split_ratios: tuple[float, ...] = (1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 10, 2.0, 3.0, 4.0, 5.0, 10.0)
    #: A ratio within this relative distance of a split ratio is flagged (0.05 is 5 percent).
    split_tolerance: float = 0.05
    #: A symbol starting or ending more than this many business days inside the requested range gets an info.
    range_tolerance_business_days: int = 3
    #: At most this many affected dates are listed per issue.
    max_dates_per_issue: int = 5

    def __post_init__(self) -> None:
        positive = {
            "ohlc_tolerance": self.ohlc_tolerance,
            "max_daily_move": self.max_daily_move,
            "split_tolerance": self.split_tolerance,
        }
        for name, value in positive.items():
            if not value > 0:
                raise ValueError(f"{name} must be positive, got {value}")
        at_least_one = {"stale_run_length": self.stale_run_length, "max_dates_per_issue": self.max_dates_per_issue}
        for name, value in at_least_one.items():
            if value < 1:
                raise ValueError(f"{name} must be at least 1, got {value}")
        for name, value in {
            "max_gap_business_days": self.max_gap_business_days,
            "range_tolerance_business_days": self.range_tolerance_business_days,
        }.items():
            if value < 0:
                raise ValueError(f"{name} must not be negative, got {value}")
        if not self.split_ratios or not all(r > 0 for r in self.split_ratios):
            raise ValueError("split_ratios must be a non-empty tuple of positive numbers")

    def to_dict(self) -> dict:
        data = asdict(self)
        data["split_ratios"] = list(self.split_ratios)
        return data


@dataclass(frozen=True)
class ValidationIssue:
    """One finding. ``symbol`` and ``field`` are None for frame-level issues.

    ``count`` is the number of affected rows (for ``starts_late`` and ``ends_early``: the number of missing business
    days). ``first_dates`` lists at most ``ValidationConfig.max_dates_per_issue`` affected dates, ascending.
    """

    severity: Severity
    code: str
    symbol: str | None
    field: str | None
    count: int
    first_dates: tuple[date, ...]
    message: str

    def to_dict(self) -> dict:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "symbol": self.symbol,
            "field": self.field,
            "count": self.count,
            "first_dates": [d.isoformat() for d in self.first_dates],
            "message": self.message,
        }


@dataclass(frozen=True)
class ValidationResult:
    """All issues of one validation, errors first, then warnings, then infos (generation order inside each)."""

    issues: tuple[ValidationIssue, ...]
    config: ValidationConfig = field(default_factory=ValidationConfig)

    def __post_init__(self) -> None:
        # sorted() is stable, so the generation order of the checks is kept inside a severity.
        object.__setattr__(self, "issues", tuple(sorted(self.issues, key=lambda i: _RANK[i.severity])))

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity is Severity.WARNING)

    @property
    def infos(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity is Severity.INFO)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    def raise_for_errors(self) -> None:
        """Raise ``DataValidationError`` if there is at least one error; warnings and infos never raise."""
        errors = self.errors
        if not errors:
            return
        shown = "; ".join(f"[{e.code}] {e.message}" for e in errors[:3])
        more = f" (and {len(errors) - 3} more)" if len(errors) > 3 else ""
        raise DataValidationError(f"{len(errors)} data error(s): {shown}{more}", self)

    def to_dict(self) -> dict:
        return {
            "ok": not self.has_errors,
            "counts": {s.value: sum(1 for i in self.issues if i.severity is s) for s in Severity},
            "issues": [i.to_dict() for i in self.issues],
            "config": self.config.to_dict(),
        }

    def to_json(self) -> str:
        """Deterministic JSON: sorted keys, ISO dates; equal results give identical text."""
        return json.dumps(self.to_dict(), sort_keys=True, indent=2)
