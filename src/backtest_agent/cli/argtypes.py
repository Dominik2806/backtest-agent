"""Argument types shared by the commands: a bad value is a usage error (exit code 2), not a journal or spec error."""

import argparse

from backtest_agent.run_id import check_run_id


def run_id_arg(text: str) -> str:
    """A run id that is a safe folder name."""
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
