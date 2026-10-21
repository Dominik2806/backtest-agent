"""Errors of the spec layer."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SpecProblem:
    """One problem of a strategy spec: a dotted field path (``(root)`` for the document) and a readable message."""

    path: str
    message: str


class SpecError(Exception):
    """A strategy spec is invalid. ``problems`` lists every problem, not only the first one."""

    def __init__(self, problems: tuple[SpecProblem, ...] | list[SpecProblem], source: str | None = None) -> None:
        self.problems = tuple(problems)
        self.source = source
        where = f" in {source}" if source else ""
        count = len(self.problems)
        header = f"Invalid strategy spec{where} ({count} problem{'s' if count != 1 else ''}):"
        super().__init__("\n".join([header, *(f"  - {p.path}: {p.message}" for p in self.problems)]))


class SignalContractError(ValueError):
    """Input or output of a signal violates the signal contract (see docs/strategy-spec.md)."""


class UnknownSignalError(LookupError):
    """No signal is registered under the requested id; the message names the available ids."""
