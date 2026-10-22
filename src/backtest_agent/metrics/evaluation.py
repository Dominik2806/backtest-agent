"""``evaluate``: a run reported next to its buy-and-hold benchmark (F-13; docs/metrics.md, ADR 0013)."""

from dataclasses import asdict, dataclass
from typing import Any

from backtest_agent.data.provider import DataProvider
from backtest_agent.engine.result import BacktestResult
from backtest_agent.engine.runner import run_backtest
from backtest_agent.metrics.benchmark import benchmark_spec
from backtest_agent.metrics.performance import (
    DEFAULT_ASSUMPTIONS,
    MetricAssumptions,
    PerformanceMetrics,
    compute_metrics,
)
from backtest_agent.metrics.relative import RelativeMetrics, compare_equity
from backtest_agent.spec.schema import StrategySpec


@dataclass(frozen=True, eq=False)  # holds results with frames, so compare fields explicitly
class Evaluation:
    """A strategy run and its benchmark run, the metrics of both and the relative metrics."""

    result: BacktestResult
    benchmark_result: BacktestResult
    metrics: PerformanceMetrics
    benchmark_metrics: PerformanceMetrics
    relative: RelativeMetrics
    assumptions: MetricAssumptions

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable summary: no frames; both data hashes, both names, risk flag codes and the alignment."""
        return {
            "strategy": {
                "name": self.result.spec.name,
                "data_hash": self.result.data_hash,
                "costs_applied": self.result.costs_applied,
                "risk_flags": [flag.code for flag in self.result.risk_flags],
                "metrics": self.metrics.to_dict(),
            },
            "benchmark": {
                "symbol": self.benchmark_result.spec.universe[0],
                "name": self.benchmark_result.spec.name,
                "data_hash": self.benchmark_result.data_hash,
                "costs_applied": self.benchmark_result.costs_applied,
                "risk_flags": [flag.code for flag in self.benchmark_result.risk_flags],
                "metrics": self.benchmark_metrics.to_dict(),
            },
            "relative": self.relative.to_dict(),
            "assumptions": asdict(self.assumptions),
        }


def evaluate_result(
    result: BacktestResult, benchmark_result: BacktestResult, assumptions: MetricAssumptions = DEFAULT_ASSUMPTIONS
) -> Evaluation:
    """Metrics of both results and the relative metrics; the pure part of ``evaluate``.

    Raises ``ValueError`` if ``benchmark_result`` is not the run of ``benchmark_spec(result.spec)`` or if the two
    results differ in ``costs_applied``: a result is never compared with a different yardstick.
    """
    if benchmark_result.spec != benchmark_spec(result.spec):
        raise ValueError("benchmark_result was not run on benchmark_spec(result.spec); it is a different yardstick")
    if benchmark_result.costs_applied != result.costs_applied:
        raise ValueError(
            f"costs_applied differs (strategy {result.costs_applied}, benchmark {benchmark_result.costs_applied})"
        )
    return Evaluation(
        result=result,
        benchmark_result=benchmark_result,
        metrics=compute_metrics(result, assumptions),
        benchmark_metrics=compute_metrics(benchmark_result, assumptions),
        relative=compare_equity(
            result.equity,
            result.initial_equity,
            benchmark_result.equity,
            benchmark_result.initial_equity,
            assumptions,
        ),
        assumptions=assumptions,
    )


def evaluate(
    spec: StrategySpec,
    provider: DataProvider,
    *,
    allow_short_warmup: bool = True,
    apply_costs: bool = True,
    assumptions: MetricAssumptions = DEFAULT_ASSUMPTIONS,
) -> Evaluation:
    """Run ``spec``, run its benchmark through the same ``run_backtest`` and provider, and compare them.

    ``allow_short_warmup`` and ``apply_costs`` go to both runs. The strategy runs first; an error of the benchmark load
    propagates unchanged and no partial result is returned.
    """
    result = run_backtest(spec, provider, allow_short_warmup=allow_short_warmup, apply_costs=apply_costs)
    benchmark_result = run_backtest(
        benchmark_spec(spec), provider, allow_short_warmup=allow_short_warmup, apply_costs=apply_costs
    )
    return evaluate_result(result, benchmark_result, assumptions)
