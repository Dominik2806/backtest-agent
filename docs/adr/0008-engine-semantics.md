# 0008: Engine semantics

- **Status:** Accepted

## Context

The engine is the part of the project the maintainer has to trust most, and its results feed metrics, reports and the
verdict of an auditor. Small unstated choices (when an order fills, what a fractional signal means, what happens on
a holiday of one symbol, what the first day return is) change every number downstream. They therefore have to be
decided once, written down in [engine.md](../engine.md) and proven by hand-calculated tests.

## Decision

- **Timeline.** The signal on bar t uses data up to the close of t. Its orders are executed on bar `t + delay_bars`
  at the open or the close of that bar, as the spec says. Bars are the rows of the standard frame. Nothing is traded
  or valued before `period.start`; a decision on a warm-up bar may execute on the first bar of the period, one that
  would execute earlier is dropped.
- **Portfolio.** Long-only, no leverage, no shorting, fractional shares, no interest on cash, adjusted prices (dividends
  inside). The portfolio starts as cash equal to `initial_capital`.
- **Sizing.** `equal_weight` gives each selected symbol `signal / n` with n the number of selected symbols, so the empty
  slots of a strategy such as `momentum_12_1` with `positive_only` are not kept in cash; `fixed_fraction` gives
  `signal * fraction`, scaled down proportionally when the sum exceeds 1.
- **Rebalancing.** `daily`, `weekly` and `monthly` (the last bar of the ISO week or calendar month in the frame),
  `on_signal` (when the target weights change, drift in between). A rebalance brings the whole portfolio to target.
  One **initial decision** is always taken for the bar that executes on the first bar of the period.
- **Orders.** An order is a share quantity fixed on its execution bar from the portfolio value at the execution price.
  A symbol without a price on that bar is valued at its last close and its order is carried to the next bar with a
  price, with the same quantity. Buys are scaled down by one common factor when the cash after the sells is not enough,
  and the rest is carried the same way; cash is never negative. Deferred and unfilled orders are counted and reported.
- **Turnover** is two-sided: the sum of absolute trade notionals divided by the portfolio value at the execution mark.
- **First bar return** is defined against an explicit `initial_equity`, the initial capital.
- **Costs** are a hook (`CostModel`, default `NoCosts`); Phase 4 does not apply the costs of the spec and the result
  says so.
- **A loop over bars, not a vectorized cumulative calculation.** The path dependence of cash, deferred orders and the
  cash constraint makes a loop the readable and verifiable form. Numpy vector operations are used across symbols.
- **Tests.** Expected values of engine tests are hand-calculated literals written out in `docs/engine.md`, never
  produced by engine code or by a helper that mirrors it.

Alternatives rejected: signal values as relative weights (`signal / sum(signal)`), which would invest 100 percent on a
lone signal of 0.5 and contradict "the value is the desired exposure"; carrying a deferred order as a target weight or
a notional, which re-sizes it on a later bar with a different portfolio value (a stale notional could even sell more
than is held), a share quantity avoids both; trading `weekly`/`monthly` strategies only on their own decision bars
without an initial decision (they would sit in cash for up to a month and could not be compared with the
buy-and-hold benchmark); a fully vectorized core.

## Consequences

- Every number can be reproduced by hand from the rules in `engine.md`, and the tests say how.
- A strategy whose signals are fractional invests less than 100 percent; the built-in signals are 0 or 1.
- A bar on which a symbol cannot trade can delay its orders; the counts are part of the result.
- Phase 5 plugs costs into the hook and extends the funding rule (a purchase must also cover its costs), see
  [ADR 0010](0010-cost-model.md).
- Phase 6 must treat turnover as two-sided when it labels turnover metrics.
- The runner adds data loading, warm-up, validation, the data hash and the result object on top of the pure
  simulation described here ([ADR 0009](0009-run-pipeline-and-warmup.md)).
- The last close of a symbol, used to value it on a bar without a price, includes closes of bars before the first
  bar; they are not traded or valued but known.
