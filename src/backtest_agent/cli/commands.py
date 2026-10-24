"""The commands of ``bt``: each handler takes the parsed arguments and a ``Context`` and returns an exit code."""

import argparse
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TextIO

from backtest_agent.cli import render
from backtest_agent.cli.argtypes import positive_int, run_id_arg
from backtest_agent.cli.errors import ExitCode
from backtest_agent.cli.provider import ProviderFactory
from backtest_agent.experiment import run_experiment
from backtest_agent.journal import get_run, list_runs, rebuild_index
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


def cmd_journal_list(args: argparse.Namespace, context: Context) -> ExitCode:
    runs = list_runs(args.runs_dir, family=args.family, limit=args.limit)
    context.emit(*render.journal_lines(runs, args.runs_dir, args.family))
    return ExitCode.OK


def cmd_journal_show(args: argparse.Namespace, context: Context) -> ExitCode:
    record = get_run(args.runs_dir, args.run_id)
    context.emit(*render.show_lines(record, args.runs_dir, args.reports_dir))
    return ExitCode.OK


def _indexed_runs(runs_dir: Path) -> int | None:
    """Rows of the existing index (the table ``runs``, docs/journal.md), or None if it is missing or unreadable.

    It reads the file as it is, without the comparison with the run folders that the read API makes: a stale index is
    exactly the case in which the old count matters.
    """
    path = runs_dir / "index.sqlite"
    if not path.is_file():
        return None
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            return int(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
        finally:
            connection.close()
    except sqlite3.Error:
        return None


def cmd_journal_rebuild(args: argparse.Namespace, context: Context) -> ExitCode:
    before = _indexed_runs(args.runs_dir)
    found = rebuild_index(args.runs_dir)
    context.emit(f"Rebuilt the index in {args.runs_dir.as_posix()}: {render.plural(found, 'run')} found.")
    if before is not None:
        context.emit(f"The old index had {render.plural(before, 'row')}.")
        if found < before:
            lost = before - found
            print(
                f"warning: the new index has {render.plural(found, 'run')}, the old one had {before}: the {lost} "
                f"missing {'run is' if lost == 1 else 'runs are'} forgotten and no longer "
                f"{'counts as a trial' if lost == 1 else 'count as trials'}",
                file=context.err,
            )
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

    journal = sub.add_parser(
        "journal",
        help="read the run journal: list, show, rebuild",
        description="Read the run journal (docs/journal.md). Folders are relative to the current directory.",
    )
    actions = journal.add_subparsers(dest="journal_command", required=True, metavar="ACTION")
    runs_dir = ("--runs-dir",)
    runs_dir_help = {"type": Path, "default": Path("runs"), "metavar": "DIR", "help": "journal folder (runs)"}

    listing = actions.add_parser(
        "list",
        parents=[common],
        help="list the logged runs, newest first",
        description="List the logged runs, newest first: run id, family, run number, variant number, whether the run "
        "introduced its variant, name.",
    )
    listing.add_argument("--family", metavar="F", help="only runs of this strategy family (the signal id)")
    listing.add_argument("--limit", type=positive_int, metavar="N", help="at most N runs (1 or more)")
    listing.add_argument(*runs_dir, **runs_dir_help)
    listing.set_defaults(handler=cmd_journal_list)

    show = actions.add_parser(
        "show",
        parents=[common],
        help="show one logged run",
        description="Show one logged run: the summary of bt run, the code version, the data hashes and the paths.",
    )
    show.add_argument("run_id", metavar="RUN_ID", type=run_id_arg, help="the run id (see bt journal list)")
    show.add_argument(*runs_dir, **runs_dir_help)
    show.add_argument(
        "--reports-dir", type=Path, default=Path("reports"), metavar="DIR", help="report folder (reports)"
    )
    show.set_defaults(handler=cmd_journal_show)

    rebuild = actions.add_parser(
        "rebuild",
        parents=[common],
        help="build the index again from the run folders",
        description="Build the SQLite index again from the run folders. Nothing is renumbered. A run whose folder was "
        "deleted is forgotten and no longer counts as a trial; the old and new number of runs are printed.",
    )
    rebuild.add_argument(*runs_dir, **runs_dir_help)
    rebuild.set_defaults(handler=cmd_journal_rebuild)

    validate = sub.add_parser(
        "validate",
        parents=[common],
        help="check a strategy spec (schema, signal id, parameters); no data is fetched",
        description="Check a strategy spec: the schema, the registered signal id and its parameters. "
        "Every problem is listed with its field path. No data is fetched and nothing is written.",
    )
    validate.add_argument("spec", metavar="SPEC", help="path of the YAML strategy spec")
    validate.set_defaults(handler=cmd_validate)
