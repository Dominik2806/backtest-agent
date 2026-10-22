"""evaluate and evaluate_result: fixtures R3a to R3c of docs/metrics.md, the yardstick checks and the serialization.

The expected values of R3 are literals taken from that document (the world of H23 in docs/engine.md plus a symbol B).
"""

import json
from datetime import date

import pandas as pd
import pytest

from backtest_agent.data import DataProvider, DataUnavailableError
from backtest_agent.engine import run_backtest
from backtest_agent.metrics import MetricAssumptions, benchmark_spec, evaluate, evaluate_result
from runner_helpers import LiteralProvider, fake_frame, make_spec, nan_rows, price_frame

TOLERANCE = 1e-9
P5 = MetricAssumptions(periods_per_year=5)
COSTS_25_PERCENT = (1000.0, 1000.0, 500.0)
FETCH = (date(2023, 12, 17), date(2024, 1, 8))  # 2024-01-02 minus 2 * (0 + 1) + 14 = 16 days, up to period.end

A_OPEN = [100, 100, 110, 121, 133.1]
A_CLOSE = [100, 110, 121, 133.1, 146.41]
B_OPEN = [50, 50, 55, 49.5, 54.45]
B_CLOSE = [50, 55, 49.5, 54.45, 49.005]


def approx(value):
    return pytest.approx(value, rel=TOLERANCE, abs=TOLERANCE)


def world(symbols=("A", "B")) -> pd.DataFrame:
    opens = {"A": A_OPEN, "B": B_OPEN}
    closes = {"A": A_CLOSE, "B": B_CLOSE}
    return price_frame({s: opens[s] for s in symbols}, {s: closes[s] for s in symbols})


def spec_for(benchmark: str):
    return make_spec(
        universe=("A",),
        start="2024-01-02",
        end="2024-01-08",
        signal="buy_and_hold",
        params={},
        costs=COSTS_25_PERCENT,
        capital=1000,
        benchmark=benchmark,
    )


# --- R3a ------------------------------------------------------------------------------------------------------------


def test_r3a_a_strategy_equal_to_its_benchmark() -> None:
    provider = LiteralProvider(world(("A",)))
    ev = evaluate(spec_for("A"), provider, assumptions=P5)

    assert provider.calls == [(("A",), *FETCH), (("A",), *FETCH)]
    for result in (ev.result, ev.benchmark_result):
        assert list(result.equity) == approx([1000, 880, 968, 1064.8, 1171.28])
        assert list(result.returns) == approx([0, -0.12, 0.1, 0.1, 0.1])
    for metrics in (ev.metrics, ev.benchmark_metrics):  # the M12 literals
        assert metrics.total_return == approx(0.17128)
        assert metrics.cagr == approx(0.17128)
        assert metrics.volatility == approx(0.217715410571)
        assert metrics.sharpe == approx(0.826767381914)
        assert metrics.sortino == approx(1.5)
        assert metrics.max_drawdown == approx(-0.12)
        assert metrics.calmar == approx(1.427333333333)
        assert metrics.hit_rate == approx(0.6)

    rel = ev.relative
    assert rel.excess_return == 0.0
    assert rel.tracking_error == 0.0
    assert rel.information_ratio is None
    al = rel.alignment
    assert (al.base, al.n_common, al.n_compared) == ("initial_equity", 5, 5)
    assert (al.n_dropped_strategy, al.n_dropped_benchmark, al.dates_dropped, al.insufficient_overlap) == (
        0,
        0,
        False,
        False,
    )
    assert ev.benchmark_result.spec == benchmark_spec(ev.result.spec)
    assert ev.benchmark_result.spec.name == f"{ev.result.spec.name} (benchmark A)"


# --- R3b ------------------------------------------------------------------------------------------------------------


def test_r3b_the_benchmark_carries_the_strategys_costs() -> None:
    provider = LiteralProvider(world())
    ev = evaluate(spec_for("B"), provider, assumptions=P5)

    assert provider.calls == [(("A",), *FETCH), (("B",), *FETCH)]
    assert list(ev.result.equity) == approx([1000, 880, 968, 1064.8, 1171.28])
    assert ev.result.net_return == approx(0.17128)

    bench = ev.benchmark_result
    assert list(bench.equity) == approx([1000, 880, 792, 871.2, 784.08])
    assert list(bench.returns) == approx([0, -0.12, -0.1, 0.1, -0.1])
    assert bench.net_return == approx(-0.21592)
    assert bench.total_costs == approx(200)
    assert list(bench.positions["B"]) == approx([0, 16, 16, 16, 16])
    assert ev.benchmark_metrics.total_return == approx(-0.21592)
    assert ev.benchmark_metrics.hit_rate == approx(0.2)
    assert ev.benchmark_metrics.max_drawdown == approx(-0.21592)

    rel = ev.relative
    assert rel.excess_return == approx(0.3872)  # a cost-free benchmark would give 0.19118
    assert rel.tracking_error == approx(0.244948974278)
    assert rel.information_ratio == approx(1.632993161855)
    assert rel.strategy_return_compared == approx(0.17128)
    assert rel.benchmark_return_compared == approx(-0.21592)
    assert not rel.alignment.dates_dropped and rel.alignment.base == "initial_equity"


# --- R3c ------------------------------------------------------------------------------------------------------------


def test_r3c_apply_costs_false_reaches_both_runs() -> None:
    ev = evaluate(spec_for("B"), LiteralProvider(world()), apply_costs=False, assumptions=P5)
    assert ev.result.costs_applied is False and ev.benchmark_result.costs_applied is False
    assert "costs_not_applied" in {flag.code for flag in ev.result.risk_flags}
    assert "costs_not_applied" in {flag.code for flag in ev.benchmark_result.risk_flags}
    assert list(ev.result.equity) == approx([1000, 1100, 1210, 1331, 1464.1])
    assert ev.benchmark_result.net_return == approx(-0.0199)
    assert ev.relative.excess_return == approx(0.4840)
    assert ev.relative.tracking_error == approx(0.244948974278)
    assert ev.relative.information_ratio == approx(1.632993161855)
    assert ev.to_dict()["strategy"]["costs_applied"] is False and ev.to_dict()["benchmark"]["costs_applied"] is False


# --- evaluate_result checks the yardstick ----------------------------------------------------------------------------


def results():
    spec = spec_for("B")
    provider = LiteralProvider(world())
    return spec, run_backtest(spec, provider), run_backtest(benchmark_spec(spec), provider)


def test_evaluate_result_accepts_the_matching_pair() -> None:
    spec, result, bench = results()
    ev = evaluate_result(result, bench, P5)
    assert ev.relative.excess_return == approx(0.3872)
    assert ev.assumptions == P5


def test_a_benchmark_result_of_another_spec_raises() -> None:
    spec, result, _ = results()
    other = benchmark_spec(spec.model_copy(update={"initial_capital": 2000.0}))
    wrong = run_backtest(other, LiteralProvider(world()))
    with pytest.raises(ValueError, match="different yardstick"):
        evaluate_result(result, wrong)


def test_the_strategy_result_is_not_a_benchmark_result() -> None:
    _, result, _ = results()
    with pytest.raises(ValueError, match="different yardstick"):
        evaluate_result(result, result)


def test_another_costs_applied_raises() -> None:
    spec, result, _ = results()
    free = run_backtest(benchmark_spec(spec), LiteralProvider(world()), apply_costs=False)
    with pytest.raises(ValueError, match="costs_applied"):
        evaluate_result(result, free)


# --- serialization ----------------------------------------------------------------------------------------------------


def test_to_dict_is_json_serializable_and_has_the_identifiers() -> None:
    ev = evaluate(spec_for("B"), LiteralProvider(world()), assumptions=P5)
    d = ev.to_dict()
    assert json.loads(json.dumps(d)) == d
    assert d["strategy"]["data_hash"] == ev.result.data_hash
    assert d["benchmark"]["data_hash"] == ev.benchmark_result.data_hash
    assert d["strategy"]["data_hash"] != d["benchmark"]["data_hash"]
    assert d["strategy"]["name"] == ev.result.spec.name
    assert d["benchmark"]["name"] == ev.benchmark_result.spec.name and d["benchmark"]["symbol"] == "B"
    assert d["strategy"]["risk_flags"] == [flag.code for flag in ev.result.risk_flags]
    assert d["benchmark"]["risk_flags"] == [flag.code for flag in ev.benchmark_result.risk_flags]
    assert d["relative"]["alignment"]["n_compared"] == 5
    assert d["relative"]["excess_return"] == approx(0.3872)
    assert d["assumptions"] == {"periods_per_year": 5, "risk_free_rate": 0.0}
    assert d["strategy"]["metrics"]["total_return"] == approx(0.17128)
    assert d["benchmark"]["metrics"]["total_return"] == approx(-0.21592)
    assert set(d) == {"strategy", "benchmark", "relative", "assumptions"}


def test_to_dict_carries_the_flag_codes_as_strings() -> None:
    ev = evaluate(spec_for("B"), LiteralProvider(world()), apply_costs=False)
    flags = ev.to_dict()["strategy"]["risk_flags"]
    assert isinstance(flags, list) and all(isinstance(code, str) for code in flags)
    assert "costs_not_applied" in flags


# --- the provider and the calendars -----------------------------------------------------------------------------------


def test_missing_benchmark_data_propagates_the_provider_error() -> None:
    with pytest.raises(DataUnavailableError, match="unknown symbols"):
        evaluate(spec_for("ZZZ"), LiteralProvider(world(("A",))))


def test_a_benchmark_inside_the_universe_is_its_own_run() -> None:
    spec = make_spec(universe=("AAA", "BBB"), benchmark="AAA")
    provider = LiteralProvider(fake_frame(("AAA", "BBB"), date(2023, 12, 1), date(2024, 4, 30)))
    ev = evaluate(spec, provider)
    assert [symbols for symbols, _, _ in provider.calls] == [("AAA", "BBB"), ("AAA",)]
    assert ev.benchmark_result.spec.universe == ["AAA"]
    assert ev.benchmark_result.data_hash != ev.result.data_hash  # own load, own hash


class TrimmedProvider(DataProvider):
    """Delivers each symbol on its own trading rows only: rows where every requested symbol is NaN are dropped."""

    name = "trimmed"

    def __init__(self, inner: LiteralProvider) -> None:
        self.inner = inner

    def get_prices(self, symbols, start, end):
        return self.inner.get_prices(symbols, start, end).dropna(how="all")


def test_a_benchmark_that_starts_late_aligns_without_error() -> None:
    frame = nan_rows(world(), "B", before="2024-01-04")  # B has rows only from Jan 4
    ev = evaluate(spec_for("B"), TrimmedProvider(LiteralProvider(frame)), assumptions=P5)
    al = ev.relative.alignment
    assert [ts.date() for ts in ev.benchmark_result.equity.index] == [date(2024, 1, d) for d in (4, 5, 8)]
    assert (al.n_strategy_bars, al.n_benchmark_bars, al.n_common) == (5, 3, 3)
    assert (al.n_dropped_strategy, al.n_dropped_benchmark) == (2, 0)
    assert al.dates_dropped and al.base == "first_common_date" and al.base_date == "2024-01-04"
    assert al.n_compared == 2 and not al.insufficient_overlap
    assert ev.relative.excess_return is not None


def test_a_benchmark_that_ends_early_aligns_without_error() -> None:
    frame = nan_rows(world(), "B", between=("2024-01-05", "2024-01-08"))
    ev = evaluate(spec_for("B"), TrimmedProvider(LiteralProvider(frame)), assumptions=P5)
    al = ev.relative.alignment
    assert (al.n_strategy_bars, al.n_benchmark_bars, al.n_common) == (5, 3, 3)
    assert (al.n_dropped_strategy, al.n_dropped_benchmark) == (2, 0)
    assert al.base == "initial_equity" and al.n_compared == 3
    assert ev.relative.excess_return is not None
