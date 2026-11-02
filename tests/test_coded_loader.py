"""The loader (backtest_agent.coded.loader): which code runs, how it is registered and what happens when it fails.

Sources are the small ones of ``coded_helpers``. The hashes in the messages are taken with ``hashlib`` (``sha_of``).
"""

import pytest

from backtest_agent.coded import approvals
from backtest_agent.coded.errors import GateError, NotApprovedError, RecordError
from backtest_agent.coded.loader import resolve_coded
from backtest_agent.data import FakeProvider
from backtest_agent.engine import run_backtest
from backtest_agent.spec import SIGNALS, SpecError, UnknownSignalError, get_signal
from coded_helpers import (
    CANARY_ID,
    World,
    canary_source,
    coded_modules,
    coded_spec,
    good_source,
    registry_and_modules_are_restored,  # noqa: F401 - autouse fixture
    sha_of,
)
from runner_helpers import make_spec

V1 = good_source(factor="0.0")
V2 = good_source(factor="0.5")
S1, S2 = sha_of(V1), sha_of(V2)


@pytest.fixture
def two_versions(world: World) -> World:
    """The idea approved with both versions of x_signal; the file holds version 2."""
    world.approve_both("x_signal", V1)
    world.approve_code("x_signal", V2, hour=12)
    world.put_file("x_signal", V2)
    return world


# --- which hash runs ---


def test_the_file_that_was_approved_is_the_code_that_runs_and_the_spec_gets_its_hash(world: World) -> None:
    world.put_file("x_signal", V1)
    world.approve_both("x_signal", V1)
    resolved = world.resolve(coded_spec())
    assert resolved.signal.coded is not None and resolved.signal.coded.code_sha256 == S1
    assert get_signal("x_signal").sha256 == S1
    assert resolved.to_dict()["signal"] == {
        "coded": {"brief": "B", "code_sha256": S1},
        "id": "x_signal",
        "params": {"scale": 1.0},  # the defaults of the params model are written out, as for every signal
    }


def test_the_file_decides_among_the_approved_versions_not_the_latest(two_versions: World) -> None:
    two_versions.put_file("x_signal", V1)  # the older version is on disk
    assert two_versions.resolve(coded_spec()).signal.coded.code_sha256 == S1  # type: ignore[union-attr]


def test_the_file_with_crlf_line_ends_is_the_same_approved_code(world: World) -> None:
    world.approve_both("x_signal", V1)
    world.put_file("x_signal", V1.replace(b"\n", b"\r\n"))
    assert world.resolve(coded_spec()).signal.coded.code_sha256 == S1  # type: ignore[union-attr]


def test_without_a_file_and_without_a_pin_the_latest_approved_version_runs(two_versions: World) -> None:
    (two_versions.signals / "x_signal.py").unlink()
    assert two_versions.resolve(coded_spec()).signal.coded.code_sha256 == S2  # type: ignore[union-attr]


def test_without_a_file_the_pin_is_used_if_it_is_listed(two_versions: World) -> None:
    (two_versions.signals / "x_signal.py").unlink()
    assert two_versions.resolve(coded_spec(pin=S1)).signal.coded.code_sha256 == S1  # type: ignore[union-attr]


def test_a_pin_that_differs_from_the_file_is_refused_even_if_the_file_is_approved(two_versions: World) -> None:
    with pytest.raises(NotApprovedError) as info:
        two_versions.resolve(coded_spec(pin=S1))  # the file is version 2, which is approved
    assert str(info.value) == f"the spec pins {S1[:8]} but strategies/signals/x_signal.py has sha {S2[:8]}"
    assert SIGNALS.snapshot().keys() == {"buy_and_hold", "momentum_12_1", "sma_crossover"}


def test_a_pin_that_equals_the_file_is_accepted(two_versions: World) -> None:
    assert two_versions.resolve(coded_spec(pin=S2)).signal.coded.code_sha256 == S2  # type: ignore[union-attr]


def test_the_stored_mode_never_reads_the_folder_and_runs_the_pinned_version(two_versions: World) -> None:
    (two_versions.signals / "x_signal.py").write_bytes(b"this is not python (\n")  # would fail if it were read
    resolved = two_versions.resolve(coded_spec(pin=S1), stored=True)
    assert resolved.signal.coded.code_sha256 == S1  # type: ignore[union-attr]
    assert resolve_coded(resolved, approvals_dir=two_versions.approvals, strategies_dir=None) == resolved


def test_the_stored_mode_needs_a_pin(two_versions: World) -> None:
    with pytest.raises(RecordError) as info:
        two_versions.resolve(coded_spec(), stored=True)
    assert (
        str(info.value) == "the spec of 'x_signal' pins no code_sha256, so the run cannot be reproduced from its record"
    )


def test_in_the_stored_mode_a_missing_approval_is_a_record_error_not_a_refusal(world: World) -> None:
    with pytest.raises(RecordError, match="the idea of 'x_signal' is not approved: there is no approval record"):
        world.resolve(coded_spec(pin=S1), stored=True)
    world.approve_idea("x_signal", "Another brief")
    with pytest.raises(RecordError, match="changed since it was approved"):
        world.resolve(coded_spec(pin=S1), stored=True)


def test_code_must_be_approved_for_the_idea_that_the_spec_has(world: World) -> None:
    world.approve_both("x_signal", V1, brief="First idea")
    world.approve_idea("x_signal", "Second idea")  # a new idea without code
    world.put_file("x_signal", V1)
    with pytest.raises(NotApprovedError, match=f"code not approved: the file has sha {S1[:8]}"):
        world.resolve(coded_spec(brief="Second idea"))
    (world.signals / "x_signal.py").unlink()
    with pytest.raises(NotApprovedError) as info:
        world.resolve(coded_spec(brief="Second idea"))
    assert str(info.value) == "code not approved: no code is approved for the idea of 'x_signal'"
    assert world.resolve(coded_spec(brief="First idea")).signal.coded.code_sha256 == S1  # type: ignore[union-attr]


def test_a_file_that_cannot_be_read_is_not_approved(world: World) -> None:
    world.approve_both("x_signal", V1)
    (world.signals / "x_signal.py").mkdir(parents=True)  # a folder where the file should be
    with pytest.raises(NotApprovedError, match=r"strategies/signals/x_signal.py cannot be read"):
        world.resolve(coded_spec())


# --- the spec that comes back ---


def test_the_resolved_spec_runs_and_gives_the_same_spec_again_in_the_stored_mode(world: World) -> None:
    world.put_file("x_signal", V2)
    world.approve_both("x_signal", V2)
    resolved = world.resolve(coded_spec(params={"scale": 0.5}))
    result = run_backtest(resolved, FakeProvider(symbols=("AAA", "BBB")))
    assert result.signals["AAA"].iloc[-1] == 0.25  # 0.5 (the version) * 0.5 (the parameter)
    assert world.resolve(resolved, stored=True) == resolved
    assert resolved.to_dict()["signal"]["params"] == {"scale": 0.5}


def test_params_that_do_not_fit_the_params_model_are_a_spec_error_with_the_field_path(world: World) -> None:
    world.put_file("x_signal", V1)
    world.approve_both("x_signal", V1)
    with pytest.raises(SpecError) as info:
        world.resolve(coded_spec(params={"scal": 0.5}))
    assert [(p.path, p.message) for p in info.value.problems] == [
        ("signal.params.scal", "unknown field 'scal'; did you mean 'scale'?"),
    ]
    with pytest.raises(SpecError) as info:
        world.resolve(coded_spec(params={"scale": 2.0}))
    assert [p.path for p in info.value.problems] == ["signal.params.scale"]
    assert "less than or equal to 1" in info.value.problems[0].message


def test_a_spec_without_a_coded_block_is_not_for_the_gate(world: World) -> None:
    with pytest.raises(GateError, match="the spec has no coded block"):
        world.resolve(make_spec())


def test_the_archive_is_read_once_per_resolution(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    world.put_file("x_signal", V1)
    world.approve_both("x_signal", V1)
    calls = []
    original = approvals.read_archived_code

    def counting(directory, sha):
        calls.append(sha)
        return original(directory, sha)

    monkeypatch.setattr("backtest_agent.coded.loader.read_archived_code", counting)
    world.resolve(coded_spec())
    assert calls == [S1]


def test_a_source_with_from_future_annotations_loads_although_its_module_is_not_in_sys_modules(world: World) -> None:
    lines = [
        "from __future__ import annotations",
        "from pydantic import Field",
        "from backtest_agent.spec.signals import SignalParams, per_symbol_signal, register_signal",
        "",
        "",
        "class Params(SignalParams):",
        "    scale: float = Field(1.0, ge=0.0, le=1.0)",
        "    window: int = 3",
        "",
        "    def warmup_rows(self) -> int:",
        "        return self.window",
        "",
        "",
        '@register_signal("x_signal", params=Params)',
        "def x_signal(prices, params):",
        "    return per_symbol_signal(prices, lambda close: close * 0.0)",
    ]
    source = ("\n".join(lines) + "\n").encode()
    world.put_file("x_signal", source)
    world.approve_both("x_signal", source)
    resolved = world.resolve(coded_spec(params={"window": 5}))
    assert resolved.warmup_rows == 5
    assert coded_modules() == []


# --- re-registration in one process (the canary counts how often the code was executed) ---


@pytest.mark.usefixtures("static_check_off")
class TestRegistration:
    def test_the_same_version_is_reused_without_executing_again(self, world: World) -> None:
        world.put_file(CANARY_ID, canary_source())
        world.approve_both(CANARY_ID, canary_source())
        first = world.resolve(coded_spec(CANARY_ID))
        loaded = get_signal(CANARY_ID)
        second = world.resolve(coded_spec(CANARY_ID))
        assert second == first and get_signal(CANARY_ID) is loaded
        assert world.marker_lines() == ["imported 0.0"]  # executed once

    def test_a_different_version_replaces_the_entry_of_the_gate_and_the_old_spec_is_not_loaded_any_more(
        self, world: World
    ) -> None:
        v1, v2 = canary_source(factor="0.0"), canary_source(factor="0.5")
        world.put_file(CANARY_ID, v1)
        world.approve_both(CANARY_ID, v1)
        old = world.resolve(coded_spec(CANARY_ID))
        world.approve_code(CANARY_ID, v2, hour=12)
        world.put_file(CANARY_ID, v2)
        new = world.resolve(coded_spec(CANARY_ID))
        assert world.marker_lines() == ["imported 0.0", "imported 0.5"]
        assert get_signal(CANARY_ID).sha256 == sha_of(v2) == new.signal.coded.code_sha256  # type: ignore[union-attr]
        with pytest.raises(UnknownSignalError, match="the spec pins sha " + sha_of(v1)[:8]):
            old.warmup_rows  # noqa: B018 - the old resolved spec has to be resolved again

    def test_a_stored_run_of_the_old_version_loads_it_from_the_archive_not_from_the_file(self, world: World) -> None:
        v1, v2 = canary_source(factor="0.0"), canary_source(factor="0.5")
        world.put_file(CANARY_ID, v1)
        world.approve_both(CANARY_ID, v1)
        old = world.resolve(coded_spec(CANARY_ID))
        world.approve_code(CANARY_ID, v2, hour=12)
        world.put_file(CANARY_ID, v2)
        world.resolve(coded_spec(CANARY_ID))  # version 2 is the one that is loaded now
        again = world.resolve(old, stored=True)  # bt report of the first run
        assert again == old and get_signal(CANARY_ID).sha256 == sha_of(v1)
        assert world.marker_lines() == ["imported 0.0", "imported 0.5", "imported 0.0"]

    def test_a_version_that_fails_to_load_leaves_the_registry_as_it_was(self, world: World) -> None:
        v1 = canary_source(factor="0.0")
        v2 = canary_source(factor="0.5", extra=('raise ValueError("boom")',))
        world.put_file(CANARY_ID, v1)
        world.approve_both(CANARY_ID, v1)
        world.resolve(coded_spec(CANARY_ID))
        kept = get_signal(CANARY_ID)
        world.approve_code(CANARY_ID, v2, hour=12)
        world.put_file(CANARY_ID, v2)
        with pytest.raises(GateError) as info:
            world.resolve(coded_spec(CANARY_ID))
        assert str(info.value) == "the code of 'canary_signal' failed when it was loaded: ValueError: boom"
        assert isinstance(info.value.__cause__, ValueError)
        assert get_signal(CANARY_ID) is kept  # version 1 is still there, unchanged

    def test_an_id_registered_by_something_else_is_refused(self, world: World) -> None:
        world.put_file(CANARY_ID, canary_source())
        world.approve_both(CANARY_ID, canary_source())
        SIGNALS.register(CANARY_ID)(lambda prices, params: prices)  # a fixture, not loaded by the gate
        before = SIGNALS.snapshot()
        with pytest.raises(GateError) as info:
            world.resolve(coded_spec(CANARY_ID))
        assert str(info.value) == "the id 'canary_signal' is already registered by something other than the gate"
        assert SIGNALS.snapshot() == before and world.marker_lines() == []

    @pytest.mark.parametrize(
        ("extra", "registered"),
        [
            (
                '@register_signal("other_signal")\ndef other_signal(prices, params):\n    return prices',
                "canary_signal, other_signal",
            ),
        ],
    )
    def test_code_that_registers_more_than_its_signal_is_refused_and_the_registry_restored(
        self, world: World, extra: str, registered: str
    ) -> None:
        source = canary_source(extra=(extra,))
        world.put_file(CANARY_ID, source)
        world.approve_both(CANARY_ID, source)
        before = SIGNALS.snapshot()
        with pytest.raises(GateError) as info:
            world.resolve(coded_spec(CANARY_ID))
        assert (
            str(info.value) == f"the code must register exactly one signal, 'canary_signal'; it registered {registered}"
        )
        assert SIGNALS.snapshot() == before

    @pytest.mark.parametrize(
        "extra",
        [
            ("from backtest_agent.spec import SIGNALS", 'SIGNALS.unregister("buy_and_hold")'),
            ("from backtest_agent.spec import SIGNALS", 'SIGNALS.set_sha256("sma_crossover", "ab" * 32)'),
        ],
        ids=["removes a signal", "changes a signal"],
    )
    def test_code_that_changes_other_registered_signals_is_refused_and_they_are_back(
        self, world: World, extra: tuple[str, ...]
    ) -> None:
        source = canary_source(extra=extra)
        world.put_file(CANARY_ID, source)
        world.approve_both(CANARY_ID, source)
        before = SIGNALS.snapshot()
        with pytest.raises(GateError) as info:
            world.resolve(coded_spec(CANARY_ID))
        assert str(info.value) == "the code changed the registry beyond registering 'canary_signal'"
        assert SIGNALS.snapshot() == before
        assert get_signal("buy_and_hold").sha256 is None and get_signal("sma_crossover").sha256 is None

    def test_code_that_registers_another_id_or_nothing_is_refused(self, world: World) -> None:
        for source, registered in [
            (
                canary_source().replace(b'register_signal("canary_signal"', b'register_signal("other_signal"'),
                "other_signal",
            ),
            (canary_source().replace(b"@register_signal(", b"# register_signal("), "nothing"),
        ]:
            world.put_file(CANARY_ID, source)
            world.approve_idea(CANARY_ID)
            world.approve_code(CANARY_ID, source)
            before = SIGNALS.snapshot()
            with pytest.raises(GateError, match=f"it registered {registered}$"):
                world.resolve(coded_spec(CANARY_ID))
            assert SIGNALS.snapshot() == before

    @pytest.mark.parametrize(
        ("line", "message"),
        [
            ("raise SystemExit(3)", "SystemExit: 3"),
            ('raise ImportError("no module")', "ImportError: no module"),
            ("x = 1 / 0", "ZeroDivisionError: division by zero"),
        ],
    )
    def test_code_that_raises_when_it_is_loaded_is_a_gate_error_even_if_it_tries_to_end_the_process(
        self, world: World, line: str, message: str
    ) -> None:
        source = canary_source(extra=(line,))
        world.put_file(CANARY_ID, source)
        world.approve_both(CANARY_ID, source)
        before = SIGNALS.snapshot()
        with pytest.raises(GateError) as info:
            world.resolve(coded_spec(CANARY_ID))
        assert str(info.value) == f"the code of 'canary_signal' failed when it was loaded: {message}"
        assert SIGNALS.snapshot() == before

    def test_code_that_does_not_compile_is_a_gate_error(self, world: World) -> None:
        source = canary_source(extra=("def broken(:",))
        world.put_file(CANARY_ID, source)
        world.approve_both(CANARY_ID, source)
        with pytest.raises(GateError, match="failed when it was loaded: SyntaxError: "):
            world.resolve(coded_spec(CANARY_ID))
