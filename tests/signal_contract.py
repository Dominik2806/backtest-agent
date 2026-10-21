"""Reusable signal contract: every registered signal must pass these checks (see docs/strategy-spec.md)."""

from collections.abc import Iterable
from datetime import date

import numpy as np
import pandas as pd

from backtest_agent.data import FIELDS, FakeProvider
from backtest_agent.spec import Signal, SignalParams, validate_signal_output
from backtest_agent.spec.signals import close_frame


def fake_prices(symbols: list[str], rows: int) -> pd.DataFrame:
    """Standard frame of ``rows`` Mon-Fri rows from the fake provider."""
    dates = pd.bdate_range(date(2024, 1, 2), periods=rows)
    return FakeProvider().get_prices(symbols, dates[0].date(), dates[-1].date())


def blank(frame: pd.DataFrame, symbol: str, positions: Iterable[int]) -> None:
    """Make rows all-NaN for one symbol (its holidays, a late start or an early end), in place."""
    for field in FIELDS:
        frame.loc[frame.index[list(positions)], (symbol, field)] = np.nan


def contract_frames(rows: int = 300) -> dict[str, pd.DataFrame]:
    """Inputs of the contract test: plain, different calendars, short history and a single symbol."""
    calendars = fake_prices(["AAA", "BBB", "CCC"], rows)
    q = rows // 4
    blank(calendars, "BBB", [rows // 30, rows // 30 + 1, rows // 7, q, q + 1, q + 2, rows // 2])  # holidays
    blank(calendars, "CCC", range(0, rows // 12))  # starts late
    blank(calendars, "AAA", range(rows - 6, rows))  # ends early
    return {
        "plain": fake_prices(["AAA", "BBB", "CCC"], rows),
        "calendars": calendars,
        "short": fake_prices(["AAA", "BBB", "CCC"], 4),
        "single": fake_prices(["AAA"], rows),
    }


def check_signal_contract(signal: Signal, params: SignalParams, frames: dict[str, pd.DataFrame]) -> None:
    """Output rules, purity and determinism on every frame, and an honest warm-up on the long ones."""
    for name, prices in frames.items():
        snapshot = prices.copy(deep=True)
        raw = signal.function(prices, params)  # the real function on the real frame: must not modify it
        pd.testing.assert_frame_equal(prices, snapshot, check_exact=True, obj=f"input of {signal.id} ({name})")
        validate_signal_output(prices, raw)
        generated = signal.generate(prices, params)
        pd.testing.assert_frame_equal(generated, raw, check_exact=True)  # deterministic
        assert generated.index.equals(prices.index)
        assert list(generated.columns) == list(dict.fromkeys(prices.columns.get_level_values("symbol")))
        assert (generated.dtypes == "float64").all()
        assert generated.to_numpy().min() >= 0.0 and generated.to_numpy().max() <= 1.0
        assert not generated.isna().to_numpy().any()
        if name in ("plain", "calendars"):
            check_warmup_is_honest(signal, params, prices)


def check_warmup_is_honest(signal: Signal, params: SignalParams, prices: pd.DataFrame) -> None:
    """The declared ``warmup_rows`` is true (this is not the Phase 15 look-ahead test).

    1. The output is 0.0 on the first ``warmup_rows`` trading rows of every symbol.
    2. On every date the value equals the value computed from only ``warmup_rows`` trading rows of history before
       that date (for every symbol, plus the date itself) instead of the full history.
    """
    w = params.warmup_rows()
    assert isinstance(w, int) and w >= 0
    full = signal.generate(prices, params)
    closes = close_frame(prices)
    trading = {s: np.flatnonzero(closes[s].notna().to_numpy()) for s in closes.columns}

    for symbol, positions in trading.items():
        end = positions[w] if len(positions) > w else len(prices)  # rows before the (w+1)-th trading row
        assert (full[symbol].iloc[:end] == 0.0).all(), f"{signal.id}: {symbol} is not 0.0 during its warm-up of {w}"

    for i in range(len(prices)):
        start = i
        for positions in trading.values():
            last = int(np.searchsorted(positions, i, side="right")) - 1  # the symbol's last trading row up to i
            if last >= 0:
                start = min(start, int(positions[max(0, last - w)]))
        truncated = signal.function(prices.iloc[start : i + 1].copy(deep=False), params)
        pd.testing.assert_series_equal(
            truncated.iloc[-1],
            full.iloc[i],
            check_exact=True,
            check_names=False,
            obj=f"{signal.id} on {prices.index[i].date()} with {w} warm-up rows",
        )
