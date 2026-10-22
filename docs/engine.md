# Engine

The engine turns prices and signals into a portfolio path: equity, cash, positions, trades and turnover. It is
deterministic Python code (the LLM never writes it, see [ADR 0002](adr/0002-deterministic-core-llm-never-writes-engine.md))
and its arithmetic is proven by hand-calculated fixtures at the end of this document. Code lives in
`src/backtest_agent/engine/`; the decisions behind it are in [ADR 0008](adr/0008-engine-semantics.md). This project is
educational and not investment advice.

Phase 4 is delivered in two parts. **Part 1 (this document's code)** is the pure simulation: sizing, rebalance
schedule, delay shift, cost hook and the portfolio core, driven by `simulate_signals` on price and signal frames.
**Part 2** adds `run_backtest(spec, provider)` (data loading, warm-up, validation, data hash, the signal call) and the
`BacktestResult` object; the parts of this document that describe them are marked "part 2".

| Module | Responsibility |
|---|---|
| `sizing.py` | `target_weights(signals, sizing)`: signal values to target weights |
| `schedule.py` | `decision_bars`, `execution_orders`: on which bars the portfolio is rebalanced, and the shift by `delay_bars` |
| `core.py` | `simulate(...)`: the bar loop that executes orders and returns a `Portfolio` |
| `simulation.py` | `simulate_signals(...)`: sizing, schedule, shift and core in one call |
| `costs.py` | `CostModel` hook, `NoCosts` (the only model in Phase 4) |

## Semantics

This section is the specification of the engine. Everything below it (code, tests, fixtures) has to follow it.

### Bars and timeline

- A **bar** is one row of the standard price frame ([data.md](data.md)): the union of the trading days of all symbols.
  A symbol that did not trade on a bar has NaN in `open` and `close` there. Bars are numbered 0, 1, 2, ... in date order.
- The **signal on bar t** uses data up to and including the close of bar t. Sizing turns it into **target weights on
  bar t**. A bar on which the rebalance rule says "rebalance" is a **decision bar**.
- The orders of a decision bar t are executed on the **execution bar e = t + delay_bars** (counted in bars), at the
  **open** of e when `execution.price` is `open`, at the **close** of e when it is `close`. With `delay_bars: 0` the
  execution bar is the decision bar itself and the price is the close (the flagged same-bar case; an open fill on
  the signal bar is impossible and rejected by the spec).
- A decision whose execution bar lies after the last bar is dropped (it can never trade).
- The **first bar** of the run is the first bar on or after `period.start`. The portfolio starts there as 100 percent
  cash equal to `initial_capital`. **Nothing is traded or valued before the first bar.** A decision made on an earlier
  (warm-up) bar may be executed on the first bar or later, but a decision whose execution bar lies before the first
  bar is dropped.
- The output has one row per bar from the first bar on. All values are at the **end of the bar** (after the close).

### Assumptions

- Long-only, no leverage, no shorting. Fractional shares are allowed. Cash earns no interest.
- Prices are the adjusted prices of the standard frame, which are total return prices (dividends are already
  inside). The engine never adds dividends. Adjusted prices are not the prices that were quoted on the day
  ([data.md](data.md)); an absolute price level means nothing, only ratios do.
- Costs are **not** applied in Phase 4 (see "Cost hook"). The result of a run says so.
- A symbol without a price on a bar is valued at its **last close** (carried forward) and cannot be traded on that bar.

### Sizing: signal values to target weights

The signal value `x_s` of a symbol is its desired exposure, between 0 and 1 ([strategy-spec.md](strategy-spec.md)).

- `equal_weight`: let `n` be the number of symbols with `x_s > 0`. Then `w_s = x_s / n` for each of them, 0 for the
  others. Capital is split among the **selected symbols only**; an empty slot does not exist, it is not kept in cash.
  With all selected signals at 1.0 the portfolio is fully invested whenever `n >= 1`. A fractional signal means
  fractional exposure: a lone signal of 0.5 invests half.
- `fixed_fraction` with fraction `f`: `w_s = x_s * f`. If the weights add up to more than 1, every weight is divided by
  that sum, so the total is exactly 1 and there is never leverage. Otherwise the rest stays in cash.

Example of the `equal_weight` edge case. `momentum_12_1` with `top_n: 3` and `positive_only: true`, three symbols A, B,
C, capital 1000, and a day on which only A has a positive score. The signal is A = 1, B = 0, C = 0. So `n = 1` and A
gets weight 1/1 = 1.0, a position of 1000. It does **not** get 1/3 with 667 left in cash. If A and B qualify, each
gets 1/2 and holds 500. Keeping the empty slots in cash ("slot-based equal weight") is a possible later extension.

### Rebalancing: on which bars the portfolio trades

The rule decides which bars are decision bars. On a decision bar the **whole portfolio** is brought to the target
weights of that bar (every symbol gets an order, orders that are too small are dropped, see "Dust").

- `daily`: every bar is a decision bar.
- `weekly` / `monthly`: the last bar of each ISO calendar week (Monday to Sunday) / each calendar month **that exists
  in the frame**. The last bar of the whole frame never counts, because the frame cannot tell whether the week or month
  is over. The trading calendar is a calendar fact, not price data, so this does not look ahead. All trading,
  including exits, happens only on these bars (plus the initial decision below).
- `on_signal`: a bar is a decision bar when its target weights differ from those of the previous bar (any weight
  differs by more than 1e-12; the target before the first bar of the frame is all zero). Between decisions the
  portfolio drifts with prices. On a decision bar all symbols are brought to target, also those whose weight did not
  change.
- **Initial decision (all rules).** The bar whose execution bar is the first bar (bar `max(first - delay_bars, 0)`)
  is always a decision bar. Without it `weekly`, `monthly` and `on_signal` would sit in cash until their next
  decision, and `on_signal` would never buy a signal that was already 1 at the start. If a decision on an earlier
  warm-up bar executed before the first bar, it is dropped and the portfolio starts in cash, so only the initial
  decision decides what the first bar holds.

### Execution of orders on a bar

On every bar `e` from the first bar on, in this order:

1. **Mark.** `p_s` is the execution price of symbol s on e (open or close of e, or none if s has no price). The mark
   `m_s` is `p_s` if it exists, else the last close of s before e. The held value is `shares_s * m_s`, the
   portfolio value `V` is cash plus the sum of held values.
2. **New orders.** If e is the execution bar of a decision, every symbol with `w_s > 0` or `shares_s > 0` gets an
   order: the **share quantity** `q_s = (w_s * V - shares_s * m_s) / m_s` (positive buys, negative sells; for
   `w_s = 0` exactly `-shares_s`). The quantity is fixed now. An order with `|q_s * m_s| <= 1e-9 * V` is dropped
   (dust). A new decision replaces all orders that are still open.
3. **Fill.** An open order whose symbol has a price on e is filled at `p_s`. Sells are filled in full and bring in
   cash. Buys are filled in full if the cash after the sells covers all of them. Otherwise **all buys are scaled
   down by the same factor** `cash_available / total_buy_cost`, so cash never becomes negative.
4. **Carry.** An order whose symbol has no price on e stays open ("deferred") and is filled on the next bar on which
   the symbol has a price, with the **same quantity** at that bar's price. The unfilled remainder of a scaled-down
   buy stays open the same way (unless it is dust), also when the scale factor was 0 and nothing of it was filled.
   Both kinds of order (no price, or not enough cash) count in `deferred_orders` once, when they are first carried
   past their execution bar. Orders still open after the last bar count in `unfilled_orders`.
5. **Close.** Last closes are updated from the close of e. Equity is cash plus shares times last close. Weights
   are `shares * last close / equity`.

Sells before buys on a bar means proceeds fund purchases of the same bar. If a sale is deferred (no price) the
buys that depended on it are limited by the cash on hand and wait in the same way until the sale has happened.

### Turnover

**Turnover is two-sided.** The turnover of a bar is the **sum of the absolute trade notionals divided by the
portfolio value `V` at the execution mark** of that bar (step 1). Buying the whole portfolio from cash gives 1.0, a
complete switch from one asset to another gives 2.0. It is 0.0 on bars without trades. Phase 6 must label turnover
metrics accordingly (a one-sided figure is half of this).

### Cost hook

`CostModel.cost(symbol, notional)` returns the cost in currency of one trade (`notional` is the absolute traded
value, the result is 0 or more). The core deducts the costs of all trades of a bar from cash. The default
`NoCosts` returns 0.0. **The costs of the spec are not applied in Phase 4**; Phase 5 plugs a model in and has to extend
the funding rule of step 3 (a purchase must also cover its costs). Until then a model that makes cash negative
raises `EngineInvariantError`.

### Output of the core

`Portfolio` (frozen) has, per bar: `equity`, `cash`, `positions` (shares per symbol), `weights` (end of bar),
`turnover`; the `trades` table (`date`, `symbol`, `shares` signed, `price`, `notional` signed, ordered by bar then by
symbol order); `initial_equity` (the initial capital); the counters `deferred_orders` and `unfilled_orders`.
`returns` is `equity / equity.shift(1, fill_value=initial_equity) - 1`, so the **return of the first bar is
well defined**: it is measured against the initial capital. Part 2 wraps this in `BacktestResult` with the spec, data
hash, validation result, risk flags, warm-up information and the field that states that costs were not applied.

### Warm-up (part 2)

`run_backtest` loads history from `period.start` minus the warm-up of the signal (`StrategySpec.warmup_rows` plus
`delay_bars` rows, turned into a generous calendar-day buffer and then counted in actual rows), validates it, hashes
it, computes the signals on all of it and passes the whole timeline to `simulate_signals`, which trims to the first
bar. The signals are therefore already warmed up on the first bar. If the provider has less history than needed, the
result says so. The core described here only needs to know where the first bar is.

### Why a loop and not a vectorized calculation

The core loops over bars and uses numpy vector operations across symbols inside the loop. Cash, deferred orders and
the cash constraint depend on the path (what was bought yesterday decides what can be bought today), so the whole
run cannot be written as a few cumulative array operations without hiding the rules. A loop is the form in which each
rule above can be read and checked line by line. A few thousand bars run in milliseconds. This deviates from the word
"vectorized" in the roadmap and is recorded there.

## Hand-calculated fixtures

Each fixture is a tiny world with round numbers. The arithmetic is written out here, and the tests in
`tests/test_engine_hand_calculated.py` contain the **expected values as literals taken from this document**; they never
compute an expected value with engine code or with a helper that mirrors it. Every fixture uses capital 1000. "Day"
dates are consecutive business days from 2024-01-02 (Tue) unless stated: Jan 2, 3, 4, 5, 8 (Mon). `open`/`close` are
given per symbol; "signal" is the signal frame, the unlisted symbols have signal 0. Unless stated the sizing is
`equal_weight`, the delay is 1 and fills are at the `open`.

### H1 Buy and hold, delay 1, open fills

Input: bars Jan 2, 3, 4, 5, 8. Symbol A: open 100, 100, 110, 121, 133.1; close 100, 110, 121, 133.1, 146.41.
Signal A = 1 on every bar. Rebalance `on_signal`. First bar Jan 2.

- Initial decision: bar 0 (Jan 2), target 1.0, executed on bar 1 (Jan 3) at the open 100.
- Jan 3: V = 1000 (cash). q = (1.0 * 1000 - 0) / 100 = +10 shares, cost 10 * 100 = 1000, cash 0.
- No later decision: the target never changes.
- Equity (end of bar): Jan 2: cash 1000. Jan 3: 10 * 110 = 1100. Jan 4: 10 * 121 = 1210. Jan 5: 10 * 133.1 = 1331.
  Jan 8: 10 * 146.41 = 1464.1.
- The final equity is 1000 * 146.41 / 100 = 1464.1, the exact ratio of the last close to the buy price.

| | Jan 2 | Jan 3 | Jan 4 | Jan 5 | Jan 8 |
|---|---|---|---|---|---|
| equity | 1000 | 1100 | 1210 | 1331 | 1464.1 |
| cash | 1000 | 0 | 0 | 0 | 0 |
| shares A | 0 | 10 | 10 | 10 | 10 |
| weight A | 0 | 1 | 1 | 1 | 1 |
| turnover | 0 | 1.0 | 0 | 0 | 0 |

One trade: Jan 3, A, +10 shares at 100, notional +1000. Return of the first bar (Jan 2): 1000 / 1000 - 1 = 0.

### H2 A signal switch on day t moves the position on day t+1

Input: prices of H1. Signal A = 1, 1, 0, 0, 0. Rebalance `on_signal`.

- Initial decision bar 0 buys on Jan 3 at 100: +10 shares (as H1).
- The target changes from 1 to 0 on bar 2 (Jan 4), so bar 2 is a decision bar; it executes on bar 3 (Jan 5) at the
  open 121. V on Jan 5 at the open = 10 * 121 = 1210. q = (0 - 1210) / 121 = -10 shares. Proceeds 1210, cash 1210.
- On Jan 4 itself (the day of the switch) the position is still held: equity 10 * 121 = 1210.

| | Jan 2 | Jan 3 | Jan 4 | Jan 5 | Jan 8 |
|---|---|---|---|---|---|
| equity | 1000 | 1100 | 1210 | 1210 | 1210 |
| cash | 1000 | 0 | 0 | 1210 | 1210 |
| shares A | 0 | 10 | 10 | 0 | 0 |
| weight A | 0 | 1 | 1 | 0 | 0 |
| turnover | 0 | 1.0 | 0 | 1.0 | 0 |

Trades: Jan 3 A +10 @ 100 (+1000); Jan 5 A -10 @ 121 (-1210). Turnover on Jan 5 = 1210 / 1210 = 1.0.

### H3 Delay 2

Input: bars Jan 2, 3, 4, 5, 8. Symbol A: open 100, 100, 125, 150, 200; close 100, 120, 130, 160, 190. Signal A = 1, 1,
0, 0, 0. Rebalance `on_signal`, `delay_bars: 2`.

- Initial decision bar 0, executed on bar 2 (Jan 4) at the open 125: q = 1000 / 125 = +8 shares, cash 0.
- The target changes on bar 2 (signal 0), executed on bar 4 (Jan 8) at the open 200: V = 8 * 200 = 1600,
  q = -8, cash 1600.
- Equity: Jan 2: 1000. Jan 3: 1000 (still cash). Jan 4: 8 * 130 = 1040. Jan 5: 8 * 160 = 1280. Jan 8: 1600.

| | Jan 2 | Jan 3 | Jan 4 | Jan 5 | Jan 8 |
|---|---|---|---|---|---|
| equity | 1000 | 1000 | 1040 | 1280 | 1600 |
| shares A | 0 | 0 | 8 | 8 | 0 |
| cash | 1000 | 1000 | 0 | 0 | 1600 |
| turnover | 0 | 0 | 1.0 | 0 | 1.0 |

Trades: Jan 4 A +8 @ 125 (+1000); Jan 8 A -8 @ 200 (-1600).

### H4 Delay 0 with close fills (the flagged same-bar case)

Input: prices of H1. Signal A = 1, 1, 0, 0, 0. Rebalance `on_signal`, `delay_bars: 0`, price `close`.

- Initial decision bar 0, executed on bar 0 (Jan 2) at the close 100: q = 1000 / 100 = +10.
- Switch to 0 on bar 2 (Jan 4), executed on Jan 4 at the close 121: V = 10 * 121 = 1210, q = -10, cash 1210.

| | Jan 2 | Jan 3 | Jan 4 | Jan 5 | Jan 8 |
|---|---|---|---|---|---|
| equity | 1000 | 1100 | 1210 | 1210 | 1210 |
| shares A | 10 | 10 | 0 | 0 | 0 |
| cash | 0 | 0 | 1210 | 1210 | 1210 |
| turnover | 1.0 | 0 | 1.0 | 0 | 0 |

Trades: Jan 2 A +10 @ 100 (+1000); Jan 4 A -10 @ 121 (-1210). The position is built on the very bar of the signal;
that is why the spec flags this case.

### H5 Two assets: daily rebalancing versus `on_signal` drift

Input: bars Jan 2, 3, 4, 5. A: open 100, 100, 125, 150; close 100, 120, 150, 150. B: open 50, 50, 50, 50; close 50,
50, 50, 50. Signals A = B = 1 on every bar. `equal_weight`, delay 1, open fills.

Both runs buy on Jan 3: V = 1000, each target 500, A +5 @ 100, B +10 @ 50, cash 0. Close of Jan 3: A 5 * 120 = 600,
B 10 * 50 = 500, equity 1100.

*Daily rebalancing.* A decision on every bar.

- Jan 4 open: A 125, B 50. V = 5 * 125 + 10 * 50 = 625 + 500 = 1125. Targets 562.5 each. A: 562.5 / 125 = 4.5
  shares, q = -0.5 (notional -62.5). B: 562.5 / 50 = 11.25, q = +1.25 (+62.5). Close: A 4.5 * 150 = 675,
  B 11.25 * 50 = 562.5, equity 1237.5.
- Jan 5 open: A 150, B 50. V = 4.5 * 150 + 11.25 * 50 = 675 + 562.5 = 1237.5. Targets 618.75 each. A: 618.75 / 150 =
  4.125, q = -0.375 (-56.25). B: 618.75 / 50 = 12.375, q = +1.125 (+56.25). Close: A 4.125 * 150 = 618.75,
  B 12.375 * 50 = 618.75, equity 1237.5.

*`on_signal`.* The target never changes, so there is no decision after the initial one. Shares stay A 5, B 10.
Jan 4 close: 5 * 150 + 10 * 50 = 750 + 500 = 1250. Jan 5: 1250.

| | Jan 2 | Jan 3 | Jan 4 | Jan 5 |
|---|---|---|---|---|
| equity, daily | 1000 | 1100 | 1237.5 | 1237.5 |
| equity, on_signal | 1000 | 1100 | 1250 | 1250 |
| shares A, daily | 0 | 5 | 4.5 | 4.125 |
| shares B, daily | 0 | 10 | 11.25 | 12.375 |
| shares A, on_signal | 0 | 5 | 5 | 5 |
| shares B, on_signal | 0 | 10 | 10 | 10 |
| weight A, daily | 0 | 6/11 | 675 / 1237.5 = 6/11 | 0.5 |
| weight A, on_signal | 0 | 600 / 1100 = 6/11 | 750 / 1250 = 0.6 | 0.6 |
| turnover, daily | 0 | 1.0 | 125 / 1125 = 1/9 | 112.5 / 1237.5 = 1/11 |
| turnover, on_signal | 0 | 1.0 | 0 | 0 |

Daily trades: Jan 3 A +5 @ 100, B +10 @ 50; Jan 4 A -0.5 @ 125, B +1.25 @ 50; Jan 5 A -0.375 @ 150, B +1.125 @ 50.
`on_signal` has only the two Jan 3 trades. Cash is 0 from Jan 3 on in both runs.

### H6 Weekly decision bars

Input: 11 bars Jan 2, 3, 4, 5, 8, 9, 10, 11, 12, 15, 16 (weeks: Jan 2-5, Jan 8-12, Jan 15-16). Symbol A with open =
close: 100, 100, 110, 120, 130, 130, 130, 130, 130, 130, 130. Signal A = 1, 1, then 0 on every later bar.
Rebalance `weekly`, delay 1, open fills. First bar Jan 2.

- Decision bars: the initial decision (bar 0) and the last bar of each week that exists in the frame: Jan 5 (bar 3)
  and Jan 12 (bar 8). Jan 16 is the last bar of the frame and does not count.
- Bar 0 (target 1.0) executes on Jan 3 at 100: +10 shares.
- The signal turns 0 on Jan 4 (mid-week), but Jan 4 is not a decision bar. Bar 3 (Jan 5, target 0) executes on
  Jan 8 at 130: V = 10 * 130 = 1300, q = -10, cash 1300. The exit happens only then.
- Bar 8 (Jan 12, target 0): no position, no order.
- Equity: Jan 2: 1000. Jan 3: 10 * 100 = 1000. Jan 4: 1100. Jan 5: 1200. Jan 8 and every later bar: 1300.

Trades: Jan 3 A +10 @ 100 (+1000); Jan 8 A -10 @ 130 (-1300). Final equity 1300. (With `on_signal` the exit would be
on Jan 5 at 120 and the final equity 1200, so the rule matters.) Turnover Jan 8: 1300 / 1300 = 1.0.

### H7 Monthly decision bars

Input: 7 bars Jan 29, 30, 31, Feb 1, 2, 5, 6. Symbol A with open = close: 100, 100, 100, 125, 150, 150, 175.
Signal A = 0, 1, 1, 1, 0, 0, 0. Rebalance `monthly`, delay 1, open fills. First bar Jan 29.

- Decision bars: the initial decision (bar 0, Jan 29) and the last bar of January in the frame, Jan 31 (bar 2).
  Feb 6 is the last bar of the frame and does not count.
- Bar 0: target 0 (signal 0), no order.
- Bar 2 (Jan 31, target 1.0) executes on Feb 1 at the open 125: V = 1000, q = 1000 / 125 = +8 shares.
  The signal was already 1 on Jan 30, but the entry waits for the month end.
- The signal turns 0 on Feb 2, but the next month end is outside the frame: the position is kept.
- Equity: Jan 29, 30, 31: 1000. Feb 1: 8 * 125 = 1000. Feb 2: 8 * 150 = 1200. Feb 5: 1200. Feb 6: 8 * 175 = 1400.

One trade: Feb 1 A +8 @ 125 (+1000). Final equity 1400.

### H8 A period that starts mid-week; decisions before the first bar

Input: the data and signals of H6 (weekly). Two runs.

*First bar Jan 3 (bar 1).* The initial decision is bar 0 (Jan 2, warm-up, signal 1): executed on the first bar Jan 3 at 100,
+10 shares. The output starts on Jan 3: 10 bars. Equity: Jan 3: 10 * 100 = 1000, Jan 4: 1100, Jan 5: 1200, Jan 8
onward: 1300 (exit on Jan 8 at 130 as in H6). `initial_equity` 1000, so the return of Jan 3 is 1000 / 1000 - 1 = 0.
Without the initial decision this strategy would hold cash until the first weekly decision (Jan 5, executed Jan 8).

*First bar Jan 5 (bar 3).* The initial decision is bar 2 (Jan 4), signal 0: target 0, no order. The earlier buy
(decided on bar 0, executed on Jan 3) lies before the first bar and is dropped. The output has 8 bars (Jan 5, 8, 9,
10, 11, 12, 15, 16). Nothing is ever traded: equity is 1000 and cash 1000 on every bar, no trades.

### H9 `fixed_fraction`

Input: bars Jan 2, 3, 4. A: open = close = 100; B: open = close = 50. Rebalance `daily`, delay 1, open fills.

- (a) fraction 0.6, signals A = B = 1. Weights 0.6 + 0.6 = 1.2 > 1, so each is divided by 1.2: 0.5 and 0.5. Jan 3:
  V = 1000, A 500 / 100 = +5, B 500 / 50 = +10, cash 0. Jan 4: V = 1000, nothing to do. Equity stays 1000.
- (b) fraction 0.6, signals A = 1, B = 0. Weight of A 0.6, B 0. Jan 3: A 600 / 100 = +6 shares, cash 400. Equity 1000.
- (c) fraction 0.3, signals A = B = 1. Weights 0.3 + 0.3 = 0.6 <= 1, no scale-down. Jan 3: A 300 / 100 = +3, B 300 / 50
  = +6, cash 1000 - 300 - 300 = 400. Equity 1000.

| run | shares A (Jan 3) | shares B (Jan 3) | cash (Jan 3) | equity (Jan 2, 3, 4) |
|---|---|---|---|---|
| (a) | 5 | 10 | 0 | 1000, 1000, 1000 |
| (b) | 6 | 0 | 400 | 1000, 1000, 1000 |
| (c) | 3 | 6 | 400 | 1000, 1000, 1000 |

Turnover on Jan 3 is the traded share of V: (a) (500 + 500) / 1000 = 1.0, (b) 600 / 1000 = 0.6, (c) (300 + 300) / 1000 = 0.6.
On Jan 4 the portfolio is already on target, every order is below the dust limit and the turnover is 0.

### H10 A fractional signal value

Input: bars Jan 2, 3, 4. A: open 100, 100, 120; close 100, 120, 120. Signal A = 0.5 on every bar. Rebalance
`on_signal`, delay 1, open fills.

- Weight: n = 1, w = 0.5 / 1 = 0.5.
- Jan 3: V = 1000, target value 500, q = 500 / 100 = +5 shares, cash 500.
- No later decision. Equity: Jan 2: 1000. Jan 3: 5 * 120 + 500 = 1100. Jan 4: 5 * 120 + 500 = 1100.
- Weights of A: Jan 3: 600 / 1100 = 6/11; Jan 4: 6/11.

Cash: 1000, 500, 500. Trade: Jan 3 A +5 @ 100 (+500). Turnover: 0, 500 / 1000 = 0.5, 0.

### H11 A symbol without a price on the execution bar (deferred order)

Input: bars Jan 2, 3, 4, 5. A: open 100, 100, 120, 120; close 100, 120, 120, 120. B: open 50, NaN, 50, 50; close 50,
NaN, 50, 60 (B did not trade on Jan 3). Signals A = B = 1 on every bar. Rebalance `on_signal`, delay 1, open fills.

- Initial decision bar 0 (targets 0.5 and 0.5), execution bar 1 (Jan 3). On Jan 3 B has no price. Mark: A 100, B's
  last close 50. V = 1000. Orders: A q = 500 / 100 = +5; B q = 500 / 50 = +10 (quantity fixed now).
- A is filled: +5 @ 100, cash 500. B has no price: its order of +10 stays open (`deferred_orders` = 1).
- Jan 3 close: A 5 * 120 = 600, cash 500, B 0: equity 1100.
- Jan 4: B has the open 50 and fills its open order: +10 @ 50, cost 500, cash 500 - 500 = 0. Turnover Jan 4:
  V at the mark = 500 (cash) + 5 * 120 (A's open) = 1100, notional 500, turnover 500 / 1100 = 5/11.
  Close: A 5 * 120 = 600, B 10 * 50 = 500: equity 1100.
- Jan 5 close: A 600, B 10 * 60 = 600: equity 1200.

| | Jan 2 | Jan 3 | Jan 4 | Jan 5 |
|---|---|---|---|---|
| equity | 1000 | 1100 | 1100 | 1200 |
| cash | 1000 | 500 | 0 | 0 |
| shares A | 0 | 5 | 5 | 5 |
| shares B | 0 | 0 | 10 | 10 |
| weight A | 0 | 6/11 | 6/11 | 0.5 |
| weight B | 0 | 0 | 5/11 | 0.5 |
| turnover | 0 | 0.5 | 5/11 | 0 |

Trades: Jan 3 A +5 @ 100 (+500); Jan 4 B +10 @ 50 (+500). `deferred_orders` = 1, `unfilled_orders` = 0.

### H12 A buy that waits for the cash of a deferred sale

Input: bars Jan 2, 3, 4, 5, 8. A: open 100, 100, NaN, 100, 100; close 100, 100, NaN, 100, 100 (A did not trade on
Jan 4). B: open 50 on every bar; close 50, 50, 50, 50, 60. Signals A = 1, 0, 0, 0, 0 and B = 1 on every bar.
Rebalance `on_signal`, delay 1, open fills.

- Jan 3 (initial decision, targets 0.5 and 0.5): V = 1000, A +5 @ 100, B +10 @ 50, cash 0.
- The targets change on bar 1 (Jan 3: A 0, B 1), so bar 1 is a decision bar, executed on bar 2 (Jan 4). On Jan 4 A
  has no price. Marks: A's last close 100, B's open 50. V = 0 + 5 * 100 + 10 * 50 = 1000. Orders: A q = -5 (target
  0), B q = (1.0 * 1000 - 500) / 50 = +10.
- A cannot be sold: its order stays open (`deferred_orders` = 1). B can be bought but the cash after sells is 0, so the
  scale factor is 0 / 500 = 0 and nothing is bought: B's order of +10 stays open (`deferred_orders` = 2).
- Jan 4 close: A 5 * 100 (last close) = 500, B 10 * 50 = 500, cash 0: equity 1000. No trade, turnover 0.
- Jan 5: A has the open 100: sell 5, proceeds 500. The cash after sells is 500 and B's purchase costs 10 * 50 = 500, so it
  is filled in full: +10 @ 50. Mark V = 5 * 100 + 10 * 50 = 1000, turnover = (500 + 500) / 1000 = 1.0. B now has 20
  shares. Close: B 20 * 50 = 1000, cash 0.
- Jan 8: close of B is 60: equity 20 * 60 = 1200.

| | Jan 2 | Jan 3 | Jan 4 | Jan 5 | Jan 8 |
|---|---|---|---|---|---|
| equity | 1000 | 1000 | 1000 | 1000 | 1200 |
| cash | 1000 | 0 | 0 | 0 | 0 |
| shares A | 0 | 5 | 5 | 0 | 0 |
| shares B | 0 | 10 | 10 | 20 | 20 |
| weight A | 0 | 0.5 | 0.5 | 0 | 0 |
| weight B | 0 | 0.5 | 0.5 | 1 | 1 |
| turnover | 0 | 1.0 | 0 | 1.0 | 0 |

Trades: Jan 3 A +5 @ 100, B +10 @ 50; Jan 5 A -5 @ 100 (-500), B +10 @ 50 (+500). `deferred_orders` = 2,
`unfilled_orders` = 0.

### H13 The return of the first bar

Input: prices and signal of H1 (A: open 100, 100, 110, 121, 133.1; close 100, 110, 121, 133.1, 146.41; signal 1;
`on_signal`), first bar **Jan 3**.

- The initial decision is bar 0 (Jan 2, warm-up), executed on the first bar Jan 3 at the open 100: +10 shares.
- The output starts on Jan 3. Equity: Jan 3: 10 * 110 = 1100; Jan 4: 1210; Jan 5: 1331; Jan 8: 1464.1.
- `initial_equity` = 1000. Returns: Jan 3: 1100 / 1000 - 1 = 0.1 (the move from the fill at 100 to the close at
  110, the buy happened inside the bar); Jan 4: 1210 / 1100 - 1 = 0.1; Jan 5: 1331 / 1210 - 1 = 0.1;
  Jan 8: 1464.1 / 1331 - 1 = 0.1.

In H1 (first bar Jan 2, bought on Jan 3) the return of the first bar is 1000 / 1000 - 1 = 0.

### Sizing examples (used in `tests/test_engine_sizing.py`)

| method | signals (A, B, C) | weights (A, B, C) |
|---|---|---|
| `equal_weight` | 1, 0, 0 | 1, 0, 0 |
| `equal_weight` | 1, 1, 0 | 0.5, 0.5, 0 |
| `equal_weight` | 1, 1, 1 | 1/3 each |
| `equal_weight` | 1.0, 0.5, 0 | 0.5, 0.25, 0 |
| `equal_weight` | 0, 0, 0 | 0, 0, 0 |
| `fixed_fraction` 0.6 | 1, 1, 0 | 0.5, 0.5, 0 |
| `fixed_fraction` 0.6 | 1, 0, 0 | 0.6, 0, 0 |
| `fixed_fraction` 0.3 | 1, 1, 0 | 0.3, 0.3, 0 |
| `fixed_fraction` 0.5 | 1, 0.5, 0 | 0.5, 0.25, 0 |
| `fixed_fraction` 0.5 | 1, 1, 1 | 1/3 each (1.5 scaled to 1) |
