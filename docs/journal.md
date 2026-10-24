# Experiment journal

Nothing that was tried should be forgotten (F-15). Every standard run gets a run id, is stored under `runs/<run-id>/`,
is listed in a small SQLite index and is counted per strategy family, so the reader of a report can see how many variants
were tried before the one they are looking at. The code is in `src/backtest_agent/journal/` (and `run_id.py`), the
decisions are in [ADR 0015](adr/0015-experiment-journal.md). `evaluate()` and `run_backtest()` stay pure and write
nothing; the journal is a separate step.

The command line ([cli.md](cli.md)) is the user-facing entry point to this journal: `bt run` calls `run_experiment`, and
`bt journal list`, `show` and `rebuild` use the read API and `rebuild_index`.

**Status.** Phase 8 is done. Part 1 delivered the journal core: the folder format, the index, the counter and the read API
(`record_run`, `list_runs`, `get_run`, `trial_count`, `run_count`, `rebuild_index`). Part 2 delivers the one entry point
that evaluates, logs and reports (`run_experiment`, section "run_experiment"), the trial line of the report
([report.md](report.md), "The trial line") and the example below.

## Layout

```
runs/
  index.sqlite                      a rebuildable index; never the only copy of a fact
  <run-id>/
    run.json                        the source of truth of the run
    spec.yaml                       the spec of the run, readable and loadable (a copy of run.json["spec"])
  .tmp-<run-id>-<random>/           only while a run is being written; ignored by everything, safe to delete
```

`runs/` is git-ignored. **Every directory in `runs/` whose name does not start with a dot counts as a run folder.** A stray
directory (or a copied folder) therefore makes the journal stale: `JournalIndexStale` from `record_run` and from the
reads, `JournalFormatError` from `rebuild_index` (it has no valid `run.json`). Plain files are ignored. The run id is `run_id.make_run_id(evaluation, generated_at)`, the same function and the same
`generated_at` as the report uses, so the journal folder and the report folder (`reports/<run-id>/`) carry the same name.
The id is `<UTC timestamp>-<slug of the strategy name>-<8 hex>`; see [ADR 0014](adr/0014-report.md) for the exact hash
input. `check_run_id` (in `run_id.py`) guards every id against path traversal, drive letters, Windows device names,
trailing dots and over-long names, and the folder must be a direct child of `runs/`.

## run.json

Canonical JSON: `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)` plus one
`"\n"`, written as UTF-8 bytes with no `\r` on every operating system. A NaN or infinity anywhere raises before anything
is written. No absolute local path, no environment variable and no key is ever stored.

| Key | Content |
|---|---|
| `schema_version` | `1`. Any other value is refused when reading (see "Reading and failures") |
| `run_id` | The folder name |
| `generated_at` | UTC, truncated to whole seconds, `YYYY-MM-DDTHH:MM:SSZ`, the same instant as the stamp of the run id |
| `code_version` | `{"commit": <40 hex or "unknown">, "dirty": <true/false/null>}` |
| `family` | The strategy family (below) |
| `trial` | `{"variant_hash", "run_number", "trial_number", "trial_count", "new_variant"}`, all as of this run (below) |
| `spec` | `StrategySpec.to_dict()` of the strategy |
| `evaluation` | `Evaluation.to_dict()`, an object with the keys `assumptions` (`periods_per_year`, `risk_free_rate`), `benchmark`, `relative` and `strategy`. `strategy` has `costs_applied`, `data_hash`, `metrics`, `name`, `risk_flags`; `benchmark` has the same keys and `symbol`; `metrics` is the dictionary of the performance metrics ([metrics.md](metrics.md)); `relative` has `alignment`, `benchmark_return_compared`, `excess_return`, `information_ratio`, `strategy_return_compared`, `tracking_error` |
| `trades` | `TradeStatistics.to_dict()` of the strategy run |
| `costs` | `{"strategy": {...}, "benchmark": {...}}`, each with `costs_applied`, `total_costs`, `gross_final_equity`, `net_return`, `gross_return`, `cost_drag`, `cost_share` |

The six cost numbers are properties of `BacktestResult`, not fields, so they are written out explicitly one by one.
`cost_share` is `null` when the gross return is not positive. Hashes and metrics are stored once, inside `evaluation`;
the index copies the two data hashes for lookup only.

**Not logged:** the price data, the equity, cash, position, weight, signal and trade frames, the list of validation
issues (the report has it), the warm-up details, the environment and the machine. A run can be repeated from the spec and
the same data (the data hash says whether it is the same data), but the journal does not keep the data.

**Code version.** `git rev-parse HEAD` and `git status --porcelain`, run with the package directory as working
directory (no shell, 10 second timeout). The commit is accepted only if the git top-level directory contains this package
at `src/backtest_agent`; an installed copy that happens to sit inside another repository gives `"unknown"`. No git, a
failing git or no repository gives `{"commit": "unknown", "dirty": null}` and never fails the run. `dirty` is true if
there is any change or untracked file that git does not ignore.

## spec.yaml

`yaml.safe_dump` of `spec.to_dict()` with sorted keys. Loading it with the normal spec loader gives a spec with the same
variant hash (a test checks this); it is a readable copy and `run.json["spec"]` stays the source of truth.

## Strategy family

The family of a run is **the signal id of its spec** (`spec.signal.id`), for example `sma_crossover`. There is no special
case: `buy_and_hold` is a registered signal, so a buy-and-hold strategy has the family `buy_and_hold`. The universe, the
period and the costs do not change the family. The benchmark run of an evaluation is never logged: it is a yardstick, not
a trial.

**Limit.** The family is only as good as the signal id. Renaming a signal (or copying it under a new id) starts a new
family with a counter at zero. The journal is an honesty aid for the researcher, not tamper-proof: anyone with write access
to `runs/` can delete a folder, edit `run.json` or rebuild the index and thereby forget trials.

## Runs and trials

- `run_count(family)` is the number of logged runs of the family, repeats included.
- `trial_count(family)` is the number of **distinct variants** among them.
- A **variant** is identified by its **variant hash**.
- `run_number` of a run is its place among the runs of its family (1, 2, 3, ...), assigned when it is logged.
- `trial_number` is the place of its variant among the variants of its family in order of first appearance; a repeat
  keeps the number of its variant. `new_variant` is true when the run introduced its variant.
- `trial_count` inside `run.json` is the number of distinct variants of the family **as of this run**, and the number of
  runs as of this run is `run_number`. Later runs do not change a stored run.

### Variant hash

SHA-256, as 64 hexadecimal characters, of the UTF-8 bytes of the canonical JSON text
`json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`, where `payload` is
`StrategySpec.to_dict()` **without the keys `name` and `description`**. Everything else counts: `schema_version`, the
universe (as written, in order), the period, the data provider, the signal id and its params (with the defaults filled in
by the spec), the execution rules, the sizing, the rebalance rule, the costs, the benchmark and the initial capital.
Not part of it: the name and description, the data hash, `apply_costs`, the metric assumptions, the code version and the
time. So a renamed re-run is a repeat, a re-run on revised data is a repeat, a cost-free run of the same spec is a repeat,
and any change of a number or a symbol in the spec is a new variant.

The variant hash is **not** the 8-character hash of the run id. The run id hash (ADR 0014) identifies the inputs of one
run: it includes the name, both data hashes, the metric assumptions and `costs_applied`, and it is cut to 8 characters.
The variant hash identifies the idea that was tried and is kept at full length in the index.

Worked example: the strategy of the run R3b of [metrics.md](metrics.md) (a buy-and-hold of `A` against `B`, 25 percent
costs). Its canonical payload without `name` and `description` is exactly this text (one line):

```json
{"benchmark":"B","costs":{"commission_bps":1000.0,"min_commission":0.0,"slippage_bps":500.0,"spread_bps":1000.0},"data":{"provider":"yfinance"},"execution":{"allow_same_bar_execution":false,"delay_bars":1,"price":"open"},"initial_capital":1000.0,"period":{"end":"2024-01-08","start":"2024-01-02"},"rebalance":"on_signal","schema_version":1,"signal":{"id":"buy_and_hold","params":{}},"sizing":{"fraction":null,"method":"equal_weight"},"universe":["A"]}
```

and its variant hash is

```
a7b3d3b5b0e2a72814fcb465bc7d203f96ae332c45eff8880ac85e5a9a492cad
```

You can check it with `hashlib.sha256(text.encode("utf-8")).hexdigest()` on the line above. The golden test of the hash
uses this digest, copied from here.

### Counter table

All strategies below have the universe `["A"]`, the benchmark `B`, the period 2024-01-02 to 2024-01-08, the costs
commission 1000, spread 1000 and slippage 500 bps (`commission_bps`, `spread_bps`, `slippage_bps`), an initial capital of 1000, the rebalance rule `on_signal` and the default execution rules, unless
the row says otherwise. The family of the rows S1 to S4 and S6 to S9 is `sma_crossover` (called F1); S5 is a
`buy_and_hold` strategy (F2). The runs are logged in this order, each one second later than the one before. Parameters are
`fast` and `slow` of `sma_crossover`.

| Step | What is run | Family | Same variant as | run_number | trial_number | trial_count as of the run | new_variant | F1 run_count after | F1 trial_count after | F2 run_count after | F2 trial_count after |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S1 | fast 2, slow 3, name "SMA A" | F1 | (new) | 1 | 1 | 1 | yes | 1 | 1 | 0 | 0 |
| S2 | as S1, name "Renamed run", description "Changed text" | F1 | S1 | 2 | 1 | 1 | no | 2 | 1 | 0 | 0 |
| S3 | fast 2, slow 4 (one parameter changed) | F1 | (new) | 3 | 2 | 2 | yes | 3 | 2 | 0 | 0 |
| S4 | as S1 with period start 2024-01-03 | F1 | (new) | 4 | 3 | 3 | yes | 4 | 3 | 0 | 0 |
| S5 | `buy_and_hold` with no params, otherwise as S1 | F2 | (new) | 1 | 1 | 1 | yes | 4 | 3 | 1 | 1 |
| S6 | as S1 again | F1 | S1 | 5 | 1 | 3 | no | 5 | 3 | 1 | 1 |
| S7 | as S1 on different price data (other data hash) | F1 | S1 | 6 | 1 | 3 | no | 6 | 3 | 1 | 1 |
| S8 | as S1 with `apply_costs=False` | F1 | S1 | 7 | 1 | 3 | no | 7 | 3 | 1 | 1 |
| S9 | as S1 with `commission_bps` 900 | F1 | (new) | 8 | 4 | 4 | yes | 8 | 4 | 1 | 1 |

Every row is a logged run, also S8 (its `costs_applied` is false). The same table is in `tests/test_journal_counter.py` as literals.

## run_experiment

`run_experiment` (module `backtest_agent.experiment`) is the one entry point of a standard run:

```python
run_experiment(spec, provider, *, runs_dir, generated_at, reports_dir=None, code_version=None,
               allow_short_warmup=True, apply_costs=True, assumptions=DEFAULT_ASSUMPTIONS) -> Experiment
```

`Experiment` is frozen and has `evaluation`, `record` (the `RunRecord` of the journal) and `report` (`ReportPaths`, or `None`
without `reports_dir`). `generated_at` must be timezone-aware; `code_version=None` means `detect_code_version()`. The
steps, in this order:

1. `evaluate(...)` (pure; the three options go to it). Nothing is on disk yet.
2. If `reports_dir` is given and `reports_dir/<run-id>` already exists, nothing is logged and `FileExistsError` is raised
   ("run id already exists; use a later generated_at" if `runs_dir/<run-id>` exists too, otherwise "report folder already
   exists: ...; nothing was logged").
3. `record_run(...)`: the journal commit. From here on the run counts.
4. If `reports_dir` is given: `write_report(..., run_id=record.run_id, trial=record.trial)` with the same `generated_at`, so
   the folders `runs/<run-id>/` and `reports/<run-id>/` have the same name and the trial numbers of the report are the ones
   of `run.json`. Without `reports_dir` no report is written.

`evaluate()` and `run_backtest()` stay pure and unchanged.

**Errors.**

| Situation | Result |
|---|---|
| `runs/<run-id>/` exists (same spec, data and name in the same second) | `FileExistsError("run id already exists; use a later generated_at: <run-id>")`, the original error is its `__cause__`; nothing is changed or counted |
| any other `FileExistsError` from the journal | passes through unchanged (only the run id error is reworded; it is recognised by the existence of `runs/<run-id>/`) |
| the journal fails (`JournalIndexStale`, `JournalBusyError`, ...) | that error; no report is written |
| the report fails after the journal committed (any exception of `write_report`) | `ExperimentReportError`, with the cause chained |

**A report that fails after logging.** The journal entry stays: a run that was tried counts, whether or not its report
could be written. `ExperimentReportError` is a `RuntimeError` that carries `evaluation`, `record`, `generated_at` and
`reports_dir`, and `error.retry() -> ReportPaths` writes the report again for the same run id, time and trial (it calls
`write_report` with them and logs nothing, so the counters do not change). If `retry()` fails again, the error of
`write_report` propagates as it is (an `OSError`, `FileExistsError` and so on, not another `ExperimentReportError`): the
run is already logged, so there is nothing new to say, and the caller who holds the error can fix the cause (a full disk,
a folder in the way) and call `retry()` again.

## Example: the three example strategies

The three strategies of `strategies/` on the fake provider, in temporary folders. Each one is run, run again unchanged (a
repeat) and run once more with twice the initial capital (a new variant). The families are the signal ids `sma_crossover`,
`momentum_12_1` and `buy_and_hold`, so each family is counted on its own. `tests/test_experiment_examples.py` runs this
code (with a fixed code version) and checks the lines below.

```python
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from backtest_agent.data import FakeProvider
from backtest_agent.experiment import run_experiment
from backtest_agent.spec import load_spec
from backtest_agent.spec.schema import Period

period = Period(start=date(2018, 1, 1), end=date(2019, 12, 31))  # the fake history starts in 2015
start = datetime(2026, 1, 15, 10, 30, 5, tzinfo=UTC)
with TemporaryDirectory() as folder:
    for name in ("sma_crossover", "momentum_12_1", "buy_and_hold"):
        spec = load_spec(f"strategies/{name}.yaml").model_copy(update={"period": period})
        provider = FakeProvider(symbols=spec.universe)
        larger = spec.model_copy(update={"initial_capital": 2 * spec.initial_capital})
        for second, s in enumerate((spec, spec, larger)):
            result = run_experiment(
                s,
                provider,
                runs_dir=Path(folder) / "runs",
                reports_dir=Path(folder) / "reports",
                generated_at=start + timedelta(seconds=second),
            )
            print(result.record.trial)
```

For each family the three reports show (`F` is the family; the wording is in [report.md](report.md), "The trial line"):

| Run | Trials line |
|---|---|
| 1, the spec | `family F: 1 distinct variant in 1 run as of this run. This run is run 1, a new variant (variant 1). Counts cover only runs logged in this journal.` |
| 2, the spec again | `family F: 1 distinct variant in 2 runs as of this run. This run is run 2, a repeat of variant 1. Counts cover only runs logged in this journal.` |
| 3, twice the capital | `family F: 2 distinct variants in 3 runs as of this run. This run is run 3, a new variant (variant 2). Counts cover only runs logged in this journal.` |

(The initial capital is part of the variant hash, so run 3 is a new variant; the name, the data hash and the time are not.)
After the three runs of a family `run_count` is 3 and `trial_count` is 2.

## The index

`runs/index.sqlite`, rollback-journal mode (no `-wal` or `-shm` files; a short-lived `index.sqlite-journal` file exists while a write is running), `PRAGMA user_version = 1`. One table, `runs`, one row per
run: `run_id` (primary key), `generated_at`, `family`, `variant_hash`, `run_number`, `trial_number`, `trial_count`,
`new_variant`, `strategy_name`, `strategy_data_hash`, `benchmark_data_hash`, `code_commit`, `code_dirty`, with a unique
constraint on `(family, run_number)`. The counters are queries: `run_count` is `COUNT(*)` of a family and `trial_count` is
`COUNT(DISTINCT variant_hash)`. The standard library `sqlite3` is the only dependency.

`rebuild_index(runs_dir)` reads every `runs/<run-id>/run.json`, checks it (below) and writes a new index next to the old
one (`index.sqlite.tmp`), then replaces the old index. It **never renumbers**: `run_number` and `trial_number` come from
the stored `run.json`. Deleting a folder and then rebuilding therefore forgets that trial; the index alone is not the
evidence, the folders are.

## One run is all or nothing

`record_run(evaluation, runs_dir, *, generated_at, code_version, busy_timeout=30.0)` does this, in this order:

1. Check the run id (`check_run_id`) and that the folder would be a direct child of `runs/`.
2. Open the index (create it if `runs/` has no run folders), `BEGIN IMMEDIATE`: from here on no other process can
   write to the index, so two processes cannot get the same run or trial number.
3. Under the lock, compare the run folders on disk with the rows of the index. A difference in either direction raises
   `JournalIndexStale` ("call rebuild_index"): an orphan folder (a crash between the folder rename and the commit, or a
   hand-copied folder), a deleted folder, or an index that is missing while folders exist. Silently starting a new index
   would reset the counters, so the journal refuses instead.
4. If `runs/<run-id>/` exists, raise `FileExistsError`. Nothing has been written yet.
5. Count: `run_number`, `trial_number`, `trial_count`, `new_variant`. Build the record and render `run.json` and
   `spec.yaml` in memory (a NaN raises here).
6. Write both files into `runs/.tmp-<run-id>-<random>/`, then rename the folder to `runs/<run-id>/`.
7. Insert the row and `COMMIT`.

If step 5, 6 or 7 fails, the folders this call created are removed first and the transaction is rolled back afterwards,
so a reader that gets the lock never sees the orphan of a failed run. A failed first
call can leave an empty `index.sqlite` (and an empty `runs/`); that is a valid empty journal, and it is never deleted
because another process may have started using it. Every SQLite connection is closed explicitly in a `finally`
(Windows keeps files locked otherwise). The only state a crash can leave behind is a `.tmp-*` folder, which is ignored, or
a complete run folder without a row, which step 3 reports as stale.

**The same run id twice.** The id has a one-second resolution. Running an identical spec on identical data with the same
`generated_at` (to the second) gives the same id and raises `FileExistsError`; nothing is overwritten and nothing is
counted. Use a later `generated_at`. (`run_experiment` turns this into the message "run id already exists; use a later
generated_at", see "run_experiment".)

**A busy index.** If another connection holds the write lock for longer than `busy_timeout` seconds, `record_run` raises
`JournalBusyError` and writes nothing.

## Reading and failures

The read API returns plain frozen dataclasses; the dicts inside a `RunRecord` are not deeply frozen, treat them as
read-only. A missing `runs/` folder is an empty journal, not an error.

| Function | Returns |
|---|---|
| `list_runs(runs_dir, *, family=None, limit=None)` | `tuple[RunSummary, ...]`, newest first by `generated_at`, then `run_id`; `limit` must be 1 or more |
| `get_run(runs_dir, run_id)` | `RunRecord` read from `run.json` (spec, evaluation, trades, costs, trial, code version) |
| `trial_count(runs_dir, family)` | distinct variants, `0` for an unknown family |
| `run_count(runs_dir, family)` | logged runs, `0` for an unknown family |
| `rebuild_index(runs_dir)` | rebuilds the index from the folders; returns the number of runs |

| Situation | Result |
|---|---|
| `runs_dir` does not exist or has no runs | empty results, counters 0 |
| run folders exist but the index is missing, or folders and rows differ | `JournalIndexStale` from `record_run` and from `list_runs`, `trial_count`, `run_count`. A reader that sees a difference first waits (up to 5 seconds) for a running writer and looks again, because a writer is briefly between its rename and its commit; if the writer does not finish in time the reader raises `JournalBusyError`, not `JournalIndexStale` |
| `get_run` of an id that is not a safe name | `ValueError` from `check_run_id` |
| `get_run` of an id without a folder | `RunNotFoundError` |
| `run.json` is not valid JSON, is not an object, lacks a key, has a wrong type, or has a `schema_version` other than 1 | `JournalFormatError` naming the file and the reason; nothing is migrated or guessed |
| the stored `variant_hash` or `family` does not match the stored spec, or the folder name differs from `run_id` | `JournalFormatError` |
| `index.sqlite` has a `user_version` other than 1 | `JournalFormatError` ("call rebuild_index") |
| `rebuild_index` finds a folder without a valid `run.json` | `JournalFormatError` naming every bad folder; the old index is untouched |
| `rebuild_index`: the run numbers of a family are not 1 to n without gaps, or the trial numbers do not follow the order in which variants first appear (also `trial_count` and `new_variant` as of each run) | `JournalFormatError` |

`JournalFormatError` is a `ValueError`. `JournalIndexStale`, `JournalBusyError` and `RunNotFoundError` share the base
class `JournalError`.

## What the journal does not do

It does not stop anyone from running something without logging it. **The rule is a convention plus a visible marker, not a
guarantee:** a standard run goes through `run_experiment`; `evaluate()`, `run_backtest()` and `write_report()` stay legal
without the journal, and a report written without a trial says `Trials: not recorded (this report was not written through
run_experiment)`. The marker makes an unlogged report visible; it cannot force a run to be logged. The journal also does
not group the periods of a variant (a changed period is a new variant), it does not keep the data, and it is not
tamper-proof (see "Strategy family").
