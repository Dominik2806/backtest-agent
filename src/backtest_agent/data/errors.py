"""Errors raised by the data layer."""


class DataError(Exception):
    """Base class for all data layer errors."""


class DataUnavailableError(DataError):
    """A symbol is unknown, or the source returned no rows for the requested range."""


class OfflineCacheMissError(DataError):
    """Offline mode is on and the requested data is not in the cache."""
