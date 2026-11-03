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
6. the params are validated by the params model of the code and returned with their defaults, as for every signal;
   the contract check runs on synthetic frames (``check_before_run``) with those params.

``strategies_dir`` says where the editable code is. ``None`` is the stored mode (``bt report``): that folder is never
read and the spec must pin ``code_sha256``. A folder is the run mode (``bt run``): ``<id>.py`` in it is only read as
bytes and hashed, never executed; if it exists its hash must be approved for the idea, and exactly that archived hash
runs; if the spec pins another hash, the run is refused; if the file does not exist, the pin is used, or else the latest
approved hash.

The one exception to "only approved bytes" is ``load_candidate``, for ``bt signal check`` alone (ADR 0018, addendum):
it executes the working file of a candidate that nobody approved, in this process, and restores the registry afterwards.

Registry rules: an id that is registered by something other than this module is refused; the same hash that is
already loaded is reused without executing again; a different hash replaces this module's own entry; on every failure
the registry is exactly what it was before the call. Nothing else the code changes is undone (ADR 0018, known gaps).
"""

import difflib
import os
import types
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from backtest_agent.coded.approvals import (
    IdeaApproval,
    code_sha256,
    idea_sha256,
    normalise_source,
    read_archived_code,
    read_record,
)
from backtest_agent.coded.contract import check_before_run
from backtest_agent.coded.errors import ApprovalError, GateError, NotApprovedError, RecordError
from backtest_agent.coded.static import check_source
from backtest_agent.coded.working import FILE_LIMIT, read_working_file  # noqa: F401 - FILE_LIMIT is re-exported
from backtest_agent.spec.coded_spec import check_scalar_params, coded_id_problem
from backtest_agent.spec.errors import SpecError, SpecProblem, UnknownSignalError
from backtest_agent.spec.schema import StrategySpec
from backtest_agent.spec.signals import SIGNALS, Signal


def resolve_coded(spec: StrategySpec, *, approvals_dir: Path | str, strategies_dir: Path | str | None) -> StrategySpec:
    """The spec with ``coded.code_sha256`` set and its signal loaded and marked in the registry.

    Raises ``NotApprovedError`` (the maintainer has to approve something; exit code 8), ``RecordError`` (the approvals
    folder cannot supply what the spec needs, or it was changed; exit code 5 in stored mode), ``StaticCheckError``,
    ``SpecError`` (the params do not fit the params model), ``SignalContractError`` (the code fails the contract check
    on synthetic frames, see ``coded/contract.py``) or ``GateError`` (the code did not load, or its params model is not
    usable). **Whenever it raises, the registry is exactly what it was before the call**: a signal that
    was loaded and then failed a later step (params, defaults, the final validation) is unloaded again.
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
    before = SIGNALS.snapshot()
    try:
        signal = _load(signal_id, sha, data, before)
        params = _validated_params(signal, spec.signal.params)
        _check_contract_once(signal, params, sha)

        resolved = spec.to_dict()
        resolved["signal"]["params"] = params
        resolved["signal"]["coded"]["code_sha256"] = sha
        try:
            result = StrategySpec.model_validate(resolved)
            result.signal.params_model()  # the registered signal carries the hash the spec now pins
        except (ValidationError, UnknownSignalError) as error:  # not expected; only the gate's own errors leave
            raise GateError(f"the resolved spec is not valid: {error}") from error
        return result
    except BaseException:
        SIGNALS.restore(before)  # from the load to the end: a failure leaves no loaded code behind
        raise


#: What passed the check before a run in this process: the hash of the code and the params it was checked with. The same
#: code with the same params is not checked again (the check costs a fraction of a second to a second).
_CHECKED: set[tuple[str, str]] = set()


def clear_checked() -> None:
    """Forget what passed the check before a run (for tests; a real process never needs it)."""
    _CHECKED.clear()


def _check_contract_once(signal: Signal, params: dict, sha: str) -> None:
    key = (sha, repr(sorted(params.items())))
    if key in _CHECKED:
        return
    check_before_run(signal, signal.parse_params(params))  # raises SignalContractError; nothing is remembered then
    _CHECKED.add(key)


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
    if os.path.lexists(path):
        file_sha = code_sha256(read_working_file(path, shown))  # only hashed, never executed
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


def _load(signal_id: str, sha: str, data: bytes, before: dict[str, Signal]) -> Signal:
    """Register the signal of ``data`` as ``signal_id``, marked with ``sha``. ``before`` is the registry on entry; the
    caller restores it if this or any later step fails."""
    if signal_id in before:
        existing = before[signal_id]
        if existing.sha256 is None:
            raise GateError(f"the id {signal_id!r} is already registered by something other than the gate")
        if existing.sha256 == sha:
            return existing  # loaded before in this process: reuse it, do not execute again
        SIGNALS.unregister(signal_id)  # the gate's own entry of another version
    _execute(signal_id, sha, data)
    return _registered_once(signal_id, sha, before)


def _registered_once(signal_id: str, sha: str, before: dict[str, Signal]) -> Signal:
    """After the code ran: exactly one new entry, ``signal_id``, and nothing else changed; it is marked with ``sha``."""
    after = SIGNALS.snapshot()
    kept = {key: value for key, value in before.items() if key != signal_id}
    if {key: after.get(key) for key in kept} != kept:
        raise GateError("the code changed the registry beyond registering " + repr(signal_id))
    added = set(after) - set(kept)
    if added != {signal_id}:
        registered = ", ".join(sorted(added)) or "nothing"
        raise GateError(f"the code must register exactly one signal, {signal_id!r}; it registered {registered}")
    return SIGNALS.set_sha256(signal_id, sha)


@dataclass(frozen=True)
class Candidate:
    """A signal loaded by ``load_candidate``: the registered (and marked) signal, the params of the spec validated by
    its params model (with defaults), and the hash of the LF form of the file it came from."""

    signal: Signal
    params: dict
    sha256: str


@contextmanager
def load_candidate(spec: StrategySpec, source: bytes) -> Iterator[Candidate]:
    """Execute a candidate that NOBODY APPROVED, for ``bt signal check`` only (ADR 0018, addendum; known gap 6).

    ``source`` is the editable file as bytes (CRLF is turned into LF, so ``sha256`` is the hash ``bt approve`` prints).
    The static check runs again before anything is compiled. The signal is registered under the id of the spec and
    marked with the hash, like a gate-loaded signal, so ``Signal.generate`` guards its calls in the same way. **When
    the ``with`` block ends, however it ends (an exception, ``KeyboardInterrupt`` and ``GeneratorExit`` included), the
    registry is exactly what it was before the call**; an entry of the gate for the same id is set aside and put back.
    Nothing is written to ``approvals/``, the cache of ``resolve_coded`` (``_CHECKED``) is not touched and the module
    is not put in ``sys.modules``. Nothing else the code changes is undone (known gap 3).

    Raises ``StaticCheckError``, ``GateError`` (no coded block, the id is taken by something other than the gate, the
    code did not load or registered something else, the params model is not usable) and ``SpecError`` (the params of
    the spec do not fit the params model). Only ``cli/signal_check.py`` may call it; a source-tree test checks that.
    """
    if spec.signal.coded is None:
        raise GateError("the spec has no coded block; there is no candidate to load")
    signal_id = spec.signal.id
    problem = coded_id_problem(signal_id)
    if problem is not None:
        raise GateError(problem)
    # Redundant today: code_sha256, the static check and compile treat CRLF like LF. Kept so that the bytes that run are
    # the bytes bt approve would archive.
    data = normalise_source(source)
    sha = code_sha256(data)
    check_source(data, signal_id)
    before = SIGNALS.snapshot()
    try:
        existing = before.get(signal_id)
        if existing is not None:
            if existing.sha256 is None:
                raise GateError(f"the id {signal_id!r} is already registered by something other than the gate")
            SIGNALS.unregister(signal_id)  # set aside; the candidate is executed even if the same hash is loaded
        _execute(signal_id, sha, data)
        signal = _registered_once(signal_id, sha, before)
        yield Candidate(signal, _validated_params(signal, spec.signal.params), sha)
    finally:
        SIGNALS.restore(before)


def _execute(signal_id: str, sha: str, data: bytes) -> None:
    module = types.ModuleType(f"coded_signal_{signal_id}")  # not put in sys.modules
    try:
        code = compile(data.decode("utf-8"), f"<coded signal {signal_id} {sha[:8]}>", "exec", dont_inherit=True)
        exec(code, module.__dict__)
    except (KeyboardInterrupt, GeneratorExit):
        raise
    except BaseException as error:  # also SystemExit raised while the code is loaded
        raise GateError(
            f"the code of {signal_id!r} failed when it was loaded: {type(error).__name__}: {error}"
        ) from error


def _validated_params(signal: Signal, params: dict) -> dict:
    """The params with their defaults, validated by the params model of the code.

    ``SpecError`` if they do not fit the model, ``GateError`` if the model itself fails or has a default that a spec
    cannot hold (the spec rule for params of a coded signal: numbers, text, true or false, or lists of those).
    """
    try:
        dumped = signal.params_model.model_validate(params).model_dump()
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
    except (KeyboardInterrupt, GeneratorExit):
        raise
    except BaseException as error:  # a validator of the code that raises something other than a ValueError
        raise GateError(f"the params model of {signal.id!r} failed: {type(error).__name__}: {error}") from error
    for name, value in dumped.items():
        try:
            check_scalar_params({name: value})
        except ValueError:
            raise GateError(
                f"the params model of the code has a default that a spec cannot hold: {name!r} is {value!r}; "
                "defaults must be numbers, text, true or false, or lists of those"
            ) from None
    # The spec stores these values, and every run validates them again: the model must accept its own defaults.
    try:
        signal.params_model.model_validate(dumped)
    except ValidationError as error:
        reasons = "; ".join(f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors())
        raise GateError(f"the params model of the code does not accept its own defaults: {reasons}") from None
    except (KeyboardInterrupt, GeneratorExit):
        raise
    except BaseException as error:
        raise GateError(f"the params model of {signal.id!r} failed: {type(error).__name__}: {error}") from error
    return dumped
