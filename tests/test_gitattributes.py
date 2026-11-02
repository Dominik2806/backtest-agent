"""Approved code is hashed byte for byte, so its line ends must not change on checkout (docs/coded-signals.md)."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def rules() -> dict[str, list[str]]:
    """Pattern -> attributes of every non-comment line of .gitattributes (later lines win in git, all are listed)."""
    found: dict[str, list[str]] = {}
    for raw in (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            pattern, *attributes = line.split()
            found.setdefault(pattern, []).extend(attributes)
    return found


@pytest.mark.parametrize("pattern", ["approvals/**", "strategies/signals/*.py"])
def test_the_file_has_a_text_eol_lf_line_for_the_approved_code(pattern: str) -> None:
    assert pattern in rules()
    assert {"text", "eol=lf"} <= set(rules()[pattern])


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
@pytest.mark.parametrize(
    "path",
    [
        "approvals/rsi_pullback.json",
        "approvals/code/" + "ab" * 32 + ".py",
        "strategies/signals/rsi_pullback.py",
    ],
)
def test_git_reports_lf_for_those_paths(path: str) -> None:
    done = subprocess.run(
        ["git", "check-attr", "eol", "text", "--", path], cwd=ROOT, capture_output=True, text=True, check=True
    )
    values = {line.split(": ")[1]: line.split(": ")[2] for line in done.stdout.strip().splitlines()}
    assert values == {"eol": "lf", "text": "set"}, done.stdout
