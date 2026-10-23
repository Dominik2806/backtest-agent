"""What makes two runs the same family or the same variant (docs/journal.md, "Strategy family" and "Variant hash")."""

import hashlib
import json
from typing import Any

from backtest_agent.spec.schema import StrategySpec

_NOT_PART_OF_A_VARIANT = ("name", "description")


def canonical_json(payload: Any) -> str:
    """Sorted keys, no spaces, ASCII only; NaN and infinity raise ``ValueError`` instead of becoming text."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def family_of(spec: StrategySpec) -> str:
    """The strategy family of a spec: its signal id (``spec.signal.id``), nothing else.

    The universe, period, costs and name do not change the family, and a built-in such as ``buy_and_hold`` is a
    registered signal like any other. Limit: a renamed or copied signal is a new family with a counter at zero.
    """
    return spec.signal.id


def variant_hash_of_dict(spec_dict: dict[str, Any]) -> str:
    """SHA-256 (64 hex) of the canonical JSON of ``StrategySpec.to_dict()`` without ``name`` and ``description``."""
    payload = {key: value for key, value in spec_dict.items() if key not in _NOT_PART_OF_A_VARIANT}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def variant_hash(spec: StrategySpec) -> str:
    """The hash that identifies the idea that was tried; not the 8 character hash of the run id."""
    return variant_hash_of_dict(spec.to_dict())
