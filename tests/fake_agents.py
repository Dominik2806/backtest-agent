"""Fake agents: scripted stand-ins for the strategy architect and the signal coder (Phase 10 part 4b).

They decide nothing. Each tool call of a script goes through the **real hook, through both of its lines** (the command
that the COPY of the agent file in the temp project carries, and the command of the COPY of ``settings.json``), each
started with ``bash -c`` as Claude Code starts it, with a payload shaped like the ones that were observed
(``tool_name``, ``tool_input``, ``agent_type``, ``agent_id``, ``permission_mode``, ``cwd``). A call is performed only
when both lines exit 0; otherwise nothing is performed and the reason on stderr is returned. Every scripted run ends
with a ``SubagentHandback`` call (the way a real subagent returns its message), also after a refusal, and it goes
through both lines too.

What this does not model: the ask rule (Claude Code asking a person before ``bt signal check``), the deny rules, the
``tools`` list, and everything else Claude Code does. The commands are performed in this process by ``run_cli`` in the
current directory (the tests change into the temp project): a Bash command ``uv run bt ...`` and a bare ``bt ...`` are
both mapped to it, and so is ``python -m backtest_agent ...``, so that a hook that let one of them through would show.
"""

import json
import os
import shutil
import signal
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from backtest_agent.data import DataProvider
from cli_helpers import Outcome, at, run_cli
from restrict_writes_helpers import ROOT, agent_file, git_bash

HANDBACK = "SubagentHandback"
SYNTHETIC_AGENT_ID = "a0123456789abcdef"  # synthetic: the shape of an observed agent_id, not one from a log
HOOK_FILES = (".claude/settings.json", ".claude/hooks/restrict_writes.py")
MISSING = object()  # a call without permission_mode


def make_project(root: Path) -> Path:
    """A temp project: copies of ``.claude/`` (settings, hook, the real agent files) and the strategies folders."""
    for relative in HOOK_FILES:
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, root / relative)
    (root / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
    for path in (ROOT / ".claude" / "agents").glob("*.md"):
        shutil.copyfile(path, root / ".claude" / "agents" / path.name)
    (root / "strategies" / "drafts").mkdir(parents=True, exist_ok=True)
    for path in ROOT.joinpath("strategies").glob("*.yaml"):
        shutil.copyfile(path, root / "strategies" / path.name)
    return root


def settings_line(project: Path) -> str:
    settings = json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))
    (entry,) = settings["hooks"]["PreToolUse"]
    (handler,) = entry["hooks"]
    return handler["command"]


def frontmatter_line(name: str, project: Path) -> str:
    frontmatter, _ = agent_file(name, project)
    (group,) = frontmatter["hooks"]["PreToolUse"]
    (handler,) = group["hooks"]
    return handler["command"]


@dataclass(frozen=True)
class Call:
    """One tool call of a script: the tool and its input."""

    tool: str
    tool_input: dict


def write(path: str, content: str) -> Call:
    return Call("Write", {"file_path": path, "content": content})


def read(path: str) -> Call:
    return Call("Read", {"file_path": path})


def bash(command: str) -> Call:
    return Call("Bash", {"command": command})


@dataclass
class Record:
    """What happened to one call: the exit codes of the two lines, the reason and, if performed, the outcome."""

    call: Call
    settings_code: int
    frontmatter_code: int
    reason: str
    performed: bool
    outcome: Outcome | None = None
    text: str | None = None

    @property
    def refused(self) -> bool:
        return not self.performed


@dataclass
class Transcript:
    records: list[Record] = field(default_factory=list)

    def of(self, tool: str) -> list[Record]:
        return [record for record in self.records if record.call.tool == tool]

    def commands(self) -> list[str]:
        return [record.call.tool_input["command"] for record in self.of("Bash")]

    @property
    def last(self) -> Record:
        return self.records[-1]


def kill_tree(process: subprocess.Popen) -> None:
    """Kill a process that is still running together with its children, and reap it. Never leaves one behind."""
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.kill()  # a no-op if the tree kill already did it
    process.wait()  # reaps the process
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None and not stream.closed:
            stream.close()


class FakeAgent:
    """A scripted agent with the name of one of the real agent files."""

    hook_timeout = 120  # seconds for both lines of one call
    processes: list[subprocess.Popen]

    def __init__(
        self,
        name: str,
        project: Path,
        *,
        mode: object = "default",
        provider: DataProvider | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.name, self.project, self.mode = name, project, mode
        self.provider, self.clock = provider, clock if clock is not None else at(0)
        self.lines = (settings_line(project), frontmatter_line(name, project))
        self.transcript = Transcript()

    # --- the hook, through both lines ---

    def payload(self, call: Call) -> str:
        found: dict = {
            "hook_event_name": "PreToolUse",
            "tool_name": call.tool,
            "tool_input": call.tool_input,
            "agent_type": self.name,
            "agent_id": SYNTHETIC_AGENT_ID,
            "cwd": str(self.project),
        }
        if self.mode is not MISSING:
            found["permission_mode"] = self.mode
        return json.dumps(found)

    def ask_the_hook(self, call: Call) -> tuple[int, int, str]:
        """Run both lines at once; on a timeout (or any error) kill and reap both, with their children."""
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.project)}
        data = self.payload(call).encode("utf-8")
        shell = git_bash()
        self.processes = started = []
        try:
            for line in self.lines:
                started.append(
                    subprocess.Popen(
                        [shell, "-c", line],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        env=env,
                        cwd=self.project,
                        start_new_session=os.name != "nt",
                    )
                )
            done = [process.communicate(data, timeout=self.hook_timeout) for process in started]
        finally:
            for process in started:
                kill_tree(process)
        codes = [process.returncode for process in started]
        reason = " | ".join(err.decode("utf-8", "replace").strip() for _, err in done if err.strip())
        return codes[0], codes[1], reason

    # --- the call ---

    def call(self, call: Call) -> Record:
        settings_code, frontmatter_code, reason = self.ask_the_hook(call)
        allowed = settings_code == 0 and frontmatter_code == 0
        record = Record(call, settings_code, frontmatter_code, reason, performed=allowed)
        if allowed:
            self.perform(record)
        self.transcript.records.append(record)
        return record

    def perform(self, record: Record) -> None:
        call = record.call
        if call.tool == "Write":
            path = self.resolve(call.tool_input["file_path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(call.tool_input["content"].encode("utf-8"))
        elif call.tool == "Read":
            record.text = self.resolve(call.tool_input["file_path"]).read_text(encoding="utf-8")
        elif call.tool == "Bash":
            record.outcome = self.run_bt(call.tool_input["command"])
        elif call.tool == HANDBACK:
            record.text = call.tool_input["message"]
        else:
            raise AssertionError(f"the hook let through {call.tool}, which the fake agent cannot perform")

    def resolve(self, file_path: str) -> Path:
        path = Path(file_path)
        return path if path.is_absolute() else self.project / path

    def run_bt(self, command: str) -> Outcome:
        words = command.split(" ")
        if words[:2] == ["uv", "run"]:
            words = words[2:]
        if words[:3] == ["python", "-m", "backtest_agent"]:
            words = ["bt", *words[3:]]
        if words[:1] != ["bt"]:
            raise AssertionError(f"the hook let through {command!r}, which the fake agent cannot perform")
        assert Path.cwd().resolve() == self.project.resolve(), "the test changes into the temp project"
        return run_cli(words[1:], provider=self.provider, clock=self.clock)

    # --- a script ---

    def path(self, relative: str) -> str:
        return str(self.project / relative)

    def run(self, calls: Sequence[Call], message: str) -> Transcript:
        """Make the calls in order, then hand the message back. A script never stops early and never retries."""
        for call in calls:
            self.call(call)
        done = self.call(Call(HANDBACK, {"message": message}))
        assert done.performed, f"the handback was refused: {done.reason}"
        return self.transcript


# The scripted literals. The spec is the one of docs/cli.md ("Example: a coded signal, from approval to run").
DRAFT = """\
# Draft: hold A for the whole period, written as a coded signal. Example, not a recommendation, not investment advice.
# Assumptions: orders at the next open (delay_bars 1), 25 percent costs on a five-bar world, benchmark B.
# Open questions: none.
schema_version: 1
name: Buy and hold A
description: A spec used in tests.
universe:
- A
period:
  start: '2024-01-02'
  end: '2024-01-08'
data:
  provider: yfinance
signal:
  id: hold_a
  params: {}
  coded:
    brief: Hold A for the whole period.
execution:
  delay_bars: 1
  price: open
  allow_same_bar_execution: false
sizing:
  method: equal_weight
  fraction: null
rebalance: on_signal
costs:
  commission_bps: 1000.0
  spread_bps: 1000.0
  slippage_bps: 500.0
  min_commission: 0.0
benchmark: B
initial_capital: 1000.0
"""

CASES = """\
# hold_a holds the symbol on every row, so the exposure of A is 1.0 on each of the three rows.
# Closes 10, 11, 12: the signal does not look at them; scale is 1.0 (its default), so 1.0 * 1.0 = 1.0 on every row.
cases:
  - name: holds A on every row
    prices:
      A: [10, 11, 12]
    expected:
      A: [1, 1, 1]
"""

SPEC = "strategies/drafts/hold_a.yaml"
VALIDATE = f"uv run bt validate {SPEC}"
CHECK = f"uv run bt signal check {SPEC}"


class FakeArchitect(FakeAgent):
    def __init__(self, project: Path, **kwargs) -> None:
        super().__init__("strategy-architect", project, **kwargs)

    def draft(self) -> Transcript:
        """Read an example, write the draft, validate it, hand back the assumptions and the open questions."""
        calls = [
            read(self.path("strategies/buy_and_hold.yaml")),
            write(self.path(SPEC), DRAFT),
            bash(VALIDATE),
        ]
        message = "Wrote strategies/drafts/hold_a.yaml. Assumptions are in its header. Open questions: none."
        return self.run(calls, message)


class FakeCoder(FakeAgent):
    def __init__(self, project: Path, source: bytes, **kwargs) -> None:
        super().__init__("signal-coder", project, **kwargs)
        self.source = source

    def code(self) -> Transcript:
        """Write the signal and its examples, validate, check; if the check is refused, finish without a retry."""
        calls = [
            write(self.path("strategies/signals/hold_a.py"), self.source.decode("utf-8")),
            write(self.path("strategies/signals/hold_a.cases.yaml"), CASES),
            bash(VALIDATE),
            bash(CHECK),
        ]
        for call in calls:
            self.call(call)
        done = self.call(Call(HANDBACK, {"message": self.message()}))
        assert done.performed, f"the handback was refused: {done.reason}"
        return self.transcript

    def message(self) -> str:
        checked = [r for r in self.transcript.of("Bash") if "signal check" in r.call.tool_input["command"]]
        if checked and checked[0].refused:
            return (
                "Wrote strategies/signals/hold_a.py and hold_a.cases.yaml and ran bt validate. The check was refused; "
                f"{CHECK} is a step for you to run after reading the code."
            )
        return "Wrote strategies/signals/hold_a.py and hold_a.cases.yaml; validate and the check ran."
