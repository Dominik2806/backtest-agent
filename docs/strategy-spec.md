# Strategy spec and signals

A strategy is a YAML file, the **spec**, plus one small function, the **signal**. The spec is the document the
maintainer approves before anything runs, so it is strict: unknown fields are rejected, types are strict and
everything that changes a result has to be written down. Code lives in `src/backtest_agent/spec/`, examples in
[`strategies/`](../strategies). The decisions behind this are [ADR 0006](adr/0006-signal-contract.md) (signal
contract) and [ADR 0007](adr/0007-strict-explicit-spec.md) (strict spec). This project is educational and not
investment advice.

## Loading a spec

```python
from backtest_agent.spec import SpecError, load_spec, parse_spec

spec = load_spec("strategies/sma_crossover.yaml")  # from a file (UTF-8)
spec = parse_spec(yaml_text)  # from text
spec.signal.params_model()  # the signal's params as a typed object
spec.warmup_rows  # trading rows of history the signal needs, see "Warm-up"
spec.risk_flags()  # facts every report must show, see "Risk flags"
spec.to_dict()  # plain dict with JSON types, for the report and the journal
```

Both functions raise one `SpecError` that lists **every** problem with its field path, never a raw YAML or Pydantic
traceback:

```text
Invalid strategy spec in strategies/bad.yaml (3 problems):
  - execution.dely_bars: unknown field 'dely_bars'; did you mean 'delay_bars'?
  - costs: the costs block is required: write commission_bps, spread_bps and slippage_bps explicitly (zeros are allowed when written)
  - signal.params.slow: slow must be larger than fast (fast=50, slow=20)
```

Paths are dotted (`execution.delay_bars`), list items are `universe[1]`, `(root)` is the whole document, `(yaml)` a
YAML syntax error and `(file)` an unreadable file. `SpecError.problems` holds the same list as `SpecProblem(path,
message)` objects. YAML is read with the safe loader only (no Python objects), a duplicate key anywhere is an
error, a document that is not a mapping is an error.

## Fields

Types are strict: `true` is not a number, `"10"` is not an integer. Integers are accepted where a number is
expected. Dates are written `2020-01-31` (as YAML date or as text). Fields marked **required** have no default,
because a default would be an assumption nobody approved.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `schema_version` | integer | **required** | Must be `1`. Lets later versions of the schema change without guessing. |
| `name` | text | **required** | One line, at most 100 characters. |
| `description` | text | `""` | What the strategy does, free text. |
| `universe` | list of symbols | **required** | At least one symbol, no whitespace, unique (also ignoring case), kept as written. |
| `period.start` | date | **required** | First day of the evaluation period. |
| `period.end` | date | **required** | Last day, on or after `start` (both inclusive, see [data.md](data.md)). |
| `data.provider` | `yfinance` | `yfinance` | Data source. Only `yfinance` exists. |
| `signal.id` | text | **required** | A registered signal, see [Built-in signals](#built-in-signals). An unknown id lists the available ones. |
| `signal.params` | mapping | `{}` | Parameters of that signal, validated against its params model. The stored values have the defaults filled in. |
| `execution.delay_bars` | integer, 0 or more | `1` | Bars between the signal and the fill. |
| `execution.price` | `open` or `close` | `open` | Which price of the fill bar the order gets. |
| `execution.allow_same_bar_execution` | boolean | `false` | Explicit opt-in for `delay_bars: 0`. |
| `sizing.method` | `equal_weight` or `fixed_fraction` | **required** | How signal values become weights. |
| `sizing.fraction` | number, above 0 up to 1 | none | Required for `fixed_fraction`, not allowed for `equal_weight`. |
| `rebalance` | `daily`, `weekly`, `monthly` or `on_signal` | **required** | When the portfolio is brought to its target weights. |
| `costs.commission_bps` | number, 0 or more | **required** | Commission in basis points of the traded value. |
| `costs.spread_bps` | number, 0 or more | **required** | Half-spread in basis points. |
| `costs.slippage_bps` | number, 0 or more | **required** | Slippage in basis points. |
| `benchmark` | symbol | **required** | Buy-and-hold comparison; may or may not be in the universe. |
| `initial_capital` | number, above 0 | **required** | Starting cash. |

Sizing, rebalancing and the execution fields are applied by the engine ([engine.md](engine.md), Phase 4); costs follow
in Phase 5 (until then `run_backtest` does not deduct them and flags it). The meaning of the sizing methods is:

- `equal_weight`: capital is split equally among the **selected symbols only**, those with a signal above 0, and each
  weight is scaled by its signal value: `weight = signal / n` with `n` the number of selected symbols. Empty slots are
  not kept in cash. Example: `momentum_12_1` with `top_n: 3` and `positive_only: true` on a day when only one symbol has
  a positive score gives that symbol 100 percent of the equity (1000 of 1000), not a third with 667 in cash; with two
  qualifying symbols each gets 50 percent. With all signal values at 1.0 the portfolio is fully invested whenever at
  least one symbol is selected; a signal of 0.5 on a lone symbol invests half. Keeping empty slots in cash ("slot-based
  equal weight") is a possible later extension.
- `fixed_fraction`: each position weighs its signal value times `fraction` of the equity. If the weights add up to
  more than 100 percent they are divided by their sum (0.6 and 0.6 become 0.5 and 0.5), so there is never leverage;
  otherwise the rest is cash.

### Rules

- **Unknown fields are rejected**, so a typo fails loudly (`dely_bars`), with a suggestion when one is close.
- **`delay_bars` defaults to 1.** A negative value is rejected.
- **`delay_bars: 0` is rejected** unless `allow_same_bar_execution: true` is written explicitly: trading on the bar
  that produced the signal can hide look-ahead bias.
- **`delay_bars: 0` with `price: open` is always rejected**, even with the flag: the signal is only known after the
  close of the bar, so an open fill on that bar would use the future. Same-bar execution therefore means
  `price: close`.
- `allow_same_bar_execution: true` together with `delay_bars: 1` or more is rejected as contradictory.
- **The `costs` block is required**, and so is each of its three numbers. Zeros are allowed when written out, and
  then the report shows a risk flag. There are no silent zero costs.
- `period.end` before `period.start` is rejected.
- `signal.params` are validated against the params model of the registered signal (`signal.params.fast: ...`).

### Risk flags

`spec.risk_flags()` returns the facts a report must always show, in a fixed order, as `RiskFlag(code, message)`
objects (`to_dict()` gives plain dicts). Phase 7 puts them in every report.

| Code | When |
|---|---|
| `same_bar_execution` | `delay_bars` is 0 (explicitly allowed): the result may contain look-ahead bias |
| `zero_costs` | commission, spread and slippage are all 0: the result overstates what trading would return |

## Complete example

```yaml
schema_version: 1
name: SMA crossover on liquid ETFs
description: >
  Each ETF is held while its fast simple moving average of the close is above the slow one.

universe: [SPY, QQQ, TLT, GLD]
period:
  start: 2010-01-01
  end: 2023-12-31
data:
  provider: yfinance

signal:
  id: sma_crossover
  params:
    fast: 50
    slow: 200

execution:
  delay_bars: 1
  price: open
  allow_same_bar_execution: false

sizing:
  method: equal_weight
rebalance: on_signal

costs:
  commission_bps: 1.0
  spread_bps: 2.0
  slippage_bps: 2.0

benchmark: SPY
initial_capital: 100000
```

The three example specs in [`strategies/`](../strategies) are loaded by a test, and so is every other `*.yaml` file
put there, so a broken spec fails CI.

## The signal contract

A signal is a function `fn(prices, params) -> DataFrame`. It is registered with `@register_signal(id, params=Model)`
and called through `get_signal(id).generate(prices, params)`, which enforces the contract on every call.

**Input.** `prices` is the standard price frame of [data.md](data.md) (checked with `validate_standard_frame`).
`params` is an instance of the signal's params model.

**Output.** A `DataFrame` with

- the **same index** as `prices`;
- **flat columns** (an `Index` named `symbol`) holding the symbols of `prices` in input order;
- dtype **`float64`**, finite, **between 0 and 1**, and **no NaN**.

The value is the desired exposure, not a weight: 0 means no position, fractions are allowed, and the sizing rule of
the spec turns the values into weights (Phase 4). `validate_signal_output(prices, signals)` checks all of this and
raises `SignalContractError` listing every violation.

**Causality.** The value on a date may use only rows up to and including that date, of any symbol: no `shift(-k)`,
no centered windows, no statistics of the whole sample. The engine shifts the signal by `delay_bars` before using it.
This rule is documented here and enforced by an automated look-ahead test in Phase 15.

**Purity.** The function must not modify its input and must be deterministic. `generate` hands the function a
copy-on-write view, so an in-place change cannot reach the caller's frame.

**Trading rows and non-trading days.** After the outer join of different calendars, a symbol has all-NaN rows on its
own holidays. A signal is computed per symbol on that symbol's **own trading rows**, the rows where its `close` is
not NaN, so windows count the symbol's own days. Warm-up rows are 0.0. The value is **carried forward** over the
symbol's non-trading days (a held position stays held on a holiday instead of being sold and bought back, which would
fake turnover and costs), and it is 0.0 before the symbol's first trading row. The helpers `per_symbol_signal`,
`carry_forward` and `close_frame` in `spec/signals.py` do this.

### Warm-up

Every params model has `warmup_rows()` (default 0): the number of trading rows of history a symbol needs before a
date to produce its final value on that date. Exactly, with W the value and k the 0-based number of a symbol's
own trading row:

1. the signal of that symbol is 0.0 on its first W trading rows (k < W);
2. from row W on it is final: the value is identical whether the function sees the full history or only the W
   trading rows of that symbol before the date, plus the date itself.

For `sma_crossover` this is `slow - 1`, for `momentum_12_1` it is `lookback_days`, for `buy_and_hold` it is 0.
`spec.warmup_rows` exposes the value for the spec's signal. The engine and the command line load history from
`period.start` minus the warm-up, run the signals on it and trim the results to the period (`run_backtest`, Phase 4;
the command line, Phase 9), so the
strategy and the benchmark are compared over the same period. This is **not** the Phase 15 look-ahead test; it only
checks that the declared warm-up is honest.

### The reusable contract test

`tests/signal_contract.py` holds the checks every registered signal must pass, and
`tests/test_signal_contract.py` runs them for every id in the registry, with default and small-window params, on
fake-provider data: a plain frame, a frame with different calendars (holidays, a symbol starting late, one ending
early), a history shorter than the warm-up and a single symbol. It checks index and columns, `float64`, the range, no
NaN, that the input frame is unchanged, determinism, that the output is 0.0 on the first `warmup_rows` trading
rows of each symbol, and that the value on every date is identical when the function only sees `warmup_rows` rows of
history before that date. A new signal is covered as soon as it is registered.

## Built-in signals

Built-in signals live in the package (`spec/builtin_signals.py`) and are registered when `backtest_agent.spec` is
imported. Signals written by agents will live in `strategies/` (Phase 10 restricts the coder to that folder); the
discovery of those files is built in Phase 10, and it must only load files the approved spec names (see ADR 0006).

| Id | Parameters (default) | Signal | Warm-up |
|---|---|---|---|
| `sma_crossover` | `fast` (50), `slow` (200), `fast` smaller than `slow` | 1.0 while the simple moving average of the close over `fast` rows is strictly above the one over `slow` rows, else 0.0 | `slow - 1` |
| `momentum_12_1` | `lookback_days` (252), `skip_days` (21), `top_n` (3), `positive_only` (false) | Per symbol `close[t - skip_days] / close[t - lookback_days] - 1` on its own trading rows; the `top_n` symbols with the highest score get 1.0, the rest 0.0. Ties go to the symbol first in the input. With `positive_only` a score must be above 0, so fewer than `top_n` symbols may be held. Symbols still in warm-up are not eligible | `lookback_days` |
| `buy_and_hold` | none | 1.0 for every symbol from its first trading row on | 0 |

`momentum_12_1` counts its windows in trading days (12 months is about 252 days, one month about 21), which is
simple, vectorized and has no calendar edge cases. `skip_days` must be smaller than `lookback_days`.
