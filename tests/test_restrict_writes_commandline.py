"""The exact command lines of the hook, run the way Claude Code runs them: a shell gets the string.

Test (i) of the plan: the line of the settings entry and the line of the frontmatter copy (an agent name as argument)
are run with ``bash -c`` from the project root and from another directory, and must exit 2 for a forbidden call and 0
(printing nothing) for an allowed one. The shortcut of the settings entry starts ``uv`` only when the input holds the
bare text ``agent_type``; the table below covers the key, no key, spaces and newlines around it, the text inside written
file content, and that the input reaches the script unchanged. Claude Code itself is not started: whether it runs these
lines in this form (``$CLAUDE_PROJECT_DIR``, ``onFailure``) is a claim of its documentation that no test here proves.
"""

import json
from pathlib import Path

import pytest

from restrict_writes_helpers import (
    ARCHITECT,
    CODER,
    ROOT,
    SETTINGS,
    frontmatter_command,
    payload,
    run_command,
    settings_command,
)

ALLOWED = {"file_path": str(ROOT / "strategies" / "signals" / "x.py"), "content": "x"}
FORBIDDEN = {"file_path": str(ROOT / "src" / "x.py"), "content": "x"}
UV_PART = 'uv run --no-project python -I "$CLAUDE_PROJECT_DIR/.claude/hooks/restrict_writes.py"'


@pytest.fixture(params=["project root", "another directory"])
def cwd(request, tmp_path: Path) -> Path:
    return ROOT if request.param == "project root" else tmp_path


def test_the_settings_entry_has_the_shape_the_design_needs() -> None:
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    (entry,) = settings["hooks"]["PreToolUse"]
    tools = entry["matcher"].split("|")
    assert len(tools) == len(set(tools)) and set(tools) == {
        "Write",
        "Edit",
        "MultiEdit",
        "NotebookEdit",
        "Bash",
        "PowerShell",
    }
    (hook,) = entry["hooks"]
    assert hook["type"] == "command" and hook["shell"] == "bash"
    assert hook["onFailure"] == "block"  # a hook that cannot start must block (Claude Code 2.1.295 or later)
    assert isinstance(hook["timeout"], int) and 0 < hook["timeout"] <= 60
    assert UV_PART in hook["command"]
    assert "agent_type" in hook["command"]


# --- the settings entry ---


def test_the_settings_line_blocks_a_forbidden_call_of_an_agent(cwd: Path) -> None:
    for agent in (ARCHITECT, CODER):
        done = run_command(settings_command(), json.dumps(payload("Write", agent, **FORBIDDEN)), cwd=cwd)
        assert done.returncode == 2 and done.stdout == b"", (agent, done.stderr)
        assert done.stderr.startswith(b"restrict_writes: blocked: ")


def test_the_settings_line_has_no_objection_to_an_allowed_call(cwd: Path) -> None:
    done = run_command(settings_command(), json.dumps(payload("Write", CODER, **ALLOWED)), cwd=cwd)
    assert (done.returncode, done.stdout) == (0, b""), done.stderr


def test_the_settings_line_does_not_start_the_hook_for_the_main_session(cwd: Path) -> None:
    done = run_command(settings_command(), json.dumps(payload("Write", **FORBIDDEN)), cwd=cwd)
    assert (done.returncode, done.stdout, done.stderr) == (0, b"", b"")


def test_a_broken_environment_blocks_only_where_the_hook_is_needed(tmp_path: Path) -> None:
    """The ``uv run`` of the line is replaced by a command that does not exist: the shell says 127 for a call of an
    agent, which only ``"onFailure": "block"`` turns into a block, and the main session never gets that far."""
    command = settings_command()
    assert command.count("uv run") == 1
    broken = command.replace("uv run", "no-such-command-for-uv")
    agent = run_command(broken, json.dumps(payload("Write", CODER, **FORBIDDEN)), cwd=tmp_path)
    main = run_command(broken, json.dumps(payload("Write", **FORBIDDEN)), cwd=tmp_path)
    assert (agent.returncode, agent.stdout) == (127, b""), agent.stderr
    assert (main.returncode, main.stdout, main.stderr) == (0, b"", b"")


def test_without_the_project_directory_variable_an_agent_call_exits_2_and_the_main_session_0(tmp_path: Path) -> None:
    """The path of the script is then /.claude/hooks/restrict_writes.py, which does not exist: Python exits 2 for a
    script it cannot open, so the call is blocked even without ``onFailure``."""
    agent = run_command(
        settings_command(), json.dumps(payload("Write", CODER, **ALLOWED)), cwd=tmp_path, unset=("CLAUDE_PROJECT_DIR",)
    )
    main = run_command(
        settings_command(), json.dumps(payload("Write", **ALLOWED)), cwd=tmp_path, unset=("CLAUDE_PROJECT_DIR",)
    )
    assert (agent.returncode, agent.stdout) == (2, b""), agent.stderr
    assert (main.returncode, main.stdout, main.stderr) == (0, b"", b"")


CHECK = {"command": "bt signal check strategies/drafts/x.yaml"}


def test_the_coders_signal_check_through_the_command_lines_needs_the_default_mode(cwd: Path) -> None:
    for line in (settings_command(), frontmatter_command(CODER)):
        allowed = run_command(line, json.dumps(payload("Bash", CODER, **CHECK)), cwd=cwd)
        assert (allowed.returncode, allowed.stdout, allowed.stderr) == (0, b"", b"")
        refused = run_command(line, json.dumps(payload("Bash", CODER, mode="auto", **CHECK)), cwd=cwd)
        assert (refused.returncode, refused.stdout) == (2, b"")
        assert b"default permission mode" in refused.stderr


# --- the frontmatter copy ---


@pytest.mark.parametrize("agent", [ARCHITECT, CODER])
def test_the_frontmatter_line_blocks_a_forbidden_call_without_an_agent_type(agent: str, cwd: Path) -> None:
    done = run_command(frontmatter_command(agent), json.dumps(payload("Write", **FORBIDDEN)), cwd=cwd)
    assert done.returncode == 2 and done.stdout == b"", done.stderr


def test_the_frontmatter_line_has_no_objection_to_an_allowed_call(cwd: Path) -> None:
    done = run_command(frontmatter_command(CODER), json.dumps(payload("Write", **ALLOWED)), cwd=cwd)
    assert (done.returncode, done.stdout) == (0, b""), done.stderr
    draft = {"file_path": str(ROOT / "strategies" / "drafts" / "x.yaml"), "content": "x"}
    done = run_command(frontmatter_command(ARCHITECT), json.dumps(payload("Write", **draft)), cwd=cwd)
    assert (done.returncode, done.stdout) == (0, b""), done.stderr


# --- the shortcut: uv starts only when the input holds the bare text agent_type ---

FORBIDDEN_CALL = payload("Write", CODER, **FORBIDDEN)
PRETTY = json.dumps(FORBIDDEN_CALL, indent=4)
SPACED = json.dumps(FORBIDDEN_CALL).replace('"agent_type":', '"agent_type"   \n  :\n  ')
SHORTCUT_TABLE = [
    ("the key, compact", json.dumps(FORBIDDEN_CALL), 2),
    ("the key, pretty printed with newlines", PRETTY, 2),
    ("spaces and newlines around the key", SPACED, 2),
    ("a trailing newline", json.dumps(FORBIDDEN_CALL) + "\n\n", 2),
    ("no key, a call the agent could not make", json.dumps(payload("Write", **FORBIDDEN)), 0),
    ("no key, empty object", "{}", 0),
    (
        "the text only inside written content (main session)",
        json.dumps(payload("Write", file_path=str(ROOT / "docs" / "x.md"), content="the agent_type field")),
        0,
    ),
    (
        "the text inside content and the key of a forbidden call",
        json.dumps(payload("Write", CODER, file_path=FORBIDDEN["file_path"], content="agent_type agent_type")),
        2,
    ),
]


@pytest.mark.parametrize(("label", "stdin", "expected"), SHORTCUT_TABLE, ids=[row[0] for row in SHORTCUT_TABLE])
def test_the_shortcut_table(label: str, stdin: str, expected: int, tmp_path: Path) -> None:
    done = run_command(settings_command(), stdin, cwd=tmp_path)
    assert done.returncode == expected, (label, done.stderr)
    assert done.stdout == b""


def test_the_input_reaches_the_script_unchanged(tmp_path: Path) -> None:
    """The line is run with the script replaced by a ``cat`` into a file: the bytes must be the bytes that came in."""
    command = settings_command()
    assert UV_PART in command
    out = tmp_path / "seen.bin"
    stub = command.replace(UV_PART, 'cat > "$OUT"')
    data = (
        (json.dumps(FORBIDDEN_CALL, indent=2, ensure_ascii=False) + "\n\n").replace("x.py", "\u00e9.py").encode("utf-8")
    )
    data = data.replace(b"\n", b"\r\n", 2) + b"  \n"
    done = run_command(stub, data, cwd=tmp_path, extra_env={"OUT": str(out)})
    assert done.returncode == 0, done.stderr
    assert out.read_bytes() == data
