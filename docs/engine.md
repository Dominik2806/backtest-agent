# Engine

The engine turns prices and signals into a portfolio path: equity, cash, positions, trades and turnover. It is
deterministic Python code (the LLM never writes it, see [ADR 0002](adr/0002-deterministic-core-llm-never-writes-engine.md))
and its arithmetic is proven by hand-calculated fixtures at the end of this document. Code lives in
`src/backtest_agent/engine/`; the decisions behind it are in [ADR 0008](adr/0008-engine-semantics.md). This project is
educational and not investment advice.

The pure simulation (sizing, rebalance schedule, delay shift, costs and the portfolio core, driven by
`simulate_signals` on price and signal frames) is described by the semantics below. On top of it,
`run_backtest(spec, provider)` loads the data with a warm-up, validates and hashes it, calls the signal, deducts the
costs of the spec and returns a `BacktestResult` with the net and the gross result (see "Running a spec").

| Module | Responsibility |
|---|---|
| `sizing.py` | `target_weights(signals, sizing)`: signal values to target weights |
| `schedule.py` | `decision_bars`, `execution_orders`: on which bars the portfolio is rebalanced, and the shift by `delay_bars` |
| `core.py` | `simulate(...)`: the bar loop that executes orders and returns a `Portfolio` |
| `simulation.py` | `simulate_signals(...)`: sizing, schedule, shift and core in one call |
| `costs.py` | `CostModel` hook, `NoCosts` and `BpsCosts`, the cost model of the spec (Phase 5) |
| `result.py` | `BacktestResult` and `WarmupInfo`: the frozen result of a run |
| `runner.py` | `run_backtest(spec, provider)`: data with warm-up, validation, hash, signal, simulation with costs, gross twin, trimming |

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
- Costs are cash fees on the bar of the fill (see "Costs"). The portfolio core applies them when it is given a cost
  model, and `run_backtest` gives it the costs of the spec (`BpsCosts.from_spec`), unless it is called with
  `apply_costs=False`.
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
   cash **net of their costs**. Buys are filled in full if the cash after the sells covers all of them **including
   their costs**. Otherwise **all buys are scaled down by the same factor** `f`, so cash never becomes negative.
   The exact rule for `f` and for the costs is in "Costs".
4. **Carry.** An order whose symbol has no price on e stays open ("deferred") and is filled on the next bar on which
   the symbol has a price, with the **same quantity** at that bar's price. The part of a scaled-down buy that cash
   could not cover **even if trading were free** stays open the same way (unless it is dust), also when nothing of it
   was filled. The part that only the costs kept from being bought is dropped (see "Costs"). Both kinds of open
   order (no price, or not enough cash) count in `deferred_orders` once, when they are first carried past their
   execution bar. Orders still open after the last bar count in `unfilled_orders`.
5. **Close.** Last closes are updated from the close of e. Equity is cash plus shares times last close. Weights
   are `shares * last close / equity`.

Sells before buys on a bar means (net) proceeds fund purchases of the same bar. If a sale is deferred (no price) the
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
complete switch from one asset to another gives 2.0. It is 0.0 on bars without trades. The metrics of Phase 6 label
both figures: the annualized two-sided turnover and the one-sided one, which is half of it (see "Turnover" in
[metrics.md](metrics.md)).

### Costs

`CostModel.cost(symbol, notional)` returns the cost in currency of one trade (`notional` is the absolute traded value,
the result must be finite and 0 or more). A **trade** is one fill: one row of the `trades` table, one symbol on one
bar. The core deducts the costs of all trades of a bar from cash on that bar. `NoCosts` returns 0.0. The model of the
spec is `BpsCosts`, built from the `costs` block with `BpsCosts.from_spec`.

**Cost of one fill** with absolute notional `N > 0` (shares filled times the execution price of the bar on which
the fill happens):

```text
commission = max(commission_bps / 10000 * N, min_commission)
spread     = spread_bps   / 10000 * N      # spread_bps is the half-spread, it is not halved again
slippage   = slippage_bps / 10000 * N
cost       = commission + spread + slippage
```

- Buys and sells alike. A deferred order is charged on the price of the bar on which it fills; a scaled-down buy is
  charged on the part that was filled. `min_commission` (account currency, default 0 = none) is charged per trade and
  applies to the commission only; with `commission_bps` 0 it is a flat fee per trade.
- The costs are **cash fees**. `price` in the `trades` table stays the execution price (open or close) and the fee
  goes into the column `cost`; `Portfolio.costs` holds the fees per bar and `Portfolio.total_costs` their sum. Turnover
  is not changed by costs. Why a fee and not an adverse fill price: [ADR 0010](adr/0010-cost-model.md).
- **A sale pays its fee out of its proceeds**, so the fee of a sale is capped at the notional of the sale (a sale
  that is smaller than the minimum commission brings in nothing, never a negative amount).
- The core does not trust a model: a negative, NaN or infinite cost, or a cash balance that would end up negative,
  raises `EngineInvariantError`. Fees can use up a whole portfolio; with equity 0 the weights and the turnover are 0.

**Funding rule (step 3).** On a bar, let `cash` be the cash before the fills, `S` the notional of the sells that can
be filled, `fee_sells` their fees (each capped as above) and `B` the total notional of the buys that can be filled.

1. `f0 = 1` if `B <= cash + S`, else `f0 = max(cash + S, 0) / B`. This is the share of the buys that cash can pay for
   if trading were free.
2. The budget for the buys is `cash + S - fee_sells`. The affordable share `f` is the largest `f <= f0` with
   `sum_i (f * N_i + fee(f * N_i)) <= budget`, where `N_i` are the notionals of the buys and `fee` is the cost of the
   model. If no fee is charged at all (free trading), `f = f0` exactly. If `f0` itself is affordable, `f = f0`. Otherwise
   `f` is found by bisection on `[0, f0]` (64 halvings) with the cost function of the model, and the affordable end is
   taken, so cash cannot become negative. `f = 0` if not even the smallest fill can pay its fee: nothing is bought.
   All buys use the same `f`. The bisection leaves a residual of the order of the floating point resolution (cash
   of about 1e-13 instead of exactly 0), which is why the cost fixtures are compared with a relative and absolute
   tolerance of **1e-9**, while the zero-cost behaviour of Phase 4 is compared exactly.
3. The buys are filled for `f` of their quantity. **Remainder rule.** Of each buy the part `f0` is settled (the
   part `f` is filled, the part `f0 - f` is dropped because only the fees kept it from being bought) and only the part
   `1 - f0` stays open. That part exists without fees: cash that is still to come (a sale that is deferred for lack of a
   price, or a deferred quantity that became more expensive). Without costs `f = f0`, so the behaviour is exactly
   that of Phase 4.

*Zero costs.* With a model that charges nothing (`NoCosts`, or `BpsCosts` with all four numbers 0) every frame and
the trades are bit-identical to the behaviour of Phase 4; the tests compare them exactly, without tolerance.

*Consequences.* A rebalance to a fully invested target can never be reached exactly with fees (the buys need their
notional plus their fees): it ends with `f < 1` and cash of about 0, and the remainder is dropped, so it does not
inflate `deferred_orders` and `unfilled_orders`. These two counters count only orders that wait for a price or for
cash that exists without fees (H20, H21). Orders are sized on the portfolio value `V` before costs, so after a
rebalance the portfolio is slightly under its target weights by the amount of the fees. A minimum fee can make the engine sell for a buy that then cannot be paid (H19b, Jan 4): the fee of the sale is lost and the portfolio ends slightly off target. This follows the rules and is not an error.

**Gross and net.** The *net* result is the run with costs. The *gross* result is a twin run of the same simulation with
all costs at zero (same data, same signals, same orders). Costs compound (a fee paid today is not invested tomorrow), so
adding the total costs back to the net equity would not give the gross path. How `run_backtest` runs the twin and
reports gross final equity, the cost drag and the share of the gross return that the costs ate is specified in "Gross
and net" under "Running a spec" ([ADR 0011](adr/0011-gross-net-result.md)).

### Output of the core

`Portfolio` (frozen) has, per bar: `equity`, `cash`, `positions` (shares per symbol), `weights` (end of bar),
`turnover`, `costs` (fees paid on the bar); the `trades` table (`date`, `symbol`, `shares` signed, `price`, `notional`
signed, `cost`, ordered by bar then by symbol order); `initial_equity` (the initial capital); the counters
`deferred_orders` and `unfilled_orders`; and the property `total_costs`.
`returns` is `equity / equity.shift(1, fill_value=initial_equity) - 1`, so the **return of the first bar is
well defined**: it is measured against the initial capital. After a portfolio ruined by fees (equity 0) the return of
every later bar is **0.0**, not 0/0 = NaN; the bar that ruined it has the return -1 (H23c: `[0, 0, -0.5, -1, 0]`). `BacktestResult` (see "Running a spec") wraps the same
series and frames.

### Why a loop and not a vectorized calculation

The core loops over bars and uses numpy vector operations across symbols inside the loop. Cash, deferred orders and
the cash constraint depend on the path (what was bought yesterday decides what can be bought today), so the whole
run cannot be written as a few cumulative array operations without hiding the rules. A loop is the form in which each
rule above can be read and checked line by line. A few thousand bars run in milliseconds. This deviates from the word
"vectorized" in the roadmap and is recorded there.

## Running a spec

`run_backtest(spec, provider, *, allow_short_warmup=True, apply_costs=True)` in `runner.py` turns a validated
`StrategySpec` into a `BacktestResult`. The costs of the spec are deducted (`apply_costs=False` switches them off, see
"Result and risk flags") and the benchmark is **not loaded** (Phases 6 and 9).

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
   from the **first bar**, the first bar on or after `period.start`, and with the cost model `BpsCosts.from_spec(
   spec.costs)` (`NoCosts` if `apply_costs=False`). This is the **net** run; positions, trades, turnover, costs and
   the order counters of the result are its.
   **Gross twin.** If costs are applied and the spec has a non-zero cost number (`spec.costs.is_zero` is False), the
   same call is made a second time with `NoCosts()`: the same `opens`, `closes` and `signals` frames (loaded and
   computed once above), the same sizing, execution, rebalance rule, initial capital and first bar, hence the same
   decisions and orders. Only its `equity` is kept, as `gross_equity`. In every other case nothing is simulated
   twice: `gross_equity` is an independent copy of `equity` (`.copy()`, so changing one never changes the other), named
   `gross_equity`.
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
with: `spec`, `data_hash`, `validation`, `risk_flags`, `warmup`, `costs_applied`, `initial_equity`, `equity`, `cash`,
`positions`, `weights`, `trades` (with the fee in `cost`), `turnover`, `costs`, `gross_equity`, `signals`,
`target_weights`, `deferred_orders`, `unfilled_orders`, and the properties `returns` (as in `Portfolio`, no synthetic
row is prepended) and the scalars of "Gross and net" below. Everything except `gross_equity` is the **net** run. Fields
are plain Python types and standard pandas frames and series, so the journal (Phase 8) can serialize them.

`costs_applied` is True if a cost model was applied, also one that charges nothing (a spec with all four cost numbers 0),
and False only for `run_backtest(..., apply_costs=False)`. `risk_flags` are, in this order: the flags of the spec
(`same_bar_execution`, `zero_costs`), `costs_not_applied`, and `insufficient_warmup` when applicable. The flags about
costs are:

| `apply_costs` | spec cost numbers | `costs_applied` | flag about costs |
|---|---|---|---|
| True | all 0 | True | `zero_costs` |
| True | any non-zero | True | none |
| False | all 0 | False | `zero_costs` |
| False | any non-zero | False | `costs_not_applied` |

`costs_not_applied` is never emitted in a normal run. It exists so that the opt-out `apply_costs=False` (used for the
cost-free regression fixtures and for tests of exact no-cost identities) cannot go unnoticed in a result that is read
later: the result overstates what trading would return.

### Gross and net

The result is the **net** run. `gross_equity` is the equity of the twin run without costs (see step 5 of "Running a
spec"; it is the same values as `equity` if no cost was charged). The scalars are **read-only properties** of the
result, computed from `costs`, `gross_equity`, `equity` and `initial_equity`, so they cannot disagree with the series
(a journal has to serialize them explicitly). The return of a run is its final equity divided by `initial_equity`
minus 1; it is not a compounded or annualized figure.

| Property | Definition |
|---|---|
| `total_costs` | `float(costs.sum())`, all fees paid |
| `net_return` | `equity[-1] / initial_equity - 1` |
| `gross_final_equity` | `gross_equity[-1]` |
| `gross_return` | `gross_final_equity / initial_equity - 1` |
| `cost_drag` | `gross_return - net_return` |
| `cost_share` | `cost_drag / gross_return`, **None** if `gross_return <= 0` |

*Edge cases.*

- **No cost charged** (`apply_costs=False`, or a spec with all four numbers 0, where `costs_applied` is still True when
  `apply_costs` is True): `costs` is 0.0 on every bar, `total_costs` is 0.0, no twin is run, `gross_equity` is a copy of
  `equity`, `cost_drag` is exactly 0.0 (a float minus the same float) and `cost_share` is 0.0 if the return is positive,
  else None. The result is bit-identical to the same spec with costs `(0, 0, 0)`.
- **Gross return zero or negative:** `cost_share` is None, because the share of a loss is not defined. `cost_drag` is
  still defined (H23b).
- **No trades:** the twin is still run if the spec has costs, and is identical: `total_costs` 0.0, `cost_drag` 0.0.
- **A portfolio ruined by fees** (equity 0): `net_return` is -1. If the gross return is positive, `cost_drag` is
  `gross_return + 1` and `cost_share` is above 1. Weights and turnover are 0, never NaN.
- **A period with warm-up:** net and gross both start on the first bar with `initial_equity` as the starting value.
  The warm-up bars are loaded and used for the signals once; the twin uses the same decisions, including the
  initial decision on the bar before the first bar. The warm-up information, the validation, the warning and the flag
  `insufficient_warmup` belong to the run, not to a simulation, and appear once.
- **`cost_drag` is not guaranteed to be 0 or more, and `cost_share` is not guaranteed to be 1 or less.** Costs change
  the path, so the two runs are not the same trades at different prices: a fee can block a bad purchase or leave cash
  in a falling market, so the net run can end above the gross run; and with a negative net return and a positive gross
  return the costs have eaten more than the whole gross return, so the share exceeds 1. The share is not clamped. Only
  identities that are exact are tested: for buy and hold on a price path without holidays, the net equity is the gross
  equity divided by `1 + r` from the day of the purchase (`r` the combined rate, no minimum commission).

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
`tests/test_engine_hand_calculated.py` (H1 to H13), `tests/test_engine_runner.py` (H14), `tests/test_engine_warmup_marks.py`
(H15), `tests/test_engine_costs_hand_calculated.py` (H16 to H22 and H19c) and `tests/test_engine_runner_costs.py` (H23, H23b, H23c) contain
the **expected values as literals taken from this document**; they never compute an expected value with engine code or
with a helper that mirrors it. H1 to H15 run without costs and are compared with a relative tolerance of 1e-12; the
cost fixtures H16 to H22 are compared with a relative and absolute tolerance of 1e-9 (the bisection of the funding rule
leaves a residual at the floating point resolution). Every fixture uses capital 1000. "Day"
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
1 / 2 / 2 bps, which this fixture does not deduct: it is the zero-cost regression of the runner and runs with
`apply_costs=False`. The signal is a test signal with `warmup_rows` 1: for each symbol on its own trading rows,
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
Risk flags: only `costs_not_applied` (`apply_costs=False` with non-zero costs, the delay is 1). `costs_applied` is False.
`gross_equity` equals `equity`, `total_costs` is 0.0 and `cost_drag` is 0.0.

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

### H16 Commission only

Input: bars Jan 2, 3, 4, 5. A: open = close = 100, 100, 120, 120. Signal A = 1, 1, 0, 0. `fixed_fraction` 0.5, `on_signal`,
delay 1, open fills. Costs: commission 100 bps (1 percent), nothing else.

- Initial decision bar 0 (target 0.5), executed on Jan 3 at 100: V = 1000, q = 500 / 100 = +5. Cost of the fill:
  0.01 * 500 = 5. The cash covers it (500 + 5 <= 1000), so `f = 1`. Cash 1000 - 500 - 5 = 495. Close: 5 * 100 = 500,
  equity 995.
- Jan 4: no execution. Close 120: 5 * 120 + 495 = 1095.
- The signal turns 0 on bar 2 (Jan 4), executed on Jan 5 at 120: V = 495 + 600 = 1095, q = -5, notional 600, cost
  0.01 * 600 = 6, cash 495 + 600 - 6 = 1089. Turnover 600 / 1095 = 40/73.

| | Jan 2 | Jan 3 | Jan 4 | Jan 5 |
|---|---|---|---|---|
| equity | 1000 | 995 | 1095 | 1089 |
| cash | 1000 | 495 | 495 | 1089 |
| shares A | 0 | 5 | 5 | 0 |
| turnover | 0 | 0.5 | 0 | 40/73 |
| costs | 0 | 5 | 0 | 6 |

Trades: Jan 3 A +5 @ 100 (+500, cost 5); Jan 5 A -5 @ 120 (-600, cost 6). Total costs 11.

### H17 Spread and slippage

Input: the world of H16. Costs: commission 0, spread 20 bps, slippage 30 bps. The spread is the half-spread and is
charged as written.

- Jan 3: notional 500, spread 0.002 * 500 = 1.0, slippage 0.003 * 500 = 1.5, cost 2.5. Cash 1000 - 500 - 2.5 = 497.5,
  equity 997.5.
- Jan 4: 600 + 497.5 = 1097.5.
- Jan 5: V = 1097.5, sale of 600: spread 1.2, slippage 1.8, cost 3.0. Cash 497.5 + 600 - 3 = 1094.5. Turnover
  600 / 1097.5 = 240/439.

| | Jan 2 | Jan 3 | Jan 4 | Jan 5 |
|---|---|---|---|---|
| equity | 1000 | 997.5 | 1097.5 | 1094.5 |
| cash | 1000 | 497.5 | 497.5 | 1094.5 |
| costs | 0 | 2.5 | 0 | 3.0 |

Trades: Jan 3 A +5 @ 100 (cost 2.5); Jan 5 A -5 @ 120 (cost 3.0).

### H18 Minimum commission

Input: the world of H16. Costs: commission 50 bps, spread 20 bps, `min_commission` 2.8.

- Jan 3, notional 500: commission max(0.005 * 500, 2.8) = max(2.5, 2.8) = 2.8 (the minimum binds), spread 1.0, cost
  3.8. Cash 1000 - 500 - 3.8 = 496.2, equity 996.2.
- Jan 4: 600 + 496.2 = 1096.2.
- Jan 5, notional 600: commission max(3.0, 2.8) = 3.0 (the minimum does not bind), spread 1.2, cost 4.2. Cash
  496.2 + 600 - 4.2 = 1092.0. Turnover 600 / 1096.2.

| | Jan 2 | Jan 3 | Jan 4 | Jan 5 |
|---|---|---|---|---|
| equity | 1000 | 996.2 | 1096.2 | 1092.0 |
| cash | 1000 | 496.2 | 496.2 | 1092.0 |
| costs | 0 | 3.8 | 0 | 4.2 |

### H19 A fee never exceeds the trade, and a buy that cannot pay its fee

*(a) The fee of a sale is capped at its proceeds.* Input: bars Jan 2, 3, 4. A: open = close = 100, 100, 101. Signal A = 1.
`fixed_fraction` 0.5, `daily`, delay 1, open fills. Costs: `min_commission` 10, everything else 0.

- Jan 3: V = 1000, q = +5, notional 500, cost max(0, 10) = 10, cash 490. Close 500 + 490 = 990.
- Jan 4 (open 101): V = 490 + 5 * 101 = 995, target 497.5, held 505, q = -7.5 / 101, notional 7.5. The minimum is 10,
  but the fee of a sale is capped at the proceeds: cost min(10, 7.5) = 7.5. Cash 490 + 7.5 - 7.5 = 490. Turnover
  7.5 / 995 = 3/398. Close: (5 - 7.5/101) * 101 = 497.5, equity 987.5.

Equity 1000, 990, 987.5. Cash 1000, 490, 490. Costs 0, 10, 7.5. Trades: Jan 3 A +5 @ 100 (cost 10); Jan 4 A -7.5/101
@ 101 (-7.5, cost 7.5).

*(b) A buy that cannot pay its minimum fee.* Input: bars Jan 2, 3, 4. A: open = close = 100, 100, 105; B: open = close = 50.
Signals A = B = 1. `equal_weight`, `daily`, delay 1, open fills. Costs: `min_commission` 10, everything else 0.

- Jan 3: V = 1000, A q = +5 (500), B q = +10 (500). `f0 = 1`. The two fees are 10 each whatever the size, so the
  outlay `f * 1000 + 20` equals the cash 1000 at `f = 0.98`. A +4.9 (490), B +9.8 (490), each with cost 10, cash 0.
  The remainder is dropped (`f0 = 1`): nothing is pending. Close: A 490, B 490, equity 980. Turnover 980 / 1000 = 0.98.
- Jan 4 (A open 105): V = 4.9 * 105 + 9.8 * 50 = 514.5 + 490 = 1004.5, targets 502.25 each. A: q = -12.25 / 105 = -7/60
  (notional 12.25); B: q = +12.25 / 50 = +0.245 (notional 12.25). The sale costs min(10, 12.25) = 10, so its net
  proceeds are 2.25. `f0 = 1` (gross cash 12.25 covers the buy), but the budget is 2.25 and even the smallest buy
  pays a fee of 10: `f = 0`. Nothing is bought and, since `f0 = 1`, nothing stays open. Cash = 12.25 - 10 = 2.25.
  Close: A (4.9 - 7/60) * 105 = 502.25, B 490, cash 2.25: equity 994.5. Turnover 12.25 / 1004.5.

Equity 1000, 980, 994.5. Cash 1000, 0, 2.25. Costs 0, 20, 10. Trades: Jan 3 A +4.9 @ 100 (cost 10), B +9.8 @ 50 (cost
10); Jan 4 A -7/60 @ 105 (-12.25, cost 10). `deferred_orders` = 0, `unfilled_orders` = 0.

### H19c Fees use up the whole portfolio

Input: bars Jan 2, 3, 4, 5. A: open = close = 100. Signal A = 1, 0, 0, 0. `fixed_fraction` 0.5, `on_signal`, delay 1, open
fills. Costs: `min_commission` 500, everything else 0.

- Jan 3 (initial decision, target 0.5): V = 1000, q = +5, notional 500, fee 500. The outlay 500 + 500 equals the cash,
  so `f = 1` and cash = 0. Close 5 * 100 = 500, equity 500. Turnover 500 / 1000 = 0.5.
- Jan 4 (the target changed to 0 on bar 1): V = 500, q = -5, notional 500, fee min(500, 500) = 500, proceeds 0, cash 0,
  equity 0. Turnover 500 / 500 = 1.0. The weights are 0.
- Jan 5: no order, V = 0, equity 0, turnover 0. A portfolio worth nothing has weights and turnover 0, never NaN.

Equity 1000, 500, 0, 0. Cash 1000, 0, 0, 0. Costs 0, 500, 500, 0. Shares A 0, 5, 0, 0. Turnover 0, 0.5, 1.0, 0. Weights
of A 0, 1, 0, 0. Trades: Jan 3 A +5 @ 100 (+500, cost 500); Jan 4 A -5 @ 100 (-500, cost 500). `deferred_orders` = 0,
`unfilled_orders` = 0.

### H20 A full rebalance with a 25 percent cost rate (the fee scale-down and the dropped remainder)

The rate is absurd on purpose: with a total rate `r = 0.25` (commission 1000, spread 1000, slippage 500 bps) the shares
are round. Input: bars Jan 2, 3, 4, 5. A: open = close = 100; B: open = close = 50. Signals A = 1, 0, 0, 0 and
B = 0, 1, 1, 1. `equal_weight`, `on_signal`, delay 1, open fills.

- Jan 3 (initial decision, target A 1): V = 1000, q = +10, notional 1000. `f0 = 1`, the outlay would be 1000 * 1.25 =
  1250 > 1000, so `f = 1000 / 1250 = 0.8`: A +8, notional 800, cost 0.25 * 800 = 200 (commission 80, spread 80,
  slippage 40). Cash 1000 - 800 - 200 = 0. The remaining 2 shares are dropped (`f0 = 1`), nothing is pending. Close
  8 * 100 = 800. Turnover 800 / 1000 = 0.8.
- Jan 4 (the target changes to B 1): V = 800, A q = -8, B q = 800 / 50 = +16. Sale: notional 800, cost 200, net 600.
  `f0 = 1` (gross cash 800 covers the buy of 800), budget 600, outlay at `f`: `f * 800 * 1.25 = 600` gives
  `f = 0.6`: B +9.6, notional 480, cost 120. Cash 0 + 800 - 200 - 480 - 120 = 0. The remaining 6.4 shares are dropped.
  Close 9.6 * 50 = 480. Turnover (800 + 480) / 800 = 1.6.
- Jan 5: no decision, equity 480.

| | Jan 2 | Jan 3 | Jan 4 | Jan 5 |
|---|---|---|---|---|
| equity | 1000 | 800 | 480 | 480 |
| cash | 1000 | 0 | 0 | 0 |
| shares A | 0 | 8 | 0 | 0 |
| shares B | 0 | 0 | 9.6 | 9.6 |
| turnover | 0 | 0.8 | 1.6 | 0 |
| costs | 0 | 200 | 320 | 0 |

Trades: Jan 3 A +8 @ 100 (+800, cost 200); Jan 4 A -8 @ 100 (-800, cost 200), B +9.6 @ 50 (+480, cost 120).
`deferred_orders` = 0, `unfilled_orders` = 0. (With the remainder rule of Phase 4 the 2 and the 6.4 shares would stay
pending and be counted.)

### H21 A deferred sale together with costs (the situation of H12)

Rate 25 percent as in H20. Input: bars Jan 2, 3, 4, 5, 8. A: open = close = 100, 100, NaN, 100, 100 (A did not trade on
Jan 4). B: open 50 on every bar; close 50, 50, 50, 50, 60. Signals A = 1, 0, 0, 0, 0 and B = 1 on every bar.
`equal_weight`, `on_signal`, delay 1, open fills.

- Jan 3 (initial decision, targets 0.5 and 0.5): V = 1000, A +5 (500), B +10 (500). `f0 = 1`, outlay 1250, `f = 0.8`:
  A +4 (notional 400, cost 100), B +8 (400, cost 100), cash 0, remainders dropped. Close 400 + 400 = 800. Turnover 0.8.
- The targets change on bar 1 (A 0, B 1), executed on Jan 4. A has no price. Marks: A's last close 100, B's open 50,
  V = 4 * 100 + 8 * 50 = 800. Orders: A q = -4, B q = (800 - 400) / 50 = +8. A cannot be sold (deferred), B can be
  bought but the cash is 0: `f0 = 0`, so `f = 0` and nothing is bought. Because `f0 = 0` the whole order of B stays open
  (cash can still come in): `deferred_orders` = 2. Close: 400 + 400 = 800, no trade, turnover 0.
- Jan 5: A has the open 100. Sell 4: notional 400, cost 100, net 300. B +8: notional 400. Gross cash 400 covers it,
  `f0 = 1`; the budget is 300 and the outlay at `f` is `f * 400 * 1.25`, so `f = 0.6`: B +4.8, notional 240, cost 60. Cash
  0 + 400 - 100 - 240 - 60 = 0. The 3.2 shares that only the fees kept from being bought are dropped:
  `unfilled_orders` = 0. Mark V = 800 (4 * 100 + 8 * 50), turnover (400 + 240) / 800 = 0.8. Close: B 12.8 * 50 = 640.
- Jan 8: B closes at 60: 12.8 * 60 = 768.

| | Jan 2 | Jan 3 | Jan 4 | Jan 5 | Jan 8 |
|---|---|---|---|---|---|
| equity | 1000 | 800 | 800 | 640 | 768 |
| cash | 1000 | 0 | 0 | 0 | 0 |
| shares A | 0 | 4 | 4 | 0 | 0 |
| shares B | 0 | 8 | 8 | 12.8 | 12.8 |
| turnover | 0 | 0.8 | 0 | 0.8 | 0 |
| costs | 0 | 200 | 0 | 160 | 0 |

Trades: Jan 3 A +4 @ 100 (cost 100), B +8 @ 50 (cost 100); Jan 5 A -4 @ 100 (-400, cost 100), B +4.8 @ 50 (+240, cost
60). `deferred_orders` = 2, `unfilled_orders` = 0.

### H22 Two assets with daily rebalancing and costs

Rate 25 percent. Input: the prices of H5 (bars Jan 2, 3, 4, 5; A open 100, 100, 125, 150, close 100, 120, 150, 150; B 50
throughout). Signals A = B = 1, `equal_weight`, `daily`, delay 1, open fills.

- Jan 3: V = 1000, A +5, B +10 (500 each). `f = 0.8`: A +4 (400, cost 100), B +8 (400, cost 100), cash 0. Close
  A 4 * 120 = 480, B 8 * 50 = 400: equity 880. Turnover 0.8.
- Jan 4 (A open 125): V = 4 * 125 + 8 * 50 = 900, targets 450 each. A: held 500, q = -50 / 125 = -0.4 (notional 50, cost
  12.5, net 37.5). B: held 400, q = +50 / 50 = +1. `f0 = 1`, outlay at `f` is `f * 50 * 1.25`, budget 37.5, so `f = 0.6`:
  B +0.6 (notional 30, cost 7.5). Cash 0 + 50 - 12.5 - 30 - 7.5 = 0. Shares A 3.6, B 8.6. Close: A 3.6 * 150 = 540, B
  8.6 * 50 = 430: equity 970. Turnover 80 / 900 = 4/45. Costs 12.5 + 7.5 = 20.
- Jan 5 (A open 150): V = 540 + 430 = 970, targets 485. A: held 540, q = -55 / 150 = -11/30 (notional 55, cost 13.75,
  net 41.25). B: held 430, q = +55 / 50 = +1.1. `f = 41.25 / 68.75 = 0.6`: B +0.66 (notional 33, cost 8.25). Cash 0.
  Shares A 3.6 - 11/30 = 97/30, B 9.26. Close: A (97/30) * 150 = 485, B 9.26 * 50 = 463: equity 948. Turnover
  88 / 970 = 44/485. Costs 13.75 + 8.25 = 22.

| | Jan 2 | Jan 3 | Jan 4 | Jan 5 |
|---|---|---|---|---|
| equity | 1000 | 880 | 970 | 948 |
| cash | 1000 | 0 | 0 | 0 |
| shares A | 0 | 4 | 3.6 | 97/30 |
| shares B | 0 | 8 | 8.6 | 9.26 |
| turnover | 0 | 0.8 | 4/45 | 44/485 |
| costs | 0 | 200 | 20 | 22 |

Trades: Jan 3 A +4 @ 100 (cost 100), B +8 @ 50 (cost 100); Jan 4 A -0.4 @ 125 (-50, cost 12.5), B +0.6 @ 50 (+30, cost
7.5); Jan 5 A -11/30 @ 150 (-55, cost 13.75), B +0.66 @ 50 (+33, cost 8.25). Total costs 242.

### H23 A whole run with costs: buy and hold on the world of H1 (`run_backtest`, net and gross)

Used in `tests/test_engine_runner_costs.py`. A tiny provider delivers the prices of H1 for the symbol A. The spec: universe
A; period 2024-01-02 to 2024-01-08; signal `buy_and_hold` (1.0 from the first trading row, as H1's constant signal);
`equal_weight`, `on_signal`, delay 1, open fills; capital 1000; costs commission 1000, spread 1000, slippage 500 bps
(total rate 25 percent, absurd on purpose so that every number is round), `min_commission` 0. A: open 100, 100, 110, 121,
133.1; close 100, 110, 121, 133.1, 146.41. The signal needs no history, so the first bar is Jan 2 (bar 0) and the
warm-up is sufficient.

*Net run.*

- Jan 2 (bar 0, first bar): nothing is executed (delay 1). Cash 1000, equity 1000, turnover 0, costs 0. The initial
  decision is bar 0 (target A 1.0), executed on bar 1.
- Jan 3 (bar 1): open 100, V = 1000, q = 1.0 * 1000 / 100 = +10, notional 1000. `f0 = 1` (the cash covers the notional)
  but the outlay would be 1000 + 0.25 * 1000 = 1250 > 1000, so `f = 1000 / 1250 = 0.8`: 8 shares, notional 800, fee
  0.25 * 800 = 200 (commission 80, spread 80, slippage 40), cash 1000 - 800 - 200 = 0. The remaining 2 shares are dropped.
  Close 110: 8 * 110 = 880. Turnover 800 / 1000 = 0.8.
- Jan 4: the target never changes, so there is no decision. Close 121: 8 * 121 = 968.
- Jan 5: close 133.1: 8 * 133.1 = 1064.8.
- Jan 8: close 146.41: 8 * 146.41 = 1171.28.

*Gross twin* (the same orders without costs): Jan 3 buys 10 shares at 100 (cash 0); equity 1000, 1100, 1210, 1331,
1464.1, the literals of H1.

| | Jan 2 | Jan 3 | Jan 4 | Jan 5 | Jan 8 |
|---|---|---|---|---|---|
| equity | 1000 | 880 | 968 | 1064.8 | 1171.28 |
| gross equity | 1000 | 1100 | 1210 | 1331 | 1464.1 |
| cash | 1000 | 0 | 0 | 0 | 0 |
| shares A | 0 | 8 | 8 | 8 | 8 |
| weight A | 0 | 1 | 1 | 1 | 1 |
| turnover | 0 | 0.8 | 0 | 0 | 0 |
| costs | 0 | 200 | 0 | 0 | 0 |
| return of the bar | 0 | 880 / 1000 - 1 = -0.12 | 968 / 880 - 1 = 0.1 | 0.1 | 0.1 |

One trade: Jan 3 A +8 @ 100 (+800, cost 200). `deferred_orders` = 0, `unfilled_orders` = 0. `costs_applied` is True and there
are no risk flags (non-zero costs, delay 1).

*Scalars.* `total_costs` = 200. `gross_final_equity` = 1464.1. `net_return` = 1171.28 / 1000 - 1 = 0.17128.
`gross_return` = 1464.1 / 1000 - 1 = 0.4641. `cost_drag` = 0.4641 - 0.17128 = 0.29282. `cost_share` = 0.29282 / 0.4641 =
292.82 / 464.1 (about 0.631). (The net equity is the gross equity divided by 1.25 from Jan 3 on: 1100 / 1.25 = 880.)

### H23b The same run in a falling market (the share of a loss is not defined)

The setup of H23. A: open 100, 100, 90, 81, 72.9; close 100, 90, 81, 72.9, 65.61.

- Jan 3: V = 1000, buy 8 shares at the open 100 (notional 800, fee 200, cash 0) as in H23. Close 90: 8 * 90 = 720.
- Jan 4 close 81: 648. Jan 5 close 72.9: 583.2. Jan 8 close 65.61: 8 * 65.61 = 524.88.
- Gross twin: 10 shares, equity 1000, 900, 810, 729, 656.1.

Scalars: `total_costs` 200; `net_return` = 524.88 / 1000 - 1 = -0.47512; `gross_return` = 656.1 / 1000 - 1 = -0.3439;
`cost_drag` = -0.3439 - (-0.47512) = 0.13122; `cost_share` = **None** because the gross return is not positive.

### H23c A portfolio ruined by fees, through `run_backtest`

The setup of H23 with a test signal that is 1.0 where the close is above the previous close (as in H14) and costs
`min_commission` 500, everything else 0 (a flat fee of 500 per trade). A: open 100, 100, 100, 100, 100; close 100, 101, 100,
100, 100. The signal is 0, 1, 0, 0, 0, so the target changes on bar 1 (to 1.0) and on bar 2 (to 0). The initial decision
(bar 0, target 0) has no order. The world has no row before Jan 2, so the signal is not warmed up on the first bar and the
run also carries the flag and the warning `insufficient_warmup`; this does not change any number below.

- Jan 4 (bar 2, executes bar 1's decision): V = 1000, q = +10, notional 1000. `f0 = 1`, the fee is 500 whatever the
  size, so the outlay `f * 1000 + 500` equals the cash at `f = 0.5`: 5 shares, notional 500, fee 500, cash 0. Close 5 * 100 = 500.
- Jan 5 (bar 3, executes bar 2's decision): V = 500, q = -5, notional 500, fee min(500, 500) = 500, proceeds 0, cash 0,
  equity 0. Jan 8: equity 0, no order.
- Equity 1000, 1000, 500, 0, 0. The weights and the turnover are never NaN. Gross twin: 10 shares bought and sold at 100,
  equity 1000 on every bar.

Scalars: `total_costs` 1000; `net_return` = -1; `gross_return` = 0; `cost_drag` = 0 - (-1) = 1; `cost_share` = **None**
(the gross return is not positive).

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
