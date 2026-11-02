"""The contract check before a run is part of the resolution: inside the restore, once per code and params.

(ADR 0018.) The canary writes a line to its marker each time its code is executed.
"""

import pytest

from backtest_agent.coded import loader
from backtest_agent.coded.errors import GateError
from backtest_agent.spec import SIGNALS, SignalContractError, SpecError, UnknownSignalError, get_signal
from coded_helpers import (
    CANARY_ID,
    World,
    coded_spec,
    good_source,
    registry_and_modules_are_restored,  # noqa: F401 - autouse fixture
    sha_of,
)


def canary_with(body: str, *, params: str = "SignalParams") -> bytes:
    """A canary (static check switched off by the tests) whose signal function is ``body`` (an indented block)."""
    lines = [
        '"""A canary whose function is chosen by the test."""',
        "import os",
        "from pydantic import Field",
        "from backtest_agent.spec.signals import SignalParams, per_symbol_signal, register_signal",
        "",
        'with open(os.environ["CANARY_MARKER"], "a") as marker:',
        '    marker.write("imported" + chr(10))',
        "",
        "",
        "class Params(SignalParams):",
        "    window: int = 3",
        "",
        "",
        f'@register_signal("{CANARY_ID}", params=Params)',
        f"def {CANARY_ID}(prices, params):",
        *body.splitlines(),
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


ZEROS = "    return per_symbol_signal(prices, lambda close: close * 0.0)"
PEEK = "    return per_symbol_signal(prices, lambda close: (close.shift(-1) > close).astype('float64'))"
BOOM = "    raise RuntimeError('boom')"


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list:
    """The params the check before a run was called with; the real check still runs."""
    seen: list = []
    real = loader.check_before_run

    def spy(signal, params):
        seen.append(params)
        real(signal, params)

    monkeypatch.setattr("backtest_agent.coded.loader.check_before_run", spy)
    return seen


# --- a failing check leaves nothing behind ---


@pytest.mark.usefixtures("static_check_off")
@pytest.mark.parametrize(
    ("body", "message"),
    [
        (PEEK, "canary_signal on the plain frame: the value on 20"),
        (BOOM, "canary_signal on the plain frame: RuntimeError: boom"),
    ],
    ids=["looks at the future", "raises"],
)
def test_a_failing_check_leaves_the_registry_as_it_was_and_a_corrected_version_loads(
    world: World, body: str, message: str
) -> None:
    bad, good = canary_with(body), canary_with(ZEROS)
    world.put_file(CANARY_ID, bad)
    world.approve_both(CANARY_ID, bad)
    before = SIGNALS.snapshot()
    with pytest.raises(SignalContractError) as info:
        world.resolve(coded_spec(CANARY_ID))
    assert str(info.value).startswith(message)
    assert SIGNALS.snapshot() == before
    with pytest.raises(UnknownSignalError):
        get_signal(CANARY_ID)
    assert world.marker_lines() == ["imported"]  # it ran, and it was unloaded again

    world.approve_code(CANARY_ID, good, hour=12)
    world.put_file(CANARY_ID, good)
    resolved = world.resolve(coded_spec(CANARY_ID))
    assert world.marker_lines() == ["imported", "imported"]
    assert resolved.signal.coded.code_sha256 == sha_of(good)  # type: ignore[union-attr]


@pytest.mark.usefixtures("static_check_off")
def test_a_failing_check_after_a_replacement_leaves_the_version_that_was_loaded(world: World) -> None:
    good, bad = canary_with(ZEROS), canary_with(PEEK)
    world.put_file(CANARY_ID, good)
    world.approve_both(CANARY_ID, good)
    world.resolve(coded_spec(CANARY_ID))
    kept = get_signal(CANARY_ID)
    world.approve_code(CANARY_ID, bad, hour=12)
    world.put_file(CANARY_ID, bad)
    before = SIGNALS.snapshot()
    with pytest.raises(SignalContractError):
        world.resolve(coded_spec(CANARY_ID))
    assert SIGNALS.snapshot() == before and get_signal(CANARY_ID) is kept


# --- when the check runs ---


def test_the_check_runs_once_for_the_same_code_and_params_and_again_for_other_params(world: World, calls: list) -> None:
    source = good_source()
    world.put_file("x_signal", source)
    world.approve_both("x_signal", source)
    world.resolve(coded_spec())
    world.resolve(coded_spec())
    assert len(calls) == 1
    world.resolve(coded_spec(params={"scale": 0.5}))
    assert len(calls) == 2
    world.resolve(coded_spec(params={"scale": 0.5}))
    assert len(calls) == 2
    loader.clear_checked()
    world.resolve(coded_spec())
    assert len(calls) == 3


def test_the_check_gets_the_params_with_their_defaults_as_an_instance_of_the_model(world: World, calls: list) -> None:
    source = good_source()
    world.put_file("x_signal", source)
    world.approve_both("x_signal", source)
    world.resolve(coded_spec(params={"scale": 0.25}))
    (params,) = calls
    assert type(params).__name__ == "Params" and params.scale == 0.25


def test_another_version_of_the_code_is_checked_again(world: World, calls: list) -> None:
    v1, v2 = good_source(factor="0.0"), good_source(factor="0.5")
    world.put_file("x_signal", v1)
    world.approve_both("x_signal", v1)
    world.resolve(coded_spec())
    world.approve_code("x_signal", v2, hour=12)
    world.put_file("x_signal", v2)
    world.resolve(coded_spec())
    assert len(calls) == 2


@pytest.mark.usefixtures("static_check_off")
def test_a_check_that_failed_is_not_remembered(world: World, calls: list) -> None:
    bad = canary_with(PEEK)
    world.put_file(CANARY_ID, bad)
    world.approve_both(CANARY_ID, bad)
    for _ in range(2):
        with pytest.raises(SignalContractError):
            world.resolve(coded_spec(CANARY_ID))
    assert len(calls) == 2


def test_the_stored_mode_checks_too(world: World, calls: list) -> None:
    source = good_source()
    sha = world.approve_both("x_signal", source)
    world.resolve(coded_spec(pin=sha), stored=True)
    assert len(calls) == 1


def test_params_that_do_not_fit_are_refused_before_the_check(world: World, calls: list) -> None:
    source = good_source()
    world.put_file("x_signal", source)
    world.approve_both("x_signal", source)
    with pytest.raises(SpecError):
        world.resolve(coded_spec(params={"nope": 1}))
    with pytest.raises(GateError):
        world.resolve(coded_spec(params={"scale": 0.5}), stored=True)  # stored mode needs a pin
    assert calls == []
