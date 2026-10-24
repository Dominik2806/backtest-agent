"""Every ``bt`` command line shown in a code block of the README or of ``docs/`` parses with the real argument parser.

The commands are only parsed, never executed: a flag that does not exist, a missing argument or a renamed command makes
the test fail, so the documentation cannot drift from the command line. ``RUN_ID`` and placeholders such as ``<run id>``
are replaced by a valid run id first; a comment after ``#`` is cut off.
"""

import contextlib
import io
import re
import shlex
from pathlib import Path

import pytest

from backtest_agent.cli.parser import build_parser

ROOT = Path(__file__).resolve().parent.parent
FILES = sorted([ROOT / "README.md", *(ROOT / "docs").rglob("*.md")])
RUN_ID = "20260115T103005Z-demo-00000000"
FENCE = re.compile(r"^```(?P<language>[A-Za-z]*)\n(?P<body>.*?)^```", flags=re.MULTILINE | re.DOTALL)
SHELL_LANGUAGES = {"powershell", "bash", "sh", "console", "shell"}


def commands_of(path: Path) -> list[tuple[int, str]]:
    """(line number, command) of every ``uv run bt ...`` line of a fence and every ``bt ...`` line of a shell fence."""
    text = path.read_text(encoding="utf-8")
    found = []
    for fence in FENCE.finditer(text):
        first_line = text.count("\n", 0, fence.start("body")) + 1
        shell = fence.group("language").lower() in SHELL_LANGUAGES
        for offset, line in enumerate(fence.group("body").splitlines()):
            stripped = line.strip()
            if stripped.startswith("uv run bt ") or (shell and stripped.startswith("bt ")):
                found.append((first_line + offset, stripped))
    return found


def argv_of(command: str) -> list[str]:
    command = re.sub(r"\s+#.*$", "", command)  # a comment after the command
    command = re.sub(r"<[^>]*>", RUN_ID, command)  # <run id> and every other placeholder in angle brackets
    command = re.sub(r"\bRUN_ID\b", RUN_ID, command)
    tokens = shlex.split(command)
    return tokens[tokens.index("bt") + 1 :]


def parse(argv: list[str]) -> None:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            build_parser().parse_args(argv)
        except SystemExit as stop:
            asked = any(arg in ("--help", "-h", "--version") for arg in argv)
            if not (asked and stop.code in (0, None)):
                raise AssertionError(f"`bt {' '.join(argv)}` does not parse: {err.getvalue().strip()}") from None


CASES = [
    pytest.param(command, id=f"{path.relative_to(ROOT).as_posix()}:{line}")
    for path in FILES
    for line, command in commands_of(path)
]


@pytest.mark.parametrize("command", CASES)
def test_the_command_of_a_code_block_parses(command: str) -> None:
    parse(argv_of(command))


def test_the_readme_and_the_cli_doc_show_enough_commands_for_this_test_to_mean_something() -> None:
    assert len(commands_of(ROOT / "README.md")) >= 10  # the quickstart and the command line section
    assert len(commands_of(ROOT / "docs" / "cli.md")) >= 4


def test_the_checker_itself_rejects_what_it_should() -> None:
    for bad in (
        "uv run bt run spec.yaml --no-such-flag",
        "uv run bt run",  # a missing argument
        "uv run bt reportt RUN_ID",  # a renamed command
        "uv run bt data fetchh spec.yaml",
        "uv run bt report RUN_ID --overwriten",
        "uv run bt report",
    ):
        with pytest.raises(AssertionError, match="does not parse"):
            parse(argv_of(bad))


def test_help_and_version_are_accepted_but_nothing_else_that_exits() -> None:
    parse(argv_of("uv run bt --help"))
    parse(argv_of("uv run bt report --help"))
    parse(argv_of("uv run bt --version"))
    with pytest.raises(AssertionError):
        parse(argv_of("uv run bt journal"))  # a missing action exits with a usage error, not with 0
