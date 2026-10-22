"""Rebalance schedule and the shift by the execution delay (see docs/engine.md)."""

import numpy as np
import pandas as pd

#: Two target weights closer than this count as unchanged for ``on_signal``.
ON_SIGNAL_TOLERANCE = 1e-12


def decision_bars(index: pd.DatetimeIndex, rebalance: str, targets: pd.DataFrame) -> np.ndarray:
    """Boolean array over the bars of ``index``: True where the rebalance rule says "rebalance".

    ``daily``: every bar. ``weekly`` / ``monthly``: the last bar of each ISO week / calendar month in ``index``; the
    last bar of the whole index never counts, because the frame cannot tell whether the period is over.
    ``on_signal``: the bars where the target weights differ from those of the previous bar (all zero before the
    first bar). The initial decision is not part of this; ``execution_orders`` adds it.
    """
    n = len(index)
    if rebalance == "daily":
        return np.ones(n, dtype=bool)
    if rebalance in ("weekly", "monthly"):
        periods = index.to_period("W" if rebalance == "weekly" else "M")
        return np.concatenate([np.asarray(periods[:-1] != periods[1:], dtype=bool), [False]])
    if rebalance == "on_signal":
        previous = targets.shift(1, fill_value=0.0)
        return (targets - previous).abs().gt(ON_SIGNAL_TOLERANCE).any(axis=1).to_numpy(dtype=bool)
    raise ValueError(f"unknown rebalance rule {rebalance!r}")


def execution_orders(
    targets: pd.DataFrame, decisions: np.ndarray, delay_bars: int, first_pos: int
) -> tuple[pd.DataFrame, pd.Series]:
    """Move the decisions from their decision bar to their execution bar.

    Returns the target weights per execution bar and a boolean Series that is True on the execution bars. The
    decision on bar ``t`` executes on bar ``t + delay_bars``; a decision whose execution bar lies after the last bar
    is dropped, and so is one that would execute before ``first_pos`` (the position of the first bar of the run).
    The bar that executes on ``first_pos`` (bar ``max(first_pos - delay_bars, 0)``) is always a decision bar.
    """
    n = len(targets)
    decisions = np.array(decisions, dtype=bool)
    decisions[max(first_pos - delay_bars, 0)] = True
    executes = np.zeros(n, dtype=bool)
    if delay_bars < n:
        executes[delay_bars:] = decisions[: n - delay_bars]
    executes[:first_pos] = False
    return targets.shift(delay_bars, fill_value=0.0), pd.Series(executes, index=targets.index)
