# 0011: Gross versus net result and the `apply_costs` opt-out

- **Status:** Accepted

## Context

[ADR 0010](0010-cost-model.md) defines the cost model and says that the gross result is a twin run without costs. This
record decides how `run_backtest` produces and reports it: which inputs the twin uses, what the result contains, what
the numbers mean in unusual cases, and how a run without costs is marked. The details are in "Running a spec" and
"Gross and net" of [engine.md](../engine.md).

## Decision

- **The result is the net run.** `run_backtest` deducts the costs of the spec (`BpsCosts.from_spec`). Positions, trades
  (with their `cost`), turnover, order counters and equity are those of the net run. The gross run contributes only
  `gross_equity`.
- **The twin uses the same inputs.** It is the same call of `simulate_signals` with `NoCosts()`: data, validation, hash and
  signals are computed once and shared, as are the sizing, execution, rebalance rule, initial capital, first bar and
  therefore the decisions. It runs only if costs are applied and the spec has a non-zero cost number
  (`CostsSpec.is_zero` is False). Otherwise nothing is simulated twice and `gross_equity` is an independent `.copy()` of
  `equity`, named `gross_equity`, so a change of one never changes the other and the two are equal to the last bit.
- **Result fields.** Stored: `costs` (fees per bar) and `gross_equity`, both standard series with the index of `equity`.
  Derived, as read-only **properties**: `total_costs`, `gross_final_equity`, `net_return`, `gross_return`, `cost_drag`
  (gross return minus net return) and `cost_share` (cost drag divided by the gross return, None if the gross return is
  not positive). A return is the final equity over `initial_equity` minus 1. Properties keep one source of truth (the
  scalars cannot disagree with the series).
- **Consequences for later phases.** Because the scalars are properties and not fields, the Phase 8 journal has to
  serialize them explicitly (`total_costs`, `gross_final_equity`, `net_return`, `gross_return`, `cost_drag`,
  `cost_share`). Phase 6 reuses `net_return` and must not define a second total-return formula.
- **`costs_applied`** is True whenever a cost model was applied, also one that charges nothing (a spec whose four cost
  numbers are 0); the flag `zero_costs` tells the reader. It is False only with `apply_costs=False`.
- **The opt-out keeps a flag.** `run_backtest(..., apply_costs=False)` gives a run without costs (for the cost-free
  regression fixtures and exact no-cost identities). If the spec has a non-zero cost number the result carries the risk
  flag `costs_not_applied`, so a result that overstates what trading would return cannot be read later without notice.
  In a normal run this flag is never emitted. For a spec with all four numbers 0 only `zero_costs` appears.
- **The two numbers have no sign guarantee.** `cost_drag` is not guaranteed to be 0 or more and `cost_share` is not
  guaranteed to be 1 or less. Costs change the path: a fee can block a bad purchase or leave cash in a falling market,
  so the net run can end above the gross run, and with a negative net return and a positive gross return the share
  exceeds 1 (the costs ate more than the whole gross return, up to a ruined portfolio with a net return of -1). The
  share is not clamped, and no test asserts a sign in general; only exact identities are tested (for buy and hold the
  net equity is the gross equity divided by `1 + r` from the purchase on).
- **Gross return zero or negative:** `cost_share` is None (the share of a loss is not defined); `cost_drag` stays defined.

Alternatives rejected: adding the total costs back to the net equity as "gross" (costs compound, so it is wrong, see ADR
0010); storing the scalars as fields (they could disagree with the series); running the twin always (a second simulation
with identical result for zero costs, and a risk of float differences between `gross_equity` and `equity`); dropping the
flag of the opt-out (a silent run without costs); clamping the share to 1 (hides the case where costs ate the whole gross
return).

## Consequences

- Every result states what it cost and what the strategy would have returned for free, from the same trades.
- A result with costs takes two simulations; the second is cheap because the twin has no funding search.
- The Phase 7 report can show total costs and the share of the gross return directly from the result.
