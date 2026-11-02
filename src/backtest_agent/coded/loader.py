"""The approval gate: the ONLY module in ``src/`` that compiles or executes strategy code (ADR 0018).

``resolve_coded(spec, ...)`` turns a spec with a ``coded`` block into a spec that can run: it checks that a person
approved the idea and the code, loads exactly the archived bytes of the approved code, and returns the spec with
``code_sha256`` set. Every refusal happens before any file is compiled. The order of the steps:

1. the spec has a ``coded`` block and its id is a file-safe id;
2. the idea ``{signal_id, brief}`` is approved (``approvals/<id>.json``);
3. the hash of the code to run is chosen (see below) and must be listed for that idea;
4. the archive ``approvals/code/<sha>.py`` is read once, its hash and the static check are checked again;
5. only now the bytes are compiled and executed, in a module that is not put in ``sys.modules``; exactly one new
   registry entry with the id must appear, and it is marked with the hash it was loaded from;
6. the params are validated by the params model of the code and returned with their defaults, as for every signal.

``strategies_dir`` says where the editable code is. ``None`` is the stored mode (``bt report``): that folder is never
read and the spec must pin ``code_sha256``. A folder is the run mode (``bt run``): ``<id>.py`` in it is only read as
bytes and hashed, never executed; if it exists its hash must be approved for the idea, and exactly that archived hash
runs; if the spec pins another hash, the run is refused; if the file does not exist, the pin is used, or else the latest
approved hash.

Registry rules: an id that is registered by something other than this module is refused; the same hash that is
already loaded is reused without executing again; a different hash replaces this module's own entry; on every failure
the registry is exactly what it was before the call. Nothing else the code changes is undone (ADR 0018, known gaps).
"""

import difflib
import types
from pathlib import Path

from pydantic import ValidationError

from backtest_agent.coded.approvals import (
    IdeaApproval,
    code_sha256,
    idea_sha256,
    read_archived_code,
    read_record,
)
from backtest_agent.coded.errors import ApprovalError, GateError, NotApprovedError, RecordError
from backtest_agent.coded.static import check_source
from backtest_agent.spec.coded_spec import coded_id_problem
from backtest_agent.spec.errors import SpecError, SpecProblem
from backtest_agent.spec.schema import StrategySpec
from backtest_agent.spec.signals import SIGNALS, Signal


def resolve_coded(spec: StrategySpec, *, approvals_dir: Path | str, strategies_dir: Path | str | None) -> StrategySpec:
    """The spec with ``coded.code_sha256`` set and its signal loaded and marked in the registry.

    Raises ``NotApprovedError`` (the maintainer has to approve something; exit code 8), ``RecordError`` (the approvals
    folder cannot supply what the spec needs, or it was changed; exit code 5 in stored mode), ``StaticCheckError``,
    ``SpecError`` (the params do not fit the params model) or ``GateError`` (the code did not load).
    """
    coded = spec.signal.coded
    if coded is None:
        raise GateError("the spec has no coded block; there is nothing for the gate to resolve")
    signal_id = spec.signal.id
    problem = coded_id_problem(signal_id)
    if problem is not None:
        raise GateError(problem)
    stored = strategies_dir is None
    refuse = RecordError if stored else NotApprovedError  # in stored mode a missing approval is a record that is gone

    entry = _approved_idea(approvals_dir, signal_id, coded.brief, refuse)
    sha = _chosen_sha(entry, signal_id, coded.code_sha256, strategies_dir, refuse)
    data = _archived(approvals_dir, sha)
    check_source(data, signal_id)  # the archive was checked when it was approved; it is checked again before it runs
    signal = _load(signal_id, sha, data)
    params = _validated_params(signal, spec.signal.params)

    resolved = spec.to_dict()
    resolved["signal"]["params"] = params
    resolved["signal"]["coded"]["code_sha256"] = sha
    result = StrategySpec.model_validate(resolved)
    result.signal.params_model()  # the registered signal carries the hash the spec now pins
    return result


def _approved_idea(approvals_dir: Path | str, signal_id: str, brief: str, refuse: type[GateError]) -> IdeaApproval:
    try:
        record = read_record(approvals_dir, signal_id)
    except ApprovalError as error:
        raise RecordError(str(error)) from error
    if record is None:
        raise refuse(f"the idea of {signal_id!r} is not approved: there is no approval record")
    entry = record.idea(idea_sha256(signal_id, brief))
    if entry is None:
        raise refuse(f"the brief of {signal_id!r} changed since it was approved: no approved idea has this brief")
    return entry


def _chosen_sha(
    entry: IdeaApproval,
    signal_id: str,
    pinned: str | None,
    strategies_dir: Path | str | None,
    refuse: type[GateError],
) -> str:
    """The hash of the code to run, checked against the hashes approved for the idea."""
    if strategies_dir is None:
        if pinned is None:
            raise RecordError(
                f"the spec of {signal_id!r} pins no code_sha256, so the run cannot be reproduced from its record"
            )
        return _listed(entry, pinned, refuse)

    shown = f"strategies/signals/{signal_id}.py"
    path = Path(strategies_dir) / f"{signal_id}.py"
    if path.exists():
        try:
            file_sha = code_sha256(path.read_bytes())  # only hashed, never executed
        except OSError as error:
            raise NotApprovedError(f"{shown} cannot be read ({error.strerror or error})") from None
        if pinned is not None and pinned != file_sha:
            raise NotApprovedError(f"the spec pins {pinned[:8]} but {shown} has sha {file_sha[:8]}")
        if not entry.has_code(file_sha):
            raise NotApprovedError(f"code not approved: the file has sha {file_sha[:8]}")
        return file_sha
    if pinned is not None:
        return _listed(entry, pinned, refuse)
    latest = entry.latest_code
    if latest is None:
        raise NotApprovedError(f"code not approved: no code is approved for the idea of {signal_id!r}")
    return latest.sha256


def _listed(entry: IdeaApproval, sha: str, refuse: type[GateError]) -> str:
    if not entry.has_code(sha):
        raise refuse(f"the pinned code {sha[:8]} is not approved for this idea")
    return sha


def _archived(approvals_dir: Path | str, sha: str) -> bytes:
    try:
        return read_archived_code(approvals_dir, sha)
    except ApprovalError as error:
        raise RecordError(str(error)) from error


def _load(signal_id: str, sha: str, data: bytes) -> Signal:
    """Register the signal of ``data`` as ``signal_id``, marked with ``sha``; the registry is restored on failure."""
    before = SIGNALS.snapshot()
    if signal_id in before:
        existing = before[signal_id]
        if existing.sha256 is None:
            raise GateError(f"the id {signal_id!r} is already registered by something other than the gate")
        if existing.sha256 == sha:
            return existing  # loaded before in this process: reuse it, do not execute again
        SIGNALS.unregister(signal_id)  # the gate's own entry of another version
    try:
        _execute(signal_id, sha, data)
        after = SIGNALS.snapshot()
        kept = {key: value for key, value in before.items() if key != signal_id}
        if {key: after.get(key) for key in kept} != kept:
            raise GateError("the code changed the registry beyond registering " + repr(signal_id))
        added = set(after) - set(kept)
        if added != {signal_id}:
            registered = ", ".join(sorted(added)) or "nothing"
            raise GateError(f"the code must register exactly one signal, {signal_id!r}; it registered {registered}")
        return SIGNALS.set_sha256(signal_id, sha)
    except BaseException:
        SIGNALS.restore(before)
        raise


def _execute(signal_id: str, sha: str, data: bytes) -> None:
    module = types.ModuleType(f"coded_signal_{signal_id}")  # not put in sys.modules
    try:
        code = compile(data.decode("utf-8"), f"<coded signal {signal_id} {sha[:8]}>", "exec")
        exec(code, module.__dict__)
    except (KeyboardInterrupt, GeneratorExit):
        raise
    except BaseException as error:  # also SystemExit: the code must not be able to end the process
        raise GateError(
            f"the code of {signal_id!r} failed when it was loaded: {type(error).__name__}: {error}"
        ) from error


def _validated_params(signal: Signal, params: dict) -> dict:
    """The params with their defaults, validated by the params model of the code; ``SpecError`` if they do not fit."""
    try:
        return signal.params_model.model_validate(params).model_dump()
    except ValidationError as error:
        known = list(signal.params_model.model_fields)
        problems = []
        for item in error.errors():
            path = ".".join(["signal", "params", *(str(part) for part in item["loc"])])
            kind = item["type"]
            if kind == "missing":
                message = "missing required field"
            elif kind == "extra_forbidden":
                close = difflib.get_close_matches(str(item["loc"][-1]), known, n=1)
                hint = f"; did you mean '{close[0]}'?" if close else f"; allowed fields: {', '.join(known)}"
                message = f"unknown field '{item['loc'][-1]}'{hint}"
            else:
                message = str(item["msg"]).removeprefix("Value error, ")
            problems.append(SpecProblem(path, message))
        raise SpecError(problems) from None
