"""The real ``bt run strategies/sma_crossover.yaml`` against yfinance, in a temporary folder (run it by hand).

`uv run pytest -m network tests/test_cli_network.py`. It goes through the installed script with the defaults, so the
folders `runs`, `reports` and `data/cache` appear in the temporary working directory and nowhere else.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(sys.executable).parent / ("bt.exe" if sys.platform == "win32" else "bt")


@pytest.mark.network
def test_bt_run_the_sma_crossover_example(tmp_path: Path) -> None:
    spec = REPO_ROOT / "strategies" / "sma_crossover.yaml"
    result = subprocess.run(
        [str(SCRIPT), "run", str(spec)], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=900
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].startswith("Run:        ")
    assert lines[1] == "Strategy:   SMA crossover on liquid ETFs (family sma_crossover)"
    run_id = lines[0].split()[1]
    assert (tmp_path / "runs" / run_id / "run.json").is_file()
    assert (tmp_path / "reports" / run_id / "report.html").is_file()
    assert (tmp_path / "data" / "cache").is_dir()
    assert not (REPO_ROOT / "runs" / run_id).exists()
