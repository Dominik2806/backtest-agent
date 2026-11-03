"""What ``bt validate`` and ``bt run`` say about a coded spec that nothing has approved yet.

(docs/coded-signals.md, "What `bt validate` says".) ``bt validate`` prints a ``Signal:`` line from the approval record
and exits 0; ``bt run`` stops at the gate with exit code 8, before any data is requested and before anything is written.
The states in between, the data commands and the canaries have their own files (``test_cli_validate_coded.py``,
``test_cli_run_coded.py``).
"""

from pathlib import Path

import pytest
import yaml

from backtest_agent.data import FakeProvider
from cli_helpers import run_cli
from coded_helpers import coded_spec, registry_and_modules_are_restored  # noqa: F401 - autouse fixture

MESSAGE = "bt: error: the idea of 'rsi_pullback' is not approved: there is no approval record\n"
HINT = "hint: approvals are made with bt approve; see docs/coded-signals.md\n"


@pytest.fixture
def spec_file(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "coded.yaml"
    path.write_text(yaml.safe_dump(coded_spec("rsi_pullback").to_dict(), sort_keys=False), encoding="utf-8")
    return path


def test_validate_says_that_the_idea_is_not_approved_and_exits_0(spec_file: Path) -> None:
    outcome = run_cli(["validate", "coded.yaml"])
    assert (outcome.code, outcome.err) == (0, "")
    assert outcome.out.splitlines() == [
        "OK: coded.yaml is a valid spec",
        "Name:       SMA test",
        "Family:     rsi_pullback",
        "Signal:     coded, idea not approved",
        "Universe:   AAA, BBB",
        "Benchmark:  AAA",
        "Period:     2024-03-01 to 2024-04-30",
        "Warm-up:    n/a (coded signal, not loaded)",
        "Risk flags: none",
    ]


def test_run_stops_at_the_gate_with_exit_8_without_touching_the_data_or_the_folders(
    spec_file: Path, tmp_path: Path
) -> None:
    provider = FakeProvider(symbols=("AAA", "BBB"))
    runs, reports = tmp_path / "runs", tmp_path / "reports"
    outcome = run_cli(["run", "coded.yaml", "--runs-dir", str(runs), "--reports-dir", str(reports)], provider=provider)
    assert (outcome.code, outcome.out, outcome.err) == (8, "", MESSAGE + HINT)
    assert provider.calls == [] and not runs.exists() and not reports.exists()
    assert not (tmp_path / "approvals").exists()  # a refusal creates nothing


def test_the_traceback_only_comes_with_debug_and_the_code_stays_8(spec_file: Path) -> None:
    outcome = run_cli(["run", "coded.yaml", "--debug"])
    assert outcome.code == 8
    assert outcome.err.endswith(MESSAGE + HINT)
    assert "Traceback (most recent call last)" in outcome.err and "NotApprovedError" in outcome.err
