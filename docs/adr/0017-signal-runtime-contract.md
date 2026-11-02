# 0017: Runtime check of the signal's zero rows

- **Status:** Accepted

## Context

[ADR 0006](0006-signal-contract.md) says a signal is 0.0 before its symbol's first trading row and on the symbol's first
`warmup_rows` trading rows. Until now only the reusable test `tests/signal_contract.py` checked that, and only for signals
registered in the repository. `Signal.generate` (what the engine calls) checked shape, dtype, NaN and range
(`validate_signal_output`) and nothing else. Phase 10 lets an agent write a signal, so the rule must hold for any signal
at run time, not only for signals that a human reviewed and put under test.

What happened without the check, observed on 2026-11-02 with a signal that is 1.0 on every row of every symbol, a
two-symbol universe in which B has no close on Jan 2, 3 and 4 (`tests/test_signal_runtime_zeros.py`): the signal passed
`Signal.generate`, and the engine stopped with `EngineError: ['B'] get an order on 2024-01-03 but have never had a price`.
So the run failed, but with an engine message far from its cause, and only because the engine happens to notice an order for
a symbol that never had a price. A violation inside the warm-up (a symbol that has a price but not yet enough history) is
not noticed by the engine at all.

## Decision

- `validate_signal_zeros(prices, signals, warmup_rows)` in `spec/signals.py`: for each symbol, every row before its
  (W+1)-th trading row must be exactly 0.0, W being `warmup_rows`. With W = 0 this is "0.0 before the first trading row"; a
  symbol with at most W trading rows must be 0.0 throughout (including a symbol that never trades). The error is a
  `SignalContractError` that names W, each offending symbol, the number of non-zero values and the first date.
- `Signal.generate` calls it right after `validate_signal_output`, with the `warmup_rows` of the parsed params.
- `validate_signal_output` is unchanged. It stays a shape-and-range check without knowledge of the params, and its own tests
  call it directly with frames of constant 0.5.
- Holidays inside a symbol's history are not touched: the value is carried over them, which is the documented behaviour.

## Consequences

- Behaviour changes for exactly one kind of input: a signal output that was accepted before and has a non-zero value before
  a symbol's (W+1)-th trading row now raises `SignalContractError` from `Signal.generate`. The three built-in signals and
  every signal registered by a test comply (checked by the test suite, no existing test changed).
- The cost is vectorised and O(rows x symbols) per call; measured on the cached example frames it adds between 0.3 and 0.5
  ms to a `generate` call of 1 to 3 ms (see the CHANGELOG entry).
- This is not a look-ahead test (Phase 15). It checks the declared zeros only; whether the declared `warmup_rows` is honest is
  still checked by the reusable contract test, and in Phase 10 by the pre-run check of coded signals.
