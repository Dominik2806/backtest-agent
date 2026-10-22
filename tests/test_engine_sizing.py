"""Sizing examples of docs/engine.md ("Sizing examples"): literal signals and literal expected weights."""

import pandas as pd
import pytest

from backtest_agent.engine import target_weights
from backtest_agent.spec.schema import SizingSpec


def weights(method: str, fraction: float | None, signal: list[float]) -> list[float]:
    frame = pd.DataFrame([signal], columns=pd.Index(["A", "B", "C"], name="symbol"))
    return list(target_weights(frame, SizingSpec(method=method, fraction=fraction)).iloc[0])


@pytest.mark.parametrize(
    ("method", "fraction", "signal", "expected"),
    [
        ("equal_weight", None, [1, 0, 0], [1, 0, 0]),
        ("equal_weight", None, [1, 1, 0], [0.5, 0.5, 0]),
        ("equal_weight", None, [1, 1, 1], [1 / 3, 1 / 3, 1 / 3]),
        ("equal_weight", None, [1.0, 0.5, 0], [0.5, 0.25, 0]),
        ("equal_weight", None, [0, 0, 0], [0, 0, 0]),
        ("fixed_fraction", 0.6, [1, 1, 0], [0.5, 0.5, 0]),
        ("fixed_fraction", 0.6, [1, 0, 0], [0.6, 0, 0]),
        ("fixed_fraction", 0.3, [1, 1, 0], [0.3, 0.3, 0]),
        ("fixed_fraction", 0.5, [1, 0.5, 0], [0.5, 0.25, 0]),
        ("fixed_fraction", 0.5, [1, 1, 1], [1 / 3, 1 / 3, 1 / 3]),
    ],
)
def test_sizing_examples(method, fraction, signal, expected) -> None:
    assert weights(method, fraction, signal) == pytest.approx(expected, rel=1e-12, abs=1e-15)


def test_equal_weight_splits_among_the_selected_symbols_only() -> None:
    # momentum_12_1 with positive_only and top_n 3 where only A qualifies: A gets everything, not a third.
    assert weights("equal_weight", None, [1, 0, 0]) == [1.0, 0.0, 0.0]


def test_the_result_has_the_shape_of_the_signals_and_never_exceeds_one() -> None:
    signals = pd.DataFrame(
        [[1.0, 1.0, 1.0], [0.2, 0.0, 0.9], [0.0, 0.0, 0.0]],
        index=pd.bdate_range("2024-01-02", periods=3, name="date"),
        columns=pd.Index(["A", "B", "C"], name="symbol"),
    )
    for sizing in (SizingSpec(method="equal_weight"), SizingSpec(method="fixed_fraction", fraction=1.0)):
        result = target_weights(signals, sizing)
        assert result.index.equals(signals.index)
        assert result.columns.equals(signals.columns)
        assert (result.sum(axis=1) <= 1.0 + 1e-12).all()
        assert (result >= 0).all().all()
