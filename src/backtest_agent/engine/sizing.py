"""Sizing: signal values (desired exposure) to target weights (see docs/engine.md)."""

import pandas as pd

from backtest_agent.spec.schema import SizingSpec


def target_weights(signals: pd.DataFrame, sizing: SizingSpec) -> pd.DataFrame:
    """Turn a signal frame (values in [0, 1]) into target weights with the sizing rule of the spec.

    ``equal_weight``: ``signal / n`` for the ``n`` symbols with a signal above 0, so capital is split among the
    selected symbols only. ``fixed_fraction``: ``signal * fraction``, all divided by their sum if it exceeds 1. The
    weights of a row never add up to more than 1 (no leverage).
    """
    values = signals.astype("float64")
    if sizing.method == "equal_weight":
        selected = (values > 0).sum(axis=1)
        weights = values.div(selected.where(selected > 0), axis=0).fillna(0.0)
    elif sizing.method == "fixed_fraction":
        if sizing.fraction is None:
            raise ValueError("fixed_fraction needs a fraction")
        weights = values * sizing.fraction
        total = weights.sum(axis=1)
        weights = weights.div(total.where(total > 1.0, 1.0), axis=0)
    else:
        raise ValueError(f"unknown sizing method {sizing.method!r}")
    return weights
