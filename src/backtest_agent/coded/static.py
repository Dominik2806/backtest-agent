"""Static check of a coded signal's source: a tripwire that parses the text and never imports or runs it.

The rules apply to the **whole syntax tree** (``ast.walk``), not only to the top level, because default arguments,
decorators, class bodies and comprehensions all run at import time. The check is a tripwire against the obvious and the
accidental (network, files, ``eval``, reaching into the interpreter); it is **not a sandbox** and a determined author
can get around it (ADR 0018 lists a known gap). The real defences are the human who reads the code before approving it
and the approval gate that only runs approved bytes.

Rules (the ``rule`` of a finding in brackets):

* the source is UTF-8 without a BOM or a NUL byte, at most 64 KiB, and parses (``encoding``, ``size``, ``syntax``);
* imports only from ``ALLOWED_MODULES``; from ``backtest_agent.spec.signals`` only ``ALLOWED_SIGNAL_NAMES``; no relative
  and no star import (``import``);
* no name of ``BANNED_NAMES`` (``banned-name``), no name or attribute that starts and ends with two underscores
  (``dunder``), no attribute of ``BANNED_ATTRIBUTES`` or starting with ``read_``, also as an imported name
  (``banned-attribute``), no ``global``, ``nonlocal`` or async syntax (``statement``);
* top level: a docstring, imports, assignments of literal constants to a plain name, classes and functions only
  (``top-level``); decorators only from ``ALLOWED_DECORATORS`` (``decorator``);
* exactly one use of ``register_signal``, as the decorator ``@register_signal("<id>", ...)`` of a top-level function,
  with the id of the file as its first argument (``register``).
"""

import ast
import unicodedata
from collections.abc import Callable

from backtest_agent.coded.errors import Finding, StaticCheckError
from backtest_agent.spec.coded_spec import forbidden_character, normalise_newlines

MAX_SOURCE_BYTES = 64 * 1024
MAX_CHARACTER_FINDINGS = 10  # then one finding "... and N more", so a file of hidden characters stays readable

ALLOWED_MODULES = frozenset({"__future__", "math", "numpy", "pandas", "pydantic", "typing"})
SIGNALS_MODULE = "backtest_agent.spec.signals"
ALLOWED_SIGNAL_NAMES = frozenset(
    {"SignalParams", "carry_forward", "close_frame", "per_symbol_signal", "register_signal"}
)

BANNED_NAMES = frozenset(
    {
        "__import__", "breakpoint", "compile", "delattr", "eval", "exec", "exit", "getattr", "globals", "help",
        "input", "locals", "open", "quit", "setattr", "vars",
    }
)  # fmt: skip
BANNED_ATTRIBUTES = frozenset(
    {
        # strings that are evaluated
        "eval", "query",
        # reading and writing files (every to_* attribute except ALLOWED_TO_ATTRIBUTES is banned as well)
        "DataSource", "fromfile", "fromregex", "genfromtxt", "load", "loadtxt", "memmap", "open_memmap", "save",
        "savetxt", "savez", "savez_compressed", "tofile",
        "parse_file", "parse_raw",
        # process-global state that would be changed at import time
        "option_context", "options", "reset_option", "seed", "set_option", "set_printoptions", "seterr", "seterrcall",
        # ways into the file system, the network and C code
        "ctypeslib", "distutils", "f2py", "io",
    }
)  # fmt: skip
ALLOWED_TO_ATTRIBUTES = frozenset(
    {
        "to_datetime", "to_dict", "to_frame", "to_list", "to_numeric", "to_numpy", "to_period", "to_pydatetime",
        "to_series", "to_timedelta", "to_timestamp",
    }
)  # fmt: skip
ALLOWED_DECORATORS = frozenset(
    {"classmethod", "field_validator", "model_validator", "property", "register_signal", "staticmethod"}
)
_REGISTER = "register_signal"

Adder = Callable[[ast.AST | None, str, str], None]


def find_problems(source: bytes, signal_id: str) -> tuple[Finding, ...]:
    """Every rule the source breaks, sorted by line. ``signal_id`` is the id the file must register."""
    findings: list[Finding] = []

    def add(node: ast.AST | None, rule: str, message: str) -> None:
        findings.append(Finding(getattr(node, "lineno", 0), getattr(node, "col_offset", 0), rule, message))

    if len(source) > MAX_SOURCE_BYTES:
        add(None, "size", f"the source has {len(source)} bytes; the limit is {MAX_SOURCE_BYTES}")
    if source.startswith(b"\xef\xbb\xbf"):
        add(None, "encoding", "the source starts with a byte order mark; save it as UTF-8 without BOM")
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as error:
        add(None, "encoding", f"the source is not UTF-8 ({error.reason} at byte {error.start})")
        return tuple(sorted(findings))
    if findings:
        return tuple(sorted(findings))
    text = normalise_newlines(text)  # the CR of a CRLF is not an error; a lone CR is
    characters: list[Finding] = []
    for number, line in enumerate(text.split(chr(10)), start=1):
        for column, character in enumerate(line):
            if forbidden_character(character):
                category = unicodedata.category(character)
                message = f"the character U+{ord(character):04X} ({category}) is not allowed"
                characters.append(Finding(number, column, "character", message))
    if len(characters) > MAX_CHARACTER_FINDINGS:
        last = characters[-1]
        more = len(characters) - MAX_CHARACTER_FINDINGS
        characters = [
            *characters[:MAX_CHARACTER_FINDINGS],
            Finding(last.line, last.column, "character", f"... and {more} more"),
        ]
    findings.extend(characters)
    if chr(0) in text:
        return tuple(sorted(findings))  # Python cannot parse a NUL byte; the finding above is the answer
    try:
        tree = ast.parse(text)
    except SyntaxError as error:
        findings.append(Finding(error.lineno or 0, error.offset or 0, "syntax", f"syntax error: {error.msg}"))
        return tuple(sorted(findings))
    except (RecursionError, MemoryError, ValueError) as error:  # a source too deeply nested for the parser
        message = f"the source cannot be parsed: {type(error).__name__}: {error}"
        findings.append(Finding(0, 0, "syntax", message))
        return tuple(sorted(findings))

    _check_imports(tree, add)
    _check_names_and_attributes(tree, add)
    _check_top_level(tree, add)
    _check_decorators(tree, add)
    _check_registration(tree, signal_id, add)
    return tuple(sorted(set(findings)))


def check_source(source: bytes, signal_id: str) -> None:
    """Raise ``StaticCheckError`` listing every problem, or return if the source passes."""
    findings = find_problems(source, signal_id)
    if findings:
        raise StaticCheckError(findings)


def _is_dunder(name: str) -> bool:
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def _banned_attribute(name: str) -> bool:
    if name.startswith("to_"):
        return name not in ALLOWED_TO_ATTRIBUTES  # fail closed: every to_* may write unless it is listed
    return name in BANNED_ATTRIBUTES or name.startswith("read_")


def _check_imports(tree: ast.AST, add: Adder) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in ALLOWED_MODULES:
                    add(node, "import", f"import of {alias.name!r} is not allowed")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                add(node, "import", "relative imports are not allowed")
            elif module == SIGNALS_MODULE:
                for alias in node.names:
                    if alias.name not in ALLOWED_SIGNAL_NAMES:
                        add(node, "import", f"{alias.name!r} may not be imported from {SIGNALS_MODULE}")
            elif module not in ALLOWED_MODULES:
                add(node, "import", f"import from {module!r} is not allowed")
            for alias in node.names:
                if alias.name == "*":
                    add(node, "import", "star imports are not allowed")
                elif _banned_attribute(alias.name) or alias.name in BANNED_NAMES or _is_dunder(alias.name):
                    add(node, "banned-attribute", f"importing {alias.name!r} is not allowed")


def _check_names_and_attributes(tree: ast.AST, add: Adder) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id in BANNED_NAMES:
                add(node, "banned-name", f"the name {node.id!r} is not allowed")
            elif _is_dunder(node.id):
                add(node, "dunder", f"the name {node.id!r} is not allowed")
        elif isinstance(node, ast.Attribute):
            if _is_dunder(node.attr):
                add(node, "dunder", f"the attribute {node.attr!r} is not allowed")
            elif _banned_attribute(node.attr):
                add(node, "banned-attribute", f"the attribute {node.attr!r} is not allowed")
        elif isinstance(node, ast.Global | ast.Nonlocal):
            add(node, "statement", f"{type(node).__name__.lower()} statements are not allowed")
        elif isinstance(node, ast.AsyncFunctionDef | ast.AsyncFor | ast.AsyncWith | ast.Await):
            add(node, "statement", "async code is not allowed")


def _check_top_level(tree: ast.Module, add: Adder) -> None:
    for index, node in enumerate(tree.body):
        if isinstance(node, ast.Import | ast.ImportFrom | ast.ClassDef | ast.FunctionDef):
            continue
        if index == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                continue
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not all(isinstance(target, ast.Name) for target in targets):
                add(node, "top-level", "a top-level assignment must assign to a plain name")
            elif node.value is not None and not _is_literal(node.value):
                add(node, "top-level", "a top-level assignment must assign a literal constant")
            continue
        add(node, "top-level", f"{type(node).__name__} statements are not allowed at the top level")


def _is_literal(node: ast.expr) -> bool:
    try:
        ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False
    return True


def _check_decorators(tree: ast.AST, add: Adder) -> None:
    top_level_functions = {id(node) for node in getattr(tree, "body", []) if isinstance(node, ast.FunctionDef)}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef | ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            name = target.id if isinstance(target, ast.Name) else None
            if name not in ALLOWED_DECORATORS:
                add(
                    decorator,
                    "decorator",
                    f"this decorator is not allowed; allowed: {', '.join(sorted(ALLOWED_DECORATORS))}",
                )
            elif name == _REGISTER and id(node) not in top_level_functions:
                add(decorator, "decorator", f"{_REGISTER} may only decorate a function at the top level")


def _check_registration(tree: ast.Module, signal_id: str, add: Adder) -> None:
    uses = [node for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id == _REGISTER]
    decorators: list[ast.Call] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            decorators += [
                d
                for d in node.decorator_list
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == _REGISTER
            ]
    if len(decorators) != 1 or len(uses) != 1:
        add(
            None,
            "register",
            f"the file must use {_REGISTER} exactly once, as @{_REGISTER}({signal_id!r}, ...) on a top-level function",
        )
        return
    arguments = decorators[0].args
    first = arguments[0] if arguments else None
    if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
        add(
            decorators[0],
            "register",
            f"the first argument of {_REGISTER} must be the id as a string literal {signal_id!r}",
        )
    elif first.value != signal_id:
        add(decorators[0], "register", f"the file registers {first.value!r} but its id is {signal_id!r}")
