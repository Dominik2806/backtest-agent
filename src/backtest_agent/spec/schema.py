"""Strategy spec: the Pydantic schema of a YAML strategy file (see docs/strategy-spec.md and ADR 0007).

The spec is what the maintainer approves before anything runs, so it is strict: unknown fields are rejected, types are
strict (no ``true`` as a number, no ``"10"`` as an integer) and everything that changes a result must be written down.
"""

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_core import InitErrorDetails, PydanticCustomError

from backtest_agent.spec.errors import UnknownSignalError
from backtest_agent.spec.signals import SignalParams, get_signal

SCHEMA_VERSION = 1
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _rule_error(title: str, problems: list[tuple[str, str, Any]]) -> ValidationError:
    """A ValidationError with one error per (field, message, value), so a rule can name the field it concerns."""
    details = [
        InitErrorDetails(type=PydanticCustomError("spec_rule", message), loc=(field,), input=value)
        for field, message, value in problems
    ]
    return ValidationError.from_exception_data(title, details)


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        raise ValueError(f"must be a date such as 2020-01-31 without a time, got {value}")
    if isinstance(value, date):
        return value
    if isinstance(value, str) and _ISO_DATE.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise ValueError(f"{value!r} is not a valid calendar date") from None
    raise ValueError(f"must be a date such as 2020-01-31, got {value!r}")


def _symbol(value: str) -> str:
    if not value or any(ch.isspace() for ch in value):
        raise ValueError(f"a symbol must be non-empty and contain no whitespace, got {value!r}")
    return value


IsoDate = Annotated[date, BeforeValidator(_as_date)]
Symbol = Annotated[str, AfterValidator(_symbol)]
Bps = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Money = Annotated[float, Field(ge=0, allow_inf_nan=False)]


@dataclass(frozen=True)
class RiskFlag:
    """A fact about a spec that every report must show next to the results."""

    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class Period(_Model):
    start: IsoDate
    end: IsoDate

    @model_validator(mode="after")
    def _end_not_before_start(self) -> "Period":
        if self.end < self.start:
            raise _rule_error(
                "Period", [("end", f"end ({self.end}) must be on or after start ({self.start})", self.end)]
            )
        return self


class DataSpec(_Model):
    provider: Literal["yfinance"] = "yfinance"


class SignalSpec(_Model):
    id: str
    params: dict[str, Any] = Field(default_factory=dict, validate_default=True)

    @field_validator("id")
    @classmethod
    def _registered(cls, signal_id: str) -> str:
        try:
            get_signal(signal_id)
        except UnknownSignalError as error:
            raise ValueError(str(error)) from None
        return signal_id

    @field_validator("params")
    @classmethod
    def _valid_params(cls, params: dict[str, Any], info: ValidationInfo) -> dict[str, Any]:
        signal_id = info.data.get("id")
        if signal_id is None:  # the id is invalid and already reported
            return params
        # A ValidationError of the params model is merged by Pydantic with the paths signal.params.<field>.
        # The stored dict has the defaults filled in, so the spec pins the values a run really uses.
        return get_signal(signal_id).params_model.model_validate(params).model_dump()

    def params_model(self) -> SignalParams:
        """The validated params instance of the signal."""
        return get_signal(self.id).parse_params(self.params)


class ExecutionSpec(_Model):
    delay_bars: int = Field(1, ge=0)
    price: Literal["open", "close"] = "open"
    allow_same_bar_execution: bool = False

    @model_validator(mode="after")
    def _same_bar_rules(self) -> "ExecutionSpec":
        problems: list[tuple[str, str, Any]] = []
        if self.delay_bars == 0 and not self.allow_same_bar_execution:
            problems.append(
                (
                    "delay_bars",
                    "delay_bars 0 trades on the same bar as the signal, which can hide look-ahead bias; "
                    "to allow it write allow_same_bar_execution: true explicitly",
                    self.delay_bars,
                )
            )
        if self.delay_bars == 0 and self.price == "open":
            problems.append(
                (
                    "price",
                    "price 'open' with delay_bars 0 is impossible: the signal is only known after the close of the "
                    "bar, so an open fill on that bar would use the future; use price: close or delay_bars: 1",
                    self.price,
                )
            )
        if self.delay_bars >= 1 and self.allow_same_bar_execution:
            problems.append(
                (
                    "allow_same_bar_execution",
                    f"allow_same_bar_execution only applies when delay_bars is 0 (delay_bars is {self.delay_bars}); "
                    "remove it",
                    self.allow_same_bar_execution,
                )
            )
        if problems:
            raise _rule_error("ExecutionSpec", problems)
        return self


class SizingSpec(_Model):
    method: Literal["equal_weight", "fixed_fraction"]
    fraction: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)] | None = None

    @model_validator(mode="after")
    def _fraction_rules(self) -> "SizingSpec":
        if self.method == "fixed_fraction" and self.fraction is None:
            raise _rule_error("SizingSpec", [("fraction", "required for method fixed_fraction", None)])
        if self.method == "equal_weight" and self.fraction is not None:
            raise _rule_error(
                "SizingSpec", [("fraction", "not allowed for method equal_weight; remove it", self.fraction)]
            )
        return self


class CostsSpec(_Model):
    commission_bps: Bps
    spread_bps: Bps
    slippage_bps: Bps
    min_commission: Money = 0.0  # per trade, account currency, commission only; 0 = no minimum


class StrategySpec(_Model):
    """A validated strategy spec. Use ``load_spec`` or ``parse_spec`` to create one from YAML."""

    schema_version: int
    name: str
    description: str = ""
    universe: list[Symbol]
    period: Period
    data: DataSpec = Field(default_factory=DataSpec)
    signal: SignalSpec
    execution: ExecutionSpec = Field(default_factory=ExecutionSpec)
    sizing: SizingSpec
    rebalance: Literal["daily", "weekly", "monthly", "on_signal"]
    costs: CostsSpec
    benchmark: Symbol
    initial_capital: Annotated[float, Field(gt=0, allow_inf_nan=False)]

    @field_validator("schema_version")
    @classmethod
    def _supported_version(cls, version: int) -> int:
        if version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {version}; this version supports {SCHEMA_VERSION}")
        return version

    @field_validator("name")
    @classmethod
    def _name(cls, name: str) -> str:
        if not name.strip() or "\n" in name or "\r" in name or len(name) > 100:
            raise ValueError("name must be a non-empty single line of at most 100 characters")
        return name

    @field_validator("universe")
    @classmethod
    def _universe(cls, universe: list[str]) -> list[str]:
        if not universe:
            raise ValueError("universe must contain at least one symbol")
        seen: dict[str, str] = {}
        duplicates: list[str] = []
        for symbol in universe:
            if symbol.upper() in seen:
                duplicates.append(symbol)
            seen.setdefault(symbol.upper(), symbol)
        if duplicates:
            raise ValueError(f"universe must not contain duplicate symbols (case-insensitive): {', '.join(duplicates)}")
        return universe

    @property
    def warmup_rows(self) -> int:
        """Trading rows of history the signal needs before a date (see ``SignalParams.warmup_rows``)."""
        return self.signal.params_model().warmup_rows()

    def risk_flags(self) -> tuple[RiskFlag, ...]:
        """Facts every report must show: same-bar execution and zero trading costs."""
        flags: list[RiskFlag] = []
        if self.execution.delay_bars == 0:
            flags.append(
                RiskFlag(
                    "same_bar_execution",
                    "Orders are filled on the same bar as the signal (delay_bars 0, allowed explicitly); "
                    "the result may contain look-ahead bias.",
                )
            )
        costs = self.costs
        if math.fsum((costs.commission_bps, costs.spread_bps, costs.slippage_bps, costs.min_commission)) == 0:
            flags.append(
                RiskFlag(
                    "zero_costs",
                    "Commission, spread, slippage and minimum commission are all zero; "
                    "the result overstates what trading would return.",
                )
            )
        return tuple(flags)

    def to_dict(self) -> dict[str, Any]:
        """Plain dict with JSON types (dates as ISO strings), for the report and the journal."""
        return self.model_dump(mode="json")
