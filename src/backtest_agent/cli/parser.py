"""The argument parser of ``bt``: global options and the argument types shared by the commands."""

import argparse

from backtest_agent import __version__
from backtest_agent.cli import commands
from backtest_agent.run_id import check_run_id


def run_id_arg(text: str) -> str:
    """A run id that is a safe folder name (so a bad id is a usage error, not a journal error)."""
    try:
        return check_run_id(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be 1 or more, got {value}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bt",
        description="Backtest a trading strategy spec on daily data, log the run and write a report. "
        "Educational, not investment advice.",
    )
    parser.add_argument("--version", action="version", version=f"bt {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", help="print the full traceback of an error on stderr")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    commands.register(sub, common)
    return parser
