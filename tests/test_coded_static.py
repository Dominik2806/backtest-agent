"""Static check of a coded signal's source (backtest_agent.coded.static): every rule has a literal bad source.

A source is built from a fixed head (lines 1 and 2, a blank line 3), the lines under test (line 4 on) and a correct
registration of the id ``sig``, so a case only lists what it breaks. ``(i, rule)`` means "the i-th line under
test breaks this rule", i.e. source line ``4 + i``.
"""

import pytest

from backtest_agent.coded.errors import Finding, StaticCheckError
from backtest_agent.coded.static import (
    ALLOWED_DECORATORS,
    BANNED_ATTRIBUTES,
    BANNED_NAMES,
    MAX_SOURCE_BYTES,
    check_source,
    find_problems,
)

HEAD = ["from backtest_agent.spec.signals import SignalParams, register_signal", "import pandas as pd", ""]
TAIL = ["", '@register_signal("sig", params=SignalParams)', "def sig(prices, params):", "    return prices"]
FIRST = len(HEAD) + 1  # source line of the first line under test


def build(middle: list[str]) -> bytes:
    return "\n".join(HEAD + middle + TAIL).encode("utf-8")


def rules(source: bytes, signal_id: str = "sig") -> set[tuple[int, str]]:
    return {(f.line, f.rule) for f in find_problems(source, signal_id)}


def at(*expected: tuple[int, str]) -> set[tuple[int, str]]:
    return {(FIRST + index, rule) for index, rule in expected}


GOOD = "\n".join(
    [
        '"""A signal that holds a symbol while its close is above its rolling mean."""',
        "import numpy as np",
        "import pandas as pd",
        "from pydantic import Field, field_validator",
        "from backtest_agent.spec.signals import SignalParams, per_symbol_signal, register_signal",
        "",
        "LIMIT = 100",
        "NAMES: tuple = ('a', 'b')",
        "",
        "class Params(SignalParams):",
        '    """Window of the mean."""',
        "",
        "    window: int = Field(14, ge=1)",
        "",
        '    @field_validator("window")',
        "    @classmethod",
        "    def _limit(cls, window: int) -> int:",
        "        if window > LIMIT:",
        "            raise ValueError('window too large')",
        "        return window",
        "",
        "    def warmup_rows(self) -> int:",
        "        return self.window - 1",
        "",
        "def _mean_rule(close: pd.Series, window: int) -> pd.Series:",
        "    mean = close.rolling(window, min_periods=window).mean()",
        "    rng = np.random.default_rng(0)",
        "    values = [float(v) for v in rng.random(2)]",
        "    return (close > mean).astype('float64').where(mean.notna()) + 0 * values[0]",
        "",
        '@register_signal("sig", params=Params)',
        "def sig(prices: pd.DataFrame, params: Params) -> pd.DataFrame:",
        '    """1.0 while the close is above its mean."""',
        "    return per_symbol_signal(prices, lambda close: _mean_rule(close, params.window))",
    ]
).encode("utf-8")


def test_a_compliant_source_passes() -> None:
    assert find_problems(GOOD, "sig") == ()
    check_source(GOOD, "sig")  # does not raise


def test_the_source_is_never_executed() -> None:
    # A source whose import would raise is only parsed: the check reports its problems and nothing else happens.
    source = build(["raise SystemExit(3)"])
    assert rules(source) == at((0, "top-level"))


# --- default arguments, decorators, class bodies and comprehensions run at import time: the whole tree is checked ---

IMPORT_TIME = [
    ("default argument", ["def helper(x=open('f')):", "    return x"], {(0, "banned-name")}),
    ("keyword-only default", ["def helper(*, x=eval('1')):", "    return x"], {(0, "banned-name")}),
    ("decorator", ["@open('f')", "def helper():", "    pass"], {(0, "banned-name"), (0, "decorator")}),
    ("class body", ["class P(SignalParams):", "    data = open('f')"], {(1, "banned-name")}),
    (
        "comprehension in a class body",
        ["class P(SignalParams):", "    v = [open(f) for f in 'ab']"],
        {(1, "banned-name")},
    ),
    ("top-level comprehension", ["NAMES = [eval(x) for x in 'ab']"], {(0, "banned-name"), (0, "top-level")}),
    ("generator expression", ["def f():", "    return sum(open(x) for x in 'ab')"], {(1, "banned-name")}),
    ("lambda default", ["def f(g=lambda: __import__('os')):", "    pass"], {(0, "banned-name")}),
]


@pytest.mark.parametrize(("label", "middle", "expected"), IMPORT_TIME, ids=[case[0] for case in IMPORT_TIME])
def test_a_banned_call_is_found_wherever_it_runs_at_import_time(label, middle, expected) -> None:
    assert rules(build(middle)) == at(*expected)


# --- names and attributes ---


@pytest.mark.parametrize("name", sorted(BANNED_NAMES))
def test_every_banned_name_is_refused(name: str) -> None:
    assert rules(build(["def f():", f"    return {name}"])) == at((1, "banned-name"))


@pytest.mark.parametrize("attribute", sorted(BANNED_ATTRIBUTES))
def test_every_banned_attribute_is_refused(attribute: str) -> None:
    assert rules(build(["def f(df):", f"    return df.{attribute}"])) == at((1, "banned-attribute"))


def test_eval_and_query_are_banned_attributes_on_frames_and_on_pandas() -> None:
    middle = ["def f(df):", "    a = df.eval('x + 1')", "    b = pd.eval('1 + 1')", "    return df.query('x > 1')"]
    assert rules(build(middle)) == at((1, "banned-attribute"), (2, "banned-attribute"), (3, "banned-attribute"))


def test_any_read_attribute_is_banned_but_a_name_that_only_contains_read_is_not() -> None:
    bad = build(["def f():", "    return pd.read_csv('x'), pd.read_anything_new('y')"])
    assert rules(bad) == at((1, "banned-attribute"))
    ok = build(["def f(spread, df):", "    return spread.read, df.bread_and, df.ahead"])
    assert rules(ok) == set()


@pytest.mark.parametrize(
    ("expression", "rule"),
    [
        ("__builtins__", "dunder"),
        ("__name__", "dunder"),
        ("__file__", "dunder"),
        ("prices.__class__", "dunder"),
        ("prices.__dict__", "dunder"),
        ("().__class__.__bases__", "dunder"),
        ("__builtins__['open']", "dunder"),
    ],
)
def test_names_and_attributes_with_two_underscores_at_both_ends_are_refused(expression: str, rule: str) -> None:
    found = rules(build(["def f(prices):", f"    return {expression}"]))
    assert found == at((1, rule))


def test_a_single_leading_underscore_and_dunder_method_definitions_are_fine() -> None:
    ok = build(
        [
            "class P(SignalParams):",
            "    def __init__(self, **data):",
            "        self._x = 1",
        ]
    )
    assert rules(ok) == set()


def test_names_in_an_f_string_are_checked() -> None:
    assert rules(build(["def f(prices):", "    return f'{prices.__class__}'"])) == at((1, "dunder"))


# --- imports ---


@pytest.mark.parametrize(
    "line",
    [
        "import os",
        "import sys",
        "import socket",
        "import subprocess",
        "import pandas.io",
        "import numpy.lib",
        "import importlib",
        "from os import path",
        "from urllib.request import urlopen",
        "from . import sibling",
        "from .. import parent",
        "from backtest_agent.engine import run_backtest",
        "from backtest_agent.spec import SIGNALS",
        "import backtest_agent",
    ],
)
def test_imports_outside_the_allowlist_are_refused(line: str) -> None:
    assert rules(build([line])) == at((0, "import"))


@pytest.mark.parametrize("name", ["SIGNALS", "SignalRegistry", "get_signal", "list_signals", "validate_signal_output"])
def test_only_the_helpers_may_be_imported_from_the_signals_module(name: str) -> None:
    assert rules(build([f"from backtest_agent.spec.signals import {name}"])) == at((0, "import"))


def test_star_imports_and_banned_imported_names_are_refused() -> None:
    assert rules(build(["from numpy import *"])) == at((0, "import"))
    assert rules(build(["from pandas import read_csv"])) == at((0, "banned-attribute"))
    assert rules(build(["from numpy import load, loadtxt"])) == at((0, "banned-attribute"))
    assert rules(build(["from math import __loader__"])) == at((0, "banned-attribute"))


def test_an_import_inside_a_function_is_checked_too() -> None:
    assert rules(build(["def f():", "    import os", "    from math import sqrt"])) == at((1, "import"))


def test_the_allowed_modules_import() -> None:
    lines = [
        "import math",
        "import numpy as np",
        "import typing",
        "from pydantic import BaseModel",
        "from typing import Any",
    ]
    assert rules(build(lines)) == set()


# --- the top level ---


@pytest.mark.parametrize(
    "line",
    [
        "print('x')",
        "if True:\n    pass",
        "for i in range(3):\n    pass",
        "while False:\n    pass",
        "with pd.option_context('a', 1):\n    pass",
        "try:\n    pass\nexcept Exception:\n    pass",
        "assert True",
        "del pd",
        "raise ValueError('x')",
        "pd.options.mode.chained_assignment = None",
        "x = y = pd",
        "LIMIT = 1 + len('a')",
        "NAMES = tuple(range(3))",
        "A, B = 1, 2",
    ],
)
def test_the_top_level_may_only_hold_literals_imports_classes_and_functions(line: str) -> None:
    assert rules(build([line])) == at((0, "top-level"))


def test_top_level_literals_are_fine() -> None:
    lines = [
        "LIMIT = 100",
        "RATE = -0.5",
        "NAMES = ('a', 'b')",
        "TABLE = {'a': [1, 2.5, None, True]}",
        "DOC: str = 'x'",
        "NOTHING: int",
    ]
    assert rules(build(lines)) == set()


def test_a_docstring_is_allowed_only_as_the_first_statement() -> None:
    first = ('"""Doc."""\n' + build([]).decode()).encode()
    assert find_problems(first, "sig") == ()
    middle = rules(build(['"""A docstring in the middle."""']))
    assert middle == at((0, "top-level"))


# --- decorators ---


def test_only_the_listed_decorators_are_allowed() -> None:
    assert ALLOWED_DECORATORS == {
        "classmethod", "field_validator", "model_validator", "property", "register_signal", "staticmethod"
    }  # fmt: skip
    assert rules(build(["import functools", "@functools.cache", "def f():", "    pass"])) == at(
        (0, "import"), (1, "decorator")
    )
    assert rules(build(["@staticmethod", "def f():", "    pass"])) == set()


def test_register_signal_may_only_decorate_a_top_level_function() -> None:
    middle = ["class P(SignalParams):", "    @register_signal('sig')", "    def m(self):", "        pass"]
    assert rules(build(middle)) == {(0, "register"), (FIRST + 1, "decorator")}  # nothing is registered at the top level


# --- registration ---


def head_only(*lines: str) -> bytes:
    return "\n".join(HEAD + list(lines)).encode("utf-8")


def test_a_file_that_registers_nothing_is_refused() -> None:
    assert [
        (f.line, f.rule) for f in find_problems(head_only("def sig(prices, params):", "    return prices"), "sig")
    ] == [(0, "register")]


def test_a_file_that_registers_twice_is_refused() -> None:
    twice = head_only(
        '@register_signal("sig", params=SignalParams)', "def sig(prices, params):", "    return prices", "",
        '@register_signal("other", params=SignalParams)', "def other(prices, params):", "    return prices",
    )  # fmt: skip
    assert [(f.line, f.rule) for f in find_problems(twice, "sig")] == [(0, "register")]


def test_the_registered_id_must_be_the_id_of_the_file() -> None:
    source = build([])
    found = find_problems(source, "other_id")
    assert [(f.line, f.rule) for f in found] == [(len(HEAD) + 1 + 1, "register")]
    assert found[0].message == "the file registers 'sig' but its id is 'other_id'"


def test_the_id_must_be_a_string_literal() -> None:
    source = head_only(
        "NAME = 'sig'", "@register_signal(NAME, params=SignalParams)", "def sig(prices, params):", "    return prices"
    )
    found = find_problems(source, "sig")
    assert [(f.line, f.rule) for f in found] == [(len(HEAD) + 2, "register")]


def test_an_alias_of_register_signal_is_refused() -> None:
    source = head_only("reg = register_signal", '@reg("sig")', "def sig(prices, params):", "    return prices")
    found = rules(source)
    assert (len(HEAD) + 1, "top-level") in found and (0, "register") in found
    assert (len(HEAD) + 2, "decorator") in found


def test_register_signal_called_inside_a_function_is_a_second_use() -> None:
    source = build(["def f():", "    return register_signal('sig')"])
    assert [(f.line, f.rule) for f in find_problems(source, "sig")] == [(0, "register")]


# --- statements, encoding, size, syntax ---


def test_global_nonlocal_and_async_code_are_refused() -> None:
    middle = [
        "COUNT = 1",
        "def f():",
        "    global COUNT",
        "    COUNT = 2",
        "def g():",
        "    x = 1",
        "    def h():",
        "        nonlocal x",
        "async def a():",
        "    pass",
    ]
    assert rules(build(middle)) == at((2, "statement"), (7, "statement"), (8, "statement"), (8, "top-level"))


def test_a_byte_order_mark_a_nul_byte_and_invalid_utf8_are_refused() -> None:
    good = build([])
    assert [(f.line, f.rule) for f in find_problems(b"\xef\xbb\xbf" + good, "sig")] == [(0, "encoding")]
    assert [(f.line, f.rule) for f in find_problems(good + b"\x00", "sig")] == [(0, "encoding")]
    bad = find_problems(good + b"\n# \xff\n", "sig")
    assert [(f.line, f.rule) for f in bad] == [(0, "encoding")]
    assert bad[0].message == "the source is not UTF-8 (invalid start byte at byte " + str(len(good) + 3) + ")"


def test_a_source_over_the_size_limit_is_refused() -> None:
    padding = b"\n# " + b"x" * (MAX_SOURCE_BYTES - len(build([])) - 3)
    at_limit = build([]) + padding
    assert len(at_limit) == MAX_SOURCE_BYTES
    assert find_problems(at_limit, "sig") == ()
    over = at_limit + b"x"
    assert [(f.line, f.rule) for f in find_problems(over, "sig")] == [(0, "size")]


def test_a_syntax_error_is_reported_with_its_line() -> None:
    found = find_problems(build(["def broken(:", "    pass"]), "sig")
    assert [(f.line, f.rule) for f in found] == [(FIRST, "syntax")]
    assert found[0].message.startswith("syntax error: ")


# --- reporting ---


def test_every_problem_is_reported_not_only_the_first() -> None:
    middle = ["import os", "def f(df):", "    return open('x'), df.query('a')", "print(1)"]
    assert rules(build(middle)) == at((0, "import"), (2, "banned-name"), (2, "banned-attribute"), (3, "top-level"))


def test_findings_are_sorted_by_line() -> None:
    found = find_problems(build(["print(1)", "import os"]), "sig")
    assert [f.line for f in found] == sorted(f.line for f in found)


def test_the_error_lists_every_finding_with_its_line_and_rule() -> None:
    with pytest.raises(StaticCheckError) as info:
        check_source(build(["import os", "print(1)"]), "sig")
    assert str(info.value) == (
        "the signal source breaks 2 rules of the static check:\n"
        "  - line 4: import of 'os' is not allowed [import]\n"
        "  - line 5: a Expr statement is not allowed at the top level [top-level]"
    )
    assert info.value.findings == (
        Finding(4, 0, "import", "import of 'os' is not allowed"),
        Finding(5, 0, "top-level", "a Expr statement is not allowed at the top level"),
    )


@pytest.mark.parametrize("name", ["_", "__", "___", "____", "__a", "a__", "_a_"])
def test_names_that_are_not_two_underscores_around_a_word_are_not_dunder(name: str) -> None:
    assert rules(build(["def f():", f"    {name} = 1", f"    return {name}"])) == set()


@pytest.mark.parametrize("name", ["__a__", "__init__", "_____", "__x1__"])
def test_two_underscores_around_at_least_one_character_are_dunder(name: str) -> None:
    assert rules(build(["def f():", f"    return {name}"])) == at((1, "dunder"))
