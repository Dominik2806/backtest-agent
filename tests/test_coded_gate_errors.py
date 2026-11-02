"""Every documented failure of ``resolve_coded`` raises exactly the documented class, and nothing else (ADR 0018).

One row per failure. The class is compared with ``type(error) is ...``, so a subclass or a raw exception of another
kind fails the row. For the classes that the commands will map, the table also pins the exit code planned for ``bt``:
``NotApprovedError`` 8, ``RecordError`` 5 (stored mode), ``StaticCheckError`` and ``SignalContractError`` 9,
``SpecError`` 3; a ``GateError`` has no code of its own yet. After each failure the registry is what it was.
"""

from collections.abc import Callable

import pytest

from backtest_agent.coded.approvals import ApprovalRecord, CodeApproval, IdeaApproval, idea_sha256, render_record
from backtest_agent.coded.errors import GateError, NotApprovedError, RecordError, StaticCheckError
from backtest_agent.coded.loader import FILE_LIMIT
from backtest_agent.spec import SIGNALS, SignalContractError, SpecError, StrategySpec, UnknownSignalError
from coded_helpers import (
    World,
    canary_source,
    coded_spec,
    good_source,
    registry_and_modules_are_restored,  # noqa: F401 - autouse fixture
    sha_of,
    with_id,
)
from runner_helpers import make_spec

PLANNED_EXIT_CODE = {
    NotApprovedError: 8,
    RecordError: 5,
    StaticCheckError: 9,
    SignalContractError: 9,
    SpecError: 3,
    GateError: None,
}
V1, V2 = good_source(factor="0.0"), good_source(factor="0.5")
Thunk = Callable[[], object]


def static_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backtest_agent.coded.approvals.check_source", lambda data, signal_id: None)
    monkeypatch.setattr("backtest_agent.coded.loader.check_source", lambda data, signal_id: None)


def prepared(world: World, source: bytes = V1) -> str:
    world.put_file("x_signal", source)
    return world.approve_both("x_signal", source)


def model_source(*fields: str, validator: str | None = None) -> bytes:
    lines = [
        '"""A signal with a params model."""',
        "from pydantic import Field, field_validator",
        "from backtest_agent.spec.signals import SignalParams, per_symbol_signal, register_signal",
        "",
        "",
        "class Params(SignalParams):",
        *([f"    {field}" for field in fields] or ["    pass"]),
        *(
            [
                "",
                '    @field_validator("scale")',
                "    @classmethod",
                "    def _check(cls, scale):",
                f"        {validator}",
            ]
            if validator
            else []
        ),
        "",
        "",
        '@register_signal("x_signal", params=Params)',
        "def x_signal(prices, params):",
        "    return per_symbol_signal(prices, lambda close: close * 0.0)",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


# --- the rows: (name, builder(world, monkeypatch) -> thunk, expected class) ---


def row_no_coded_block(world, mp) -> Thunk:
    return lambda: world.resolve(make_spec())


def row_id_not_allowed(world, mp) -> Thunk:
    return lambda: world.resolve(with_id(coded_spec(), "con"))


def row_idea_not_approved(world, mp) -> Thunk:
    return lambda: world.resolve(coded_spec())


def row_brief_changed(world, mp) -> Thunk:
    prepared(world)
    return lambda: world.resolve(coded_spec(brief="Another brief"))


def row_stored_idea_not_approved(world, mp) -> Thunk:
    return lambda: world.resolve(coded_spec(pin=sha_of(V1)), stored=True)


def row_stored_without_pin(world, mp) -> Thunk:
    prepared(world)
    return lambda: world.resolve(coded_spec(), stored=True)


def row_stored_pin_not_listed(world, mp) -> Thunk:
    prepared(world)
    return lambda: world.resolve(coded_spec(pin=sha_of(V2)), stored=True)


def row_file_not_approved(world, mp) -> Thunk:
    prepared(world)
    world.put_file("x_signal", V2)
    return lambda: world.resolve(coded_spec())


def row_pin_differs_from_file(world, mp) -> Thunk:
    prepared(world)
    world.approve_code("x_signal", V2, hour=12)
    world.put_file("x_signal", V2)  # the file is version 2, which is approved
    return lambda: world.resolve(coded_spec(pin=sha_of(V1)))


def row_no_code_approved_and_no_file(world, mp) -> Thunk:
    world.approve_idea("x_signal")
    return lambda: world.resolve(coded_spec())


def row_pin_not_listed_and_no_file(world, mp) -> Thunk:
    world.approve_idea("x_signal")
    return lambda: world.resolve(coded_spec(pin=sha_of(V1)))


def row_file_is_a_folder(world, mp) -> Thunk:
    prepared(world)
    (world.signals / "x_signal.py").unlink()
    (world.signals / "x_signal.py").mkdir()
    return lambda: world.resolve(coded_spec())


def row_file_too_large(world, mp) -> Thunk:
    prepared(world)
    world.put_file("x_signal", b"#" * (FILE_LIMIT + 1))
    return lambda: world.resolve(coded_spec())


def row_archive_missing(world, mp) -> Thunk:
    sha = prepared(world)
    (world.approvals / "code" / f"{sha}.py").unlink()
    return lambda: world.resolve(coded_spec())


def row_archive_changed(world, mp) -> Thunk:
    sha = prepared(world)
    (world.approvals / "code" / f"{sha}.py").write_bytes(V1 + b"# edited\n")
    return lambda: world.resolve(coded_spec())


def row_record_malformed(world, mp) -> Thunk:
    world.approvals.mkdir(parents=True)
    (world.approvals / "x_signal.json").write_bytes(b"{")
    return lambda: world.resolve(coded_spec())


def row_static_check_fails_on_the_archive(world, mp) -> Thunk:
    source = canary_source("x_signal")  # uses open and os: the real static check refuses it
    sha = sha_of(source)
    entry = IdeaApproval(
        idea_sha256("x_signal", "B"), "2026-11-02T10:00:00Z", (CodeApproval(sha, "2026-11-02T11:00:00Z"),)
    )
    (world.approvals / "code").mkdir(parents=True)
    (world.approvals / "code" / f"{sha}.py").write_bytes(source)
    (world.approvals / "x_signal.json").write_bytes(render_record(ApprovalRecord("x_signal", (entry,))))
    return lambda: world.resolve(coded_spec(pin=sha), stored=True)


def row_id_taken_by_something_else(world, mp) -> Thunk:
    prepared(world)
    SIGNALS.register("x_signal")(lambda prices, params: prices)
    return lambda: world.resolve(coded_spec())


def canary_row(world, mp, *extra: str) -> Thunk:
    static_off(mp)
    source = canary_source("x_signal", extra=extra)
    prepared(world, source)
    return lambda: world.resolve(coded_spec())


def row_code_raises_when_loaded(world, mp) -> Thunk:
    return canary_row(world, mp, 'raise ValueError("boom")')


def row_code_exits_when_loaded(world, mp) -> Thunk:
    return canary_row(world, mp, "raise SystemExit(3)")


def row_code_registers_two_signals(world, mp) -> Thunk:
    return canary_row(
        world, mp, '@register_signal("other_signal")\ndef other_signal(prices, params):\n    return prices'
    )


def row_params_do_not_fit(world, mp) -> Thunk:
    prepared(world, model_source("window: int = 3"))
    return lambda: world.resolve(coded_spec(params={"windo": 3}))


def row_default_a_spec_cannot_hold(world, mp) -> Thunk:
    prepared(world, model_source("cap: float | None = None"))
    return lambda: world.resolve(coded_spec())


def row_model_rejects_its_own_default(world, mp) -> Thunk:
    prepared(world, model_source("scale: float = Field(2.0, le=1.0)"))
    return lambda: world.resolve(coded_spec())


def row_validator_raises(world, mp) -> Thunk:
    prepared(world, model_source("scale: float = 1.0", validator="raise RuntimeError('bad')"))
    return lambda: world.resolve(coded_spec(params={"scale": 0.5}))


def row_validator_exits(world, mp) -> Thunk:
    prepared(world, model_source("scale: float = 1.0", validator="raise SystemExit(3)"))
    return lambda: world.resolve(coded_spec(params={"scale": 0.5}))


def row_contract_violation(world, mp) -> Thunk:
    peek = model_source().replace(b"close * 0.0", b"(close.shift(-1) > close).astype('float64')")
    prepared(world, peek)
    return lambda: world.resolve(coded_spec())


def row_code_raises_in_the_check(world, mp) -> Thunk:
    boom = model_source().replace(b"lambda close: close * 0.0", b"lambda close: 1 / 0")
    prepared(world, boom)
    return lambda: world.resolve(coded_spec())


def row_last_step_fails(world, mp) -> Thunk:
    prepared(world)
    spec = coded_spec()

    def refuse(*args, **kwargs):
        raise UnknownSignalError("the registry changed under the gate")

    mp.setattr(StrategySpec, "model_validate", refuse)
    return lambda: world.resolve(spec)


ROWS = [
    (row_no_coded_block, GateError),
    (row_id_not_allowed, GateError),
    (row_idea_not_approved, NotApprovedError),
    (row_brief_changed, NotApprovedError),
    (row_stored_idea_not_approved, RecordError),
    (row_stored_without_pin, RecordError),
    (row_stored_pin_not_listed, RecordError),
    (row_file_not_approved, NotApprovedError),
    (row_pin_differs_from_file, NotApprovedError),
    (row_no_code_approved_and_no_file, NotApprovedError),
    (row_pin_not_listed_and_no_file, NotApprovedError),
    (row_file_is_a_folder, NotApprovedError),
    (row_file_too_large, NotApprovedError),
    (row_archive_missing, RecordError),
    (row_archive_changed, RecordError),
    (row_record_malformed, RecordError),
    (row_static_check_fails_on_the_archive, StaticCheckError),
    (row_id_taken_by_something_else, GateError),
    (row_code_raises_when_loaded, GateError),
    (row_code_exits_when_loaded, GateError),
    (row_code_registers_two_signals, GateError),
    (row_params_do_not_fit, SpecError),
    (row_default_a_spec_cannot_hold, GateError),
    (row_model_rejects_its_own_default, GateError),
    (row_validator_raises, GateError),
    (row_validator_exits, GateError),
    (row_contract_violation, SignalContractError),
    (row_code_raises_in_the_check, SignalContractError),
    (row_last_step_fails, GateError),
]


@pytest.mark.parametrize(("builder", "expected"), ROWS, ids=[row[0].__name__.removeprefix("row_") for row in ROWS])
def test_every_failure_of_resolve_coded_is_exactly_the_documented_class(
    world: World, monkeypatch: pytest.MonkeyPatch, builder, expected
) -> None:
    thunk = builder(world, monkeypatch)
    before = SIGNALS.snapshot()  # the setup of a row may register a fixture; the gate must leave it as it found it
    with pytest.raises(BaseException) as info:  # noqa: PT011 - the point is to see which class comes out
        thunk()
    assert type(info.value) is expected, f"{builder.__name__}: {type(info.value).__name__}: {info.value}"
    assert SIGNALS.snapshot() == before


def test_the_planned_exit_codes_of_the_classes_are_the_documented_ones() -> None:
    assert PLANNED_EXIT_CODE[NotApprovedError] == 8 and PLANNED_EXIT_CODE[RecordError] == 5
    assert PLANNED_EXIT_CODE[StaticCheckError] == PLANNED_EXIT_CODE[SignalContractError] == 9
    assert PLANNED_EXIT_CODE[SpecError] == 3


def test_the_rows_cover_every_class_the_gate_can_raise() -> None:
    assert {expected for _, expected in ROWS} == set(PLANNED_EXIT_CODE)  # no class is left without a row


def test_the_classes_of_the_gate_are_what_the_documents_say() -> None:
    assert issubclass(NotApprovedError, GateError) and issubclass(RecordError, GateError)
