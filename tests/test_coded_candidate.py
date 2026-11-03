"""``load_candidate``: executing a candidate that nobody approved, for ``bt signal check`` only (ADR 0018, addendum).

The hashes are literals taken with ``hashlib`` outside the project (``good_source("x_signal")`` with the factors 0.0 and
0.5). Whatever happens, the registry is what it was; nothing is written; no module of the candidate stays behind (the
autouse fixture of ``coded_helpers`` checks ``sys.modules`` and restores the registry after every test).
"""

import pytest

from backtest_agent.coded import loader
from backtest_agent.coded.errors import GateError, StaticCheckError
from backtest_agent.coded.loader import load_candidate
from backtest_agent.spec import SIGNALS, SpecError
from coded_helpers import (
    World,
    canary_source,
    coded_spec,
    good_source,
    registry_and_modules_are_restored,  # noqa: F401 - autouse fixture
    with_id,
)
from runner_helpers import make_spec

SHA_ZERO = "382c5d1b2f9cbeebb6aa13a34c6ec93636b256e5e35ee103b2d73358071cb122"  # good_source("x_signal"), LF
SHA_HALF = "81d30b983518137333e6868e5db31497951cbb1709bb10464544f0dcc7bb2d77"  # good_source("x_signal", "0.5")


def test_a_good_candidate_is_registered_and_marked_inside_the_block_and_gone_after_it() -> None:
    before = SIGNALS.snapshot()
    with load_candidate(coded_spec(), good_source()) as candidate:
        assert candidate.sha256 == SHA_ZERO
        assert candidate.params == {"scale": 1.0}  # the default of the params model, as the gate returns it
        assert candidate.signal.id == "x_signal"
        assert candidate.signal.sha256 == SHA_ZERO  # marked, so Signal.generate guards its calls
        assert SIGNALS.get("x_signal") is candidate.signal
    assert SIGNALS.snapshot() == before
    assert "x_signal" not in SIGNALS


def test_the_params_of_the_spec_are_validated_by_the_params_model_of_the_candidate() -> None:
    with load_candidate(coded_spec(params={"scale": 0.25}), good_source()) as candidate:
        assert candidate.params == {"scale": 0.25}


def test_a_file_with_crlf_has_the_hash_of_the_lf_form() -> None:
    with load_candidate(coded_spec(), good_source().replace(b"\n", b"\r\n")) as candidate:
        assert candidate.sha256 == SHA_ZERO


def test_params_that_do_not_fit_are_a_spec_error_and_the_registry_is_restored() -> None:
    before = SIGNALS.snapshot()
    with pytest.raises(SpecError), load_candidate(coded_spec(params={"nope": 1}), good_source()):
        pytest.fail("the block must not be entered")
    assert SIGNALS.snapshot() == before


@pytest.mark.parametrize("error", [RuntimeError("boom"), SystemExit(3), KeyboardInterrupt(), GeneratorExit()])
def test_whatever_the_body_raises_the_registry_is_restored(error: BaseException) -> None:
    before = SIGNALS.snapshot()
    with pytest.raises(type(error)), load_candidate(coded_spec(), good_source()):
        assert "x_signal" in SIGNALS
        raise error
    assert SIGNALS.snapshot() == before


def test_the_static_check_runs_again_and_nothing_is_executed_when_it_refuses(world: World) -> None:
    before = SIGNALS.snapshot()
    with pytest.raises(StaticCheckError), load_candidate(coded_spec("canary_signal"), canary_source()):
        pytest.fail("the block must not be entered")
    assert world.marker_lines() == []  # the canary was never executed
    assert SIGNALS.snapshot() == before


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ("raise SystemExit(3)", "SystemExit: 3"),
        ("raise ValueError('boom')", "ValueError: boom"),
        ("raise KeyError('k')", "KeyError: 'k'"),
    ],
)
def test_a_candidate_that_raises_when_it_is_loaded_is_a_gate_error_and_leaves_nothing(
    world: World, static_check_off: None, extra: str, message: str
) -> None:
    before = SIGNALS.snapshot()
    with (
        pytest.raises(GateError, match=message),
        load_candidate(coded_spec("canary_signal"), canary_source(extra=(extra,))),
    ):
        pytest.fail("the block must not be entered")
    assert world.marker_lines() == ["imported 0.0"]  # it did run, once
    assert SIGNALS.snapshot() == before


def test_a_candidate_that_registers_a_second_signal_is_refused_and_both_are_removed(
    world: World, static_check_off: None
) -> None:
    before = SIGNALS.snapshot()
    other = "register_signal('other_signal', params=SignalParams)(lambda prices, params: None)"
    with (
        pytest.raises(GateError, match="must register exactly one signal"),
        load_candidate(coded_spec("canary_signal"), canary_source(extra=(other,))),
    ):
        pytest.fail("the block must not be entered")
    assert "other_signal" not in SIGNALS and "canary_signal" not in SIGNALS
    assert SIGNALS.snapshot() == before


def test_a_candidate_that_removes_a_registered_signal_is_refused_and_the_registry_is_restored(
    world: World, static_check_off: None
) -> None:
    before = SIGNALS.snapshot()
    victim = next(iter(before))
    with (
        pytest.raises(GateError, match="changed the registry"),
        load_candidate(
            coded_spec("canary_signal"),
            canary_source(extra=("from backtest_agent.spec import SIGNALS", f"SIGNALS.unregister({victim!r})")),
        ),
    ):
        pytest.fail("the block must not be entered")
    assert SIGNALS.snapshot() == before


def test_an_id_that_something_other_than_the_gate_registered_is_refused_without_executing(world: World) -> None:
    SIGNALS.register("x_signal")(lambda prices, params: None)
    before = SIGNALS.snapshot()
    with (
        pytest.raises(GateError, match="already registered by something other than the gate"),
        load_candidate(coded_spec(), good_source()),
    ):
        pytest.fail("the block must not be entered")
    assert SIGNALS.snapshot() == before


def test_the_entry_of_the_gate_for_the_same_id_is_set_aside_executed_against_and_put_back(world: World) -> None:
    approved = good_source()
    world.put_file("x_signal", approved)
    world.approve_both("x_signal", approved)
    resolved = world.resolve(coded_spec())
    original = SIGNALS.get("x_signal")
    assert original.sha256 == SHA_ZERO
    with load_candidate(coded_spec(), good_source(factor="0.5")) as candidate:
        assert candidate.sha256 == SHA_HALF
        assert SIGNALS.get("x_signal").sha256 == SHA_HALF  # the candidate, not the approved version
    assert SIGNALS.get("x_signal") is original  # the very entry the gate had loaded
    assert resolved.signal.coded.code_sha256 == SHA_ZERO


def test_the_same_hash_that_the_gate_loaded_is_executed_again_not_reused(world: World, static_check_off: None) -> None:
    source = canary_source()
    world.put_file("canary_signal", source)
    world.approve_both("canary_signal", source)
    world.resolve(coded_spec("canary_signal"))
    assert world.marker_lines() == ["imported 0.0"]
    with load_candidate(coded_spec("canary_signal"), source):
        pass
    assert world.marker_lines() == ["imported 0.0", "imported 0.0"]


def test_the_cache_of_the_check_before_a_run_is_not_touched(world: World) -> None:
    before = set(loader._CHECKED)
    with load_candidate(coded_spec(), good_source()):
        pass
    assert loader._CHECKED == before


def test_nothing_is_written_to_disk(world: World, tmp_path) -> None:
    with load_candidate(coded_spec(), good_source()):
        pass
    assert sorted(p.name for p in tmp_path.iterdir()) == []


def test_a_spec_without_a_coded_block_has_no_candidate() -> None:
    with (
        pytest.raises(GateError, match="no coded block"),
        load_candidate(make_spec(signal="buy_and_hold", params={}), good_source()),
    ):
        pytest.fail("the block must not be entered")


@pytest.mark.parametrize("forged", ["buy_and_hold", "con", "../evil", "X"])
def test_a_forged_spec_with_an_id_that_a_coded_signal_may_not_have_is_refused(forged: str) -> None:
    before = SIGNALS.snapshot()
    with pytest.raises(GateError), load_candidate(with_id(coded_spec(), forged), good_source(forged)):
        pytest.fail("the block must not be entered")
    assert SIGNALS.snapshot() == before
