"""H15 of docs/engine.md: the closes of the bars before the first bar value a symbol that has no price on it."""

import numpy as np

from engine_helpers import NAN, run


def test_h15_a_symbol_without_a_price_on_the_first_bar_is_valued_at_its_warm_up_close() -> None:
    portfolio = run(
        opens={"A": [100, 100, 100, 120], "B": [50, 50, NAN, 50]},
        closes={"A": [100, 100, 110, 120], "B": [50, 50, NAN, 70]},
        signals={"A": [1, 1, 1, 1], "B": [1, 1, 1, 1]},
        first_bar="2024-01-04",
    )
    assert [d.day for d in portfolio.equity.index] == [4, 5]
    np.testing.assert_allclose(portfolio.equity, [1050, 1300], rtol=1e-12)
    np.testing.assert_allclose(portfolio.cash, [500, 0], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(portfolio.positions["A"], [5, 5], rtol=1e-12)
    np.testing.assert_allclose(portfolio.positions["B"], [0, 10], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(portfolio.weights["A"], [11 / 21, 6 / 13], rtol=1e-12)
    np.testing.assert_allclose(portfolio.weights["B"], [0, 7 / 13], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(portfolio.turnover, [0.5, 5 / 11], rtol=1e-12)
    trades = portfolio.trades
    assert [d.day for d in trades["date"]] == [4, 5]
    assert trades["symbol"].tolist() == ["A", "B"]
    assert trades["shares"].tolist() == [5, 10]
    assert trades["price"].tolist() == [100, 50]
    assert trades["notional"].tolist() == [500, 500]
    assert (portfolio.deferred_orders, portfolio.unfilled_orders) == (1, 0)
