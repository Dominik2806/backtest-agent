"""docs/cli.md and the other documents are true about ``bt signal check`` (Phase 10 part 3b).

The blocks of the document are what the command prints (the command is run on the fixtures of
``tests/test_cli_signal_check.py`` and its output is compared with the fenced blocks, character for character); the
exit-code rows, the hint-table sentences, the sentences about the agents and the rules of CLAUDE.md are tied to the code
or to the tests that enforce them; and no document says that ``bt signal check`` is not built any more. The expected
blocks are literals of the documents, never computed by project code.
"""

import re
from pathlib import Path

import pytest

from cli_helpers import run_cli
from coded_helpers import (
    World,
    canary_source,
    good_source,
    registry_and_modules_are_restored,  # noqa: F401 - autouse fixture
)
from test_cli_signal_check import ID, WORSE_CASES, candidate
from test_coded_source_tree import CANDIDATE_FILES, LOADER

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def cwd(world: World, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(world.root)
    return world.root


def read(*parts: str) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8").replace("\r\n", "\n")


CLI = read("docs", "cli.md")
CODED = read("docs", "coded-signals.md")
ADR = read("docs", "adr", "0018-coded-signals-and-approval-gate.md")
README = read("README.md")
CLAUDE = read("CLAUDE.md")
CHANGELOG = read("CHANGELOG.md")
FLAT = {
    name: " ".join(text.split()) for name, text in {"cli": CLI, "coded": CODED, "adr": ADR, "readme": README}.items()
}

SECTION = CLI[CLI.index("### `bt signal check SPEC`") : CLI.index("\n## Exit codes\n")]
BLOCKS = re.findall(r"^```\n(.*?)^```", SECTION, flags=re.MULTILINE | re.DOTALL)
CONSENT_BLOCK, STDOUT_BLOCK, STATIC_BLOCK, CONTRACT_BLOCK, EXAMPLES_BLOCK = BLOCKS


def lines(block: str) -> list[str]:
    return block.rstrip("\n").split("\n")


def test_the_section_has_the_five_blocks_this_file_compares() -> None:
    assert len(BLOCKS) == 5
    assert lines(CONSENT_BLOCK)[0].startswith(
        "bt: executing strategies/signals/x_signal.py (sha 81d30b98, NOT approved)"
    )


# --- the blocks are what the command prints ---


def test_the_output_block_and_the_consent_line_are_what_a_good_run_prints(cwd: Path) -> None:
    candidate(cwd, good_source(ID, "0.5"))
    result = run_cli(["signal", "check", "spec.yaml"])
    assert (result.code, result.out.splitlines(), result.err.splitlines()) == (
        0,
        lines(STDOUT_BLOCK),
        lines(CONSENT_BLOCK),
    )


def test_the_static_check_failure_is_what_the_command_prints(cwd: Path) -> None:
    candidate(cwd, canary_source(ID))
    result = run_cli(["signal", "check", "spec.yaml"])
    assert (result.code, result.out, result.err.splitlines()) == (9, "", lines(STATIC_BLOCK))


def test_the_contract_failure_is_what_the_command_prints(cwd: Path) -> None:
    candidate(cwd, good_source(ID, "2.0"))
    result = run_cli(["signal", "check", "spec.yaml"])
    assert (result.code, result.out, result.err.splitlines()) == (9, "", lines(CONTRACT_BLOCK))


def test_the_failing_example_is_what_the_command_prints(cwd: Path) -> None:
    candidate(cwd, good_source(ID, "0.5"), cases=WORSE_CASES)
    result = run_cli(["signal", "check", "spec.yaml"])
    assert (result.code, result.out, result.err.splitlines()) == (9, "", lines(EXAMPLES_BLOCK))


def test_the_fixture_described_under_the_block_is_the_fixture_that_was_run() -> None:
    assert "the signal of `tests/coded_helpers.py` with the factor 0.5" in SECTION
    assert "`AAA` trades on three rows (10, 11, 12) and `BBB` on the last two (20, 21)" in SECTION
    assert "expected exposure is 0.5 on every row on which a symbol trades and 0 before its first row" in SECTION


# --- the sentences of the section ---


def test_the_section_states_what_the_command_does_and_does_not_do() -> None:
    flat = " ".join(SECTION.split())
    for words in (
        "**This command executes the file `strategies/signals/<id>.py`, which nobody approved.**",
        "with the permissions of whoever runs it and with no time or memory limit",
        "The static check is a tripwire, not a sandbox",
        "Nothing is approved and nothing is written, and the approvals folder is not read.",
        "There is no `--approvals-dir`",
        "a candidate can be checked before its idea is approved",
        "A candidate is checked again every time",
        "is exit code 9, **not 8**: nothing is waiting for an approval here",
        "**Up to here nothing was executed and the consent line has not been written.**",
        "The command never exits with 8 or 5.",
        "`--strategies-dir` when it was given and is not the default",
        "`bt approve --code` still shows the whole file, still refuses an unapproved idea (exit code 8) and "
        "still needs the `--sha`",
    ):
        assert words in flat, words


def test_the_options_of_the_section_are_the_options_of_the_command() -> None:
    help_text = run_cli(["signal", "check", "--help"]).out
    assert "--strategies-dir DIR" in help_text and "--approvals-dir" not in help_text
    options = re.findall(r"^\| (`--[a-z-]+)", SECTION, flags=re.MULTILINE)
    assert options == ["`--strategies-dir"]  # the only row of the option table
    assert "| `--strategies-dir DIR` | `strategies/signals` |" in SECTION


def test_the_consent_line_of_the_document_is_the_line_of_the_command_and_of_the_adr() -> None:
    template = (
        "bt: executing strategies/signals/<id>.py (sha <8 hex>, NOT approved) in this process, with your permissions "
        "and no time or memory limit; the static check is a tripwire, not a sandbox"
    )
    assert template in FLAT["adr"] and template in FLAT["coded"]
    assert lines(CONSENT_BLOCK)[0] == template.replace("<id>", "x_signal").replace("<8 hex>", "81d30b98")


def test_the_exit_code_rows_name_bt_signal_check() -> None:
    rows = {line.split("|")[1].strip(): line for line in CLI.splitlines() if re.match(r"\| (2|3|9|130) \|", line)}
    assert "`bt signal check` without `SPEC` or with `--approvals-dir`" in rows["2"]
    assert "`bt approve` and `bt signal check`: the spec has no `coded` block" in rows["3"]
    assert "the params of the spec do not fit the params model of the candidate" in rows["3"]
    assert "`CasesError`, the examples of `bt signal check`" in rows["9"] and "is also 9, not 8" in rows["9"]
    assert "not built yet" not in rows["9"]


def test_the_hint_table_states_the_unreadable_record_and_the_missing_record_outside_stored_mode() -> None:
    assert "A record file that cannot be read (a folder in its place, no permission) is treated the same" in CLI
    assert (
        "A record that is missing is exit code 5 only in stored mode (`bt report`); in `bt run`, "
        "`bt validate --data` and `bt data fetch` it is exit code 8 (the idea is not approved)"
    ) in " ".join(CLI.split())


# --- nothing says that bt signal check is not built, and the agents still are not ---

NOT_BUILT = re.compile(
    r"signal check`?,?\s*(\(|\*\*)?(is |and the agents are |are )?(not built|not yet built|not a command)",
    re.IGNORECASE,
)
OLD_PHRASES = (
    "no command raises `CasesError` today",
    "nothing in `bt` runs `cases.yaml` today",
    "nothing in `bt` runs `cases.yaml` yet",
    "that command is not built",
    "which is not built yet",
    "`bt signal check`, **not built yet**",
)


def tracked_text_files() -> list[Path]:
    """Every file that could still say it: documents, source and tests (not this file, which names the phrases)."""
    found = [ROOT / "README.md", ROOT / "CLAUDE.md", ROOT / "CHANGELOG.md", *sorted((ROOT / "docs").rglob("*.md"))]
    found += sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "tests").glob("*.py"))
    return [path for path in found if path != Path(__file__).resolve()]


def offences(files: list[Path], root: Path) -> list[str]:
    """``<file>: <phrase>`` for every file that says that ``bt signal check`` is not built."""
    found = []
    for path in files:
        text = " ".join(path.read_text(encoding="utf-8").split())
        name = path.relative_to(root).as_posix()
        found += [f"{name}: {m.group(0)}" for m in NOT_BUILT.finditer(text)]
        found += [f"{name}: {phrase}" for phrase in OLD_PHRASES if phrase in text]
    return found


def test_no_file_says_that_bt_signal_check_is_not_built() -> None:
    files = tracked_text_files()
    assert len(files) > 150 and ROOT / "docs" / "cli.md" in files and Path(__file__).resolve() not in files
    assert offences(files, ROOT) == []


def test_a_file_that_says_it_is_named_with_its_phrase(tmp_path: Path) -> None:
    clean, dirty = tmp_path / "clean.md", tmp_path / "dirty.md"
    clean.write_text("`bt signal check` is built; the agents are not built yet.\n", encoding="utf-8")
    dirty.write_text("The agents and `bt signal check` (not built yet) come later.\n", encoding="utf-8")
    assert offences([clean, dirty], tmp_path) == ["dirty.md: signal check` (not built"]


def test_the_checker_itself_finds_the_old_wording() -> None:
    for old in (
        "`bt signal check` and the agents are not built yet",
        "`bt signal check` (not built yet)",
        "**`bt signal check` is not built yet, so no command raises",
        "`bt signal check` is not built.",
    ):
        assert NOT_BUILT.search(old), old


def test_the_agent_files_exist_and_the_documents_say_what_is_still_not_built() -> None:
    assert "The agent files exist" in FLAT["readme"] and "The agents are not built yet" not in FLAT["readme"]
    assert (
        "[docs/agents.md](docs/agents.md)" in README
        and "the example specs, the fake agents and an end-to-end test follow" in FLAT["readme"]
    )
    assert "**The agent files exist**" in FLAT["cli"] and "The agents are not built yet" not in FLAT["cli"]
    not_built = CODED[CODED.index("## Not built yet") :]
    assert not_built.count("\n- ") == 2
    assert "The example specs, the fake agents and the end-to-end test of the agents" in not_built
    assert "The agent files that write the spec and the code" not in not_built
    assert (
        "The rule that denies `bt approve` to the agents" not in not_built
    )  # it exists since part 4a (docs/agents.md)
    assert "It also decides whether the agents may run" not in not_built
    assert "in a subprocess with a wall-clock limit and a memory limit" in not_built
    assert "bt signal check" in not_built  # and the section no longer lists the command itself as missing
    assert "The command `bt signal check`" not in not_built


def test_the_sentence_about_agents_and_the_hardening_is_the_same_in_every_document() -> None:
    sentence = "the only limit of an agent run is the timeout of its own tool"
    unattended = re.compile(
        r"[Ww]hether agents may run (it|the command) unattended is decided in the agents part \(pull request 4\)"
    )
    for name in ("cli", "coded", "adr"):
        assert sentence in FLAT[name] and unattended.search(FLAT[name]), name
    assert "docs/agents.md" in FLAT["cli"] and "docs/agents.md" in FLAT["coded"] and "docs/agents.md" in FLAT["adr"]
    for name, text in FLAT.items():
        assert "precondition" not in text.lower(), name  # it is not a precondition; the agents part decides
    assert "**NOT built**" in FLAT["adr"] or "**Hardening that is NOT built:**" in FLAT["adr"]
    assert "**Not built:** running the candidate in a subprocess" in FLAT["coded"]
    assert "it is **not built**" in FLAT["cli"]


def test_known_gap_6_is_in_the_adr_and_in_the_coded_signals_document() -> None:
    assert "6. **Executing code that nobody approved.**" in ADR
    assert "**Known gap 6: it executes code that nobody approved.**" in CODED
    assert "known gaps 4 and 6" in FLAT["cli"]


def test_the_status_line_of_the_adr_says_that_bt_signal_check_is_built_and_the_agent_files_exist() -> None:
    status = " ".join(ADR[: ADR.index("## Context")].split())
    assert "Phase 10 part 3b, `bt signal check` with `load_candidate`" in status
    assert "the agent files exist (ADR 0019)" in status and "the agents are not built yet" not in status
    assert "only `bt signal check` raises it" in status


# --- CLAUDE.md names the rules that the source-tree tests enforce ---


def test_claude_md_names_the_one_module_that_the_source_tree_tests_allow() -> None:
    assert CANDIDATE_FILES == {LOADER, "cli/signal_check.py"}
    flat = " ".join(CLAUDE.split())
    assert "**Only `cli/signal_check.py` may use `load_candidate` or import `coded/cases.py`**" in flat
    assert "`tests/test_coded_source_tree.py` and `tests/test_cli_docs_coded.py`" in flat
    assert "caches nothing" in flat and "never 8" in flat
    assert "Not built: running a candidate in a subprocess" in flat and "Not built: the agent files" not in flat
    assert "no rule denies the command to an agent yet" not in flat


def test_the_changelog_and_the_readme_name_the_command_and_the_changed_hint() -> None:
    unreleased = CHANGELOG[CHANGELOG.index("## [Unreleased]") : CHANGELOG.index("## [0.1.0]")]
    flat = " ".join(unreleased.split())
    assert "Phase 10 part 3b (F-18), `bt signal check SPEC [--strategies-dir DIR]`" in flat
    assert "It executes the working file, which nobody approved" in flat.replace("**", "")
    assert "One hint for a damaged approval record in every command that reads approvals" in flat
    assert "uv run bt signal check spec.yaml" in README and "EXECUTES the unapproved candidate file" in README


def test_the_new_files_of_part_3b_are_in_the_entry_of_part_3b_and_not_in_the_entry_of_part_3() -> None:
    """Each entry has its own ``New files:`` sentence; the entries under ``### Added`` run 4a, 3b, 3, 2b."""
    added = CHANGELOG[CHANGELOG.index("### Added") : CHANGELOG.index("### Changed")]
    entries = re.split(r"(?m)^(?=- Phase 10 part )", added)[1:]
    by_part = {entry.split(" (F-18)")[0].removeprefix("- Phase 10 part "): entry for entry in entries}
    assert list(by_part)[:4] == ["4a", "3b", "3", "2b"]  # 4a is the first entry, 3b the second
    part_3b, part_3 = by_part["3b"], by_part["3"]
    sentence = [line for line in part_3b.splitlines() if line.startswith("  New files:")]
    assert len(sentence) == 1 and "`src/backtest_agent/cli/signal_check.py`" in sentence[0]
    assert part_3b.index("  New files:") < part_3b.index("No new dependency.")
    assert "signal_check" not in part_3
    assert part_3.count("  New files:") == 1 and "`src/backtest_agent/cli/coded.py`" in part_3


def test_the_adr_addendum_says_what_it_changed_above_and_the_readme_lists_the_command() -> None:
    assert (
        "No rule above changes; only the sentences that said that the command is not built were corrected."
        in FLAT["adr"]
    )
    assert "nothing above changes" not in FLAT["adr"]
    assert (
        "`bt approve` and `bt signal check` with the approval gate for coded signals (Phase 10, in progress) exist"
        in FLAT["readme"]
    )
    assert "`rebuild` (Phase 9), `approve` and `signal check` (Phase 10)" in FLAT["readme"]
