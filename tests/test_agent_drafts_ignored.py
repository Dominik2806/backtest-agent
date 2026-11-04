"""``strategies/drafts/`` holds what the strategy-architect writes; it stays out of the public repository.

Only the empty ``.gitkeep`` is tracked (so the folder exists on a fresh clone). ``strategies/signals`` and
``approvals`` stay tracked on purpose: a person adds them after reading the code (docs/agents.md).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NEEDS_GIT = pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(), reason="no git checkout")


def check_ignore(path: str) -> int:
    return subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT, capture_output=True, check=False).returncode


@NEEDS_GIT
@pytest.mark.parametrize(
    "path", ["strategies/drafts/idea.yaml", "strategies/drafts/a-b_1.yaml", "strategies/drafts/sub/x.yaml"]
)
def test_git_ignores_a_draft(path: str) -> None:
    assert check_ignore(path) == 0, f"git would not ignore {path}"


@NEEDS_GIT
@pytest.mark.parametrize(
    "path",
    [
        "strategies/drafts/.gitkeep",
        "strategies/examples/rsi_pullback.yaml",
        "strategies/signals/rsi_pullback.py",
        "strategies/signals/rsi_pullback.cases.yaml",
        "strategies/sma_crossover.yaml",
        "approvals/rsi_pullback.json",
        "src/strategies/drafts/x.yaml",
    ],
)
def test_git_does_not_ignore_anything_else(path: str) -> None:
    assert check_ignore(path) == 1, f"git would ignore {path}"


def test_the_gitkeep_exists_and_is_empty() -> None:
    assert (ROOT / "strategies" / "drafts" / ".gitkeep").read_bytes() == b""
