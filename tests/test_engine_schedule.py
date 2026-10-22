"""Rebalance schedule and the delay shift on literal calendars (docs/engine.md, "Rebalancing")."""

import numpy as np
import pandas as pd
import pytest

from backtest_agent.engine import decision_bars, execution_orders


def index(start: str, periods: int) -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=periods, name="date")


def targets(values: list[float], idx: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({"A": values}, index=idx, columns=pd.Index(["A"], name="symbol"))


def positions(mask) -> list[int]:
    return [int(i) for i in np.flatnonzero(np.asarray(mask))]


def test_daily_is_every_bar() -> None:
    idx = index("2024-01-02", 4)
    assert positions(decision_bars(idx, "daily", targets([1, 1, 1, 1], idx))) == [0, 1, 2, 3]


def test_weekly_is_the_last_bar_of_each_week_but_never_the_last_bar_of_the_frame() -> None:
    idx = index("2024-01-02", 11)  # Tue Jan 2 .. Tue Jan 16: weeks Jan 2-5, Jan 8-12, Jan 15-16
    assert positions(decision_bars(idx, "weekly", targets([1] * 11, idx))) == [3, 8]


def test_weekly_uses_the_last_bar_that_exists_in_a_short_week() -> None:
    idx = pd.DatetimeIndex(pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-08", "2024-01-09"]))
    # Friday Jan 5 is missing (holiday): Thursday Jan 4 is the last bar of the first week.
    assert positions(decision_bars(idx, "weekly", targets([1] * 5, idx))) == [2]


def test_monthly_is_the_last_bar_of_each_month_in_the_frame() -> None:
    idx = index("2024-01-29", 7)  # Jan 29, 30, 31, Feb 1, 2, 5, 6
    assert positions(decision_bars(idx, "monthly", targets([1] * 7, idx))) == [2]


def test_on_signal_is_where_the_target_changes_and_the_first_nonzero_target() -> None:
    idx = index("2024-01-02", 6)
    assert positions(decision_bars(idx, "on_signal", targets([0, 0, 1, 1, 0.5, 0.5], idx))) == [2, 4]
    assert positions(decision_bars(idx, "on_signal", targets([1, 1, 1, 1, 1, 1], idx))) == [0]


def test_on_signal_ignores_changes_below_the_tolerance() -> None:
    idx = index("2024-01-02", 3)
    assert positions(decision_bars(idx, "on_signal", targets([0.5, 0.5 + 1e-14, 0.5], idx))) == [0]


def test_a_single_bar_frame_has_no_weekly_decision() -> None:
    idx = index("2024-01-02", 1)
    assert positions(decision_bars(idx, "weekly", targets([1], idx))) == []


def test_an_unknown_rule_is_rejected() -> None:
    idx = index("2024-01-02", 2)
    with pytest.raises(ValueError, match="unknown rebalance rule"):
        decision_bars(idx, "yearly", targets([1, 1], idx))


def test_decisions_move_to_the_execution_bar_by_the_delay() -> None:
    idx = index("2024-01-02", 6)
    t = targets([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], idx)
    decisions = np.array([False, True, False, True, False, False])
    exec_targets, executes = execution_orders(t, decisions, delay_bars=2, first_pos=0)
    # the initial decision (bar 0) is added; bars 0, 1, 3 execute on bars 2, 3, 5
    assert positions(executes) == [2, 3, 5]
    assert exec_targets["A"].iloc[2] == 0.1 and exec_targets["A"].iloc[3] == 0.2 and exec_targets["A"].iloc[5] == 0.4


def test_decisions_whose_execution_bar_is_after_the_last_bar_are_dropped() -> None:
    idx = index("2024-01-02", 4)
    _, executes = execution_orders(targets([1, 1, 1, 1], idx), np.ones(4, dtype=bool), delay_bars=1, first_pos=0)
    assert positions(executes) == [1, 2, 3]  # the decision on bar 3 would execute on bar 4, which does not exist
    _, executes = execution_orders(targets([1, 1, 1, 1], idx), np.ones(4, dtype=bool), delay_bars=10, first_pos=0)
    assert positions(executes) == []


def test_the_initial_decision_is_the_bar_that_executes_on_the_first_bar() -> None:
    idx = index("2024-01-02", 8)
    none = np.zeros(8, dtype=bool)
    for delay, first, expected in [(1, 4, [4]), (2, 4, [4]), (0, 4, [4]), (1, 0, [1])]:
        _, executes = execution_orders(targets([1] * 8, idx), none, delay, first)
        assert positions(executes) == expected


def test_a_decision_that_would_execute_before_the_first_bar_is_dropped() -> None:
    idx = index("2024-01-02", 8)
    decisions = np.zeros(8, dtype=bool)
    decisions[[0, 1, 5]] = True  # execute on bars 1, 2, 6; the first bar is 4
    _, executes = execution_orders(targets([1] * 8, idx), decisions, delay_bars=1, first_pos=4)
    assert positions(executes) == [4, 6]  # bar 4 from the initial decision (bar 3), bar 6 from bar 5


def test_the_initial_decision_is_bar_zero_when_there_is_not_enough_history() -> None:
    idx = index("2024-01-02", 5)
    _, executes = execution_orders(targets([1] * 5, idx), np.zeros(5, dtype=bool), delay_bars=2, first_pos=1)
    assert positions(executes) == [2]  # max(1 - 2, 0) = bar 0, executed on bar 2
