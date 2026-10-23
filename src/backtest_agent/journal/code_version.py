"""The code version of a run: the git commit of this package and a dirty flag (docs/journal.md, "Code version")."""

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import backtest_agent

UNKNOWN = "unknown"
GIT_TIMEOUT_SECONDS = 10
_COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


@dataclass(frozen=True)
class CodeVersion:
    commit: str  # 40 (or 64) hex characters, or "unknown"
    dirty: bool | None  # None if unknown

    def to_dict(self) -> dict[str, str | bool | None]:
        return {"commit": self.commit, "dirty": self.dirty}


UNKNOWN_VERSION = CodeVersion(UNKNOWN, None)


def _git(run: Callable[..., subprocess.CompletedProcess], args: list[str], cwd: Path) -> str | None:
    """stdout of a git command without its final newline, or None for any failure (no git, no repository, timeout)."""
    try:
        done = run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.rstrip("\r\n")


def detect_code_version(
    package_dir: Path | None = None, *, run: Callable[..., subprocess.CompletedProcess] = subprocess.run
) -> CodeVersion:
    """The commit and dirty flag of the repository that contains this package, ``unknown`` if there is none.

    git runs with the package directory as working directory and no shell. The commit is accepted only if the git
    top-level directory holds this package at ``src/backtest_agent``: an installed copy that sits inside some other
    repository must not report that repository's commit. Never raises. ``dirty`` is True if git reports any change or
    untracked file that it does not ignore. ``package_dir`` and ``run`` exist so tests do not depend on the real repo.
    """
    package = (package_dir if package_dir is not None else Path(backtest_agent.__file__).parent).resolve()
    top = _git(run, ["rev-parse", "--show-toplevel"], package)
    if not top or (Path(top) / "src" / "backtest_agent").resolve() != package:
        return UNKNOWN_VERSION
    commit = _git(run, ["rev-parse", "HEAD"], package)
    if commit is None or not _COMMIT.fullmatch(commit):
        return UNKNOWN_VERSION
    status = _git(run, ["status", "--porcelain"], package)
    return CodeVersion(commit, None if status is None else bool(status.strip()))
