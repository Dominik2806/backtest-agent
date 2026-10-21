from pathlib import Path
from typing import Any

import pytest

from backtest_agent.spec import SpecError, SpecProblem, load_spec, parse_spec
from specs import to_yaml, valid


def problems_of(source: dict[str, Any] | str) -> dict[str, str]:
    """Parse a spec that must be invalid and return its problems as {path: message}."""
    text = to_yaml(source) if isinstance(source, dict) else source
    with pytest.raises(SpecError) as info:
        parse_spec(text)
    found = {p.path: p.message for p in info.value.problems}
    assert len(found) == len(info.value.problems), "a path was reported twice"
    return found


def mutated(**changes: Any) -> dict[str, Any]:
    """The valid spec with top-level fields replaced; a value of ... removes the field."""
    data = valid()
    for key, value in changes.items():
        if value is ...:
            del data[key]
        else:
            data[key] = value
    return data


def with_execution(**changes: Any) -> dict[str, Any]:
    data = valid()
    data["execution"] = {**data["execution"], **changes}
    return data


def with_params(params: dict[str, Any]) -> dict[str, Any]:
    data = valid()
    data["signal"] = {"id": "sma_crossover", "params": params}
    return data


# --- typos and unknown fields ---


def test_typo_in_a_nested_field_name_suggests_the_right_one() -> None:
    data = valid()
    data["execution"] = {"dely_bars": 1}
    assert problems_of(data) == {"execution.dely_bars": "unknown field 'dely_bars'; did you mean 'delay_bars'?"}


def test_typo_in_a_top_level_field_name_also_reports_the_missing_field() -> None:
    data = valid()
    data["univers"] = data.pop("universe")
    found = problems_of(data)
    assert found["univers"] == "unknown field 'univers'; did you mean 'universe'?"
    assert found["universe"] == "missing required field"


def test_unknown_field_without_a_close_match_lists_the_allowed_fields() -> None:
    data = valid()
    data["costs"]["fees"] = 1
    message = problems_of(data)["costs.fees"]
    assert message.startswith("unknown field 'fees'; allowed fields: ")
    assert "commission_bps" in message


def test_unknown_signal_param_suggests_the_right_one() -> None:
    assert problems_of(with_params({"fats": 5})) == {"signal.params.fats": "unknown field 'fats'; did you mean 'fast'?"}


# --- execution rules ---


def test_negative_delay_is_rejected() -> None:
    found = problems_of(with_execution(delay_bars=-1))
    assert list(found) == ["execution.delay_bars"]
    assert "greater than or equal to 0" in found["execution.delay_bars"]
    assert "(got -1)" in found["execution.delay_bars"]


def test_delay_zero_needs_the_explicit_flag() -> None:
    found = problems_of(with_execution(delay_bars=0, price="close"))
    assert list(found) == ["execution.delay_bars"]
    assert "allow_same_bar_execution: true" in found["execution.delay_bars"]


def test_delay_zero_with_open_price_is_always_rejected_even_with_the_flag() -> None:
    found = problems_of(with_execution(delay_bars=0, price="open", allow_same_bar_execution=True))
    assert list(found) == ["execution.price"]
    assert "impossible" in found["execution.price"]


def test_delay_zero_open_without_flag_reports_both_problems() -> None:
    found = problems_of(with_execution(delay_bars=0, price="open", allow_same_bar_execution=False))
    assert set(found) == {"execution.delay_bars", "execution.price"}


def test_the_opt_in_flag_with_a_delay_is_contradictory() -> None:
    found = problems_of(with_execution(delay_bars=1, allow_same_bar_execution=True))
    assert list(found) == ["execution.allow_same_bar_execution"]
    assert "only applies when delay_bars is 0" in found["execution.allow_same_bar_execution"]


def test_execution_types_are_strict() -> None:
    for field, value in (("delay_bars", True), ("delay_bars", "1"), ("delay_bars", 1.5), ("price", "next_open")):
        found = problems_of(with_execution(**{field: value}))
        assert list(found) == [f"execution.{field}"], (field, value)
    assert f"(got '{'next_open'}')" in problems_of(with_execution(price="next_open"))["execution.price"]
    assert "execution.allow_same_bar_execution" in problems_of(with_execution(allow_same_bar_execution="yes"))


# --- period and universe ---


def test_end_before_start() -> None:
    data = valid()
    data["period"] = {"start": "2020-01-02", "end": "2020-01-01"}
    found = problems_of(data)
    assert list(found) == ["period.end"]
    assert "must be on or after start" in found["period.end"]


def test_start_equal_to_end_is_allowed() -> None:
    data = valid()
    data["period"] = {"start": "2020-01-02", "end": "2020-01-02"}
    parse_spec(to_yaml(data))


@pytest.mark.parametrize("value", ["2020/01/01", "20200101", 20200101, "2020-02-30", "2020-01-01 10:00:00", "today"])
def test_bad_dates(value: Any) -> None:
    data = valid()
    data["period"]["start"] = value
    assert list(problems_of(data)) == ["period.start"]


def test_empty_universe() -> None:
    assert "at least one symbol" in problems_of(mutated(universe=[]))["universe"]


def test_duplicate_universe_symbols_also_by_case() -> None:
    found = problems_of(mutated(universe=["SPY", "QQQ", "spy"]))
    assert list(found) == ["universe"]
    assert "duplicate symbols" in found["universe"] and "spy" in found["universe"]


def test_bad_symbol_names_the_list_item() -> None:
    found = problems_of(mutated(universe=["SPY", "Q Q", ""]))
    assert set(found) == {"universe[1]", "universe[2]"}
    assert "whitespace" in found["universe[1]"]
    assert list(problems_of(mutated(universe="SPY"))) == ["universe"]


# --- signal ---


def test_unknown_signal_id_lists_the_available_ids() -> None:
    data = valid()
    data["signal"] = {"id": "sma_crosover", "params": {"fast": "not checked"}}
    found = problems_of(data)
    assert list(found) == ["signal.id"]  # the params of an unknown signal cannot be checked
    assert "unknown signal id 'sma_crosover'" in found["signal.id"]
    assert "buy_and_hold, momentum_12_1, sma_crossover" in found["signal.id"]


def test_wrong_param_type() -> None:
    found = problems_of(with_params({"fast": "ten"}))
    assert list(found) == ["signal.params.fast"]
    assert "valid integer" in found["signal.params.fast"] and "(got 'ten')" in found["signal.params.fast"]
    assert list(problems_of(with_params({"fast": "10"}))) == ["signal.params.fast"]  # strict: no str as int
    assert list(problems_of(with_params({"fast": True}))) == ["signal.params.fast"]


def test_fast_must_be_smaller_than_slow() -> None:
    found = problems_of(with_params({"fast": 50, "slow": 20}))
    assert list(found) == ["signal.params.slow"]
    assert "slow must be larger than fast (fast=50, slow=20)" in found["signal.params.slow"]


def test_param_range_error_names_the_field() -> None:
    assert list(problems_of(with_params({"fast": 0}))) == ["signal.params.fast"]


def test_params_must_be_a_mapping_and_the_signal_a_block() -> None:
    assert list(problems_of(mutated(signal={"id": "sma_crossover", "params": [1, 2]}))) == ["signal.params"]
    assert "block of fields" in problems_of(mutated(signal="sma_crossover"))["signal"]


def test_momentum_params_rules() -> None:
    data = valid()
    data["signal"] = {"id": "momentum_12_1", "params": {"lookback_days": 10, "skip_days": 10, "top_n": 0}}
    assert set(problems_of(data)) == {"signal.params.skip_days", "signal.params.top_n"}


# --- required fields ---


@pytest.mark.parametrize(
    "key",
    [
        "schema_version",
        "name",
        "universe",
        "period",
        "signal",
        "sizing",
        "rebalance",
        "costs",
        "benchmark",
        "initial_capital",
    ],
)
def test_every_required_field_is_reported_when_missing(key: str) -> None:
    found = problems_of(mutated(**{key: ...}))
    assert key in found
    assert len(found) == 1


def test_missing_costs_block_has_a_helpful_message() -> None:
    message = problems_of(mutated(costs=...))["costs"]
    assert "commission_bps, spread_bps and slippage_bps" in message and "zeros are allowed" in message


def test_every_cost_component_is_required() -> None:
    data = valid()
    del data["costs"]["spread_bps"]
    assert problems_of(data) == {"costs.spread_bps": "missing required field"}


def test_costs_must_be_finite_and_not_negative() -> None:
    for bad in (-1, "1", True):
        data = valid()
        data["costs"]["commission_bps"] = bad
        assert list(problems_of(data)) == ["costs.commission_bps"], bad
    text = to_yaml(valid()).replace("commission_bps: 1.0", "commission_bps: .nan")
    assert "finite" in problems_of(text)["costs.commission_bps"]


def test_missing_fields_inside_optional_blocks_are_not_a_problem() -> None:
    data = valid()
    data["execution"] = {}
    data["data"] = {}
    parse_spec(to_yaml(data))


def test_optional_blocks_must_not_be_null() -> None:
    assert "block of fields" in problems_of(mutated(execution=None))["execution"]


def test_schema_version() -> None:
    assert "unsupported schema_version 2" in problems_of(mutated(schema_version=2))["schema_version"]
    assert list(problems_of(mutated(schema_version="1"))) == ["schema_version"]
    assert list(problems_of(mutated(schema_version=True))) == ["schema_version"]


def test_other_enums_and_scalars() -> None:
    assert "(got 'yearly')" in problems_of(mutated(rebalance="yearly"))["rebalance"]
    data = valid()
    data["data"] = {"provider": "polygon"}
    assert list(problems_of(data)) == ["data.provider"]
    assert list(problems_of(mutated(initial_capital=0))) == ["initial_capital"]
    assert list(problems_of(mutated(initial_capital="100000"))) == ["initial_capital"]
    assert list(problems_of(mutated(name=123))) == ["name"]
    assert list(problems_of(mutated(name="two\nlines"))) == ["name"]
    assert list(problems_of(mutated(name=""))) == ["name"]
    assert list(problems_of(mutated(benchmark=""))) == ["benchmark"]


def test_sizing_rules() -> None:
    def sizing(**fields: Any) -> dict[str, str]:
        return problems_of(mutated(sizing=fields))

    assert sizing(method="fixed_fraction") == {"sizing.fraction": "required for method fixed_fraction"}
    assert "not allowed for method equal_weight" in sizing(method="equal_weight", fraction=0.5)["sizing.fraction"]
    assert list(sizing(method="fixed_fraction", fraction=1.5)) == ["sizing.fraction"]
    assert list(sizing(method="fixed_fraction", fraction=0)) == ["sizing.fraction"]
    assert list(sizing(method="kelly")) == ["sizing.method"]
    assert list(sizing()) == ["sizing.method"]


# --- YAML level ---


def test_duplicate_yaml_key_is_rejected_with_its_lines() -> None:
    text = to_yaml(valid()) + "name: again\n"
    found = problems_of(text)
    assert list(found) == ["name"]
    assert "duplicate key 'name' (lines 2 and " in found["name"]


def test_duplicate_key_in_a_nested_block_names_the_path() -> None:
    text = to_yaml(valid()).replace("  delay_bars: 1\n", "  delay_bars: 1\n  delay_bars: 2\n")
    found = problems_of(text)
    assert list(found) == ["execution.delay_bars"]
    assert "duplicate key 'delay_bars'" in found["execution.delay_bars"]


def test_every_duplicate_key_is_listed() -> None:
    text = to_yaml(valid()) + "name: a\nbenchmark: b\n"
    assert set(problems_of(text)) == {"name", "benchmark"}


def test_a_yaml_list_instead_of_a_mapping() -> None:
    assert problems_of("- a\n- b\n") == {"(root)": "the spec must be a mapping of fields, got a list"}
    assert problems_of("just text") == {"(root)": "the spec must be a mapping of fields, got text"}
    assert problems_of("42") == {"(root)": "the spec must be a mapping of fields, got a number"}


def test_empty_documents() -> None:
    assert problems_of("") == {"(root)": "the document is empty"}
    assert problems_of("# only a comment\n") == {"(root)": "the document is empty"}


def test_yaml_syntax_error_reports_the_line() -> None:
    found = problems_of("name: x\nuniverse: [SPY, QQQ\nperiod: {}")
    assert list(found) == ["(yaml)"]
    assert "YAML syntax error at line" in found["(yaml)"]


def test_multiple_documents_are_rejected() -> None:
    assert list(problems_of("a: 1\n---\nb: 2\n")) == ["(yaml)"]


def test_yaml_cannot_construct_python_objects() -> None:
    assert list(problems_of("name: !!python/object/apply:os.system ['echo hacked']\n")) == ["(yaml)"]


def test_several_problems_are_all_listed() -> None:
    data = valid()
    data["execution"] = {"delay_bars": -1}
    data["period"] = {"start": "2020-01-02", "end": "2020-01-01"}
    data["universe"] = []
    del data["costs"]
    data["extra"] = 1
    found = problems_of(data)
    assert set(found) == {"execution.delay_bars", "period.end", "universe", "costs", "extra"}


# --- the error object and files ---


def test_spec_error_message_lists_every_problem_with_its_path() -> None:
    with pytest.raises(SpecError) as info:
        parse_spec(to_yaml(mutated(universe=[], rebalance="yearly")))
    error = info.value
    assert all(isinstance(p, SpecProblem) for p in error.problems)
    lines = str(error).splitlines()
    assert lines[0] == "Invalid strategy spec (2 problems):"
    assert lines[1].startswith("  - universe: ")
    assert lines[2].startswith("  - rebalance: ")
    assert "pydantic" not in str(error).lower() and "Traceback" not in str(error)


def test_a_single_problem_is_not_pluralized() -> None:
    with pytest.raises(SpecError, match=r"\(1 problem\):"):
        parse_spec(to_yaml(mutated(rebalance="yearly")))


def test_load_spec_reads_a_file_and_names_it_in_errors(tmp_path: Path) -> None:
    good = tmp_path / "good.yaml"
    good.write_text(to_yaml(valid()), encoding="utf-8")
    assert load_spec(good).name == "SMA test"
    assert load_spec(str(good)).name == "SMA test"

    bom = tmp_path / "bom.yaml"
    bom.write_text(to_yaml(valid()), encoding="utf-8-sig")
    assert load_spec(bom).name == "SMA test"

    bad = tmp_path / "bad.yaml"
    bad.write_text(to_yaml(mutated(rebalance="yearly")), encoding="utf-8")
    with pytest.raises(SpecError) as info:
        load_spec(bad)
    assert info.value.source == str(bad)
    assert str(bad) in str(info.value)


def test_unreadable_files_are_spec_errors(tmp_path: Path) -> None:
    with pytest.raises(SpecError) as info:
        load_spec(tmp_path / "missing.yaml")
    assert [p.path for p in info.value.problems] == ["(file)"]
    assert "cannot read" in info.value.problems[0].message
    binary = tmp_path / "binary.yaml"
    binary.write_bytes(b"\xff\xfe\x00\x01\x80")
    with pytest.raises(SpecError):
        load_spec(binary)
    with pytest.raises(SpecError):
        load_spec(tmp_path)  # a directory
