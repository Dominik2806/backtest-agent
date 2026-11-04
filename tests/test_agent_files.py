"""The two agent files (``.claude/agents``) are tied to the hook, to settings.json and to the real ``bt`` parser.

Nothing here starts Claude Code: the tests read the files, run the hook line that a file carries (``bash -c``) and ask
the hook's own functions what it would do. Whether Claude Code honours the frontmatter (``shell``, ``onFailure``, a
missing matcher, the ``agent_type``) is a claim of its documentation and is not tested (docs/agents.md). The commands
that a prompt may name are not listed a second time: they are checked with ``hook.check_bash``.
"""

import contextlib
import io
import json
import re
import shlex
from pathlib import Path

import pytest

from backtest_agent.cli.parser import build_parser
from restrict_writes_helpers import (
    AGENTS_DIR,
    ROOT,
    agent_file,
    derived_command,
    frontmatter_command,
    load_hook,
    payload,
    run_command,
    settings_command,
)
from test_agent_deny_rules import Matcher, rules_of

hook = load_hook()
NAMES = ["strategy-architect", "signal-coder"]
SETTINGS = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
SETTINGS_HANDLER = SETTINGS["hooks"]["PreToolUse"][0]["hooks"][0]
SETTINGS_MATCHER = set(SETTINGS["hooks"]["PreToolUse"][0]["matcher"].split("|"))
PLACEHOLDERS = {"<name>": "trend", "<id>": "hold_a", "<8 hex>": "3f9a1c2e"}
INSTRUCTIONS = "These are instructions, not enforcement: a hook limits what you write and run."
SENTENCE_A = (
    "If `uv run bt signal check strategies/drafts/<name>.yaml` is refused, finish anyway: keep the files, run "
    "`uv run bt validate strategies/drafts/<name>.yaml`, and say in your final message that the check was refused and "
    "that `uv run bt signal check strategies/drafts/<name>.yaml` is a step for the person to run after reading the "
    "code."
)
SENTENCE_B = (
    "After any refusal, do not try another spelling of the command or another way round it, and do not advise "
    "switching the permission mode."
)


def flat(text: str) -> str:
    return " ".join(text.split())


def section(body: str, title: str) -> str:
    for part in re.split(r"(?m)^## ", body)[1:]:
        if part.startswith(title):
            return part
    raise AssertionError(f"no section {title!r}")


def block_lines(body: str, title: str) -> list[str]:
    fence = re.search(r"```text\n(.*?)```", section(body, title), flags=re.DOTALL)
    assert fence, title
    return [line.strip() for line in fence[1].splitlines() if line.strip()]


def concrete(line: str) -> str:
    for placeholder, value in PLACEHOLDERS.items():
        line = line.replace(placeholder, value)
    return line


def without_fences(body: str) -> str:
    return re.sub(r"```.*?```", "", body, flags=re.DOTALL)


# --- the folder and the frontmatter ---


def test_agents_folder_has_exactly_the_two_files() -> None:
    assert sorted(path.name for path in AGENTS_DIR.iterdir()) == ["signal-coder.md", "strategy-architect.md"]


@pytest.mark.parametrize("name", NAMES)
def test_tools_are_exactly_read_glob_grep_write_edit_bash(name: str) -> None:
    tools = agent_file(name)[0]["tools"]
    assert isinstance(tools, str) and [tool.strip() for tool in tools.split(",")] == [
        "Read",
        "Glob",
        "Grep",
        "Write",
        "Edit",
        "Bash",
    ]


@pytest.mark.parametrize("name", NAMES)
def test_frontmatter_keys_are_name_description_tools_hooks(name: str) -> None:
    frontmatter = agent_file(name)[0]
    assert set(frontmatter) == {"name", "description", "tools", "hooks"}
    for key in ("permissionMode", "mcpServers", "disallowedTools"):
        assert key not in frontmatter
    description = frontmatter["description"]
    assert isinstance(description, str) and "\n" not in description.strip() and "proactively" not in description.lower()


@pytest.mark.parametrize("name", NAMES)
def test_hook_entry_has_no_matcher_no_if_one_handler(name: str) -> None:
    hooks = agent_file(name)[0]["hooks"]
    assert list(hooks) == ["PreToolUse"]
    (group,) = hooks["PreToolUse"]
    assert set(group) == {"hooks"}  # no matcher: the group fires on every tool call of the agent
    (handler,) = group["hooks"]
    assert "if" not in handler and "matcher" not in handler


@pytest.mark.parametrize("name", NAMES)
def test_handler_equals_settings_handler_except_the_argument(name: str) -> None:
    (group,) = agent_file(name)[0]["hooks"]["PreToolUse"]
    (handler,) = group["hooks"]
    expected = {key: value for key, value in SETTINGS_HANDLER.items() if key != "command"}
    assert {key: value for key, value in handler.items() if key != "command"} == expected


@pytest.mark.parametrize("name", NAMES)
def test_command_is_settings_script_path_plus_agent_name(name: str) -> None:
    assert frontmatter_command(name) == derived_command(name)


@pytest.mark.parametrize("name", NAMES)
def test_file_name_equals_name_equals_argument(name: str) -> None:
    frontmatter = agent_file(name)[0]
    assert (AGENTS_DIR / f"{name}.md").is_file()
    assert frontmatter["name"] == name == frontmatter["hooks"]["PreToolUse"][0]["hooks"][0]["command"].split()[-1]
    assert name in hook.AGENTS


# --- what the line of each file does when a shell runs it ---


@pytest.fixture(params=["project root", "another directory"])
def cwd(request, tmp_path: Path) -> Path:
    return ROOT if request.param == "project root" else tmp_path


@pytest.mark.parametrize("name", NAMES)
def test_each_file_own_command_blocks_and_allows_through_bash_c(name: str, cwd: Path) -> None:
    folder = "drafts/x.yaml" if name == "strategy-architect" else "signals/x.py"
    allowed = {"file_path": str(ROOT / "strategies" / folder), "content": "x"}
    forbidden = {"file_path": str(ROOT / "src" / "x.py"), "content": "x"}
    ok = run_command(frontmatter_command(name), json.dumps(payload("Write", **allowed)), cwd=cwd)
    assert (ok.returncode, ok.stdout) == (0, b""), ok.stderr
    refused = run_command(frontmatter_command(name), json.dumps(payload("Write", **forbidden)), cwd=cwd)
    assert refused.returncode == 2 and refused.stderr.startswith(b"restrict_writes: blocked: ")


# Tool names from the Claude Code documentation (sub-agents.md and tools-reference.md) that a subagent might be given.
DOCUMENTED_TOOL_NAMES = [
    "ToolSearch",
    "TodoWrite",
    "Skill",
    "LSP",
    "Monitor",
    "TaskStop",
    "SendMessage",
    "Artifact",
    "EnterWorktree",
    "ExitWorktree",
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskUpdate",
    "Agent",
    "Task",
    "WebFetch",
    "WebSearch",
    "AskUserQuestion",
    "mcp__github__create_issue",
]


@pytest.mark.parametrize("name", NAMES)
def test_matcherless_entry_gets_refused_tool_names(name: str, tmp_path: Path) -> None:
    for tool in DOCUMENTED_TOOL_NAMES:
        with pytest.raises(hook.Refused, match="may not use"):
            hook.decide(name, payload(tool, command="bt validate strategies/drafts/x.yaml"), ROOT)
    done = run_command(frontmatter_command(name), json.dumps(payload("ToolSearch", query="x")), cwd=tmp_path)
    assert done.returncode == 2 and b"ToolSearch" in done.stderr and b"docs/agents.md" in done.stderr


# The internal tool by which a subagent returns its final message: observed once (Claude Code 2.1.318), not documented.
# The payload has the shape of the observed one (agent_type, agent_id, permission_mode "auto", a "message" field).
HANDBACK = {"message": "I wrote strategies/drafts/x.yaml and bt validate accepts it."}


def handback_payload(name: str) -> dict:
    found = payload("SubagentHandback", name, mode="auto", **HANDBACK)
    found["agent_id"] = "a0000000000000000"
    return found


@pytest.mark.parametrize("name", NAMES)
def test_subagent_handback_is_allowed_in_process_and_through_the_files_own_line(name: str, cwd: Path) -> None:
    hook.decide(name, handback_payload(name), ROOT)  # raises Refused if the hook would refuse it
    done = run_command(frontmatter_command(name), json.dumps(handback_payload(name)), cwd=cwd)
    assert (done.returncode, done.stdout, done.stderr) == (0, b"", b"")


@pytest.mark.parametrize("name", NAMES)
def test_a_second_internal_name_is_still_refused_with_the_tool_named(name: str, cwd: Path) -> None:
    other = payload("SendMessage", name, mode="auto", message="x")
    with pytest.raises(hook.Refused, match="SendMessage.*docs/agents.md"):
        hook.decide(name, other, ROOT)
    done = run_command(frontmatter_command(name), json.dumps(other), cwd=cwd)
    assert done.returncode == 2 and b"SendMessage" in done.stderr and b"docs/agents.md" in done.stderr


def test_subagent_handback_is_not_in_the_settings_matcher() -> None:
    """The settings entry is not widened: it never saw the tool, and the frontmatter copy allows it."""
    assert "SubagentHandback" not in SETTINGS_MATCHER
    assert SETTINGS_MATCHER == {"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "PowerShell"}
    assert hook.HANDBACK_TOOL == "SubagentHandback" and hook.HANDBACK_TOOL not in hook.READ_TOOLS


def test_an_unknown_agent_name_gets_no_allowance_for_the_handback(tmp_path: Path) -> None:
    data = json.dumps(handback_payload("someone-else"))
    env = {"CLAUDE_PROJECT_DIR": str(ROOT)}
    assert hook.run(["someone-else"], data, env) == 2  # an argument the hook does not know
    done = run_command(derived_command("someone-else"), data, cwd=tmp_path)
    assert done.returncode == 2 and b"unknown agent" in done.stderr
    # the settings entry (no argument) gives no decision to another agent_type, as before: it is not an allowance
    assert hook.run([], data, env) == 0


# --- the prompts ---


@pytest.mark.parametrize("name", NAMES)
def test_prompts_name_only_commands_the_hook_allows(name: str) -> None:
    lines = block_lines(agent_file(name)[1], "Commands you may run")
    assert lines
    for line in lines:
        hook.check_bash(name, concrete(line), "default")  # raises Refused if the hook would refuse it


def parses(argv: list[str]) -> bool:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            build_parser().parse_args(argv)
        except SystemExit:
            return False
    return True


@pytest.mark.parametrize("name", NAMES)
def test_person_commands_are_refused_for_the_agent_and_parse(name: str) -> None:
    lines = block_lines(agent_file(name)[1], "For the person only")
    assert lines
    for line in lines:
        command = concrete(line)
        with pytest.raises(hook.Refused):
            hook.check_bash(name, command, "default")
        assert Matcher.blocked_by(rules_of("deny"), "Bash", command), command
        words = shlex.split(command)
        assert words[:3] == ["uv", "run", "bt"] and parses(words[3:]), command


@pytest.mark.parametrize("name", NAMES)
def test_every_bt_mention_is_in_one_of_the_two_blocks(name: str) -> None:
    body = agent_file(name)[1]
    known = {
        flat(line) for title in ("Commands you may run", "For the person only") for line in block_lines(body, title)
    }
    mentions = re.findall(r"`((?:uv run )?bt [^`]*)`", without_fences(body))
    assert mentions
    assert [mention for mention in mentions if flat(mention) not in known] == []


@pytest.mark.parametrize("name", NAMES)
def test_prompts_say_instructions_not_enforcement(name: str) -> None:
    assert INSTRUCTIONS in flat(agent_file(name)[1])
    assert "educational tool, not investment advice" in flat(agent_file(name)[1])


@pytest.mark.parametrize("name", NAMES)
def test_prompts_have_no_enforcement_words(name: str) -> None:
    text = flat(agent_file(name)[1]).replace(INSTRUCTIONS, "")
    found = re.findall(
        r"(?i)\b(guarantee[sd]?|impossible|cannot be bypassed|can't be bypassed|unbreakable|prevents?)\b", text
    )
    assert found == []


@pytest.mark.parametrize(("name", "needle"), [("strategy-architect", "--idea"), ("signal-coder", "--code --sha")])
def test_prompts_end_with_next_for_you(name: str, needle: str) -> None:
    last = [paragraph for paragraph in agent_file(name)[1].strip().split("\n\n") if paragraph.strip()][-1]
    assert "Next, for you:" in last and needle in last


def test_coder_prompt_has_sentence_a() -> None:
    assert flat(SENTENCE_A) in flat(agent_file("signal-coder")[1])


@pytest.mark.parametrize("name", NAMES)
def test_both_prompts_have_sentence_b(name: str) -> None:
    assert flat(SENTENCE_B) in flat(agent_file(name)[1])


@pytest.mark.parametrize("name", NAMES)
def test_prompts_give_no_mode_advice(name: str) -> None:
    """The words 'permission mode' and 'switch' occur only inside sentence B, which forbids the advice."""
    rest = flat(agent_file(name)[1]).replace(flat(SENTENCE_B), "").lower()
    assert "permission mode" not in rest and "switch" not in rest and "default mode" not in rest


@pytest.mark.parametrize("name", NAMES)
def test_prompts_stay_short(name: str) -> None:
    assert len(agent_file(name)[1].splitlines()) <= 120


# --- nothing in the files widens what the hook allows ---


def test_agent_files_cannot_widen_the_hook() -> None:
    # (a) the agents the hook knows are exactly the agent files
    assert set(hook.AGENTS) == {path.stem for path in AGENTS_DIR.glob("*.md")}
    # (b) the script path is the same in both files and in settings.json
    paths = {
        re.search(r'"(\$CLAUDE_PROJECT_DIR/[^"]+)"', command)[1]
        for command in (settings_command(), *map(frontmatter_command, NAMES))
    }
    assert paths == {"$CLAUDE_PROJECT_DIR/.claude/hooks/restrict_writes.py"} and len(paths) == 1
    # (c) every tool that the settings matcher or a file can route to the hook is refused with the worst call of
    #     its kind, except the three read tools, which the documents call unrestricted
    reachable = (
        SETTINGS_MATCHER
        | {tool.strip() for name in NAMES for tool in agent_file(name)[0]["tools"].split(",")}
        | {"SubagentHandback"}
    )
    worst = {
        "file_path": "src/x.py",
        "content": "x",
        "command": "python -m backtest_agent approve strategies/drafts/x.yaml --idea",
        "notebook_path": "n.ipynb",
    }
    passes = set()
    for name in NAMES:
        for tool in reachable:
            try:
                hook.decide(name, payload(tool, **worst), ROOT)
            except hook.Refused:
                continue
            passes.add(tool)
    #     SubagentHandback is the one internal tool the hook allows besides the read tools: it is how a subagent returns
    #     its message (observed once, not documented); it writes and runs nothing. It is not in the settings matcher.
    assert passes == {"Read", "Glob", "Grep", "SubagentHandback"}
    # (d) every tool a file lists, apart from the read tools, is matched by the settings entry and known to the hook
    for name in NAMES:
        listed = {tool.strip() for tool in agent_file(name)[0]["tools"].split(",")}
        assert listed - set(hook.READ_TOOLS) <= SETTINGS_MATCHER
        assert "SubagentHandback" not in listed
        assert listed <= set(hook.READ_TOOLS) | set(hook.WRITE_TOOLS) | {"Bash"}
