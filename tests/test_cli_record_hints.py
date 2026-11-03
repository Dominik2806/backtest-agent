"""A damaged approval record: exit code 5 and ONE hint in every command that reads it; the other record problems.

The commands that read the record themselves (``bt approve``, ``bt validate``) raise ``ApprovalFormatError``; the
commands that pass the gate (``bt run``, ``bt validate --data``, ``bt data fetch``, ``bt report``) get
``RecordError``, which wraps it (``raise RecordError(...) from error``). ``classify`` reads the ``__cause__``: the same
damaged record gets "an approval record is not valid; restore it from version control" in all seven commands. A record
or an archive that is missing keeps "the approvals folder ... has to hold the record and the archived code this run
used", also in a first ``bt run``. What is wrong with the record is in the message line, not in the hint. The
expected texts are literals (docs/cli.md); ``bt signal check`` never reads approvals and is not part of this.
"""

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from backtest_agent.cli.errors import classify
from backtest_agent.coded.errors import ApprovalError, ApprovalFormatError, RecordError
from backtest_agent.coded.loader import clear_checked
from backtest_agent.spec import SIGNALS
from cli_helpers import at, run_cli
from coded_cli_helpers import HOLD_A, SHA_A, approve_all, write_hold_spec
from coded_helpers import coded_spec, registry_and_modules_are_restored  # noqa: F401 - autouse fixture
from report_helpers import world as r3b_world
from runner_helpers import LiteralProvider

GATE_HINT = "the approvals folder (--approvals-dir) has to hold the record and the archived code this run used"
FORMAT_HINT = "an approval record is not valid; restore it from version control (docs/coded-signals.md)"
KEYS = 'must be an object with exactly the keys "ideas", "schema_version" and "signal_id"'

#: How the record is damaged: the bytes of the file (valid JSON of the wrong shape or not JSON at all) and the text
#: after ``hold_a.json: `` in the message line.
CONTENTS = {
    "not-json": (b"{", "is not valid JSON in UTF-8"),
    "not-an-object": (b"[]", KEYS),
    "wrong-keys": (b"{}", KEYS),
    "wrong-version": (b'{"ideas":[],"schema_version":2,"signal_id":"hold_a"}', "schema_version must be 1, got 2"),
}
#: Every command that reads approvals: (arguments, passes the gate); ``bt signal check`` is not among them.
COMMANDS = {
    "bt run": (["run", "spec.yaml"], True),
    "bt validate --data": (["validate", "spec.yaml", "--data"], True),
    "bt data fetch": (["data", "fetch", "spec.yaml"], True),
    "bt report": (["report", "RUN_ID", "--overwrite"], True),
    "bt validate": (["validate", "spec.yaml"], False),
    "bt approve --idea": (["approve", "spec.yaml", "--idea"], False),
    "bt approve --code": (["approve", "spec.yaml", "--code"], False),
}
#: How docs/cli.md names each of them in the table of hints.
DOCUMENTED = {name: name.split(" --idea")[0].split(" --code")[0] for name in COMMANDS}


@pytest.fixture
def run_id(tmp_path: Path, monkeypatch) -> str:
    """A world with a logged coded run, whose registry entry is then forgotten (a new process)."""
    monkeypatch.chdir(tmp_path)
    write_hold_spec(tmp_path)
    approve_all(tmp_path, HOLD_A, "8b0b3234")
    result = run_cli(["run", "spec.yaml"], provider=LiteralProvider(r3b_world()), clock=at(0))
    assert result.code == 0, result.err
    SIGNALS.unregister("hold_a")
    clear_checked()
    return re.search(r"Run:\s+(\S+)", result.out).group(1)


def run(run_id: str, args: list[str]):
    data = LiteralProvider(r3b_world())
    result = run_cli([run_id if a == "RUN_ID" else a for a in args] + ["--debug"], provider=data, clock=at(60))
    return result, data


@pytest.mark.parametrize("command", COMMANDS, ids=list(COMMANDS))
@pytest.mark.parametrize("content", CONTENTS, ids=list(CONTENTS))
def test_the_same_damaged_record_is_exit_5_with_the_same_hint_in_every_command(
    run_id: str, content: str, command: str
) -> None:
    raw, what = CONTENTS[content]
    args, through_the_gate = COMMANDS[command]
    Path("approvals", "hold_a.json").write_bytes(raw)
    result, data = run(run_id, args)
    assert (result.code, result.out) == (5, "")
    assert result.err.splitlines()[-2:] == [f"bt: error: hold_a.json: {what}", f"hint: {FORMAT_HINT}"]
    assert ("RecordError" in result.err) is through_the_gate  # the gate wraps ApprovalFormatError, the others do not
    assert "ApprovalFormatError" in result.err
    assert data.calls == []  # nothing is requested before the record is read


@pytest.mark.parametrize("command", COMMANDS, ids=list(COMMANDS))
def test_a_record_that_cannot_be_read_is_the_same_damaged_record_in_every_command(run_id: str, command: str) -> None:
    Path("approvals", "hold_a.json").unlink()
    Path("approvals", "hold_a.json").mkdir()  # a folder where the file should be
    result, _ = run(run_id, COMMANDS[command][0])
    assert (result.code, result.out) == (5, "")
    error, hint = result.err.splitlines()[-2:]
    assert error.startswith("bt: error: hold_a.json: cannot be read (") and hint == f"hint: {FORMAT_HINT}"


def test_a_first_bt_run_prints_the_same_hint_for_a_damaged_record_and_not_a_hint_about_this_run(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    write_hold_spec(tmp_path)
    Path("approvals").mkdir()
    Path("approvals", "hold_a.json").write_bytes(b"{")
    result = run_cli(["run", "spec.yaml"], provider=LiteralProvider(r3b_world()))
    assert not Path("runs").exists()  # no run exists
    assert result.err.splitlines() == [f"bt: error: hold_a.json: {CONTENTS['not-json'][1]}", f"hint: {FORMAT_HINT}"]


# --- the problems that are not a damaged record keep the hint of the gate ---


def test_a_missing_record_in_stored_mode_keeps_the_gate_hint(run_id: str) -> None:
    Path("approvals", "hold_a.json").unlink()
    result, _ = run(run_id, COMMANDS["bt report"][0])
    assert (result.code, result.out) == (5, "")
    assert result.err.splitlines()[-2:] == [
        "bt: error: the idea of 'hold_a' is not approved: there is no approval record",
        f"hint: {GATE_HINT}",
    ]


@pytest.mark.parametrize(
    "args",
    [["run", "spec.yaml"], ["validate", "spec.yaml", "--data"], ["data", "fetch", "spec.yaml"]],
    ids=lambda a: a[0],
)
def test_a_missing_record_outside_stored_mode_is_exit_8_not_5(run_id: str, args: list[str]) -> None:
    """docs/cli.md: a record that is missing is exit code 5 only in stored mode (bt report)."""
    Path("approvals", "hold_a.json").unlink()
    result, _ = run(run_id, args)
    assert (result.code, result.out) == (8, "")
    assert result.err.splitlines()[-2:] == [
        "bt: error: the idea of 'hold_a' is not approved: there is no approval record",
        "hint: approvals are made with bt approve; see docs/coded-signals.md",
    ]


@pytest.mark.parametrize("command", [name for name, (_, gate) in COMMANDS.items() if gate], ids=lambda n: n)
@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_a_missing_or_changed_archive_keeps_the_gate_hint(run_id: str, command: str, damage: str) -> None:
    archive = Path("approvals", "code", f"{SHA_A}.py")
    if damage == "missing":
        archive.unlink()
        what = "the archived code 8b0b3234 is missing"
    else:
        archive.write_bytes(HOLD_A + b"# edited\n")
        what = "the archived code 8b0b3234 does not match its hash; the archive was changed"
    result, _ = run(run_id, COMMANDS[command][0])
    assert (result.code, result.out) == (5, "")
    assert result.err.splitlines()[-2:] == [f"bt: error: {what}", f"hint: {GATE_HINT}"]


def test_a_missing_archive_in_a_first_bt_run_keeps_the_this_run_used_wording(tmp_path: Path, monkeypatch) -> None:
    """The wording "this run used" stays for a missing archive even when there is no earlier run (docs/cli.md)."""
    monkeypatch.chdir(tmp_path)
    write_hold_spec(tmp_path)
    approve_all(tmp_path, HOLD_A, "8b0b3234")
    Path("approvals", "code", f"{SHA_A}.py").unlink()
    result = run_cli(["run", "spec.yaml"], provider=LiteralProvider(r3b_world()))
    assert not Path("runs").exists()
    assert result.err.splitlines()[-1] == f"hint: {GATE_HINT}"


# --- classify reads the cause, and only the cause ---


def chained(how: str) -> RecordError:
    """A ``RecordError`` over an ``ApprovalFormatError`` as the gate raises it, or in the ways that must not count."""
    inner = ApprovalFormatError("hold_a.json: x")
    try:
        try:
            raise inner
        except ApprovalFormatError as error:
            if how == "cause":
                raise RecordError("x") from error
            if how == "context":
                raise RecordError("x")  # noqa: B904 - on purpose: implicit chaining only (__context__, not __cause__)
            raise RecordError("x") from None
    except RecordError as record_error:
        return record_error


@pytest.mark.parametrize(
    ("build", "hint"),
    [
        (lambda: chained("cause"), FORMAT_HINT),
        (lambda: chained("context"), GATE_HINT),
        (lambda: chained("none"), GATE_HINT),
        (lambda: RecordError("x"), GATE_HINT),
        (lambda: ApprovalFormatError("hold_a.json: x"), FORMAT_HINT),
    ],
    ids=["format error as cause", "format error only as context", "cause suppressed", "no cause", "read directly"],
)
def test_classify_decides_the_hint_by_the_cause_of_a_record_error(build: Callable[[], Exception], hint: str) -> None:
    failure = classify(build())
    assert (failure.code, failure.hint) == (5, hint)


def test_a_record_error_over_another_approval_error_keeps_the_gate_hint() -> None:
    try:
        try:
            raise ApprovalError("the archived code 8b0b3234 is missing")
        except ApprovalError as error:
            raise RecordError("the archived code 8b0b3234 is missing") from error
    except RecordError as record_error:
        assert classify(record_error).hint == GATE_HINT


# --- the gate chains the cause where it wraps a damaged record ---


@pytest.mark.parametrize("stored", [False, True], ids=["run mode", "stored mode"])
def test_the_gate_raises_record_error_from_the_format_error_of_a_damaged_record(world, stored: bool) -> None:
    world.approvals.mkdir(parents=True)
    (world.approvals / "x_signal.json").write_bytes(b"{")
    with pytest.raises(RecordError) as caught:
        world.resolve(coded_spec(pin="0" * 64 if stored else None), stored=stored)
    assert isinstance(caught.value.__cause__, ApprovalFormatError)
