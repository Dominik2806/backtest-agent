"""The ``cases.yaml`` of a coded signal: hand-calculated examples as data (ADR 0018, docs/coded-signals.md).

The signal coder writes its tests as data, not as pytest files, because a pytest file would import agent code in every
test run. A case gives closing prices of a few symbols and the exposure the signal must produce on every row. The file
is read with the safe YAML loader (no aliases, no duplicate keys), is bounded in size, and may not hold hidden
characters. ``run_cases`` runs the cases against a loaded signal through ``Signal.generate``, so the output rules and
the zero rows are checked as well. Only ``bt signal check`` runs cases; a run does not.

.. code-block:: yaml

    signal: rsi_pullback        # optional; if given it must be the id of the file
    params: {window: 2}         # optional; the params of every case (defaults otherwise)
    cases:
      - name: rises, falls and rises
        prices:                 # closing prices per symbol, one per row; null = the symbol does not trade
          AAA: [10, 11, 10, 12]
          BBB: [null, 20, 21, 19]
        expected:               # the exposure per symbol and row, between 0 and 1
          AAA: [0, 1, 0, 1]
          BBB: [0, 0, 1, 0]

Rows are consecutive Monday-to-Friday days from 2024-01-02; open, high and low equal the close; volume is 1000.
"""

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from backtest_agent.coded.errors import CasesError
from backtest_agent.spec.coded_spec import check_scalar_params, forbidden_character, normalise_newlines
from backtest_agent.spec.signals import Signal

MAX_FILE_BYTES = 256 * 1024
MAX_CASES = 50
MAX_SYMBOLS = 10
MAX_ROWS = 400
TOLERANCE = 1e-9
MAX_DIFFERENCES = 10
_FIELDS = ("open", "high", "low", "close", "volume")

Price = Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]
Exposure = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False, strict=True)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Case(_Model):
    name: Annotated[str, Field(min_length=1, max_length=100, strict=True)]
    prices: dict[str, list[Price | None]]
    expected: dict[str, list[Exposure]]

    @field_validator("name")
    @classmethod
    def _plain_name(cls, name: str) -> str:
        if any(forbidden_character(c) for c in name) or "\n" in name:
            raise ValueError("a case name is one line without control or hidden characters")
        return name

    @model_validator(mode="after")
    def _shapes(self) -> "Case":
        problems = []
        if not 1 <= len(self.prices) <= MAX_SYMBOLS:
            problems.append(f"prices needs 1 to {MAX_SYMBOLS} symbols, got {len(self.prices)}")
        if set(self.prices) != set(self.expected):
            problems.append(f"prices has the symbols {sorted(self.prices)} but expected has {sorted(self.expected)}")
        lengths = {len(values) for values in (*self.prices.values(), *self.expected.values())}
        if len(lengths) != 1:
            problems.append(f"every symbol needs the same number of rows in prices and expected, got {sorted(lengths)}")
        elif not 1 <= next(iter(lengths)) <= MAX_ROWS:
            problems.append(f"a case needs 1 to {MAX_ROWS} rows, got {next(iter(lengths))}")
        for symbol, values in self.prices.items():
            if all(v is None for v in values):
                problems.append(f"{symbol} never trades in prices; give it at least one price")
        if problems:
            raise ValueError("; ".join(problems))
        return self


class CasesFile(_Model):
    signal: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    cases: Annotated[list[Case], Field(min_length=1, max_length=MAX_CASES)]

    @field_validator("params")
    @classmethod
    def _scalar_params(cls, params: dict[str, Any]) -> dict[str, Any]:
        check_scalar_params(params)
        return params


@dataclass(frozen=True)
class Cases:
    """A validated cases file: the params for every case and the cases."""

    params: dict[str, Any]
    cases: tuple[Case, ...]


def cases_path(strategies_dir: Path | str, signal_id: str) -> Path:
    """Where the cases of ``signal_id`` are: ``<strategies_dir>/<id>.cases.yaml``."""
    return Path(strategies_dir) / f"{signal_id}.cases.yaml"


def read_cases(path: Path, signal_id: str) -> Cases:
    """Read and validate a cases file; ``CasesError`` if it is missing, too large or not valid."""
    try:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise CasesError(f"{path.name} has {size} bytes; the limit is {MAX_FILE_BYTES}")
        with path.open("rb") as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
    except FileNotFoundError:
        raise CasesError(
            f"{path.name} is missing; the signal coder writes the examples of {signal_id!r} in it"
        ) from None
    except OSError as error:
        raise CasesError(f"{path.name} cannot be read ({error.strerror or error})") from None
    return parse_cases(data, signal_id, name=path.name)


def parse_cases(data: bytes, signal_id: str, *, name: str = "cases.yaml") -> Cases:
    """Validate the bytes of a cases file; ``CasesError`` lists every problem."""
    if len(data) > MAX_FILE_BYTES:
        raise CasesError(f"{name} has {len(data)} bytes; the limit is {MAX_FILE_BYTES}")
    try:
        text = normalise_newlines(data.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise _invalid(name, [f"(file): not UTF-8 ({error.reason} at byte {error.start})"]) from None
    for number, line in enumerate(text.split("\n"), start=1):
        for character in line:
            if forbidden_character(character):
                code = f"U+{ord(character):04X}"
                raise _invalid(name, [f"line {number}: the character {code} is not allowed"])
    document = _load(text, name)
    if not isinstance(document, dict):
        raise _invalid(name, ["(root): the file must be a mapping with a list of cases"])
    try:
        parsed = CasesFile.model_validate(document)
    except ValidationError as error:
        raise _invalid(name, [_describe(item) for item in error.errors()]) from None
    if parsed.signal is not None and parsed.signal != signal_id:
        raise _invalid(name, [f"signal: the file is for {parsed.signal!r} but the signal is {signal_id!r}"])
    return Cases(parsed.params, tuple(parsed.cases))


def run_cases(signal: Signal, cases: Cases) -> int:
    """Run every case through ``Signal.generate``; ``CasesError`` lists the differences. Returns the number of cases."""
    problems: list[str] = []
    try:
        params = signal.parse_params(cases.params)
    except Exception as error:
        raise CasesError(
            f"{signal.id}: the params of the cases are not valid for the signal ({_short(error)})"
        ) from None
    for case in cases.cases:
        where = f"{signal.id} on the case {case.name!r}"
        frame = _frame(case)
        try:
            output = signal.generate(frame, params)
        except Exception as error:  # any failure of the code is a failed case
            problems.append(f"{where}: {type(error).__name__}: {_short(error)}")
            continue
        for symbol, wanted in case.expected.items():
            got = output[symbol].to_numpy()
            for row in np.flatnonzero(~np.isclose(got, np.array(wanted), rtol=0.0, atol=TOLERANCE)):
                day = frame.index[row].date()
                problems.append(f"{where}: {symbol} row {int(row)} ({day}): expected {wanted[row]}, got {got[row]}")
    if problems:
        shown = problems[:MAX_DIFFERENCES]
        if len(problems) > MAX_DIFFERENCES:
            shown.append(f"... and {len(problems) - MAX_DIFFERENCES} more")
        count = len(problems)
        raise CasesError(
            "\n".join([f"{count} difference{'s' if count != 1 else ''} in the examples:", *(f"  - {p}" for p in shown)])
        )
    return len(cases.cases)


def _frame(case: Case) -> pd.DataFrame:
    """The standard price frame of a case: consecutive weekdays, open = high = low = close, volume 1000."""
    rows = len(next(iter(case.prices.values())))
    index = pd.bdate_range("2024-01-02", periods=rows).astype("datetime64[ns]").rename("date")
    data: dict[tuple[str, str], np.ndarray] = {}
    for symbol, values in case.prices.items():
        close = np.array([math.nan if v is None else v for v in values], dtype="float64")
        for field in _FIELDS[:4]:
            data[(symbol, field)] = close
        data[(symbol, "volume")] = np.where(np.isnan(close), np.nan, 1000.0)
    frame = pd.DataFrame(data, index=index)
    frame.columns = pd.MultiIndex.from_tuples(frame.columns, names=["symbol", "field"])
    return frame


class _Loader(yaml.SafeLoader):
    """The safe loader that refuses a key that is given twice."""


def _mapping(loader: _Loader, node: yaml.MappingNode, deep: bool = False) -> dict:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(None, None, f"the key {key!r} is given twice", key_node.start_mark)
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _load(text: str, name: str) -> Any:
    try:
        if any(isinstance(event, yaml.AliasEvent) for event in yaml.parse(text, Loader=yaml.SafeLoader)):
            raise _invalid(name, ["(yaml): aliases are not allowed"])
        return yaml.load(text, Loader=_Loader)  # noqa: S506 - a SafeLoader subclass
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        reason = getattr(error, "problem", None) or str(error)
        raise _invalid(name, [f"(yaml): syntax error{where}: {reason}"]) from None


def _describe(item: dict[str, Any]) -> str:
    path = ""
    for part in item["loc"]:
        path += f"[{part}]" if isinstance(part, int) else (f".{part}" if path else str(part))
    kind = item["type"]
    if kind == "missing":
        return f"{path or '(root)'}: missing required field"
    if kind == "extra_forbidden":
        return f"{path}: unknown field"
    return f"{path or '(root)'}: {str(item['msg']).removeprefix('Value error, ')}"


def _invalid(name: str, problems: list[str]) -> CasesError:
    count = len(problems)
    lines = [f"{name} is not valid ({count} problem{'s' if count != 1 else ''}):", *(f"  - {p}" for p in problems)]
    return CasesError("\n".join(lines))


def _short(error: BaseException) -> str:
    text = str(error).replace("\n", " ")
    return text if len(text) <= 500 else text[:497] + "..."
