"""The code version: commit and dirty flag from git, never failing (docs/journal.md, "Code version")."""

import shutil
import subprocess
from pathlib import Path

import pytest

import backtest_agent
from backtest_agent.journal import CodeVersion, detect_code_version
from journal_helpers import no_repo_runs  # noqa: F401 - fixture used through pytestmark

pytestmark = pytest.mark.usefixtures("no_repo_runs")

COMMIT = "0123456789abcdef0123456789abcdef01234567"
UNKNOWN = CodeVersion("unknown", None)


class FakeGit:
    """A stand-in for ``subprocess.run``: answers by git subcommand and records every call."""

    def __init__(self, tmp_path: Path, *, top=None, head=COMMIT + "\n", status="", returncodes=None, raises=None):
        self.package = tmp_path / "repo" / "src" / "backtest_agent"
        self.package.mkdir(parents=True)
        self.top = tmp_path / "repo" if top is None else top
        self.answers = {"--show-toplevel": str(self.top) + "\n", "HEAD": head, "--porcelain": status}
        self.returncodes = returncodes or {}
        self.raises = raises
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if self.raises is not None:
            raise self.raises
        key = command[-1]
        return subprocess.CompletedProcess(command, self.returncodes.get(key, 0), self.answers[key], "")


def test_the_commit_and_a_clean_tree(tmp_path) -> None:
    git = FakeGit(tmp_path)
    assert detect_code_version(git.package, run=git) == CodeVersion(COMMIT, False)


def test_any_change_or_untracked_file_is_dirty(tmp_path) -> None:
    git = FakeGit(tmp_path, status=" M src/backtest_agent/run_id.py\n?? new.py\n")
    assert detect_code_version(git.package, run=git) == CodeVersion(COMMIT, True)


def test_git_runs_in_the_package_directory_without_a_shell_and_with_a_timeout(tmp_path) -> None:
    git = FakeGit(tmp_path)
    detect_code_version(git.package, run=git)
    commands = [command for command, _ in git.calls]
    assert commands == [
        ["git", "rev-parse", "--show-toplevel"],
        ["git", "rev-parse", "HEAD"],
        ["git", "status", "--porcelain"],
    ]
    for _, kwargs in git.calls:
        assert kwargs["cwd"] == git.package.resolve()
        assert kwargs["timeout"] == 10
        assert not kwargs.get("shell", False)
        assert kwargs["check"] is False


@pytest.mark.parametrize(
    "error",
    [FileNotFoundError("git"), PermissionError("denied"), subprocess.TimeoutExpired("git", 10)],
    ids=["no git", "not allowed", "timeout"],
)
def test_git_missing_or_hanging_gives_unknown(tmp_path, error) -> None:
    git = FakeGit(tmp_path, raises=error)
    assert detect_code_version(git.package, run=git) == UNKNOWN


@pytest.mark.parametrize("failing", ["--show-toplevel", "HEAD"])
def test_a_failing_git_gives_unknown(tmp_path, failing) -> None:
    git = FakeGit(tmp_path, returncodes={failing: 128})  # not a repository, no commit yet
    assert detect_code_version(git.package, run=git) == UNKNOWN


def test_a_failing_status_keeps_the_commit_and_leaves_dirty_open(tmp_path) -> None:
    git = FakeGit(tmp_path, returncodes={"--porcelain": 1})
    assert detect_code_version(git.package, run=git) == CodeVersion(COMMIT, None)


@pytest.mark.parametrize("head", ["", "HEAD\n", "xyz\n", COMMIT[:39] + "\n", COMMIT.upper() + "\n"])
def test_something_that_is_not_a_commit_gives_unknown(tmp_path, head) -> None:
    git = FakeGit(tmp_path, head=head)
    assert detect_code_version(git.package, run=git) == UNKNOWN


def test_a_sha256_commit_is_accepted(tmp_path) -> None:
    git = FakeGit(tmp_path, head="ab" * 32 + "\n")
    assert detect_code_version(git.package, run=git) == CodeVersion("ab" * 32, False)


def test_a_package_inside_another_repository_gives_unknown(tmp_path) -> None:
    # for example an installed copy in a virtual environment that sits in some unrelated project
    git = FakeGit(tmp_path, top=tmp_path)  # the top level is not the repository that holds src/backtest_agent
    assert detect_code_version(git.package, run=git) == UNKNOWN


def test_the_real_function_gives_unknown_when_git_is_not_on_the_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    assert detect_code_version() == UNKNOWN


def test_the_default_package_is_this_one(tmp_path) -> None:
    git = FakeGit(tmp_path)
    detect_code_version(run=git)
    assert git.calls[0][1]["cwd"] == Path(backtest_agent.__file__).parent.resolve()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_a_real_repository(tmp_path) -> None:
    repo = tmp_path / "repo"
    package = repo / "src" / "backtest_agent"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")

    def git(*args: str) -> str:
        done = subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
        return done.stdout.strip()

    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "first")
    commit = git("rev-parse", "HEAD")
    assert detect_code_version(package) == CodeVersion(commit, False)
    (package / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    assert detect_code_version(package) == CodeVersion(commit, True)
