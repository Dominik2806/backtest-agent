"""A report for each of the three example strategies, offline: FakeProvider, the period moved into the fake history.

Like tests/test_engine_examples.py. No test here may reach the network: an autouse fixture makes every socket connection
fail, and one test proves that the guard works.
"""

import socket
import warnings
from datetime import date
from pathlib import Path

import pytest

from backtest_agent.data import FakeProvider
from backtest_agent.metrics import evaluate
from backtest_agent.spec import load_spec
from backtest_agent.spec.schema import Period
from report_example_checks import check_written_report

STRATEGIES = Path(__file__).resolve().parents[1] / "strategies"
NAMES = ("sma_crossover", "momentum_12_1", "buy_and_hold")
PERIOD = Period(start=date(2018, 1, 1), end=date(2019, 12, 31))  # the fake history starts in 2015


def install_guard(patcher: pytest.MonkeyPatch) -> None:
    def refuse(self, *args, **kwargs):
        raise AssertionError("an offline test tried to open a network connection")

    patcher.setattr(socket.socket, "connect", refuse)
    patcher.setattr(socket.socket, "connect_ex", refuse)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    install_guard(monkeypatch)  # monkeypatch puts the real functions back after every test


def test_the_guard_blocks_connections() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock, pytest.raises(AssertionError, match="offline test"):
        sock.connect(("127.0.0.1", 9))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock, pytest.raises(AssertionError, match="offline test"):
        sock.connect_ex(("127.0.0.1", 9))


def test_the_guard_is_installed_with_monkeypatch_and_undone_with_it() -> None:
    before = (socket.socket.connect, socket.socket.connect_ex)
    with pytest.MonkeyPatch.context() as patcher:
        install_guard(patcher)
        assert (socket.socket.connect, socket.socket.connect_ex) != before
    assert (socket.socket.connect, socket.socket.connect_ex) == before


@pytest.mark.parametrize("name", NAMES)
def test_the_report_of_an_example_strategy(name: str, tmp_path: Path) -> None:
    spec = load_spec(STRATEGIES / f"{name}.yaml").model_copy(update={"period": PERIOD})
    provider = FakeProvider(symbols=spec.universe)
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # enough history: no warning of any kind
        evaluation = evaluate(spec, provider)

    assert len(evaluation.result.equity) > 500 and not evaluation.result.trades.empty
    assert evaluation.result.warmup.sufficient
    folder = check_written_report(evaluation, tmp_path / "reports")
    assert folder.parent == tmp_path / "reports"
    print(f"{name}: {len(evaluation.result.equity)} bars, {len(evaluation.result.trades)} trades")
