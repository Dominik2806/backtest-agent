"""Signal interface, registry and contract check (see docs/strategy-spec.md and ADR 0006).

A signal is a function ``fn(prices, params) -> DataFrame``. ``prices`` is the standard price frame, ``params`` an
instance of the signal's params model. The output has the index of ``prices``, one flat float64 column per symbol
(an ``Index`` named ``symbol``, in input order), values in [0, 1] and no NaN. See ``validate_signal_output``.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from backtest_agent.data.provider import validate_standard_frame
from backtest_agent.spec.errors import SignalContractError, UnknownSignalError

_ID = re.compile(r"[a-z][a-z0-9_]*")


class SignalParams(BaseModel):
    """Base class of every signal params model: frozen, no unknown fields, strict types, defaults for all fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def warmup_rows(self) -> int:
        """Trading rows of history a symbol needs before a date to produce its final value on that date.

        Exact meaning: let W be this value and k the 0-based number of a symbol's own trading row (a row where its
        close is not NaN). The signal of that symbol is 0.0 on its first W trading rows (k < W), and from row W on
        it is final: it is identical whether the function sees the full history or only the W trading rows of that
        symbol before the date, plus the date itself. Default 0 (no history needed).
        """
        return 0


SignalFunction = Callable[[pd.DataFrame, Any], pd.DataFrame]


@dataclass(frozen=True)
class Signal:
    """A registered signal: id, params model and function."""

    id: str
    params_model: type[SignalParams]
    function: SignalFunction
    description: str = ""

    def parse_params(self, params: Mapping[str, Any] | SignalParams | None = None) -> SignalParams:
        """Return a validated params instance: a mapping is validated, ``None`` gives the defaults."""
        if isinstance(params, SignalParams):
            if not isinstance(params, self.params_model):
                raise TypeError(f"signal {self.id!r} needs {self.params_model.__name__}, got {type(params).__name__}")
            return params
        return self.params_model.model_validate({} if params is None else dict(params))

    def warmup_rows(self, params: Mapping[str, Any] | SignalParams | None = None) -> int:
        return self.parse_params(params).warmup_rows()

    def generate(self, prices: pd.DataFrame, params: Mapping[str, Any] | SignalParams | None = None) -> pd.DataFrame:
        """Run the signal and enforce the contract on input and output (what the engine calls).

        The function gets a copy-on-write view of ``prices``, so even an in-place modification cannot reach the
        caller's frame. ``ValueError`` for a non-standard input, ``SignalContractError`` for a bad output.
        """
        validate_standard_frame(prices)
        signals = self.function(prices.copy(deep=False), self.parse_params(params))
        validate_signal_output(prices, signals)
        return signals


class SignalRegistry:
    """Signals by id, so the engine finds a strategy by the id in its spec."""

    def __init__(self) -> None:
        self._signals: dict[str, Signal] = {}

    def register(
        self, signal_id: str, params: type[SignalParams] = SignalParams
    ) -> Callable[[SignalFunction], SignalFunction]:
        """Decorator: ``@registry.register("my_signal", params=MyParams)``. Returns the function unchanged."""
        if not _ID.fullmatch(signal_id):
            raise ValueError(f"signal id {signal_id!r} must be lowercase letters, digits and underscores")
        if not (isinstance(params, type) and issubclass(params, SignalParams)):
            raise TypeError("params must be a subclass of SignalParams")

        def decorator(function: SignalFunction) -> SignalFunction:
            if signal_id in self._signals:
                raise ValueError(f"signal id {signal_id!r} is already registered")
            description = (function.__doc__ or "").strip().splitlines()[0] if function.__doc__ else ""
            self._signals[signal_id] = Signal(signal_id, params, function, description)
            return function

        return decorator

    def get(self, signal_id: str) -> Signal:
        try:
            return self._signals[signal_id]
        except KeyError:
            available = ", ".join(self.ids()) or "none registered"
            raise UnknownSignalError(f"unknown signal id {signal_id!r}; available signals: {available}") from None

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._signals))

    def __contains__(self, signal_id: object) -> bool:
        return signal_id in self._signals


#: The registry the engine and the spec use.
SIGNALS = SignalRegistry()
register_signal = SIGNALS.register


def get_signal(signal_id: str) -> Signal:
    return SIGNALS.get(signal_id)


def list_signals() -> tuple[str, ...]:
    return SIGNALS.ids()


def close_frame(prices: pd.DataFrame) -> pd.DataFrame:
    """Wide frame of closes: one flat float64 column per symbol (``Index`` named ``symbol``), input order."""
    return prices.xs("close", axis=1, level="field").astype("float64")


def carry_forward(values: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """Spread values given on a symbol's own trading rows over the full index.

    Non-trading days carry the value of the last trading row before them (causal); rows before the first trading row
    are NaN. Uses the last row label, so a NaN value on a trading row (warm-up) stays NaN.
    """
    if values.empty:
        return pd.Series(np.nan, index=index, dtype="float64")
    return values.reindex(index, method="ffill")


def per_symbol_signal(prices: pd.DataFrame, compute: Callable[[pd.Series], pd.Series]) -> pd.DataFrame:
    """Build a signal frame symbol by symbol on each symbol's own trading rows.

    ``compute`` gets the close of one symbol with its non-trading days removed and returns a series on the same
    index; NaN there means warm-up and becomes 0.0. The result is carried over the symbol's non-trading days and is
    0.0 before its first trading row.
    """
    closes = close_frame(prices)
    columns = {}
    for symbol in closes.columns:
        own = closes[symbol].dropna()
        values = compute(own).astype("float64").fillna(0.0)
        columns[symbol] = carry_forward(values, closes.index).fillna(0.0)
    return pd.DataFrame(columns, index=closes.index, columns=closes.columns)


def validate_signal_output(prices: pd.DataFrame, signals: pd.DataFrame) -> None:
    """Raise ``SignalContractError`` listing every violation of the output contract.

    The output must have the index of ``prices``, flat columns named ``symbol`` holding the input symbols in input
    order, all ``float64``, finite, within [0, 1] and without NaN.
    """
    problems: list[str] = []
    if not isinstance(signals, pd.DataFrame):
        raise SignalContractError(f"signal output must be a DataFrame, got {type(signals).__name__}")
    symbols = list(dict.fromkeys(prices.columns.get_level_values("symbol")))
    if not signals.index.equals(prices.index) or signals.index.name != prices.index.name:
        problems.append("index must equal the index of the input prices")
    if isinstance(signals.columns, pd.MultiIndex) or list(signals.columns) != symbols:
        problems.append(f"columns must be the input symbols {symbols} in input order, got {list(signals.columns)}")
    elif signals.columns.name != "symbol":
        problems.append("the columns must be an Index named 'symbol'")
    bad_dtypes = sorted({str(d) for d in signals.dtypes if d != "float64"})
    if bad_dtypes:
        problems.append(f"all columns must be float64, found {bad_dtypes}")
    else:
        values = signals.to_numpy()
        for label, mask in (
            ("NaN", np.isnan(values)),
            ("infinite", np.isinf(values)),
            ("outside [0, 1]", np.isfinite(values) & ((values < 0) | (values > 1))),
        ):
            if mask.any():
                row, col = (int(i[0]) for i in np.nonzero(mask))
                where = f"first at {signals.index[row].date()} in {signals.columns[col]!r}"
                problems.append(f"{int(mask.sum())} value(s) {label}; {where}")
    if problems:
        raise SignalContractError("signal output violates the contract: " + "; ".join(problems))
