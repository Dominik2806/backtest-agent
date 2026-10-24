"""The comparison of ``bt report`` (ADR 0016, docs/cli.md): does a re-evaluation reproduce the stored record?

Pure functions over the plain dictionaries of ``RunRecord.to_dict()``: no file, no clock, no import from the journal or
the rest of the CLI, so every rule is tested with literal dictionaries.
"""

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

COMPARED_KEYS = ("spec", "evaluation", "trades", "costs")  # not code_version, generated_at, run_number, trial_*
RELATIVE_TOLERANCE = 1e-9
_PLAIN_KEY = re.compile(r"[A-Za-z0-9_]+")


class _Missing:
    """The value of a key that one of the two sides does not have."""

    def __repr__(self) -> str:
        return "MISSING"


MISSING = _Missing()
Kind = Literal["changed", "missing", "extra"]


@dataclass(frozen=True)
class Difference:
    """One place where the fresh record is not the stored one.

    ``missing``: the key is in the stored record only; ``extra``: in the fresh record only; ``changed``: both have a
    value and the values differ (also a different type, for example an object against a number).
    """

    path: str
    stored: Any
    fresh: Any
    kind: Kind


def differences(stored: Mapping[str, Any], fresh: Mapping[str, Any]) -> list[Difference]:
    """Every difference in ``COMPARED_KEYS``, in a fixed order: the compared keys in order, inside an object the keys
    sorted, inside a list the indices, depth first."""
    found: list[Difference] = []
    for key in COMPARED_KEYS:
        _compare(key, stored.get(key, MISSING), fresh.get(key, MISSING), found)
    return found


def prioritized(found: Sequence[Difference]) -> list[Difference]:
    """The differences of the data hashes first (a changed hash explains the others), then the rest, each in order."""
    return [*(d for d in found if is_data_hash(d)), *(d for d in found if not is_data_hash(d))]


def is_data_hash(difference: Difference) -> bool:
    return difference.path.endswith("data_hash")


def change_kind(found: Sequence[Difference]) -> Literal["data", "metrics"]:
    """``data`` if a data hash differs, else ``metrics`` (any other difference of the compared keys)."""
    return "data" if any(is_data_hash(d) for d in found) else "metrics"


def _key_path(path: str, key: str) -> str:
    if _PLAIN_KEY.fullmatch(key):
        return f"{path}.{key}" if path else key
    return f"{path}[{json.dumps(key)}]"


def _compare(path: str, stored: Any, fresh: Any, found: list[Difference]) -> None:
    if stored is MISSING and fresh is MISSING:
        return
    if fresh is MISSING:
        found.append(Difference(path, stored, MISSING, "missing"))
    elif stored is MISSING:
        found.append(Difference(path, MISSING, fresh, "extra"))
    elif isinstance(stored, dict) and isinstance(fresh, dict):
        for key in sorted(set(stored) | set(fresh)):
            _compare(_key_path(path, key), stored.get(key, MISSING), fresh.get(key, MISSING), found)
    elif isinstance(stored, list) and isinstance(fresh, list):
        for index in range(max(len(stored), len(fresh))):
            one = stored[index] if index < len(stored) else MISSING
            other = fresh[index] if index < len(fresh) else MISSING
            _compare(f"{path}[{index}]", one, other, found)
    elif not _equal(stored, fresh):
        found.append(Difference(path, stored, fresh, "changed"))


def _equal(a: Any, b: Any) -> bool:
    """Scalars: strings exact; ``None`` only with ``None``; a bool only with the same bool (``True`` is not ``1``);
    two integers exact; any other pair of numbers within ``abs(a - b) <= 1e-9 * max(1, |a|, |b|)``.

    A record never holds NaN or infinity (the journal refuses to write them, an undefined metric is ``None``), so the
    case cannot occur in a real comparison; if it does, a non-finite value is equal to nothing, not even to itself.
    """
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, str) or isinstance(b, str):
        return isinstance(a, str) and isinstance(b, str) and a == b
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    if isinstance(a, int | float) and isinstance(b, int | float):
        if not (math.isfinite(a) and math.isfinite(b)):
            return False
        return abs(a - b) <= RELATIVE_TOLERANCE * max(1.0, abs(a), abs(b))
    return False
