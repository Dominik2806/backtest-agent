"""The two requests of a run, fetched without running it (``bt data fetch``, ``bt validate --data``).

Everything that knows a window or loads data lives in ``backtest_agent.engine`` (``load_history``,
``warmup_window``); this module only calls it for the spec and for its benchmark, as ``evaluate`` does.
"""

from dataclasses import dataclass

import pandas as pd

from backtest_agent.data import DataProvider
from backtest_agent.engine import LoadedHistory, load_history
from backtest_agent.metrics import benchmark_spec
from backtest_agent.spec import StrategySpec


@dataclass(frozen=True)
class DataFetch:
    """What a run would load: the universe over its window and the benchmark over its own window."""

    spec: StrategySpec
    strategy: LoadedHistory
    benchmark: LoadedHistory

    @property
    def error_count(self) -> int:
        """Validation errors of both requests: a run on this data would fail if it is above 0."""
        return len(self.strategy.validation.errors) + len(self.benchmark.validation.errors)


def fetch_data(spec: StrategySpec, provider: DataProvider) -> DataFetch:
    """Make exactly the requests of ``evaluate(spec, provider)``: ``spec`` first, then ``benchmark_spec(spec)``."""
    return DataFetch(spec, load_history(spec, provider), load_history(benchmark_spec(spec), provider))


def rows_with_data(frame: pd.DataFrame, symbol: str) -> int:
    """Rows in which the symbol has at least one value (all-NaN rows are not trading days, docs/data.md)."""
    return int(frame[symbol].notna().any(axis=1).sum())
