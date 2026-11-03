"""What the approval record says about a coded spec, without loading anything (``bt validate``, docs/coded-signals.md).

Only the record ``approvals/<id>.json`` is read: the editable file is not read, nothing is imported or executed and the
registry is not touched. The question is the one the gate asks first, answered without the gate: is the idea of the
spec approved, and is there approved code for it?
"""

from dataclasses import dataclass
from pathlib import Path

from backtest_agent.coded.approvals import idea_sha256, read_record
from backtest_agent.spec.schema import StrategySpec


@dataclass(frozen=True)
class ApprovalState:
    """``idea``: the idea ``{signal id, brief}`` of the spec is approved. ``code_sha256``: the code that would run
    (64 hex), or ``None`` if there is none approved."""

    idea: bool
    code_sha256: str | None = None


def approval_state(spec: StrategySpec, approvals_dir: Path | str) -> ApprovalState:
    """The state of a spec with a ``coded`` block. Raises ``ApprovalFormatError`` if the record is damaged.

    A pin (``coded.code_sha256``) names the code: it counts only if it is approved for this idea, otherwise the code is
    not approved, whatever else is. Without a pin the latest approved code counts, as in the run mode of the gate.
    """
    coded = spec.signal.coded
    if coded is None:
        raise ValueError("the spec has no coded block")
    record = read_record(approvals_dir, spec.signal.id)
    entry = record.idea(idea_sha256(spec.signal.id, coded.brief)) if record is not None else None
    if entry is None:
        return ApprovalState(idea=False)
    if coded.code_sha256 is not None:
        return ApprovalState(True, coded.code_sha256 if entry.has_code(coded.code_sha256) else None)
    latest = entry.latest_code
    return ApprovalState(True, None if latest is None else latest.sha256)
