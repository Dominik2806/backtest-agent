"""The ``signal.coded`` block of a strategy spec and the rules for the id of a coded signal.

A coded signal is a signal that an agent writes after the spec is approved (Phase 10, docs/coded-signals.md). The spec
can therefore name it before it exists: the block holds the plain-language ``brief`` that the maintainer approves (with
the id) and, once a run is made, the sha256 of the code that ran. Nothing in this module imports or looks up a signal.
"""

import math
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer

BUILTIN_SIGNAL_IDS = frozenset({"buy_and_hold", "momentum_12_1", "sma_crossover"})
MAX_ID_LENGTH = 64
MAX_BRIEF_LENGTH = 2000

_ID = re.compile(r"[a-z][a-z0-9_]*")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"} | {f"com{n}" for n in range(1, 10)} | {f"lpt{n}" for n in range(1, 10)}
)
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def normalise_newlines(text: str) -> str:
    """CRLF becomes LF; nothing else is changed (no stripping). The one normalisation of a brief or of source code."""
    return text.replace("\r\n", "\n")


def coded_id_problem(signal_id: str) -> str | None:
    """Why ``signal_id`` cannot be the id of a coded signal, or None if it can.

    The id is also a file name (``strategies/signals/<id>.py``, ``approvals/<id>.json``), so it is held to a strict
    pattern, must not be a built-in id and must not be a name that Windows reserves for devices.
    """
    if not _ID.fullmatch(signal_id):
        return (
            "a coded signal id must be lowercase letters, digits and underscores starting with a letter, "
            f"got {signal_id!r}"
        )
    if len(signal_id) > MAX_ID_LENGTH:
        return f"a coded signal id must have at most {MAX_ID_LENGTH} characters, got {len(signal_id)}"
    if signal_id in BUILTIN_SIGNAL_IDS:
        return f"{signal_id!r} is the id of a built-in signal; a coded signal needs an id of its own"
    if signal_id in _DEVICE_NAMES:
        return f"{signal_id!r} is a reserved file name on Windows; choose another id"
    return None


def check_scalar_params(params: dict[str, Any]) -> None:
    """Raise ``ValueError`` unless every value is a bool, int, finite float or str, or a list of those.

    A coded signal has no params model before the gate loads its code, so its params can only be checked for shape here;
    the model of the code validates them when the signal is resolved.
    """

    def scalar(value: Any) -> bool:
        if isinstance(value, bool | int | str):
            return True
        return isinstance(value, float) and math.isfinite(value)

    for name, value in params.items():
        if scalar(value):
            continue
        if isinstance(value, list) and all(scalar(item) for item in value):
            continue
        raise ValueError(
            f"the parameter {name!r} of a coded signal must be a number, text, true or false, or a list of those "
            f"(no null, no nested block, no NaN or infinity), got {value!r}"
        )


class CodedSpec(BaseModel):
    """``signal.coded``: the brief that is approved with the signal id, and the code that ran (``code_sha256``)."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    brief: str = Field(description="what the signal does, every parameter and what history it needs, in plain language")
    code_sha256: str | None = Field(default=None, description="sha256 of the code that ran; set when the gate resolves")

    @field_validator("brief")
    @classmethod
    def _brief(cls, brief: str) -> str:
        brief = normalise_newlines(brief)
        if not brief.strip():
            raise ValueError("the brief must not be empty")
        if len(brief) > MAX_BRIEF_LENGTH:
            raise ValueError(f"the brief must have at most {MAX_BRIEF_LENGTH} characters, got {len(brief)}")
        if _CONTROL.search(brief):
            raise ValueError("the brief must not contain control characters (a line break and a tab are allowed)")
        return brief

    @field_validator("code_sha256")
    @classmethod
    def _sha(cls, sha: str | None) -> str | None:
        if sha is not None and not _SHA256.fullmatch(sha):
            raise ValueError(f"code_sha256 must be 64 lowercase hex characters, got {sha!r}")
        return sha

    @model_serializer(mode="wrap")
    def _without_unset_sha(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        if data.get("code_sha256") is None:
            data.pop("code_sha256", None)
        return data
