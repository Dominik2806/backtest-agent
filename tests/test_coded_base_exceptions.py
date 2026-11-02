"""A coded signal cannot end the process: SystemExit and every other exception become contract errors.

(ADR 0018.) Policy: KeyboardInterrupt and GeneratorExit pass through; every other BaseException that the code of a coded
signal raises is a SignalContractError (or a failed case) with its type and text. In ``Signal.generate`` that holds for
signals that the gate loaded (``sha256`` is set); built-in signals and fixtures behave as they always did.
"""

from datetime import date

import pandas as pd
import pytest

from backtest_agent.coded.cases import Cases, parse_cases, run_cases
from backtest_agent.coded.contract import check_before_run
from backtest_agent.coded.errors import CasesError
from backtest_agent.engine import run_backtest
from backtest_agent.spec import SIGNALS, Signal, SignalContractError, SignalParams
from backtest_agent.spec.signals import per_symbol_signal
from coded_helpers import (
    coded_spec,
    registry_and_modules_are_restored,  # noqa: F401 - autouse fixture
)
from runner_helpers import LiteralProvider, fake_frame

SHA = "ab" * 32
RAISED = [
    (SystemExit(0), "SystemExit: 0"),
    (SystemExit(3), "SystemExit: 3"),
    (KeyError("close"), "KeyError: 'close'"),
]
IDS = ["SystemExit(0)", "SystemExit(3)", "KeyError"]


class Plain(SignalParams):
    """warmup_rows is 0."""


def raising(error: BaseException):
    def function(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        raise error

    return function


def zeros(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
    return per_symbol_signal(prices, lambda close: close * 0.0)


def loaded(function, sha: str | None = SHA, params: type[SignalParams] = Plain) -> Signal:
    """A signal registered the way the gate registers one (with the hash), or a fixture without one."""
    SIGNALS.register("x_signal", params=params)(function)
    return SIGNALS.set_sha256("x_signal", sha) if sha is not None else SIGNALS.get("x_signal")


PRICES = fake_frame(("AAA", "BBB"), date(2024, 1, 2), date(2024, 1, 31))
ONE_CASE = "cases:\n  - name: c\n    prices: {AAA: [1, 2]}\n    expected: {AAA: [0, 1]}\n"


def cases() -> Cases:
    return parse_cases(ONE_CASE.encode(), "x_signal")


# --- Signal.generate ---


@pytest.mark.parametrize(("error", "shown"), RAISED, ids=IDS)
def test_generate_turns_what_a_loaded_signal_raises_into_a_contract_error(error: BaseException, shown: str) -> None:
    signal = loaded(raising(error))
    with pytest.raises(SignalContractError) as info:
        signal.generate(PRICES)
    assert str(info.value) == f"x_signal: the signal raised {shown}"
    assert info.value.__cause__ is error


@pytest.mark.parametrize(("error", "shown"), RAISED, ids=IDS)
def test_a_signal_without_a_hash_is_not_guarded_and_its_errors_propagate_as_they_always_did(
    error: BaseException, shown: str
) -> None:
    signal = loaded(raising(error), sha=None)
    with pytest.raises(type(error)) as info:
        signal.generate(PRICES)
    assert info.value is error


@pytest.mark.parametrize("error", [KeyboardInterrupt(), GeneratorExit()], ids=["KeyboardInterrupt", "GeneratorExit"])
def test_keyboard_interrupt_and_generator_exit_pass_through_even_for_a_loaded_signal(error: BaseException) -> None:
    with pytest.raises(type(error)):
        loaded(raising(error)).generate(PRICES)


def test_a_contract_error_of_the_code_itself_is_not_wrapped_again() -> None:
    own = SignalContractError("its own words")
    with pytest.raises(SignalContractError) as info:
        loaded(raising(own)).generate(PRICES)
    assert info.value is own


def test_a_warmup_rows_that_raises_is_guarded_too() -> None:
    class Odd(SignalParams):
        def warmup_rows(self) -> int:
            raise SystemExit(5)

    with pytest.raises(SignalContractError) as info:
        loaded(zeros, params=Odd).generate(PRICES)
    assert str(info.value) == "x_signal: the signal raised SystemExit: 5"


def test_the_guard_does_not_change_a_signal_that_works() -> None:
    plain = loaded(zeros, sha=None).generate(PRICES)
    SIGNALS.unregister("x_signal")
    marked = loaded(zeros).generate(PRICES)
    assert marked.equals(plain)


# --- check_before_run ---


@pytest.mark.parametrize(("error", "shown"), RAISED, ids=IDS)
@pytest.mark.parametrize("sha", [SHA, None], ids=["loaded", "fixture"])
def test_the_check_before_a_run_reports_it_as_a_contract_error_on_the_first_frame(
    error: BaseException, shown: str, sha: str | None
) -> None:
    signal = loaded(raising(error), sha)
    with pytest.raises(SignalContractError) as info:
        check_before_run(signal, Plain())
    assert str(info.value) == f"x_signal on the plain frame: {shown}"
    assert info.value.__cause__ is error


def test_a_call_with_less_history_that_exits_is_caught_in_the_honesty_check() -> None:
    def exits_on_short_frames(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        if len(prices) < 5:
            raise SystemExit(1)
        return zeros(prices, params)

    with pytest.raises(SignalContractError) as info:
        check_before_run(loaded(exits_on_short_frames), Plain())
    assert str(info.value) == "x_signal on the plain frame: SystemExit: 1"


def test_an_exit_in_the_second_call_of_a_frame_is_caught_by_the_guard_of_generate() -> None:
    calls: list[int] = []

    def exits_the_second_time(prices: pd.DataFrame, params: Plain) -> pd.DataFrame:
        calls.append(1)
        if len(calls) == 2:
            raise SystemExit(2)
        return zeros(prices, params)

    with pytest.raises(SignalContractError) as info:
        check_before_run(loaded(exits_the_second_time), Plain())
    assert str(info.value) == "x_signal on the plain frame: x_signal: the signal raised SystemExit: 2"


# --- run_cases ---


@pytest.mark.parametrize(("error", "shown"), RAISED, ids=IDS)
def test_a_case_in_which_a_loaded_signal_raises_fails_with_the_guarded_message(
    error: BaseException, shown: str
) -> None:
    with pytest.raises(CasesError) as info:
        run_cases(loaded(raising(error)), cases())
    assert str(info.value) == (
        f"1 difference in the examples:\n  - x_signal on the case 'c': SignalContractError: "
        f"x_signal: the signal raised {shown}"
    )


@pytest.mark.parametrize("error", [KeyboardInterrupt(), GeneratorExit()], ids=["KeyboardInterrupt", "GeneratorExit"])
def test_keyboard_interrupt_and_generator_exit_pass_through_the_cases_too(error: BaseException) -> None:
    with pytest.raises(type(error)):
        run_cases(loaded(raising(error), sha=None), cases())


@pytest.mark.parametrize(("error", "shown"), RAISED, ids=IDS)
def test_a_case_in_which_a_fixture_raises_fails_with_the_type_and_text(error: BaseException, shown: str) -> None:
    with pytest.raises(CasesError) as info:
        run_cases(loaded(raising(error), sha=None), cases())
    assert str(info.value) == f"1 difference in the examples:\n  - x_signal on the case 'c': {shown}"


def test_params_of_the_cases_that_make_a_validator_exit_are_a_cases_error() -> None:
    class Exits(SignalParams):
        value: int = 0

        @classmethod
        def model_validate(cls, *args, **kwargs):
            raise SystemExit(4)

    text = "params: {value: 1}\n" + ONE_CASE
    with pytest.raises(CasesError) as info:
        run_cases(loaded(zeros, params=Exits), parse_cases(text.encode(), "x_signal"))
    assert str(info.value) == "x_signal: the params of the cases are not valid for the signal (4)"


# --- run_backtest ---


@pytest.mark.parametrize(("error", "shown"), RAISED, ids=IDS)
def test_a_run_with_a_signal_that_exits_raises_a_contract_error_and_leaves_the_data_alone(
    error: BaseException, shown: str
) -> None:
    frame = fake_frame(("AAA", "BBB"), date(2023, 10, 1), date(2024, 5, 1))
    provider = LiteralProvider(frame)
    before = frame.copy(deep=True)
    loaded(raising(error))
    with pytest.raises(SignalContractError) as info:
        run_backtest(coded_spec(pin=SHA), provider)  # the process must not exit here
    assert str(info.value) == f"x_signal: the signal raised {shown}"
    assert provider.frame.equals(before) and len(provider.calls) == 1
    assert SIGNALS.get("x_signal").sha256 == SHA  # run_backtest does not touch the registry
