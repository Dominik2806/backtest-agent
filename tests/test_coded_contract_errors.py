"""Every failure of the contract check is a SignalContractError that names the signal and the frame (coded/contract.py).

Code written by an agent can fail in any way: it can raise, return the wrong thing, or break a rule of the contract.
The frames are those of ``contract_frames(rows=60)``: row 10 is Tuesday 2024-01-16 (row 0 is Tuesday 2024-01-02).
"""

import pandas as pd
import pytest

from backtest_agent.coded.contract import (
    PRE_RUN_ROWS,
    check_before_run,
    check_signal_contract,
    check_warmup_is_honest,
    contract_frames,
)
from backtest_agent.spec import Signal, SignalContractError, SignalParams
from backtest_agent.spec.signals import close_frame, per_symbol_signal

FRAMES = contract_frames(rows=60)


class Plain(SignalParams):
    """warmup_rows is 0."""


def zeros(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
    return per_symbol_signal(prices, lambda close: close * 0.0)


def run(function, frames=FRAMES) -> None:
    check_signal_contract(Signal("fixture", Plain, function), Plain(), frames)


def message(function, frames=FRAMES) -> str:
    with pytest.raises(SignalContractError) as info:
        run(function, frames)
    return str(info.value)


# --- anything the function raises ---


def test_an_exception_of_the_function_is_a_contract_error_with_the_frame_and_the_type() -> None:
    def boom(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        raise RuntimeError("boom")

    with pytest.raises(SignalContractError) as info:
        run(boom)
    assert str(info.value) == "fixture on the plain frame: RuntimeError: boom"
    assert isinstance(info.value.__cause__, RuntimeError)


@pytest.mark.parametrize(
    ("error", "shown"),
    [
        (KeyError("close"), "KeyError: 'close'"),
        (ZeroDivisionError("division by zero"), "ZeroDivisionError: division by zero"),
        (ValueError("bad"), "ValueError: bad"),
        (IndexError("out of range"), "IndexError: out of range"),
        (AssertionError("no"), "AssertionError: no"),
        (SignalContractError("own"), "own"),  # a contract error of the function itself is not wrapped twice by type
    ],
)
def test_any_kind_of_exception_is_reported_with_its_type(error: Exception, shown: str) -> None:
    def raising(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        raise error

    assert message(raising) == f"fixture on the plain frame: {shown}"


def test_an_exception_that_only_a_later_frame_provokes_names_that_frame() -> None:
    def fails_on_holes(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        if close_frame(prices).isna().to_numpy().any():
            raise ValueError("holes in the data")
        return zeros(prices, params)

    assert message(fails_on_holes) == "fixture on the calendars frame: ValueError: holes in the data"


def test_an_exception_in_a_call_with_less_history_names_the_frame_of_the_honesty_check() -> None:
    def fails_on_short_history(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        if len(prices) < 5:
            raise ValueError("needs 5 rows")
        return zeros(prices, params)

    # The full frames are fine; the check calls the function with only the history it declares (0 rows before the date).
    assert message(fails_on_short_history, {"plain": FRAMES["plain"]}) == (
        "fixture on the plain frame: ValueError: needs 5 rows"
    )


def test_baseexceptions_that_are_not_errors_are_not_swallowed() -> None:
    def interrupted(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(interrupted)


# --- the errors of Signal.generate carry the frame too ---


def test_a_value_the_contract_forbids_names_the_frame() -> None:
    def with_nan(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        out = zeros(prices, params)
        out.iloc[10, 0] = float("nan")
        return out

    assert message(with_nan) == (
        "fixture on the plain frame: signal output violates the contract: 1 value(s) NaN; first at 2024-01-16 in 'AAA'"
    )


def test_an_output_that_is_not_a_frame_names_the_frame() -> None:
    assert (
        message(lambda prices, params: None)
        == "fixture on the plain frame: signal output must be a DataFrame, got NoneType"
    )


def test_a_frame_with_fewer_columns_when_given_less_history_is_a_contract_error() -> None:
    def shrinks(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        out = zeros(prices, params)
        return out.iloc[:, :1] if len(prices) < 5 else out

    assert message(shrinks, {"plain": FRAMES["plain"]}) == (
        "fixture on the plain frame: the function does not return a frame with one column per symbol when it is given "
        "only 0 rows of history before 2024-01-02"
    )


# --- the honesty check on its own ---


def test_the_honesty_check_names_the_signal_and_the_frame_if_it_is_given_one() -> None:
    def peeking(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        return per_symbol_signal(prices, lambda close: (close.shift(-1) > close).astype("float64"))

    signal = Signal("fixture", Plain, peeking)
    with pytest.raises(SignalContractError, match=r"^fixture: the value on 20\d\d-\d\d-\d\d changes when only 0 rows"):
        check_warmup_is_honest(signal, Plain(), FRAMES["plain"])
    with pytest.raises(SignalContractError, match=r"^fixture on the calendars frame: the value on 20\d\d"):
        check_warmup_is_honest(signal, Plain(), FRAMES["calendars"], frame="calendars")


@pytest.mark.parametrize(
    ("error", "shown"),
    [(OSError("disk"), "OSError: disk"), (SystemExit(3), "SystemExit: 3")],
    ids=["OSError", "SystemExit"],
)
def test_an_exception_in_the_honesty_check_alone_is_wrapped_too(error: BaseException, shown: str) -> None:
    def boom(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        raise error

    signal = Signal("fixture", Plain, boom)
    with pytest.raises(SignalContractError) as info:
        check_warmup_is_honest(signal, Plain(), FRAMES["plain"])
    assert str(info.value) == f"fixture: {shown}"


def test_keyboard_interrupt_passes_through_the_honesty_check_alone() -> None:
    def interrupted(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        check_warmup_is_honest(Signal("fixture", Plain, interrupted), Plain(), FRAMES["plain"])


# --- the check before a run ---


def test_the_check_before_a_run_uses_frames_of_120_rows_and_all_the_checks() -> None:
    assert PRE_RUN_ROWS == 120
    lengths: set[int] = set()

    def recording(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        lengths.add(len(prices))
        return zeros(prices, params)

    check_before_run(Signal("fixture", Plain, recording), Plain())
    assert 120 in lengths and 4 in lengths and 300 not in lengths  # plain, calendars and single: 120 rows; short: 4


def test_the_check_before_a_run_refuses_what_the_full_check_refuses() -> None:
    def mutating(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        prices.iloc[0, 0] = prices.iloc[0, 0] + 1.0
        return zeros(prices, params)

    with pytest.raises(SignalContractError) as info:
        check_before_run(Signal("fixture", Plain, mutating), Plain())
    assert str(info.value) == "fixture on the plain frame: the function modified its input frame"


def test_the_check_before_a_run_is_the_same_on_every_call() -> None:
    def peeking(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        return per_symbol_signal(prices, lambda close: (close.shift(-1) > close).astype("float64"))

    messages = set()
    for _ in range(3):
        with pytest.raises(SignalContractError) as info:
            check_before_run(Signal("fixture", Plain, peeking), Plain())
        messages.add(str(info.value))
    assert len(messages) == 1  # nothing in the check depends on time or chance
