"""The exit-7 message of ``bt report`` as docs/cli.md describes it: values, the cap of five, the missing sides."""

import json

import pytest

from backtest_agent.cli.compare import MISSING, Difference
from backtest_agent.cli.render import changed_message, difference_value

RUN = "20260115T103005Z-buy-and-hold-a-HHHHHHHH"


def changed(path: str, stored, fresh) -> Difference:
    return Difference(path, stored, fresh, "changed")


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        (0.41591999999999985, "0.41591999999999985"),  # every digit
        (0.3872, "0.3872"),
        (1.0, "1.0"),
        (20, "20"),
        (-3, "-3"),
        ("B", "B"),  # a string has no quotes
        ("a" * 64, "a" * 64),
        (None, "null"),
        (True, "true"),
        (False, "false"),
        (MISSING, "(missing)"),
        ({"b": 1, "a": [1, 2]}, '{"a":[1,2],"b":1}'),  # compact, keys sorted
        ([1, "x"], '[1,"x"]'),
    ],
)
def test_how_a_value_is_printed(value, shown: str) -> None:
    assert difference_value(value) == shown


def test_a_long_object_is_cut_after_80_characters() -> None:
    shown = difference_value({"key": "x" * 200})
    assert len(shown) == 80 and shown.endswith("...")
    assert shown == json.dumps({"key": "x" * 200}, sort_keys=True, separators=(",", ":"))[:77] + "..."


def test_one_difference_has_no_more_line_and_says_difference_not_differences() -> None:
    message = changed_message(RUN, "metrics", [changed("evaluation.x", 1.5, 2.5)])
    assert message.splitlines() == [
        f"run {RUN} no longer reproduces: metrics changed (1 difference)",
        "  evaluation.x: stored 1.5, now 2.5",
    ]


def test_five_differences_have_no_more_line() -> None:
    found = [changed(f"evaluation.k{i}", i, i + 1) for i in range(5)]
    lines = changed_message(RUN, "metrics", found).splitlines()
    assert lines[0].endswith("(5 differences)")
    assert len(lines) == 6 and not any("more" in line for line in lines)


def test_six_differences_print_five_and_one_more() -> None:
    found = [changed(f"evaluation.k{i}", i, i + 1) for i in range(6)]
    lines = changed_message(RUN, "metrics", found).splitlines()
    assert lines[0].endswith("(6 differences)")
    assert [line.split(":")[0].strip() for line in lines[1:6]] == [f"evaluation.k{i}" for i in range(5)]
    assert lines[6] == "  ... and 1 more"
    assert len(lines) == 7


def test_eighteen_differences_end_with_13_more() -> None:
    found = [changed(f"evaluation.k{i:02d}", i, i + 1) for i in range(18)]
    assert changed_message(RUN, "data", found).splitlines()[-1] == "  ... and 13 more"


def test_a_missing_and_an_extra_key_print_the_missing_side() -> None:
    found = [
        Difference("evaluation.gone", {"a": 1}, MISSING, "missing"),
        Difference("evaluation.new", MISSING, 2.5, "extra"),
    ]
    assert changed_message(RUN, "metrics", found).splitlines()[1:] == [
        '  evaluation.gone: stored {"a":1}, now (missing)',
        "  evaluation.new: stored (missing), now 2.5",
    ]


def test_a_string_with_line_breaks_is_printed_on_one_line_like_every_text_of_bt() -> None:
    message = changed_message(RUN, "metrics", [changed("evaluation.name", "first\nsecond\r\n\tthird", "a\n\n\nb")])
    assert message.splitlines() == [
        f"run {RUN} no longer reproduces: metrics changed (1 difference)",
        "  evaluation.name: stored first second third, now a b",
    ]


def test_a_character_that_xml_forbids_becomes_the_replacement_character_and_an_empty_string_is_none() -> None:
    message = changed_message(
        RUN, "metrics", [changed("evaluation.x", "red\x1b[31m", ""), changed("evaluation.y", "\x00", "   ")]
    )
    assert message.splitlines()[1:] == [
        "  evaluation.x: stored red�[31m, now (none)",
        "  evaluation.y: stored �, now (none)",
    ]


def test_a_path_is_cleaned_too() -> None:
    message = changed_message(RUN, "metrics", [changed('evaluation["a\nb"]', 1, 2)])
    assert len(message.splitlines()) == 2
