"""The data provider of the command line: the default factory and the guard around any provider (ADR 0016)."""

from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

import pandas as pd

from backtest_agent.data.cache import CachedProvider
from backtest_agent.data.errors import DataError
from backtest_agent.data.provider import DataProvider
from backtest_agent.data.yfinance_provider import YFinanceProvider

ProviderFactory = Callable[[Path], DataProvider]


def default_provider_factory(cache_dir: Path) -> DataProvider:
    """Real prices from yfinance, cached as Parquet under ``cache_dir``."""
    return CachedProvider(YFinanceProvider(), cache_dir)


class GuardedProvider(DataProvider):
    """Wraps only the calls into a provider: any exception that is not a ``DataError`` becomes one.

    A connection error of the HTTP layer is a data problem for the user, not a bug (exit code 4, not 1). The original
    error is chained as the cause, so ``--debug`` shows it. ``KeyboardInterrupt`` is not an ``Exception`` and passes.
    """

    def __init__(self, inner: DataProvider) -> None:
        self.inner = inner
        self.name = inner.name

    def get_prices(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        try:
            return self.inner.get_prices(symbols, start, end)
        except DataError:
            raise
        except Exception as error:
            raise DataError(f"the data provider failed ({type(error).__name__}: {error})") from error
