# 0007: Strict, explicit strategy spec

- **Status:** Accepted

## Context

The strategy spec is the document the maintainer approves before anything runs (guiding principle 3), and it will
often be written by an agent. Anything that is not written in it is an assumption nobody approved, and a typo in a
field name must not silently fall back to a default. Costs, execution timing and look-ahead are exactly the places where
a backtest turns pretty but wrong.

## Decision

- The schema is a Pydantic v2 model that is frozen, rejects unknown fields and uses strict types (no `true` as a
  number, no `"10"` as an integer). YAML is loaded only with the safe loader, duplicate keys and non-mapping documents
  are errors.
- **Required** fields: `schema_version` (must be 1), `name`, `universe`, `period`, `signal`, `sizing`, `rebalance`,
  `costs` (with all three numbers), `benchmark` and `initial_capital`. **Defaults** only where the default is safe or
  there is one choice: `description`, `data` (`yfinance`) and `execution` (`delay_bars` 1, price `open`, no same-bar
  opt-in). Zero costs are allowed, but they have to be written, and then they are a risk flag.
- Execution rules: `delay_bars: 0` is rejected without an explicit `allow_same_bar_execution: true`; `delay_bars: 0`
  with `price: open` is always rejected (the signal is only known after the close of the bar); the opt-in flag together
  with a delay of 1 or more is rejected as contradictory.
- `signal.params` are validated against the params model of the registered signal inside the spec model, and stored
  with the defaults filled in, so the spec (and later the journal) pins the values a run really used even if a default
  changes in a future version.
- `StrategySpec.risk_flags()` returns the facts every report must show (`same_bar_execution`, `zero_costs`) with stable
  codes; the spec exposes `warmup_rows` of its signal.
- Loading raises one `SpecError` that lists every problem with its dotted field path, a suggestion for typos and the
  received value for type errors, instead of a raw Pydantic or YAML traceback.

Alternatives rejected: defaults for sizing, rebalancing, benchmark and capital (hidden assumptions that change turnover,
costs and comparisons); lax types (a quoted number or a boolean slipping through); stopping at the first error (an
agent or a person would need one round trip per problem); validating signal params only when the engine runs.

## Consequences

- Specs are a little longer, and an example or an agent-written spec cannot forget costs, sizing or timing.
- The schema carries a version, so later changes can be told apart; adding an optional field stays compatible, adding a
  required field or changing a meaning needs a new `schema_version`.
- The spec says what sizing, rebalancing and costs mean, but the engine applies sizing, rebalancing and execution since Phase 4 and
  the costs follow in Phase 5; until then the costs are validated, not executed, and the result says so.
- Every file in `strategies/` is loaded by a test, so a broken spec fails CI.
- See [strategy-spec.md](../strategy-spec.md) for every field with type, default and meaning.
