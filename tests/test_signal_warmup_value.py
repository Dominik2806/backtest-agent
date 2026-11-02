"""``warmup_rows()`` must return a Python int of at least 0 (docs/strategy-spec.md, "Warm-up").

The check is in ``validate_signal_zeros``, which ``Signal.generate`` calls on every run. NumPy integers are refused
too: they are not ``int``, and a value that prints like an integer but is not one is a surprise the contract avoids.
"""

import numpy as np
import pandas as pd
import pytest

from backtest_agent.spec import Signal, SignalContractError, SignalParams
from backtest_agent.spec.signals import per_symbol_signal, validate_signal_zeros
from runner_helpers import price_frame

PRICES = price_frame({"A": [10, 11, 12]}, {"A": [10, 11, 12]})
ZEROS = pd.DataFrame(0.0, index=PRICES.index, columns=pd.Index(["A"], name="symbol"))
PREFIX = "signal output violates the contract: warmup_rows must be an integer of at least 0, got "


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        (-1, "-1"),
        (True, "True"),
        (False, "False"),
        (1.5, "1.5"),
        (2.0, "2.0"),
        ("3", "'3'"),
        (None, "None"),
        (np.int64(2), "np.int64(2)"),
        (np.int32(0), "np.int32(0)"),
    ],
)
def test_a_warmup_that_is_not_a_python_int_of_at_least_zero_is_refused_with_this_message(value, shown) -> None:
    with pytest.raises(SignalContractError) as info:
        validate_signal_zeros(PRICES, ZEROS, value)
    assert str(info.value) == PREFIX + shown


@pytest.mark.parametrize("value", [0, 1, 2, 3, 100])
def test_a_python_int_of_at_least_zero_is_accepted(value: int) -> None:
    validate_signal_zeros(PRICES, ZEROS, value)  # an all-zero signal obeys every warm-up


def test_generate_refuses_a_numpy_integer_declared_by_the_params() -> None:
    class Numpy(SignalParams):
        def warmup_rows(self):
            return np.int64(1)

    signal = Signal("fixture", Numpy, lambda prices, params: per_symbol_signal(prices, lambda close: close * 0.0))
    with pytest.raises(SignalContractError) as info:
        signal.generate(PRICES)
    assert str(info.value) == PREFIX + "np.int64(1)"
