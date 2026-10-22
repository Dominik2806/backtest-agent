"""The benchmark spec (F-13; derivation in docs/metrics.md, "Benchmark and relative metrics", ADR 0013)."""

from backtest_agent.spec.schema import SignalSpec, SizingSpec, StrategySpec

_NAME_LIMIT = 100  # StrategySpec.name allows at most this many characters


def benchmark_spec(spec: StrategySpec) -> StrategySpec:
    """The spec of the buy-and-hold benchmark of ``spec``, to run through the same ``run_backtest``.

    The universe is ``[spec.benchmark]``, the signal ``buy_and_hold`` with no params, the sizing ``equal_weight`` (a
    ``fixed_fraction`` strategy still gets a fully invested benchmark) and the rebalancing ``on_signal``. The period,
    initial capital, execution rules and costs, and everything else, are copied unchanged. The name is
    ``"<name> (benchmark <SYM>)"``; the strategy name is cut so that the result stays within the length the spec allows.
    The spec is built through the constructor, so every validator runs.
    """
    suffix = f" (benchmark {spec.benchmark})"
    name = spec.name[: max(_NAME_LIMIT - len(suffix), 1)].rstrip() + suffix
    return StrategySpec(
        schema_version=spec.schema_version,
        name=name,
        description=spec.description,
        universe=[spec.benchmark],
        period=spec.period,
        data=spec.data,
        signal=SignalSpec(id="buy_and_hold", params={}),
        execution=spec.execution,
        sizing=SizingSpec(method="equal_weight"),
        rebalance="on_signal",
        costs=spec.costs,
        benchmark=spec.benchmark,
        initial_capital=spec.initial_capital,
    )
