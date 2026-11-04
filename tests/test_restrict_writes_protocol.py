"""The protocol of the hook: which entry decides what, the exit codes, and that it never prints a decision.

``run(argv, raw, env)`` is called in process for the table; a few cases run the script itself as a subprocess to see the
real exit code and the real streams. Exit 0 prints nothing (so the ask rule of ``bt signal check`` is never skipped),
exit 2 prints the reason on stderr, and the script prints no ``permissionDecision`` ever.
"""

import json
from pathlib import Path

import pytest

from restrict_writes_helpers import ARCHITECT, CODER, HOOK, ROOT, load_hook, payload, run_script

hook = load_hook()
ENV = {"CLAUDE_PROJECT_DIR": str(ROOT)}
ALLOWED = {"file_path": str(ROOT / "strategies" / "signals" / "x.py"), "content": "x"}
FORBIDDEN = {"file_path": str(ROOT / "src" / "x.py"), "content": "x"}


def call(
    argv: list[str], data: object, capsys: pytest.CaptureFixture[str], env: dict | None = None
) -> tuple[int, str, str]:
    raw = data if isinstance(data, str) else json.dumps(data)
    code = hook.run(argv, raw, ENV if env is None else env)
    seen = capsys.readouterr()
    return code, seen.out, seen.err


# --- the entry of settings.json (no argument): the agent is the agent_type of the call ---


@pytest.mark.parametrize("data", [payload("Write", **FORBIDDEN), payload("Bash", command="bt approve x --idea")])
def test_a_call_without_agent_type_is_the_main_session_and_gets_no_decision(capsys, data) -> None:
    assert call([], data, capsys) == (0, "", "")


@pytest.mark.parametrize("other", ["Explore", "general-purpose", "", "signal-coder2", None, 5, ["signal-coder"]])
def test_a_call_of_another_agent_gets_no_decision(capsys, other) -> None:
    data = payload("Write", **FORBIDDEN) | {"agent_type": other}
    assert call([], data, capsys) == (0, "", "")


@pytest.mark.parametrize("agent", [ARCHITECT, CODER])
def test_a_forbidden_call_of_an_agent_is_blocked_by_the_settings_entry(capsys, agent) -> None:
    code, out, err = call([], payload("Write", agent, **FORBIDDEN), capsys)
    assert (code, out) == (2, "") and err.startswith("restrict_writes: blocked: ")


def test_an_allowed_call_of_the_coder_gets_no_decision_and_prints_nothing(capsys) -> None:
    assert call([], payload("Write", CODER, **ALLOWED), capsys) == (0, "", "")
    assert call([], payload("Bash", CODER, command="bt signal check strategies/drafts/x.yaml"), capsys) == (0, "", "")


# --- the entry in the frontmatter (the agent is the argument) ---


@pytest.mark.parametrize("agent", [ARCHITECT, CODER])
def test_the_frontmatter_entry_blocks_without_an_agent_type(capsys, agent) -> None:
    code, out, _ = call([agent], payload("Write", **FORBIDDEN), capsys)
    assert (code, out) == (2, "")


def test_the_frontmatter_entry_allows_what_the_agent_may_do(capsys) -> None:
    assert call([CODER], payload("Write", **ALLOWED), capsys) == (0, "", "")
    draft = {"file_path": str(ROOT / "strategies" / "drafts" / "x.yaml"), "content": "x"}
    assert call([ARCHITECT], payload("Write", **draft), capsys) == (0, "", "")


def test_an_agent_type_that_differs_from_the_argument_is_blocked(capsys) -> None:
    code, _, err = call([CODER], payload("Write", ARCHITECT, **ALLOWED), capsys)
    assert code == 2 and "strategy-architect" in err and "signal-coder" in err


def test_an_unknown_agent_or_too_many_arguments_is_blocked(capsys) -> None:
    assert call(["explorer"], payload("Write", **ALLOWED), capsys)[0] == 2
    assert call([CODER, ARCHITECT], payload("Write", **ALLOWED), capsys)[0] == 2
    assert call([""], payload("Write", **ALLOWED), capsys)[0] == 2


# --- fail closed ---


@pytest.mark.parametrize("raw", ["", "{", "[]", "null", "5", '"x"', "é", "{'a': 1}"])
@pytest.mark.parametrize("argv", [[], [CODER]])
def test_stdin_that_is_not_a_json_object_is_blocked(capsys, raw, argv) -> None:
    code, out, err = call(argv, raw, capsys)
    assert (code, out) == (2, "") and err.startswith("restrict_writes: blocked: ")


def test_no_project_directory_is_blocked_and_the_cwd_of_the_call_is_the_fallback(capsys, tmp_path: Path) -> None:
    data = payload("Write", CODER, **{"file_path": "strategies/signals/x.py", "content": "x"})
    assert call([], data, capsys, env={})[0] == 2
    assert call([], data | {"cwd": str(tmp_path)}, capsys, env={}) == (0, "", "")
    assert call([], data | {"cwd": ""}, capsys, env={})[0] == 2
    assert call([], data | {"cwd": 5}, capsys, env={})[0] == 2


def test_the_environment_wins_over_the_cwd_of_the_call(capsys, tmp_path: Path) -> None:
    data = payload("Write", CODER, **ALLOWED) | {"cwd": str(tmp_path)}  # absolute path of the real project
    assert call([], data, capsys) == (0, "", "")
    elsewhere = {"CLAUDE_PROJECT_DIR": str(tmp_path)}
    assert call([], data, capsys, env=elsewhere)[0] == 2  # the folder is looked up in the project of the environment


def test_an_error_inside_the_decision_is_blocked_not_passed(capsys, monkeypatch) -> None:
    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(hook, "decide", broken)
    code, out, err = call([CODER], payload("Write", **ALLOWED), capsys)
    assert (code, out) == (2, "") and "RuntimeError" in err


# --- the real script, as a subprocess ---


def run(args: list[str], data: object):
    return run_script(args, data if isinstance(data, (str, bytes)) else json.dumps(data))


@pytest.mark.parametrize(
    "data",
    [
        payload("Write", CODER, **ALLOWED),
        payload("Bash", CODER, command="bt validate strategies/drafts/x.yaml"),
        payload("Write", **FORBIDDEN),
    ],
)
def test_the_script_exits_0_and_prints_nothing_when_it_has_no_objection(data) -> None:
    done = run([], data)
    assert (done.returncode, done.stdout, done.stderr) == (0, b"", b"")


def test_the_script_never_prints_a_decision() -> None:
    cases = [
        ([], payload("Write", CODER, **ALLOWED)),
        ([], payload("Write", CODER, **FORBIDDEN)),
        ([CODER], payload("Bash", command="bt signal check strategies/drafts/x.yaml")),
        ([CODER], payload("Bash", command="bt approve x")),
        ([], "not json"),
    ]
    for args, data in cases:
        done = run(args, data)
        assert done.stdout == b"", (args, done.stderr)
        assert b"permissionDecision" not in done.stdout + done.stderr


def test_the_script_exits_2_with_the_reason_on_stderr_when_it_blocks() -> None:
    done = run([], payload("Bash", CODER, command="bt approve strategies/drafts/x.yaml --idea"))
    assert done.returncode == 2 and done.stdout == b""
    assert done.stderr.decode("ascii").startswith("restrict_writes: blocked: ")


def test_a_file_name_with_another_character_is_blocked_and_the_message_stays_ascii() -> None:
    done = run([CODER], payload("Write", file_path="strategies/signals/é.py", content="x"))
    assert done.returncode == 2 and done.stdout == b""
    done.stderr.decode("ascii")  # raises if the hook printed a character the console may not show
    non_ascii = '{"tool_name": "Write", "tool_input": {"file_path": "strategies/signals/é.py"}}'
    assert run_script([CODER], non_ascii.encode("utf-8")).returncode == 2


def test_stdin_that_is_not_utf8_is_blocked() -> None:
    assert run_script([CODER], b'{"tool_name": "\xff\xfe"}').returncode == 2


def test_a_script_that_cannot_run_exits_1_and_that_is_why_the_entry_needs_on_failure_block(tmp_path: Path) -> None:
    """Claude Code lets a call through for any exit code but 2; a broken script exits 1. Only "onFailure": "block"
    turns that into a block (docs/agents.md); the script itself cannot do it."""
    broken = tmp_path / "restrict_writes.py"
    broken.write_text(HOOK.read_text(encoding="utf-8") + "\ndef (:\n", encoding="utf-8")
    done = run_script([CODER], json.dumps(payload("Write", **FORBIDDEN)), script=broken)
    assert done.returncode == 1 and b"SyntaxError" in done.stderr


# --- found by the mutation table ---


def test_an_unknown_agent_argument_is_blocked_also_for_a_command_that_the_grammar_would_allow(capsys) -> None:
    data = payload("Bash", command="bt validate strategies/drafts/x.yaml")
    code, _, err = call(["explorer"], data, capsys)
    assert code == 2 and "unknown agent" in err


def test_a_json_value_that_is_not_an_object_gets_its_own_reason(capsys) -> None:
    for raw in ("[]", "null", "5"):
        code, _, err = call([CODER], raw, capsys)
        assert code == 2 and "not a JSON object" in err


def test_a_file_name_with_another_character_is_shown_escaped_not_dropped() -> None:
    done = run([CODER], payload("Write", file_path="strategies/signals/é.py", content="x"))
    assert done.returncode == 2 and (chr(92) + "xe9").encode() in done.stderr


def test_an_allowed_write_with_content_that_is_not_in_the_console_code_page_is_not_blocked() -> None:
    """Content with characters outside ASCII (UTF-8 bytes) must not make the hook fail. On the development machine
    (stdin is cp1252) this passes with and without the line that sets UTF-8 on stdin, so that line is not covered by
    any test here: the mutation that removes it survives (reported at STOP 2)."""
    data = payload("Write", CODER, **{"file_path": ALLOWED["file_path"], "content": "# Á → €"})
    done = run_script([], json.dumps(data, ensure_ascii=False).encode("utf-8"))
    assert (done.returncode, done.stdout, done.stderr) == (0, b"", b"")


# --- the hook looks at no permission mode (docs/agents.md, "Details of the hook") ---


@pytest.mark.parametrize(
    "mode", ["default", "acceptEdits", "plan", "auto", "bypassPermissions", "dontAsk", None, 5, ""]
)
def test_the_decision_does_not_depend_on_a_permission_mode(capsys, mode) -> None:
    check = payload("Bash", CODER, command="bt signal check strategies/drafts/x.yaml")
    for data, expected in (
        (payload("Write", CODER, **ALLOWED), 0),
        (payload("Write", CODER, **FORBIDDEN), 2),
        (check, 0),
    ):
        assert call([], data | {"permission_mode": mode}, capsys)[0] == expected
