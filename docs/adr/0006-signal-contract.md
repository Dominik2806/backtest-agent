# 0006: Signal contract and where signals live

- **Status:** Accepted

## Context

The signal function is the only code an agent will be allowed to write (Phase 10), and the engine trusts its output to
build positions. A pretty but wrong result from a signal that peeks at the future, returns NaN or breaks on a holiday
is worse than no result. The contract therefore has to be precise enough to be checked mechanically, and the check has
to run on every call. After the outer join of several symbols, rows of a closed exchange are all-NaN, which every signal
must handle the same way.

## Decision

A signal is a function `fn(prices, params) -> DataFrame` with a Pydantic params model that has defaults, registered
by id in a `SignalRegistry` so the engine finds it from the spec.

- **Input:** the standard price frame of Phase 1 and an instance of the params model.
- **Output:** the same index as the input, flat columns (an `Index` named `symbol`) with the input symbols in input
  order, `float64`, finite, within [0, 1], no NaN. The value is the desired exposure, 0 means no position; sizing turns
  values into weights later.
- **Causality:** the value on a date uses only rows up to and including that date, of any symbol. The engine shifts it
  by `delay_bars`. A mechanical test of this rule is Phase 15.
- **Purity:** the function does not modify its input and is deterministic.
- **Non-trading days:** each symbol is computed on its own trading rows (rows where its close is not NaN). Warm-up rows
  are 0.0, the value is carried forward over the symbol's non-trading days and is 0.0 before its first trading row.
  Carrying forward instead of writing 0.0 keeps a held position held on a holiday and avoids fake turnover and costs.
- **Warm-up (`warmup_rows`):** every params model reports `warmup_rows()` (default 0), the number of trading rows of
  history a symbol needs before a date to produce its final value on that date. With W that value and k the 0-based
  number of a symbol's own trading row: the signal of that symbol is 0.0 on its first W trading rows (k < W), and from
  row W on it is identical whether the function sees the full history or only the W trading rows of that symbol before
  the date, plus the date itself. `sma_crossover` declares `slow - 1`, `momentum_12_1` declares `lookback_days`,
  `buy_and_hold` declares 0. A reusable contract test checks that the declaration is honest on every registered
  signal. It is not the look-ahead test of Phase 15, it only proves the declared history is enough and the output is 0.0
  during warm-up. `StrategySpec.warmup_rows` exposes it for the spec's signal.
- **Runtime check:** `Signal.generate` validates the input, runs the function on a copy-on-write view of the frame
  and validates the output (`validate_signal_output`, raising `SignalContractError`) on every call, so an agent-written
  signal cannot hand the engine a NaN, a value of 1.5 or a misaligned frame.
- **Registry:** a `SignalRegistry` class with a default instance (`register_signal`, `get_signal`, `list_signals`), so
  tests can use private registries. An unknown id raises `UnknownSignalError` naming the available ids; a duplicate id is
  an error.
- **Where signals live:** built-in signals live in the package (`spec/builtin_signals.py`) and are registered on
  import. Agent-written signals will live in `strategies/` (Phase 10 restricts the coder to that folder); the discovery
  of those files is built in Phase 10, not now. `momentum_12_1` counts its windows in trading days (252 and 21), not
  calendar months.

Alternatives rejected: writing 0.0 on non-trading days (spurious sells); passing the whole universe to one function
without a per-symbol rule (every signal would handle calendars differently); trusting the signal and checking only in
tests (an agent-written signal would be unchecked at run time); a `warmup_rows` hook added later (the engine and CLI need
it from the start, because without warm-up history the first part of every period is flat).

## Consequences

- The engine and the command line must load history from `period.start` minus the warm-up of the signal, run the
  signals on it and trim the results to the period, so the strategy and the benchmark are compared over the same
  period. Converting rows into a calendar start date and handling a provider with too little history is their job
  (tasks in Phases 4 and 9 of the roadmap).
- Phase 10 will execute Python written by an LLM when it loads `strategies/*.py`. Discovery must therefore only import
  files that the approved spec names, and only after the approval gate; this is a requirement for that phase.
- A signal that needs data of other symbols at the same date is possible (the contract allows any symbol's rows up to
  the date), which is what the cross-sectional `momentum_12_1` needs; for those signals warm-up is measured per symbol.
- A 0.0 during warm-up cannot be told apart from "no position"; the declared `warmup_rows` is how callers know.
- See [strategy-spec.md](../strategy-spec.md) for the full contract and the built-in signals.
