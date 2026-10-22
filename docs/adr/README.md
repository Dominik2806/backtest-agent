# Architecture decision records

Short records of the decisions that shape this project. Each one has a status, the context, the decision and its
consequences. The pull request numbers refer to where the decision landed. For the overall picture see
[architecture.md](../architecture.md).

To add one, copy [0000-template.md](0000-template.md) to the next free number and list it here.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-own-engine-instead-of-vectorbt-or-backtrader.md) | Own engine instead of vectorbt or backtrader | Accepted |
| [0002](0002-deterministic-core-llm-never-writes-engine.md) | Deterministic core, the LLM never writes the engine | Accepted |
| [0003](0003-standard-price-frame.md) | One standard price frame, adjusted prices, caching as a wrapper | Accepted |
| [0004](0004-validation-reports-calendar-heuristic.md) | Validation reports issues, calendar gaps by heuristic | Accepted |
| [0005](0005-canonical-data-hash.md) | Canonical data hash | Accepted |
| [0006](0006-signal-contract.md) | Signal contract and where signals live | Accepted |
| [0007](0007-strict-explicit-spec.md) | Strict, explicit strategy spec | Accepted |
| [0008](0008-engine-semantics.md) | Engine semantics: timeline, sizing, orders, turnover | Accepted |
| [0009](0009-run-pipeline-and-warmup.md) | Run pipeline, warm-up and result object | Accepted |
