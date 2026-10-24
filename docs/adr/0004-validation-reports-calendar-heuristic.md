# 0004: Validation reports issues, calendar gaps by heuristic

- **Status:** Accepted

## Context

A backtest on bad data gives a pretty but wrong result. Data quality has to be checked before a run, and the findings
must reach the report and the journal. After the outer join of several symbols, NaN rows on days when only one exchange
was open are expected, so a naive NaN check would flag healthy data. Checking against an exchange calendar needs a
calendar library and a mapping from every symbol to its exchange, which is itself a source of errors.

## Decision

- `validate_prices` **reports** instead of raising. Each finding is an issue with a severity (error, warning, info), a
  stable code, symbol, field, number of affected rows, the first affected dates and a message. Errors stop a run
  (`ValidationResult.raise_for_errors()` raises `DataValidationError`), warnings appear in the report, infos are
  context. The result is deterministic, never modifies the frame and serializes to a dict and to JSON, including the
  thresholds that were used.
- Format violations of the standard frame stay a `ValueError` (`validate_standard_frame`). The validation accepts
  unsorted and duplicate dates because reporting them is its job, and raises only for structural problems.
- Every per-symbol check runs only on the rows where that symbol has data (at least one non-NaN field).
- NaN in open, high, low or close is an error, NaN or zero volume is only a warning or info: the engine is price-based
  and indices and FX pairs often have no usable volume. Volume problems give one summary issue per symbol and field.
- Thresholds live in a frozen `ValidationConfig` with documented defaults, so they can differ per run.
- **Calendar gaps use a dependency-free heuristic**: the number of missing Monday-to-Friday days between a symbol's own
  consecutive data dates, flagged when above a limit (default 4). It works the same for absent rows and all-NaN rows.

Alternatives rejected: an exchange calendar library (a heavy dependency plus a symbol-to-exchange mapping, to be
reconsidered together with more providers); raising on the first problem (one run would show only one problem and
warnings could not exist); treating NaN volume as an error (it would reject valid index and FX data).

## Consequences

- One missing day inside a symbol's history looks like a holiday and is **not** detected; only runs of missing days
  longer than the limit are. A missing week is found, and so are wrong prices, splits and stale data.
- The mechanism for "data errors stop a run" exists after Phase 2. Since Phase 4 `run_backtest` calls
  `raise_for_errors()` before every run (tested); so does the command line (`bt run`, Phase 9; `bt validate --data`
  lists every issue).
- A jump to 1/2 or 2 times the price fires both `split_artifact` and `extreme_move`, by design.
- The codes are a stable interface for the report, the journal and the auditor; renaming one is a breaking change.
- See [data.md](../data.md) for the table of all checks and their default thresholds.
