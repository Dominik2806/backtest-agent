"""The handler of ``bt signal check`` (docs/cli.md, docs/coded-signals.md, ADR 0018 addendum).

This is the one module that may execute a candidate that nobody approved (``load_candidate``) and the one that runs the
examples of ``cases.yaml``. The order is the safety rule: everything that is only data is checked first (the file as
bytes, the static check, the cases file), then the consent line is written to stderr, and only then is the candidate
executed, checked against the contract on frames of 300 rows and run on its examples. The approvals folder is never read
and nothing is written.
"""

import argparse

from backtest_agent.cli import render
from backtest_agent.cli.coded import DEFAULT_STRATEGIES_DIR
from backtest_agent.cli.context import Context
from backtest_agent.cli.errors import ExitCode
from backtest_agent.coded.approvals import code_sha256, normalise_source
from backtest_agent.coded.cases import cases_path, read_cases, run_cases
from backtest_agent.coded.contract import check_signal_contract, contract_frames
from backtest_agent.coded.errors import GateError, NotApprovedError
from backtest_agent.coded.loader import load_candidate
from backtest_agent.coded.static import check_source
from backtest_agent.coded.working import read_working_file
from backtest_agent.spec import load_spec
from backtest_agent.spec.errors import SpecError, SpecProblem


def cmd_signal_check(args: argparse.Namespace, context: Context) -> ExitCode:
    """Check a candidate before it is approved: static check, cases file, then (executing it) contract and examples."""
    spec = load_spec(args.spec)
    coded = spec.signal.coded
    if coded is None:
        raise SpecError(
            [SpecProblem("signal.coded", "the spec has no coded block; only a coded signal is checked")],
            source=args.spec,
        )
    signal_id = spec.signal.id
    path = args.strategies_dir / f"{signal_id}.py"
    shown = path.as_posix()
    try:
        raw = read_working_file(path, shown)
    except NotApprovedError as error:  # nothing is waiting for an approval here: the file is not there to be checked
        raise GateError(str(error)) from None
    data = normalise_source(raw)  # the bytes that are checked, run and hashed are the bytes bt approve would archive
    sha = code_sha256(data)
    check_source(data, signal_id)  # runs again inside load_candidate, on purpose: neither place trusts the other
    cases_file = cases_path(args.strategies_dir, signal_id)
    cases = read_cases(cases_file, signal_id)  # still only data: a missing or invalid file stops here, nothing executed

    print(render.executing_notice(shown, sha), file=context.err)
    with load_candidate(spec, data) as candidate:
        check_signal_contract(candidate.signal, candidate.signal.parse_params(candidate.params), contract_frames())
        count = run_cases(candidate.signal, cases)

    given = (("--strategies-dir", args.strategies_dir, DEFAULT_STRATEGIES_DIR),)
    folders = tuple((option, folder.as_posix()) for option, folder, default in given if folder != default)
    context.emit(
        *render.signal_check_lines(signal_id, shown, sha, cases_file.name, count, coded.code_sha256, args.spec, folders)
    )
    return ExitCode.OK
