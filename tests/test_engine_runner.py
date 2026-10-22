"""run_backtest: window, warm-up, validation, hash, flags and the edge cases of the data (see docs/engine.md)."""

import dataclasses
import warnings
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from backtest_agent.data import DataUnavailableError, DataValidationError, FakeProvider, hash_frame
from backtest_agent.engine import (
    BacktestResult,
    InsufficientHistoryError,
    InsufficientWarmupWarning,
    run_backtest,
)
from backtest_agent.spec import get_signal
from runner_helpers import LiteralProvider, fake_frame, make_spec, nan_rows, price_frame, register_up_day

SYMBOLS = ("AAA", "BBB")
START, END = date(2024, 3, 1), date(2024, 4, 30)  # a Friday and a Tuesday
WARMUP_ROWS = 19  # sma_crossover with slow = 20


def fake_provider(**kwargs) -> FakeProvider:
    return FakeProvider(symbols=SYMBOLS, **kwargs)


def test_results_start_on_the_first_bar_on_or_after_period_start_and_end_on_period_end() -> None:
    spec = make_spec(start="2024-03-02", end="2024-04-26")  # Saturday to Friday
    result = run_backtest(spec, fake_provider())
    assert isinstance(result, BacktestResult)
    assert result.equity.index[0] == pd.Timestamp("2024-03-04")
    assert result.equity.index[-1] == pd.Timestamp("2024-04-26")
    assert result.warmup.first_bar == date(2024, 3, 4)


def test_a_period_end_on_a_weekend_ends_on_the_last_bar_before_it() -> None:
    result = run_backtest(make_spec(end="2024-04-28"), fake_provider())  # a Sunday
    assert result.equity.index[-1] == pd.Timestamp("2024-04-26")


def test_every_frame_of_the_result_is_trimmed_to_the_same_bars() -> None:
    result = run_backtest(make_spec(), fake_provider())
    index = result.equity.index
    assert index[0] >= pd.Timestamp(START)
    for frame in (result.cash, result.positions, result.weights, result.turnover, result.signals):
        assert frame.index.equals(index)
    assert result.target_weights.index.equals(index)
    assert list(result.signals.columns) == list(SYMBOLS) == list(result.target_weights.columns)
    assert result.trades["date"].min() >= index[0]


def test_the_fetch_window_is_period_start_minus_two_n_plus_14_days() -> None:
    provider = fake_provider()
    result = run_backtest(make_spec(), provider)
    rows_needed = WARMUP_ROWS + 1  # warmup_rows + delay_bars
    expected_start = START - timedelta(days=2 * rows_needed + 14)
    assert provider.calls == [(SYMBOLS, expected_start, END)]
    warmup = result.warmup
    assert (warmup.required_rows, warmup.delay_bars, warmup.rows_needed) == (WARMUP_ROWS, 1, rows_needed)
    assert (warmup.buffer_days, warmup.fetch_start) == (54, expected_start)


def test_signals_on_the_first_bar_equal_those_of_a_much_longer_independent_fetch() -> None:
    spec = make_spec()
    result = run_backtest(spec, fake_provider())
    long_history = fake_frame(SYMBOLS, date(2015, 1, 1), END)  # years more than the run loaded
    reference = get_signal("sma_crossover").generate(long_history, spec.signal.params)
    pd.testing.assert_frame_equal(result.signals, reference.loc[result.equity.index[0] :], check_freq=False)
    assert result.signals.to_numpy().any(), "a test world without any signal proves nothing"
    # Control: without the warm-up the signal would be 0 on the first bars, so the warm-up does the work.
    cold = get_signal("sma_crossover").generate(fake_frame(SYMBOLS, START, END), spec.signal.params)
    assert not cold.iloc[:WARMUP_ROWS].to_numpy().any()
    assert result.signals.iloc[0].equals(reference.loc[result.equity.index[0]])


def test_initial_target_weights_and_first_decision_date() -> None:
    spec = make_spec()
    result = run_backtest(spec, fake_provider())
    reference = get_signal("sma_crossover").generate(fake_frame(SYMBOLS, date(2015, 1, 1), END), spec.signal.params)
    decision = pd.Timestamp(result.warmup.first_decision_date)
    assert decision < result.equity.index[0]  # delay 1: the decision is made on the bar before the first bar
    assert result.equity.index[result.equity.index.searchsorted(decision)] > decision
    chosen = reference.loc[decision]
    selected = (chosen > 0).sum()
    expected = {s: (float(chosen[s]) / selected if selected else 0.0) for s in SYMBOLS}
    assert result.warmup.initial_target_weights == expected


def test_first_decision_date_is_the_first_bar_with_delay_zero_or_without_earlier_history() -> None:
    same_bar = run_backtest(make_spec(delay=0, price="close"), fake_provider())
    assert same_bar.warmup.first_decision_date == same_bar.warmup.first_bar

    frame = fake_frame(SYMBOLS, START, END)  # history starts exactly on period.start
    spec = make_spec(signal="buy_and_hold")
    result = run_backtest(spec, LiteralProvider(frame))
    assert result.warmup.first_decision_date == result.warmup.first_bar == START
    assert result.warmup.initial_target_weights == {"AAA": 0.5, "BBB": 0.5}


def test_a_run_with_enough_history_raises_no_warning_and_has_no_warmup_flag() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = run_backtest(make_spec(), fake_provider(), allow_short_warmup=False)
    assert result.warmup.sufficient
    assert result.warmup.short_symbols == ()
    assert all(count >= WARMUP_ROWS for count in result.warmup.rows_before.values())
    assert "insufficient_warmup" not in [flag.code for flag in result.risk_flags]


@pytest.fixture
def short_history() -> LiteralProvider:
    """Prices that start only 6 bars before period.start, far less than the 19 rows the signal needs."""
    return LiteralProvider(fake_frame(SYMBOLS, date(2024, 2, 22), END))


def test_too_little_history_is_reported_by_flag_warning_and_warmup_info(short_history: LiteralProvider) -> None:
    with pytest.warns(InsufficientWarmupWarning, match="fewer than 19 rows"):
        result = run_backtest(make_spec(), short_history)
    assert not result.warmup.sufficient
    assert result.warmup.short_symbols == SYMBOLS
    assert result.warmup.rows_before == {"AAA": 5, "BBB": 5}  # Feb 22, 23, 26, 27, 28 before the decision on Feb 29
    assert result.warmup.first_decision_date == date(2024, 2, 29)
    assert [flag.code for flag in result.risk_flags][-1] == "insufficient_warmup"
    assert result.equity.index[0] == pd.Timestamp(START)  # the run still happened


def test_too_little_history_raises_with_allow_short_warmup_false(short_history: LiteralProvider) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # raising replaces the warning
        with pytest.raises(InsufficientHistoryError, match="fewer than 19 rows") as raised:
            run_backtest(make_spec(), short_history, allow_short_warmup=False)
    assert raised.value.warmup.short_symbols == SYMBOLS


def test_only_the_symbol_with_too_little_history_is_short() -> None:
    frame = nan_rows(fake_frame(SYMBOLS, date(2024, 1, 2), END), "BBB", before="2024-02-26")
    with pytest.warns(InsufficientWarmupWarning):
        result = run_backtest(make_spec(), LiteralProvider(frame))
    assert result.warmup.short_symbols == ("BBB",)
    assert result.warmup.rows_before["AAA"] > WARMUP_ROWS > result.warmup.rows_before["BBB"]
    assert result.warmup.first_data == {"AAA": date(2024, 1, 8), "BBB": date(2024, 2, 26)}  # the fetch starts Jan 7


def test_a_validation_error_stops_the_run() -> None:
    frame = fake_frame(SYMBOLS, date(2024, 1, 2), END)
    frame.loc[pd.Timestamp("2024-02-14"), ("AAA", "close")] = -1.0
    with pytest.raises(DataValidationError, match="non_positive_price") as raised:
        run_backtest(make_spec(), LiteralProvider(frame))
    assert raised.value.result.has_errors


def test_validation_warnings_go_into_the_result() -> None:
    frame = fake_frame(SYMBOLS, date(2024, 1, 2), END)
    frame = nan_rows(frame, "AAA", between=("2024-03-11", "2024-03-22"))  # two missing weeks: a calendar gap
    result = run_backtest(make_spec(signal="buy_and_hold"), LiteralProvider(frame))
    assert "calendar_gap" in {issue.code for issue in result.validation.warnings}
    assert not result.validation.has_errors


def test_the_data_hash_is_the_hash_of_the_frame_the_provider_delivered_warm_up_included() -> None:
    provider = LiteralProvider(fake_frame(SYMBOLS, date(2024, 1, 2), END))
    result = run_backtest(make_spec(), provider)
    assert result.data_hash == hash_frame(provider.last_frame)
    assert provider.last_frame.index[0] < pd.Timestamp(START)  # the warm-up is part of the hashed data
    assert len(result.data_hash) == 64


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, ["costs_not_applied"]),
        ({"costs": (0.0, 0.0, 0.0)}, ["zero_costs"]),
        ({"costs": (0.0, 0.0, 0.5)}, ["costs_not_applied"]),
        ({"delay": 0, "price": "close"}, ["same_bar_execution", "costs_not_applied"]),
        ({"delay": 0, "price": "close", "costs": (0.0, 0.0, 0.0)}, ["same_bar_execution", "zero_costs"]),
    ],
)
def test_risk_flags(kwargs: dict, expected: list[str]) -> None:
    result = run_backtest(make_spec(**kwargs), fake_provider())
    assert [flag.code for flag in result.risk_flags] == expected
    assert result.costs_applied is False


def test_the_insufficient_warmup_flag_comes_last(short_history: LiteralProvider) -> None:
    spec = make_spec(delay=0, price="close", costs=(0.0, 0.0, 0.0))
    with pytest.warns(InsufficientWarmupWarning):
        result = run_backtest(spec, short_history)
    assert [flag.code for flag in result.risk_flags] == ["same_bar_execution", "zero_costs", "insufficient_warmup"]
    with pytest.warns(InsufficientWarmupWarning):
        costly = run_backtest(make_spec(), short_history)
    assert [flag.code for flag in costly.risk_flags] == ["costs_not_applied", "insufficient_warmup"]


def test_returns_use_the_initial_equity_for_the_first_bar() -> None:
    result = run_backtest(make_spec(capital=50000), fake_provider())
    assert result.initial_equity == 50000.0
    assert result.returns.iloc[0] == result.equity.iloc[0] / 50000.0 - 1.0
    np.testing.assert_allclose(result.returns.iloc[1:], result.equity.pct_change().iloc[1:], rtol=1e-12)


def test_the_result_is_frozen() -> None:
    result = run_backtest(make_spec(), fake_provider())
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.costs_applied = True  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.warmup.sufficient = False  # type: ignore[misc]


# --- the data does not match the period -------------------------------------------------------------------------


def test_a_symbol_that_starts_after_period_start_is_not_an_error() -> None:
    frame = nan_rows(fake_frame(SYMBOLS, date(2024, 1, 2), END), "BBB", before="2024-03-12")
    result = run_backtest(make_spec(signal="buy_and_hold"), LiteralProvider(frame))
    assert result.warmup.first_data["BBB"] == date(2024, 3, 12)
    assert result.warmup.sufficient  # buy_and_hold needs no history
    assert (result.signals.loc[:"2024-03-11", "BBB"] == 0.0).all()
    assert (result.signals.loc["2024-03-12":, "BBB"] == 1.0).all()
    assert result.trades.loc[result.trades["symbol"] == "BBB", "date"].min() >= pd.Timestamp("2024-03-12")
    assert "starts_late" in {i.code for i in result.validation.infos if i.symbol == "BBB"}


def test_all_data_starting_after_period_start_starts_the_run_on_the_first_available_bar() -> None:
    provider = LiteralProvider(fake_frame(SYMBOLS, date(2024, 3, 20), END))
    result = run_backtest(make_spec(signal="buy_and_hold"), provider)
    assert result.equity.index[0] == pd.Timestamp("2024-03-20")
    assert result.warmup.rows_before == {"AAA": 0, "BBB": 0}
    assert result.warmup.sufficient
    with pytest.warns(InsufficientWarmupWarning):
        short = run_backtest(make_spec(), provider)
    assert not short.warmup.sufficient


def test_data_that_ends_before_period_start_raises_data_unavailable() -> None:
    provider = LiteralProvider(fake_frame(SYMBOLS, date(2024, 1, 2), date(2024, 2, 28)))
    with pytest.raises(DataUnavailableError, match=r"no bar on or after period.start 2024-03-01.*2024-02-28"):
        run_backtest(make_spec(), provider)


def test_a_period_end_beyond_the_last_available_date_ends_the_result_there() -> None:
    provider = LiteralProvider(fake_frame(SYMBOLS, date(2024, 1, 2), date(2024, 4, 10)))
    result = run_backtest(make_spec(), provider)
    assert result.equity.index[-1] == pd.Timestamp("2024-04-10")
    assert "ends_early" in {issue.code for issue in result.validation.infos}


def test_a_provider_that_returns_fewer_symbols_than_requested_raises_data_unavailable() -> None:
    provider = LiteralProvider(fake_frame(("AAA",), date(2024, 1, 2), END), strict=False)
    with pytest.raises(DataUnavailableError, match="BBB"):
        run_backtest(make_spec(), provider)


def test_a_provider_that_returns_symbols_in_another_order_raises_value_error() -> None:
    frame = fake_frame(("BBB", "AAA"), date(2024, 1, 2), END)
    with pytest.raises(ValueError, match="in this order"):
        run_backtest(make_spec(), LiteralProvider(frame, strict=False))


def test_a_provider_that_returns_rows_after_period_end_raises_value_error() -> None:
    provider = LiteralProvider(fake_frame(SYMBOLS, date(2024, 1, 2), date(2024, 5, 31)), clip_end=False)
    with pytest.raises(ValueError, match="after period.end"):
        run_backtest(make_spec(), provider)


def test_an_unknown_symbol_error_of_the_provider_propagates() -> None:
    with pytest.raises(DataUnavailableError, match="unknown symbols"):
        run_backtest(make_spec(universe=("AAA", "ZZZ")), fake_provider())


def test_the_benchmark_is_not_loaded() -> None:
    provider = FakeProvider(symbols=("AAA", "BBB", "SPY"))
    result = run_backtest(make_spec(), provider)  # benchmark is the first universe symbol in make_spec
    assert [symbols for symbols, _, _ in provider.calls] == [SYMBOLS]
    assert list(result.positions.columns) == list(SYMBOLS)


# --- fixture H14 of docs/engine.md: expected values are the literals written out there -------------------------

NAN = float("nan")
H14_OPENS = {
    "A": [100, 100, 105, 115, 125, 130, 130, 120, 130, 144],
    "B": [50, 55, 60, 55, 50, 50, 60, NAN, 55, 80],
}
H14_CLOSES = {
    "A": [100, 100, 110, 120, 130, 130, 120, 120, 140, 150],
    "B": [50, 60, 60, 50, 50, 50, 65, NAN, 60, 75],
}
H14_DATES = [date(2024, 1, d) for d in (8, 9, 10, 11, 12, 15)]


@pytest.fixture
def fixture_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    register_up_day(monkeypatch)


def h14_spec():
    return make_spec(
        universe=("A", "B"),
        start="2024-01-06",
        end="2024-01-15",
        signal="fixture_up_day",
        costs=(1.0, 2.0, 2.0),
        capital=1000,
    )


def test_h14_a_whole_run_with_warm_up_a_decision_before_the_first_bar_and_a_holiday(fixture_signal: None) -> None:
    provider = LiteralProvider(price_frame(H14_OPENS, H14_CLOSES))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = run_backtest(h14_spec(), provider)

    assert provider.calls == [(("A", "B"), date(2023, 12, 19), date(2024, 1, 15))]
    assert result.data_hash == hash_frame(provider.last_frame)
    assert not result.validation.has_errors
    assert result.validation.warnings == ()

    def dates(index: pd.Index) -> list[date]:
        return [ts.date() for ts in index]

    for frame in (result.equity, result.cash, result.positions, result.weights, result.turnover):
        assert dates(frame.index) == H14_DATES
    assert dates(result.signals.index) == dates(result.target_weights.index) == H14_DATES
    assert result.initial_equity == 1000.0

    np.testing.assert_allclose(result.equity, [1040, 1040, 1040, 1040, 1120, 1500], rtol=1e-12)
    np.testing.assert_allclose(result.cash, [0, 0, 1040, 1040, 160, 0], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(result.positions["A"], [8, 8, 0, 0, 0, 10], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(result.positions["B"], [0, 0, 0, 0, 16, 0], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(result.weights["A"], [1, 1, 0, 0, 0, 1], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(result.weights["B"], [0, 0, 0, 0, 6 / 7, 0], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(result.turnover, [1.0, 0, 1.0, 0, 11 / 13, 17 / 9], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(result.returns, [0.04, 0, 0, 0, 1 / 13, 19 / 56], rtol=1e-12, atol=1e-12)

    assert result.signals["A"].tolist() == [1, 0, 0, 0, 1, 1]
    assert result.signals["B"].tolist() == [0, 0, 1, 1, 0, 1]
    assert result.target_weights["A"].tolist() == [1, 0, 0, 0, 1, 0.5]
    assert result.target_weights["B"].tolist() == [0, 0, 1, 1, 0, 0.5]

    trades = result.trades
    assert dates(pd.DatetimeIndex(trades["date"])) == [date(2024, 1, d) for d in (8, 10, 12, 15, 15)]
    assert trades["symbol"].tolist() == ["A", "A", "B", "A", "B"]
    assert trades["shares"].tolist() == [8, -8, 16, 10, -16]
    assert trades["price"].tolist() == [125, 130, 55, 144, 80]
    assert trades["notional"].tolist() == [1000, -1040, 880, 1440, -1280]
    assert (result.deferred_orders, result.unfilled_orders) == (1, 0)

    warmup = result.warmup
    assert warmup.first_bar == date(2024, 1, 8)
    assert warmup.first_decision_date == date(2024, 1, 5)
    assert warmup.initial_target_weights == {"A": 1.0, "B": 0.0}
    assert warmup.rows_before == {"A": 3, "B": 3}
    assert warmup.first_data == {"A": date(2024, 1, 2), "B": date(2024, 1, 2)}
    assert (warmup.required_rows, warmup.delay_bars, warmup.rows_needed, warmup.buffer_days) == (1, 1, 2, 18)
    assert warmup.fetch_start == date(2023, 12, 19)
    assert warmup.short_symbols == ()
    assert warmup.sufficient

    assert [flag.code for flag in result.risk_flags] == ["costs_not_applied"]
    assert result.costs_applied is False


def test_h14_without_the_warm_up_rows_the_first_decision_is_cash_and_the_run_says_so(fixture_signal: None) -> None:
    frame = price_frame(H14_OPENS, H14_CLOSES).loc["2024-01-08":]
    with pytest.warns(InsufficientWarmupWarning):
        result = run_backtest(h14_spec(), LiteralProvider(frame))
    warmup = result.warmup
    assert not warmup.sufficient
    assert warmup.rows_before == {"A": 0, "B": 0}
    assert warmup.short_symbols == ("A", "B")
    assert warmup.first_decision_date == warmup.first_bar == date(2024, 1, 8)
    assert warmup.initial_target_weights == {"A": 0.0, "B": 0.0}  # no previous close: the signal is 0 on bar 0
    assert result.equity.iloc[0] == 1000.0  # delay 1: nothing is bought on the first bar
    assert [flag.code for flag in result.risk_flags] == ["costs_not_applied", "insufficient_warmup"]
