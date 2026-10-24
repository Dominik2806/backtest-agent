"""The commands of ``bt``: each handler takes the parsed arguments and a ``Context`` and returns an exit code."""

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TextIO

from backtest_agent.cli import render
from backtest_agent.cli.errors import ExitCode
from backtest_agent.cli.provider import ProviderFactory
from backtest_agent.experiment import run_experiment
from backtest_agent.spec import load_spec


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


def cmd_run(args: argparse.Namespace, context: Context) -> ExitCode:
    """The standard run: ``run_experiment`` evaluates, logs the run and writes the report."""
    spec = load_spec(args.spec)
    provider = context.provider_factory(args.cache_dir)
    experiment = run_experiment(
        spec,
        provider,
        runs_dir=args.runs_dir,
        generated_at=context.clock(),
        reports_dir=None if args.no_report else args.reports_dir,
        apply_costs=not args.no_costs,
    )
    run_id = experiment.record.run_id
    lines = render.record_lines(experiment.record)
    lines.append(render.line("Journal", (args.runs_dir / run_id / "run.json").as_posix()))
    if experiment.report is not None:
        lines.append(render.line("Report", f"{experiment.report.markdown.as_posix()} and report.html"))
    context.emit(*lines)
    return ExitCode.OK


def cmd_validate(args: argparse.Namespace, context: Context) -> ExitCode:
    """Load and check a spec. No network, nothing is written."""
    spec = load_spec(args.spec)
    context.emit(*render.validate_lines(spec, args.spec))
    return ExitCode.OK


def register(sub: "argparse._SubParsersAction", common: argparse.ArgumentParser) -> None:
    """Add every command to the sub-parsers of the top-level parser."""
    run = sub.add_parser(
        "run",
        parents=[common],
        help="run a strategy spec: evaluate, log the run in the journal, write the report",
        description="Run a strategy spec next to its buy-and-hold benchmark, log the run in the journal (counted per "
        "strategy family) and write the report. Folders are relative to the current directory.",
    )
    run.add_argument("spec", metavar="SPEC", help="path of the YAML strategy spec")
    run.add_argument("--runs-dir", type=Path, default=Path("runs"), metavar="DIR", help="journal folder (runs)")
    run.add_argument("--reports-dir", type=Path, default=Path("reports"), metavar="DIR", help="report folder (reports)")
    run.add_argument("--no-report", action="store_true", help="log the run but write no report")
    run.add_argument(
        "--no-costs",
        action="store_true",
        help="run without the costs of the spec; the run is marked with the risk flag costs_not_applied",
    )
    run.add_argument(
        "--cache-dir", type=Path, default=Path("data/cache"), metavar="DIR", help="price cache folder (data/cache)"
    )
    run.set_defaults(handler=cmd_run)

    validate = sub.add_parser(
        "validate",
        parents=[common],
        help="check a strategy spec (schema, signal id, parameters); no data is fetched",
        description="Check a strategy spec: the schema, the registered signal id and its parameters. "
        "Every problem is listed with its field path. No data is fetched and nothing is written.",
    )
    validate.add_argument("spec", metavar="SPEC", help="path of the YAML strategy spec")
    validate.set_defaults(handler=cmd_validate)
