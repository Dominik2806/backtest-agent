"""``run_backtest``: spec and provider in, ``BacktestResult`` out (see docs/engine.md)."""

import warnings
from datetime import date

import numpy as np
import pandas as pd

from backtest_agent.data.checks import validate_prices
from backtest_agent.data.errors import DataUnavailableError
from backtest_agent.data.hash import hash_frame
from backtest_agent.data.provider import DataProvider, validate_standard_frame
from backtest_agent.engine.core import Portfolio
from backtest_agent.engine.costs import BpsCosts, CostModel, NoCosts
from backtest_agent.engine.errors import InsufficientHistoryError, InsufficientWarmupWarning
from backtest_agent.engine.history import warmup_window
from backtest_agent.engine.result import BacktestResult, WarmupInfo
from backtest_agent.engine.simulation import simulate_signals
from backtest_agent.engine.sizing import target_weights
from backtest_agent.spec.schema import RiskFlag, StrategySpec
from backtest_agent.spec.signals import close_frame, get_signal


def run_backtest(
    spec: StrategySpec, provider: DataProvider, *, allow_short_warmup: bool = True, apply_costs: bool = True
) -> BacktestResult:
    """Run ``spec`` on the data of ``provider`` and return the result trimmed to the period.

    History is loaded from ``period.start`` minus a calendar buffer for the warm-up (``warmup_rows`` plus
    ``delay_bars`` rows), validated (errors raise ``DataValidationError``), hashed as loaded and given to the signal
    as a whole. If a symbol has fewer rows before the first decision than the signal needs, the run continues with
    the flag ``insufficient_warmup`` and an ``InsufficientWarmupWarning``, or raises ``InsufficientHistoryError``
    when ``allow_short_warmup`` is False. The costs of the spec are deducted (``BpsCosts``); with
    ``apply_costs=False`` the run is free of costs and keeps the flag ``costs_not_applied`` if the spec has any.
    If costs are applied and the spec has a non-zero cost number, a twin simulation without costs on the same data,
    signals and orders gives ``gross_equity``. The benchmark is not loaded.
    """
    period, universe = spec.period, list(spec.universe)
    window = warmup_window(spec)
    required, rows_needed, buffer_days, fetch_start = (
        window.required_rows,
        window.rows_needed,
        window.buffer_days,
        window.fetch_start,
    )

    frame = provider.get_prices(universe, fetch_start, period.end)
    delivered = set(frame.columns.get_level_values("symbol"))
    missing = [s for s in universe if s not in delivered]
    if missing:
        raise DataUnavailableError(f"the provider returned no data for {missing}")
    validate_standard_frame(frame, universe)
    if frame.index[-1] > pd.Timestamp(period.end):
        raise ValueError(f"the provider returned rows after period.end {period.end} (last: {frame.index[-1].date()})")
    validation = validate_prices(frame, start=fetch_start, end=period.end)
    validation.raise_for_errors()
    data_hash = hash_frame(frame)

    closes = close_frame(frame)
    first_pos = int(frame.index.searchsorted(pd.Timestamp(period.start)))
    if first_pos >= len(frame):
        raise DataUnavailableError(
            f"there is no bar on or after period.start {period.start} (last available: {frame.index[-1].date()})"
        )

    signals = get_signal(spec.signal.id).generate(frame, spec.signal.params)
    targets = target_weights(signals, spec.sizing)
    warmup = _warmup_info(spec, closes, targets, first_pos, required, rows_needed, buffer_days, fetch_start)

    flags: list[RiskFlag] = list(spec.risk_flags())
    if not apply_costs and not spec.costs.is_zero:
        flags.append(
            RiskFlag(
                "costs_not_applied",
                "run_backtest was called with apply_costs=False: the costs of the spec were not deducted, "
                "so the result overstates what trading would return.",
            )
        )
    if not warmup.sufficient:
        message = (
            f"{list(warmup.short_symbols)} have fewer than {required} rows before the first decision on "
            f"{warmup.first_decision_date} (rows: {warmup.rows_before}); the signal is not warmed up there"
        )
        if not allow_short_warmup:
            raise InsufficientHistoryError(message, warmup)
        flags.append(RiskFlag("insufficient_warmup", message))
        warnings.warn(message, InsufficientWarmupWarning, stacklevel=2)

    opens = frame.xs("open", axis=1, level="field").astype("float64")

    def simulate(cost_model: CostModel) -> Portfolio:
        return simulate_signals(
            opens,
            closes,
            signals,
            spec.sizing,
            spec.execution,
            spec.rebalance,
            spec.initial_capital,
            frame.index[first_pos],
            cost_model,
        )

    portfolio = simulate(BpsCosts.from_spec(spec.costs) if apply_costs else NoCosts())
    # The gross path is the same simulation without costs; it is only run if costs can make a difference.
    twin_needed = apply_costs and not spec.costs.is_zero
    gross_equity = (simulate(NoCosts()).equity if twin_needed else portfolio.equity.copy()).rename("gross_equity")
    return BacktestResult(
        spec=spec,
        data_hash=data_hash,
        validation=validation,
        risk_flags=tuple(flags),
        warmup=warmup,
        costs_applied=apply_costs,
        initial_equity=portfolio.initial_equity,
        equity=portfolio.equity,
        cash=portfolio.cash,
        positions=portfolio.positions,
        weights=portfolio.weights,
        trades=portfolio.trades,
        turnover=portfolio.turnover,
        costs=portfolio.costs,
        gross_equity=gross_equity,
        signals=signals.iloc[first_pos:],
        target_weights=targets.iloc[first_pos:],
        deferred_orders=portfolio.deferred_orders,
        unfilled_orders=portfolio.unfilled_orders,
    )


def _warmup_info(
    spec: StrategySpec,
    closes: pd.DataFrame,
    targets: pd.DataFrame,
    first_pos: int,
    required: int,
    rows_needed: int,
    buffer_days: int,
    fetch_start: date,
) -> WarmupInfo:
    decision_pos = max(first_pos - spec.execution.delay_bars, 0)
    traded = closes.notna()
    rows_before = {s: int(traded[s].iloc[:decision_pos].sum()) for s in closes.columns}
    short = tuple(s for s, rows in rows_before.items() if rows < required)
    first_data = {s: closes.index[int(np.argmax(traded[s].to_numpy()))].date() for s in closes.columns}
    return WarmupInfo(
        required_rows=required,
        delay_bars=spec.execution.delay_bars,
        rows_needed=rows_needed,
        fetch_start=fetch_start,
        buffer_days=buffer_days,
        first_bar=closes.index[first_pos].date(),
        first_decision_date=closes.index[decision_pos].date(),
        initial_target_weights={s: float(w) for s, w in targets.iloc[decision_pos].items()},
        rows_before=rows_before,
        first_data=first_data,
        short_symbols=short,
        sufficient=not short,
    )
