"""Synthetic Evaluations for the report tests, built from the literal worlds of docs/metrics.md (R3) and docs/engine.md.

They build inputs only; no expected value of a test is computed here.
"""

import warnings
from datetime import date

import pandas as pd

from backtest_agent.data import DataProvider
from backtest_agent.engine import InsufficientWarmupWarning
from backtest_agent.metrics import Evaluation, MetricAssumptions, evaluate
from runner_helpers import LiteralProvider, make_spec, nan_rows, price_frame

P5 = MetricAssumptions(periods_per_year=5)
COSTS_25_PERCENT = (1000.0, 1000.0, 500.0)
A_OPEN = [100, 100, 110, 121, 133.1]
A_CLOSE = [100, 110, 121, 133.1, 146.41]
B_OPEN = [50, 50, 55, 49.5, 54.45]
B_CLOSE = [50, 55, 49.5, 54.45, 49.005]


class TrimmedProvider(DataProvider):
    """Delivers each symbol on its own trading rows only: rows where every requested symbol is NaN are dropped."""

    name = "trimmed"

    def __init__(self, inner: LiteralProvider) -> None:
        self.inner = inner

    def get_prices(self, symbols, start, end):
        return self.inner.get_prices(symbols, start, end).dropna(how="all")


def world(symbols=("A", "B")) -> pd.DataFrame:
    opens = {"A": A_OPEN, "B": B_OPEN}
    closes = {"A": A_CLOSE, "B": B_CLOSE}
    return price_frame({s: opens[s] for s in symbols}, {s: closes[s] for s in symbols})


def spec_for(benchmark: str = "B", *, name: str | None = None, **kwargs):
    spec = make_spec(
        universe=kwargs.pop("universe", ("A",)),
        start="2024-01-02",
        end="2024-01-08",
        signal=kwargs.pop("signal", "buy_and_hold"),
        params=kwargs.pop("params", {}),
        costs=kwargs.pop("costs", COSTS_25_PERCENT),
        capital=1000,
        benchmark=benchmark,
        **kwargs,
    )
    return spec.model_copy(update={"name": name or "Buy and hold A"})


def make_evaluation(spec=None, provider=None, **kwargs) -> Evaluation:
    """Evaluate on the R3 world (A vs B, 25 percent costs, 5 periods a year) unless told otherwise."""
    spec = spec if spec is not None else spec_for()
    provider = provider if provider is not None else LiteralProvider(world())
    kwargs.setdefault("assumptions", P5)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", InsufficientWarmupWarning)
        return evaluate(spec, provider, **kwargs)


def equal_start() -> Evaluation:
    """R3b: the benchmark B starts with the strategy (all dates compared, base initial equity)."""
    return make_evaluation()


def late_benchmark() -> Evaluation:
    """B has rows only from Jan 4: base is the first common date."""
    frame = nan_rows(world(), "B", before="2024-01-04")
    return make_evaluation(provider=TrimmedProvider(LiteralProvider(frame)))


def early_benchmark() -> Evaluation:
    """A has rows only from Jan 4: the strategy starts after its benchmark B."""
    frame = nan_rows(world(), "A", before="2024-01-04")
    return make_evaluation(provider=TrimmedProvider(LiteralProvider(frame)))


def insufficient_overlap() -> Evaluation:
    """B has a row only on Jan 8: one common date, so no relative metric."""
    frame = nan_rows(world(), "B", before="2024-01-08")
    return make_evaluation(provider=TrimmedProvider(LiteralProvider(frame)))


def costs_off() -> Evaluation:
    return make_evaluation(apply_costs=False)


def benchmark_in_universe() -> Evaluation:
    spec = spec_for("A", universe=("A", "B"))
    return make_evaluation(spec=spec)


def with_flags() -> Evaluation:
    """Same-bar execution and zero costs: two spec flags."""
    spec = spec_for("B", costs=(0.0, 0.0, 0.0), delay=0, price="close")
    return make_evaluation(spec=spec)


def insufficient_warmup() -> Evaluation:
    """An SMA crossover that needs 19 rows on a world with 5: the flag insufficient_warmup."""
    spec = spec_for("B", signal="sma_crossover", params={"fast": 5, "slow": 20})
    return make_evaluation(spec=spec)


def all_kinds() -> dict[str, Evaluation]:
    return {
        "equal_start": equal_start(),
        "late_benchmark": late_benchmark(),
        "early_benchmark": early_benchmark(),
        "insufficient_overlap": insufficient_overlap(),
        "costs_off": costs_off(),
        "benchmark_in_universe": benchmark_in_universe(),
        "with_flags": with_flags(),
        "insufficient_warmup": insufficient_warmup(),
    }


FIXED_DAY = date(2026, 1, 15)


def all_cells(model) -> list[str]:
    """Every display string of a ReportModel: table cells, issue rows, flag rows, heatmap cells and notes."""
    from backtest_agent.reporting.model import Table

    cells: list[str] = []

    def walk(obj) -> None:
        if isinstance(obj, Table):
            cells.extend(obj.headers)
            for row in obj.rows:
                cells.extend(row)
        elif isinstance(obj, str):
            cells.append(obj)
        elif isinstance(obj, tuple | list):
            for item in obj:
                walk(item)
        elif hasattr(obj, "__dataclass_fields__"):
            for name in obj.__dataclass_fields__:
                walk(getattr(obj, name))

    walk(model)
    return cells
