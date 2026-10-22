"""The independent cost calculation of tests/cost_reference.py, checked offline (the live test runs it on real prices).

The reference imports no engine code. Here it is checked against the literals of H23 and against the engine on fake
data, so the arithmetic of the live network test is exercised without the network.
"""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from backtest_agent.engine import run_backtest
from backtest_agent.spec import load_spec
from backtest_agent.spec.schema import Period
from cost_reference import independent_buy_and_hold
from runner_helpers import LiteralProvider, fake_frame

STRATEGIES = Path(__file__).resolve().parents[1] / "strategies"


def test_the_reference_gives_the_literals_of_h23() -> None:
    opens = {"2024-01-03": 100.0}
    closes = {"2024-01-08": 146.41}
    net, fees = independent_buy_and_hold(
        lambda day, symbol: opens[day],
        lambda day, symbol: closes[day],
        ["A"],
        1000.0,
        0.25,
        ["2024-01-03"],
        "2024-01-08",
    )
    assert net == pytest.approx(1171.28, rel=1e-12)  # 8 shares * 146.41, H23
    assert fees == pytest.approx(200.0, rel=1e-12)
    gross, no_fees = independent_buy_and_hold(
        lambda day, symbol: opens[day],
        lambda day, symbol: closes[day],
        ["A"],
        1000.0,
        0.0,
        ["2024-01-03"],
        "2024-01-08",
    )
    assert gross == pytest.approx(1464.1, rel=1e-12) and no_fees == 0.0


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_the_engine_matches_the_reference_on_fake_data(seed: int) -> None:
    spec = load_spec(STRATEGIES / "buy_and_hold.yaml").model_copy(
        update={"period": Period(start=date(2018, 1, 1), end=date(2019, 12, 31))}
    )
    frame = fake_frame(spec.universe, date(2015, 1, 1), date(2019, 12, 31), seed=seed)
    provider = LiteralProvider(frame)
    result = run_backtest(spec, provider)
    data = provider.last_frame

    # Fill days: the first bar (the initial decision is made before it) and the first bar of every later month.
    bars = result.equity.index
    firsts = bars.to_series().groupby(bars.to_period("M")).first()
    days = [ts.strftime("%Y-%m-%d") for ts in firsts]
    assert days[0] == bars[0].strftime("%Y-%m-%d")
    assert (
        sorted({ts.strftime("%Y-%m-%d") for ts in result.trades["date"]}) == days
    )  # the reference uses the right days

    def px(field: str):
        return lambda day, symbol: float(data.loc[pd.Timestamp(day), (symbol, field)])

    costs = spec.costs
    rate = (costs.commission_bps + costs.spread_bps + costs.slippage_bps) / 10_000
    last = bars[-1].strftime("%Y-%m-%d")
    args = (px("open"), px("close"), list(spec.universe), spec.initial_capital)
    gross, _ = independent_buy_and_hold(*args, 0.0, days, last)
    net, fees = independent_buy_and_hold(*args, rate, days, last)

    assert result.equity.iloc[-1] == pytest.approx(net, rel=1e-9)
    assert result.gross_final_equity == pytest.approx(gross, rel=1e-9)
    assert result.total_costs == pytest.approx(fees, rel=1e-9)
    assert result.trades["cost"].sum() == pytest.approx(fees, rel=1e-9)
    assert result.cost_drag == pytest.approx((gross - net) / spec.initial_capital, rel=1e-6)
    if gross > spec.initial_capital:
        assert result.cost_share == pytest.approx((gross - net) / (gross - spec.initial_capital), rel=1e-6)
    else:
        assert result.cost_share is None  # a loss has no share
