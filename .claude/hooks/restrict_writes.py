"""PreToolUse hook: what the agents strategy-architect and signal-coder may write and run (ADR 0019, docs/agents.md).

A fence, not a boundary. It reads the JSON that Claude Code sends on stdin and either exits 0 without printing
anything (no decision: the normal permission flow goes on, so the deny and ask rules of settings.json still apply) or
exits 2 with the reason on stderr (the call is blocked). **It never prints a permissionDecision**: an "allow" must
not be able to skip the ask rule for ``bt signal check``. Any error of the script itself is exit 2; a script that
cannot start at all exits 1 or 127, which Claude Code lets through unless the entry has ``"onFailure": "block"``.

Two ways to call it, the same script:

* ``restrict_writes.py`` (the entry of ``.claude/settings.json``): the agent is the ``agent_type`` of the payload.
  A call without ``agent_type``, or of another agent, is the main session or someone else's: exit 0.
* ``restrict_writes.py <agent>`` (the entry in the frontmatter of that agent): the agent is the argument; an
  ``agent_type`` in the payload that differs from it is refused.

What an agent may do: Read, Glob and Grep are not restricted (no objection); Write, Edit and MultiEdit only in the
folder of the agent; Bash only the exact commands of ``check_bash``; every other tool name is refused. The signal coder
may run ``bt signal check`` only when ``permission_mode`` of the call is ``"default"``.

Standard library only, and nothing is imported from ``backtest_agent``: tests/test_restrict_writes.py compares the id
rules below with the project's own (``coded_id_problem``) on a table, and tests/test_agents_docs.py checks the imports.
"""

import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

ARCHITECT = "strategy-architect"
CODER = "signal-coder"
AGENTS = (ARCHITECT, CODER)

BUILTIN_SIGNAL_IDS = frozenset({"buy_and_hold", "momentum_12_1", "sma_crossover"})
DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"} | {f"com{n}" for n in range(1, 10)} | {f"lpt{n}" for n in range(1, 10)}
)
MAX_ID_LENGTH = 64

READ_TOOLS = ("Read", "Glob", "Grep")
WRITE_TOOLS = ("Write", "Edit", "MultiEdit")
FOLDER = {ARCHITECT: ("strategies", "drafts"), CODER: ("strategies", "signals")}
BASH_CHARACTERS = re.compile(r"[A-Za-z0-9_./ -]+")  # an allowlist: no quote, glob, redirect, pipe, $ or backslash
SPEC_PATH = re.compile(r"strategies/(?P<folder>drafts|examples)/(?P<name>[a-z0-9][a-z0-9_-]{0,63})\.yaml")
DRIVE_RELATIVE = re.compile(r"[A-Za-z]:(?![\\/])")
DRIVE = re.compile(r"[A-Za-z]:")
MISSING = object()  # a payload without the key, as against a key with the value None


class Refused(Exception):
    """The reason a call is blocked."""


def coded_id_ok(signal_id: str) -> bool:
    """The id rules of a coded signal (``spec/coded_spec.py: coded_id_problem``), repeated here on purpose."""
    return (
        re.fullmatch(r"[a-z][a-z0-9_]*", signal_id) is not None
        and len(signal_id) <= MAX_ID_LENGTH
        and signal_id not in BUILTIN_SIGNAL_IDS
        and signal_id not in DEVICE_NAMES
    )


def name_ok(agent: str, name: str) -> bool:
    """May ``agent`` write a file called ``name`` in its folder?"""
    if agent == ARCHITECT:
        found = re.fullmatch(r"([a-z0-9][a-z0-9_-]{0,63})\.yaml", name)
        return found is not None and found[1] not in DEVICE_NAMES
    found = re.fullmatch(r"([a-z][a-z0-9_]*)(?:\.py|\.cases\.yaml)", name)
    return found is not None and coded_id_ok(found[1])


def check_text_of_path(text: str) -> None:
    """The refusals that need only the text of a path, wherever the project is (they hold on every operating system)."""
    if text.startswith(("\\\\", "//")):
        raise Refused("UNC and device paths are refused")
    if "\0" in text or re.search(r'[<>"|?*]', text):
        raise Refused("the path has a character that no allowed file name has")
    if DRIVE_RELATIVE.match(text):
        raise Refused("a path relative to a drive is refused")
    rest = text[2:] if DRIVE.match(text) else text
    if ":" in rest:
        raise Refused("a colon in a path (an NTFS stream) is refused")
    if ".." in re.split(r"[\\/]+", text):
        raise Refused("'..' in a path is refused")


def below_project(path: Path, project: Path) -> list[str]:
    """The components of ``path`` under the project directory (all of them if it is not under it)."""
    same = os.path.normcase
    root = [same(part) for part in project.parts]
    parts = list(path.parts)
    return parts[len(root) :] if [same(part) for part in parts[: len(root)]] == root else parts


def check_components(parts: Sequence[str]) -> None:
    """The refusals for the components below the project directory; the directory itself may have a short name."""
    for part in re.split(r"[\\/]+", "/".join(parts)):
        if part not in ("", ".") and part.endswith((".", " ")):
            raise Refused("a path component ends with a dot or a space")
        if re.search(r"~[0-9]", part):
            raise Refused("an 8.3 short name (NAME~1) is refused")


def check_path(agent: str, raw: object, project: Path) -> None:
    if not isinstance(raw, str) or not raw:
        raise Refused("the call has no file path")
    check_text_of_path(raw)
    path = Path(raw)
    if not path.is_absolute():
        path = project / path
    check_components(below_project(path, project))
    folder = Path(os.path.realpath(project)).joinpath(*FOLDER[agent])
    if not name_ok(agent, path.name):
        raise Refused(f"{agent} may not write a file called {path.name!r} (see docs/agents.md)")
    same = os.path.normcase
    if same(os.path.realpath(path.parent)) != same(str(folder)):
        raise Refused(f"{agent} writes only in {'/'.join(FOLDER[agent])}")
    if same(os.path.realpath(path)) != same(str(folder / path.name)):
        raise Refused("the file is a link to somewhere else")


def spec_ok(agent: str, spec: str) -> bool:
    found = SPEC_PATH.fullmatch(spec)
    if found is None or found["name"] in DEVICE_NAMES:
        return False
    return found["folder"] == "drafts" or agent == CODER  # the architect reads its drafts, the coder also the examples


def check_mode(mode: object) -> None:
    """``bt signal check`` of the coder: only in the default permission mode of the session."""
    where = "the signal coder may run bt signal check only in the default permission mode"
    if mode is MISSING:
        raise Refused(f"the call has no permission_mode: {where}")
    if not isinstance(mode, str):
        raise Refused(f"permission_mode is not text: {where}")
    if mode != "default":
        raise Refused(f"permission_mode is {ascii(mode[:40])}: {where}; switch the session to the default mode")


def check_bash(agent: str, command: object, mode: object) -> None:
    if not isinstance(command, str) or not command:
        raise Refused("the call has no command")
    if "\\" in command:
        raise Refused("a backslash in a command is refused; write paths with forward slashes")
    if BASH_CHARACTERS.fullmatch(command) is None:
        raise Refused("the command has a character outside letters, digits, _ . / - and single spaces")
    words = command.split(" ")
    if "" in words:
        raise Refused("the command has a leading, trailing or double space")
    if words[:2] == ["uv", "run"]:
        words = words[2:]
    if words[:1] != ["bt"]:
        raise Refused("only 'bt validate' and 'bt signal check' may be run (also as 'uv run bt ...')")
    rest = words[1:]
    if len(rest) == 2 and rest[0] == "validate" and spec_ok(agent, rest[1]):
        return
    if agent == CODER and rest[:2] == ["signal", "check"] and len(rest) in (3, 5) and spec_ok(agent, rest[2]):
        if len(rest) == 3 or rest[3:] == ["--strategies-dir", "strategies/signals"]:
            check_mode(mode)
            return
    raise Refused(f"{agent} may not run this command")


def decide(agent: str, payload: Mapping[str, object], project: Path) -> None:
    """Raise ``Refused`` if ``agent`` may not make this tool call; return None if the hook has no objection."""
    tool, tool_input = payload.get("tool_name"), payload.get("tool_input")
    if not isinstance(tool, str) or not isinstance(tool_input, dict):
        raise Refused("the call has no tool_name or tool_input")
    if tool in READ_TOOLS:
        return
    if tool in WRITE_TOOLS:
        check_path(agent, tool_input.get("file_path"), project)
    elif tool == "Bash":
        check_bash(agent, tool_input.get("command"), payload.get("permission_mode", MISSING))
    elif tool in ("NotebookEdit", "PowerShell"):
        raise Refused(f"{agent} may not use {tool}")
    else:
        raise Refused(f"{agent} may not use {tool}: the hook does not know it")


def say(text: str) -> None:
    """One line on stderr, ASCII only (a file name with another character is shown escaped): printing cannot fail."""
    sys.stderr.write(text.encode("ascii", "backslashreplace").decode("ascii") + chr(10))


def run(argv: Sequence[str], raw: str, env: Mapping[str, str]) -> int:
    """The whole hook: 0 for no objection (nothing printed), 2 with the reason on stderr for a block."""
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise Refused("stdin is not a JSON object")
        if len(argv) > 1:
            raise Refused("at most one argument (the agent) is expected")
        agent_type = payload.get("agent_type")
        if not argv:  # the entry of settings.json: decide by the agent_type of the call
            if agent_type not in AGENTS:
                return 0
            agent = agent_type
        else:
            agent = argv[0]
            if agent not in AGENTS:
                raise Refused(f"unknown agent {agent!r}")
            if agent_type is not None and agent_type != agent:
                raise Refused(f"the call is of {agent_type!r}, this entry is for {agent!r}")
        project_dir = env.get("CLAUDE_PROJECT_DIR") or payload.get("cwd")
        if not isinstance(project_dir, str) or not project_dir:
            raise Refused("no project directory (CLAUDE_PROJECT_DIR or cwd)")
        decide(agent, payload, Path(project_dir))
        return 0
    except Refused as reason:
        say(f"restrict_writes: blocked: {reason}")
        return 2
    except Exception as error:  # fail closed: a hook that breaks must not let a call through
        say(f"restrict_writes: blocked: the hook failed ({type(error).__name__}: {error})")
        return 2


def main() -> int:
    try:
        data = sys.stdin.buffer.read()  # bytes: the encoding of the console is not asked
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            say(f"restrict_writes: blocked: stdin is not valid UTF-8 (byte {error.start})")
            return 2
        return run(sys.argv[1:], text, os.environ)
    except BaseException as error:  # fail closed, also for an interrupt or a broken stream
        try:
            say(f"restrict_writes: blocked: the hook failed ({type(error).__name__})")
        except BaseException:
            pass
        return 2


if __name__ == "__main__":
    sys.exit(main())
