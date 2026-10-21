# 0001: Own engine instead of vectorbt or backtrader

- **Status:** Accepted

## Context

`backtest-agent` needs a backtesting engine. Mature libraries exist (vectorbt, backtrader), but the project has
specific requirements: signals are shifted by at least one bar by default, every assumption (execution delay,
costs, adjustment rules) must be visible in the report, and the arithmetic must be provable with hand-calculated
tests. The project is also educational, so understanding the engine matters as much as using it.

## Decision

We write our own small engine: a vectorized, daily, long-only, multi-asset backtester on `pandas` and `numpy`
(Phases 4 and 5). We do not build on vectorbt or backtrader.

- **vectorbt** is fast, but its API is large and many defaults (for example same-bar execution) have to be
  unlearned or disabled one by one. It is hard to guarantee that look-ahead is impossible by default.
- **backtrader** is event-driven and flexible, but heavier than needed for daily bars, less actively maintained, and
  its behaviour is harder to verify with small fixtures.

The scope stays deliberately narrow: daily bars, long-only, no leverage. Short selling, leverage and intraday bars
are listed as outlook items in the roadmap.

## Consequences

- The execution delay, cost model and invariants are under our control and covered by tests with hand-calculated
  fixtures.
- Fewer features than the libraries, and we maintain the engine ourselves.
- Results are not directly comparable to other tools without checking their assumptions first.
- If the scope grows beyond daily long-only strategies, this decision has to be revisited in a new ADR.
