"""The real entry points: ``python -m backtest_agent`` and the installed ``bt`` script (no network)."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(sys.executable).parent / ("bt.exe" if sys.platform == "win32" else "bt")


def _run(command: list[str], cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=120)


def test_python_dash_m_prints_the_help() -> None:
    result = _run([sys.executable, "-I", "-m", "backtest_agent", "--help"])
    assert result.returncode == 0
    assert result.stdout.startswith("usage: bt ")


def test_the_installed_script_prints_the_help() -> None:
    if not SCRIPT.exists():
        pytest.skip("the bt script is not installed in this environment (run uv sync)")
    result = _run([str(SCRIPT), "--help"])
    assert result.returncode == 0
    assert result.stdout.startswith("usage: bt ")


def test_the_installed_script_returns_the_usage_exit_code() -> None:
    if not SCRIPT.exists():
        pytest.skip("the bt script is not installed in this environment (run uv sync)")
    result = _run([str(SCRIPT), "no-such-command"])
    assert result.returncode == 2
    assert result.stdout == ""
