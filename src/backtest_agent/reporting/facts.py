"""Facts about a run that the model and the caveats both need, read from the dataclasses (nothing is recomputed)."""

from dataclasses import dataclass
from datetime import date

from backtest_agent.metrics.evaluation import Evaluation


@dataclass(frozen=True)
class BenchmarkTiming:
    """First and last bar of the strategy and of the benchmark run, and how the benchmark relates to the strategy."""

    strategy_first: date
    strategy_last: date
    benchmark_first: date
    benchmark_last: date

    @property
    def starts_later(self) -> bool:
        return self.benchmark_first > self.strategy_first

    @property
    def starts_earlier(self) -> bool:
        return self.benchmark_first < self.strategy_first

    @property
    def ends_earlier(self) -> bool:
        return self.benchmark_last < self.strategy_last

    @property
    def ends_later(self) -> bool:
        return self.benchmark_last > self.strategy_last

    @property
    def same_start(self) -> bool:
        return self.benchmark_first == self.strategy_first


def benchmark_timing(evaluation: Evaluation) -> BenchmarkTiming:
    strategy, benchmark = evaluation.result.equity.index, evaluation.benchmark_result.equity.index
    return BenchmarkTiming(
        strategy_first=strategy[0].date(),
        strategy_last=strategy[-1].date(),
        benchmark_first=benchmark[0].date(),
        benchmark_last=benchmark[-1].date(),
    )
