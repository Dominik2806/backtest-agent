"""The exit code of every error class, the provider guard, ``--debug``, stdout/stderr and encoding (docs/cli.md)."""

import io
import warnings
from datetime import date
from pathlib import Path

import pytest

from backtest_agent.cli import ExitCode, main
from backtest_agent.cli.errors import classify
from backtest_agent.cli.provider import GuardedProvider
from backtest_agent.data import DataError, DataUnavailableError, DataValidationError, FakeProvider
from backtest_agent.journal import JournalBusyError, JournalFormatError, JournalIndexStale, RunNotFoundError
from backtest_agent.spec.errors import SpecError, SpecProblem, UnknownSignalError
from cli_helpers import add_test_command, run_cli


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (SpecError([SpecProblem("name", "missing required field")], "x.yaml"), 3),
        (UnknownSignalError("no signal 'nope'"), 3),
        (DataError("boom"), 4),
        (DataUnavailableError("no rows"), 4),
        (DataValidationError("bad", None), 4),
        (JournalIndexStale("stale"), 5),
        (JournalBusyError("busy"), 5),
        (RunNotFoundError("no run"), 5),
        (JournalFormatError("bad run.json"), 5),
        (FileExistsError("run id already exists: runs/x; use a later generated_at"), 5),
        (KeyboardInterrupt(), 130),
        (ValueError("a bug"), 1),
        (PermissionError("read-only"), 1),
        (RuntimeError("a bug"), 1),
    ],
)
def test_the_exit_code_of_an_error_class(error: BaseException, code: int) -> None:
    assert classify(error).code == code


def test_journal_format_error_is_a_journal_problem_not_a_generic_value_error() -> None:
    assert isinstance(JournalFormatError("x"), ValueError)
    assert classify(JournalFormatError("x")).code == ExitCode.JOURNAL


def test_a_stale_index_hint_names_the_rebuild_command_and_the_directory() -> None:
    failure = classify(JournalIndexStale("stale"), runs_dir=Path("my-runs"))
    assert failure.hint is not None
    assert "bt journal rebuild --runs-dir my-runs" in failure.hint
    assert "forgotten" in failure.hint


def test_the_provider_guard_turns_foreign_errors_into_data_errors_with_the_cause() -> None:
    class Offline(FakeProvider):
        def get_prices(self, symbols, start, end):
            raise ConnectionError("network is down")

    guarded = GuardedProvider(Offline())
    with pytest.raises(DataError, match=r"the data provider failed \(ConnectionError: network is down\)") as info:
        guarded.get_prices(["AAA"], date(2024, 1, 2), date(2024, 1, 3))
    assert isinstance(info.value.__cause__, ConnectionError)


def test_the_provider_guard_keeps_data_errors_and_interrupts_unchanged() -> None:
    class Unavailable(FakeProvider):
        def get_prices(self, symbols, start, end):
            raise DataUnavailableError("unknown symbol")

    class Interrupted(FakeProvider):
        def get_prices(self, symbols, start, end):
            raise KeyboardInterrupt

    with pytest.raises(DataUnavailableError):
        GuardedProvider(Unavailable()).get_prices(["AAA"], date(2024, 1, 2), date(2024, 1, 3))
    with pytest.raises(KeyboardInterrupt):
        GuardedProvider(Interrupted()).get_prices(["AAA"], date(2024, 1, 2), date(2024, 1, 3))


def test_the_guard_reaches_the_commands_through_the_context(monkeypatch) -> None:
    class Offline(FakeProvider):
        def get_prices(self, symbols, start, end):
            raise ConnectionError("network is down")

    def handler(args, context):
        context.provider_factory(Path("cache")).get_prices(["AAA"], date(2024, 1, 2), date(2024, 1, 3))
        return 0

    add_test_command(monkeypatch, handler)
    result = run_cli(["probe"], provider=Offline())
    assert result.code == 4
    assert "the data provider failed (ConnectionError: network is down)" in result.err


def test_an_error_is_one_line_on_stderr_and_stdout_stays_empty(monkeypatch) -> None:
    def handler(args, context):
        context.emit("partial result")
        raise JournalIndexStale("the journal is stale")

    add_test_command(monkeypatch, handler)
    result = run_cli(["probe"])
    assert result.code == 5
    assert result.out == "partial result\n"
    assert result.err.splitlines()[0] == "bt: error: the journal is stale"
    assert result.err.splitlines()[1].startswith('hint: run "bt journal rebuild')
    assert "Traceback" not in result.err


def test_debug_adds_the_traceback_and_without_it_there_is_none(monkeypatch) -> None:
    def handler(args, context):
        raise RuntimeError("a bug")

    add_test_command(monkeypatch, handler)
    quiet = run_cli(["probe"])
    assert quiet.code == 1
    assert quiet.err.startswith("bt: error: unexpected error (RuntimeError): a bug\nhint: run again with --debug")
    assert "Traceback" not in quiet.err
    loud = run_cli(["probe", "--debug"])
    assert loud.code == 1
    assert "Traceback (most recent call last)" in loud.err
    assert "RuntimeError: a bug" in loud.err
    assert loud.err.rstrip().splitlines()[-2].startswith("bt: error: unexpected error")


def test_an_interrupt_is_exit_130_and_the_message_is_short(monkeypatch) -> None:
    def handler(args, context):
        raise KeyboardInterrupt

    add_test_command(monkeypatch, handler)
    result = run_cli(["probe"])
    assert (result.code, result.out, result.err) == (130, "", "bt: error: interrupted\n")


def test_every_captured_warning_is_printed_once_without_a_path(monkeypatch) -> None:
    def handler(args, context):
        warnings.warn("first thing", UserWarning, stacklevel=1)
        warnings.warn("first thing", UserWarning, stacklevel=1)
        warnings.warn("second   thing\nwith a break", RuntimeWarning, stacklevel=1)
        return 0

    add_test_command(monkeypatch, handler)
    result = run_cli(["probe"])
    assert result.code == 0
    assert result.err == "warning: first thing\nwarning: second thing with a break\n"


def test_control_characters_in_an_error_message_are_replaced(monkeypatch) -> None:
    def handler(args, context):
        raise DataError("bad \x1b[31mred\x1b[0m text")

    add_test_command(monkeypatch, handler)
    assert "\x1b" not in run_cli(["probe"]).err


def test_text_that_a_console_cannot_encode_is_escaped_instead_of_crashing(monkeypatch) -> None:
    def handler(args, context):
        context.emit("name: café 中文")
        raise DataError("symbol 中")

    add_test_command(monkeypatch, handler)
    raw_out, raw_err = io.BytesIO(), io.BytesIO()
    out = io.TextIOWrapper(raw_out, encoding="cp1252", errors="strict", newline="\n")
    err = io.TextIOWrapper(raw_err, encoding="cp1252", errors="strict", newline="\n")
    code = main(["probe"], stdout=out, stderr=err)
    out.flush()
    err.flush()
    assert code == 4
    assert raw_out.getvalue().decode("cp1252") == "name: café \\u4e2d\\u6587\n"
    assert "symbol \\u4e2d" in raw_err.getvalue().decode("cp1252")
