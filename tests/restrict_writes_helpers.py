"""Helpers for the tests of ``.claude/hooks/restrict_writes.py``: load the script, build payloads, run it, find bash.

They build inputs and run the script; no expected value of a test is computed here.
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".claude" / "hooks" / "restrict_writes.py"
SETTINGS = ROOT / ".claude" / "settings.json"
ARCHITECT = "strategy-architect"
CODER = "signal-coder"


def load_hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location("restrict_writes_under_test", HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MISSING = object()  # a payload without a permission_mode (as against the value None)


def payload(tool: str, agent: str | None = None, *, mode: object = "default", **tool_input: object) -> dict:
    """The JSON a PreToolUse hook receives (the fields the script reads); every call has a permission_mode."""
    found: dict = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}
    if agent is not None:
        found["agent_type"] = agent
    if mode is not MISSING:
        found["permission_mode"] = mode
    return found


def run_script(args: list[str], stdin: str | bytes, *, env: dict[str, str] | None = None, script: Path = HOOK):
    """Run the script itself with the interpreter of the tests (isolated mode, like the real command line)."""
    data = stdin if isinstance(stdin, bytes) else stdin.encode("utf-8")
    return subprocess.run(
        [sys.executable, "-I", str(script), *args],
        input=data,
        capture_output=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT)} if env is None else env,
        timeout=60,
    )


def settings_command() -> str:
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    (entry,) = settings["hooks"]["PreToolUse"]
    (hook,) = entry["hooks"]
    return hook["command"]


AGENTS_DIR = ROOT / ".claude" / "agents"


def split_agent_file(text: str) -> tuple[dict, str]:
    """(frontmatter, body) of an agent file: a YAML block between two lines of three dashes, then the prompt."""
    text = text.replace("\r\n", "\n")
    assert text.startswith("---\n"), "an agent file starts with its frontmatter"
    head, body = text[4:].split("\n---\n", 1)
    return yaml.safe_load(head), body


def agent_file(name: str, root: Path = ROOT) -> tuple[dict, str]:
    return split_agent_file((root / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8"))


def frontmatter_command(agent: str, root: Path = ROOT) -> str:
    """The command line that the agent's OWN file carries (read from the file, not built from a template)."""
    frontmatter, _ = agent_file(agent, root)
    (group,) = frontmatter["hooks"]["PreToolUse"]
    (handler,) = group["hooks"]
    return handler["command"]


def derived_command(agent: str) -> str:
    """The command line that the settings entry implies for ``agent``: its uv command and script path, plus the name."""
    found = re.search(r'uv run .*?restrict_writes\.py"', settings_command())
    assert found, "the settings line holds the uv command"
    return f"{found[0]} {agent}"


def git_bash() -> str:
    """Git Bash, the shell Claude Code uses on Windows (never the bash.exe of WSL in System32)."""
    if os.name == "nt":
        git = shutil.which("git")
        if git:
            for parent in Path(git).resolve().parents:
                for candidate in (parent / "bin" / "bash.exe", parent / "usr" / "bin" / "bash.exe"):
                    if candidate.exists():
                        return str(candidate)
    found = shutil.which("bash")
    assert found, "bash is needed to run the command line of the hook"
    return found


def run_command(
    command: str,
    stdin: str | bytes,
    *,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
    unset: tuple[str, ...] = (),
):
    """Run a hook command line the way Claude Code does (shell form: the shell gets the string), from ``cwd``.

    CLAUDE_PROJECT_DIR is the project (a Windows path on Windows) unless it is named in ``unset``.
    """
    assert shutil.which("uv"), "uv is needed to run the command line of the hook"
    data = stdin if isinstance(stdin, bytes) else stdin.encode("utf-8")
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT), **(extra_env or {})}
    for name in unset:
        env.pop(name, None)
    return subprocess.run([git_bash(), "-c", command], input=data, capture_output=True, env=env, cwd=cwd, timeout=120)


def make_dir_link(link: Path, target: Path) -> None:
    """A directory symlink, or a junction on Windows without the privilege; skip the test if neither can be made."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except OSError:
        if os.name != "nt":
            pytest.skip("cannot create a symlink here")
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    if result.returncode != 0:
        pytest.skip("cannot create a junction here")
