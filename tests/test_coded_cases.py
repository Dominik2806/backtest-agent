"""The cases.yaml of a coded signal (backtest_agent.coded.cases): the format, its limits and running the examples.

The expected exposures are calculated by hand next to each example. The signal is "1.0 on a day when the close is above
the symbol's previous close" (its own trading rows), with a warm-up of one row.
"""

import numpy as np
import pandas as pd
import pytest
import yaml

from backtest_agent.coded.cases import (
    MAX_CASES,
    MAX_FILE_BYTES,
    MAX_FLOW_DEPTH,
    MAX_ROWS,
    MAX_SYMBOLS,
    cases_path,
    parse_cases,
    read_cases,
    run_cases,
)
from backtest_agent.coded.errors import CasesError
from backtest_agent.spec import Signal, SignalParams
from backtest_agent.spec.signals import per_symbol_signal


class UpParams(SignalParams):
    threshold: float = 0.0

    def warmup_rows(self) -> int:
        return 1


def up_day(prices: pd.DataFrame, params: UpParams) -> pd.DataFrame:
    """1.0 where the close is above the previous close of the symbol by more than the threshold."""
    return per_symbol_signal(prices, lambda close: (close - close.shift(1) > params.threshold).astype("float64"))


SIGNAL = Signal("up_day", UpParams, up_day)

GOOD = """\
signal: up_day
cases:
  - name: rises, falls and rises
    prices:
      AAA: [10, 11, 10, 12]
      BBB: [null, 20, 21, 19]
    expected:
      AAA: [0, 1, 0, 1]
      BBB: [0, 0, 1, 0]
"""
# AAA: row 0 is its first row (0.0); 11 > 10 gives 1; 10 > 11 no (0); 12 > 10 gives 1.
# BBB: no trade on row 0; row 1 is its first trading row (0.0, warm-up); 21 > 20 gives 1; 19 > 21 no (0).
# The carried values over BBB's missing day do not appear: BBB is missing only before its first row.


def parse(text: str) -> object:
    return parse_cases(text.encode("utf-8"), "up_day")


def problems(text: str | bytes, signal_id: str = "up_day") -> list[str]:
    data = text if isinstance(text, bytes) else text.encode("utf-8")
    with pytest.raises(CasesError) as info:
        parse_cases(data, signal_id)
    return str(info.value).splitlines()


# --- the format ---


def test_a_valid_file_is_parsed_and_its_examples_hold() -> None:
    cases = parse(GOOD)
    assert [case.name for case in cases.cases] == ["rises, falls and rises"]  # type: ignore[attr-defined]
    assert run_cases(SIGNAL, cases) == 1  # type: ignore[arg-type]


def test_integers_and_floats_are_both_numbers_and_the_signal_and_params_are_optional() -> None:
    text = "cases:\n  - name: a\n    prices: {AAA: [1, 2.5]}\n    expected: {AAA: [0, 1]}\n"
    assert run_cases(SIGNAL, parse(text)) == 1  # type: ignore[arg-type]  # 2.5 > 1: row 1 is 1.0


def test_the_params_of_the_file_are_used_for_every_case() -> None:
    text = doc(prices={"AAA": [10, 11, 13]}, expected={"AAA": [0, 0, 1]}, top={"params": {"threshold": 1.5}})
    # 11 - 10 = 1 is not above 1.5, and 13 - 11 = 2 is
    assert run_cases(SIGNAL, parse(text)) == 1  # type: ignore[arg-type]


def test_a_file_with_crlf_is_the_same_file() -> None:
    assert run_cases(SIGNAL, parse(GOOD.replace("\n", "\r\n"))) == 1  # type: ignore[arg-type]


def doc(prices=None, expected=None, name="a", case_extra=None, top=None, drop=()) -> str:
    """The text of a cases file with one case, made from plain Python values and dumped as YAML."""
    case = {
        "name": name,
        "prices": {"A": [1]} if prices is None else prices,
        "expected": {"A": [0]} if expected is None else expected,
    }
    case.update(case_extra or {})
    for key in drop:
        del case[key]
    return yaml.safe_dump({**(top or {}), "cases": [case]}, sort_keys=False)


NULL_PARAM = (
    "params: the parameter 'a' of a coded signal must be a number, text, true or false, or a list of those "
    "(no null, no nested block, no NaN or infinity), got None"
)
SAME_ROWS = "cases[0]: every symbol needs the same number of rows in prices and expected, got [1, 2]"

INVALID = [
    ("[]", "(root): the file must be a mapping with a list of cases"),
    ("{}", "cases: missing required field"),
    ("cases: []", "cases: List should have at least 1 item after validation, not 0"),
    (doc(top={"signal": "other"}), "signal: the file is for 'other' but the signal is 'up_day'"),
    (doc(case_extra={"extra": 1}), "cases[0].extra: unknown field"),
    (doc(drop=("expected",)), "cases[0].expected: missing required field"),
    (doc(prices={"A": [0]}), "cases[0].prices.A[0]: Input should be greater than 0"),
    (doc(prices={"A": [-1]}), "cases[0].prices.A[0]: Input should be greater than 0"),
    (doc(expected={"A": [1.5]}), "cases[0].expected.A[0]: Input should be less than or equal to 1"),
    (doc(expected={"A": [-0.1]}), "cases[0].expected.A[0]: Input should be greater than or equal to 0"),
    (doc(prices={"A": [True]}), "cases[0].prices.A[0]: Input should be a valid number"),
    (doc(prices={"A": [float("nan")]}), "cases[0].prices.A[0]: Input should be a finite number"),
    (doc(prices={"A": [1, 2]}), SAME_ROWS),
    (doc(expected={"B": [0]}), "cases[0]: prices has the symbols ['A'] but expected has ['B']"),
    (doc(prices={"A": [None]}), "cases[0]: A never trades in prices; give it at least one price"),
    (doc(name=""), "cases[0].name: String should have at least 1 character"),
    (doc(drop=("name",)), "cases[0].name: missing required field"),
    (doc(top={"params": {"a": None}}), NULL_PARAM),
]


@pytest.mark.parametrize(("text", "problem"), INVALID, ids=[str(i) for i in range(len(INVALID))])
def test_every_way_a_file_can_be_invalid_has_a_message_with_the_field(text: str, problem: str) -> None:
    assert problems(text) == ["cases.yaml is not valid (1 problem):", "  - " + problem]


def test_all_problems_are_listed_not_only_the_first() -> None:
    first = "{name: a, prices: {A: [0]}, expected: {A: [2]}}"
    second = "{name: b, prices: {B: [1]}, expected: {B: [-1]}}"
    text = f"cases:\n  - {first}\n  - {second}\n"
    lines = problems(text)
    assert lines[0] == "cases.yaml is not valid (3 problems):"
    assert [line.split(":")[0] for line in lines[1:]] == [
        "  - cases[0].prices.A[0]",
        "  - cases[0].expected.A[0]",
        "  - cases[1].expected.B[0]",
    ]


def test_a_key_given_twice_aliases_and_syntax_errors_are_refused() -> None:
    twice = "cases: []\ncases: []\n"
    assert problems(twice)[1].startswith("  - (yaml): syntax error at line 2, column 1: the key 'cases' is given twice")
    alias = "x: &a [1]\ncases: *a\n"
    assert problems(alias) == ["cases.yaml is not valid (1 problem):", "  - (yaml): aliases are not allowed"]
    assert problems("cases: [")[1].startswith("  - (yaml): syntax error at line")
    assert problems("a: !!python/object/apply:os.system ['echo']")[1].startswith("  - (yaml): syntax error")


def test_hidden_characters_and_bad_bytes_are_refused() -> None:
    hidden = GOOD.replace("rises", "ri" + chr(0x200B) + "ses")
    assert problems(hidden) == [
        "cases.yaml is not valid (1 problem):",
        "  - line 3: the character U+200B is not allowed",
    ]
    assert problems(GOOD + chr(0x202E))[1].endswith("the character U+202E is not allowed")
    assert problems(b"cases: \xff")[1].startswith("  - (file): not UTF-8 (invalid start byte at byte 7)")
    assert problems(GOOD.replace("rises", "ri\rses"))[1].endswith("the character U+000D is not allowed")


def test_the_limits_of_the_format() -> None:
    assert (MAX_CASES, MAX_SYMBOLS, MAX_ROWS, MAX_FILE_BYTES) == (50, 10, 400, 262144)

    def many_cases(n: int) -> str:
        cases = [{"name": "n", "prices": {"A": [1]}, "expected": {"A": [0]}} for _ in range(n)]
        return yaml.safe_dump({"cases": cases}, sort_keys=False)

    parse(many_cases(MAX_CASES))
    assert "at most 50 items" in problems(many_cases(MAX_CASES + 1))[1]

    def rows(n: int) -> str:
        return doc(prices={"A": [1] * n}, expected={"A": [0] * n})

    parse(rows(MAX_ROWS))
    assert "a case needs 1 to 400 rows, got 401" in problems(rows(MAX_ROWS + 1))[1]

    def symbols(n: int) -> str:
        return doc(prices={f"S{i}": [1] for i in range(n)}, expected={f"S{i}": [0] for i in range(n)})

    parse(symbols(MAX_SYMBOLS))
    assert "prices needs 1 to 10 symbols, got 11" in problems(symbols(MAX_SYMBOLS + 1))[1]


def test_a_file_of_exactly_the_size_limit_is_read_and_a_larger_one_is_refused(tmp_path) -> None:
    base = GOOD
    pad = "#" * (MAX_FILE_BYTES - len(base.encode()) - 3) + "\n"
    exact = ("# " + pad + base).encode()
    assert len(exact) == MAX_FILE_BYTES
    path = tmp_path / "up_day.cases.yaml"
    path.write_bytes(exact)
    assert run_cases(SIGNAL, read_cases(path, "up_day")) == 1
    path.write_bytes(exact + b"#")
    with pytest.raises(CasesError, match="up_day.cases.yaml has 262145 bytes; the limit is 262144"):
        read_cases(path, "up_day")


def test_a_missing_file_and_a_folder_are_cases_errors(tmp_path) -> None:
    assert cases_path(tmp_path, "up_day") == tmp_path / "up_day.cases.yaml"
    with pytest.raises(CasesError) as info:
        read_cases(cases_path(tmp_path, "up_day"), "up_day")
    assert str(info.value) == "up_day.cases.yaml is missing; the signal coder writes the examples of 'up_day' in it"
    (tmp_path / "up_day.cases.yaml").mkdir()
    with pytest.raises(CasesError, match=r"^up_day.cases.yaml cannot be read \(not a regular file\)$"):
        read_cases(cases_path(tmp_path, "up_day"), "up_day")


# --- running the examples ---


def test_a_difference_names_the_case_the_symbol_the_row_the_date_and_both_values() -> None:
    wrong = GOOD.replace("AAA: [0, 1, 0, 1]", "AAA: [0, 1, 1, 0.5]")
    with pytest.raises(CasesError) as info:
        run_cases(SIGNAL, parse(wrong))
    assert str(info.value) == (
        "2 differences in the examples:\n"
        "  - up_day on the case 'rises, falls and rises': AAA row 2 (2024-01-04): expected 1.0, got 0.0\n"
        "  - up_day on the case 'rises, falls and rises': AAA row 3 (2024-01-05): expected 0.5, got 1.0"
    )


def test_at_most_ten_differences_are_listed_and_the_rest_is_counted() -> None:
    n = 14
    text = (
        "cases:\n  - {name: many, prices: {A: ["
        + ", ".join(["1"] * n)
        + "]}, expected: {A: ["
        + ", ".join(["1"] * n)
        + "]}}\n"
    )
    with pytest.raises(CasesError) as info:  # a constant price gives 0.0 everywhere; 1.0 is expected on all 14 rows
        run_cases(SIGNAL, parse(text))
    lines = str(info.value).splitlines()
    assert lines[0] == "14 differences in the examples:"
    assert len(lines) == 12 and lines[-1] == "  - ... and 4 more"


def test_a_difference_below_the_tolerance_is_not_one() -> None:
    near = GOOD.replace("AAA: [0, 1, 0, 1]", "AAA: [0, 0.9999999999, 1.0e-10, 1]")
    assert run_cases(SIGNAL, parse(near)) == 1  # type: ignore[arg-type]
    far = GOOD.replace("AAA: [0, 1, 0, 1]", "AAA: [0, 1, 0.000001, 1]")
    with pytest.raises(CasesError, match="AAA row 2"):
        run_cases(SIGNAL, parse(far))


def test_anything_the_code_raises_is_a_failed_case() -> None:
    def broken(prices: pd.DataFrame, params: UpParams) -> pd.DataFrame:
        raise KeyError("close")

    with pytest.raises(CasesError) as info:
        run_cases(Signal("up_day", UpParams, broken), parse(GOOD))
    assert str(info.value) == (
        "1 difference in the examples:\n  - up_day on the case 'rises, falls and rises': KeyError: 'close'"
    )


def test_a_contract_violation_in_a_case_is_a_failed_case_with_the_contract_message() -> None:
    def always_on(prices: pd.DataFrame, params: UpParams) -> pd.DataFrame:
        return pd.DataFrame(1.0, index=prices.index, columns=prices.columns.get_level_values("symbol").unique())

    with pytest.raises(CasesError) as info:
        run_cases(Signal("up_day", UpParams, always_on), parse(GOOD))
    assert str(info.value) == (
        "1 difference in the examples:\n"
        "  - up_day on the case 'rises, falls and rises': SignalContractError: signal output violates the contract: "
        "exposure must be 0.0 before a symbol's trading row 2 (warmup_rows is 1); 'AAA': 1 value(s) non-zero, first at "
        "2024-01-02; 'BBB': 2 value(s) non-zero, first at 2024-01-02"
    )


def test_params_the_signal_does_not_accept_are_a_cases_error() -> None:
    text = "params: {nope: 1}\ncases: [{name: a, prices: {A: [1]}, expected: {A: [0]}}]"
    with pytest.raises(CasesError, match="up_day: the params of the cases are not valid for the signal"):
        run_cases(SIGNAL, parse(text))


def test_the_frame_of_a_case_is_the_documented_one() -> None:
    from backtest_agent.coded.cases import _frame

    case = parse(GOOD).cases[0]  # type: ignore[attr-defined]
    frame = _frame(case)
    assert [d.date().isoformat() for d in frame.index] == ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    assert list(frame.columns.get_level_values("symbol").unique()) == ["AAA", "BBB"]
    assert frame[("BBB", "close")].isna().tolist() == [True, False, False, False]
    assert frame[("AAA", "open")].tolist() == frame[("AAA", "close")].tolist() == [10.0, 11.0, 10.0, 12.0]
    assert np.isnan(frame[("BBB", "volume")].iloc[0]) and frame[("BBB", "volume")].iloc[1] == 1000.0


def test_a_huge_file_is_refused_by_its_size_before_it_is_read(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "up_day.cases.yaml"
    path.write_bytes(b"#" * (2 * MAX_FILE_BYTES))
    monkeypatch.setattr(type(path), "open", lambda *a, **k: (_ for _ in ()).throw(AssertionError("opened")))
    with pytest.raises(CasesError) as info:
        read_cases(path, "up_day")
    assert str(info.value) == "up_day.cases.yaml has 524288 bytes; the limit is 262144"


# --- input that is too deep for the YAML parser ---

TOO_DEEP = ["(yaml): too deeply nested"]


@pytest.mark.parametrize(
    "text",
    ["[" * 100000, "{a: " * 50000, "[" * 21, "[" * 10 + "{" * 11, "cases: " + "[" * 100000 + "]" * 100000],
    ids=["100000 brackets", "50000 braces", "21 brackets", "10 and 11 mixed", "closed"],
)
def test_nesting_beyond_the_limit_is_refused_at_once_not_after_minutes(text: str) -> None:
    # PyYAML needs quadratic time for a long run of opening brackets (13 s for 16000, minutes for 100000): the file is
    # refused by a count before the parser sees it, so this test returns immediately.
    assert len(text.encode()) <= MAX_FILE_BYTES
    assert problems(text) == ["cases.yaml is not valid (1 problem):", "  - " + TOO_DEEP[0]]


def test_nesting_up_to_the_limit_is_still_read() -> None:
    assert MAX_FLOW_DEPTH == 20
    with pytest.raises(CasesError) as info:  # 20 deep is read; it is only not a cases file
        parse("[" * 20 + "]" * 20)
    assert info.value.args[0].splitlines()[1] == "  - (root): the file must be a mapping with a list of cases"


def test_brackets_that_are_closed_again_do_not_add_up() -> None:
    from backtest_agent.coded.cases import _too_deep

    assert _too_deep("[1]," * 5000) is False  # many brackets, each closed at once: the depth never passes 1
    assert _too_deep("]" * 50 + "[" * 20) is False  # a closing bracket without an opening one does not go below 0
    assert _too_deep("[" * 21) is True and _too_deep("[" * 20) is False


@pytest.mark.parametrize("error", [RecursionError("maximum recursion depth exceeded"), MemoryError()])
def test_a_recursion_or_memory_error_of_the_yaml_library_is_a_cases_error(
    error: BaseException, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(*args, **kwargs):
        raise error

    monkeypatch.setattr("backtest_agent.coded.cases.yaml.load", failing)
    assert problems(GOOD) == ["cases.yaml is not valid (1 problem):", "  - " + TOO_DEEP[0]]


def test_the_count_covers_the_whole_text_so_brackets_in_a_comment_count_too() -> None:
    # This pins the documented behaviour (docs/coded-signals.md): "at most 20 brackets open at once, counted over the
    # whole text, quotes and comments included". 21 unclosed brackets in a comment are refused like any others; the
    # scan is a cheap guard against a parser that needs quadratic time, not a reader of YAML.
    comment = "# [" * 21
    assert problems(comment) == ["cases.yaml is not valid (1 problem):", "  - " + TOO_DEEP[0]]
    assert problems(GOOD + comment) == ["cases.yaml is not valid (1 problem):", "  - " + TOO_DEEP[0]]
    parse(GOOD + "# [" * 20)  # 20 open brackets in a comment are still read
