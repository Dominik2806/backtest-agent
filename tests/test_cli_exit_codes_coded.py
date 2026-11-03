"""Exit codes 8 and 9 and the gate errors that map to 5 (docs/cli.md, "Exit codes"; ADR 0016 and 0018).

``classify`` in ``cli/errors.py`` is the only place that decides a code. The expected codes, messages and hints
are literals.
The classes that ``bt approve``, the gate and ``bt signal check`` raise are mapped here with one error each;
``CasesError`` is raised by ``bt signal check`` only.
"""

from pathlib import Path

import pytest

from backtest_agent.cli import ExitCode
from backtest_agent.cli.errors import ConfirmationError, UsageError, classify
from backtest_agent.coded.errors import (
    ApprovalError,
    ApprovalFormatError,
    CasesError,
    Finding,
    GateError,
    NotApprovedError,
    RecordError,
    StaticCheckError,
)
from backtest_agent.spec import SIGNALS, Signal
from backtest_agent.spec.errors import SignalContractError
from cli_helpers import run_cli, write_spec
from report_helpers import spec_for
from report_helpers import world as report_world
from runner_helpers import LiteralProvider, UpDayParams

STATIC = StaticCheckError([Finding(3, 1, "import", "import of 'os' is not allowed")])


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (NotApprovedError("code not approved: the file has sha 3f9a1c2e"), 8),
        (ApprovalError("another approval is in progress"), 8),
        (ConfirmationError("spec.yaml", "3f9a1c2e", "the code is not approved yet"), 8),
        (RecordError("the approval record of 'x_signal' is missing"), 5),
        (ApprovalFormatError("x_signal.json: schema_version must be 1"), 5),
        (STATIC, 9),
        (SignalContractError("signal output must be a DataFrame, got int"), 9),
        (CasesError("cases.yaml: no case"), 9),
        (GateError("the code of 'x_signal' failed when it was loaded: SystemExit: 3"), 9),
    ],
    ids=[
        "NotApprovedError",
        "ApprovalError",
        "ConfirmationError",
        "RecordError",
        "ApprovalFormatError",
        "StaticCheckError",
        "SignalContractError",
        "CasesError",
        "GateError",
    ],
)
def test_the_exit_code_of_every_gate_error(error: BaseException, code: int) -> None:
    assert classify(error).code == code


def test_the_new_codes_have_their_numbers() -> None:
    assert (ExitCode.GATE, ExitCode.CODE) == (8, 9)


def test_the_subclasses_of_gate_error_are_classified_before_gate_error() -> None:
    """GateError is code 9; the two subclasses that are not "code rejected" must not fall into it."""
    assert issubclass(NotApprovedError, GateError) and issubclass(RecordError, GateError)
    assert classify(NotApprovedError("x")).code == 8
    assert classify(RecordError("x")).code == 5
    assert classify(GateError("x")).code == 9


def test_an_approval_format_error_is_a_record_problem_not_a_refusal() -> None:
    """ApprovalFormatError is an ApprovalError (code 8) and must be checked first."""
    assert issubclass(ApprovalFormatError, ApprovalError)
    assert classify(ApprovalFormatError("x")).code == 5


def test_a_signal_contract_error_is_a_code_problem_not_an_unexpected_error() -> None:
    """SignalContractError is a ValueError, and a ValueError that nobody classified is code 1."""
    assert issubclass(SignalContractError, ValueError)
    assert classify(SignalContractError("x")).code == 9
    assert classify(ValueError("x")).code == 1


def test_a_refusal_has_the_neutral_hint_because_a_folder_or_a_large_file_is_also_code_8() -> None:
    failure = classify(NotApprovedError("strategies/signals/x_signal.py cannot be read (not a regular file)"))
    assert failure.message == "strategies/signals/x_signal.py cannot be read (not a regular file)"
    assert failure.hint == "approvals are made with bt approve; see docs/coded-signals.md"
    assert classify(ApprovalError("x")).hint == failure.hint


def test_only_the_confirmation_names_the_command_with_the_hash() -> None:
    failure = classify(ConfirmationError("strategies/rsi.yaml", "3f9a1c2e", "the code is not approved yet"))
    assert failure.message == "the code is not approved yet"
    assert failure.hint == (
        "read the code printed above; if you accept it, run: bt approve strategies/rsi.yaml --code --sha 3f9a1c2e"
    )
    for other in (NotApprovedError("x"), ApprovalError("x"), RecordError("x"), STATIC, GateError("x")):
        assert "--sha" not in (classify(other).hint or "")


@pytest.mark.parametrize(
    ("spec", "shown"),
    [
        ("strategies/rsi.yaml", "strategies/rsi.yaml"),
        (r"C:\work\rsi_pullback-1.yaml", r"C:\work\rsi_pullback-1.yaml"),
        ("my strategies/rsi.yaml", '"my strategies/rsi.yaml"'),
        ("rsi (copy).yaml", '"rsi (copy).yaml"'),
        ("a&b.yaml", '"a&b.yaml"'),
    ],
    ids=["plain", "windows", "space", "parentheses", "ampersand"],
)
def test_the_spec_path_of_the_hint_is_quoted_only_when_it_needs_quotes(spec: str, shown: str) -> None:
    hint = classify(ConfirmationError(spec, "3f9a1c2e", "x")).hint
    assert hint == f"read the code printed above; if you accept it, run: bt approve {shown} --code --sha 3f9a1c2e"


@pytest.mark.parametrize("hint", ["bt approve --help describes the arguments", "another hint", None])
def test_a_usage_error_carries_its_own_hint(hint: str | None) -> None:
    failure = classify(UsageError("--sha goes with --code", hint))
    assert (failure.code, failure.message, failure.hint) == (2, "--sha goes with --code", hint)


def test_the_hint_of_a_confirmation_repeats_the_folders_with_quotes_where_needed() -> None:
    error = ConfirmationError(
        "spec.yaml", "3f9a1c2e", "x", [("--approvals-dir", "my approvals"), ("--strategies-dir", "src/signals")]
    )
    assert classify(error).hint == (
        "read the code printed above; if you accept it, run: bt approve spec.yaml --code --sha 3f9a1c2e "
        '--approvals-dir "my approvals" --strategies-dir src/signals'
    )


def test_the_message_of_a_failed_static_check_lists_the_findings() -> None:
    failure = classify(STATIC)
    assert failure.message == (
        "the signal source breaks 1 rule of the static check:\n  - line 3: import of 'os' is not allowed [import]"
    )
    assert failure.hint == "the rules a coded signal has to follow are in docs/coded-signals.md"


def test_the_hints_of_the_record_errors_and_the_contract_error() -> None:
    assert classify(RecordError("x")).hint == (
        "the approvals folder (--approvals-dir) has to hold the record and the archived code this run used"
    )
    assert classify(ApprovalFormatError("x")).hint == (
        "an approval record is not valid; restore it from version control (docs/coded-signals.md)"
    )
    assert (
        classify(SignalContractError("x")).hint == "a signal has to follow the signal contract (docs/strategy-spec.md)"
    )


def test_bt_run_on_a_built_in_signal_that_breaks_the_contract_is_code_9(tmp_path: Path, monkeypatch) -> None:
    """Before this change the same run ended with code 1, "unexpected error"."""
    monkeypatch.chdir(tmp_path)

    def not_a_frame(prices, params):
        return 1

    monkeypatch.setitem(
        SIGNALS._signals,
        "fixture_not_a_frame",
        Signal("fixture_not_a_frame", UpDayParams, not_a_frame, "returns an int"),
    )
    path = write_spec(tmp_path, spec_for(signal="fixture_not_a_frame"))
    result = run_cli(["run", str(path)], provider=LiteralProvider(report_world()))
    assert result.code == 9
    assert result.out == ""
    assert result.err.splitlines() == [
        "bt: error: signal output must be a DataFrame, got int",
        "hint: a signal has to follow the signal contract (docs/strategy-spec.md)",
    ]
    assert not (tmp_path / "runs").exists()
    assert not (tmp_path / "reports").exists()
