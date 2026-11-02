"""The ``signal.coded`` block: parsing without a registry lookup, the id rules, a serializer that changes nothing else.

Expected values are literals written out by hand (docs/coded-signals.md, "The coded block").
"""

from pathlib import Path
from typing import Any

import pytest

from backtest_agent.journal import canonical_json, family_of, variant_hash
from backtest_agent.spec import SIGNALS, Signal, SignalParams, SpecError, StrategySpec, UnknownSignalError, parse_spec
from specs import to_yaml, valid

BRIEF = "Buy a symbol when its 14-day RSI is below entry_below.\nwindow is the RSI length in trading rows."


def coded(signal: dict[str, Any] | None = None) -> dict[str, Any]:
    data = valid()
    data["signal"] = signal or {
        "id": "rsi_pullback",
        "params": {"window": 14, "entry_below": 30.0},
        "coded": {"brief": BRIEF},
    }
    return data


def problems(data: dict[str, Any]) -> dict[str, str]:
    with pytest.raises(SpecError) as info:
        parse_spec(to_yaml(data))
    return {p.path: p.message for p in info.value.problems}


# --- a coded spec parses without any registered signal ---


def test_a_coded_spec_is_valid_before_its_code_exists() -> None:
    assert "rsi_pullback" not in SIGNALS
    spec = parse_spec(to_yaml(coded()))
    assert spec.signal.id == "rsi_pullback"
    assert spec.signal.coded is not None and spec.signal.coded.brief == BRIEF
    assert spec.signal.coded.code_sha256 is None
    assert spec.signal.params == {"window": 14, "entry_below": 30.0}  # no defaults are filled in: no params model yet


def test_the_serialized_signal_of_a_coded_spec_holds_the_brief_and_no_sha_until_there_is_one() -> None:
    assert parse_spec(to_yaml(coded())).to_dict()["signal"] == {
        "coded": {"brief": BRIEF},
        "id": "rsi_pullback",
        "params": {"entry_below": 30.0, "window": 14},
    }
    sha = "ab" * 32
    pinned = coded({"id": "rsi_pullback", "params": {}, "coded": {"brief": "B", "code_sha256": sha}})
    assert parse_spec(to_yaml(pinned)).to_dict()["signal"] == {
        "coded": {"brief": "B", "code_sha256": sha},
        "id": "rsi_pullback",
        "params": {},
    }


def test_a_coded_spec_round_trips_through_its_dict() -> None:
    spec = parse_spec(to_yaml(coded()))
    assert StrategySpec.model_validate(spec.to_dict()) == spec


class RsiParams(SignalParams):
    window: int = 14
    entry_below: float = 30.0

    def warmup_rows(self) -> int:
        return self.window


def test_an_unresolved_coded_spec_never_finds_its_signal_even_if_one_is_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(SIGNALS._signals, "rsi_pullback", Signal("rsi_pullback", RsiParams, lambda p, q: p))
    spec = parse_spec(to_yaml(coded()))
    assert spec.signal.coded is not None and spec.signal.coded.code_sha256 is None
    with pytest.raises(UnknownSignalError, match=r"the coded signal 'rsi_pullback' is not resolved; it has to pass"):
        spec.signal.params_model()
    with pytest.raises(UnknownSignalError, match="is not resolved"):
        spec.warmup_rows  # noqa: B018 - the property raises


def test_with_a_sha_the_registered_signal_is_found_and_without_one_registered_it_is_not_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pinned = coded(
        {"id": "rsi_pullback", "params": {"window": 14}, "coded": {"brief": BRIEF, "code_sha256": "ab" * 32}}
    )
    spec = parse_spec(to_yaml(pinned))
    with pytest.raises(UnknownSignalError, match="is not loaded"):
        spec.signal.params_model()
    monkeypatch.setitem(
        SIGNALS._signals, "rsi_pullback", Signal("rsi_pullback", RsiParams, lambda p, q: p, sha256="ab" * 32)
    )
    assert spec.warmup_rows == 14


def test_an_unknown_id_without_a_coded_block_is_still_an_error() -> None:
    data = coded({"id": "rsi_pullback", "params": {}})
    assert "unknown signal id 'rsi_pullback'" in problems(data)["signal.id"]


def test_coded_null_is_the_same_as_no_coded_block() -> None:
    data = valid()
    data["signal"]["coded"] = None
    spec = parse_spec(to_yaml(data))
    assert spec.signal.coded is None
    assert "coded" not in spec.to_dict()["signal"]


# --- nothing else changes: the serializer leaves other specs byte-identical ---


def test_a_spec_without_coded_serializes_exactly_as_before() -> None:
    spec = parse_spec(to_yaml(valid()))
    assert spec.to_dict()["signal"] == {"id": "sma_crossover", "params": {"fast": 20, "slow": 100}}
    assert list(spec.to_dict()["signal"]) == ["id", "params"]
    assert canonical_json(spec.to_dict()["signal"]) == '{"id":"sma_crossover","params":{"fast":20,"slow":100}}'


@pytest.mark.parametrize("name", ["sma_crossover", "momentum_12_1", "buy_and_hold"])
def test_the_example_specs_have_no_coded_key(name: str) -> None:
    from backtest_agent.spec import load_spec

    spec = load_spec(Path(__file__).resolve().parents[1] / "strategies" / f"{name}.yaml")
    assert "coded" not in spec.to_dict()["signal"]
    assert spec.signal.coded is None


def test_the_family_of_a_coded_spec_is_its_id_and_the_sha_makes_a_new_variant() -> None:
    plain = parse_spec(to_yaml(coded()))
    pinned = parse_spec(
        to_yaml(
            coded(
                {
                    "id": "rsi_pullback",
                    "params": {"window": 14, "entry_below": 30.0},
                    "coded": {"brief": BRIEF, "code_sha256": "cd" * 32},
                }
            )
        )
    )
    other = parse_spec(
        to_yaml(
            coded(
                {
                    "id": "rsi_pullback",
                    "params": {"window": 14, "entry_below": 30.0},
                    "coded": {"brief": BRIEF, "code_sha256": "ef" * 32},
                }
            )
        )
    )
    assert family_of(plain) == family_of(pinned) == family_of(other) == "rsi_pullback"
    assert len({variant_hash(plain), variant_hash(pinned), variant_hash(other)}) == 3


# --- the brief ---


def test_crlf_in_the_brief_becomes_lf_and_nothing_else_is_changed() -> None:
    data = coded({"id": "x_signal", "params": {}, "coded": {"brief": "  a\r\nb\r\n\r\n c  "}})
    assert parse_spec(to_yaml(data)).signal.coded.brief == "  a\nb\n\n c  "  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("brief", "message"),
    [
        ("", "the brief must not be empty"),
        (" \n\t ", "the brief must not be empty"),
        ("x" * 2001, "the brief must have at most 2000 characters, got 2001"),
        ("   ", "the brief must not be empty"),  # only Unicode spaces (category Zs) is empty too
    ],
)
def test_bad_briefs_are_refused(brief: str, message: str) -> None:
    data = coded({"id": "x_signal", "params": {}, "coded": {"brief": brief}})
    assert message in problems(data)["signal.coded.brief"]


FORBIDDEN_MESSAGE = (
    "the brief must not contain control, format or line-separator characters "
    "(Unicode categories Cc, Cf, Zl, Zp; a line break and a tab are allowed)"
)


@pytest.mark.parametrize(
    "character",
    [
        "\x00",
        "\x07",
        "\x1b",
        "\x7f",
        "\x85",
        "\r",
        "\u200b",
        "\u200e",
        "\u202e",
        "\u2066",
        "\ufeff",
        "\u2028",
        "\u2029",
    ],
    ids=lambda c: f"U+{ord(c):04X}",
)
def test_characters_of_the_categories_cc_cf_zl_zp_are_refused_in_a_brief(character: str) -> None:
    # "\r" here is a lone CR: the CR of a CRLF is removed by the normalisation first.
    data = coded({"id": "x_signal", "params": {}, "coded": {"brief": f"ab{character}cd"}})
    assert problems(data) == {"signal.coded.brief": FORBIDDEN_MESSAGE}


def test_other_unicode_is_fine_in_a_brief() -> None:
    brief = "café über 中文 αβ\ttab\nline  nbsp  em space"
    spec = parse_spec(to_yaml(coded({"id": "x_signal", "params": {}, "coded": {"brief": brief}})))
    assert spec.signal.coded.brief == brief  # type: ignore[union-attr]


def test_the_limit_of_2000_characters_counts_after_crlf_becomes_lf() -> None:
    inside = "x" * 1999 + "\r\n"  # 2001 characters as written, 2000 after the normalisation
    spec = parse_spec(to_yaml(coded({"id": "x_signal", "params": {}, "coded": {"brief": inside}})))
    assert len(spec.signal.coded.brief) == 2000  # type: ignore[union-attr]
    outside = "x" * 2000 + "\r\n"  # 2002 as written, 2001 after
    data = coded({"id": "x_signal", "params": {}, "coded": {"brief": outside}})
    assert problems(data) == {"signal.coded.brief": "the brief must have at most 2000 characters, got 2001"}
    many = "\r\n" * 1000  # 2000 as written, 1000 after, and not empty
    assert parse_spec(to_yaml(coded({"id": "x_signal", "params": {}, "coded": {"brief": many + "x"}})))


def test_an_invalid_coded_block_gives_one_error_and_no_second_one_about_the_id() -> None:
    # The id is not registered, but the coded block is the problem, so only the brief is reported.
    data = coded({"id": "not_registered_anywhere", "params": {"w": 1}, "coded": {"brief": "  "}})
    assert problems(data) == {"signal.coded.brief": "the brief must not be empty"}
    data = coded({"id": "not_registered_anywhere", "params": {1: 2}, "coded": {"brief": "ok"}})
    assert list(problems(data)) == ["signal.params[1].[key]"]  # the key of the params is the only error


def test_a_brief_of_exactly_2000_characters_and_with_tabs_and_newlines_is_valid() -> None:
    brief = "a\tb\n" + "x" * 1996
    assert len(brief) == 2000
    assert (
        parse_spec(to_yaml(coded({"id": "x_signal", "params": {}, "coded": {"brief": brief}}))).signal.coded.brief
        == brief
    )  # type: ignore[union-attr]


# --- the id ---


@pytest.mark.parametrize(
    ("signal_id", "message"),
    [
        ("RSI", "must be lowercase letters, digits and underscores starting with a letter, got 'RSI'"),
        ("1rsi", "starting with a letter, got '1rsi'"),
        ("rsi-x", "got 'rsi-x'"),
        ("rsi/x", "got 'rsi/x'"),
        ("..", "got '..'"),
        ("a" * 65, "at most 64 characters, got 65"),
        ("sma_crossover", "'sma_crossover' is the id of a built-in signal"),
        ("momentum_12_1", "'momentum_12_1' is the id of a built-in signal"),
        ("buy_and_hold", "'buy_and_hold' is the id of a built-in signal"),
    ],
)
def test_bad_ids_of_a_coded_signal_are_refused(signal_id: str, message: str) -> None:
    data = coded({"id": signal_id, "params": {}, "coded": {"brief": "B"}})
    assert message in problems(data)["signal.id"]


def test_an_id_of_exactly_64_characters_is_valid() -> None:
    assert parse_spec(to_yaml(coded({"id": "a" * 64, "params": {}, "coded": {"brief": "B"}}))).signal.id == "a" * 64


# --- params and the sha ---


@pytest.mark.parametrize(
    ("params", "fragment"),
    [
        ({"w": None}, "the parameter 'w' of a coded signal must be a number, text"),
        ({"w": {"a": 1}}, "the parameter 'w' of a coded signal must be"),
        ({"w": [1, [2]]}, "the parameter 'w' of a coded signal must be"),
        ({"w": float("nan")}, "the parameter 'w' of a coded signal must be"),
        ({"w": float("inf")}, "the parameter 'w' of a coded signal must be"),
    ],
)
def test_params_of_a_coded_signal_must_be_scalars_or_lists_of_scalars(params: dict[str, Any], fragment: str) -> None:
    data = coded({"id": "x_signal", "params": params, "coded": {"brief": "B"}})
    assert fragment in problems(data)["signal.params"]


def test_scalar_params_and_lists_are_accepted() -> None:
    params = {"a": 1, "b": 2.5, "c": "text", "d": True, "e": [1, 2.5, "x", False], "f": []}
    assert (
        parse_spec(to_yaml(coded({"id": "x_signal", "params": params, "coded": {"brief": "B"}}))).signal.params
        == params
    )


@pytest.mark.parametrize("sha", ["AB" * 32, "ab" * 31 + "a", "ab" * 33, "xy" * 32, ""])
def test_a_malformed_sha_is_refused(sha: str) -> None:
    data = coded({"id": "x_signal", "params": {}, "coded": {"brief": "B", "code_sha256": sha}})
    assert "code_sha256 must be 64 lowercase hex characters" in problems(data)["signal.coded.code_sha256"]


def test_unknown_fields_of_the_coded_block_are_refused() -> None:
    data = coded({"id": "x_signal", "params": {}, "coded": {"brief": "B", "file": "x.py"}})
    assert "unknown field 'file'" in problems(data)["signal.coded.file"]


def test_the_brief_is_required() -> None:
    data = coded({"id": "x_signal", "params": {}, "coded": {}})
    assert problems(data)["signal.coded.brief"] == "missing required field"


def test_the_reserved_builtin_ids_are_exactly_the_registered_built_ins() -> None:
    from backtest_agent.spec import list_signals
    from backtest_agent.spec.coded_spec import BUILTIN_SIGNAL_IDS

    assert BUILTIN_SIGNAL_IDS == {"sma_crossover", "momentum_12_1", "buy_and_hold"} == set(list_signals())


DEVICE_NAMES = ["con", "prn", "aux", "nul"] + [f"com{n}" for n in range(1, 10)] + [f"lpt{n}" for n in range(1, 10)]


def test_there_are_22_reserved_device_names() -> None:
    assert len(DEVICE_NAMES) == len(set(DEVICE_NAMES)) == 22


@pytest.mark.parametrize("name", DEVICE_NAMES)
def test_every_windows_device_name_is_refused_as_an_id(name: str) -> None:
    data = coded({"id": name, "params": {}, "coded": {"brief": "B"}})
    assert problems(data) == {"signal.id": f"{name!r} is a reserved file name on Windows; choose another id"}


@pytest.mark.parametrize("name", ["console", "com10", "lpt0", "com0", "aux1", "nul_", "my_con", "prn2"])
def test_names_that_only_look_like_device_names_are_fine(name: str) -> None:
    assert parse_spec(to_yaml(coded({"id": name, "params": {}, "coded": {"brief": "B"}}))).signal.id == name


def test_the_check_of_the_param_names_does_not_rely_on_the_model() -> None:
    from backtest_agent.spec.coded_spec import check_scalar_params

    with pytest.raises(ValueError, match="the parameter names of a coded signal must be text, got 1"):
        check_scalar_params({1: "a"})  # type: ignore[dict-item]
