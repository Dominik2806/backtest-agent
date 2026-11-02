"""The reusable signal contract check: what every signal must do on synthetic frames (docs/strategy-spec.md).

It lived in ``tests/signal_contract.py`` and was only run for the signals of this repository. A coded signal has to
pass the same checks before it runs, and ``bt signal check`` runs them for the maintainer, so they live in the package
now and raise ``SignalContractError`` (not ``assert``, which ``python -O`` removes). ``tests/signal_contract.py``
re-exports them.

The checks use synthetic frames of the fake provider, never real data:

* the function does not modify the frame it is given, and gives the same answer twice;
* the output obeys the contract on every call (shape, range, no NaN, zero rows: ``Signal.generate`` checks all of it);
* the declared ``warmup_rows`` is honest: the value on every date equals the value computed from only that many rows
  of history before it, which also catches a function that looks at the future. It is **not** the look-ahead test of
  Phase 15 on real data; it proves that the declared history is enough on these frames.
"""

from collections.abc import Iterable
from datetime import date

import numpy as np
import pandas as pd

from backtest_agent.data import FIELDS, FakeProvider
from backtest_agent.spec.errors import SignalContractError
from backtest_agent.spec.signals import Signal, SignalParams, close_frame

FRAME_NAMES = ("plain", "calendars", "short", "single")
_HONESTY_FRAMES = ("plain", "calendars")


def fake_prices(symbols: list[str], rows: int) -> pd.DataFrame:
    """Standard frame of ``rows`` Mon-Fri rows from the fake provider."""
    dates = pd.bdate_range(date(2024, 1, 2), periods=rows)
    return FakeProvider().get_prices(symbols, dates[0].date(), dates[-1].date())


def blank(frame: pd.DataFrame, symbol: str, positions: Iterable[int]) -> None:
    """Make rows all-NaN for one symbol (its holidays, a late start or an early end), in place."""
    for field in FIELDS:
        frame.loc[frame.index[list(positions)], (symbol, field)] = np.nan


def contract_frames(rows: int = 300) -> dict[str, pd.DataFrame]:
    """Inputs of the contract check: plain, different calendars, short history and a single symbol."""
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
    """Purity, determinism, the output rules and an honest warm-up on every frame; raises ``SignalContractError``.

    Every error names the signal and the frame (``"<id> on the <frame> frame: ..."``). That includes the errors that
    ``Signal.generate`` raises for a bad output, and anything else the function raises (``"<id> on the <frame>
    frame: <ExceptionType>: <text>"``): code written by an agent can fail in any way, and the result is always a
    contract error.
    """
    for name, prices in frames.items():
        where = f"{signal.id} on the {name} frame"
        try:
            _check_frame(signal, params, prices, honest=name in _HONESTY_FRAMES)
        except SignalContractError as error:
            raise SignalContractError(f"{where}: {error}") from error
        except (KeyboardInterrupt, GeneratorExit):
            raise
        except BaseException as error:  # also SystemExit: reported as a contract error
            raise SignalContractError(f"{where}: {type(error).__name__}: {error}") from error


def _check_frame(signal: Signal, params: SignalParams, prices: pd.DataFrame, *, honest: bool) -> None:
    snapshot = prices.copy(deep=True)
    raw = signal.function(prices, params)  # the real function on the real frame: it must not modify it
    if not prices.equals(snapshot):
        raise SignalContractError("the function modified its input frame")
    generated = signal.generate(prices, params)  # the output rules and the zero rows, as the engine calls it
    if not generated.equals(raw):
        raise SignalContractError("the function is not deterministic (a second call gave another answer)")
    if honest:
        _check_honest(signal, params, prices)


def check_warmup_is_honest(
    signal: Signal, params: SignalParams, prices: pd.DataFrame, frame: str | None = None
) -> None:
    """The declared ``warmup_rows`` is true; raises ``SignalContractError`` otherwise.

    That the output is 0.0 on the first ``warmup_rows`` trading rows of every symbol is enforced by ``generate``
    itself (``validate_signal_zeros``). Here: on every date the value equals the value computed from only
    ``warmup_rows`` trading rows of history before that date (for every symbol, plus the date itself) instead of the
    full history. The error names the signal, and the frame if ``frame`` is given.
    """
    where = signal.id if frame is None else f"{signal.id} on the {frame} frame"
    try:
        _check_honest(signal, params, prices)
    except SignalContractError as error:
        raise SignalContractError(f"{where}: {error}") from error
    except (KeyboardInterrupt, GeneratorExit):
        raise
    except BaseException as error:  # also SystemExit
        raise SignalContractError(f"{where}: {type(error).__name__}: {error}") from error


def _check_honest(signal: Signal, params: SignalParams, prices: pd.DataFrame) -> None:
    full = signal.generate(prices, params)  # also refuses a warmup_rows that is not an integer of at least 0
    w = params.warmup_rows()
    closes = close_frame(prices)
    trading = {s: np.flatnonzero(closes[s].notna().to_numpy()) for s in closes.columns}

    for i in range(len(prices)):
        start = i
        for positions in trading.values():
            last = int(np.searchsorted(positions, i, side="right")) - 1  # the symbol's last trading row up to i
            if last >= 0:
                start = min(start, int(positions[max(0, last - w)]))
        truncated = signal.function(prices.iloc[start : i + 1].copy(deep=False), params)
        if not isinstance(truncated, pd.DataFrame) or truncated.shape[1] != full.shape[1]:
            raise SignalContractError(
                f"the function does not return a frame with one column per symbol when it is given only {w} rows of "
                f"history before {prices.index[i].date()}"
            )
        if not np.array_equal(truncated.iloc[-1].to_numpy(), full.iloc[i].to_numpy()):
            raise SignalContractError(
                f"the value on {prices.index[i].date()} changes when only {w} rows of history are given; "
                "the declared warmup_rows is too small, or the function uses data from after the date"
            )


#: Rows of the synthetic frames that the check before a run uses (``bt signal check`` uses the 300 of
#: ``contract_frames``).
PRE_RUN_ROWS = 120


def check_before_run(signal: Signal, params: SignalParams) -> None:
    """The contract check that the gate makes before a coded signal runs: all checks, on frames of ``PRE_RUN_ROWS``.

    No row is skipped and nothing depends on time, so the same code and params give the same answer on every machine.
    """
    check_signal_contract(signal, params, contract_frames(PRE_RUN_ROWS))
