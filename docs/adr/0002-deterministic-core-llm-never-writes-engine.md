# 0002: Deterministic core, the LLM never writes the engine

- **Status:** Accepted

## Context

The project uses Claude subagents to turn a plain-language idea into a strategy. An LLM can write plausible code
that contains subtle errors such as look-ahead bias, wrong cost arithmetic or silent data problems, and a pretty
result from wrong code is worse than no result. Results must also be reproducible: the same spec on the same data
must always give the same numbers.

## Decision

The data layer, engine, metrics, reporting and journal are deterministic, tested Python code written and reviewed by
humans. Agents work only around this core:

- the strategy architect writes a strategy spec, and nothing runs until the maintainer approves it;
- the signal coder writes one small signal function against a fixed interface, with write permission only for
  `strategies/` and tests, never for the engine;
- the bias auditor and the report interpreter read results and give findings and a verdict.

Alternatives rejected: letting an agent generate a whole backtest script per idea (not reproducible, hard to
audit), and letting agents modify the engine (the grader would be able to change the rules).

## Consequences

- Correctness of the numbers rests on the test suite, not on trusting the model.
- Agents can be wrong without corrupting the engine; mistakes are caught by the interface test, the look-ahead
  test and the independent auditor.
- Strategies are limited to what the spec and the signal interface can express.
- Every new agent capability must keep this boundary and be listed under trust boundaries in
  [architecture.md](../architecture.md).
