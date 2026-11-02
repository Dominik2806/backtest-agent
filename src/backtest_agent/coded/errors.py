"""Errors of the coded-signal layer."""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Finding:
    """One problem found in a source file: where it is, which rule found it, and what is wrong."""

    line: int
    column: int
    rule: str
    message: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.message} [{self.rule}]" if self.line else f"{self.message} [{self.rule}]"


class StaticCheckError(Exception):
    """The source of a coded signal breaks a rule of the static check; ``findings`` lists every problem."""

    def __init__(self, findings: Sequence[Finding]) -> None:
        self.findings = tuple(findings)
        count = len(self.findings)
        header = f"the signal source breaks {count} rule{'s' if count != 1 else ''} of the static check:"
        super().__init__("\n".join([header, *(f"  - {finding}" for finding in self.findings)]))


class ApprovalError(Exception):
    """An approval cannot be given or read: the idea is not approved, or an archived file is missing or was changed."""


class ApprovalFormatError(ApprovalError):
    """A file in ``approvals/`` is not a valid approval record; the message names the file and the field."""


class GateError(Exception):
    """The approval gate refuses to load a coded signal; the message says why (nothing was compiled or run)."""


class NotApprovedError(GateError):
    """A person has to approve something (the idea or the code) before this can run; exit code 8 of ``bt run``."""


class RecordError(GateError):
    """The approvals folder cannot supply what the spec needs, or it was changed (a record or an archive is missing or
    does not match its hash); in stored mode (``bt report``) this is a record that cannot be reproduced, exit code 5."""


class CasesError(Exception):
    """The ``cases.yaml`` of a coded signal is missing or not valid, or the signal does not give its examples; the
    message lists every problem. Like a failed contract check this is exit code 9 of ``bt signal check``."""
