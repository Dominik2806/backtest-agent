"""The records of Phase 10 part 4b: the ROADMAP entry, the CHANGELOG entry and the lists of files they name.

The lists are checked against a literal (the files of the part) and, where git has a ``main`` to compare with,
against ``git diff --name-only`` of the branch, so that a file added or changed later has to be listed. The numbers
of the ROADMAP list (lines added/deleted) are rewritten by a script outside the repository until they are stable;
they are not tested here.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROADMAP = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
ENTRY = ROADMAP[
    ROADMAP.index("- Phase 10 part 4b (`feature/agents-architect-coder`)") : ROADMAP.index("\n---\n\n## Phase 0")
]
LOG = CHANGELOG[CHANGELOG.index("- Phase 10 part 4b (F-18)") : CHANGELOG.index("- Phase 10 part 4a (F-18)")]
PATH = re.compile(r"`([A-Za-z0-9_./-]+\.[a-z]+)`")

CHANGED = {
    ".claude/hooks/restrict_writes.py",
    "tests/restrict_writes_helpers.py",
    "tests/test_agents_docs.py",
    "tests/test_cli_docs_coded.py",
    "tests/test_cli_docs_signal_check.py",
    "tests/test_restrict_writes.py",
    "CHANGELOG.md",
    "CLAUDE.md",
    "README.md",
    "docs/ROADMAP.md",
    "docs/adr/0018-coded-signals-and-approval-gate.md",
    "docs/adr/0019-agents-and-their-guardrails.md",
    "docs/agents.md",
    "docs/cli.md",
    "docs/coded-signals.md",
}
NEW = {
    ".claude/agents/signal-coder.md",
    ".claude/agents/strategy-architect.md",
    "strategies/examples/rsi_pullback.yaml",
    "strategies/examples/trend_filter_etfs.yaml",
    "strategies/examples/vol_filtered_trend.yaml",
    "tests/fake_agents.py",
    "tests/test_agent_examples.py",
    "tests/test_agent_files.py",
    "tests/test_agents_end_to_end.py",
    "tests/test_phase_10_docs.py",
}


def paths(text: str) -> set[str]:
    return set(PATH.findall(text))


def roadmap_lists() -> tuple[set[str], set[str]]:
    changed_block = ENTRY[ENTRY.index("Every file that existed before part 4b") : ENTRY.index("  - **New files**")]
    return paths(" ".join(re.findall(r"`[^`]+` \(\+\d+/-\d+", changed_block))), paths(
        ENTRY[ENTRY.index("  - **New files**") :]
    )


def changelog_lists() -> tuple[set[str], set[str]]:
    changed = [line for line in LOG.splitlines() if line.startswith("  Changed files:")]
    new = [line for line in LOG.splitlines() if line.startswith("  New files:")]
    assert len(changed) == 1 and len(new) == 1
    return paths(changed[0]), paths(new[0])


def test_the_roadmap_lists_are_the_files_of_the_part() -> None:
    assert roadmap_lists() == (CHANGED, NEW)


def test_the_changelog_lists_are_the_files_of_the_part() -> None:
    assert changelog_lists() == (CHANGED, NEW)


def git(*args: str) -> str | None:
    try:
        done = subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def test_the_lists_equal_the_files_the_branch_changed_since_main() -> None:
    base, head = git("merge-base", "main", "HEAD"), git("rev-parse", "HEAD")
    if base is None or head is None or base == head:
        pytest.skip("no main to compare with, or this is main")
    names = {}
    for kind in ("M", "A"):
        found = git("diff", base, "--name-only", f"--diff-filter={kind}")
        assert found is not None
        names[kind] = set(found.splitlines())
    names["A"] |= {name for name in (git("ls-files", "--others", "--exclude-standard") or "").splitlines() if name}
    assert (names["M"], names["A"]) == (CHANGED, NEW)


def test_the_roadmap_entry_records_the_deviations_of_part_4b_and_none_of_the_earlier_ones() -> None:
    flat = " ".join(ENTRY.split())
    for needle in (
        "**`SubagentHandback` is allowed by the hook.**",
        "**The prompts name `uv run bt ...`**",
        "no longer says to switch the permission mode",
        "**The fake agents are scripts that run both lines of the hook, and model nothing else.**",
        "It does not model the ask rule, the deny rules, the `tools` list or the settings matcher",
        "**The three example ideas are specs in `strategies/examples/`, not text in `docs/agents.md`.**",
        "**The default permission mode was not reached on the maintainer's machine**",
    ):
        assert needle in flat, needle
    assert "became cases.yaml" not in flat and "became an allowlist hook" not in flat
    assert "tests became" not in flat and "Phase 10 is Done" in flat


def test_the_changelog_entry_is_dated_and_says_what_the_probe_found() -> None:
    flat = " ".join(LOG.split())
    assert "No new dependency. Date: 2026-11-04." in flat
    assert "the hook now allows that one name for the two agents (found by the probe, not planned)" in flat
    assert "still refuses every other tool name it does not know" in flat
    assert "the fences stay fences, not boundaries" in flat and "No new dependency." in flat
    added = CHANGELOG[CHANGELOG.index("### Added") : CHANGELOG.index("### Changed")]
    assert added.index("Phase 10 part 4b (F-18)") < added.index("Phase 10 part 4a (F-18)")
