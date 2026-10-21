"""Data layer: provider interface, providers, cache, quality validation and data hash."""

from backtest_agent.data.checks import validate_prices
from backtest_agent.data.errors import DataError, DataUnavailableError, DataValidationError, OfflineCacheMissError
from backtest_agent.data.fake import FakeProvider
from backtest_agent.data.hash import HASH_VERSION, hash_frame
from backtest_agent.data.provider import FIELDS, DataProvider, validate_standard_frame
from backtest_agent.data.validation import Severity, ValidationConfig, ValidationIssue, ValidationResult

__all__ = [
    "FIELDS",
    "HASH_VERSION",
    "DataError",
    "DataProvider",
    "DataUnavailableError",
    "DataValidationError",
    "FakeProvider",
    "OfflineCacheMissError",
    "Severity",
    "ValidationConfig",
    "ValidationIssue",
    "ValidationResult",
    "hash_frame",
    "validate_prices",
    "validate_standard_frame",
]
