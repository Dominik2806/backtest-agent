"""``bt validate`` of a coded spec: the ``Signal:`` line from the approval record alone, and the gate for ``--data``.

Without ``--data`` nothing is loaded: no file is read, no code is imported, the registry is not touched (the
canary tests). With ``--data``, and in ``bt data fetch``, the warm-up window needs the signal, so the spec goes
through the gate in run mode first (exit code 8 before the approval, and the provider is not touched). The world is
the coded twin of fixture R3b (``coded_cli_helpers``); the data hashes are the literals of docs/cli.md.
"""

import hashlib
from datetime import date
from pathlib import Path

import pytest

from backtest_agent.spec import SIGNALS
from cli_helpers import at, run_cli
from coded_cli_helpers import BRIEF, HOLD_A, HOLD_B, SHA_A, approve_all, put_source, write_hold_spec
from coded_helpers import (
    canary_source,
    coded_modules,
    registry_and_modules_are_restored,  # noqa: F401 - autouse fixture
)
from report_helpers import world as r3b_world
from runner_helpers import LiteralProvider

HASH_A = "61669f6e7476623e1289ff7dad8c8b767f36be44961c05ec4def3f45c15dd090"
HASH_B = "ff487f9000d166df03fa5e84640c7524f7414b58173ed654e33fab7f1df0b094"
WINDOW = "2023-12-17 to 2024-01-08 (16 days before the period start)"
NEUTRAL_HINT = "hint: approvals are made with bt approve; see docs/coded-signals.md"
NO_RECORD = "bt: error: the idea of 'hold_a' is not approved: there is no approval record"


def head(signal: str, warmup: str = "n/a (coded signal, not loaded)") -> list[str]:
    return [
        "OK: spec.yaml is a valid spec",
        "Name:       Buy and hold A",
        "Family:     hold_a",
        f"Signal:     {signal}",
        "Universe:   A",
        "Benchmark:  B",
        "Period:     2024-01-02 to 2024-01-08",
        f"Warm-up:    {warmup}",
        "Risk flags: none",
    ]


DATA_BLOCKS = [
    f"Strategy:   {WINDOW}",
    "  A         5 rows",
    "  Checks:   0 errors, 0 warnings, 1 info",
    f"  Data:     {HASH_A}",
    "  info    starts_late              A           count 11, first 2024-01-02",
    f"Benchmark:  {WINDOW}",
    "  B         5 rows",
    "  Checks:   0 errors, 0 warnings, 1 info",
    f"  Data:     {HASH_B}",
    "  info    starts_late              B           count 11, first 2024-01-02",
]


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    write_hold_spec(tmp_path)
    return tmp_path


def validate(*args: str):
    return run_cli(["validate", "spec.yaml", *args], provider=LiteralProvider(r3b_world()))


# --- the three states, from the record alone ---


def test_nothing_approved_is_state_1(workdir: Path) -> None:
    result = validate()
    assert (result.code, result.err) == (0, "")
    assert result.out.splitlines() == head("coded, idea not approved")


def test_an_approved_idea_without_code_is_state_2(workdir: Path) -> None:
    assert run_cli(["approve", "spec.yaml", "--idea"]).code == 0
    result = validate()
    assert (result.code, result.err) == (0, "")
    assert result.out.splitlines() == head("coded, idea approved, code not approved")


def test_an_approved_idea_and_code_is_state_3_with_the_start_of_the_hash(workdir: Path) -> None:
    approve_all(workdir, HOLD_A, "8b0b3234")
    result = validate()
    assert (result.code, result.err) == (0, "")
    assert result.out.splitlines() == head("coded, idea and code approved (sha 8b0b3234)")


def test_a_pin_that_is_not_approved_is_state_2_even_if_other_code_is_approved(workdir: Path) -> None:
    approve_all(workdir, HOLD_A, "8b0b3234")
    write_hold_spec(workdir, pin="ab" * 32)
    assert validate().out.splitlines() == head("coded, idea approved, code not approved")


def test_a_pin_that_is_approved_is_state_3_with_the_pinned_hash(workdir: Path) -> None:
    approve_all(workdir, HOLD_A, "8b0b3234")
    put_source(workdir, HOLD_B)
    assert run_cli(["approve", "spec.yaml", "--code", "--sha", "3d693599"]).code == 0
    write_hold_spec(workdir, pin=SHA_A)  # the older of the two approved codes
    assert validate().out.splitlines() == head("coded, idea and code approved (sha 8b0b3234)")


def test_without_a_pin_the_latest_approved_code_counts(workdir: Path) -> None:
    approve_all(workdir, HOLD_A, "8b0b3234")
    put_source(workdir, HOLD_B)
    assert run_cli(["approve", "spec.yaml", "--code", "--sha", "3d693599"]).code == 0
    assert validate().out.splitlines() == head("coded, idea and code approved (sha 3d693599)")


def test_another_brief_is_an_idea_that_is_not_approved(workdir: Path) -> None:
    approve_all(workdir, HOLD_A, "8b0b3234")
    text = (workdir / "spec.yaml").read_text(encoding="utf-8").replace(BRIEF, "Another brief.")
    (workdir / "spec.yaml").write_text(text, encoding="utf-8")
    assert validate().out.splitlines() == head("coded, idea not approved")


def test_a_damaged_record_is_exit_5(workdir: Path) -> None:
    (workdir / "approvals").mkdir()
    (workdir / "approvals" / "hold_a.json").write_bytes(b"{")
    result = validate()
    assert (result.code, result.out) == (5, "")
    assert result.err.splitlines()[0].startswith("bt: error: hold_a.json: ")


def test_the_approvals_folder_option_is_used(workdir: Path) -> None:
    approve_all(workdir, HOLD_A, "8b0b3234", options=("--approvals-dir", "appr"))
    assert validate().out.splitlines() == head("coded, idea not approved")  # the default folder has nothing
    assert validate("--approvals-dir", "appr").out.splitlines() == head("coded, idea and code approved (sha 8b0b3234)")


# --- mutation row 12: validate without --data loads nothing ---


def test_validate_loads_nothing_not_even_approved_code(workdir: Path, world, static_check_off) -> None:
    """The approved code is a canary that writes a marker when it is imported; the file is never read either."""
    canary = canary_source("hold_a")
    world.approve_both("hold_a", canary, BRIEF)
    ids = SIGNALS.ids()
    sha8 = hashlib.sha256(canary).hexdigest()[:8]
    result = validate()
    assert (result.code, result.err) == (0, "")
    assert result.out.splitlines() == head(f"coded, idea and code approved (sha {sha8})")
    assert world.marker_lines() == [] and coded_modules() == [] and SIGNALS.ids() == ids


def test_validate_does_not_read_the_working_file(workdir: Path) -> None:
    approve_all(workdir, HOLD_A, "8b0b3234")
    (workdir / "strategies" / "signals" / "hold_a.py").unlink()
    assert validate().out.splitlines() == head("coded, idea and code approved (sha 8b0b3234)")


# --- with --data, and in bt data fetch, the gate runs first ---


@pytest.mark.parametrize("command", [["validate", "spec.yaml", "--data"], ["data", "fetch", "spec.yaml"]])
def test_data_before_the_approval_is_exit_8_and_the_provider_is_untouched(workdir: Path, command: list[str]) -> None:
    put_source(workdir, HOLD_A)
    data = LiteralProvider(r3b_world())
    result = run_cli(command, provider=data)
    assert (result.code, result.out) == (8, "")
    assert result.err.splitlines() == [NO_RECORD, NEUTRAL_HINT]
    assert data.calls == []


def test_validate_data_with_an_approved_coded_spec_passes_the_gate_and_fetches(workdir: Path) -> None:
    approve_all(workdir, HOLD_A, "8b0b3234")
    data = LiteralProvider(r3b_world())
    result = run_cli(["validate", "spec.yaml", "--data"], provider=data)
    assert (result.code, result.err) == (0, "")
    expected = head("coded, idea and code approved (sha 8b0b3234)", warmup="0 rows") + [""] + DATA_BLOCKS
    assert result.out.splitlines() == expected
    assert data.calls == [
        (("A",), date(2023, 12, 17), date(2024, 1, 8)),
        (("B",), date(2023, 12, 17), date(2024, 1, 8)),
    ]


def test_data_fetch_with_an_approved_coded_spec_prints_the_blocks_of_docs_cli_md(workdir: Path) -> None:
    approve_all(workdir, HOLD_A, "8b0b3234")
    result = run_cli(["data", "fetch", "spec.yaml"], provider=LiteralProvider(r3b_world()), clock=at(0))
    assert (result.code, result.err) == (0, "")
    assert result.out.splitlines() == [
        "Spec:       Buy and hold A",
        f"Strategy:   {WINDOW}",
        "  A         5 rows",
        "  Checks:   0 errors, 0 warnings, 1 info",
        f"  Data:     {HASH_A}",
        f"Benchmark:  {WINDOW}",
        "  B         5 rows",
        "  Checks:   0 errors, 0 warnings, 1 info",
        f"  Data:     {HASH_B}",
    ]


def test_the_data_commands_do_not_execute_unapproved_code(workdir: Path, world) -> None:
    put_source(workdir, canary_source("hold_a"))
    assert run_cli(["approve", "spec.yaml", "--idea"]).code == 0
    for command in (["validate", "spec.yaml", "--data"], ["data", "fetch", "spec.yaml"]):
        data = LiteralProvider(r3b_world())
        result = run_cli(command, provider=data)
        assert (result.code, result.out) == (8, "")
        assert data.calls == []
    assert world.marker_lines() == [] and coded_modules() == []
