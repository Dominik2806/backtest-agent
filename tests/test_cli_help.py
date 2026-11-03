"""The help of every command names its main options (key lines only, not a snapshot of the whole text)."""

import pytest

from cli_helpers import run_cli


def test_the_top_level_help_lists_the_commands() -> None:
    out = run_cli(["--help"]).out
    for command in ("run", "validate", "approve", "signal", "data", "journal"):
        assert f"\n    {command} " in out
    assert "Educational, not investment advice." in out


@pytest.mark.parametrize(
    ("command", "options"),
    [
        (
            ["run"],
            ["SPEC", "--runs-dir DIR", "--reports-dir DIR", "--no-report", "--no-costs", "--cache-dir DIR", "--debug"],
        ),
        (["validate"], ["SPEC", "--debug"]),
        (
            ["approve"],
            ["SPEC", "(--idea | --code)", "[--sha HEX8]", "--approvals-dir DIR", "--strategies-dir DIR", "--debug"],
        ),
        (["signal", "check"], ["SPEC", "--strategies-dir DIR", "--debug"]),
        (["journal", "list"], ["--family F", "--limit N", "--runs-dir DIR", "--debug"]),
        (["journal", "show"], ["RUN_ID", "--runs-dir DIR", "--reports-dir DIR", "--debug"]),
        (["journal", "rebuild"], ["--runs-dir DIR", "--debug"]),
    ],
)
def test_a_command_help_names_its_options(command: list[str], options: list[str]) -> None:
    result = run_cli([*command, "--help"])
    assert result.code == 0
    assert result.out.startswith(f"usage: bt {' '.join(command)} ")
    for option in options:
        assert option in result.out


def test_the_journal_help_lists_its_actions() -> None:
    out = run_cli(["journal", "--help"]).out
    for action in ("list", "show", "rebuild"):
        assert f"\n    {action} " in out


def test_the_rebuild_help_warns_that_deleted_runs_are_forgotten() -> None:
    assert "forgotten" in run_cli(["journal", "rebuild", "--help"]).out.replace("\n", " ")


def test_the_signal_check_help_says_that_it_executes_the_file_and_what_that_means() -> None:
    text = " ".join(run_cli(["signal", "check", "--help"]).out.split())
    for words in (
        "THIS COMMAND EXECUTES THE FILE",
        "which nobody approved",
        "with your permissions",
        "no time or memory limit",
        "the static check is a tripwire, not a sandbox",
        "Nothing is approved or written",
        "the approvals folder is not read",
    ):
        assert words in text, words
    assert "--approvals-dir" not in text
