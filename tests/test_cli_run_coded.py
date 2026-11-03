"""``bt run`` with a coded spec: the gate in run mode, the journal, and what is refused before any data is requested.

The world is the coded twin of fixture R3b (``coded_cli_helpers``): ``hold_a`` does what ``buy_and_hold`` does, so the
printed numbers are the literals of docs/cli.md. Hashes are literals computed with ``hashlib`` outside the project.
"""

import hashlib
import json
import re
from pathlib import Path

import pytest
import yaml

from backtest_agent.coded.loader import clear_checked
from backtest_agent.spec import SIGNALS
from cli_helpers import at, run_cli
from coded_cli_helpers import (
    FIRST,
    HOLD_A,
    HOLD_B,
    NEW_VARIANT,
    REPEAT,
    SHA_A,
    SHA_B,
    VARIANT_A,
    VARIANT_B,
    approve_all,
    logged_spec,
    put_source,
    summary,
    write_hold_spec,
)
from coded_helpers import (
    canary_source,
    coded_modules,
    registry_and_modules_are_restored,  # noqa: F401 - autouse fixture
)
from report_helpers import world as r3b_world
from runner_helpers import LiteralProvider

RUN_ID = re.compile(r"20260115T1030(?P<second>\d\d)Z-buy-and-hold-a-(?P<hash>[0-9a-f]{8})")
NEUTRAL_HINT = "hint: approvals are made with bt approve; see docs/coded-signals.md"


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    write_hold_spec(tmp_path)
    return tmp_path


def provider() -> LiteralProvider:
    return LiteralProvider(r3b_world())


def run_id_of(out: str) -> str:
    match = RUN_ID.search(out)
    assert match, out
    return match.group(0)


def stored(workdir: Path, run_id: str) -> dict:
    return json.loads((workdir / "runs" / run_id / "run.json").read_text(encoding="utf-8"))


def test_a_coded_buy_and_hold_prints_the_numbers_of_docs_cli_md(workdir: Path) -> None:
    approve_all(workdir, HOLD_A, "8b0b3234")
    spec_before = (workdir / "spec.yaml").read_bytes()
    result = run_cli(["run", "spec.yaml"], provider=provider(), clock=at(0))
    assert (result.code, result.err) == (0, "")
    run_id = run_id_of(result.out)
    assert result.out.splitlines() == summary(run_id, "hold_a", FIRST)
    assert (workdir / "spec.yaml").read_bytes() == spec_before  # the command never edits the spec
    assert (workdir / "reports" / run_id / "report.md").is_file()


def test_run_json_stores_the_resolved_spec_and_the_family_is_the_signal_id(workdir: Path) -> None:
    approve_all(workdir, HOLD_A, "8b0b3234")
    run_id = run_id_of(run_cli(["run", "spec.yaml"], provider=provider(), clock=at(0)).out)
    record = stored(workdir, run_id)
    assert record["spec"] == logged_spec(SHA_A)  # code_sha256 set, brief, params with their defaults
    assert record["family"] == "hold_a"
    assert record["trial"] == {
        "new_variant": True,
        "run_number": 1,
        "trial_count": 1,
        "trial_number": 1,
        "variant_hash": VARIANT_A,
    }
    assert yaml.safe_load((workdir / "runs" / run_id / "spec.yaml").read_text(encoding="utf-8")) == logged_spec(SHA_A)


def test_the_counters_a_repeat_with_a_pinned_spec_and_a_new_variant_after_a_code_change(workdir: Path) -> None:
    approve_all(workdir, HOLD_A, "8b0b3234")
    write_hold_spec(workdir, "pinned.yaml", pin=SHA_A)
    first = run_cli(["run", "spec.yaml"], provider=provider(), clock=at(0))
    second = run_cli(["run", "pinned.yaml"], provider=provider(), clock=at(1))  # the same spec, pinned
    assert second.code == 0, second.err
    first_id, second_id = run_id_of(first.out), run_id_of(second.out)
    assert second.out.splitlines() == summary(second_id, "hold_a", REPEAT)
    assert stored(workdir, second_id)["trial"] == {
        "new_variant": False,
        "run_number": 2,
        "trial_count": 1,
        "trial_number": 1,
        "variant_hash": VARIANT_A,  # an unpinned spec and the same spec pinned are one variant
    }
    assert stored(workdir, second_id)["spec"] == stored(workdir, first_id)["spec"] == logged_spec(SHA_A)

    # another code of the same idea, approved: a new hash in the resolved spec is a new variant (a new trial)
    put_source(workdir, HOLD_B)
    assert run_cli(["approve", "spec.yaml", "--code", "--sha", "3d693599"]).code == 0
    third = run_cli(["run", "spec.yaml"], provider=provider(), clock=at(2))
    assert third.code == 0, third.err
    third_id = run_id_of(third.out)
    assert third.out.splitlines() == summary(third_id, "hold_a", NEW_VARIANT)
    assert stored(workdir, third_id)["spec"] == logged_spec(SHA_B)
    assert stored(workdir, third_id)["trial"] == {
        "new_variant": True,
        "run_number": 3,
        "trial_count": 2,
        "trial_number": 2,
        "variant_hash": VARIANT_B,
    }


def test_a_spec_pinned_to_an_older_hash_is_refused_when_the_file_changed(workdir: Path) -> None:
    approve_all(workdir, HOLD_A, "8b0b3234")
    write_hold_spec(workdir, "old.yaml", pin=SHA_A)
    put_source(workdir, HOLD_B)
    assert run_cli(["approve", "old.yaml", "--code", "--sha", "3d693599"]).code == 0
    result = run_cli(["run", "old.yaml"], provider=provider(), clock=at(0))
    assert (result.code, result.out) == (8, "")
    assert result.err.splitlines() == [
        "bt: error: the spec pins 8b0b3234 but strategies/signals/hold_a.py has sha 3d693599",
        NEUTRAL_HINT,
    ]
    assert not (workdir / "runs").exists() and not (workdir / "reports").exists()


def test_the_folder_options_are_used(workdir: Path) -> None:
    options = ("--approvals-dir", "appr", "--strategies-dir", "src_signals")
    approve_all(workdir, HOLD_A, "8b0b3234", options=options)
    result = run_cli(["run", "spec.yaml", *options], provider=provider(), clock=at(0))
    assert result.code == 0, result.err
    assert (workdir / "appr" / "hold_a.json").is_file() and not (workdir / "approvals").exists()
    assert stored(workdir, run_id_of(result.out))["spec"] == logged_spec(SHA_A)


# --- refusals: nothing is requested and nothing is written ---


def untouched(workdir: Path, data: LiteralProvider) -> None:
    assert data.calls == []
    assert not (workdir / "runs").exists() and not (workdir / "reports").exists()


def test_nothing_approved_is_exit_8_before_any_data_is_requested(workdir: Path) -> None:
    put_source(workdir, HOLD_A)
    data = provider()
    result = run_cli(["run", "spec.yaml"], provider=data)
    assert (result.code, result.out) == (8, "")
    assert result.err.splitlines() == [
        "bt: error: the idea of 'hold_a' is not approved: there is no approval record",
        NEUTRAL_HINT,
    ]
    untouched(workdir, data)


def test_an_idea_without_approved_code_is_exit_8(workdir: Path) -> None:
    put_source(workdir, HOLD_A)
    assert run_cli(["approve", "spec.yaml", "--idea"]).code == 0
    data = provider()
    result = run_cli(["run", "spec.yaml"], provider=data)
    assert (result.code, result.out) == (8, "")
    assert result.err.splitlines() == ["bt: error: code not approved: the file has sha 8b0b3234", NEUTRAL_HINT]
    untouched(workdir, data)


def test_a_changed_brief_is_exit_8(workdir: Path) -> None:
    approve_all(workdir, HOLD_A, "8b0b3234")
    data = yaml.safe_load((workdir / "spec.yaml").read_text(encoding="utf-8"))
    data["signal"]["coded"]["brief"] = "Another brief."
    (workdir / "spec.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    provider_ = provider()
    result = run_cli(["run", "spec.yaml"], provider=provider_)
    assert (result.code, result.out) == (8, "")
    assert result.err.splitlines()[0] == (
        "bt: error: the brief of 'hold_a' changed since it was approved: no approved idea has this brief"
    )
    untouched(workdir, provider_)


def test_a_debug_traceback_names_the_gate_error_and_the_code_stays_8(workdir: Path) -> None:
    result = run_cli(["run", "spec.yaml", "--debug"], provider=provider())
    assert result.code == 8
    assert "Traceback (most recent call last)" in result.err and "NotApprovedError" in result.err


def test_a_damaged_archive_is_exit_5_in_run_mode_too(workdir: Path) -> None:
    approve_all(workdir, HOLD_A, "8b0b3234")
    archive = workdir / "approvals" / "code" / f"{SHA_A}.py"
    archive.write_bytes(archive.read_bytes() + b"# edited\n")
    data = provider()
    result = run_cli(["run", "spec.yaml"], provider=data)
    assert (result.code, result.out) == (5, "")
    assert result.err.splitlines()[0] == (
        "bt: error: the archived code 8b0b3234 does not match its hash; the archive was changed"
    )
    untouched(workdir, data)


# --- canaries: `bt run` never executes code that is not approved ---


def canary_hash8(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()[:8]


def test_a_canary_file_whose_code_is_not_approved_is_not_executed_by_bt_run(workdir: Path, world) -> None:
    ids = SIGNALS.ids()
    canary = canary_source("hold_a")
    put_source(workdir, canary)
    assert run_cli(["approve", "spec.yaml", "--idea"]).code == 0
    data = provider()
    result = run_cli(["run", "spec.yaml"], provider=data)
    assert (result.code, result.out) == (8, "")
    assert result.err.splitlines()[0] == f"bt: error: code not approved: the file has sha {canary_hash8(canary)}"
    assert world.marker_lines() == [] and coded_modules() == [] and SIGNALS.ids() == ids
    untouched(workdir, data)


def test_approved_code_that_was_replaced_by_a_canary_is_not_executed_by_bt_run(workdir: Path, world) -> None:
    approve_all(workdir, HOLD_A, "8b0b3234")
    ids = SIGNALS.ids()
    canary = canary_source("hold_a")
    put_source(workdir, canary)  # the editable file is replaced after the approval
    data = provider()
    result = run_cli(["run", "spec.yaml"], provider=data)
    assert (result.code, result.out) == (8, "")
    assert result.err.splitlines()[0] == f"bt: error: code not approved: the file has sha {canary_hash8(canary)}"
    assert world.marker_lines() == [] and coded_modules() == [] and SIGNALS.ids() == ids
    untouched(workdir, data)


# --- mutation row 7: the gate is what makes a coded spec runnable ---


def test_without_the_gate_the_registry_does_not_have_the_signal_of_a_coded_spec(workdir: Path) -> None:
    """The run needs the gate: before it nothing registered ``hold_a``, after it the registry holds it with its hash."""
    clear_checked()
    assert "hold_a" not in SIGNALS
    approve_all(workdir, HOLD_A, "8b0b3234")
    assert "hold_a" not in SIGNALS  # approving loads nothing
    assert run_cli(["run", "spec.yaml"], provider=provider(), clock=at(0)).code == 0
    assert SIGNALS.get("hold_a").sha256 == SHA_A
