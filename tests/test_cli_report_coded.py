"""``bt report`` of a coded run: the gate in stored mode (the archive of the pinned hash, never the working file).

The world is the coded twin of fixture R3b (``coded_cli_helpers``). Between the run and the report the registry is
emptied of the signal, which is what a new process looks like; only the stored mode of the gate can bring it back.
"""

import hashlib
import json
import re
from pathlib import Path

import pytest

from backtest_agent.coded.loader import clear_checked
from backtest_agent.spec import SIGNALS
from cli_helpers import at, run_cli
from coded_cli_helpers import HOLD_A, SHA_A, approve_all, put_source, write_hold_spec
from coded_helpers import (
    canary_source,
    coded_modules,
    registry_and_modules_are_restored,  # noqa: F401 - autouse fixture
)
from report_helpers import world as r3b_world
from runner_helpers import LiteralProvider

RUN_ID = re.compile(r"20260115T1030(?P<second>\d\d)Z-buy-and-hold-a-[0-9a-f]{8}")
RECORD_HINT = "hint: the approvals folder (--approvals-dir) has to hold the record and the archived code this run used"


@pytest.fixture
def run_id(tmp_path: Path, monkeypatch) -> str:
    """A logged coded run, after which the registry is back to what a new process has (no hold_a)."""
    monkeypatch.chdir(tmp_path)
    write_hold_spec(tmp_path)
    approve_all(tmp_path, HOLD_A, "8b0b3234")
    result = run_cli(["run", "spec.yaml"], provider=LiteralProvider(r3b_world()), clock=at(0))
    assert result.code == 0, result.err
    found = RUN_ID.search(result.out)
    assert found
    forget_the_signal()
    return found.group(0)


def forget_the_signal() -> None:
    if "hold_a" in SIGNALS:
        SIGNALS.unregister("hold_a")
    clear_checked()
    assert "hold_a" not in SIGNALS


def edit_the_stored_spec(tmp_path: Path, run_id: str, edit) -> None:
    """Change the spec in run.json and keep the file consistent: the journal refuses a record whose
    ``trial.variant_hash`` is not the hash of its spec (sha256 of the canonical JSON without name and description)."""
    path = tmp_path / "runs" / run_id / "run.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data["spec"])
    payload = {key: value for key, value in data["spec"].items() if key not in ("name", "description")}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    data["trial"]["variant_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    path.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def report(*args: str):
    return run_cli(["report", *args], provider=LiteralProvider(r3b_world()))


def test_the_report_reproduces_after_the_registry_was_emptied(run_id: str, tmp_path: Path) -> None:
    """Only the stored mode of the gate can register the signal again, from the archive of the pinned hash."""
    original = (tmp_path / "reports" / run_id / "report.md").read_bytes()
    result = report(run_id, "--overwrite")
    assert (result.code, result.err) == (0, "")
    assert result.out.splitlines() == [
        f"Run:        {run_id}",
        "Checked:    spec, evaluation, trades and costs equal the journal record",
        f"Journal:    runs/{run_id}/run.json (unchanged)",
        f"Report:     reports/{run_id}/report.md and report.html",
    ]
    assert (tmp_path / "reports" / run_id / "report.md").read_bytes() == original
    assert SIGNALS.get("hold_a").sha256 == SHA_A


def test_an_edited_working_file_does_not_matter_and_is_not_executed(run_id: str, tmp_path: Path, world) -> None:
    put_source(tmp_path, canary_source("hold_a"))  # the editable file is replaced by a canary
    ids = SIGNALS.ids()
    result = report(run_id, "--overwrite")
    assert (result.code, result.err) == (0, "")
    assert world.marker_lines() == [] and coded_modules() == []
    assert sorted(SIGNALS.ids()) == sorted([*ids, "hold_a"])  # the gate registered the archived signal, nothing else
    assert SIGNALS.get("hold_a").sha256 == SHA_A


def test_a_missing_working_file_does_not_matter(run_id: str, tmp_path: Path) -> None:
    (tmp_path / "strategies" / "signals" / "hold_a.py").unlink()
    assert report(run_id, "--overwrite").code == 0


def test_the_report_never_logs_and_never_writes_into_the_journal(run_id: str, tmp_path: Path) -> None:
    before = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in (tmp_path / "runs").rglob("*") if p.is_file()}
    assert report(run_id, "--overwrite").code == 0
    after = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in (tmp_path / "runs").rglob("*") if p.is_file()}
    assert after == before


def test_a_changed_archive_is_exit_5(run_id: str, tmp_path: Path) -> None:
    archive = tmp_path / "approvals" / "code" / f"{SHA_A}.py"
    archive.write_bytes(archive.read_bytes() + b"# edited\n")
    result = report(run_id, "--overwrite")
    assert (result.code, result.out) == (5, "")
    assert result.err.splitlines() == [
        "bt: error: the archived code 8b0b3234 does not match its hash; the archive was changed",
        RECORD_HINT,
    ]
    assert "hold_a" not in SIGNALS


def test_a_missing_archive_is_exit_5(run_id: str, tmp_path: Path) -> None:
    (tmp_path / "approvals" / "code" / f"{SHA_A}.py").unlink()
    result = report(run_id, "--overwrite")
    assert (result.code, result.out) == (5, "")
    assert result.err.splitlines() == ["bt: error: the archived code 8b0b3234 is missing", RECORD_HINT]


def test_a_missing_record_is_exit_5(run_id: str, tmp_path: Path) -> None:
    (tmp_path / "approvals" / "hold_a.json").unlink()
    result = report(run_id, "--overwrite")
    assert (result.code, result.out) == (5, "")
    assert result.err.splitlines() == [
        "bt: error: the idea of 'hold_a' is not approved: there is no approval record",
        RECORD_HINT,
    ]


def test_a_stored_spec_without_a_pin_cannot_be_reproduced_exit_5(run_id: str, tmp_path: Path) -> None:
    edit_the_stored_spec(tmp_path, run_id, lambda spec: spec["signal"]["coded"].pop("code_sha256"))
    result = report(run_id, "--overwrite")
    assert (result.code, result.out) == (5, "")
    assert result.err.splitlines() == [
        "bt: error: the spec of 'hold_a' pins no code_sha256, so the run cannot be reproduced from its record",
        RECORD_HINT,
    ]


def test_params_that_no_longer_fit_the_archived_code_are_a_stored_spec_that_does_not_validate_exit_3(
    run_id: str, tmp_path: Path
) -> None:
    # the archived code allows 0.0 to 1.0
    edit_the_stored_spec(tmp_path, run_id, lambda spec: spec["signal"].update(params={"scale": 5.0}))
    result = report(run_id, "--overwrite")
    assert (result.code, result.out) == (3, "")
    lines = result.err.splitlines()
    assert lines[0] == f"bt: error: the stored spec of run {run_id} no longer validates (1 problem):"
    assert lines[-1] == (
        "hint: the run folder is untouched; the spec schema or a signal changed since the run (docs/strategy-spec.md)"
    )


def test_the_approvals_folder_option_is_used(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_hold_spec(tmp_path)
    options = ("--approvals-dir", "appr")
    approve_all(tmp_path, HOLD_A, "8b0b3234", options=options)
    first = run_cli(["run", "spec.yaml", *options], provider=LiteralProvider(r3b_world()), clock=at(0))
    assert first.code == 0, first.err
    found = RUN_ID.search(first.out)
    assert found
    forget_the_signal()
    assert report(found.group(0), "--overwrite").code == 5  # the default folder "approvals" does not exist
    forget_the_signal()
    assert report(found.group(0), "--overwrite", *options).code == 0
