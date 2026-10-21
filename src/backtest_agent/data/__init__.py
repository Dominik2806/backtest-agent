"""Data layer: provider interface, providers, cache (validation and data hash follow in Phase 2)."""

from backtest_agent.data.errors import DataError, DataUnavailableError, OfflineCacheMissError
from backtest_agent.data.fake import FakeProvider
from backtest_agent.data.provider import FIELDS, DataProvider, validate_standard_frame

__all__ = [
    "FIELDS",
    "DataError",
    "DataProvider",
    "DataUnavailableError",
    "FakeProvider",
    "OfflineCacheMissError",
    "validate_standard_frame",
]
