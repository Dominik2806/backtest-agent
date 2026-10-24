"""The real ``bt run strategies/sma_crossover.yaml`` against yfinance, in a temporary folder (run it by hand).

`uv run pytest -m network tests/test_cli_network.py`. It goes through the installed script with the defaults, so the
folders `runs`, `reports` and `data/cache` appear in the temporary working directory and nowhere else.
"""

import json
import re
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


SHORT_SPEC = """\
schema_version: 1
name: Live round trip
universe: [SPY, GLD]
period: {start: 2023-03-01, end: 2023-03-31}
data: {provider: yfinance}
signal: {id: buy_and_hold, params: {}}
execution: {delay_bars: 1, price: open, allow_same_bar_execution: false}
sizing: {method: equal_weight}
rebalance: on_signal
costs: {commission_bps: 1.0, spread_bps: 2.0, slippage_bps: 2.0}
benchmark: SPY
initial_capital: 100000
"""
REPORT_FILES = ("report.md", "report.html", "equity.svg", "drawdown.svg")


def bt(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=900)


@pytest.mark.network
def test_data_fetch_run_and_report_round_trip_on_one_cache(tmp_path: Path) -> None:
    """A period far in the past is cached: fetch fills the cache, run and report are served from it and agree."""
    spec = tmp_path / "spec.yaml"
    spec.write_text(SHORT_SPEC, encoding="utf-8")
    cache, runs = tmp_path / "cache", tmp_path / "runs"
    first, second = tmp_path / "reports-1", tmp_path / "reports-2"

    fetched = bt(tmp_path, "data", "fetch", str(spec), "--cache-dir", str(cache))
    assert fetched.returncode == 0, fetched.stderr
    rows = re.findall(r"^  (\S+)\s+(\d+) rows?$", fetched.stdout, flags=re.MULTILINE)
    assert [symbol for symbol, _ in rows] == ["SPY", "GLD", "SPY"]  # the universe, then the benchmark
    assert all(int(count) > 0 for _, count in rows)
    hashes = re.findall(r"^  Data:     ([0-9a-f]{64})$", fetched.stdout, flags=re.MULTILINE)
    assert len(hashes) == 2

    ran = bt(
        tmp_path, "run", str(spec), "--runs-dir", str(runs), "--reports-dir", str(first), "--cache-dir", str(cache)
    )
    assert ran.returncode == 0, ran.stderr
    run_id = ran.stdout.splitlines()[0].split()[1]
    stored = json.loads((runs / run_id / "run.json").read_text(encoding="utf-8"))
    assert [stored["evaluation"]["strategy"]["data_hash"], stored["evaluation"]["benchmark"]["data_hash"]] == hashes

    journal_before = sorted(path.relative_to(runs).as_posix() for path in runs.rglob("*"))
    run_json = (runs / run_id / "run.json").read_bytes()
    reported = bt(
        tmp_path, "report", run_id, "--runs-dir", str(runs), "--reports-dir", str(second), "--cache-dir", str(cache)
    )
    assert reported.returncode == 0, reported.stderr
    for name in REPORT_FILES:
        assert (second / run_id / name).read_bytes() == (first / run_id / name).read_bytes(), name
    assert sorted(path.relative_to(runs).as_posix() for path in runs.rglob("*")) == journal_before  # nothing logged
    assert (runs / run_id / "run.json").read_bytes() == run_json
