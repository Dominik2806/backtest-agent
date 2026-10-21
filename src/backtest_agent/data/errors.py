"""Errors raised by the data layer."""


class DataError(Exception):
    """Base class for all data layer errors."""


class DataUnavailableError(DataError):
    """A symbol is unknown, or the source returned no rows for the requested range."""


class DataValidationError(DataError):
    """The data quality validation found at least one error. ``result`` is the full ``ValidationResult``."""

    def __init__(self, message: str, result: object = None) -> None:
        super().__init__(message)
        self.result = result


class OfflineCacheMissError(DataError):
    """Offline mode is on and the requested data is not in the cache."""
