"""Approvals of coded signals: an append-only history in ``approvals/<id>.json`` and an archive of approved code.

An **idea** is a signal id plus its brief; the maintainer approves it before any code is written. **Code** is approved
by its sha256, and only for an idea that is already approved. Nothing is ever overwritten or removed: a changed brief
adds a new idea entry, a changed file adds a new code entry, and approving what is already approved changes nothing (the
first timestamp stays), so a stored run can always be reproduced from the idea and the code it names.

File layout (``docs/coded-signals.md`` has the literal bytes)::

    approvals/<id>.json            canonical JSON like run.json: sorted keys, no spaces, ASCII, one trailing "\\n"
    approvals/code/<sha256>.py     the approved source, line ends turned into LF; the file name is its hash

No user name, no path and no machine is ever written. Timestamps are UTC with whole seconds and come from the caller.
The functions here read and write files but never import or run a signal; that is ``coded/loader.py`` (gate).
"""

import hashlib
import json
import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backtest_agent.coded.errors import ApprovalError, ApprovalFormatError
from backtest_agent.coded.static import check_source
from backtest_agent.journal.identity import canonical_json
from backtest_agent.spec.coded_spec import check_brief, coded_id_problem, normalise_newlines

SCHEMA_VERSION = 1
LOCK_NAME = ".lock"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class CodeApproval:
    sha256: str
    approved_at: str


@dataclass(frozen=True)
class IdeaApproval:
    idea_sha256: str
    approved_at: str
    code: tuple[CodeApproval, ...] = ()

    @property
    def latest_code(self) -> CodeApproval | None:
        """The most recently approved code of this idea, or None."""
        return self.code[-1] if self.code else None

    def has_code(self, sha256: str) -> bool:
        return any(entry.sha256 == sha256 for entry in self.code)


@dataclass(frozen=True)
class ApprovalRecord:
    signal_id: str
    ideas: tuple[IdeaApproval, ...] = ()

    def idea(self, idea_sha256: str) -> IdeaApproval | None:
        """The entry of this idea hash, or None."""
        return next((entry for entry in self.ideas if entry.idea_sha256 == idea_sha256), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ideas": [
                {
                    "approved_at": idea.approved_at,
                    "code": [{"approved_at": c.approved_at, "sha256": c.sha256} for c in idea.code],
                    "idea_sha256": idea.idea_sha256,
                }
                for idea in self.ideas
            ],
            "schema_version": SCHEMA_VERSION,
            "signal_id": self.signal_id,
        }


# --- hashes ---


def idea_sha256(signal_id: str, brief: str) -> str:
    """SHA-256 of ``canonical_json({"brief": <brief, CRLF turned into LF>, "signal_id": <id>})`` as UTF-8.

    The brief is not stripped or changed in any other way, and nothing else of the spec (params, universe, period,
    costs, name, description) is part of the idea.
    """
    payload = canonical_json({"brief": normalise_newlines(brief), "signal_id": signal_id})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalise_source(source: bytes) -> bytes:
    """CRLF turned into LF; nothing else is changed. The bytes that are hashed, archived and (later) run."""
    return source.replace(b"\r\n", b"\n")


def code_sha256(source: bytes) -> str:
    """SHA-256 of the source after ``normalise_source``."""
    return hashlib.sha256(normalise_source(source)).hexdigest()


def format_time(moment: datetime) -> str:
    """UTC, whole seconds, ``YYYY-MM-DDTHH:MM:SSZ``. A naive datetime is refused."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("the approval time must be timezone-aware")
    return moment.astimezone(UTC).strftime(_TIME_FORMAT)


# --- paths ---


def record_path(approvals_dir: Path | str, signal_id: str) -> Path:
    problem = coded_id_problem(signal_id)
    if problem is not None:
        raise ValueError(problem)
    return Path(approvals_dir) / f"{signal_id}.json"


def code_path(approvals_dir: Path | str, sha256: str) -> Path:
    if not _SHA256.fullmatch(sha256):
        raise ValueError(f"a code hash must be 64 lowercase hex characters, got {sha256!r}")
    return Path(approvals_dir) / "code" / f"{sha256}.py"


# --- reading ---


def read_record(approvals_dir: Path | str, signal_id: str) -> ApprovalRecord | None:
    """The record of ``signal_id``, or None if there is no file. A file that is not a valid record raises
    ``ApprovalFormatError``."""
    path = record_path(approvals_dir, signal_id)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ApprovalFormatError(f"{path.name}: cannot be read ({error.strerror or error})") from None
    return parse_record(raw, signal_id, path.name)


def parse_record(raw: bytes, signal_id: str, name: str) -> ApprovalRecord:
    def fail(reason: str) -> ApprovalFormatError:
        return ApprovalFormatError(f"{name}: {reason}")

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise fail("is not valid JSON in UTF-8") from None
    if not isinstance(data, dict) or set(data) != {"ideas", "schema_version", "signal_id"}:
        raise fail('must be an object with exactly the keys "ideas", "schema_version" and "signal_id"')
    if data["schema_version"] != SCHEMA_VERSION or isinstance(data["schema_version"], bool):
        raise fail(f"schema_version must be {SCHEMA_VERSION}, got {data['schema_version']!r}")
    if data["signal_id"] != signal_id:
        raise fail(f"signal_id is {data['signal_id']!r} but the file is the record of {signal_id!r}")
    if not isinstance(data["ideas"], list):
        raise fail('"ideas" must be a list')

    ideas: list[IdeaApproval] = []
    for position, entry in enumerate(data["ideas"]):
        where = f"ideas[{position}]"
        if not isinstance(entry, dict) or set(entry) != {"approved_at", "code", "idea_sha256"}:
            raise fail(f'{where} must be an object with exactly the keys "approved_at", "code" and "idea_sha256"')
        _check_time(entry["approved_at"], f"{where}.approved_at", fail)
        _check_sha(entry["idea_sha256"], f"{where}.idea_sha256", fail)
        if any(previous.idea_sha256 == entry["idea_sha256"] for previous in ideas):
            raise fail(f"{where}.idea_sha256 appears twice")
        if not isinstance(entry["code"], list):
            raise fail(f"{where}.code must be a list")
        code: list[CodeApproval] = []
        for index, item in enumerate(entry["code"]):
            at = f"{where}.code[{index}]"
            if not isinstance(item, dict) or set(item) != {"approved_at", "sha256"}:
                raise fail(f'{at} must be an object with exactly the keys "approved_at" and "sha256"')
            _check_time(item["approved_at"], f"{at}.approved_at", fail)
            _check_sha(item["sha256"], f"{at}.sha256", fail)
            if any(previous.sha256 == item["sha256"] for previous in code):
                raise fail(f"{at}.sha256 appears twice")
            code.append(CodeApproval(item["sha256"], item["approved_at"]))
        ideas.append(IdeaApproval(entry["idea_sha256"], entry["approved_at"], tuple(code)))
    return ApprovalRecord(signal_id, tuple(ideas))


def _check_time(value: Any, where: str, fail: Callable[[str], ApprovalFormatError]) -> None:
    if not isinstance(value, str) or not _TIME.fullmatch(value):
        raise fail(f"{where} must be a UTC time such as 2026-11-02T10:00:00Z, got {value!r}")
    try:
        datetime.strptime(value, _TIME_FORMAT)
    except ValueError:
        raise fail(f"{where} is not a valid time, got {value!r}") from None


def _check_sha(value: Any, where: str, fail: Callable[[str], ApprovalFormatError]) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise fail(f"{where} must be 64 lowercase hex characters, got {value!r}")


def render_record(record: ApprovalRecord) -> bytes:
    """Canonical JSON plus one LF, UTF-8, the same form as ``run.json``."""
    return (canonical_json(record.to_dict()) + "\n").encode("utf-8")


# --- writing (append-only) ---


@contextmanager
def approvals_lock(approvals_dir: Path | str) -> Iterator[None]:
    """Hold ``approvals/.lock`` while an approval is read, changed and written.

    The file is created exclusively; if it exists, another approval is running (or crashed and left it) and
    ``ApprovalError`` says so. It is removed on the way out, also after an error. It holds nothing.
    """
    directory = Path(approvals_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / LOCK_NAME
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ApprovalError(
            f"another approval is in progress ({LOCK_NAME} exists in the approvals folder); if no other bt approve "
            "is running, delete that file and try again"
        ) from None
    os.close(descriptor)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def approve_idea(
    approvals_dir: Path | str, signal_id: str, brief: str, moment: datetime
) -> tuple[ApprovalRecord, bool]:
    """Approve the idea ``(signal_id, brief)``. Returns the record and whether anything was written.

    An idea that is already approved is a no-op (the original timestamp stays). A new brief appends a new entry; earlier
    entries and their code are untouched.
    """
    stamp = format_time(moment)
    record_path(approvals_dir, signal_id)  # refuses an id that is not a coded signal id before anything is touched
    try:
        brief = check_brief(brief)  # the rules of the spec: an idea the spec would refuse is not approved
    except ValueError as error:
        raise ApprovalError(f"the brief is not valid: {error}") from None
    digest = idea_sha256(signal_id, brief)
    with approvals_lock(approvals_dir):
        record = read_record(approvals_dir, signal_id) or ApprovalRecord(signal_id)
        if record.idea(digest) is not None:
            return record, False
        record = ApprovalRecord(signal_id, (*record.ideas, IdeaApproval(digest, stamp)))
        _write_atomic(record_path(approvals_dir, signal_id), render_record(record))
        return record, True


def approve_code(
    approvals_dir: Path | str, signal_id: str, brief: str, source: bytes, moment: datetime
) -> tuple[ApprovalRecord, str, bool]:
    """Approve ``source`` as the code of the idea ``(signal_id, brief)``. Returns the record, the code hash and whether
    anything was written.

    The idea must already be approved (``ApprovalError`` otherwise) and the source must pass the static check
    (``StaticCheckError``); nothing is written if either fails. The normalised bytes are archived under their own hash.
    A hash that is already approved for this idea is a no-op.
    """
    stamp = format_time(moment)
    record_path(approvals_dir, signal_id)  # as above
    with approvals_lock(approvals_dir):
        record = read_record(approvals_dir, signal_id)
        entry = None if record is None else record.idea(idea_sha256(signal_id, brief))
        if record is None or entry is None:
            raise ApprovalError(f"the idea of {signal_id!r} with this brief is not approved; approve the idea first")
        data = normalise_source(source)
        check_source(data, signal_id)
        digest = hashlib.sha256(data).hexdigest()
        if entry.has_code(digest):
            return record, digest, False
        _archive(code_path(approvals_dir, digest), data)
        ideas = tuple(
            IdeaApproval(i.idea_sha256, i.approved_at, (*i.code, CodeApproval(digest, stamp))) if i is entry else i
            for i in record.ideas
        )
        record = ApprovalRecord(signal_id, ideas)
        _write_atomic(record_path(approvals_dir, signal_id), render_record(record))
        return record, digest, True


def read_archived_code(approvals_dir: Path | str, sha256: str) -> bytes:
    """The archived bytes of an approved hash. ``ApprovalError`` if the file is missing or its bytes do not hash to its
    name (the archive was edited)."""
    path = code_path(approvals_dir, sha256)
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise ApprovalError(f"the archived code {sha256[:8]} is missing") from None
    except OSError as error:
        raise ApprovalError(f"the archived code {sha256[:8]} cannot be read ({error.strerror or error})") from None
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ApprovalError(f"the archived code {sha256[:8]} does not match its hash; the archive was changed")
    return data


def _archive(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise ApprovalError(f"the archived code {path.stem[:8]} exists with other bytes; the archive was changed")
        return
    _write_atomic(path, data)


def _write_atomic(path: Path, data: bytes) -> None:
    """Write ``data`` as the whole file: a temporary file in the same folder, then a rename. No newline translation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
