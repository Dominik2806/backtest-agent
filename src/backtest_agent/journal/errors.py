"""Errors of the journal (see docs/journal.md, "Reading and failures")."""


class JournalError(Exception):
    """Base class of the journal's own errors."""


class JournalFormatError(JournalError, ValueError):
    """A run.json, an index or a set of run folders that cannot be read as what it claims to be."""


class JournalIndexStale(JournalError):
    """The run folders on disk and the rows of the index differ (or the index is missing): call ``rebuild_index``."""


class JournalBusyError(JournalError):
    """Another connection held the write lock of the index for longer than the timeout; nothing was written."""


class RunNotFoundError(JournalError):
    """There is no run folder with this id."""
