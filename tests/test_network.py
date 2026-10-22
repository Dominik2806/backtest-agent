from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from backtest_agent.data import DataProvider, hash_frame, validate_prices, validate_standard_frame
from backtest_agent.data.cache import CachedProvider
from backtest_agent.data.yfinance_provider import YFinanceProvider
from backtest_agent.engine import run_backtest
from backtest_agent.spec import load_spec
from backtest_agent.spec.schema import Period
from cost_reference import independent_buy_and_hold

SYMBOLS = ["AAPL", "SAP.DE", "SPY"]  # US stock, German stock (tz-aware Europe/Berlin index), US ETF
START = date(2023, 1, 2)
END = date(2023, 3, 31)


@pytest.mark.network
def test_live_yfinance_three_tickers_second_call_comes_from_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inner = YFinanceProvider()
    fetches: list[tuple[str, ...]] = []
    real_get_prices = inner.get_prices

    def counting(symbols, start, end):
        fetches.append(tuple(symbols))
        return real_get_prices(symbols, start, end)

    monkeypatch.setattr(inner, "get_prices", counting)
    provider = CachedProvider(inner, cache_dir=tmp_path)

    first = provider.get_prices(SYMBOLS, START, END)
    validate_standard_frame(first, SYMBOLS)
    assert fetches == [tuple(SYMBOLS)]
    assert len(list((tmp_path / "yfinance").glob("*.parquet"))) == 3

    second = provider.get_prices(SYMBOLS, START, END)
    assert fetches == [tuple(SYMBOLS)]  # no second download
    pd.testing.assert_frame_equal(first, second, check_exact=True)

    # Real data can be messy, so warnings are allowed; errors are not.
    result = validate_prices(first, start=START, end=END)
    assert not result.has_errors, result.to_json()
    assert hash_frame(first) == hash_frame(second)


class RecordingProvider(DataProvider):
    """Delegates to another provider and keeps the frame it delivered last."""

    def __init__(self, inner: DataProvider) -> None:
        self.inner = inner
        self.name = inner.name
        self.frame: pd.DataFrame | None = None

    def get_prices(self, symbols, start, end):
        self.frame = self.inner.get_prices(symbols, start, end)
        return self.frame


@pytest.mark.network
def test_live_buy_and_hold_final_equity_matches_an_independent_calculation(tmp_path: Path) -> None:
    spec = load_spec(Path(__file__).resolve().parents[1] / "strategies" / "buy_and_hold.yaml")
    spec = spec.model_copy(update={"period": Period(start=date(2023, 1, 3), end=date(2023, 3, 31))})
    assert list(spec.universe) == ["SPY", "TLT", "GLD"]
    provider = RecordingProvider(CachedProvider(YFinanceProvider(), cache_dir=tmp_path))

    result = run_backtest(spec, provider)
    frame = provider.frame
    assert frame is not None

    # Independent calculation from the same downloaded frame, in plain arithmetic (tests/cost_reference.py, no engine
    # code): equal thirds bought at the open of the first bar (the initial decision is made on the bar before,
    # 2022-12-30), then rebalanced to equal thirds at the opens of 2023-02-01 and 2023-03-01 (the bars after the month
    # ends 2023-01-31 and 2023-02-28; 2023-03-31 is the last bar of the data, so it is no decision bar). Delay 1, open
    # fills. Run once without costs (the gross path) and once with the spec's costs, which are cash fees.
    def px(field: str):
        return lambda day, symbol: float(frame.loc[pd.Timestamp(day), (symbol, field)])

    capital = spec.initial_capital
    costs = spec.costs
    rate = (costs.commission_bps + costs.spread_bps + costs.slippage_bps) / 10_000
    assert costs.min_commission == 0  # the reference solves proportional fees only
    days = ["2023-01-03", "2023-02-01", "2023-03-01"]
    gross, _ = independent_buy_and_hold(px("open"), px("close"), list(spec.universe), capital, 0.0, days, "2023-03-31")
    net, fees = independent_buy_and_hold(
        px("open"), px("close"), list(spec.universe), capital, rate, days, "2023-03-31"
    )

    assert result.equity.index[0] == pd.Timestamp("2023-01-03")
    assert result.equity.index[-1] == pd.Timestamp("2023-03-31")
    assert result.equity.iloc[-1] == pytest.approx(net, rel=1e-9)
    assert result.gross_final_equity == pytest.approx(gross, rel=1e-9)
    assert result.total_costs == pytest.approx(fees, rel=1e-9)
    assert result.trades["cost"].sum() == pytest.approx(fees, rel=1e-9)
    assert result.trades["cost"].sum() == pytest.approx(rate * result.trades["notional"].abs().sum(), rel=1e-9)
    assert result.net_return == pytest.approx(net / capital - 1, rel=1e-9)
    assert result.cost_drag == pytest.approx((gross - net) / capital, rel=1e-6)
    if gross > capital:
        assert result.cost_share == pytest.approx((gross - net) / (gross - capital), rel=1e-6)
    else:
        assert result.cost_share is None
    assert result.costs_applied and result.risk_flags == ()
    assert sorted({ts.date().isoformat() for ts in result.trades["date"]}) == days
    assert len(result.trades) == 9
    assert result.data_hash == hash_frame(frame)
    assert not result.validation.has_errors
