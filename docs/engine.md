# Engine

The engine turns prices and signals into a portfolio path: equity, cash, positions, trades and turnover. It is
deterministic Python code (the LLM never writes it, see [ADR 0002](adr/0002-deterministic-core-llm-never-writes-engine.md))
and its arithmetic is proven by hand-calculated fixtures at the end of this document. Code lives in
`src/backtest_agent/engine/`; the decisions behind it are in [ADR 0008](adr/0008-engine-semantics.md). This project is
educational and not investment advice.

The pure simulation (sizing, rebalance schedule, delay shift, cost hook and the portfolio core, driven by
`simulate_signals` on price and signal frames) is described by the semantics below. On top of it,
`run_backtest(spec, provider)` loads the data with a warm-up, validates and hashes it, calls the signal and returns a
`BacktestResult` (see "Running a spec").

| Module | Responsibility |
|---|---|
| `sizing.py` | `target_weights(signals, sizing)`: signal values to target weights |
| `schedule.py` | `decision_bars`, `execution_orders`: on which bars the portfolio is rebalanced, and the shift by `delay_bars` |
| `core.py` | `simulate(...)`: the bar loop that executes orders and returns a `Portfolio` |
| `simulation.py` | `simulate_signals(...)`: sizing, schedule, shift and core in one call |
| `costs.py` | `CostModel` hook, `NoCosts` (the only model in Phase 4) |
| `result.py` | `BacktestResult` and `WarmupInfo`: the frozen result of a run |
| `runner.py` | `run_backtest(spec, provider)`: data with warm-up, validation, hash, signal, simulation, trimming |

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
  The last close may come from a bar before the first bar: those bars are not traded or valued, but their closes are
  known (H15).

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

**Documented simplification.** A deferred order keeps its original **share quantity**, fixed on its execution bar
from the prices of that bar (H11, H12, H14). When it is filled later at another price, the portfolio is not re-sized.
With `on_signal` there is no new decision before the signal changes, so the portfolio can stay slightly off target
(a bit of cash left over, or a weight a little different from the target) until the next decision. With `daily`,
`weekly` and `monthly` the next decision corrects it. Re-sizing deferred orders is a possible later extension; ADR
0008 explains why a quantity was chosen over a weight or a notional.

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
well defined**: it is measured against the initial capital. `BacktestResult` (see "Running a spec") wraps the same
series and frames.

### Why a loop and not a vectorized calculation

The core loops over bars and uses numpy vector operations across symbols inside the loop. Cash, deferred orders and
the cash constraint depend on the path (what was bought yesterday decides what can be bought today), so the whole
run cannot be written as a few cumulative array operations without hiding the rules. A loop is the form in which each
rule above can be read and checked line by line. A few thousand bars run in milliseconds. This deviates from the word
"vectorized" in the roadmap and is recorded there.

## Running a spec

`run_backtest(spec, provider, *, allow_short_warmup=True)` in `runner.py` turns a validated `StrategySpec` into a
`BacktestResult`. The costs of the spec are **not applied** (Phase 5) and the benchmark is **not loaded** (Phases 6
and 9).

1. **Window.** Let `N = spec.warmup_rows + delay_bars`. History is fetched from `period.start` minus `2 * N + 14`
   calendar days up to `period.end` for the symbols of the universe (`provider.get_prices`). The buffer is generous
   (about 1.4 trading rows per row needed, plus two weeks for holidays); the rows are then counted, there is no
   retry.
2. **Checks.** The frame must follow the standard format with the universe symbols in order; rows after `period.end`
   are a broken provider contract (`ValueError`). `validate_prices` runs on the whole frame; errors raise
   `DataValidationError`, warnings and infos go into `BacktestResult.validation`.
3. **Hash.** `data_hash` is `hash_frame` of the frame as loaded, warm-up rows included.
4. **Signals.** The registered signal runs through `Signal.generate` (the runtime contract check) on the **whole**
   loaded frame; the history is not trimmed before, so the signals are warmed up on the first bar.
5. **Simulation.** `simulate_signals` runs with the sizing, execution, rebalance rule and initial capital of the spec
   from the **first bar**, the first bar on or after `period.start`.
6. **Trim.** Everything in the result starts on the first bar and ends on the last bar of the loaded frame (at most
   `period.end`). `signals` and `target_weights` are the values at decision time (before the shift by `delay_bars`).

### Warm-up information

`WarmupInfo` states what history the run had. The **first decision bar** is the bar that executes on the first bar
(bar `max(first - delay_bars, 0)`, "Initial decision" above); its date is `first_decision_date`.
`initial_target_weights` are the target weights (same sizing as `target_weights`) of that bar. They show what the very
first trade was based on, which the trimmed `signals` and `target_weights` of the result cannot, because they start
on the first bar. `rows_before[s]` is the number of rows of symbol `s` strictly before the first decision bar, counted
on the symbol's own trading rows (close not NaN). The run is **sufficient** when `rows_before[s] >= warmup_rows` for
every symbol; `warmup_rows = 0` is always sufficient. The other fields are `required_rows`, `delay_bars`,
`rows_needed` (`N`), `fetch_start`, `buffer_days`, `first_bar`, `first_data` (first own trading date of each symbol)
and `short_symbols`.

If the run is not sufficient it continues: `WarmupInfo.sufficient` is False, the risk flag `insufficient_warmup` is
added and an `InsufficientWarmupWarning` is issued. With `allow_short_warmup=False` the runner raises
`InsufficientHistoryError` (with the `WarmupInfo` in `.warmup`) instead.

### Result and risk flags

`BacktestResult` is a frozen dataclass (compared by field, not by `==`, because frames have no unambiguous equality)
with: `spec`, `data_hash`, `validation`, `risk_flags`, `warmup`, `costs_applied` (False), `initial_equity`, `equity`,
`cash`, `positions`, `weights`, `trades`, `turnover`, `signals`, `target_weights`, `deferred_orders`,
`unfilled_orders` and the property `returns` (as in `Portfolio`, no synthetic row is prepended). Fields are plain
Python types and standard pandas frames, so the journal (Phase 8) can serialize them. `risk_flags` are, in this
order: the flags of the spec (`same_bar_execution`, `zero_costs`), `costs_not_applied` when the spec has non-zero
costs, and `insufficient_warmup` when applicable.

### When the data does not match the period

| Case | What happens |
|---|---|
| A symbol's data starts after `period.start` | Not an error. Its signal is 0 until its first row, `validation` has an info `starts_late`, `first_data` shows the date; with `warmup_rows > 0` it is also short. |
| All data starts after `period.start` | The first bar is the first available bar. `rows_before` is 0, so a signal that needs history is insufficient. |
| No bar on or after `period.start` | `DataUnavailableError`. |
| `period.end` after the last available date | Not an error. The result ends on the last available bar, `validation` has an info `ends_early`; the equity index is the truth. |
| The provider returns fewer symbols than requested | `DataUnavailableError` naming them. Other symbols or another order: `ValueError`. |
| A requested symbol has no data at all | `no_data` validation error, `DataValidationError`. |

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

### H14 A whole run: warm-up, a decision before the first bar, a holiday (`run_backtest`)

Used in `tests/test_engine_runner.py`. A tiny provider delivers these literal prices for the symbols A and B on ten
consecutive business days. The spec: universe A, B; period 2024-01-06 (a Saturday) to 2024-01-15; test signal
`fixture_up_day`; `equal_weight`; `on_signal`; `delay_bars` 1, fills at the `open`; initial capital 1000; costs
1 / 2 / 2 bps (not applied). The signal is a test signal with `warmup_rows` 1: for each symbol on its own trading rows,
1.0 if the close is above its previous close, else 0.0 (0.0 on its first row); it is carried over days the symbol did
not trade.

| Bar | 0 Jan 2 | 1 Jan 3 | 2 Jan 4 | 3 Jan 5 | 4 Jan 8 | 5 Jan 9 | 6 Jan 10 | 7 Jan 11 | 8 Jan 12 | 9 Jan 15 |
|---|---|---|---|---|---|---|---|---|---|---|
| A open | 100 | 100 | 105 | 115 | 125 | 130 | 130 | 120 | 130 | 144 |
| A close | 100 | 100 | 110 | 120 | 130 | 130 | 120 | 120 | 140 | 150 |
| B open | 50 | 55 | 60 | 55 | 50 | 50 | 60 | NaN | 55 | 80 |
| B close | 50 | 60 | 60 | 50 | 50 | 50 | 65 | NaN | 60 | 75 |

B did not trade on Jan 11 (bar 7).

*Signals.* A: 0 (first row), 100 > 100 no: 0, 110 > 100: 1, 120 > 110: 1, 130 > 120: 1, 130 > 130 no: 0, 120 > 130 no: 0,
120 > 120 no: 0, 140 > 120: 1, 150 > 140: 1. B (own rows; Jan 11 carries the value of Jan 10): 0, 60 > 50: 1, 60 > 60
no: 0, 50 > 60 no: 0, 50 > 50 no: 0, 50 > 50 no: 0, 65 > 50: 1, Jan 11 carried: 1, 60 > 65 no: 0, 75 > 60: 1.

| Bar | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|---|
| signal A | 0 | 0 | 1 | 1 | 1 | 0 | 0 | 0 | 1 | 1 |
| signal B | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 1 |
| target A | 0 | 0 | 1 | 1 | 1 | 0 | 0 | 0 | 1 | 0.5 |
| target B | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 0.5 |

*Window and first bar.* The signal needs 1 row and the delay is 1 bar, so `N = 2` and the buffer is
`2 * 2 + 14 = 18` days: the fetch starts on 2024-01-06 minus 18 days = 2023-12-19. The provider has data from Jan 2,
so bars 0 to 3 are warm-up. The first bar is the first bar on or after Jan 6: **Jan 8 (bar 4)**.

*Decisions.* `on_signal`: the target changes on bars 1 (to B), 2 (to A), 5 (to cash), 6 (to B), 8 (to A) and 9 (to
both). Bars 1 and 2 would execute on bars 2 and 3, before the first bar, so they are dropped. The initial decision is
bar 3 (Jan 5), the bar that executes on the first bar (`4 - 1`); its target is A 1.0, B 0 (signals A 1, B 0, `n = 1`).
So `first_decision_date` = 2024-01-05 and `initial_target_weights` = {A: 1.0, B: 0.0}. The decision of bar 9 would
execute on bar 10, which does not exist, and is dropped. Executions: bar 4 with the targets of bar 3, bar 6 with
those of bar 5, bar 7 with those of bar 6 and bar 9 with those of bar 8.

*Warm-up information.* Rows before the first decision bar (bars 0 to 2): A 3, B 3; `warmup_rows` is 1, so
`sufficient` is True and no symbol is short. `first_data`: A and B on 2024-01-02. `rows_needed` 2, `buffer_days` 18.

*Bars.*

- Jan 8 (bar 4): target A 1.0. V = 1000 (cash). A: q = 1000 / 125 = +8 shares, cost 1000, cash 0. B: no order. Turnover
  1000 / 1000 = 1.0. Close: 8 * 130 = 1040. The return of the first bar is 1040 / 1000 - 1 = 0.04.
- Jan 9 (bar 5): no execution. Close: 8 * 130 = 1040.
- Jan 10 (bar 6): target cash. Mark: A open 130, V = 8 * 130 = 1040. A: q = -8 (target 0), proceeds 1040, cash 1040.
  Turnover 1040 / 1040 = 1.0. Equity 1040.
- Jan 11 (bar 7): target B 1.0. B has no price. Mark: A none held, B's last close 65, V = 1040 (cash). B: q =
  (1.0 * 1040 - 0) / 65 = +16 shares, fixed now. B cannot be filled: the order stays open (`deferred_orders` = 1).
  Nothing is traded, turnover 0, equity 1040, cash 1040.
- Jan 12 (bar 8): no new execution (the target did not change on bar 7). B has the open 55 and fills the open order: +16
  at 55, cost 880, cash 1040 - 880 = 160. Mark V = 1040 (B had no shares yet), turnover 880 / 1040 = 11/13. The
  quantity was fixed on Jan 11, so the portfolio is not re-sized: 160 stays in cash (the simplification above). Close:
  16 * 60 = 960, equity 160 + 960 = 1120. Weight of B 960 / 1120 = 6/7.
- Jan 15 (bar 9): target A 1.0 (from bar 8). Marks: A open 144, B open 80. V = 160 + 16 * 80 = 1440. A: q =
  (1440 - 0) / 144 = +10; B: q = -16 (target 0). Sells first: proceeds 16 * 80 = 1280, cash 1440; the buy costs
  10 * 144 = 1440, filled in full, cash 0. Turnover (1280 + 1440) / 1440 = 17/9. Close: 10 * 150 = 1500.
  `unfilled_orders` = 0.

| | Jan 8 | Jan 9 | Jan 10 | Jan 11 | Jan 12 | Jan 15 |
|---|---|---|---|---|---|---|
| equity | 1040 | 1040 | 1040 | 1040 | 1120 | 1500 |
| cash | 0 | 0 | 1040 | 1040 | 160 | 0 |
| shares A | 8 | 8 | 0 | 0 | 0 | 10 |
| shares B | 0 | 0 | 0 | 0 | 16 | 0 |
| weight A | 1 | 1 | 0 | 0 | 0 | 1 |
| weight B | 0 | 0 | 0 | 0 | 6/7 | 0 |
| turnover | 1.0 | 0 | 1.0 | 0 | 11/13 | 17/9 |
| signal A, B | 1, 0 | 0, 0 | 0, 1 | 0, 1 | 1, 0 | 1, 1 |
| target A, B | 1, 0 | 0, 0 | 0, 1 | 0, 1 | 1, 0 | 0.5, 0.5 |

Trades: Jan 8 A +8 @ 125 (+1000); Jan 10 A -8 @ 130 (-1040); Jan 12 B +16 @ 55 (+880); Jan 15 A +10 @ 144 (+1440),
B -16 @ 80 (-1280). `deferred_orders` = 1. Returns: 0.04, 0, 0, 0, 1120 / 1040 - 1 = 1/13, 1500 / 1120 - 1 = 19/56.
Risk flags: only `costs_not_applied` (the costs are non-zero, the delay is 1). `costs_applied` is False.

### H15 A symbol without a price on the first bar (its last close is from the warm-up)

Input: bars Jan 2, 3, 4, 5. A: open 100, 100, 100, 120; close 100, 100, 110, 120. B: open 50, 50, NaN, 50; close 50, 50,
NaN, 70 (B did not trade on Jan 4). Signals A = B = 1 on every bar. Rebalance `on_signal`, delay 1, open fills, first bar
**Jan 4**.

- The initial decision is bar 1 (Jan 3, warm-up, targets 0.5 and 0.5), executed on the first bar Jan 4. B has no price
  there; its last close is the close of Jan 3, 50. Mark: A 100 (open), B 50. V = 1000. Orders: A q = 500 / 100 = +5; B
  q = 500 / 50 = +10 (quantity fixed now).
- A is filled: +5 @ 100, cash 500. B has no price: its order stays open (`deferred_orders` = 1). Jan 4 close: A 5 * 110 =
  550, cash 500, equity 1050. Turnover 500 / 1000 = 0.5.
- Jan 5: B has the open 50 and fills: +10 @ 50, cost 500, cash 0. V at the mark = 500 + 5 * 120 = 1100, turnover
  500 / 1100 = 5/11. Close: A 5 * 120 = 600, B 10 * 70 = 700, equity 1300.

| | Jan 4 | Jan 5 |
|---|---|---|
| equity | 1050 | 1300 |
| cash | 500 | 0 |
| shares A | 5 | 5 |
| shares B | 0 | 10 |
| weight A | 550 / 1050 = 11/21 | 600 / 1300 = 6/13 |
| weight B | 0 | 700 / 1300 = 7/13 |
| turnover | 0.5 | 5/11 |

Trades: Jan 4 A +5 @ 100 (+500); Jan 5 B +10 @ 50 (+500). `deferred_orders` = 1, `unfilled_orders` = 0. Without the
closes of the warm-up bars B would have no mark on Jan 4 and the order could not be sized.

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
