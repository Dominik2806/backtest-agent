# 0009: Run pipeline, warm-up and result object

- **Status:** Accepted

## Context

`run_backtest(spec, provider)` is where data, signals and the engine meet. How much history is loaded, what counts as
enough history, what happens when the data does not match the period and what a result contains decide whether a
number can be trusted and compared later (metrics, benchmark, report, journal).

## Decision

- **Window.** With `N = spec.warmup_rows + delay_bars`, history is fetched from `period.start` minus `2 * N + 14`
  calendar days and the rows are counted afterwards; there is no retry. The loaded history is not trimmed before the
  signals run, and the data hash covers the frame as loaded, warm-up included.
- **Enough history.** The run is sufficient when every symbol has at least `warmup_rows` of its own trading rows
  strictly before the first decision bar (the bar that executes on the first bar). Otherwise the run continues with
  `WarmupInfo.sufficient` False, the risk flag `insufficient_warmup` and an `InsufficientWarmupWarning`;
  `allow_short_warmup=False` raises `InsufficientHistoryError`. `WarmupInfo` also records `first_decision_date` and
  `initial_target_weights`, because the trimmed signals of the result start after the decision the first trade is
  based on.
- **Data that does not match the period.** A symbol that starts late, data that ends early and a period start before
  all data are reported (validation infos, `first_data`, the warm-up count), not rejected. Missing symbols raise
  `DataUnavailableError`, no bar on or after `period.start` raises `DataUnavailableError`, rows after `period.end`
  raise `ValueError`. The benchmark is not loaded yet.
- **Result.** `BacktestResult` is a frozen dataclass of plain types and standard frames (compared by field), so the
  journal can serialize it later. `costs_applied` is False and the flag `costs_not_applied` is added while the costs
  of the spec are not deducted (Phase 5).
- **Last close from the warm-up.** A symbol without a price on the first bar is valued at its last close, which may
  come from a warm-up bar. Without it a holiday of one symbol on the first bar made the run fail.

Rejected: a retry loop that fetches more history until it is enough (hides the cost and the data source behaviour);
failing on short history by default (a short test world would need a flag everywhere); trimming the history before the
signals (signals would not be warmed up on the first bar).

## Consequences

- A result always says how much history stood behind its first decision.
- The benchmark of Phase 6 has to run through the same engine with the same execution rules as the strategy.
- Phase 5 plugs the costs in and sets `costs_applied` and removes `costs_not_applied` accordingly.
