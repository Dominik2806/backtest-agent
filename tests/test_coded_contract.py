"""The contract check in the package (backtest_agent.coded.contract): signals that break one rule each are caught.

Every bad signal here breaks exactly one rule. The frames are the ones of ``contract_frames(rows=60)``; their holes are
written out by hand below.
"""

import numpy as np
import pandas as pd
import pytest

import signal_contract  # the re-export used by the existing tests
from backtest_agent.coded.contract import (
    FRAME_NAMES,
    check_signal_contract,
    check_warmup_is_honest,
    contract_frames,
)
from backtest_agent.spec import Signal, SignalContractError, SignalParams
from backtest_agent.spec.signals import close_frame, per_symbol_signal

FRAMES = contract_frames(rows=60)


class Plain(SignalParams):
    """warmup_rows is 0."""


class Window(SignalParams):
    window: int = 5

    def warmup_rows(self) -> int:
        return self.window - 1


class Declares(SignalParams):
    declared: int = 0

    def warmup_rows(self) -> int:
        return self.declared


class Dishonest(Window):
    """Needs window - 1 rows of history but declares ``declared`` rows."""

    declared: int = 0

    def warmup_rows(self) -> int:
        return self.declared


def above_mean(prices: pd.DataFrame, params: Window) -> pd.DataFrame:
    def compute(close: pd.Series) -> pd.Series:
        mean = close.rolling(params.window, min_periods=params.window).mean()
        return (close > mean).astype("float64").where(mean.notna())

    return per_symbol_signal(prices, compute)


def run(function, params: SignalParams, frames=FRAMES) -> None:
    check_signal_contract(Signal("fixture", type(params), function), params, frames)


# --- the frames ---


def test_the_four_frames_have_the_documented_shape_and_holes() -> None:
    assert list(FRAMES) == list(FRAME_NAMES) == ["plain", "calendars", "short", "single"]
    assert [len(frame) for frame in FRAMES.values()] == [60, 60, 4, 60]
    assert [list(close_frame(frame).columns) for frame in FRAMES.values()] == [
        ["AAA", "BBB", "CCC"],
        ["AAA", "BBB", "CCC"],
        ["AAA", "BBB", "CCC"],
        ["AAA"],
    ]
    closes = close_frame(FRAMES["calendars"])
    # rows // 30 = 2, rows // 7 = 8, rows // 4 = 15, rows // 2 = 30: BBB's holidays are rows 2, 3, 8, 15, 16, 17, 30
    assert np.flatnonzero(closes["BBB"].isna().to_numpy()).tolist() == [2, 3, 8, 15, 16, 17, 30]
    assert np.flatnonzero(closes["CCC"].isna().to_numpy()).tolist() == [0, 1, 2, 3, 4]  # rows // 12 = 5: starts late
    assert np.flatnonzero(closes["AAA"].isna().to_numpy()).tolist() == [54, 55, 56, 57, 58, 59]  # ends early
    assert not close_frame(FRAMES["plain"]).isna().to_numpy().any()


# --- a good signal passes ---


def test_an_honest_signal_passes_on_every_frame() -> None:
    run(above_mean, Window(window=5))
    run(above_mean, Window(window=2))


def test_the_checks_run_on_every_frame_in_order() -> None:
    seen: list[str] = []

    def recording(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        for name, frame in FRAMES.items():
            if prices is frame and name not in seen:  # the first call on each of the given frames, not a truncated copy
                seen.append(name)
        return per_symbol_signal(prices, lambda close: close * 0.0)

    run(recording, Plain())
    assert seen == ["plain", "calendars", "short", "single"]


# --- one rule each ---


def test_a_function_that_modifies_its_input_is_caught() -> None:
    def mutating(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        prices.iloc[0, 0] = prices.iloc[0, 0] + 1.0
        return per_symbol_signal(prices, lambda close: close * 0.0)

    with pytest.raises(SignalContractError) as info:
        run(mutating, Plain())
    assert str(info.value) == "fixture on the plain frame: the function modified its input frame"


def test_a_function_that_is_not_deterministic_is_caught() -> None:
    calls: list[int] = []

    def drifting(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        calls.append(1)
        value = 0.0 if len(calls) == 1 else 0.5
        return per_symbol_signal(prices, lambda close: close * 0.0 + value)

    with pytest.raises(SignalContractError) as info:
        run(drifting, Plain())
    assert str(info.value) == (
        "fixture on the plain frame: the function is not deterministic (a second call gave another answer)"
    )


@pytest.mark.parametrize(
    ("label", "value", "message"),
    [
        ("NaN", float("nan"), "1 value(s) NaN"),
        ("above 1", 1.5, "outside [0, 1]"),
        ("infinite", float("inf"), "infinite"),
    ],
)
def test_a_value_the_contract_forbids_is_caught(label: str, value: float, message: str) -> None:
    def bad(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        out = per_symbol_signal(prices, lambda close: close * 0.0)
        out.iloc[10, 0] = value
        return out

    with pytest.raises(SignalContractError, match=message.replace("(", r"\(").replace(")", r"\)").replace("[", r"\[")):
        run(bad, Plain())


def test_exposure_before_a_symbols_first_trading_row_is_caught() -> None:
    def always_on(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        return pd.DataFrame(1.0, index=prices.index, columns=close_frame(prices).columns)

    # On the plain frame every symbol trades from row 0; on the calendars frame CCC has no close on rows 0 to 4.
    with pytest.raises(SignalContractError) as info:
        run(always_on, Plain())
    assert str(info.value) == (
        "fixture on the calendars frame: signal output violates the contract: exposure must be 0.0 before a "
        "symbol's trading row 1 (warmup_rows is 0); 'CCC': 5 value(s) non-zero, first at 2024-01-02"
    )


def test_a_warmup_that_is_declared_longer_than_the_zeros_is_caught() -> None:
    def half(prices: pd.DataFrame, params: Declares) -> pd.DataFrame:
        return per_symbol_signal(prices, lambda close: close * 0.0 + 0.5)

    with pytest.raises(
        SignalContractError, match=r"before a symbol's trading row 4 \(warmup_rows is 3\); 'AAA': 3 value"
    ):
        run(half, Declares(declared=3))


def test_a_warmup_that_is_declared_shorter_than_the_history_used_is_caught() -> None:
    with pytest.raises(SignalContractError) as info:
        run(above_mean, Dishonest(window=5, declared=0))  # needs window - 1 = 4 rows of history, the params say 0
    assert str(info.value).startswith("fixture on the plain frame: the value on 20")
    assert str(info.value).endswith(
        " changes when only 0 rows of history are given; the declared warmup_rows is too small, "
        "or the function uses data from after the date"
    )


def test_a_signal_that_is_only_dishonest_when_calendars_differ_is_caught_on_that_frame() -> None:
    def knows_about_holidays(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        has_holiday = float(close_frame(prices).isna().to_numpy().any())  # looks at the whole frame, not at the past
        return per_symbol_signal(prices, lambda close: close * 0.0 + has_holiday)

    signal = Signal("fixture", Plain, knows_about_holidays)
    check_warmup_is_honest(signal, Plain(), FRAMES["plain"])  # no holiday anywhere: nothing to tell
    with pytest.raises(SignalContractError, match="changes when only 0 rows of history"):
        check_signal_contract(signal, Plain(), FRAMES)  # the calendars frame has holidays, and only 'plain' passes


def test_a_function_that_looks_at_the_future_is_caught() -> None:
    def peeking(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        return per_symbol_signal(prices, lambda close: (close.shift(-1) > close).astype("float64"))

    with pytest.raises(SignalContractError, match=r"the value on 20\d\d-\d\d-\d\d changes when only 0 rows of history"):
        run(peeking, Plain())


@pytest.mark.parametrize("declared", [-1, True, 2.0])
def test_a_warmup_that_is_not_an_integer_of_at_least_zero_is_refused(declared) -> None:
    class Odd(SignalParams):
        def warmup_rows(self):
            return declared

    def zeros(prices: pd.DataFrame, params: Odd) -> pd.DataFrame:
        return per_symbol_signal(prices, lambda close: close * 0.0)

    with pytest.raises(
        SignalContractError,
        match=r"warmup_rows must be an integer of at least 0, got " + repr(declared).replace(".", r"\."),
    ):
        run(zeros, Odd())


def test_the_warmup_check_can_be_called_on_one_frame() -> None:
    signal = Signal("fixture", Dishonest, above_mean)
    check_warmup_is_honest(signal, Dishonest(window=3, declared=2), FRAMES["plain"])
    with pytest.raises(SignalContractError, match="changes when only 1 rows of history"):
        check_warmup_is_honest(signal, Dishonest(window=5, declared=1), FRAMES["plain"])


# --- the re-export keeps the AssertionError of the tests of this repository ---


def test_the_test_helper_raises_assertion_error_with_the_same_message() -> None:
    def mutating(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        prices.iloc[0, 0] = prices.iloc[0, 0] + 1.0
        return per_symbol_signal(prices, lambda close: close * 0.0)

    signal = Signal("fixture", Plain, mutating)
    with pytest.raises(AssertionError, match="fixture on the plain frame: the function modified its input frame"):
        signal_contract.check_signal_contract(signal, Plain(), FRAMES)
    assert signal_contract.contract_frames is contract_frames
