"""Hand-calculated fixtures H1 to H13 of docs/engine.md.

Every expected value below is a literal copied from that document. Nothing is computed with engine code or with a
helper that mirrors it; the only arithmetic is a literal fraction such as 6 / 11 written as in the document.
"""

import pandas as pd
import pytest

from backtest_agent.engine import Portfolio
from engine_helpers import NAN, run

REL = 1e-12


def approx(values: list[float]):
    return pytest.approx(values, rel=REL, abs=1e-12)


def check(
    p: Portfolio,
    *,
    dates: list[str],
    equity: list[float],
    cash: list[float] | None = None,
    shares: dict[str, list[float]] | None = None,
    weights: dict[str, list[float]] | None = None,
    turnover: list[float] | None = None,
    trades: list[tuple[str, str, float, float, float]] | None = None,
    deferred: int = 0,
    unfilled: int = 0,
) -> None:
    assert [d.strftime("%Y-%m-%d") for d in p.equity.index] == dates
    assert list(p.equity) == approx(equity)
    if cash is not None:
        assert list(p.cash) == approx(cash)
    for symbol, expected in (shares or {}).items():
        assert list(p.positions[symbol]) == approx(expected), f"shares {symbol}"
    for symbol, expected in (weights or {}).items():
        assert list(p.weights[symbol]) == approx(expected), f"weights {symbol}"
    if turnover is not None:
        assert list(p.turnover) == approx(turnover)
    if trades is not None:
        assert len(p.trades) == len(trades), p.trades
        for row, (date, symbol, quantity, price, notional) in zip(
            p.trades.itertuples(index=False), trades, strict=True
        ):
            assert row.date == pd.Timestamp(date)
            assert row.symbol == symbol
            assert [row.shares, row.price, row.notional] == approx([quantity, price, notional])
    assert p.initial_equity == 1000.0
    assert p.deferred_orders == deferred
    assert p.unfilled_orders == unfilled


H1_OPEN = {"A": [100, 100, 110, 121, 133.1]}
H1_CLOSE = {"A": [100, 110, 121, 133.1, 146.41]}
D5 = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"]


def test_h1_buy_and_hold_delay_1_open() -> None:
    p = run(H1_OPEN, H1_CLOSE, {"A": [1, 1, 1, 1, 1]})
    check(
        p,
        dates=D5,
        equity=[1000, 1100, 1210, 1331, 1464.1],
        cash=[1000, 0, 0, 0, 0],
        shares={"A": [0, 10, 10, 10, 10]},
        weights={"A": [0, 1, 1, 1, 1]},
        turnover=[0, 1.0, 0, 0, 0],
        trades=[("2024-01-03", "A", 10, 100, 1000)],
    )
    assert list(p.returns)[0] == 0.0  # 1000 / 1000 - 1


def test_h2_signal_switch_moves_the_position_on_the_next_day() -> None:
    p = run(H1_OPEN, H1_CLOSE, {"A": [1, 1, 0, 0, 0]})
    check(
        p,
        dates=D5,
        equity=[1000, 1100, 1210, 1210, 1210],
        cash=[1000, 0, 0, 1210, 1210],
        shares={"A": [0, 10, 10, 0, 0]},
        weights={"A": [0, 1, 1, 0, 0]},
        turnover=[0, 1.0, 0, 1.0, 0],
        trades=[("2024-01-03", "A", 10, 100, 1000), ("2024-01-05", "A", -10, 121, -1210)],
    )


def test_h3_delay_2() -> None:
    p = run(
        {"A": [100, 100, 125, 150, 200]},
        {"A": [100, 120, 130, 160, 190]},
        {"A": [1, 1, 0, 0, 0]},
        delay_bars=2,
    )
    check(
        p,
        dates=D5,
        equity=[1000, 1000, 1040, 1280, 1600],
        cash=[1000, 1000, 0, 0, 1600],
        shares={"A": [0, 0, 8, 8, 0]},
        turnover=[0, 0, 1.0, 0, 1.0],
        trades=[("2024-01-04", "A", 8, 125, 1000), ("2024-01-08", "A", -8, 200, -1600)],
    )


def test_h4_delay_0_with_close_fills() -> None:
    p = run(H1_OPEN, H1_CLOSE, {"A": [1, 1, 0, 0, 0]}, delay_bars=0, price="close")
    check(
        p,
        dates=D5,
        equity=[1000, 1100, 1210, 1210, 1210],
        cash=[0, 0, 1210, 1210, 1210],
        shares={"A": [10, 10, 0, 0, 0]},
        turnover=[1.0, 0, 1.0, 0, 0],
        trades=[("2024-01-02", "A", 10, 100, 1000), ("2024-01-04", "A", -10, 121, -1210)],
    )


H5_OPEN = {"A": [100, 100, 125, 150], "B": [50, 50, 50, 50]}
H5_CLOSE = {"A": [100, 120, 150, 150], "B": [50, 50, 50, 50]}
H5_SIGNAL = {"A": [1, 1, 1, 1], "B": [1, 1, 1, 1]}
D4 = D5[:4]


def test_h5_two_assets_daily_rebalancing() -> None:
    p = run(H5_OPEN, H5_CLOSE, H5_SIGNAL, rebalance="daily")
    check(
        p,
        dates=D4,
        equity=[1000, 1100, 1237.5, 1237.5],
        cash=[1000, 0, 0, 0],
        shares={"A": [0, 5, 4.5, 4.125], "B": [0, 10, 11.25, 12.375]},
        weights={"A": [0, 6 / 11, 6 / 11, 0.5], "B": [0, 5 / 11, 5 / 11, 0.5]},
        turnover=[0, 1.0, 1 / 9, 1 / 11],
        trades=[
            ("2024-01-03", "A", 5, 100, 500),
            ("2024-01-03", "B", 10, 50, 500),
            ("2024-01-04", "A", -0.5, 125, -62.5),
            ("2024-01-04", "B", 1.25, 50, 62.5),
            ("2024-01-05", "A", -0.375, 150, -56.25),
            ("2024-01-05", "B", 1.125, 50, 56.25),
        ],
    )


def test_h5_two_assets_on_signal_lets_the_weights_drift() -> None:
    p = run(H5_OPEN, H5_CLOSE, H5_SIGNAL, rebalance="on_signal")
    check(
        p,
        dates=D4,
        equity=[1000, 1100, 1250, 1250],
        cash=[1000, 0, 0, 0],
        shares={"A": [0, 5, 5, 5], "B": [0, 10, 10, 10]},
        weights={"A": [0, 6 / 11, 0.6, 0.6], "B": [0, 5 / 11, 0.4, 0.4]},
        turnover=[0, 1.0, 0, 0],
        trades=[("2024-01-03", "A", 5, 100, 500), ("2024-01-03", "B", 10, 50, 500)],
    )


WEEK_PRICE = [100, 100, 110, 120, 130, 130, 130, 130, 130, 130, 130]
WEEK_SIGNAL = [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0]
D11 = [
    "2024-01-02",
    "2024-01-03",
    "2024-01-04",
    "2024-01-05",
    "2024-01-08",
    "2024-01-09",
    "2024-01-10",
    "2024-01-11",
    "2024-01-12",
    "2024-01-15",
    "2024-01-16",
]
WEEK_TRADES = [("2024-01-03", "A", 10, 100, 1000), ("2024-01-08", "A", -10, 130, -1300)]


def test_h6_weekly_decision_bars_exit_only_at_the_week_end() -> None:
    p = run({"A": WEEK_PRICE}, {"A": WEEK_PRICE}, {"A": WEEK_SIGNAL}, rebalance="weekly")
    check(
        p,
        dates=D11,
        equity=[1000, 1000, 1100, 1200] + [1300] * 7,
        cash=[1000, 0, 0, 0] + [1300] * 7,
        shares={"A": [0, 10, 10, 10] + [0] * 7},
        turnover=[0, 1.0, 0, 0, 1.0, 0, 0, 0, 0, 0, 0],
        trades=WEEK_TRADES,
    )


def test_h7_monthly_decision_bars_enter_after_the_month_end() -> None:
    price = [100, 100, 100, 125, 150, 150, 175]
    p = run({"A": price}, {"A": price}, {"A": [0, 1, 1, 1, 0, 0, 0]}, start="2024-01-29", rebalance="monthly")
    check(
        p,
        dates=["2024-01-29", "2024-01-30", "2024-01-31", "2024-02-01", "2024-02-02", "2024-02-05", "2024-02-06"],
        equity=[1000, 1000, 1000, 1000, 1200, 1200, 1400],
        cash=[1000, 1000, 1000, 0, 0, 0, 0],
        shares={"A": [0, 0, 0, 8, 8, 8, 8]},
        turnover=[0, 0, 0, 1.0, 0, 0, 0],
        trades=[("2024-02-01", "A", 8, 125, 1000)],
    )


def test_h8_period_starting_mid_week_still_invests_on_the_first_bar() -> None:
    p = run({"A": WEEK_PRICE}, {"A": WEEK_PRICE}, {"A": WEEK_SIGNAL}, rebalance="weekly", first_bar="2024-01-03")
    check(
        p,
        dates=D11[1:],
        equity=[1000, 1100, 1200] + [1300] * 7,
        cash=[0, 0, 0] + [1300] * 7,
        shares={"A": [10, 10, 10] + [0] * 7},
        turnover=[1.0, 0, 0, 1.0, 0, 0, 0, 0, 0, 0],
        trades=WEEK_TRADES,
    )
    assert list(p.returns)[0] == 0.0


def test_h8_a_decision_before_the_first_bar_is_dropped() -> None:
    p = run({"A": WEEK_PRICE}, {"A": WEEK_PRICE}, {"A": WEEK_SIGNAL}, rebalance="weekly", first_bar="2024-01-05")
    check(
        p,
        dates=[
            "2024-01-05",
            "2024-01-08",
            "2024-01-09",
            "2024-01-10",
            "2024-01-11",
            "2024-01-12",
            "2024-01-15",
            "2024-01-16",
        ],
        equity=[1000] * 8,
        cash=[1000] * 8,
        shares={"A": [0] * 8},
        turnover=[0] * 8,
        trades=[],
    )


H9_OPEN = {"A": [100, 100, 100], "B": [50, 50, 50]}
D3 = D5[:3]


@pytest.mark.parametrize(
    ("fraction", "signal_b", "shares_a", "shares_b", "cash", "turnover"),
    [
        (0.6, 1, [0, 5, 5], [0, 10, 10], [1000, 0, 0], [0, 1.0, 0]),  # (a) 0.6 + 0.6 = 1.2, scaled to 0.5 + 0.5
        (0.6, 0, [0, 6, 6], [0, 0, 0], [1000, 400, 400], [0, 0.6, 0]),  # (b) only A, 0.6
        (0.3, 1, [0, 3, 3], [0, 6, 6], [1000, 400, 400], [0, 0.6, 0]),  # (c) 0.3 + 0.3 = 0.6, no scale-down
    ],
    ids=["a_scaled_down", "b_one_symbol", "c_no_scale_down"],
)
def test_h9_fixed_fraction(fraction, signal_b, shares_a, shares_b, cash, turnover) -> None:
    p = run(
        H9_OPEN,
        H9_OPEN,
        {"A": [1, 1, 1], "B": [signal_b] * 3},
        rebalance="daily",
        method="fixed_fraction",
        fraction=fraction,
    )
    check(
        p,
        dates=D3,
        equity=[1000, 1000, 1000],
        cash=cash,
        shares={"A": shares_a, "B": shares_b},
        turnover=turnover,
    )


def test_h10_fractional_signal_value_invests_that_fraction() -> None:
    p = run({"A": [100, 100, 120]}, {"A": [100, 120, 120]}, {"A": [0.5, 0.5, 0.5]})
    check(
        p,
        dates=D3,
        equity=[1000, 1100, 1100],
        cash=[1000, 500, 500],
        shares={"A": [0, 5, 5]},
        weights={"A": [0, 6 / 11, 6 / 11]},
        turnover=[0, 0.5, 0],
        trades=[("2024-01-03", "A", 5, 100, 500)],
    )


def test_h11_missing_price_on_the_execution_bar_defers_the_order() -> None:
    p = run(
        {"A": [100, 100, 120, 120], "B": [50, NAN, 50, 50]},
        {"A": [100, 120, 120, 120], "B": [50, NAN, 50, 60]},
        {"A": [1, 1, 1, 1], "B": [1, 1, 1, 1]},
    )
    check(
        p,
        dates=D4,
        equity=[1000, 1100, 1100, 1200],
        cash=[1000, 500, 0, 0],
        shares={"A": [0, 5, 5, 5], "B": [0, 0, 10, 10]},
        weights={"A": [0, 6 / 11, 6 / 11, 0.5], "B": [0, 0, 5 / 11, 0.5]},
        turnover=[0, 0.5, 5 / 11, 0],
        trades=[("2024-01-03", "A", 5, 100, 500), ("2024-01-04", "B", 10, 50, 500)],
        deferred=1,
    )


def test_h12_a_buy_waits_for_the_cash_of_a_deferred_sale() -> None:
    p = run(
        {"A": [100, 100, NAN, 100, 100], "B": [50, 50, 50, 50, 50]},
        {"A": [100, 100, NAN, 100, 100], "B": [50, 50, 50, 50, 60]},
        {"A": [1, 0, 0, 0, 0], "B": [1, 1, 1, 1, 1]},
    )
    check(
        p,
        dates=D5,
        equity=[1000, 1000, 1000, 1000, 1200],
        cash=[1000, 0, 0, 0, 0],
        shares={"A": [0, 5, 5, 0, 0], "B": [0, 10, 10, 20, 20]},
        weights={"A": [0, 0.5, 0.5, 0, 0], "B": [0, 0.5, 0.5, 1, 1]},
        turnover=[0, 1.0, 0, 1.0, 0],
        trades=[
            ("2024-01-03", "A", 5, 100, 500),
            ("2024-01-03", "B", 10, 50, 500),
            ("2024-01-05", "A", -5, 100, -500),
            ("2024-01-05", "B", 10, 50, 500),
        ],
        deferred=2,
    )


def test_h13_the_return_of_the_first_bar_is_measured_against_the_initial_capital() -> None:
    p = run(H1_OPEN, H1_CLOSE, {"A": [1, 1, 1, 1, 1]}, first_bar="2024-01-03")
    check(
        p,
        dates=D5[1:],
        equity=[1100, 1210, 1331, 1464.1],
        shares={"A": [10, 10, 10, 10]},
        trades=[("2024-01-03", "A", 10, 100, 1000)],
    )
    assert list(p.returns) == approx([0.1, 0.1, 0.1, 0.1])
