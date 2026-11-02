"""Only the gate executes strategy code: a scan of the syntax trees of everything in ``src/backtest_agent`` (ADR 0018).

``coded/loader.py`` is the one module that may compile and execute code and create a module object. The scan does not
grep for words (``re.compile`` is everywhere); it reads the syntax tree: calls of the builtins ``exec`` and ``compile``,
any use of ``eval`` or ``__import__``, ``importlib`` (only ``importlib.metadata``, only in the package ``__init__``),
``runpy``, ``pkgutil``, ``codeop``, ``import_module``, ``types.ModuleType``, the registry methods that load and unload
signals, and the ``sha256`` marker of a ``Signal``. The rules are tested on small trees written to a temporary
folder, one violation each, so that every rule is known to fire; then the real tree is scanned.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "backtest_agent"

LOADER = "coded/loader.py"
REGISTRY_FILES = {LOADER, "spec/signals.py"}  # the loader and the module that defines the registry
INIT = "__init__.py"

FORBIDDEN_NAMES = {"eval": "eval", "__import__": "__import__"}
EXECUTING_NAMES = {"exec", "compile"}  # the builtins; re.compile is an attribute and does not count
FORBIDDEN_MODULES = {"runpy", "pkgutil", "codeop"}
REGISTRY_METHODS = {"set_sha256", "unregister", "restore", "snapshot"}


def violations(root: Path) -> list[str]:
    """Every use outside its allowed place, as ``path:line: what``, for the Python files under ``root``."""
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        in_loader = relative == LOADER
        counts = {"exec": 0, "compile": 0, "ModuleType": 0}

        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                if node.id in FORBIDDEN_NAMES:
                    _note(found, relative, node, f"the builtin {node.id} is not allowed anywhere")
                elif node.id in EXECUTING_NAMES:
                    if in_loader:
                        counts[node.id] += 1
                    else:
                        _note(found, relative, node, f"the builtin {node.id} may only be used in {LOADER}")
                elif node.id == "import_module":
                    _note(found, relative, node, "import_module is not allowed")
            elif isinstance(node, ast.Attribute):
                if node.attr == "import_module":
                    _note(found, relative, node, "import_module is not allowed")
                elif node.attr == "ModuleType":
                    if in_loader:
                        counts["ModuleType"] += 1
                    else:
                        _note(found, relative, node, f"ModuleType may only be used in {LOADER}")
                elif node.attr in REGISTRY_METHODS and relative not in REGISTRY_FILES:
                    _note(
                        found,
                        relative,
                        node,
                        f"the registry method {node.attr} may only be used in {' and '.join(sorted(REGISTRY_FILES))}",
                    )
                elif node.attr == "_signals" and relative != "spec/signals.py":
                    _note(
                        found, relative, node, "the private content of the registry may only be used in spec/signals.py"
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    found += _module_problems(relative, node, alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                found += _module_problems(relative, node, module)
                for alias in node.names:
                    if alias.name == "ModuleType":
                        if in_loader:
                            counts["ModuleType"] += 1
                        else:
                            _note(found, relative, node, f"ModuleType may only be used in {LOADER}")
                    elif alias.name == "import_module":
                        _note(found, relative, node, "import_module is not allowed")
            elif isinstance(node, ast.Call) and relative not in REGISTRY_FILES:
                if any(keyword.arg == "sha256" for keyword in node.keywords):
                    _note(
                        found,
                        relative,
                        node,
                        f"the sha256 marker of a Signal may only be set in {' and '.join(sorted(REGISTRY_FILES))}",
                    )

        if in_loader:  # the loader does what it is for, once each, and nothing grows unnoticed
            expected = {"exec": 1, "compile": 1, "ModuleType": 1}
            if counts != expected:
                found.append(f"{LOADER}:1: expected exactly one use each of {expected}, found {counts}")
    return found


def _note(found: list[str], relative: str, node: ast.AST, what: str) -> None:
    found.append(f"{relative}:{node.lineno}: {what}")


def _module_problems(relative: str, node: ast.AST, module: str) -> list[str]:
    top = module.split(".")[0]
    where = f"{relative}:{node.lineno}"
    if top == "importlib":
        if module == "importlib.metadata" and relative == INIT:
            return []
        return [f"{where}: importlib is only allowed as importlib.metadata in {INIT}, got {module}"]
    if top in FORBIDDEN_MODULES:
        return [f"{where}: {top} is not allowed"]
    return []


# --- the real tree ---


def test_the_package_has_no_forbidden_use_outside_the_places_that_are_allowed() -> None:
    assert violations(SRC) == []


def test_the_scan_sees_the_loader_and_the_one_place_that_uses_importlib() -> None:
    assert (SRC / LOADER).is_file() and (SRC / INIT).is_file()
    assert "importlib.metadata" in (SRC / INIT).read_text(encoding="utf-8")
    assert len(list(SRC.rglob("*.py"))) > 60


# --- every rule fires on a small tree ---


def tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, source in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return tmp_path


LOADER_OK = (
    "import types\nmodule = types.ModuleType('m')\ncode = compile('1', 'f', 'exec')\nexec(code, module.__dict__)\n"
)
REGISTRY_USES = (
    "from dataclasses import replace\nSIGNALS.restore({})\nSIGNALS._signals.clear()\nx = Signal(sha256='a')\n"
)


def test_a_tree_that_only_uses_what_is_allowed_has_no_violation(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            LOADER: LOADER_OK,
            INIT: "from importlib.metadata import version\n",
            "other.py": "import re\nPATTERN = re.compile('a')\n",
            "spec/signals.py": REGISTRY_USES,
        },
    )
    assert violations(root) == []


@pytest.mark.parametrize(
    ("source", "what"),
    [
        ("exec('1')", "the builtin exec may only be used in coded/loader.py"),
        ("compile('1', 'f', 'exec')", "the builtin compile may only be used in coded/loader.py"),
        ("f = exec", "the builtin exec may only be used in coded/loader.py"),
        ("eval('1')", "the builtin eval is not allowed anywhere"),
        ("__import__('os')", "the builtin __import__ is not allowed anywhere"),
        ("import importlib", "importlib is only allowed as importlib.metadata in __init__.py, got importlib"),
        ("import importlib.util", "got importlib.util"),
        ("from importlib import util", "got importlib"),
        ("from importlib.util import spec_from_file_location", "got importlib.util"),
        ("from importlib.metadata import version", "importlib is only allowed as importlib.metadata in __init__.py"),
        ("import runpy", "runpy is not allowed"),
        ("import pkgutil", "pkgutil is not allowed"),
        ("from codeop import compile_command", "codeop is not allowed"),
        ("x = something.import_module('m')", "import_module is not allowed"),
        ("from importlib import import_module", "import_module is not allowed"),
        ("import types\nm = types.ModuleType('m')", "ModuleType may only be used in coded/loader.py"),
        ("from types import ModuleType", "ModuleType may only be used in coded/loader.py"),
        ("SIGNALS.set_sha256('a', 'b')", "the registry method set_sha256 may only be used in"),
        ("SIGNALS.unregister('a')", "the registry method unregister may only be used in"),
        ("SIGNALS.restore({})", "the registry method restore may only be used in"),
        ("before = SIGNALS.snapshot()", "the registry method snapshot may only be used in"),
        ("SIGNALS._signals['a'] = 1", "the private content of the registry may only be used in spec/signals.py"),
        ("x = Signal('a', P, f, sha256='ab')", "the sha256 marker of a Signal may only be set in"),
        ("x = replace(signal, sha256='ab')", "the sha256 marker of a Signal may only be set in"),
    ],
)
def test_every_rule_fires_in_a_module_that_is_not_allowed_to_do_it(tmp_path: Path, source: str, what: str) -> None:
    found = violations(tree(tmp_path, {"elsewhere/module.py": source + "\n"}))
    assert found, source
    assert all(line.startswith("elsewhere/module.py:") for line in found)
    assert any(what in line for line in found), found


def test_importlib_metadata_is_allowed_only_in_the_package_init(tmp_path: Path) -> None:
    root = tree(
        tmp_path, {INIT: "from importlib.metadata import version\n", "sub/__init__.py": "import importlib.metadata\n"}
    )
    found = violations(root)
    assert [line.split(":")[0] for line in found] == ["sub/__init__.py"]


def test_eval_and_import_are_not_allowed_even_in_the_loader(tmp_path: Path) -> None:
    root = tree(tmp_path, {LOADER: LOADER_OK + "eval('1')\n__import__('os')\n"})
    assert sorted(line.split(": ", 1)[1] for line in violations(root)) == [
        "the builtin __import__ is not allowed anywhere",
        "the builtin eval is not allowed anywhere",
    ]


@pytest.mark.parametrize(
    "source",
    [
        "import types\ncode = compile('1', 'f', 'exec')\nexec(code, {})\n",  # no module object
        LOADER_OK + "exec(code, {})\n",  # a second exec
        LOADER_OK + "compile('2', 'g', 'exec')\n",  # a second compile
        LOADER_OK + "other = types.ModuleType('n')\n",  # a second module object
        "x = 1\n",  # nothing at all
    ],
    ids=["no ModuleType", "two exec", "two compile", "two ModuleType", "nothing"],
)
def test_the_loader_does_exactly_one_of_each_thing_it_is_for(tmp_path: Path, source: str) -> None:
    found = violations(tree(tmp_path, {LOADER: source}))
    assert len(found) == 1 and "expected exactly one use each of" in found[0], found


def test_a_registry_method_and_the_marker_are_allowed_in_the_loader_and_in_the_registry_module(tmp_path: Path) -> None:
    source = "SIGNALS.set_sha256('a', 'b')\nSIGNALS.unregister('a')\nx = Signal('a', P, f, sha256='ab')\n"
    root = tree(tmp_path, {LOADER: LOADER_OK + source, "spec/signals.py": source})
    assert violations(root) == []
