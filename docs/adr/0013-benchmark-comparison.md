# 0013: Benchmark comparison

- **Status:** Accepted

## Context

A result means little without a yardstick, and a yardstick that is computed differently from the strategy (close to close
instead of through the engine, without costs, on another calendar) makes the comparison wrong in ways nobody sees. The
benchmark has to be measured exactly like the strategy, and the comparison has to be honest when the two calendars differ.
The formulas, the alignment rule and the fixtures R1 to R3 are in [metrics.md](../metrics.md).

## Decision

- **Same engine, same costs.** The benchmark is a buy-and-hold run through the same `run_backtest`, with the same period,
  initial capital, execution rules (delay, price rule, same-bar flag) and costs as the strategy, loaded through the same
  provider. It is not computed from closes. Alternatives rejected: a close-to-close benchmark (the first bar and the costs
  would be measured differently), a cost-free benchmark (the strategy would be compared with something that cannot be
  bought).
- **A derived spec.** `benchmark_spec(spec)` sets the universe to `[spec.benchmark]`, the signal to `buy_and_hold` with no
  params, sizing `equal_weight` (a `fixed_fraction` strategy still gets a fully invested benchmark), rebalance
  `on_signal`, the name to `"<name> (benchmark <SYM>)"` (the strategy name is cut so the result stays within the 100
  characters the spec allows), and copies everything else unchanged. It is built with the `StrategySpec` constructor so
  that every validator runs. Alternative rejected: `model_copy(update=...)`, which skips validation.
- **Its own run, no special cases.** If the benchmark symbol is also in the universe, the benchmark is still its own
  `run_backtest` call with its own provider call, its own data hash and its own validation. A benchmark that cannot be
  loaded raises the provider's error unchanged and no partial result is returned; alternative rejected: an evaluation
  without a benchmark, which would break "a run always reports its metrics next to the benchmark".
- **Alignment on equity levels.** The two results are compared on the intersection of their bar dates, and the returns are
  computed from the equity levels on that grid (with the engine's `bar_returns`), because a per-bar return across a date
  that exists in only one series covers a different holding period. If the first common date is the first bar of both runs,
  the base of the first return is the initial equity of each run and nothing is lost. Otherwise the base is the equity at the
  first common date, that date has no return, and `n_compared = n_common - 1`. Dropped dates are counted for both sides and
  flagged (`dates_dropped`); fewer than two observations flag `insufficient_overlap` and make every relative metric `None`.
  Nothing is dropped silently and different calendars never raise.
- **What the window leaves out.** When the first common date is not the first bar of both runs, the first-bar return of each
  run, measured against its initial equity, is not part of the compared window. So the excess return, which is computed
  over the window, can differ from the difference of the two `net_return`s. The window totals and the alignment are
  reported next to the metrics so this is visible. The `PerformanceMetrics` of each run stay on its own full result.
- **Relative metrics.** Excess return is the difference of the compounded totals over the window. Tracking error is the
  annualized sample standard deviation (`ddof = 1`) of the per-bar active return and the information ratio is the
  annualized mean active return over the tracking error. The zero tolerance (1e-12 on the per-bar deviation) and the
  assumptions (`periods_per_year`) of [ADR 0012](0012-metric-conventions.md) are reused: a tracking error below the
  tolerance is exactly 0.0 and the ratio is `None`. An undefined value is `None`, never NaN or inf. The standard deviation
  is computed without the input check of `volatility`, because an active return can be below -1.
- **`evaluate` is the single entry point.** `evaluate(spec, provider, *, allow_short_warmup, apply_costs, assumptions)` runs
  the strategy, runs the benchmark with the same `allow_short_warmup` and `apply_costs`, and returns an `Evaluation`
  with both results, both metric sets and the relative metrics. `evaluate_result` is its pure part and raises
  `ValueError` unless `benchmark_result.spec == benchmark_spec(result.spec)` and both have the same `costs_applied`, so a
  result is never compared with another yardstick. `run_backtest` stays unchanged and loads no benchmark.
- **A plain `to_dict`.** `Evaluation.to_dict()` holds floats, ints, strings, bools, `None`, dicts and lists of strings (the
  risk flag codes of both runs), including both data hashes, both spec names and the alignment; no frames. The Phase 7
  report and the Phase 8 journal store it as it is.

## Consequences

- The strategy is judged against something that can really be bought, with the same costs and delay.
- A benchmark costs a second run and a second provider call (the data cache absorbs the repeated call), also when it is in
  the universe.
- A calendar mismatch changes the compared window, never the metrics of a single run; the report must show the alignment.
- Hand-calculated fixtures R1 to R3 pin the rule, the numbers and the proof that the benchmark carries the strategy's costs.
