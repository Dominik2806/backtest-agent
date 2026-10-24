"""The skeleton of ``bt``: help, version, usage errors (exit 2) and the main function's contract."""

import io
import re

from backtest_agent import __version__
from backtest_agent.cli import main
from cli_helpers import run_cli


def test_help_exits_zero_and_names_the_program() -> None:
    result = run_cli(["--help"])
    assert result.code == 0
    assert result.out.startswith("usage: bt ")
    assert "--version" in result.out
    assert result.err == ""


def test_version_prints_the_package_version() -> None:
    result = run_cli(["--version"])
    assert result.code == 0
    assert result.out == f"bt {__version__}\n"
    assert re.fullmatch(r"bt \d+\.\d+\.\d+\n", result.out)


def test_no_command_is_a_usage_error() -> None:
    result = run_cli([])
    assert result.code == 2
    assert result.out == ""
    assert result.err.startswith("usage: bt ")
    assert "the following arguments are required: COMMAND" in result.err


def test_unknown_command_is_a_usage_error() -> None:
    result = run_cli(["frobnicate"])
    assert result.code == 2
    assert result.out == ""
    assert "invalid choice: 'frobnicate'" in result.err


def test_main_writes_to_the_injected_streams_and_never_exits() -> None:
    out, err = io.StringIO(), io.StringIO()
    assert main(["--version"], stdout=out, stderr=err) == 0
    assert out.getvalue().startswith("bt ")
    assert main(["--nope"], stdout=out, stderr=err) == 2
    assert err.getvalue().startswith("usage: bt ")
