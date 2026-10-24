"""The ``bt`` command line (F-16; docs/cli.md, ADR 0016).

``main`` returns the exit code and never calls ``sys.exit``; the console script and ``python -m backtest_agent`` wrap
it. Providers, the clock and the streams are injected, so tests run the whole command line without network, real time or
a console. The clock is read only here (``utc_now``); the engine, the journal and the report never read it.
"""

import contextlib
import sys
import traceback
import warnings
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from backtest_agent.cli.commands import Context
from backtest_agent.cli.errors import ExitCode, classify, clean
from backtest_agent.cli.parser import build_parser
from backtest_agent.cli.provider import GuardedProvider, ProviderFactory, default_provider_factory
from backtest_agent.data.provider import DataProvider
from backtest_agent.reporting.model import text

__all__ = ["ExitCode", "default_provider_factory", "main", "utc_now"]


def utc_now() -> datetime:
    return datetime.now(UTC)


def _safe_stream(stream: TextIO) -> None:
    """Text from specs and data must never crash a console: unencodable characters print as backslash escapes."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        with contextlib.suppress(ValueError, OSError):
            reconfigure(errors="backslashreplace")


def _exit_code(code: object) -> int:
    return code if isinstance(code, int) else int(ExitCode.USAGE)


def main(
    argv: Sequence[str] | None = None,
    *,
    provider_factory: ProviderFactory = default_provider_factory,
    clock: Callable[[], datetime] = utc_now,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run ``bt`` with ``argv`` (default: the process arguments) and return the exit code."""
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    _safe_stream(out)
    _safe_stream(err)
    parser = build_parser()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            args = parser.parse_args(argv)
        except SystemExit as exit_:  # --help, --version and usage errors
            return _exit_code(exit_.code)

    def guarded(directory: Path) -> DataProvider:
        return GuardedProvider(provider_factory(directory))

    context = Context(guarded, clock, out, err)
    failure = None
    code = ExitCode.OK
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            code = args.handler(args, context)
        except (Exception, KeyboardInterrupt) as error:
            failure = classify(error, runs_dir=getattr(args, "runs_dir", None))
            if getattr(args, "debug", False):
                traceback.print_exception(error, file=err)
    for message in dict.fromkeys(text(w.message) for w in caught):
        print(f"warning: {message}", file=err)
    if failure is not None:
        print(f"bt: error: {clean(failure.message)}", file=err)
        if failure.hint:
            print(f"hint: {clean(failure.hint)}", file=err)
        return int(failure.code)
    return int(code)
