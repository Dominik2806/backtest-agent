"""A registered signal carries the hash of the code it was loaded from; a spec that pins a hash needs that same hash.

(ADR 0018, "The registered signal carries the hash it was loaded from"). Nothing here executes a coded signal: the
signals are fixtures registered by the test, marked the way the loader will mark them.
"""

import pandas as pd
import pytest

from backtest_agent.data import FakeProvider
from backtest_agent.engine import run_backtest, warmup_window
from backtest_agent.spec import (
    SIGNALS,
    Signal,
    SignalParams,
    SignalRegistry,
    StrategySpec,
    UnknownSignalError,
    get_signal,
    list_signals,
)
from backtest_agent.spec.signals import per_symbol_signal
from runner_helpers import make_spec

SHA_A = "aa" * 32
SHA_B = "bb" * 32
BRIEF = "Holds nothing. Needs no history."


@pytest.fixture(autouse=True)
def registry_is_restored():
    before = SIGNALS.snapshot()
    yield
    SIGNALS.restore(before)


def zeros(prices: pd.DataFrame, params: SignalParams) -> pd.DataFrame:
    """A signal that never holds anything."""
    return per_symbol_signal(prices, lambda close: close * 0.0)


def put(sha: str | None, signal_id: str = "x_signal") -> None:
    """Register a fixture under the id the way the loader will: through the decorator, then marked with the hash."""
    if signal_id in SIGNALS:
        SIGNALS.unregister(signal_id)
    SIGNALS.register(signal_id, params=SignalParams)(zeros)
    if sha is not None:
        SIGNALS.set_sha256(signal_id, sha)


def coded_spec(pin: str | None, signal_id: str = "x_signal") -> StrategySpec:
    """A valid spec for the fake provider with the coded signal ``signal_id``, pinned to ``pin`` if that is given."""
    data = make_spec(signal="buy_and_hold", params={}).to_dict()
    coded = {"brief": BRIEF} | ({} if pin is None else {"code_sha256": pin})
    data["signal"] = {"id": signal_id, "params": {}, "coded": coded}
    return StrategySpec.model_validate(data)


# --- the field ---


def test_a_signal_has_no_hash_unless_it_is_given_one() -> None:
    assert Signal("s", SignalParams, zeros).sha256 is None
    assert Signal("s", SignalParams, zeros, "doc", SHA_A).sha256 == SHA_A


@pytest.mark.parametrize("bad", ["", "AA" * 32, "aa" * 31, "aa" * 33, "xy" * 32, " " + "aa" * 31 + "a"])
def test_a_malformed_hash_is_refused(bad: str) -> None:
    with pytest.raises(ValueError, match="sha256 must be 64 lowercase hex characters"):
        Signal("s", SignalParams, zeros, sha256=bad)


def test_the_built_in_signals_have_no_hash() -> None:
    assert list_signals() == ("buy_and_hold", "momentum_12_1", "sma_crossover")
    assert [get_signal(signal_id).sha256 for signal_id in list_signals()] == [None, None, None]


# --- the registry helpers ---


def private_registry() -> SignalRegistry:
    registry = SignalRegistry()
    registry.register("one", params=SignalParams)(zeros)
    registry.register("two", params=SignalParams)(zeros)
    return registry


def test_a_snapshot_is_a_copy_and_restore_brings_back_exactly_that_content() -> None:
    registry = private_registry()
    snapshot = registry.snapshot()
    assert sorted(snapshot) == ["one", "two"]
    registry.unregister("one")
    registry.register("three", params=SignalParams)(zeros)
    registry.set_sha256("two", SHA_A)
    assert registry.ids() == ("three", "two")
    assert sorted(snapshot) == ["one", "two"]  # the snapshot did not change with the registry
    registry.restore(snapshot)
    assert registry.ids() == ("one", "two")
    assert registry.get("two").sha256 is None  # the marked entry is the old one again
    snapshot.clear()  # changing the snapshot afterwards does not touch the registry
    assert registry.ids() == ("one", "two")


def test_unregister_returns_the_signal_and_refuses_an_unknown_id() -> None:
    registry = private_registry()
    removed = registry.unregister("one")
    assert removed.id == "one" and "one" not in registry
    with pytest.raises(UnknownSignalError, match="cannot unregister 'one': it is not registered"):
        registry.unregister("one")


def test_set_sha256_marks_the_entry_and_returns_it() -> None:
    registry = private_registry()
    marked = registry.set_sha256("one", SHA_A)
    assert marked.sha256 == SHA_A and registry.get("one") is marked
    assert registry.get("two").sha256 is None
    assert registry.get("one").function is zeros  # nothing else about the entry changed
    with pytest.raises(UnknownSignalError, match="unknown signal id 'nope'"):
        registry.set_sha256("nope", SHA_A)
    with pytest.raises(ValueError, match="sha256 must be 64 lowercase hex characters"):
        registry.set_sha256("one", "xyz")
    assert registry.get("one").sha256 == SHA_A  # a refused hash changed nothing


def test_the_registry_of_the_engine_is_restored_after_each_test_of_this_file() -> None:
    assert "x_signal" not in SIGNALS  # the fixture of an earlier test is gone


# --- a spec that pins a hash needs a signal with that hash ---


def test_the_signal_with_the_pinned_hash_is_found() -> None:
    put(SHA_A)
    spec = coded_spec(SHA_A)
    assert spec.warmup_rows == 0
    assert spec.signal.params_model() == SignalParams()


def test_two_hashes_for_the_same_id_the_spec_gets_only_its_own() -> None:
    spec_a, spec_b = coded_spec(SHA_A), coded_spec(SHA_B)
    put(SHA_A)
    assert spec_a.warmup_rows == 0
    with pytest.raises(UnknownSignalError) as info:
        spec_b.warmup_rows  # noqa: B018 - the property raises
    assert str(info.value) == (
        "the coded signal 'x_signal' is not loaded: the registered signal has sha aaaaaaaa, the spec pins sha bbbbbbbb"
    )
    put(SHA_B)  # another version replaces it
    assert spec_b.warmup_rows == 0
    with pytest.raises(UnknownSignalError) as info:
        spec_a.signal.params_model()
    assert str(info.value) == (
        "the coded signal 'x_signal' is not loaded: the registered signal has sha bbbbbbbb, the spec pins sha aaaaaaaa"
    )


def test_a_fixture_without_a_hash_is_not_the_coded_signal() -> None:
    put(None)
    with pytest.raises(UnknownSignalError) as info:
        coded_spec(SHA_A).warmup_rows  # noqa: B018
    assert str(info.value) == (
        "the coded signal 'x_signal' is not loaded: the registered signal has no sha (it was not loaded by the gate), "
        "the spec pins sha aaaaaaaa"
    )


def test_a_built_in_under_the_id_is_not_the_coded_signal_either() -> None:
    # A coded spec cannot name a built-in id (the parser refuses it); build one around that rule to see the lookup.
    spec = coded_spec(SHA_A)
    forged = spec.model_copy(update={"signal": spec.signal.model_copy(update={"id": "buy_and_hold"})})
    assert forged.signal.coded is not None and forged.signal.id == "buy_and_hold"
    with pytest.raises(UnknownSignalError, match="the registered signal has no sha .it was not loaded by the gate."):
        forged.warmup_rows  # noqa: B018


def test_nothing_registered_is_not_loaded() -> None:
    with pytest.raises(UnknownSignalError) as info:
        coded_spec(SHA_A).warmup_rows  # noqa: B018
    assert str(info.value) == "the coded signal 'x_signal' is not loaded; it has to pass the approval gate first"


def test_a_spec_without_a_pin_never_finds_it_even_with_a_marked_signal() -> None:
    put(SHA_A)
    with pytest.raises(UnknownSignalError) as info:
        coded_spec(None).warmup_rows  # noqa: B018
    assert str(info.value) == "the coded signal 'x_signal' is not resolved; it has to pass the approval gate first"


def test_a_spec_without_the_coded_block_is_not_affected_by_the_field() -> None:
    spec = make_spec()  # sma_crossover with short windows, a built-in without a hash
    assert spec.warmup_rows == 19
    assert spec.signal.params_model().warmup_rows() == 19


# --- the engine asks for the warm-up before it asks for the signal ---


def test_the_engine_refuses_a_spec_whose_hash_is_not_the_loaded_one_before_it_loads_any_data() -> None:
    provider = FakeProvider(symbols=("AAA", "BBB"))
    spec_a, spec_b = coded_spec(SHA_A), coded_spec(SHA_B)

    put(SHA_A)
    result = run_backtest(spec_a, provider)
    assert len(result.equity) > 0 and len(provider.calls) == 1

    with pytest.raises(UnknownSignalError, match="the registered signal has sha aaaaaaaa, the spec pins sha bbbbbbbb"):
        run_backtest(spec_b, provider)
    assert len(provider.calls) == 1  # no data was requested for the refused run

    put(SHA_B)
    with pytest.raises(UnknownSignalError, match="the registered signal has sha bbbbbbbb, the spec pins sha aaaaaaaa"):
        run_backtest(spec_a, provider)
    assert len(provider.calls) == 1
    assert len(run_backtest(spec_b, provider).equity) > 0 and len(provider.calls) == 2


def test_the_window_of_a_spec_needs_the_loaded_hash_too() -> None:
    put(SHA_A)
    assert warmup_window(coded_spec(SHA_A)).required_rows == 0
    with pytest.raises(UnknownSignalError, match="the spec pins sha bbbbbbbb"):
        warmup_window(coded_spec(SHA_B))


def test_the_engine_refuses_a_fixture_without_a_hash_and_an_unresolved_spec() -> None:
    provider = FakeProvider(symbols=("AAA", "BBB"))
    put(None)
    with pytest.raises(UnknownSignalError, match="has no sha"):
        run_backtest(coded_spec(SHA_A), provider)
    put(SHA_A)
    with pytest.raises(UnknownSignalError, match="is not resolved"):
        run_backtest(coded_spec(None), provider)
    assert provider.calls == []


# --- one place where a spec finds its signal ---


def test_resolve_signal_gives_the_registered_signal_of_a_plain_spec_and_of_a_loaded_coded_spec() -> None:
    assert make_spec().signal.resolve_signal() is get_signal("sma_crossover")
    put(SHA_A)
    assert coded_spec(SHA_A).signal.resolve_signal() is get_signal("x_signal")


def test_resolve_signal_refuses_what_params_model_refuses_with_the_same_message() -> None:
    cases = [
        (coded_spec(SHA_A), None),  # nothing registered
        (coded_spec(None), SHA_A),  # not resolved
        (coded_spec(SHA_B), SHA_A),  # another version
        (coded_spec(SHA_A), "no sha"),  # a fixture
    ]
    for spec, registered in cases:
        if registered == "no sha":
            put(None)
        elif registered is not None:
            put(registered)
        else:
            SIGNALS.restore({k: v for k, v in SIGNALS.snapshot().items() if k != "x_signal"})
        with pytest.raises(UnknownSignalError) as from_resolve:
            spec.signal.resolve_signal()
        with pytest.raises(UnknownSignalError) as from_params:
            spec.signal.params_model()
        assert str(from_resolve.value) == str(from_params.value)


def test_the_runner_asks_for_the_signal_itself_so_a_wrongly_marked_one_cannot_run_even_without_the_warm_up_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backtest_agent.engine import history

    provider = FakeProvider(symbols=("AAA", "BBB"))
    spec_a = coded_spec(SHA_A)
    put(SHA_A)
    window = warmup_window(spec_a)  # computed while the right version is loaded
    put(SHA_B)  # another version is loaded now; the spec still pins version A
    # Bypass the pin check of warmup_window (it reads spec.warmup_rows): the runner must still refuse on its own.
    monkeypatch.setattr(history, "warmup_window", lambda spec: window)
    with pytest.raises(UnknownSignalError, match="the registered signal has sha bbbbbbbb, the spec pins sha aaaaaaaa"):
        run_backtest(spec_a, provider)
    assert len(provider.calls) == 1  # the data was loaded: only the runner's own lookup refused
