"""An independent calculation of an equal-weight buy-and-hold portfolio with costs, in plain arithmetic.

It imports nothing from ``backtest_agent`` and uses no engine code: only prices and the cost rules of docs/engine.md
("Costs"), solved in closed form (no minimum commission, so the fees are proportional). The live network test checks
the engine against it on real prices; an offline test does the same on fake prices, so the arithmetic is exercised
without the network. Used by tests/test_network.py and tests/test_engine_runner_costs.py.
"""

from collections.abc import Callable, Sequence


def independent_buy_and_hold(
    open_price: Callable[[str, str], float],
    close_price: Callable[[str, str], float],
    symbols: Sequence[str],
    capital: float,
    rate: float,
    fill_days: Sequence[str],
    last_day: str,
) -> tuple[float, float]:
    """Final equity (at the close of ``last_day``) and total fees of equal weights rebalanced on ``fill_days``.

    ``rate`` is the combined cost rate (commission + half-spread + slippage, as a fraction of the traded value).
    ``open_price(day, symbol)`` and ``close_price(day, symbol)`` give the prices. On each fill day the portfolio is
    brought to equal value at the open; sells pay their fee out of the proceeds, buys need notional plus fee and are
    scaled down by one factor if the cash does not cover them.
    """
    count = len(symbols)
    shares = dict.fromkeys(symbols, 0.0)
    cash, fees = capital, 0.0
    for day in fill_days:
        value = cash + sum(shares[s] * open_price(day, s) for s in symbols)
        target = value / count
        sells = {s: shares[s] * open_price(day, s) - target for s in symbols if shares[s] * open_price(day, s) > target}
        buys = {s: target - shares[s] * open_price(day, s) for s in symbols if s not in sells}
        sold, bought = sum(sells.values()), sum(buys.values())
        budget = cash + sold * (1 - rate)  # cash after the sells, net of their fees
        free_share = 1.0 if bought <= cash + sold else (cash + sold) / bought  # what cash covers if trading were free
        share = min(free_share, budget / (bought * (1 + rate))) if bought > 0 else 0.0
        for s, amount in sells.items():
            shares[s] -= amount / open_price(day, s)
        for s, amount in buys.items():
            shares[s] += share * amount / open_price(day, s)
        cash = budget - share * bought * (1 + rate)
        fees += rate * sold + rate * share * bought
    return cash + sum(shares[s] * close_price(last_day, s) for s in symbols), fees
