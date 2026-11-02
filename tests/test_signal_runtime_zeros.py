"""Runtime rule of ``Signal.generate``: 0.0 before a symbol's (W+1)-th trading row (docs/strategy-spec.md, ADR 0017).

W is ``warmup_rows``. The frames are literal; every expected count, symbol and date is written out by hand next to the
frame, none comes from project code. Bars are Mon-Fri from 2024-01-02: row 0 is Jan 2, row 1 Jan 3, row 2 Jan 4,
row 3 Jan 5, row 4 Jan 8, row 5 Jan 9.
"""

from datetime import date

import pandas as pd
import pytest

from backtest_agent.engine import run_backtest
from backtest_agent.spec import SIGNALS, Signal, SignalContractError, SignalParams, get_signal
from backtest_agent.spec.signals import validate_signal_zeros
from runner_helpers import LiteralProvider, make_spec, price_frame

NAN = float("nan")


class NoWarmup(SignalParams):
    """warmup_rows is 0 (the default)."""


class TwoRows(SignalParams):
    def warmup_rows(self) -> int:
        return 2


def always_on(prices: pd.DataFrame, params: SignalParams) -> pd.DataFrame:
    """A signal that breaks the rule: 1.0 on every row of every symbol."""
    return pd.DataFrame(1.0, index=prices.index, columns=prices.columns.get_level_values("symbol").unique())


def frame(closes: dict[str, list[float]]) -> pd.DataFrame:
    return price_frame(closes, closes)  # opens equal closes; only the close matters for these tests


def signal_with(params: type[SignalParams], function=always_on) -> Signal:
    return Signal("fixture_always_on", params, function)


def values(prices: pd.DataFrame, **columns: list[float]) -> pd.DataFrame:
    """A signal frame on the index and symbols of ``prices`` from literal columns."""
    out = pd.DataFrame(columns, index=prices.index, dtype="float64")
    out.columns = pd.Index(list(columns), name="symbol")
    return out


# A trades on all 6 rows; B has no close on rows 0 and 1 (trading rows 2 to 5); C has no close on row 2 only.
PRICES = frame(
    {
        "A": [10, 11, 12, 13, 14, 15],
        "B": [NAN, NAN, 20, 21, 22, 23],
        "C": [30, 31, NAN, 33, 34, 35],
    }
)


def test_zero_before_the_first_trading_row_passes() -> None:
    signals = values(
        PRICES,
        A=[1, 1, 1, 1, 1, 1],
        B=[0, 0, 1, 1, 1, 1],  # first trading row is row 2
        C=[1, 1, 1, 1, 1, 1],  # the holiday on row 2 carries the held exposure: allowed
    )
    validate_signal_zeros(PRICES, signals, 0)


def test_exposure_before_the_first_trading_row_is_refused_with_symbol_count_and_first_date() -> None:
    signals = values(PRICES, A=[1, 1, 1, 1, 1, 1], B=[1, 0.5, 1, 1, 1, 1], C=[1, 1, 1, 1, 1, 1])
    # B: rows 0 and 1 are before its first trading row (row 2): 2 values, first on Jan 2.
    with pytest.raises(SignalContractError) as info:
        validate_signal_zeros(PRICES, signals, 0)
    assert str(info.value) == (
        "signal output violates the contract: exposure must be 0.0 before a symbol's trading row 1 "
        "(warmup_rows is 0); 'B': 2 value(s) non-zero, first at 2024-01-02"
    )


def test_exposure_during_the_warm_up_is_refused() -> None:
    # W = 2: a symbol must be 0.0 until its third trading row.
    # A: third trading row is row 2, so rows 0 and 1 must be 0: 1.0 on both = 2 values, first Jan 2.
    # B: third trading row is row 4, so rows 0 to 3 must be 0: 1.0 on rows 2 and 3 = 2 values, first Jan 4.
    # C: trading rows 0, 1, 3 -> third trading row is row 3, so rows 0 to 2 must be 0: 1.0 on all 3, first Jan 2.
    signals = values(PRICES, A=[1, 1, 1, 1, 1, 1], B=[0, 0, 1, 1, 1, 1], C=[1, 1, 1, 1, 1, 1])
    with pytest.raises(SignalContractError) as info:
        validate_signal_zeros(PRICES, signals, 2)
    assert str(info.value) == (
        "signal output violates the contract: exposure must be 0.0 before a symbol's trading row 3 "
        "(warmup_rows is 2); 'A': 2 value(s) non-zero, first at 2024-01-02; "
        "'B': 2 value(s) non-zero, first at 2024-01-04; 'C': 3 value(s) non-zero, first at 2024-01-02"
    )


def test_exposure_from_the_row_after_the_warm_up_is_allowed() -> None:
    signals = values(PRICES, A=[0, 0, 1, 1, 1, 1], B=[0, 0, 0, 0, 1, 1], C=[0, 0, 0, 1, 1, 1])
    validate_signal_zeros(PRICES, signals, 2)


def test_a_symbol_with_at_most_w_trading_rows_must_be_zero_throughout() -> None:
    prices = frame({"A": [10, 11, 12, 13, 14, 15], "B": [NAN, NAN, NAN, NAN, NAN, 20]})  # B has 1 trading row
    ok = values(prices, A=[0, 0, 1, 1, 1, 1], B=[0, 0, 0, 0, 0, 0])
    validate_signal_zeros(prices, ok, 2)
    bad = values(prices, A=[0, 0, 1, 1, 1, 1], B=[0, 0, 0, 0, 0, 1])  # 1.0 on its only trading row
    with pytest.raises(SignalContractError, match=r"'B': 1 value\(s\) non-zero, first at 2024-01-09"):
        validate_signal_zeros(prices, bad, 2)


def test_a_symbol_with_exactly_w_trading_rows_must_be_zero_throughout() -> None:
    # B has trading rows 4 and 5 only; W = 2 means its third trading row never comes, so all 6 rows must be 0.0.
    prices = frame({"A": [10, 11, 12, 13, 14, 15], "B": [NAN, NAN, NAN, NAN, 20, 21]})
    validate_signal_zeros(prices, values(prices, A=[0, 0, 1, 1, 1, 1], B=[0, 0, 0, 0, 0, 0]), 2)
    with pytest.raises(SignalContractError, match=r"'B': 2 value\(s\) non-zero, first at 2024-01-08"):
        validate_signal_zeros(prices, values(prices, A=[0, 0, 1, 1, 1, 1], B=[0, 0, 0, 0, 1, 1]), 2)


def test_a_direct_call_flags_any_non_zero_value_not_only_positive_ones() -> None:
    # Through Signal.generate a value below 0 is already refused by validate_signal_output (the range check runs first),
    # so "!= 0.0" and "> 0.0" cannot be told apart there. Called directly, the function must still flag it.
    prices = frame({"A": [10, 11, 12], "B": [NAN, 20, 21]})
    with pytest.raises(SignalContractError, match=r"'B': 1 value\(s\) non-zero, first at 2024-01-02"):
        validate_signal_zeros(prices, values(prices, A=[1, 1, 1], B=[-0.5, 1, 1]), 0)
    with pytest.raises(SignalContractError, match=r"'B': 1 value\(s\) non-zero, first at 2024-01-02"):
        validate_signal_zeros(prices, values(prices, A=[1, 1, 1], B=[float("nan"), 1, 1]), 0)


def test_a_symbol_that_never_trades_must_be_zero_throughout() -> None:
    prices = frame({"A": [10, 11, 12], "B": [NAN, NAN, NAN]})
    validate_signal_zeros(prices, values(prices, A=[1, 1, 1], B=[0, 0, 0]), 0)
    with pytest.raises(SignalContractError, match=r"'B': 3 value\(s\) non-zero, first at 2024-01-02"):
        validate_signal_zeros(prices, values(prices, A=[1, 1, 1], B=[1, 1, 1]), 0)


def test_generate_applies_the_rule_with_the_warm_up_of_the_params() -> None:
    with pytest.raises(
        SignalContractError, match=r"before a symbol's trading row 1 \(warmup_rows is 0\); 'B': 2 value"
    ):
        signal_with(NoWarmup).generate(PRICES)
    with pytest.raises(
        SignalContractError, match=r"before a symbol's trading row 3 \(warmup_rows is 2\); 'A': 2 value"
    ):
        signal_with(TwoRows).generate(PRICES)


def test_generate_still_reports_the_older_violations_first() -> None:
    def nan_signal(prices: pd.DataFrame, params: SignalParams) -> pd.DataFrame:
        out = always_on(prices, params)
        out.iloc[0, 0] = float("nan")
        return out

    with pytest.raises(SignalContractError, match="NaN") as info:
        signal_with(NoWarmup, nan_signal).generate(PRICES)
    assert "exposure must be 0.0" not in str(info.value)  # the first check raised; the new one runs after it


@pytest.mark.parametrize("signal_id", ["sma_crossover", "momentum_12_1", "buy_and_hold"])
def test_the_built_in_signals_pass_on_a_frame_with_a_late_start_and_a_holiday(signal_id: str) -> None:
    closes = {
        "A": [10 + i for i in range(30)],
        "B": [NAN] * 7 + [20 + i for i in range(23)],
        "C": [30 + i if i != 12 else NAN for i in range(30)],
    }
    params = {
        "sma_crossover": {"fast": 2, "slow": 4},
        "momentum_12_1": {"lookback_days": 5, "skip_days": 1, "top_n": 2},
    }
    get_signal(signal_id).generate(frame(closes), params.get(signal_id))


# --- what the engine did with such a signal before this rule (failing-first test, ADR 0017) ---


def test_the_engine_refuses_a_signal_that_is_on_before_a_symbol_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    # B has no price on Jan 2, 3 and 4. A signal that is 1.0 on B on those rows used to pass Signal.generate and then
    # stopped the engine with "EngineError: ['B'] get an order on 2024-01-03 but have never had a price" (observed
    # before this rule): a contract violation of the signal reported as an engine problem, far from its cause.
    monkeypatch.setitem(SIGNALS._signals, "fixture_always_on", signal_with(NoWarmup))
    prices = frame({"A": [10, 10, 10, 10, 10, 10], "B": [NAN, NAN, NAN, 20, 20, 20]})
    spec = make_spec(
        universe=("A", "B"), start="2024-01-02", end="2024-01-09", signal="fixture_always_on", capital=1000
    )
    with pytest.raises(SignalContractError, match=r"'B': 3 value\(s\) non-zero, first at 2024-01-02"):
        run_backtest(spec, LiteralProvider(prices), apply_costs=False)


def test_a_compliant_always_on_signal_still_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    def on_from_first_row(prices: pd.DataFrame, params: SignalParams) -> pd.DataFrame:
        closes = prices.xs("close", axis=1, level="field")
        out = closes.notna().cummax().astype("float64")  # 1.0 from each symbol's first trading row on
        out.columns = pd.Index(out.columns, name="symbol")
        return out

    monkeypatch.setitem(SIGNALS._signals, "fixture_always_on", signal_with(NoWarmup, on_from_first_row))
    prices = frame({"A": [10, 10, 10, 10, 10, 10], "B": [NAN, NAN, NAN, 20, 20, 20]})
    spec = make_spec(
        universe=("A", "B"), start="2024-01-02", end="2024-01-09", signal="fixture_always_on", capital=1000
    )
    result = run_backtest(spec, LiteralProvider(prices), apply_costs=False)
    assert result.signals["B"].tolist() == [0, 0, 0, 1, 1, 1]
    assert result.signals.index[0].date() == date(2024, 1, 2)
