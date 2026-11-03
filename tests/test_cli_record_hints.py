"""An approval record that is not valid: exit code 5 in every command that reads it, and the hint of each command.

The commands that read the record themselves (``bt approve``, ``bt validate``) raise ``ApprovalFormatError`` and get
the hint "an approval record is not valid; restore it from version control"; the commands that pass the gate
(``bt run``, ``bt validate --data``, ``bt data fetch``, ``bt report``) get ``RecordError`` (the gate wraps the
format error) and its hint "the approvals folder ... has to hold the record and the archived code this run used",
also in a first ``bt run``.
What is wrong with the record is in the message line, not in the hint. The expected texts are literals (docs/cli.md).
"""

import re
from pathlib import Path

import pytest

from backtest_agent.coded.loader import clear_checked
from backtest_agent.spec import SIGNALS
from cli_helpers import at, run_cli
from coded_cli_helpers import HOLD_A, approve_all, write_hold_spec
from coded_helpers import registry_and_modules_are_restored  # noqa: F401 - autouse fixture
from report_helpers import world as r3b_world
from runner_helpers import LiteralProvider

GATE_HINT = "the approvals folder (--approvals-dir) has to hold the record and the archived code this run used"
FORMAT_HINT = "an approval record is not valid; restore it from version control (docs/coded-signals.md)"
KEYS = 'must be an object with exactly the keys "ideas", "schema_version" and "signal_id"'

CONTENTS = {
    "not-json": (b"{", "is not valid JSON in UTF-8"),
    "not-an-object": (b"[]", KEYS),
    "wrong-keys": (b"{}", KEYS),
    "wrong-version": (b'{"ideas":[],"schema_version":2,"signal_id":"hold_a"}', "schema_version must be 1, got 2"),
}
COMMANDS = {
    "bt run": (["run", "spec.yaml"], True),
    "bt validate --data": (["validate", "spec.yaml", "--data"], True),
    "bt data fetch": (["data", "fetch", "spec.yaml"], True),
    "bt report": (["report", "RUN_ID", "--overwrite"], True),
    "bt validate": (["validate", "spec.yaml"], False),
    "bt approve --idea": (["approve", "spec.yaml", "--idea"], False),
    "bt approve --code": (["approve", "spec.yaml", "--code"], False),
}


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


@pytest.mark.parametrize("command", COMMANDS, ids=list(COMMANDS))
@pytest.mark.parametrize("content", CONTENTS, ids=list(CONTENTS))
def test_each_invalid_record_is_exit_5_and_each_command_has_its_hint(run_id: str, content: str, command: str) -> None:
    raw, what = CONTENTS[content]
    args, through_the_gate = COMMANDS[command]
    Path("approvals", "hold_a.json").write_bytes(raw)
    data = LiteralProvider(r3b_world())
    result = run_cli([run_id if a == "RUN_ID" else a for a in args] + ["--debug"], provider=data, clock=at(60))
    assert (result.code, result.out) == (5, "")
    lines = result.err.splitlines()
    assert lines[-2:] == [f"bt: error: hold_a.json: {what}", f"hint: {GATE_HINT if through_the_gate else FORMAT_HINT}"]
    assert ("RecordError" in result.err) is through_the_gate  # the gate wraps ApprovalFormatError, the others do not
    assert "ApprovalFormatError" in result.err
    assert data.calls == []  # nothing is requested before the record is read


def test_a_first_bt_run_prints_the_same_gate_hint_although_no_run_exists_yet(tmp_path: Path, monkeypatch) -> None:
    """The hint says "this run used" in a first run too: RECORD_HINT is one constant for every ``RecordError``."""
    monkeypatch.chdir(tmp_path)
    write_hold_spec(tmp_path)
    Path("approvals").mkdir()
    Path("approvals", "hold_a.json").write_bytes(b"{")
    result = run_cli(["run", "spec.yaml"], provider=LiteralProvider(r3b_world()))
    assert not Path("runs").exists()  # no run exists
    assert result.err.splitlines() == [f"bt: error: hold_a.json: {CONTENTS['not-json'][1]}", f"hint: {GATE_HINT}"]
