"""Hand-calculated cost fixtures H16 to H22 of docs/engine.md.

Every expected value below is a literal copied from that document; nothing is computed with engine code or with a
helper that mirrors it (only literal fractions such as 40 / 73, written as in the document). The tolerance is the
documented 1e-9: the bisection of the funding rule leaves a residual at the floating point resolution.
"""

import pandas as pd
import pytest

from backtest_agent.engine import BpsCosts, Portfolio
from engine_helpers import NAN, run

TOLERANCE = 1e-9
D3 = ["2024-01-02", "2024-01-03", "2024-01-04"]
D4 = D3 + ["2024-01-05"]
D5 = D4 + ["2024-01-08"]


def approx(values: list[float]):
    return pytest.approx(values, rel=TOLERANCE, abs=TOLERANCE)


def check(
    p: Portfolio,
    *,
    dates: list[str],
    equity: list[float],
    cash: list[float],
    costs: list[float],
    trades: list[tuple[str, str, float, float, float, float]],  # date, symbol, shares, price, notional, cost
    shares: dict[str, list[float]] | None = None,
    turnover: list[float] | None = None,
    deferred: int = 0,
    unfilled: int = 0,
) -> None:
    assert [d.strftime("%Y-%m-%d") for d in p.equity.index] == dates
    assert list(p.equity) == approx(equity)
    assert list(p.cash) == approx(cash)
    assert list(p.costs) == approx(costs)
    assert p.total_costs == pytest.approx(sum(costs), rel=TOLERANCE, abs=TOLERANCE)
    for symbol, expected in (shares or {}).items():
        assert list(p.positions[symbol]) == approx(expected), f"shares {symbol}"
    if turnover is not None:
        assert list(p.turnover) == approx(turnover)
    assert len(p.trades) == len(trades), p.trades
    for row, (date, symbol, quantity, price, notional, cost) in zip(
        p.trades.itertuples(index=False), trades, strict=True
    ):
        assert row.date == pd.Timestamp(date)
        assert row.symbol == symbol
        assert [row.shares, row.price, row.notional, row.cost] == approx([quantity, price, notional, cost])
    assert p.initial_equity == 1000.0
    assert (p.deferred_orders, p.unfilled_orders) == (deferred, unfilled)


H16_PRICE = {"A": [100, 100, 120, 120]}
H16_SIGNAL = {"A": [1, 1, 0, 0]}
HALF = {"method": "fixed_fraction", "fraction": 0.5}


def test_h16_commission_only() -> None:
    p = run(H16_PRICE, H16_PRICE, H16_SIGNAL, cost_model=BpsCosts(100, 0, 0), **HALF)
    check(
        p,
        dates=D4,
        equity=[1000, 995, 1095, 1089],
        cash=[1000, 495, 495, 1089],
        costs=[0, 5, 0, 6],
        shares={"A": [0, 5, 5, 0]},
        turnover=[0, 0.5, 0, 40 / 73],
        trades=[("2024-01-03", "A", 5, 100, 500, 5), ("2024-01-05", "A", -5, 120, -600, 6)],
    )


def test_h17_spread_and_slippage_add_up_and_the_spread_is_not_halved_again() -> None:
    p = run(H16_PRICE, H16_PRICE, H16_SIGNAL, cost_model=BpsCosts(0, 20, 30), **HALF)
    check(
        p,
        dates=D4,
        equity=[1000, 997.5, 1097.5, 1094.5],
        cash=[1000, 497.5, 497.5, 1094.5],
        costs=[0, 2.5, 0, 3.0],
        turnover=[0, 0.5, 0, 240 / 439],
        trades=[("2024-01-03", "A", 5, 100, 500, 2.5), ("2024-01-05", "A", -5, 120, -600, 3.0)],
    )


def test_h18_the_minimum_commission_binds_on_the_small_trade_only() -> None:
    p = run(H16_PRICE, H16_PRICE, H16_SIGNAL, cost_model=BpsCosts(50, 20, 0, min_commission=2.8), **HALF)
    check(
        p,
        dates=D4,
        equity=[1000, 996.2, 1096.2, 1092.0],
        cash=[1000, 496.2, 496.2, 1092.0],
        costs=[0, 3.8, 0, 4.2],
        turnover=[0, 0.5, 0, 600 / 1096.2],
        trades=[("2024-01-03", "A", 5, 100, 500, 3.8), ("2024-01-05", "A", -5, 120, -600, 4.2)],
    )


def test_h19a_the_fee_of_a_sale_is_capped_at_its_proceeds() -> None:
    price = {"A": [100, 100, 101]}
    p = run(price, price, {"A": [1, 1, 1]}, rebalance="daily", cost_model=BpsCosts(0, 0, 0, min_commission=10), **HALF)
    check(
        p,
        dates=D3,
        equity=[1000, 990, 987.5],
        cash=[1000, 490, 490],
        costs=[0, 10, 7.5],
        turnover=[0, 0.5, 3 / 398],
        trades=[("2024-01-03", "A", 5, 100, 500, 10), ("2024-01-04", "A", -7.5 / 101, 101, -7.5, 7.5)],
    )


def test_h19b_a_buy_that_cannot_pay_its_minimum_fee_is_not_made_and_does_not_stay_open() -> None:
    p = run(
        {"A": [100, 100, 105], "B": [50, 50, 50]},
        {"A": [100, 100, 105], "B": [50, 50, 50]},
        {"A": [1, 1, 1], "B": [1, 1, 1]},
        rebalance="daily",
        cost_model=BpsCosts(0, 0, 0, min_commission=10),
    )
    check(
        p,
        dates=D3,
        equity=[1000, 980, 994.5],
        cash=[1000, 0, 2.25],
        costs=[0, 20, 10],
        shares={"A": [0, 4.9, 4.9 - 7 / 60], "B": [0, 9.8, 9.8]},
        turnover=[0, 0.98, 12.25 / 1004.5],
        trades=[
            ("2024-01-03", "A", 4.9, 100, 490, 10),
            ("2024-01-03", "B", 9.8, 50, 490, 10),
            ("2024-01-04", "A", -7 / 60, 105, -12.25, 10),
        ],
    )


def test_h19c_fees_use_up_the_whole_portfolio_and_nothing_is_nan() -> None:
    price = {"A": [100, 100, 100, 100]}
    p = run(price, price, {"A": [1, 0, 0, 0]}, cost_model=BpsCosts(0, 0, 0, min_commission=500), **HALF)
    check(
        p,
        dates=D4,
        equity=[1000, 500, 0, 0],
        cash=[1000, 0, 0, 0],
        costs=[0, 500, 500, 0],
        shares={"A": [0, 5, 0, 0]},
        turnover=[0, 0.5, 1.0, 0],
        trades=[("2024-01-03", "A", 5, 100, 500, 500), ("2024-01-04", "A", -5, 100, -500, 500)],
    )
    assert list(p.weights["A"]) == approx([0, 1, 0, 0])
    assert not p.weights.isna().to_numpy().any() and not p.turnover.isna().any()


H20_COSTS = BpsCosts(1000, 1000, 500)  # a total rate of 25 percent


def test_h20_a_full_rebalance_scales_the_buy_down_and_drops_the_fee_remainder() -> None:
    p = run(
        {"A": [100] * 4, "B": [50] * 4},
        {"A": [100] * 4, "B": [50] * 4},
        {"A": [1, 0, 0, 0], "B": [0, 1, 1, 1]},
        cost_model=H20_COSTS,
    )
    check(
        p,
        dates=D4,
        equity=[1000, 800, 480, 480],
        cash=[1000, 0, 0, 0],
        costs=[0, 200, 320, 0],
        shares={"A": [0, 8, 0, 0], "B": [0, 0, 9.6, 9.6]},
        turnover=[0, 0.8, 1.6, 0],
        trades=[
            ("2024-01-03", "A", 8, 100, 800, 200),
            ("2024-01-04", "A", -8, 100, -800, 200),
            ("2024-01-04", "B", 9.6, 50, 480, 120),
        ],
    )


def test_h21_a_deferred_sale_keeps_the_cost_free_part_of_the_buy_open() -> None:
    p = run(
        {"A": [100, 100, NAN, 100, 100], "B": [50] * 5},
        {"A": [100, 100, NAN, 100, 100], "B": [50, 50, 50, 50, 60]},
        {"A": [1, 0, 0, 0, 0], "B": [1] * 5},
        cost_model=H20_COSTS,
    )
    check(
        p,
        dates=D5,
        equity=[1000, 800, 800, 640, 768],
        cash=[1000, 0, 0, 0, 0],
        costs=[0, 200, 0, 160, 0],
        shares={"A": [0, 4, 4, 0, 0], "B": [0, 8, 8, 12.8, 12.8]},
        turnover=[0, 0.8, 0, 0.8, 0],
        trades=[
            ("2024-01-03", "A", 4, 100, 400, 100),
            ("2024-01-03", "B", 8, 50, 400, 100),
            ("2024-01-05", "A", -4, 100, -400, 100),
            ("2024-01-05", "B", 4.8, 50, 240, 60),
        ],
        deferred=2,
    )


def test_h22_two_assets_with_daily_rebalancing_and_costs() -> None:
    p = run(
        {"A": [100, 100, 125, 150], "B": [50] * 4},
        {"A": [100, 120, 150, 150], "B": [50] * 4},
        {"A": [1] * 4, "B": [1] * 4},
        rebalance="daily",
        cost_model=H20_COSTS,
    )
    check(
        p,
        dates=D4,
        equity=[1000, 880, 970, 948],
        cash=[1000, 0, 0, 0],
        costs=[0, 200, 20, 22],
        shares={"A": [0, 4, 3.6, 97 / 30], "B": [0, 8, 8.6, 9.26]},
        turnover=[0, 0.8, 4 / 45, 44 / 485],
        trades=[
            ("2024-01-03", "A", 4, 100, 400, 100),
            ("2024-01-03", "B", 8, 50, 400, 100),
            ("2024-01-04", "A", -0.4, 125, -50, 12.5),
            ("2024-01-04", "B", 0.6, 50, 30, 7.5),
            ("2024-01-05", "A", -11 / 30, 150, -55, 13.75),
            ("2024-01-05", "B", 0.66, 50, 33, 8.25),
        ],
    )
