"""What the hook lets each agent write and run, decided in process (``decide``) with literal tables.

The hook is a fence, not a boundary (docs/agents.md). The tables name the refusals the plan promises: ``..``, an
absolute path outside the project, a link out of the folder, UNC, an NTFS stream, a trailing dot or space, an 8.3 name,
case, the id rules, the Bash allowlist, the backslash and the tools that are not allowed at all.
"""

import os
from pathlib import Path

import pytest

from backtest_agent.spec.coded_spec import coded_id_problem
from restrict_writes_helpers import ARCHITECT, CODER, load_hook, make_dir_link, payload

hook = load_hook()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    for folder in ("strategies/signals", "strategies/drafts", "strategies/examples", "src", "approvals"):
        (root / folder).mkdir(parents=True)
    return root


def refusal(agent: str, project: Path, tool: str, **tool_input: object) -> str | None:
    """The reason the hook gives, or None if it has no objection."""
    try:
        hook.decide(agent, payload(tool, **tool_input), project)
    except hook.Refused as reason:
        return str(reason)
    return None


def write_refusal(agent: str, project: Path, path: str, tool: str = "Write") -> str | None:
    return refusal(agent, project, tool, file_path=path, content="x")


# --- the id rules are the project's own ---

IDS = [
    "rsi_pullback", "a", "a1", "x" * 64, "x" * 65, "", "_x", "1a", "A", "x-y", "a.b", "ab cd", "\u00e9",
    "con", "prn", "aux", "nul", "com1", "com9", "com10", "lpt1", "lpt9", "lpt0",
    "buy_and_hold", "momentum_12_1", "sma_crossover", "sma_crossover2",
]  # fmt: skip


@pytest.mark.parametrize("signal_id", IDS)
def test_the_id_rules_of_the_hook_are_the_rules_of_the_spec(signal_id: str) -> None:
    assert hook.coded_id_ok(signal_id) is (coded_id_problem(signal_id) is None)


# --- writes of the signal coder ---


@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit"])
@pytest.mark.parametrize(
    "relative",
    ["strategies/signals/rsi_pullback.py", "strategies/signals/rsi_pullback.cases.yaml", "strategies/signals/a.py"],
)
def test_the_coder_may_write_its_two_files_by_relative_and_absolute_path(
    project: Path, tool: str, relative: str
) -> None:
    assert write_refusal(CODER, project, relative, tool) is None
    assert write_refusal(CODER, project, str(project / relative), tool) is None


@pytest.mark.parametrize(
    "relative",
    [
        "src/backtest_agent/engine/runner.py",
        "tests/test_x.py",
        "approvals/x_signal.json",
        "approvals/code/abc.py",
        ".claude/settings.json",
        ".claude/hooks/restrict_writes.py",
        "docs/agents.md",
        "strategies/sma_crossover.yaml",
        "strategies/drafts/x.yaml",
        "strategies/examples/x.yaml",
        "strategies/signals/sub/x.py",
        "strategies/signals/x.txt",
        "strategies/signals/x.py.bak",
        "strategies/signals/x.yaml",
        "strategies/signals/x.cases.py",
        "strategies/signals/x.PY",
        "strategies/signals/.py",
        "strategies/signals/",
        "strategies/signals",
        "pyproject.toml",
    ],
)
def test_the_coder_may_not_write_anywhere_else(project: Path, relative: str) -> None:
    assert write_refusal(CODER, project, relative) is not None
    assert write_refusal(CODER, project, str(project / relative)) is not None


@pytest.mark.parametrize(
    "name", ["con.py", "nul.cases.yaml", "com1.py", "buy_and_hold.py", "1x.py", ("x" * 65) + ".py", "x-y.py", "X.py"]
)
def test_the_id_rules_apply_to_the_file_name(project: Path, name: str) -> None:
    assert write_refusal(CODER, project, f"strategies/signals/{name}") is not None


def test_a_path_with_dot_dot_is_refused_even_when_it_lands_in_the_folder(project: Path) -> None:
    assert "'..'" in (write_refusal(CODER, project, "strategies/signals/../signals/x.py") or "")
    assert "'..'" in (write_refusal(CODER, project, str(project / "strategies/signals/../../src/x.py")) or "")
    assert "'..'" in (write_refusal(CODER, project, "strategies\\signals\\..\\x.py") or "")


def test_an_absolute_path_outside_the_project_is_refused(project: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside" / "strategies" / "signals"
    outside.mkdir(parents=True)
    assert write_refusal(CODER, project, str(outside / "x.py")) is not None
    assert write_refusal(CODER, project, Path(project.anchor, "x.py").as_posix()) is not None


@pytest.mark.parametrize(
    "path",
    [
        "//server/share/strategies/signals/x.py",
        "\\\\server\\share\\strategies\\signals\\x.py",
        "\\\\?\\C:\\project\\strategies\\signals\\x.py",
        "//./pipe/x.py",
    ],
)
def test_unc_and_device_paths_are_refused(project: Path, path: str) -> None:
    assert "UNC" in (write_refusal(CODER, project, path) or "")


@pytest.mark.parametrize("suffix", ["::$DATA", ":stream", ":stream:$DATA"])
def test_an_ntfs_stream_is_refused(project: Path, suffix: str) -> None:
    path = str(project / "strategies/signals/x.py") + suffix
    assert "colon" in (write_refusal(CODER, project, path) or "")
    assert "colon" in (write_refusal(CODER, project, "strategies/signals/x.py" + suffix) or "")


@pytest.mark.parametrize(
    "relative",
    ["strategies/signals/x.py.", "strategies/signals/x.py ", "strategies/signals./x.py", "strategies/signals /x.py"],
)
def test_a_trailing_dot_or_space_is_refused(project: Path, relative: str) -> None:
    assert "dot or a space" in (write_refusal(CODER, project, relative) or "")
    assert "dot or a space" in (write_refusal(CODER, project, str(project / relative)) or "")


@pytest.mark.parametrize(
    "relative",
    [
        "strategies/signals/RSIPUL~1.py",
        "STRATE~1/signals/x.py",
        "strategies/SIGNAL~1/x.py",
        "strategies/signals/x~2.py",
    ],
)
def test_an_8_3_short_name_is_refused(project: Path, relative: str) -> None:
    assert "8.3" in (write_refusal(CODER, project, relative) or "")


def test_a_wrong_case_in_the_folder_is_the_same_folder_only_where_the_system_says_so(project: Path) -> None:
    refused = write_refusal(CODER, project, str(project / "STRATEGIES" / "SIGNALS" / "x.py"))
    assert (refused is None) is (os.name == "nt")  # Windows folds case, so it is the folder; elsewhere it is not
    assert write_refusal(CODER, project, "strategies/signals/X_signal.py") is not None  # a name is lowercase always


@pytest.mark.parametrize("path", ["C:x.py", "c:strategies/signals/x.py"])
def test_a_path_relative_to_a_drive_is_refused(project: Path, path: str) -> None:
    assert "drive" in (write_refusal(CODER, project, path) or "")


@pytest.mark.parametrize("path", ["strategies/signals/*.py", "strategies/signals/x?.py", 'strategies/signals/"x".py'])
def test_wildcards_and_reserved_characters_are_refused(project: Path, path: str) -> None:
    assert write_refusal(CODER, project, path) is not None


@pytest.mark.parametrize("path", [None, "", 5, ["strategies/signals/x.py"], "strategies/signals/x\0.py"])
def test_a_missing_or_odd_path_is_refused(project: Path, path: object) -> None:
    assert write_refusal(CODER, project, path) is not None  # type: ignore[arg-type]


def test_a_junction_or_link_from_the_folder_to_somewhere_else_is_refused(project: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (project / "strategies" / "signals").rmdir()
    make_dir_link(project / "strategies" / "signals", elsewhere)
    assert "only in" in (write_refusal(CODER, project, "strategies/signals/x.py") or "")


def test_a_file_that_is_a_link_to_another_file_is_refused(project: Path, tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("x = 1\n", encoding="utf-8")
    link = project / "strategies" / "signals" / "x.py"
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("cannot create a file symlink here")
    assert "link" in (write_refusal(CODER, project, "strategies/signals/x.py") or "")
    assert write_refusal(CODER, project, "strategies/signals/y.py") is None


# --- writes of the strategy architect ---


@pytest.mark.parametrize("name", ["my-idea_1.yaml", "0a.yaml", "trend.yaml"])
def test_the_architect_may_write_a_draft(project: Path, name: str) -> None:
    assert write_refusal(ARCHITECT, project, f"strategies/drafts/{name}") is None
    assert write_refusal(ARCHITECT, project, str(project / "strategies" / "drafts" / name)) is None


@pytest.mark.parametrize(
    "relative",
    [
        "strategies/drafts/x.yml",
        "strategies/drafts/x.yaml.bak",
        "strategies/drafts/sub/x.yaml",
        "strategies/drafts/X.yaml",
        "strategies/drafts/con.yaml",
        "strategies/drafts/-x.yaml",
        "strategies/drafts/x.py",
        "strategies/x.yaml",
        "strategies/examples/x.yaml",
        "strategies/signals/x.py",
        "strategies/signals/x.cases.yaml",
        "src/x.py",
        "approvals/x.json",
        ".claude/settings.json",
    ],
)
def test_the_architect_may_write_nothing_else(project: Path, relative: str) -> None:
    assert write_refusal(ARCHITECT, project, relative) is not None


def test_the_two_agents_do_not_share_a_folder(project: Path) -> None:
    assert write_refusal(CODER, project, "strategies/drafts/x.yaml") is not None
    assert write_refusal(ARCHITECT, project, "strategies/signals/x.py") is not None


# --- Bash ---

SPEC = "strategies/drafts/trend.yaml"
BASH_ARCHITECT = [f"bt validate {SPEC}", f"uv run bt validate {SPEC}", "bt validate strategies/drafts/a-b_1.yaml"]
BASH_CODER = [
    *BASH_ARCHITECT,
    "bt validate strategies/examples/rsi_pullback.yaml",
    f"bt signal check {SPEC}",
    "bt signal check strategies/examples/rsi_pullback.yaml",
    f"uv run bt signal check {SPEC}",
    f"bt signal check {SPEC} --strategies-dir strategies/signals",
    f"uv run bt signal check {SPEC} --strategies-dir strategies/signals",
]


@pytest.mark.parametrize("command", BASH_ARCHITECT)
def test_the_architect_may_validate_a_draft(project: Path, command: str) -> None:
    assert refusal(ARCHITECT, project, "Bash", command=command) is None


@pytest.mark.parametrize("command", BASH_CODER)
def test_the_coder_may_validate_and_check(project: Path, command: str) -> None:
    assert refusal(CODER, project, "Bash", command=command) is None


@pytest.mark.parametrize(
    "command",
    [
        f"bt signal check {SPEC}",  # the architect has no signal check
        f"uv run bt signal check {SPEC}",
        "bt validate strategies/examples/rsi_pullback.yaml",  # the architect reads its drafts only
    ],
)
def test_the_architect_may_not_check_a_signal_or_read_the_examples(project: Path, command: str) -> None:
    assert refusal(ARCHITECT, project, "Bash", command=command) is not None


FORBIDDEN_FOR_BOTH = [
    f"bt approve {SPEC} --idea",
    f"bt approve {SPEC} --code --sha 3f9a1c2e",
    f"uv run bt approve {SPEC} --idea",
    f"python -m backtest_agent approve {SPEC} --idea",
    f"bt.exe approve {SPEC} --idea",
    f"bt run {SPEC}",
    f"bt report abc {SPEC}",
    "bt journal list",
    f"bt data fetch {SPEC}",
    f"bt validate {SPEC} --data",
    f"bt validate {SPEC} --debug",
    f"bt validate {SPEC} extra",
    "bt validate",
    "bt",
    "bt --help",
    "uv run",
    "uv run python -c x",
    "uv run --quiet bt validate " + SPEC,
    f"bt.exe validate {SPEC}",
    f"/usr/bin/bt validate {SPEC}",
    f"./bt validate {SPEC}",
    "bt validate strategies/drafts/../x.yaml",
    "bt validate strategies/drafts/x.yml",
    "bt validate strategies/x.yaml",
    "bt validate strategies/signals/x.yaml",
    "bt validate strategies/drafts/con.yaml",
    "bt validate strategies/drafts/sub/x.yaml",
    "bt validate /etc/passwd",
    "bt validate ../x.yaml",
    "bt validate strategies/drafts/*.yaml",
    f"bt validate {SPEC}; bt approve {SPEC} --idea",
    f"bt validate {SPEC} && bt approve {SPEC} --idea",
    f"bt validate {SPEC} || true",
    f"bt validate {SPEC} | cat",
    f"bt validate {SPEC} & true",
    f"bt validate {SPEC} `id`",
    "bt validate $(id)",
    f"bt validate {SPEC} > out.txt",
    f"bt validate {SPEC} < in.txt",
    f"bt validate {SPEC}\nbt approve {SPEC} --idea",
    f"bt validate {SPEC}\r",
    f"bt\tvalidate {SPEC}",
    f"bt validate '{SPEC}'",
    f'bt validate "{SPEC}"',
    f"bt  validate {SPEC}",
    f" bt validate {SPEC}",
    f"bt validate {SPEC} ",
    f"FOO=1 bt validate {SPEC}",
    f"cd strategies && bt validate {SPEC}",
    f"bash -c 'bt validate {SPEC}'",
    "python -c 'print(1)'",
    "python strategies/signals/x.py",
    "cat approvals/x.json",
    "rm -rf src",
    "git add strategies/signals/x.py",
    "echo hi > strategies/signals/x.py",
    "\u00e9",
    "",
]


@pytest.mark.parametrize("agent", [ARCHITECT, CODER])
@pytest.mark.parametrize("command", FORBIDDEN_FOR_BOTH)
def test_every_other_command_is_refused(project: Path, agent: str, command: str) -> None:
    assert refusal(agent, project, "Bash", command=command) is not None


@pytest.mark.parametrize(
    "command",
    [
        f"bt signal check {SPEC} --strategies-dir strategies/drafts",
        f"bt signal check {SPEC} --strategies-dir /tmp",
        f"bt signal check {SPEC} --strategies-dir ../signals",
        f"bt signal check {SPEC} --approvals-dir approvals",
        f"bt signal check {SPEC} --strategies-dir",
        f"bt signal check {SPEC} --strategies-dir strategies/signals extra",
        f"bt signal check {SPEC} --debug",
        "bt signal check",
        "bt signal",
        "bt signal check strategies/signals/x.py",
        "bt signal check strategies/x.yaml",
        f"bt signal check {SPEC} {SPEC}",
    ],
)
def test_the_signal_check_of_the_coder_has_one_form(project: Path, command: str) -> None:
    assert refusal(CODER, project, "Bash", command=command) is not None


def test_a_backslash_is_refused_with_its_own_reason(project: Path) -> None:
    reason = refusal(CODER, project, "Bash", command="bt validate strategies\\drafts\\trend.yaml")
    assert reason and "backslash" in reason and "forward slashes" in reason


@pytest.mark.parametrize("command", [None, 5, ["bt", "validate"]])
def test_a_command_that_is_not_text_is_refused(project: Path, command: object) -> None:
    assert refusal(CODER, project, "Bash", command=command) is not None


# --- the tools that are not allowed at all ---


@pytest.mark.parametrize("agent", [ARCHITECT, CODER])
@pytest.mark.parametrize(
    "tool", ["NotebookEdit", "PowerShell", "Read", "WebFetch", "WebSearch", "Agent", "Glob", "mcp__x", ""]
)
def test_every_other_tool_is_refused(project: Path, agent: str, tool: str) -> None:
    assert refusal(agent, project, tool, notebook_path="n.ipynb", command="bt validate " + SPEC) is not None


@pytest.mark.parametrize("agent", [ARCHITECT, CODER])
def test_a_call_without_tool_name_or_input_is_refused(project: Path, agent: str) -> None:
    for broken in ({}, {"tool_name": "Write"}, {"tool_name": "Write", "tool_input": "x"}, {"tool_input": {}}):
        try:
            hook.decide(agent, broken, project)
        except hook.Refused:
            continue
        raise AssertionError(f"{broken} was not refused")


# --- reasons: each guard is checked by what it says, not only by the refusal ---


def test_each_text_guard_gives_its_own_reason(project: Path) -> None:
    assert "no allowed file name has" in (write_refusal(CODER, project, "strategies/signals/x?.py") or "")
    assert "no allowed file name has" in (write_refusal(CODER, project, "strategies/signals/*.py") or "")
    for tool in ("PowerShell", "NotebookEdit"):
        reason = refusal(CODER, project, tool, command="bt validate " + SPEC, notebook_path="n.ipynb") or ""
        assert f"may not use {tool}" in reason and "does not know" not in reason
    assert "does not know" in (refusal(CODER, project, "WebFetch", url="x") or "")


@pytest.mark.parametrize(
    "command", [f"bt validate {SPEC};", f"bt validate {SPEC} | cat", "bt validate $(id)", f"bt validate '{SPEC}'"]
)
def test_a_shell_character_gets_the_allowlist_reason(project: Path, command: str) -> None:
    assert "character outside" in (refusal(CODER, project, "Bash", command=command) or "")


@pytest.mark.parametrize("command", [f"bt  validate {SPEC}", f" bt validate {SPEC}", f"bt validate {SPEC} "])
def test_a_stray_space_gets_its_own_reason(project: Path, command: str) -> None:
    assert "double space" in (refusal(CODER, project, "Bash", command=command) or "")


def test_a_wrong_case_folder_that_does_not_exist_yet_is_the_folder_only_where_the_system_says_so(
    tmp_path: Path,
) -> None:
    """realpath fixes the case of a folder that exists; for one that does not exist yet only normcase decides."""
    bare = tmp_path / "bare"
    bare.mkdir()
    refused = write_refusal(CODER, bare, str(bare / "STRATEGIES" / "SIGNALS" / "x.py"))
    assert (refused is None) is (os.name == "nt")


def test_a_file_whose_real_path_is_somewhere_else_is_refused(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The file-symlink case without needing the privilege to make a symlink: realpath says where the file really is."""
    real = os.path.realpath

    def moved(path):
        return str(project.parent / "elsewhere" / "x.py") if str(path).endswith("x.py") else real(path)

    monkeypatch.setattr(hook.os.path, "realpath", moved)
    assert "link" in (write_refusal(CODER, project, "strategies/signals/x.py") or "")
