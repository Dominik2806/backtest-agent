"""Every registered signal must pass the reusable contract, with its defaults and with small-window variants."""

import pytest

from backtest_agent.spec import get_signal, list_signals
from signal_contract import check_signal_contract, contract_frames

# Extra params per signal id, in addition to the defaults, so that warm-ups are exercised on the short test frames.
EXTRA_PARAMS: dict[str, list[dict]] = {
    "sma_crossover": [{"fast": 2, "slow": 5}, {"fast": 5, "slow": 30}],
    "momentum_12_1": [
        {"lookback_days": 20, "skip_days": 3, "top_n": 1},
        {"lookback_days": 10, "skip_days": 0, "top_n": 2, "positive_only": True},
    ],
}
CASES = [
    pytest.param(signal_id, params, id=f"{signal_id}-{'default' if not params else index}")
    for signal_id in list_signals()
    for index, params in enumerate([{}, *EXTRA_PARAMS.get(signal_id, [])])
]
FRAMES = contract_frames(rows=300)


@pytest.mark.parametrize(("signal_id", "params"), CASES)
def test_registered_signal_passes_the_contract(signal_id: str, params: dict) -> None:
    signal = get_signal(signal_id)
    check_signal_contract(signal, signal.parse_params(params), FRAMES)


def test_every_registered_signal_is_covered_and_declares_a_warmup() -> None:
    assert {case.values[0] for case in CASES} == set(list_signals())
    for signal_id in list_signals():
        warmup = get_signal(signal_id).warmup_rows()
        assert isinstance(warmup, int) and warmup >= 0
