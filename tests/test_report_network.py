"""A report for each example strategy with real data (yfinance through CachedProvider). Run manually: -m network.

Not part of the default run or of CI. Like tests/test_network.py, the cache lives in a pytest temporary folder (that
file has no other cache location), shared by the three tests of one run so that SPY, TLT and GLD are downloaded once.
The period is short, the assertions are structural (more than 0 trades, consistent dates and cash), and the numbers
of each run are printed (use -s).
"""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from backtest_agent.data.cache import CachedProvider
from backtest_agent.data.yfinance_provider import YFinanceProvider
from backtest_agent.metrics import evaluate
from backtest_agent.spec import load_spec
from backtest_agent.spec.schema import Period
from report_example_checks import check_written_report

STRATEGIES = Path(__file__).resolve().parents[1] / "strategies"
NAMES = ("sma_crossover", "momentum_12_1", "buy_and_hold")
PERIOD = Period(start=date(2022, 1, 3), end=date(2023, 12, 29))


@pytest.fixture(scope="module")
def provider(tmp_path_factory: pytest.TempPathFactory) -> CachedProvider:
    return CachedProvider(YFinanceProvider(), cache_dir=tmp_path_factory.mktemp("yfinance-cache"))


@pytest.mark.network
@pytest.mark.parametrize("name", NAMES)
def test_the_report_of_an_example_strategy_with_real_data(name: str, provider: CachedProvider, tmp_path: Path) -> None:
    spec = load_spec(STRATEGIES / f"{name}.yaml").model_copy(update={"period": PERIOD})
    evaluation = evaluate(spec, provider)  # real data can be messy: warnings are allowed, errors stop the run
    result = evaluation.result

    bars, trades = len(result.equity), len(result.trades)
    assert bars > 400 and trades > 0
    assert result.equity.index[0] >= pd.Timestamp(PERIOD.start) and result.equity.index[-1] <= pd.Timestamp(PERIOD.end)
    assert not result.validation.has_errors and result.warmup.sufficient
    assert (result.cash >= 0).all() and (result.weights.sum(axis=1) <= 1 + 1e-9).all()
    assert pd.to_datetime(result.trades["date"]).between(result.equity.index[0], result.equity.index[-1]).all()

    check_written_report(evaluation, tmp_path / "reports")
    print(
        f"{name}: {bars} bars, {trades} trades, first bar {result.equity.index[0].date()}, "
        f"last bar {result.equity.index[-1].date()}, {len(result.validation.warnings)} validation warnings"
    )
