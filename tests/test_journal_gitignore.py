"""``runs/`` never reaches the public repository (docs/journal.md, "Layout")."""

import shutil
import subprocess

import pytest

from journal_helpers import REPO_ROOT, no_repo_runs  # noqa: F401 - fixture used through pytestmark

pytestmark = pytest.mark.usefixtures("no_repo_runs")


def test_gitignore_lists_the_runs_folder() -> None:
    lines = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/runs/" in lines


@pytest.mark.skipif(shutil.which("git") is None or not (REPO_ROOT / ".git").exists(), reason="no git checkout")
@pytest.mark.parametrize(
    "path",
    ["runs/20260115T103001Z-sma-a-5ef0aaa5/run.json", "runs/index.sqlite", "runs/.tmp-x-1234/spec.yaml", "runs/x"],
)
def test_git_ignores_everything_under_runs(path) -> None:
    done = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT, capture_output=True, check=False)
    assert done.returncode == 0, f"git would not ignore {path}"


@pytest.mark.skipif(shutil.which("git") is None or not (REPO_ROOT / ".git").exists(), reason="no git checkout")
def test_git_does_not_ignore_a_folder_that_only_looks_like_runs() -> None:
    done = subprocess.run(["git", "check-ignore", "-q", "src/runs/x"], cwd=REPO_ROOT, capture_output=True, check=False)
    assert done.returncode == 1  # the rule is anchored to the root: /runs/
