"""Ruff leaves approved code alone: it is hashed byte for byte (docs/coded-signals.md, ADR 0018).

If ruff linted ``strategies/signals`` and ``approvals``, CI would fail on code written by an agent, and a local
``ruff format`` would change the bytes after the maintainer reviewed them, so the approval would no longer match the
file.
"""

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BAD_SOURCE = "import os,sys\nx=1;y = 2\ndef f( a ,b ):\n  return a+b\n"  # lints and formats badly on purpose


def test_pyproject_excludes_the_approved_code() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["ruff"]["extend-exclude"] == ["approvals", "strategies/signals"]


def run_ruff(folder: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ruff", *arguments, "--no-cache", "."], cwd=folder, capture_output=True, text=True
    )


def project_with(tmp_path: Path, *bad_files: str) -> Path:
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    for name in bad_files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(BAD_SOURCE.encode("utf-8"))
    return tmp_path


def test_ruff_ignores_bad_files_in_those_folders_and_changes_nothing(tmp_path: Path) -> None:
    folder = project_with(tmp_path, "strategies/signals/x.py", "approvals/code/y.py")
    before = {p: p.read_bytes() for p in folder.rglob("*.py")}
    check = run_ruff(folder, "check")
    assert (check.returncode, check.stdout.strip()) == (0, "All checks passed!"), check.stdout + check.stderr
    format_check = run_ruff(folder, "format", "--check")
    assert format_check.returncode == 0, format_check.stdout + format_check.stderr
    run_ruff(folder, "format")  # even a real format run leaves the bytes alone
    assert {p: p.read_bytes() for p in folder.rglob("*.py")} == before


def test_the_same_bad_file_elsewhere_is_still_found(tmp_path: Path) -> None:
    folder = project_with(tmp_path, "strategies/other.py", "src/z.py")
    check = run_ruff(folder, "check")
    assert check.returncode == 1
    assert "strategies" in check.stdout and "z.py" in check.stdout
    assert run_ruff(folder, "format", "--check").returncode == 1


def test_a_file_in_another_folder_of_strategies_is_not_excluded(tmp_path: Path) -> None:
    folder = project_with(tmp_path, "strategies/examples/bad.py")
    assert run_ruff(folder, "check").returncode == 1
