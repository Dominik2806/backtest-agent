"""The handler of ``bt approve`` (docs/cli.md, docs/coded-signals.md, ADR 0018).

``bt approve`` never imports, compiles or executes the code it shows: it reads the editable file as bytes
(``read_working_file``), runs the static check (a syntax tree walk) and hands the same bytes to ``approve_code``.
The clock is read here, once, and nowhere in ``coded/``.
"""

import argparse

from backtest_agent.cli import render
from backtest_agent.cli.context import Context
from backtest_agent.cli.errors import ConfirmationError, ExitCode, UsageError
from backtest_agent.coded.approvals import (
    approve_code,
    approve_idea,
    code_path,
    code_sha256,
    idea_sha256,
    normalise_source,
    read_record,
    record_path,
)
from backtest_agent.coded.errors import ApprovalError
from backtest_agent.coded.static import check_source
from backtest_agent.coded.working import read_working_file
from backtest_agent.spec import load_spec
from backtest_agent.spec.errors import SpecError, SpecProblem


def cmd_approve(args: argparse.Namespace, context: Context) -> ExitCode:
    """Approve the idea of a coded spec (``--idea``) or its code (``--code``, confirmed with ``--sha``)."""
    if args.idea and args.sha is not None:
        raise UsageError("--sha goes with --code; the idea needs no confirmation")
    spec = load_spec(args.spec)
    coded = spec.signal.coded
    if coded is None:
        raise SpecError(
            [SpecProblem("signal.coded", "the spec has no coded block; only a coded signal is approved")],
            source=args.spec,
        )
    signal_id = spec.signal.id
    now = context.clock()
    idea = idea_sha256(signal_id, coded.brief)
    record_file = record_path(args.approvals_dir, signal_id)

    if args.idea:
        record, changed = approve_idea(args.approvals_dir, signal_id, coded.brief, now)
        entry = record.idea(idea)
        assert entry is not None, "approve_idea returned a record without the idea it approved"
        context.emit(*render.approve_idea_lines(signal_id, idea, changed, entry.approved_at, record_file, coded.brief))
        return ExitCode.OK

    path = args.strategies_dir / f"{signal_id}.py"
    shown = path.as_posix()
    data = normalise_source(read_working_file(path, shown))  # read once: shown, hashed and archived are these bytes
    existing = read_record(args.approvals_dir, signal_id)
    if existing is None or existing.idea(idea) is None:
        raise ApprovalError(f"the idea of {signal_id!r} is not approved; approve the idea first")
    check_source(data, signal_id)
    digest = code_sha256(data)
    if args.sha != digest[:8]:
        context.emit(*render.review_lines(signal_id, shown, data, digest))
        if args.sha is None:
            message = f"the code is not approved yet; confirm it with --sha {digest[:8]}"
        else:
            message = f"--sha {args.sha} is not the start of the hash of {shown}; the file has sha {digest[:8]}"
        raise ConfirmationError(args.spec, digest[:8], message)

    record, digest, changed = approve_code(args.approvals_dir, signal_id, coded.brief, data, now)
    entry = record.idea(idea)
    assert entry is not None, "approve_code returned a record without the idea it belongs to"
    approved_at = next(code.approved_at for code in entry.code if code.sha256 == digest)
    context.emit(
        *render.approve_code_lines(
            signal_id,
            digest,
            changed,
            approved_at,
            code_path(args.approvals_dir, digest),
            record_file,
            coded.code_sha256,
        )
    )
    return ExitCode.OK
