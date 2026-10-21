"""Tiny literal price frames for hand-computed tests."""

import numpy as np
import pandas as pd

from backtest_agent.data import FIELDS


def literal_frame(closes: dict[str, list[float]], start: str = "2024-01-02") -> pd.DataFrame:
    """Standard frame with open = high = low = close per symbol; NaN in a close makes that row all-NaN."""
    rows = len(next(iter(closes.values())))
    index = pd.bdate_range(start, periods=rows).astype("datetime64[ns]").rename("date")
    data = {}
    for symbol, values in closes.items():
        close = np.array(values, dtype="float64")
        for field in FIELDS[:4]:
            data[(symbol, field)] = close
        data[(symbol, "volume")] = np.where(np.isnan(close), np.nan, 1000.0)
    frame = pd.DataFrame(data, index=index)
    frame.columns = pd.MultiIndex.from_tuples(frame.columns, names=["symbol", "field"])
    return frame
