"""The commands of ``bt``: each handler takes the parsed arguments and a ``Context`` and returns an exit code."""

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TextIO

from backtest_agent.cli.provider import ProviderFactory


@dataclass(frozen=True)
class Context:
    """What a command needs from the outside: the provider factory, the clock and the two streams."""

    provider_factory: ProviderFactory
    clock: Callable[[], datetime]
    out: TextIO
    err: TextIO

    def emit(self, *lines: str) -> None:
        for line in lines:
            print(line, file=self.out)


def register(sub: "argparse._SubParsersAction", common: argparse.ArgumentParser) -> None:
    """Add every command to the sub-parsers of the top-level parser."""
