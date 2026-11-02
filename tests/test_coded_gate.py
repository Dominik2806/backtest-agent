"""The gate never loads code that a person did not approve: a canary whose import writes a marker file (ADR 0018).

Rows G1 to G10 are the ways the gate has to refuse. In every row the marker file is absent afterwards (nothing was
compiled or executed), no module of the canary exists, and the registry is exactly what it was. The last tests show
the marker appears only after the idea and the code were approved and the spec was resolved, so the absences are not
vacuous.
"""

import pytest
import yaml

from backtest_agent.coded.approvals import (
    ApprovalRecord,
    CodeApproval,
    IdeaApproval,
    idea_sha256,
    render_record,
)
from backtest_agent.coded.errors import GateError, NotApprovedError, RecordError, StaticCheckError
from backtest_agent.data import FakeProvider
from backtest_agent.engine import run_backtest
from backtest_agent.metrics import evaluate
from backtest_agent.spec import SIGNALS, UnknownSignalError, load_spec
from cli_helpers import run_cli
from coded_helpers import (
    CANARY_ID,
    World,
    at,
    canary_source,
    coded_modules,
    coded_spec,
    registry_and_modules_are_restored,  # noqa: F401 - autouse fixture
    sha_of,
    with_id,
)

pytestmark = pytest.mark.usefixtures("static_check_off")


def nothing_happened(world: World, before: dict) -> None:
    """The marker was never written, no module exists and the registry is as it was."""
    assert world.marker_lines() == []
    assert coded_modules() == []
    assert SIGNALS.snapshot() == before


@pytest.fixture
def before() -> dict:
    return SIGNALS.snapshot()


def canary_world(world: World) -> bytes:
    source = canary_source()
    world.put_file(CANARY_ID, source)
    return source


# --- G1 to G10 ---


def test_g1_no_approval_record_at_all(world: World, before: dict) -> None:
    canary_world(world)
    with pytest.raises(NotApprovedError) as info:
        world.resolve(coded_spec(CANARY_ID))
    assert str(info.value) == "the idea of 'canary_signal' is not approved: there is no approval record"
    nothing_happened(world, before)


def test_g2_the_record_holds_another_idea(world: World, before: dict) -> None:
    canary_world(world)
    world.approve_idea(CANARY_ID, "Some other idea")
    with pytest.raises(NotApprovedError) as info:
        world.resolve(coded_spec(CANARY_ID))
    assert str(info.value) == (
        "the brief of 'canary_signal' changed since it was approved: no approved idea has this brief"
    )
    nothing_happened(world, before)


def test_g3_the_brief_was_edited_after_the_approval_by_one_space(world: World, before: dict) -> None:
    canary_world(world)
    world.approve_both(CANARY_ID, canary_source(), brief="Hold nothing.")
    with pytest.raises(NotApprovedError, match="changed since it was approved"):
        world.resolve(coded_spec(CANARY_ID, brief="Hold nothing. "))
    world.resolve(coded_spec(CANARY_ID, brief="Hold nothing."))  # the approved brief itself does load (see below)
    assert world.marker_lines() == ["imported 0.0"]


def test_g4_a_built_in_id_is_refused_before_anything_is_read(world: World, before: dict) -> None:
    forged = with_id(coded_spec(CANARY_ID), "sma_crossover")
    with pytest.raises(GateError) as info:
        world.resolve(forged)
    assert type(info.value) is GateError
    assert str(info.value) == "'sma_crossover' is the id of a built-in signal; a coded signal needs an id of its own"
    assert not world.approvals.exists() and not world.signals.exists()
    nothing_happened(world, before)


@pytest.mark.parametrize("bad_id", ["..", "a/b", "a\\b", "C:", "con", "nul", "COM1", "x.py", ""])
def test_g5_an_id_that_is_a_path_or_a_device_name_is_refused_before_anything_is_read(
    world: World, before: dict, bad_id: str
) -> None:
    forged = with_id(coded_spec(CANARY_ID), bad_id)
    with pytest.raises(GateError) as info:
        world.resolve(forged)
    assert type(info.value) is GateError
    assert not world.approvals.exists() and not world.signals.exists()
    nothing_happened(world, before)


def test_g6_a_hash_that_is_not_listed_for_the_idea(world: World, before: dict) -> None:
    canary_world(world)
    world.approve_idea(CANARY_ID)  # the idea is approved, no code is
    unlisted = "ab" * 32
    with pytest.raises(RecordError, match="the pinned code abababab is not approved for this idea"):
        world.resolve(coded_spec(CANARY_ID, pin=unlisted), stored=True)
    world.signals.joinpath(f"{CANARY_ID}.py").unlink()  # run mode without the file uses the pin
    with pytest.raises(NotApprovedError, match="the pinned code abababab is not approved for this idea"):
        world.resolve(coded_spec(CANARY_ID, pin=unlisted))
    nothing_happened(world, before)


def test_g7_the_archive_is_missing(world: World, before: dict) -> None:
    source = canary_world(world)
    sha = world.approve_both(CANARY_ID, source)
    (world.approvals / "code" / f"{sha}.py").unlink()
    with pytest.raises(RecordError) as info:
        world.resolve(coded_spec(CANARY_ID))
    assert str(info.value) == f"the archived code {sha[:8]} is missing"
    nothing_happened(world, before)


def test_g8_the_archive_bytes_do_not_match_their_hash(world: World, before: dict) -> None:
    source = canary_world(world)
    sha = world.approve_both(CANARY_ID, source)
    (world.approvals / "code" / f"{sha}.py").write_bytes(source + b"# edited after the approval\n")
    with pytest.raises(RecordError) as info:
        world.resolve(coded_spec(CANARY_ID))
    assert str(info.value) == f"the archived code {sha[:8]} does not match its hash; the archive was changed"
    nothing_happened(world, before)


def test_g9_the_static_check_runs_again_on_the_archive(world: World, before: dict, monkeypatch) -> None:
    # The real static check refuses the canary (it uses open and os). Approving it is refused ...
    monkeypatch.undo()
    monkeypatch.setenv("CANARY_MARKER", str(world.marker))
    source = canary_world(world)
    world.approve_idea(CANARY_ID)
    with pytest.raises(StaticCheckError):
        world.approve_code(CANARY_ID, source)
    assert not (world.approvals / "code").exists()
    # ... and so is code that was forged into the archive and the record without the check.
    sha = sha_of(source)
    entry = IdeaApproval(
        idea_sha256(CANARY_ID, "B"), "2026-11-02T10:00:00Z", (CodeApproval(sha, "2026-11-02T11:00:00Z"),)
    )
    (world.approvals / "code").mkdir(parents=True)
    (world.approvals / "code" / f"{sha}.py").write_bytes(source)
    (world.approvals / f"{CANARY_ID}.json").write_bytes(render_record(ApprovalRecord(CANARY_ID, (entry,))))
    with pytest.raises(StaticCheckError) as info:
        world.resolve(coded_spec(CANARY_ID))
    assert "import of 'os' is not allowed [import]" in str(info.value)
    assert "the name 'open' is not allowed [banned-name]" in str(info.value)
    nothing_happened(world, before)


def test_g10_the_file_has_a_hash_that_was_not_approved(world: World, before: dict) -> None:
    world.put_file(CANARY_ID, canary_source(factor="0.0"))
    world.approve_both(CANARY_ID, canary_source(factor="0.0"))
    edited = canary_source(factor="0.5")
    world.put_file(CANARY_ID, edited)  # edited after the approval, not approved again
    with pytest.raises(NotApprovedError) as info:
        world.resolve(coded_spec(CANARY_ID))
    assert str(info.value) == f"code not approved: the file has sha {sha_of(edited)[:8]}"
    nothing_happened(world, before)


# --- the marker appears only when the gate lets the code load ---


def test_the_marker_is_written_only_after_the_idea_and_the_code_are_approved_and_the_spec_is_resolved(
    world: World, before: dict, tmp_path
) -> None:
    source = canary_world(world)
    provider = FakeProvider(symbols=("AAA", "BBB"))
    spec = coded_spec(CANARY_ID)
    spec_file = tmp_path / "canary.yaml"
    spec_file.write_text(yaml.safe_dump(spec.to_dict(), sort_keys=False), encoding="utf-8")

    # Nothing here loads code: reading the spec, validating it, evaluating it, running it, asking the gate too early.
    loaded = load_spec(spec_file)
    assert loaded.signal.coded is not None
    run_cli(["validate", str(spec_file)])  # exit code: see tests/test_cli_validate.py; here only that nothing loads
    with pytest.raises(UnknownSignalError, match="is not resolved"):
        evaluate(loaded, provider)
    outcome = run_cli(
        ["run", str(spec_file), "--runs-dir", str(tmp_path / "runs"), "--reports-dir", str(tmp_path / "reports")],
        provider=provider,
    )
    assert outcome.code != 0 and provider.calls == []
    with pytest.raises(NotApprovedError, match="there is no approval record"):
        world.resolve(loaded)
    nothing_happened(world, before)

    world.approve_idea(CANARY_ID)  # the idea alone loads nothing
    with pytest.raises(NotApprovedError, match="code not approved: the file has sha"):
        world.resolve(loaded)
    nothing_happened(world, before)

    sha = world.approve_code(CANARY_ID, source)  # approving the code archives it, it does not run it
    assert (world.approvals / "code" / f"{sha}.py").read_bytes() == source
    nothing_happened(world, before)

    resolved = world.resolve(loaded)  # now, and only now, the code is loaded
    assert world.marker_lines() == ["imported 0.0"]
    assert resolved.signal.coded is not None and resolved.signal.coded.code_sha256 == sha
    assert SIGNALS.get(CANARY_ID).sha256 == sha
    assert coded_modules() == []  # it ran in a module that is not in sys.modules

    result = run_backtest(resolved, provider)  # running it does not load it again
    assert len(result.equity) > 0 and world.marker_lines() == ["imported 0.0"]
    assert evaluate(resolved, provider) is not None
    assert world.marker_lines() == ["imported 0.0"]


def test_the_real_static_check_refuses_the_canary_at_the_approval(world: World, monkeypatch) -> None:
    monkeypatch.undo()
    monkeypatch.setenv("CANARY_MARKER", str(world.marker))
    world.approve_idea(CANARY_ID)
    with pytest.raises(StaticCheckError) as info:
        world.approve_code(CANARY_ID, canary_source())
    assert str(info.value).splitlines()[0] == "the signal source breaks 3 rules of the static check:"
    assert world.marker_lines() == [] and not (world.approvals / "code").exists()


def test_at_is_used_for_the_clock_of_the_helpers() -> None:
    assert at(10).isoformat() == "2026-11-02T10:00:00+00:00"
