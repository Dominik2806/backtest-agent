"""Loading strategy specs from YAML: ``load_spec(path)`` and ``parse_spec(text)``.

YAML is only read with the safe loader. Every problem is collected into one ``SpecError`` with dotted field paths;
raw Pydantic or YAML messages never reach the user.
"""

import difflib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from backtest_agent.spec.errors import SpecError, SpecProblem, UnknownSignalError
from backtest_agent.spec.schema import StrategySpec
from backtest_agent.spec.signals import get_signal

_MERGE_TAG = "tag:yaml.org,2002:merge"
_NO_GOT = {"missing", "extra_forbidden", "value_error", "assertion_error"}
_HINTS = {
    "costs": (
        "the costs block is required: write commission_bps, spread_bps and slippage_bps explicitly "
        "(zeros are allowed when written)"
    ),
}


def load_spec(path: str | Path) -> StrategySpec:
    """Read a YAML file (UTF-8, BOM tolerated) and return the validated spec. Raises ``SpecError``."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        raise SpecError([SpecProblem("(file)", f"cannot read {path}: {error}")], source=str(path)) from error
    return parse_spec(text, source=str(path))


def parse_spec(text: str, source: str | None = None) -> StrategySpec:
    """Parse YAML text and return the validated spec. Raises ``SpecError`` listing every problem."""
    data = _load_yaml(text, source)
    if data is None:
        raise SpecError([SpecProblem("(root)", "the document is empty")], source)
    if not isinstance(data, dict):
        kind = {list: "a list", str: "text", int: "a number", float: "a number", bool: "true or false"}.get(
            type(data), type(data).__name__
        )
        raise SpecError([SpecProblem("(root)", f"the spec must be a mapping of fields, got {kind}")], source)
    try:
        return StrategySpec.model_validate(data)
    except ValidationError as error:
        problems = [_problem(err, data) for err in error.errors()]
        raise SpecError(problems, source) from None


def _load_yaml(text: str, source: str | None) -> Any:
    try:
        root = yaml.compose(text, Loader=yaml.SafeLoader)
        duplicates = list(_duplicate_keys(root, ""))
        if duplicates:
            raise SpecError(duplicates, source)
        return yaml.safe_load(text)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        reason = getattr(error, "problem", None) or str(error)
        raise SpecError([SpecProblem("(yaml)", f"YAML syntax error{where}: {reason}")], source) from None


def _duplicate_keys(node: yaml.Node | None, path: str) -> Iterator[SpecProblem]:
    """Yield a problem for every repeated key of every mapping, with the dotted path of the key."""
    if isinstance(node, yaml.MappingNode):
        first_line: dict[str, int] = {}
        for key_node, value_node in node.value:
            if isinstance(key_node, yaml.ScalarNode) and key_node.tag != _MERGE_TAG:
                key = key_node.value
                line = key_node.start_mark.line + 1
                child = f"{path}.{key}" if path else key
                if key in first_line:
                    yield SpecProblem(child, f"duplicate key '{key}' (lines {first_line[key]} and {line})")
                first_line.setdefault(key, line)
                yield from _duplicate_keys(value_node, child)
    elif isinstance(node, yaml.SequenceNode):
        for index, item in enumerate(node.value):
            yield from _duplicate_keys(item, f"{path}[{index}]")


def _path(loc: tuple[Any, ...]) -> str:
    path = ""
    for part in loc:
        path += f"[{part}]" if isinstance(part, int) else (f".{part}" if path else str(part))
    return path or "(root)"


def _known_fields(loc: tuple[Any, ...], data: dict[str, Any]) -> list[str]:
    """Names of the fields allowed where an unknown field was found (empty if they cannot be determined)."""
    parent = loc[:-1]
    if parent == ("signal", "params"):
        signal = data.get("signal")
        try:
            return list(get_signal(signal["id"]).params_model.model_fields)  # type: ignore[index]
        except (UnknownSignalError, KeyError, TypeError):
            return []
    model: type[BaseModel] = StrategySpec
    for part in parent:
        field = model.model_fields.get(part) if isinstance(part, str) else None
        annotation = field.annotation if field is not None else None
        if not (isinstance(annotation, type) and issubclass(annotation, BaseModel)):
            return []
        model = annotation
    return list(model.model_fields)


def _problem(error: Any, data: dict[str, Any]) -> SpecProblem:
    loc, kind = tuple(error["loc"]), error["type"]
    path = _path(loc)
    if kind == "missing":
        return SpecProblem(path, _HINTS.get(path, "missing required field"))
    if kind == "extra_forbidden":
        name = str(loc[-1])
        known = _known_fields(loc, data)
        close = difflib.get_close_matches(name, known, n=1)
        hint = f"; did you mean '{close[0]}'?" if close else (f"; allowed fields: {', '.join(known)}" if known else "")
        return SpecProblem(path, f"unknown field '{name}'{hint}")
    message = str(error["msg"])
    if kind == "value_error":
        message = message.removeprefix("Value error, ")
    elif kind == "model_type":
        message = "must be a block of fields (a YAML mapping)"
    elif kind not in _NO_GOT and not kind.startswith("spec_") and "input" in error:
        shown = repr(error["input"])
        message += f" (got {shown if len(shown) <= 60 else shown[:57] + '...'})"
    return SpecProblem(path, message)
