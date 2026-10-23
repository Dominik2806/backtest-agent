"""Run ids (F-14, F-15; the exact hash input is written out in docs/adr/0014-report.md).

A run id is ``<YYYYMMDDTHHMMSSZ>-<slug of the strategy name>-<8 hex characters>``. It is built outside any renderer from
an explicit ``generated_at``, so the same inputs at the same time give the same id. The 8 hex characters identify the
inputs of the run and do not depend on the time: two runs of the same spec on the same data have the same suffix.
"""

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict
from datetime import UTC, datetime

from backtest_agent.metrics.evaluation import Evaluation

SLUG_LIMIT = 40
_SAFE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}")
_WINDOWS_DEVICE = re.compile(r"(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", re.IGNORECASE)
_NOT_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """A name as a folder-safe slug: ASCII, lowercase, ``[a-z0-9]`` separated by single dashes, at most 40 characters.

    Everything else (spaces, dots, slashes, colons, quotes, non-ASCII characters) becomes a dash, so the result has no
    character that Windows or POSIX forbid in a name and no trailing dot or space. An empty result is ``run``.
    """
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    return _NOT_SLUG.sub("-", folded).strip("-")[:SLUG_LIMIT].strip("-") or "run"


def run_id_hash_input(evaluation: Evaluation) -> str:
    """The text that is hashed: canonical JSON (sorted keys, no spaces) of the spec and the inputs that change a number.

    Keys: ``assumptions`` (``periods_per_year``, ``risk_free_rate``), ``benchmark_data_hash``, ``costs_applied`` (of the
    strategy run), ``spec`` (``StrategySpec.to_dict()``) and ``strategy_data_hash``.
    """
    payload = {
        "assumptions": asdict(evaluation.assumptions),
        "benchmark_data_hash": evaluation.benchmark_result.data_hash,
        "costs_applied": evaluation.result.costs_applied,
        "spec": evaluation.result.spec.to_dict(),
        "strategy_data_hash": evaluation.result.data_hash,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def inputs_digest(evaluation: Evaluation) -> str:
    """The 8 hex characters: the first 8 of the SHA-256 of ``run_id_hash_input`` encoded as UTF-8."""
    return hashlib.sha256(run_id_hash_input(evaluation).encode("utf-8")).hexdigest()[:8]


def make_run_id(evaluation: Evaluation, generated_at: datetime) -> str:
    """``<UTC timestamp>-<slug>-<8 hex>``; ``generated_at`` must be timezone-aware (``ValueError`` otherwise)."""
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware; pass a datetime in UTC, e.g. datetime.now(timezone.utc)")
    stamp = generated_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{slugify(evaluation.result.spec.name)}-{inputs_digest(evaluation)}"


def check_run_id(run_id: str) -> str:
    """The run id as a folder name: one path component made of letters, digits, ``.``, ``_`` and ``-``.

    Raises ``ValueError`` for anything that could leave the reports folder or is not a valid Windows name: path
    separators, ``..``, a drive colon, a leading dot, a trailing dot or space, a Windows device name such as ``CON``,
    an empty or a very long name.
    """
    reserved = _WINDOWS_DEVICE.fullmatch(run_id.split(".")[0])
    if not _SAFE_RUN_ID.fullmatch(run_id) or run_id.endswith(".") or ".." in run_id or reserved:
        raise ValueError(
            f"{run_id!r} is not a safe run id: use letters, digits, '.', '_' and '-' in one path component"
        )
    return run_id
