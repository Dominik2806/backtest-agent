"""End to end, without a real model: scripted fake agents, the real hook (both lines) and the real ``bt`` (part 4b).

The flow is the one of docs/cli.md ("Example: a coded signal, from approval to run"): the architect writes a draft and
validates it, the coder writes a signal and its examples, validates and checks them, and then **the test plays the
person**: it approves the idea, reads the code (the review, exit 8), approves the code with the sha and runs the
strategy. Every call of an agent goes through the hook in a temp project that holds copies of ``.claude/`` (the real
agent files, ``settings.json`` and the script), as ``bash -c`` lines, and every script ends with a ``SubagentHandback``.
The refusal tests assert the refusal **and** that nothing was created. The numbers of the run are the literals of
docs/cli.md (``coded_cli_helpers.summary``); the sha is a literal computed with ``hashlib`` outside the project.

Not modelled (see ``fake_agents``): the ask rule, the deny rules, the ``tools`` list. What a real Claude Code does
with the hook is in docs/agents.md, "Observations".
"""

import json
import subprocess
from pathlib import Path

import pytest

from cli_helpers import at, run_cli
from coded_cli_helpers import FIRST, HOLD_A, SHA_A, summary
from coded_helpers import registry_and_modules_are_restored  # noqa: F401 - autouse fixture
from fake_agents import (
    CHECK,
    HANDBACK,
    MISSING,
    SPEC,
    VALIDATE,
    Call,
    FakeAgent,
    FakeArchitect,
    FakeCoder,
    Transcript,
    bash,
    kill_tree,
    make_project,
    write,
)
from report_helpers import world
from runner_helpers import LiteralProvider

SHA8 = "8b0b3234"
CONSENT = (
    "bt: executing strategies/signals/hold_a.py (sha 8b0b3234, NOT approved) in this process, with your permissions "
    "and no time or memory limit; the static check is a tripwire, not a sandbox"
)
VALIDATE_OUT = [
    f"OK: {SPEC} is a valid spec",
    "Name:       Buy and hold A",
    "Family:     hold_a",
    "Signal:     coded, idea not approved",
    "Universe:   A",
    "Benchmark:  B",
    "Period:     2024-01-02 to 2024-01-08",
    "Warm-up:    n/a (coded signal, not loaded)",
    "Risk flags: none",
]
APPROVE_SPELLINGS = [
    f"uv run bt approve {SPEC} --idea",
    f"bt approve {SPEC} --code",
    f"python -m backtest_agent approve {SPEC} --code --sha {SHA8}",
]


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = make_project(tmp_path / "project")
    monkeypatch.chdir(root)
    return root


def tree(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


def ended_with_the_handback(transcript: Transcript) -> None:
    """The last call is the handback, and BOTH lines of the hook allowed it."""
    last = transcript.last
    assert last.call.tool == HANDBACK and last.call.tool_input["message"]
    assert (last.settings_code, last.frontmatter_code, last.performed) == (0, 0, True), last.reason
    assert last.text == last.call.tool_input["message"]


def both_lines_refused(record) -> None:
    assert record.refused and (record.settings_code, record.frontmatter_code) == (2, 2), record
    assert record.reason.count("restrict_writes: blocked:") == 2  # one reason from each line


# --- the whole flow ---


def test_from_idea_to_run_with_the_real_hook_and_the_real_bt(project: Path) -> None:
    architect = FakeArchitect(project)
    drafted = architect.draft()
    ended_with_the_handback(drafted)
    assert drafted.commands() == [VALIDATE]
    validated = drafted.of("Bash")[0]
    assert validated.performed and (validated.outcome.code, validated.outcome.err) == (0, "")
    assert validated.outcome.out.splitlines() == VALIDATE_OUT

    coder = FakeCoder(project, HOLD_A, mode="default")
    coded = coder.code()
    ended_with_the_handback(coded)
    assert coded.commands() == [VALIDATE, CHECK]  # the spelling of the prompts, both allowed by the hook
    checked = coded.of("Bash")[1].outcome
    assert checked.code == 0
    assert f"Sha256:     {SHA_A}" in checked.out.splitlines()
    assert "Contract:   ok (frames of 300 rows)" in checked.out.splitlines()
    assert "Cases:      ok (1 case in hold_a.cases.yaml)" in checked.out.splitlines()
    assert checked.err.splitlines() == [CONSENT]
    assert not (project / "approvals").exists()  # an agent approves nothing

    # --- the person: the steps in the wrong order, then in the right one ---
    early = run_cli(["approve", SPEC, "--code", "--sha", SHA8], clock=at(0))
    assert early.code == 8 and not (project / "approvals").exists()
    assert run_cli(["approve", SPEC, "--idea"], clock=at(0)).code == 0
    review = run_cli(["approve", SPEC, "--code"], clock=at(60))
    assert review.code == 8 and f"Sha256:     {SHA_A}" in review.out.splitlines()
    assert review.err.splitlines()[0] == f"bt: error: the code is not approved yet; confirm it with --sha {SHA8}"
    assert tree(project / "approvals") == ["hold_a.json"]  # no archive before the sha
    assert run_cli(["approve", SPEC, "--code", "--sha", SHA8], clock=at(60)).code == 0
    assert tree(project / "approvals") == ["code/" + SHA_A + ".py", "hold_a.json"]
    assert (project / "approvals" / "code" / f"{SHA_A}.py").read_bytes() == HOLD_A
    record = json.loads((project / "approvals" / "hold_a.json").read_text(encoding="utf-8"))
    assert record["signal_id"] == "hold_a" and record["ideas"][0]["code"][0]["sha256"] == SHA_A

    ran = run_cli(["run", SPEC], provider=LiteralProvider(world()), clock=at(0))
    assert (ran.code, ran.err) == (0, "")
    run_id = ran.out.splitlines()[0].removeprefix("Run:        ")
    assert ran.out.splitlines() == summary(run_id, "hold_a", FIRST)


def test_a_brief_changed_after_the_idea_is_not_the_approved_idea(project: Path) -> None:
    FakeArchitect(project).draft()
    FakeCoder(project, HOLD_A).code()
    assert run_cli(["approve", SPEC, "--idea"], clock=at(0)).code == 0
    assert run_cli(["approve", SPEC, "--code", "--sha", SHA8], clock=at(0)).code == 0
    spec = project / SPEC
    spec.write_text(spec.read_text(encoding="utf-8").replace("Hold A for", "Hold B for"), encoding="utf-8")
    before = tree(project)
    result = run_cli(["run", SPEC], provider=LiteralProvider(world()), clock=at(0))
    assert result.code == 8 and result.out == ""
    assert result.err.splitlines()[0] == (
        "bt: error: the brief of 'hold_a' changed since it was approved: no approved idea has this brief"
    )
    assert tree(project) == before  # no run, no report


# --- both lines, for every call ---


def test_every_call_goes_through_both_lines_and_a_refused_call_is_refused_by_each(project: Path) -> None:
    coder = FakeCoder(project, HOLD_A)
    transcript = coder.run([write(coder.path("src/probe.py"), "x = 1\n")], "Tried one write.")
    both_lines_refused(transcript.records[0])
    ended_with_the_handback(transcript)
    assert not (project / "src").exists()


@pytest.mark.parametrize("name", ["strategy-architect", "signal-coder"])
def test_a_handback_is_allowed_by_both_lines_for_each_agent(project: Path, name: str) -> None:
    agent = FakeAgent(name, project)
    ended_with_the_handback(agent.run([], "Nothing to do."))
    assert [record.call.tool for record in agent.transcript.records] == [HANDBACK]


# --- the strategy architect: what it may not do ---


@pytest.mark.parametrize(
    "relative",
    [
        "src/x.py",
        "strategies/signals/hold_a.py",
        "strategies/drafts/../signals/x.yaml",
        "strategies/drafts/../../src/x.yaml",
        "approvals/hold_a.json",
    ],
)
def test_the_architect_writes_only_a_draft(project: Path, relative: str) -> None:
    before = tree(project)
    architect = FakeArchitect(project)
    transcript = architect.run([write(architect.path(relative), "x\n")], "Tried one write.")
    both_lines_refused(transcript.records[0])
    ended_with_the_handback(transcript)
    assert tree(project) == before


@pytest.mark.parametrize(
    "command",
    [
        f"uv run bt signal check {SPEC}",
        f"bt signal check {SPEC}",
        f"uv run bt run {SPEC}",
        f"uv run bt validate {SPEC} --data",
        *APPROVE_SPELLINGS,
    ],
)
def test_the_architect_runs_only_validate(project: Path, command: str) -> None:
    before = tree(project)
    transcript = FakeArchitect(project).run([bash(command)], "Tried one command.")
    both_lines_refused(transcript.records[0])
    ended_with_the_handback(transcript)
    assert tree(project) == before and not (project / "approvals").exists()


# --- the signal coder: what it may not do ---


@pytest.mark.parametrize("command", APPROVE_SPELLINGS)
def test_the_coder_cannot_approve_anything(project: Path, command: str) -> None:
    FakeArchitect(project).draft()
    FakeCoder(project, HOLD_A).code()
    before = tree(project)
    transcript = FakeCoder(project, HOLD_A).run([bash(command)], "Tried one command.")
    both_lines_refused(transcript.records[0])
    ended_with_the_handback(transcript)
    assert tree(project) == before and not (project / "approvals").exists()


def test_the_coder_writes_only_its_signal_and_its_examples(project: Path) -> None:
    coder = FakeCoder(project, HOLD_A)
    calls = [write(coder.path(p), "x\n") for p in ("src/probe.py", "tests/probe.py", "strategies/drafts/hold_a.yaml")]
    before = tree(project)
    transcript = coder.run(calls, "Tried three writes.")
    for record in transcript.records[:-1]:
        both_lines_refused(record)
    ended_with_the_handback(transcript)
    assert tree(project) == before


@pytest.mark.parametrize("mode", ["acceptEdits", "plan", "auto", "bypassPermissions", "dontAsk", MISSING])
def test_the_coders_signal_check_is_refused_outside_the_default_mode(project: Path, mode: object) -> None:
    FakeArchitect(project).draft()
    coder = FakeCoder(project, HOLD_A, mode=mode)
    transcript = coder.code()
    check = transcript.of("Bash")[1]
    both_lines_refused(check)
    assert "default permission mode" in check.reason and "switch" not in check.reason
    ended_with_the_handback(transcript)


def test_the_same_check_is_allowed_in_the_default_mode(project: Path) -> None:
    FakeArchitect(project).draft()
    transcript = FakeCoder(project, HOLD_A, mode="default").code()
    check = transcript.of("Bash")[1]
    assert (check.settings_code, check.frontmatter_code, check.performed) == (0, 0, True)
    assert check.outcome.code == 0


def test_a_refused_check_leaves_the_files_approves_nothing_and_the_handback_is_allowed(project: Path) -> None:
    FakeArchitect(project).draft()
    transcript = FakeCoder(project, HOLD_A, mode="auto").code()
    validate, check = transcript.of("Bash")
    assert validate.performed
    both_lines_refused(check)
    assert (project / "strategies" / "signals" / "hold_a.py").read_bytes() == HOLD_A
    assert (project / "strategies" / "signals" / "hold_a.cases.yaml").is_file()
    assert not (project / "approvals").exists()
    ended_with_the_handback(transcript)


# --- a hook line that hangs ---


def test_a_timeout_kills_and_reaps_both_processes(project: Path) -> None:
    agent = FakeAgent("signal-coder", project)
    agent.lines = ("sleep 30", "sleep 30")  # two hook lines that do not return
    agent.hook_timeout = 1
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            agent.call(bash(VALIDATE))
        assert len(agent.processes) == 2
        assert [process.poll() is not None for process in agent.processes] == [True, True]  # killed and reaped
    finally:
        for process in agent.processes:  # a test that fails must not leave the sleepers behind either
            kill_tree(process)


# --- tools the hook does not know ---


@pytest.mark.parametrize("name", ["strategy-architect", "signal-coder"])
@pytest.mark.parametrize("tool", ["TodoWrite", "SendMessage", "ToolSearch", "PowerShell", "SubagentHandbackX"])
def test_an_unknown_tool_is_refused_and_the_agent_still_hands_back(project: Path, name: str, tool: str) -> None:
    agent = FakeAgent(name, project)
    transcript = agent.run([Call(tool, {"command": "bt validate " + SPEC, "message": "x"})], "Tried one tool.")
    assert transcript.records[0].refused and "restrict_writes: blocked:" in transcript.records[0].reason
    assert tool in transcript.records[0].reason
    ended_with_the_handback(transcript)
