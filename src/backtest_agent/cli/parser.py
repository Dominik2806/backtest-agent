"""The argument parser of ``bt``: the global options; the commands add their own (``commands.register``)."""

import argparse

from backtest_agent import __version__
from backtest_agent.cli import commands


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
