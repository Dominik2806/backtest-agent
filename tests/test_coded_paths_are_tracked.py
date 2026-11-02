"""The approved code and the approvals are tracked in git, so public in this repository (docs/coded-signals.md).

Nothing in ``.gitignore`` may hide them; only the lock file of a running approval is ignored.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = "ab" * 32

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def ignored(path: str) -> bool:
    """True if git ignores ``path`` (``git check-ignore`` exits 0), False if not (exit 1); anything else is an error."""
    done = subprocess.run(["git", "check-ignore", "-q", "--", path], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode in (0, 1), done.stderr
    return done.returncode == 0


def test_the_lock_of_a_running_approval_is_ignored() -> None:
    assert ignored("approvals/.lock")


@pytest.mark.parametrize(
    "path",
    [
        "approvals/x_signal.json",
        f"approvals/code/{SHA}.py",
        "approvals/code",
        "approvals",
        "strategies/signals/x_signal.py",
        "strategies/signals/x_signal.cases.yaml",
        "strategies/signals",
        "strategies/some_idea.yaml",
    ],
)
def test_approvals_and_coded_signals_are_not_ignored(path: str) -> None:
    assert not ignored(path)


def test_the_check_sees_a_rule_that_does_ignore() -> None:
    assert ignored("runs/anything.json") and ignored("reports/x/report.md")  # the detector is not always False
