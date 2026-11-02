"""When a resolution fails after the code was loaded, the code is unloaded again: the registry is what it was.

(ADR 0018.) The canary writes a line to a marker file each time its code is executed, so "it ran twice" shows that the
first load really was undone, and a second resolution with corrected params works.
"""

import pytest

from backtest_agent.coded.errors import GateError
from backtest_agent.spec import SIGNALS, SpecError, StrategySpec, UnknownSignalError, get_signal
from coded_helpers import (
    CANARY_ID,
    World,
    coded_spec,
    registry_and_modules_are_restored,  # noqa: F401 - autouse fixture
)

pytestmark = pytest.mark.usefixtures("static_check_off")

GUARD = [
    '    @field_validator("scale")',
    "    @classmethod",
    "    def _check(cls, scale):",
    "        if scale > 0.5:",
    '            raise RuntimeError("too big")',
    "        return scale",
]


def canary_with_params(*fields: str, validator: bool = False, factor: str = "0.0") -> bytes:
    lines = [
        '"""A canary with a params model."""',
        "import os",
        "from pydantic import Field, field_validator",
        "from backtest_agent.spec.signals import SignalParams, per_symbol_signal, register_signal",
        "",
        'with open(os.environ["CANARY_MARKER"], "a") as marker:',
        '    marker.write("imported" + chr(10))',
        "",
        "",
        "class Params(SignalParams):",
        *(f"    {field}" for field in fields),
        *(["", *GUARD] if validator else []),
        "",
        "",
        f'@register_signal("{CANARY_ID}", params=Params)',
        f"def {CANARY_ID}(prices, params):",
        f"    return per_symbol_signal(prices, lambda close: close * 0.0 + {factor})",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def prepared(world: World, source: bytes) -> World:
    world.put_file(CANARY_ID, source)
    world.approve_both(CANARY_ID, source)
    return world


def fails_then_works(world: World, bad: dict, good: dict, error: type[Exception]) -> None:
    """The first resolution raises ``error`` and leaves nothing loaded; the second, with ``good`` params, works."""
    before = SIGNALS.snapshot()
    with pytest.raises(error):
        world.resolve(coded_spec(CANARY_ID, params=bad))
    assert SIGNALS.snapshot() == before
    with pytest.raises(UnknownSignalError):
        get_signal(CANARY_ID)
    assert world.marker_lines() == ["imported"]  # the code ran once, and it was unloaded again

    resolved = world.resolve(coded_spec(CANARY_ID, params=good))
    assert world.marker_lines() == ["imported", "imported"]  # it ran again: nothing was left over to reuse
    assert get_signal(CANARY_ID).sha256 == resolved.signal.coded.code_sha256  # type: ignore[union-attr]


def test_a_default_a_spec_cannot_hold(world: World) -> None:
    prepared(world, canary_with_params("cap: float | None = None"))
    fails_then_works(world, {}, {"cap": 1.0}, GateError)


def test_a_validator_that_crashes_on_a_value_of_the_spec(world: World) -> None:
    prepared(world, canary_with_params("scale: float = 0.1", validator=True))
    fails_then_works(world, {"scale": 0.9}, {"scale": 0.1}, GateError)


def test_a_validator_that_crashes_only_on_the_default(world: World) -> None:
    prepared(world, canary_with_params("scale: float = 0.9", validator=True))  # the default breaks its own validator
    fails_then_works(world, {}, {"scale": 0.1}, GateError)


def test_a_model_that_does_not_accept_its_own_default(world: World) -> None:
    prepared(world, canary_with_params("scale: float = Field(2.0, le=1.0)"))
    fails_then_works(world, {}, {"scale": 0.5}, GateError)


def test_params_that_do_not_fit_the_model(world: World) -> None:
    prepared(world, canary_with_params("window: int = 3"))
    fails_then_works(world, {"windo": 3}, {}, SpecError)


def test_a_failure_of_the_last_step(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    prepared(world, canary_with_params("window: int = 3"))
    spec = coded_spec(CANARY_ID)
    before = SIGNALS.snapshot()

    def refuse(*args, **kwargs):
        raise UnknownSignalError("the registry changed under the gate")

    with monkeypatch.context() as patch:
        patch.setattr(StrategySpec, "model_validate", refuse)
        with pytest.raises(GateError, match="the resolved spec is not valid"):
            world.resolve(spec)
    assert SIGNALS.snapshot() == before
    with pytest.raises(UnknownSignalError):
        get_signal(CANARY_ID)
    assert world.marker_lines() == ["imported"]
    world.resolve(spec)
    assert world.marker_lines() == ["imported", "imported"]


def test_a_failed_replacement_leaves_the_version_that_was_loaded_before(world: World) -> None:
    v1 = canary_with_params("scale: float = 0.1", validator=True, factor="0.0")
    v2 = canary_with_params("scale: float = 0.1", validator=True, factor="0.5")
    prepared(world, v1)
    world.resolve(coded_spec(CANARY_ID))
    kept = get_signal(CANARY_ID)
    world.approve_code(CANARY_ID, v2, hour=12)
    world.put_file(CANARY_ID, v2)
    before = SIGNALS.snapshot()
    with pytest.raises(GateError):
        world.resolve(coded_spec(CANARY_ID, params={"scale": 0.9}))  # version 2 loads, its validator then fails
    assert SIGNALS.snapshot() == before and get_signal(CANARY_ID) is kept
    assert world.marker_lines() == ["imported", "imported"]  # version 1, and the attempt at version 2
    world.resolve(coded_spec(CANARY_ID, params={"scale": 0.2}))
    assert world.marker_lines() == ["imported", "imported", "imported"]
    assert get_signal(CANARY_ID) is not kept


def test_a_failure_after_a_reuse_leaves_the_loaded_version_as_it_was(world: World) -> None:
    prepared(world, canary_with_params("window: int = 3"))
    world.resolve(coded_spec(CANARY_ID))
    kept = get_signal(CANARY_ID)
    with pytest.raises(SpecError):
        world.resolve(coded_spec(CANARY_ID, params={"windo": 3}))
    assert get_signal(CANARY_ID) is kept  # it was loaded before this call, so it stays
    assert world.marker_lines() == ["imported"]  # and nothing was executed again


def test_a_resolution_that_works_changes_nothing_about_this(world: World) -> None:
    prepared(world, canary_with_params("window: int = 3"))
    resolved = world.resolve(coded_spec(CANARY_ID))
    assert get_signal(CANARY_ID).sha256 == resolved.signal.coded.code_sha256  # type: ignore[union-attr]
    assert world.marker_lines() == ["imported"]


def test_a_keyboard_interrupt_while_the_code_is_loaded_passes_through_and_the_registry_is_restored(
    world: World,
) -> None:
    source = canary_with_params("window: int = 3") + b"\nraise KeyboardInterrupt  # after the signal was registered\n"
    world.put_file(CANARY_ID, source)
    world.approve_both(CANARY_ID, source)
    before = SIGNALS.snapshot()
    with pytest.raises(KeyboardInterrupt):
        world.resolve(coded_spec(CANARY_ID))
    assert SIGNALS.snapshot() == before
    with pytest.raises(UnknownSignalError):
        get_signal(CANARY_ID)
