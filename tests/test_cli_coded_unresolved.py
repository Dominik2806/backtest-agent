"""What ``bt validate`` and ``bt run`` say today about a spec with a ``coded`` block that was not resolved.

(docs/coded-signals.md, "What `bt validate` will say".) The message comes from ``SignalSpec.resolve_signal`` and is
printed by ``cli/__init__.py`` as ``bt: error: <message>``; ``cli/errors.py`` maps ``UnknownSignalError`` to exit
code 3. The commands that resolve a coded spec (``bt approve``, ``bt signal check``) are not built yet; when
``bt validate`` learns to print a ``Signal:`` line for a coded spec, this test changes with it.
"""

from pathlib import Path

import pytest
import yaml

from backtest_agent.data import FakeProvider
from cli_helpers import run_cli
from coded_helpers import coded_spec

MESSAGE = "bt: error: the coded signal 'rsi_pullback' is not resolved; it has to pass the approval gate first\n"


@pytest.fixture
def spec_file(tmp_path: Path) -> Path:
    path = tmp_path / "coded.yaml"
    path.write_text(yaml.safe_dump(coded_spec("rsi_pullback").to_dict(), sort_keys=False), encoding="utf-8")
    return path


def test_validate_prints_the_message_and_exits_3(spec_file: Path) -> None:
    outcome = run_cli(["validate", str(spec_file)])
    assert (outcome.code, outcome.out, outcome.err) == (3, "", MESSAGE)


def test_run_prints_the_same_message_and_exits_3_without_touching_the_data_or_the_folders(
    spec_file: Path, tmp_path: Path
) -> None:
    provider = FakeProvider(symbols=("AAA", "BBB"))
    runs, reports = tmp_path / "runs", tmp_path / "reports"
    outcome = run_cli(
        ["run", str(spec_file), "--runs-dir", str(runs), "--reports-dir", str(reports)], provider=provider
    )
    assert (outcome.code, outcome.out, outcome.err) == (3, "", MESSAGE)
    assert provider.calls == [] and not runs.exists() and not reports.exists()


def test_the_traceback_only_comes_with_debug_and_the_code_stays_3(spec_file: Path) -> None:
    outcome = run_cli(["validate", str(spec_file), "--debug"])
    assert outcome.code == 3
    assert outcome.err.endswith(MESSAGE)
    assert "Traceback (most recent call last)" in outcome.err and "UnknownSignalError" in outcome.err
