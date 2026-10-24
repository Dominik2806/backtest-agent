"""The comparison of ``bt report`` with literal dictionaries: every rule of docs/cli.md ("bt report")."""

from typing import Any

import pytest

from backtest_agent.cli.compare import (
    COMPARED_KEYS,
    MISSING,
    Difference,
    change_kind,
    differences,
    is_data_hash,
    prioritized,
)


def record(**parts: Any) -> dict[str, Any]:
    """A record whose compared keys are empty objects unless given."""
    return {key: parts.get(key, {}) for key in COMPARED_KEYS}


def value_diffs(stored: Any, fresh: Any) -> list[Difference]:
    return differences(record(evaluation={"x": stored}), record(evaluation={"x": fresh}))


def equal(stored: Any, fresh: Any) -> bool:
    return value_diffs(stored, fresh) == []


def test_equal_records_have_no_difference() -> None:
    both = record(spec={"a": 1}, evaluation={"m": [1.5, None, "s", True]}, trades={"n": 2}, costs={"c": 0.0})
    assert differences(both, both) == []


def test_the_keys_that_are_not_compared_are_ignored() -> None:
    stored = {
        **record(),
        "code_version": {"commit": "a"},
        "generated_at": "2026-01-15T10:30:05Z",
        "trial": {"run_number": 2},
    }
    fresh = {
        **record(),
        "code_version": {"commit": "b"},
        "generated_at": "2027-01-01T00:00:00Z",
        "trial": {"run_number": 3},
    }
    assert differences(stored, fresh) == []


@pytest.mark.parametrize(
    ("stored", "fresh", "same"),
    [
        (0.0, 1e-9, True),  # exactly on the boundary: 1e-9 <= 1e-9 * max(1, 0, 1e-9)
        (0.0, 1.0000000001e-9, False),  # one step above it
        (1e-12, 2e-12, True),  # below 1 the tolerance is absolute
        (0.0, 2e-9, False),
        (1.0, 1.0 + 0.9e-9, True),
        (1.0, 1.0 + 1.1e-9, False),
        (1e6, 1e6 + 0.0009, True),  # above 1 it is relative: 1e-9 * 1e6 = 1e-3
        (1e6, 1e6 + 0.0011, False),
        (1e6 + 0.0009, 1e6, True),  # symmetric
        (-1e6, -1e6 - 0.0011, False),
        (-0.5, 0.5, False),
    ],
)
def test_floats_are_equal_within_the_relative_tolerance_with_an_absolute_floor_of_1(
    stored: float, fresh: float, same: bool
) -> None:
    assert equal(stored, fresh) is same


@pytest.mark.parametrize(
    ("stored", "fresh", "same"),
    [
        (1000000000, 1000000000, True),
        (1000000000, 1000000001, False),  # a relative tolerance would pass this; integers are exact
        (0, 1, False),
        (1, 1.0, True),
        (1.0, 1, True),
        (1, 1.0000000001, True),  # an integer against a float is a number against a number
        (2, 2.0000001, False),
    ],
)
def test_integers_are_exact_and_an_integer_against_a_float_is_numeric(stored: Any, fresh: Any, same: bool) -> None:
    assert equal(stored, fresh) is same


@pytest.mark.parametrize(
    ("stored", "fresh"),
    [
        (True, 1),
        (1, True),
        (True, 1.0),
        (1.0, True),
        (False, 0),
        (0, False),
        (False, 0.0),
        (True, False),
        (False, True),
    ],
)
def test_a_bool_never_equals_a_number_and_two_bools_must_match(stored: Any, fresh: Any) -> None:
    assert not equal(stored, fresh)


@pytest.mark.parametrize("value", [True, False])
def test_the_same_bool_is_equal(value: bool) -> None:
    assert equal(value, value)


@pytest.mark.parametrize(
    ("stored", "fresh"), [(None, 0), (0, None), (None, 1.5), (1.5, None), (None, False), (None, "")]
)
def test_none_against_a_value_is_a_difference(stored: Any, fresh: Any) -> None:
    assert [d.kind for d in value_diffs(stored, fresh)] == ["changed"]


def test_none_equals_none() -> None:
    assert equal(None, None)


@pytest.mark.parametrize(
    ("stored", "fresh", "same"), [("a", "a", True), ("a", "A", False), ("1", 1, False), (1, "1", False)]
)
def test_strings_are_exact_and_never_equal_a_number(stored: Any, fresh: Any, same: bool) -> None:
    assert equal(stored, fresh) is same


def test_a_difference_names_the_path_and_both_values() -> None:
    found = value_diffs(1.5, 2.5)
    assert found == [Difference("evaluation.x", 1.5, 2.5, "changed")]


def test_a_key_of_the_stored_record_only_is_missing() -> None:
    found = differences(record(evaluation={"a": 1, "b": 2}), record(evaluation={"a": 1}))
    assert found == [Difference("evaluation.b", 2, MISSING, "missing")]


def test_a_key_of_the_fresh_record_only_is_extra() -> None:
    found = differences(record(evaluation={"a": 1}), record(evaluation={"a": 1, "b": 2}))
    assert found == [Difference("evaluation.b", MISSING, 2, "extra")]


def test_a_missing_key_whose_stored_value_is_none_is_still_missing_not_equal() -> None:
    found = differences(record(evaluation={"a": None}), record(evaluation={}))
    assert found == [Difference("evaluation.a", None, MISSING, "missing")]


def test_a_compared_key_that_one_record_lacks_entirely_is_missing_or_extra() -> None:
    stored = {"spec": {}, "evaluation": {}, "trades": {}}
    fresh = {"spec": {}, "evaluation": {}, "costs": {}}
    assert differences(stored, fresh) == [
        Difference("trades", {}, MISSING, "missing"),
        Difference("costs", MISSING, {}, "extra"),
    ]


def test_lists_are_compared_by_index_and_the_surplus_is_missing_or_extra() -> None:
    assert differences(record(evaluation={"l": [1, 2, 3]}), record(evaluation={"l": [1, 2]})) == [
        Difference("evaluation.l[2]", 3, MISSING, "missing")
    ]
    assert differences(record(evaluation={"l": [1]}), record(evaluation={"l": [1, 9]})) == [
        Difference("evaluation.l[1]", MISSING, 9, "extra")
    ]
    assert differences(record(evaluation={"l": [[1, 2], [3]]}), record(evaluation={"l": [[1, 5], [3]]})) == [
        Difference("evaluation.l[0][1]", 2, 5, "changed")
    ]


@pytest.mark.parametrize(
    ("stored", "fresh"),
    [({"a": 1}, [1]), ([1], {"a": 1}), ({"a": 1}, 1), (1, [1]), ("s", {"a": 1}), ([], None)],
)
def test_a_different_type_is_one_changed_difference_at_that_path(stored: Any, fresh: Any) -> None:
    assert [(d.path, d.kind) for d in value_diffs(stored, fresh)] == [("evaluation.x", "changed")]


def test_the_order_is_the_compared_keys_then_sorted_keys_then_indices_depth_first() -> None:
    stored = record(
        spec={"s": 1},
        evaluation={"b": 1, "a": {"z": 1, "y": [1, 1]}},
        trades={"t": 1},
        costs={"c": 1},
    )
    fresh = record(
        spec={"s": 2},
        evaluation={"b": 2, "a": {"z": 2, "y": [2, 2]}},
        trades={"t": 2},
        costs={"c": 2},
    )
    assert [d.path for d in differences(stored, fresh)] == [
        "spec.s",
        "evaluation.a.y[0]",
        "evaluation.a.y[1]",
        "evaluation.a.z",
        "evaluation.b",
        "trades.t",
        "costs.c",
    ]


def test_the_order_of_the_keys_in_the_dictionaries_does_not_matter() -> None:
    one = record(evaluation={"b": 1, "a": 1})
    other = record(evaluation={"a": 1, "b": 1})
    assert differences(one, other) == []


@pytest.mark.parametrize(
    ("key", "path"),
    [
        ("sharpe_ratio", "evaluation.sharpe_ratio"),
        ("BRK.B", 'evaluation["BRK.B"]'),
        ("a b", 'evaluation["a b"]'),
        ("", 'evaluation[""]'),
        ("ä", 'evaluation["\\u00e4"]'),
        ('q"uote', 'evaluation["q\\"uote"]'),
    ],
)
def test_a_key_that_is_not_plain_is_written_as_a_quoted_index(key: str, path: str) -> None:
    assert [d.path for d in differences(record(evaluation={key: 1}), record(evaluation={key: 2}))] == [path]


def test_a_quoted_key_inside_a_path_continues_with_dots_and_indices() -> None:
    stored = record(evaluation={"positions": {"BRK.B": {"shares": [1]}}})
    fresh = record(evaluation={"positions": {"BRK.B": {"shares": [2]}}})
    assert [d.path for d in differences(stored, fresh)] == ['evaluation.positions["BRK.B"].shares[0]']


def test_the_data_hashes_come_first_and_the_rest_keeps_its_order() -> None:
    stored = record(
        spec={"s": 1},
        evaluation={"benchmark": {"data_hash": "a", "m": 1}, "strategy": {"data_hash": "b", "m": 1}},
    )
    fresh = record(
        spec={"s": 2},
        evaluation={"benchmark": {"data_hash": "c", "m": 2}, "strategy": {"data_hash": "d", "m": 2}},
    )
    found = differences(stored, fresh)
    assert [d.path for d in found] == [
        "spec.s",
        "evaluation.benchmark.data_hash",
        "evaluation.benchmark.m",
        "evaluation.strategy.data_hash",
        "evaluation.strategy.m",
    ]
    assert [d.path for d in prioritized(found)] == [
        "evaluation.benchmark.data_hash",
        "evaluation.strategy.data_hash",
        "spec.s",
        "evaluation.benchmark.m",
        "evaluation.strategy.m",
    ]


def test_a_change_is_data_if_any_hash_differs_else_metrics() -> None:
    hash_diff = Difference("evaluation.strategy.data_hash", "a", "b", "changed")
    metric_diff = Difference("evaluation.strategy.metrics.sharpe", 1.0, 2.0, "changed")
    assert is_data_hash(hash_diff) and not is_data_hash(metric_diff)
    assert change_kind([metric_diff, hash_diff]) == "data"
    assert change_kind([metric_diff]) == "metrics"
    assert change_kind([Difference("spec.name", "a", "b", "changed")]) == "metrics"


NAN, INF = float("nan"), float("inf")


@pytest.mark.parametrize(
    ("stored", "fresh"),
    [
        (NAN, NAN),  # not even to itself
        (NAN, 1.0),
        (1.0, NAN),
        (NAN, 1),
        (NAN, None),
        (INF, INF),
        (-INF, -INF),
        (INF, -INF),
        (INF, 1.0),
        (1.0, INF),
        (INF, 10**300),
        (NAN, INF),
    ],
)
def test_a_non_finite_number_is_equal_to_nothing_not_even_to_itself(stored: Any, fresh: Any) -> None:
    # it cannot occur in a record (canonical JSON refuses it), so it must never be reported as reproduced
    assert [d.kind for d in value_diffs(stored, fresh)] == ["changed"]


def test_none_equals_none_which_is_how_an_undefined_metric_reproduces() -> None:
    assert differences(record(evaluation={"sharpe": None}), record(evaluation={"sharpe": None})) == []


def test_the_keys_of_both_records_are_merged_and_sorted_whoever_has_them() -> None:
    stored = record(evaluation={"b": 1, "d": 1})
    fresh = record(evaluation={"a": 1, "c": 1, "b": 2})
    found = differences(stored, fresh)
    assert [(d.path, d.kind) for d in found] == [
        ("evaluation.a", "extra"),
        ("evaluation.b", "changed"),
        ("evaluation.c", "extra"),
        ("evaluation.d", "missing"),
    ]


def test_keys_are_sorted_by_code_point_so_a_capital_comes_before_a_small_letter() -> None:
    stored = record(evaluation={"a": 1, "B": 1, "Z": 1, "_": 1})
    fresh = record(evaluation={"a": 2, "B": 2, "Z": 2, "_": 2})
    # "B" (66) and "Z" (90) before "_" (95) before "a" (97)
    assert [d.path for d in differences(stored, fresh)] == [
        "evaluation.B",
        "evaluation.Z",
        "evaluation._",
        "evaluation.a",
    ]


@pytest.mark.parametrize(
    "path",
    [
        "spec.params.my_data_hash",
        "spec.data_hash",
        "evaluation.relative.data_hash",
        "evaluation.strategy.data_hash.extra",
        "evaluation.strategy.metrics.data_hash",
        "costs.strategy.data_hash",
    ],
)
def test_only_the_two_data_hashes_of_the_evaluation_are_data_hashes(path: str) -> None:
    assert not is_data_hash(Difference(path, "a", "b", "changed"))


@pytest.mark.parametrize("path", ["evaluation.strategy.data_hash", "evaluation.benchmark.data_hash"])
def test_the_two_data_hash_paths_are_data_hashes(path: str) -> None:
    assert is_data_hash(Difference(path, "a", "b", "changed"))


def test_a_data_hash_named_key_elsewhere_is_an_ordinary_difference_metrics_changed_if_alone() -> None:
    stored = record(spec={"params": {"my_data_hash": "a"}})
    fresh = record(spec={"params": {"my_data_hash": "b"}})
    found = differences(stored, fresh)
    assert [d.path for d in found] == ["spec.params.my_data_hash"]
    assert change_kind(found) == "metrics"
    # and it does not jump the queue in front of the first-listed differences
    both = differences(
        record(spec={"params": {"my_data_hash": "a"}}, evaluation={"strategy": {"data_hash": "x"}}),
        record(spec={"params": {"my_data_hash": "b"}}, evaluation={"strategy": {"data_hash": "y"}}),
    )
    assert [d.path for d in prioritized(both)] == ["evaluation.strategy.data_hash", "spec.params.my_data_hash"]
    assert change_kind(both) == "data"
