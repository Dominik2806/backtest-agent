# Backtest report: Buy and hold A

- **Run id:** `20260115T103005Z-buy-and-hold-a-a85a59ee`
- **Generated at:** 2026-01-15 10:30:05 UTC
- **Period:** 2024-01-02 to 2024-01-08
- **Bars:** 5 bars, first bar 2024-01-02, last bar 2024-01-08
- **Universe:** A
- **Benchmark:** B
- **Trials:** family buy_and_hold: 2 distinct variants in 3 runs as of this run. This run is run 3, a repeat of variant 1. Counts cover only runs logged in this journal.

## Spec summary

| Item | Value |
| --- | --- |
| Name | Buy and hold A |
| Description | A spec used in tests. |
| Universe | A |
| Period | 2024-01-02 to 2024-01-08 |
| Data provider | yfinance |
| Signal | buy_and_hold |
| Signal parameters | (none) |
| Warm-up rows required | 0 |
| Rebalance | on_signal |
| Sizing | equal_weight |
| Execution delay (bars) | 1 |
| Execution price | open |
| Same-bar execution allowed | no |
| Initial capital | 1,000.00 |
| Commission | 1,000 bps |
| Spread | 1,000 bps |
| Slippage | 500 bps |
| Minimum commission per trade | 0.00 |
| Benchmark | B |

## Data

### Strategy run

- **Symbols:** A
- **Data hash:** `61669f6e7476623e1289ff7dad8c8b767f36be44961c05ec4def3f45c15dd090`
- **Validation:** 0 errors, 0 warnings, 1 info

| Severity | Code | Symbol | Field | Rows | First dates | Message |
| --- | --- | --- | --- | --- | --- | --- |
| info | starts_late | A | all | 11 | 2024-01-02 | A: data starts on 2024-01-02, 11 business days after the requested 2023-12-17 |

### Benchmark run

- **Symbols:** B
- **Data hash:** `ff487f9000d166df03fa5e84640c7524f7414b58173ed654e33fab7f1df0b094`
- **Validation:** 0 errors, 0 warnings, 1 info

| Severity | Code | Symbol | Field | Rows | First dates | Message |
| --- | --- | --- | --- | --- | --- | --- |
| info | starts_late | B | all | 11 | 2024-01-02 | B: data starts on 2024-01-02, 11 business days after the requested 2023-12-17 |

### Warm-up

| Item | Value |
| --- | --- |
| Warm-up rows required by the signal | 0 |
| Execution delay (bars) | 1 |
| Rows needed before the first bar | 1 |
| History loaded from | 2023-12-17 |
| First bar of the run | 2024-01-02 |
| First decision date | 2024-01-02 |
| Warm-up sufficient | yes |
| Symbols with too little history | none |

| Symbol | Rows before the first decision | First data date | Target weight of the first decision |
| --- | --- | --- | --- |
| A | 0 | 2024-01-02 | 100.00% |

Benchmark B: 0 warm-up rows required, warm-up sufficient: yes, first bar 2024-01-02.

## Risk flags

No risk flags.

## Metrics

### Assumptions

| Assumption | Value |
| --- | --- |
| Bars per year (periods_per_year) | 5 |
| Risk-free rate (annual) | 0.00% |

### Performance

| Metric | Strategy | Benchmark |
| --- | --- | --- |
| Total return | 17.13% | -21.59% |
| CAGR | 17.13% | -21.59% |
| Volatility (annualized) | 21.77% | 20.83% |
| Sharpe ratio | 0.83 | -1.06 |
| Sortino ratio | 1.50 | -1.19 |
| Maximum drawdown | -12.00% | -21.59% |
| Current drawdown | 0.00% | -21.59% |
| Longest drawdown | 3 bars / 3 days | 4 bars / 6 days |
| Calmar ratio | 1.43 | -1.00 |
| Hit rate (share of bars with a gain) | 60.00% | 20.00% |
| Best month | 17.13% (2024-01) | -21.59% (2024-01) |
| Worst month | 17.13% (2024-01) | -21.59% (2024-01) |
| Bars | 5 | 5 |
| Years | 1.00 | 1.00 |

### Relative to the benchmark

| Metric | Value |
| --- | --- |
| Excess return (compared window) | +38.72% |
| Tracking error (annualized) | 24.49% |
| Information ratio | 1.63 |
| Strategy return over the compared window | 17.13% |
| Benchmark return over the compared window | -21.59% |

## Benchmark alignment

| Item | Value |
| --- | --- |
| Bars of the strategy | 5 |
| Bars of the benchmark | 5 |
| Common dates | 5 |
| Compared return observations | 5 |
| Dropped dates of the strategy | 0 |
| Dropped dates of the benchmark | 0 |
| Dates dropped | no |
| Insufficient overlap (relative metrics are n/a) | no |
| Base of the comparison | initial_equity |
| Base date | n/a |
| First compared date | 2024-01-02 |
| Last compared date | 2024-01-08 |

The first common date is the first bar of both runs, so the return of the first bar is measured against the initial equity of each run.

## Costs

| Item | Strategy | Benchmark |
| --- | --- | --- |
| Costs applied | yes | yes |
| Total costs | 200.00 | 200.00 |
| Final equity, net of costs | 1,171.28 | 784.08 |
| Final equity, without costs (gross) | 1,464.10 | 980.10 |
| Net return | 17.13% | -21.59% |
| Gross return | 46.41% | -1.99% |
| Cost drag (gross return minus net return) | 29.28% | 19.60% |
| Cost share (share of the gross return the costs ate) | 63.09% | n/a (gross return is not positive) |

- The cost share is n/a when the gross return is not positive. It can be negative or above 100%, because costs change the path of the portfolio (a fee can block a bad purchase).

## Charts

### Equity

![Equity of Buy and hold A (solid) and of the benchmark B (dashed), net of costs, 2024-01-02 to 2024-01-08. The strategy ends at 1,171.28, the benchmark at 784.08.](equity.svg)

Both curves start on 2024-01-02 with the same initial capital (1,000.00), so they are comparable from the first bar. The first common date is the first bar of both runs, so the return of the first bar is measured against the initial equity of each run.

### Drawdown

![Drawdown from the highest equity so far of Buy and hold A (solid) and of the benchmark B (dashed), 2024-01-02 to 2024-01-08. The deepest drawdown of the strategy is -12.00%, of the benchmark -21.59%.](drawdown.svg)

Drawdown is the fall from the highest equity reached so far, the initial capital included. The benchmark is drawn on its own dates.

## Monthly returns

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2024 | 17.13%\* | · | · | · | · | · | · | · | · | · | · | · |

\* the first or the last month of the run, which can be partial. · a month outside the run. Returns are compounded from the net returns of the bars.

## Trade statistics

| Item | Value |
| --- | --- |
| Trades (fills) | 1 |
| Buys | 1 |
| Sells | 0 |
| Total cost of the trades | 200.00 |
| Average cost per trade | 200.00 |
| Turnover per year, two-sided | 80.00% |
| Turnover per year, one-sided | 40.00% |
| Exposure (mean invested share of equity) | 80.00% |
| Share of bars with a position | 80.00% |
| Orders deferred to a later bar | 0 |
| Orders unfilled at the end | 0 |

| Symbol | Trades | Buys | Sells |
| --- | --- | --- | --- |
| A | 1 | 1 | 0 |

- A trade is one fill: one symbol on one bar. Turnover is two-sided (buying the whole portfolio from cash is 100%).
- Deferred and unfilled orders are fields of the backtest result (deferred_orders, unfilled_orders), not trade statistics: an order is deferred when its symbol has no price on the bar or cash is short, and unfilled if it is still open after the last bar.

## Assumptions and caveats

### Fixed caveats

- **Execution.** Orders are filled the number of bars after the signal that the spec names (delay_bars, default one bar) at the open or the close of that bar. A fill on the same bar as the signal can hide look-ahead bias. The data are daily bars: there is no intraday path, no partial fill and no market impact.
- **Costs.** Costs are commission, half-spread and slippage in basis points of the traded value plus an optional minimum commission, deducted as cash fees. Real costs depend on size, liquidity and time. Costs of zero overstate what trading would return. The benchmark is charged the same costs. Taxes are not modelled.
- **Adjusted prices.** Prices are adjusted for splits and dividends, and the close is the adjusted close, which is total return with dividends reinvested. Adjusted prices are not the prices quoted on the day, and the whole adjusted history changes whenever a new dividend or split is issued. Free data can also be wrong; the validation warnings of the run are listed in the section Data.
- **Survivorship.** The universe is today's constituents unless the spec states otherwise. Securities that were delisted, merged or dropped from an index are missing, which makes past results look better than they were.
- **Annualization of short runs.** CAGR, volatility, Sharpe, Sortino, Calmar and annualized turnover are scaled from the length of the run with the bars per year printed in the metrics table. For a run of a year or less they are strongly extrapolated, and CAGR and Calmar most of all.
- **Partial months.** The first and the last calendar month of a run can be partial. Their monthly returns cover fewer bars than a full month, and the best and worst month can be one of them.
- **Selection bias.** This report does not know how many other variants were tried before this one. The more variants are tried, the more likely a good-looking result is luck.
- **Not investment advice.** A backtest is a description of the past under the assumptions above, not a forecast. This project and this report are educational and are not investment advice.

### This run

- Execution in this run: delay of 1 bar(s), fills at the open.
- The run covers 5 bars (1.00 years at 5 bars a year): CAGR and Calmar are annualized from a very short window.
