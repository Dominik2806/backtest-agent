# Command line: `bt`

The whole backtester runs from one command, without any agent (F-16). `bt` is a thin layer over code that already exists:
a standard run is `run_experiment` ([journal.md](journal.md)), reading the journal is its read API, the numbers are
printed by the formatters of the report ([report.md](report.md)), and a coded signal is approved and loaded by the code of
[coded-signals.md](coded-signals.md) (`approve_idea`, `approve_code`, `resolve_coded`). `evaluate()` and `run_backtest()`
stay pure and write nothing. The code is in `src/backtest_agent/cli/`; the decisions are in [ADR 0016](adr/0016-command-line.md). The project is educational and not investment advice.

**Status.** Every command described here exists: `run`, `validate` (also `--data`), `data fetch`, `report`,
`journal list`, `journal show`, `journal rebuild` and `approve`. The first seven were delivered in three pull requests
(Phase 9): part 1 `run`, `validate` (spec only) and the journal commands, part 2 `data fetch` and `validate --data`, part 3
`report` (exit code 7) and the README quickstart. `approve`, the exit codes 8 and 9 and the handling of a spec with a `coded`
block in `run`, `validate`, `data fetch` and `report` came with Phase 10 (F-18). **`bt signal check` and the agents are not
built yet** ([coded-signals.md](coded-signals.md), "Not built yet"), so nothing in `bt` runs `cases.yaml` today.

## Starting `bt`

```powershell
uv sync                                    # installs the package and the bt script
uv run bt run strategies/sma_crossover.yaml
uv run bt --help
python -m backtest_agent --help            # the same command line
```

`pyproject.toml` has `[project.scripts] bt = "backtest_agent.cli:main"`. Adding an entry point changes no dependency and
no `uv.lock` (the lock file holds no entry points); the version bump of the release changes `uv.lock`, not this.
`main(argv=None, *, provider_factory, clock, stdout, stderr) -> int` returns the exit code and never calls `sys.exit`;
the script and `__main__.py` wrap it.

## Paths: everything is relative to the current directory

| Default | Used by | Created |
|---|---|---|
| `runs` | the journal: `runs/<run id>/run.json`, `spec.yaml`, `runs/index.sqlite` | by `bt run` |
| `reports` | `reports/<run id>/report.md`, `report.html`, `equity.svg`, `drawdown.svg` | by `bt run` |
| `data/cache` | the Parquet cache of the prices | by the first fetch |
| `approvals` | the approval records `approvals/<id>.json`, the archived code `approvals/code/<sha256>.py` and `approvals/.lock` while an approval runs | by the first `bt approve` |
| `strategies/signals` | the editable files `<id>.py` of coded signals. `bt approve`, `bt run`, `bt validate --data` and `bt data fetch` read the file only as bytes, hash it and compare the hash with the approved hashes; what runs is the archived copy `approvals/code/<sha256>.py`, never this file | never by `bt`: a person or an agent writes the file |

The spec is found by the path you give, so the examples are `strategies/*.yaml` relative to a clone. `bt` also works
from another folder, but then it writes `runs/`, `reports/`, `data/cache/` and `approvals/` into **that** folder and looks for `strategies/signals/` there. **The journal, and so
the trial counter of a strategy family, belongs to one `--runs-dir`**: running the same strategy from two folders gives
two journals with separate counters, and the trial line of a report only counts runs of its own journal. Use the same
folder (or the same `--runs-dir`) for everything you want counted together. `bt run` prints the path of the journal entry
every time. `runs`, `reports` and `data/cache` are git-ignored in this repository; `approvals` and `strategies/signals` are tracked, so they are public ([coded-signals.md](coded-signals.md)).

## Commands

All commands accept `--help`. Every leaf command also accepts `--debug` (print the full traceback of an error on stderr).
`bt --version` prints `bt <version>`.

### `bt run SPEC`

| Option | Default | Meaning |
|---|---|---|
| `--runs-dir DIR` | `runs` | where the run is logged |
| `--reports-dir DIR` | `reports` | where the report is written |
| `--no-report` | off | log the run, write no report: no `Report` line, and the reports folder is not created (`--reports-dir` is then unused) |
| `--no-costs` | off | run without the costs of the spec (`apply_costs=False`); the output says so and the run carries the risk flag `costs_not_applied`. It does not change the variant: a cost-free run of the same spec is a repeat ([journal.md](journal.md)) |
| `--cache-dir DIR` | `data/cache` | the Parquet cache of the prices (relative to the current directory) |
| `--approvals-dir DIR` | `approvals` | a spec with a `coded` block only: where the approvals are read |
| `--strategies-dir DIR` | `strategies/signals` | a spec with a `coded` block only: where the editable `<id>.py` is read (hashed, never executed) |

`--debug` only adds the traceback of an error on stderr; it never changes an exit code.

`bt run` loads and validates the spec, then calls

```python
run_experiment(
    spec,
    provider,
    runs_dir=...,
    generated_at=clock(),
    reports_dir=None if no_report else ...,
    apply_costs=not no_costs,
)
```

so evaluating, logging and reporting happen in the order of [journal.md](journal.md). `generated_at` is read from the
clock here and nowhere else (UTC, timezone-aware, injectable). `allow_short_warmup` and the metric assumptions
(`periods_per_year` 252, risk-free rate 0) keep their defaults. **`allow_short_warmup` is not stored in `run.json` and has
no command line flag**: it is always the default (True), so a short history gives the risk flag `insufficient_warmup` and
a warning, never an error.

**A spec with a `coded` block.** `bt run` first passes the spec through the gate in run mode,
`resolve_coded(spec, approvals_dir=..., strategies_dir=...)` ([coded-signals.md](coded-signals.md), "The gate"), before the
provider is created and before any data is requested. The idea and the code must be approved; the hash of
`strategies/signals/<id>.py` decides which approved code runs, so a file that was edited after the approval is refused, and
so is a spec that pins another hash. A refusal is exit code 8 (`NotApprovedError`, also when there is no record yet); an archive that is missing or
changed, or a record that is not valid, is exit code 5; code that fails the static check, does not load or fails the contract check is exit code 9; nothing is
fetched, logged or written. A run of a coded spec is a standard run: `run_experiment` logs it, the family is the signal id and
`run.json` stores the **resolved** spec, with `coded.brief`, `coded.code_sha256` (64 hex characters) and the params with every
default written out. So an unpinned spec and the same spec pinned to the hash it resolved to are one variant, and a new
approved hash is a new variant, a new trial ([journal.md](journal.md)). `bt run` never writes the spec file. A full example
is at the end of this document.

The provider is `CachedProvider(YFinanceProvider(), cache_dir)`. The spec's `data.provider` can only be `yfinance`
today. History is loaded from `period.start` minus the warm-up of the signal, for the universe and, in a second run, for
the benchmark (below, "The data window").

**Output** (stdout). The block down to the `Risk flags` line is the same for `bt run` and `bt journal show`: both print it
from the stored record (`RunRecord`), so a number looks the same in both and in the report, because it goes through
`reporting/format.py`. `bt run` ends it with the `Journal` and `Report` lines, `bt journal show` with the lines of its own
(below).

```
Run:        <run id>
Strategy:   <name> (family <signal id>)
Trials:     <the Trials sentence of the report header>
Period:     <start> to <end>, <n> bars
Costs:      applied | NOT applied (the result overstates what trading would return)

Metric            Strategy  Benchmark (<symbol>)
<one row each: Total return, CAGR, Sharpe ratio, Maximum drawdown>

Excess return (compared window): <signed percent>

Risk flags: none | strategy run: <codes>; benchmark run: <codes>
Journal:    <runs dir>/<run id>/run.json
Report:     <reports dir>/<run id>/report.md and report.html      (not with --no-report)
```

In the printed summary lines paths always use `/` (an error message, for example from loading the spec, shows a path as the
operating system writes it). The first two lines of the block are `Run` and `Strategy`; each later `Label:` is padded to 12
characters. In the metric table the label column is left-aligned, the two value columns are right-aligned, every column is as
wide as its longest cell and the columns are separated by two spaces. The labels of the metric rows are the labels of the
report; the header of the last column is `Benchmark (` + the benchmark symbol + `)`.

**How numbers look** (the formatters of the report, [report.md](report.md), "Formats"): a percentage has two decimals, a
thousands separator and an ASCII minus sign (`-21.59%`, `288,635.82%`); a ratio (Sharpe) has two decimals; the excess return
alone carries an explicit `+` for a gain; a value that rounds to zero has no sign (never `-0.00%`); `n/a` stands for a metric
that is not defined (for example the Sharpe ratio of one bar, or the excess return when the strategy and the benchmark share
fewer than two dates), never `nan`. Which metrics are undefined when is defined in [metrics.md](metrics.md).

### `bt validate SPEC`

Checks the spec only: the schema, a registered signal id and valid parameters (every problem is listed with its field
path; a spec with a `coded` block has no registered signal before its code is approved, see below). It fetches no data,
writes nothing and needs no network. Output:

```
OK: strategies/sma_crossover.yaml is a valid spec
Name:       SMA crossover on liquid ETFs
Family:     sma_crossover
Universe:   SPY, QQQ, TLT, GLD
Benchmark:  SPY
Period:     2010-01-01 to 2023-12-31
Warm-up:    199 rows
Risk flags: none
```

**A spec with a `coded` block.** Without `--data` it is not looked up in the registry and no code is loaded; `bt validate`
prints the same block with one more line after `Family:`, the `Signal:` line, taken from the approval record
`approvals/<id>.json` alone (`--approvals-dir DIR`, default `approvals`), and the warm-up, which needs the code, is `n/a`.
The three states of the line:

| State | The `Signal:` line |
|---|---|
| the idea `{signal id, brief}` of the spec is not approved (no record, or another brief) | `Signal:     coded, idea not approved` |
| the idea is approved and its code is not: a spec that pins a hash needs that hash approved for the idea, without a pin the latest approved code counts | `Signal:     coded, idea approved, code not approved` |
| the idea and the code are approved | `Signal:     coded, idea and code approved (sha <first 8 hex of the hash>)` |

The exit code is 0 in all three states (a record that is not valid is exit code 5). The line says what the **record** says:
`bt validate` does not read `strategies/signals/<id>.py` and does not read the archive, so a file edited after the approval,
or an archive that was changed, still shows `approved`. The commands that run code check the file (`bt run`,
`bt validate --data`, `bt data fetch`: its hash) or the archive (`bt report`). Output for the first state (the spec of
"Example: a coded signal, from approval to run"):

```
OK: spec.yaml is a valid spec
Name:       Buy and hold A
Family:     hold_a
Signal:     coded, idea not approved
Universe:   A
Benchmark:  B
Period:     2024-01-02 to 2024-01-08
Warm-up:    n/a (coded signal, not loaded)
Risk flags: none
```

**`bt validate SPEC --data [--cache-dir DIR]`** also fetches the two requests of a run through the cache (the same fetch as
`bt data fetch` below, default `--cache-dir data/cache`) and lists the validation result, without running a backtest.
Without `--data` the output above is unchanged and `--cache-dir` is unused. With `--data`, after the lines above and an
empty line, it prints the two data blocks of `bt data fetch` and, under each block, **every validation issue** of that
request (errors first, then warnings, then infos, in the order of [data.md](data.md), "Result, thresholds and errors"; no
limit). An issue line is built from the structured fields of the issue only, never from its free-text message:

```
  <severity, 8 wide><code, 25 wide><target, 12 wide>count <n>[, first <date>[, <date> ...]]
```

`<severity>` is `error`, `warning` or `info`; `<code>` is the code of [data.md](data.md); `<target>` is `SYMBOL.field`, or
`SYMBOL` when the issue has no field, or `-` for a frame-level issue; a cell longer than its width is followed by one
space. `count` and the `first` dates are those of [data.md](data.md) (the dates are printed only where data.md defines
them: not for the frame-level `unsorted_dates` and `duplicate_dates`, and not when the issue has none, like `no_data`).
If the data has validation errors in either request, the exit code is **4**: a run on this data would fail with the same
errors. Everything is printed first (stdout), then stderr gets one line, `bt: error: the data has 3 validation errors
(listed above)` (`1 validation error` for one), and no hint, so no issue is printed twice. Without errors the exit code is 0 (warnings
and infos do not change it). A provider failure, no data or a cache miss is exit code 4 as everywhere, with nothing on stdout.

For a spec with a `coded` block, `--data` needs the warm-up window of the signal, so the spec passes the gate in run mode
first, like in `bt run` (`--approvals-dir DIR` and `--strategies-dir DIR`, defaults `approvals` and `strategies/signals`). Before
the approval that is exit code 8 and nothing is requested from the provider; after it the head block has the real warm-up and
the `Signal:` line `coded, idea and code approved (sha <8 hex>)`, and the approved code was loaded.

### `bt journal list`

| Option | Default | Meaning |
|---|---|---|
| `--family F` | all | only runs of this strategy family (the signal id) |
| `--limit N` | all | at most N runs, N of 1 or more |
| `--runs-dir DIR` | `runs` | the journal |

Newest first (by the time of the run, then the run id). Columns, left-aligned, each as wide as its longest cell, separated by
two spaces, no trailing spaces: the run id, the family, the run number in its family (`RUN`), the variant number (`VARIANT`),
whether the run introduced its variant (`NEW`, `yes` or `no`), the strategy name (longer than 40 characters: the first 37
followed by `...`). Then an empty line and `1 run listed` or `N runs listed`, the number of rows shown. `--family` is applied
first, then `--limit` keeps the newest N. A journal without runs prints `No runs in <runs dir>.` (with a family:
`No runs of family F in <runs dir>.`) and exits 0.

### `bt journal show RUN_ID`

Options `--runs-dir DIR` (`runs`) and `--reports-dir DIR` (`reports`; used only to print the report path if that folder
exists under `--reports-dir`: `<reports dir>/<run id>/report.md`). It prints the block of `bt run` down to the risk flags and
then when the run was made, the code version, both data hashes and the paths.
The run id must be a safe folder name (letters, digits, `.`, `_`, `-`); anything else is a usage error.

### `bt journal rebuild`

Option `--runs-dir DIR` (`runs`). Builds the SQLite index again from the run folders (`rebuild_index`). It is the answer to
a stale index (exit code 5, below). It prints the number of runs found and, if the old index can be read, the number of rows
it had. **If the new index has fewer runs than the old one, those runs are forgotten**: their folders were deleted, and
the trial counter no longer counts them. `bt` then prints a warning on stderr that says so (exit code stays 0):

```
Rebuilt the index in runs: 2 runs found.                         (stdout)
The old index had 3 rows.                                        (stdout, only if the old index could be read)
warning: the new index has 2 runs, the old one had 3: the 1 missing run is forgotten and no longer counts as a trial   (stderr)
```

The old rows are counted directly in the file, because the read API refuses a stale index. The rebuild keeps the numbers of
the stored `run.json` files and refuses (exit code 5, the old index is untouched) when they have a gap: deleting a run from
the middle of a family cannot be repaired by a rebuild, only the last runs of a family can be forgotten.

### `bt data fetch SPEC`

Option `--cache-dir DIR` (`data/cache`); for a spec with a `coded` block also `--approvals-dir DIR` and `--strategies-dir DIR`:
the warm-up window needs the signal, so such a spec passes the gate in run mode first (exit code 8 before the approval, and
nothing is requested from the provider). Fetches exactly the two requests of a run through the cache, so a later `bt run` is
served from it: the universe over `fetch_start` to `period.end`, then the benchmark (`benchmark_spec`) over its own window
("The data window" below). It runs no backtest and writes nothing but the cache. For each request it prints the window, the
rows per symbol, the validation counts and the data hash:

```
Spec:       <name>
Strategy:   <fetch_start> to <period.end> (<buffer_days> days before the period start)
  <symbol>  <n> row(s)                        (one line per symbol of the universe, in spec order)
  Checks:   <n> error(s), <n> warning(s), <n> info(s)
  Data:     <64 hex characters>
Benchmark:  <fetch_start> to <period.end> (<buffer_days> days before the period start)
  <symbol>  <n> row(s)
  Checks:   <n> error(s), <n> warning(s), <n> info(s)
  Data:     <64 hex characters>
```

Rules: the first label is padded to 12 characters like in `bt run`; the lines under a block start with two spaces and the
text is padded to 10 characters, so every value starts in column 12 (a symbol of 10 or more characters is followed by one
space instead, so it never touches its count); counts are `0 errors`, `1 error`, `2 errors` (the same
for `row`, `warning`, `info`); the rows of a symbol are the rows in which it has at least one value ([data.md](data.md),
"Rows with data"); the hash is `hash_frame` of the frame as loaded for that request, warm-up rows included, the same value a
run stores as `strategy` or `benchmark` data hash. Validation errors do **not** change the exit code (the fetch worked;
`bt validate SPEC --data` judges the data): stdout is the same and stderr gets
`warning: N validation error(s); a run would fail; bt validate SPEC --data lists them` (with the path as typed). A provider
failure, no data or a cache miss is exit code 4.

### `bt report RUN_ID`

Writes the report of a logged run again, without logging anything. `run.json` holds dictionaries, not an `Evaluation`, so
the report cannot be rendered from the journal alone. `bt report` therefore re-evaluates the stored spec on the (cached)
data and refuses if the result differs from the journal.

| Option | Default | Meaning |
|---|---|---|
| `--runs-dir DIR` | `runs` | the journal the run is read from (only read; nothing is logged, the index is not opened) |
| `--reports-dir DIR` | `reports` | where the report is written, in `<reports dir>/<run id>/` |
| `--cache-dir DIR` | `data/cache` | the price cache; **it must be the cache the run was made with** |
| `--approvals-dir DIR` | `approvals` | a coded run only: where the record and the archived code of the approved hash are read |
| `--overwrite` | off | replace the files of an existing report folder (`report.md`, `report.html`, the two SVGs); other files in it stay |

**Flow, in this order** (each failure stops there and nothing is written):

1. The run is read from `runs/<run id>/run.json` (not found or unreadable: exit code 5).
2. If `<reports dir>/<run id>` exists and `--overwrite` is not given: exit code 5, **before** any data is fetched. The hint
   names the option: `pass --overwrite to replace the files in it, or choose another --reports-dir`.
3. The spec is rebuilt from `run.json`. A spec that no longer validates (the schema or a signal changed since the run) is
   exit code 3: `the stored spec of run <id> no longer validates (<n> problems):` and the field paths. A stored spec with a
   `coded` block then passes the gate in **stored mode** (`strategies_dir=None`, see "Coded runs" below).
4. The stored settings are read: `costs_applied` of the strategy and of the benchmark must both be `true` or `false` and
   **equal** (the evaluation takes one `apply_costs` flag for both runs, so two different values are a record that cannot be
   reproduced) and the metric assumptions (`periods_per_year`, `risk_free_rate`) must be readable (unknown or invalid keys
   are not); both are exit code 5, a journal problem.
5. `evaluate` runs on the data of `--cache-dir` with the stored `costs_applied` and assumptions (data problems: exit code 4,
   for example an empty cache and no network). It runs exactly the two requests of `bt data fetch`.
6. The record is built again with the stored run id, time, code version and trial, and compared with the stored one. Any
   difference is exit code 7 (below) and nothing is written.
7. The report is written with the stored run id, `generated_at` and trial, never through `run_experiment`: nothing is
   logged, the clock is not read, the journal and the index are not touched, and with unchanged data and spec **`report.md`
   (and the other three files) is identical to the original byte for byte**, including the trial line "as of this run" even
   if more runs of the family were logged since.

**Coded runs.** The archive decides, not the working file: whatever was done to `strategies/signals/<id>.py` since the run
(edited, replaced or deleted) does not matter, and the file is never read or executed. The stored spec must pin
`code_sha256`, and exactly the archived bytes of that hash are checked (hash and static check) and loaded. A record or an
archive that is missing or does not match its hash, an idea that is not in the record and a stored spec without a pin are exit
code 5 (`RecordError`); params that no longer fit the archived code are exit code 3 (`the stored spec of run <id> no longer
validates`); archived code that fails the static check, does not load or fails the contract check is exit code 9. The signal
does not have to be in the registry before: the gate puts it there. Everything after that is as for any run.

**What is compared.** Exactly four of the keys of `run.json` ([journal.md](journal.md)): `spec`, `evaluation` (both data
hashes, all metrics, the alignment, the assumptions), `trades` and `costs`. **Not compared:** the others, that is
`schema_version`, `run_id`, `generated_at`, `code_version`, `family` and `trial` with all its keys (`variant_hash`,
`run_number`, `trial_number`, `trial_count`, `new_variant`): the stored values of these are used to build the fresh record
and the report. The stored `spec` is compared too because it is rebuilt through the current schema: a difference in
`spec` means that the schema or a default changed since the run. Rules per value:

| Stored against fresh | Equal when |
|---|---|
| string (also both data hashes) | the same text |
| `true` / `false` | the same boolean; a boolean is never equal to `1`, `1.0`, `0` or `0.0` |
| `null` | only `null`; `null` against a number is a difference |
| NaN, infinity | never equal to anything, not even to themselves; this rule comes before the formula below, which would call infinity equal to any number; they cannot occur (below) |
| integer against integer | the same integer (exact) |
| integer against float, float against float | `abs(a - b) <= 1e-9 * max(1, abs(a), abs(b))` |
| object against object, list against list | every key / index is equal; a key or index only in the stored record is `missing`, only in the fresh one `extra` |
| any other pair (an object against a number, a string against a number, ...) | never: one difference at that path |

A **data hash** is exactly one of the two paths `evaluation.strategy.data_hash` and `evaluation.benchmark.data_hash`; a key
with the same name anywhere else (for example `spec.params.my_data_hash`) is an ordinary value. If at least one of them differs the run is **"data changed"**, whatever else differs (the other differences
follow from it), and the hint is the one for changed data; if only other things differ it is **"metrics changed"**. Both
are exit code 7. If both hashes differ they are listed in sorted order, the benchmark's first.

**NaN and infinity cannot occur.** `run.json` is canonical JSON written with `allow_nan=False`, so the journal refuses to
store them, and a metric that is not defined is stored as `null` (the Sharpe ratio of a run on flat prices, for example,
is `null` in the journal and `n/a` in the report, and `bt report` reproduces such a run: `null` equals `null`). If a fresh
evaluation ever produced a NaN, building its record would raise like `bt run` would (exit code 1, a bug) before the
comparison; the comparison itself treats a non-finite number as different from everything, so it can never report such a
run as reproduced.

**Paths and order.** A difference is named by its path: keys joined by `.` and list indices as `[i]`, starting with the key
(`evaluation.strategy.metrics.sharpe`, `trades.n_trades`, `spec.universe[1]`); a key that is not made only of the ASCII
letters, digits and `_` (an empty key, a key with a dot, a space, a quote or a non-ASCII letter) is written as a
JSON-quoted index appended without a dot, with JSON escapes and ASCII only (`evaluation.positions["BRK.B"].shares`,
`evaluation["\u00e4"]`). The differences are found in a fixed order: the compared keys in the order above; inside an
object the **union** of the keys of both records, sorted as strings by code point (case-sensitive, so `B` comes before
`a`), a key that only one record has sitting in its sorted place; inside a list the indices; depth first.

A key (or a list index) that only one record has is **one** difference at that path, whatever the value is: the whole value
is printed, the missing side as `(missing)`; a list of another length gives one difference per surplus index. Two values
of different types (an object against a list, a string against a number) are one difference at that path; the search does
not go below it.

The message lists the **data hash differences first** (in the order above), then the others in that order. At most **5**
paths are printed; if there are more, a last path line says `  ... and N-5 more`, where N is the number of differences, and
with 5 or fewer there is no such line. The first line counts all of them (`1 difference`, `2 differences`).

**Exit code 7** (stderr; warnings of the evaluation, if there are any, come first as `warning: ...` lines like for every
command; then the first line, one line per path with the stored and the fresh value, the hint). How a value is printed:

- a float with all its digits (`repr`), because a rounded number would hide a difference at the 1e-9 level; an integer in
  decimal; `null`, `true` and `false` as in JSON;
- a string **without quotes** (so a data hash is a bare word), cleaned like every text of `bt` (see "Windows and
  encodings"): any run of whitespace, line breaks included, becomes one space, characters that XML forbids (such as an
  escape character) become U+FFFD, and an empty or blank string is shown as `(none)`; so a value is always one line;
- a missing side as `(missing)`; an object or a list (only when a whole subtree is the difference, or the types differ)
  as compact JSON with sorted keys, cut after 80 characters with `...`.

```
bt: error: run <run id> no longer reproduces: data changed (<N> differences)
  evaluation.strategy.data_hash: stored <64 hex>, now <64 hex>
  <up to four more paths>: stored <value>, now <value>
  ... and <N-5> more
hint: the stored run is untouched; use the cache the run was made with (--cache-dir) or log a new run with bt run
```

For "metrics changed" the first line ends `metrics changed (<N> differences)` (`1 difference` for one) and the hint is
`the stored run is untouched; the metric code or the stored values changed; log a new run with bt run`.

**Output on success** (stdout; nothing else, nothing on stderr unless the run has a warning):

```
Run:        <run id>
Checked:    spec, evaluation, trades and costs equal the journal record
Journal:    <runs dir>/<run id>/run.json (unchanged)
Report:     <reports dir>/<run id>/report.md and report.html
```

**Caveats.** `--cache-dir` must be the cache of the run, so keep the cache folder of every run you may want to reproduce: a
deleted cache, or a provider that revised an adjusted price since, gives exit code 7 by design (the data hash differs; the
run in the journal stays valid and untouched). A run whose period ends today or later is never cached ([data.md](data.md)),
so `bt report` fetches it live and can see other data than the run did. With no cache and no network the provider fails: exit
code 4 and nothing is written. `bt report` is also the answer to exit code 6 (the run was logged but its report failed): it
writes that report without logging the run twice.

### `bt approve SPEC`

Approves a coded signal in the two steps of [coded-signals.md](coded-signals.md), "What is approved": the idea (`--idea`)
and the code (`--code`). It is a decision of a person. It never imports, compiles or executes anything: it reads the editable
file as bytes, runs the static check (a walk over the syntax tree) and hands the same bytes to the approval code. It needs no
network and requests no data. Exactly one of `--idea` and `--code` is required.

| Option | Default | Meaning |
|---|---|---|
| `--idea` | | approve the idea `{signal id, brief}` of the spec |
| `--code` | | show the code of the signal and its hash; with `--sha`, approve it |
| `--sha HEX8` | | with `--code`: the first 8 hex characters of the hash that the command printed, in capitals or not |
| `--approvals-dir DIR` | `approvals` | where the records and the archived code are written |
| `--strategies-dir DIR` | `strategies/signals` | where the editable `<id>.py` is read |

Neither `--idea` nor `--code`, both, a `--sha` that is not exactly 8 hex characters and `--sha` with `--idea` are usage errors
(exit code 2). `SPEC` gives the signal id and the brief; a spec without a `coded` block is exit code 3, and the command never
edits the spec. The clock is read once, in the command, and is the time of the approval (UTC, whole seconds).

**`--idea`** approves the idea of the spec, appends it to `approvals/<id>.json` and prints (exit code 0):

```
Signal:     rsi_pullback
Idea:       approved (sha 69b960c5)
Approved:   2026-01-15T10:30:05Z
Record:     approvals/rsi_pullback.json
Brief:      Buy the dip.

            Hold while RSI(2) < 10.
            Exit at 50.
```

The brief is printed as stored, not wrapped: the lines after the first start in column 13 and a blank line stays blank. Approving
the same idea again prints `Idea:       already approved (sha 69b960c5)` with the time of the **first** approval, exits 0 and leaves the
record file byte for byte as it was. A changed brief is a new idea, an extra entry; earlier entries and their code stay.

**`--code` without `--sha`** is the review step. In this order: the working file is read once (a regular file of at most
128 KiB; a file that is missing, a folder or too large is exit code 8 with the message of the gate); its line ends are turned
into LF; the idea must be approved (otherwise exit code 8, `the idea of 'x' is not approved; approve the idea first`, and
**nothing** is printed); the static check runs (findings are exit code 9, nothing is printed but the error). Then stdout gets the
facts and the whole file with line numbers, and the command exits with code 8, because the code is not approved yet:

```
Signal:     <id>
File:       <strategies dir>/<id>.py
Size:       <n> bytes, <m> lines
Sha256:     <64 hex characters>
Static:     ok

<line number> | <line of the source>
...
```

stderr then says (the 8 hex characters are the start of the hash):

```
bt: error: the code is not approved yet; confirm it with --sha 2dd4906a
hint: read the code printed above; if you accept it, run: bt approve spec.yaml --code --sha 2dd4906a
```

**File limits.** Approved code is at most 64 KiB, counted after CRLF became LF. A file larger than 128 KiB (twice that,
because CRLF makes a file longer) is not read: exit code 8, `<path> is larger than the limit; approved code is at most 64 KiB`.
A file of up to 128 KiB is read; if its LF-normalised size is more than 64 KiB the static check refuses it: exit code 9, with the
finding `[size]`.

**Size** is the size of the LF-normalised source, the bytes that are hashed: `<n>` is their number and `<m>` the number of lines, a
last line without a newline counting as a line. A file saved with CRLF shows the same size and the same hash as the same file with
LF. The line numbers are right-aligned to the width of the largest one, a line is printed after ` | `, and an empty line is
printed as the number and ` |` without a trailing space. **Every character is printed as ASCII.** The characters from the space (U+0020) to `~` (U+007E) are printed as they
are. U+0000 to U+001F, the tab included (the line feed only ends a line), and U+007F (DEL) are printed as `\xNN`, two lowercase hex
digits. Every other character is printed as `\uXXXX`, four lowercase hex digits, up to U+FFFF, so U+0080 to U+009F too, and as
`\UXXXXXXXX`, eight digits, above U+FFFF. The static check already refuses the characters of the Unicode categories Cc, Cf, Zl and Zp
except the tab, so in practice only the tab and non-ASCII characters of comments and strings appear (U+00A0, the no-break space, is
accepted and printed as `\u00a0`).

**`--code --sha HEX8`** compares the 8 hex characters with the start of the hash of the bytes it has just read. A missing or a
different `--sha` prints the review block again (stdout), writes nothing and is exit code 8; the message names the hash of the
**current** file, and the hint repeats the spec path and the folder options that were given and are not the defaults, in that
order `--approvals-dir`, `--strategies-dir`. A path is put in double quotes if it has a character outside
`[A-Za-z0-9_./\:-]`:

```
bt: error: --sha 00000000 is not the start of the hash of strategies/signals/rsi_pullback.py; the file has sha 2dd4906a
hint: read the code printed above; if you accept it, run: bt approve spec.yaml --code --sha 2dd4906a
```

A matching `--sha` approves exactly the bytes that were read: they are checked by the static check again, archived as
`approvals/code/<sha256>.py` and listed in the record, and the command prints (exit code 0, the second time `already approved`
with the time of the first approval and no byte of the record or the archive changed):

```
Signal:     rsi_pullback
Code:       approved (sha 2dd4906a)
Approved:   2026-01-15T10:31:05Z
Archive:    approvals/code/2dd4906aab2f817dc071472f59a7029e06bfa026f20df4db0e5a620bc7137c8c.py
Record:     approvals/rsi_pullback.json
Pin:        not set (signal.coded.code_sha256: 2dd4906aab2f817dc071472f59a7029e06bfa026f20df4db0e5a620bc7137c8c)
```

The `Pin:` line compares the spec with the hash: `not set (signal.coded.code_sha256: <64 hex>)` (the line to add if you want to
pin the code), `matches`, or `differs (spec pins <8 hex>)`. The spec file is never edited. An approval takes `approvals/.lock`
([coded-signals.md](coded-signals.md), "The lock"): if it exists, the command is exit code 8 and writes nothing.

The exit codes of `bt approve`: 0 approved (or already approved); 2 arguments; 3 no `coded` block; 5 a record that is not valid;
8 the idea is not approved, the file cannot be read or is too large, an approval is running (`.lock`), `--sha` is missing or
wrong; 9 the static check refuses the file (the bytes are refused before they are decoded or printed, so a file that is not
UTF-8 is a finding too).

**Who runs `bt approve`.** A person, and a person has to read the printed code before the second command: nothing in the
command checks that anybody did. An agent that has a shell could run both commands itself, and then the approval would mean
nothing, so the agent that writes a signal must not run `bt approve`. Today only the discipline of the person enforces that. A later pull
request adds a rule that denies the command to the agents; that rule does not exist yet. The static check is a tripwire and an
approval does not make code safe: it means that a person read this code ([coded-signals.md](coded-signals.md)).

**Known limits.**

- A backslash in the code is printed as it is, so code that contains the six characters `\u00e9` and code that contains the
  character `é` look the same in the review (`\u00e9`).
- The reason in `cannot be read (...)` is the operating system's own text and follows its language.
- The hint puts a path in double quotes when it has an unusual character. PowerShell expands `$` and the backtick inside double
  quotes, so a path with one of them has to be quoted by hand (single quotes) before the command of the hint is pasted.
- The review is on stdout and the exit code is 8 by design: it says that the code is not approved yet, not that something broke.

## Exit codes

| Code | Meaning | Caused by |
|---|---|---|
| 0 | success (also `--help`, `--version`, an empty journal) | |
| 1 | unexpected error: a bug, or an operating system error such as a folder that cannot be written | any other exception |
| 2 | usage error: unknown command or option, a missing argument, `--limit 0`, an unsafe run id; `bt approve` without exactly one of `--idea` and `--code`, a malformed `--sha`, `--sha` with `--idea` | argparse, `UsageError` |
| 3 | the spec is invalid or its file cannot be read; `bt report`: the spec stored in the run no longer validates (also when the params no longer fit the archived code of a coded run); `bt approve`: the spec has no `coded` block | `SpecError`, `UnknownSignalError`, `StoredSpecError` |
| 4 | data problem: the provider failed, no data, validation errors in the data, a cache miss offline | `DataError` and subclasses (validation errors of a run: the first 10 are listed, then `... and N more`; `bt validate --data` prints all of them on stdout and one line on stderr); any other exception of a provider call |
| 5 | journal problem or an existing output: stale or busy index, an index file that is not a database (for example garbage bytes), unreadable `run.json`, run not found, run id exists, report folder exists (also for `bt report`, whose hint names `--overwrite`), stored `costs_applied` values that differ or stored metric assumptions that cannot be read (`bt report`); approvals: an approval record that is not valid, whatever is wrong with it (not JSON, not an object with the keys of a record, another `schema_version`): exit code 5 in every command that reads the record, that is `bt approve` and `bt validate` (which raise `ApprovalFormatError`) and `bt run`, `bt validate --data`, `bt data fetch` and `bt report` (which pass the gate and report it as `RecordError`; the hint differs, see the table of hints), an archived code that is missing or does not match its hash (`bt run`, `bt validate --data`, `bt data fetch`, `bt report`), and in stored mode (`bt report`) a record that is missing, an idea that is not in it and a stored coded spec without a pin | `JournalError`, `JournalFormatError`, `FileExistsError` (`ReportFolderExistsError` for `bt report`), `sqlite3.Error` (the index cannot be read), `RecordError`, `ApprovalFormatError` |
| 6 | the run was logged but its report failed; the message names the run id and the hint is `bt report RUN_ID` | `ExperimentReportError` |
| 7 | `bt report` found changed data or changed metrics: the re-evaluated record differs from the journal record | `RunChangedError` |
| 8 | not approved or not confirmed: the idea or the code of a coded spec is not approved, the working file has another hash than the approved ones or than the pin of the spec, it cannot be read or is too large (`bt run`, `bt validate --data`, `bt data fetch`, `bt approve`); an approval error (another approval is running: `.lock`; `bt approve --code` for an idea that is not approved); `bt approve --code` without `--sha`, or with another one than the hash of the file | `NotApprovedError`, `ApprovalError`, `ConfirmationError` |
| 9 | code that is rejected: the static check, the contract check at run time (**every** signal, a built-in too; it was code 1 before Phase 10), a coded signal that does not load or whose params model is unusable (`GateError`). `CasesError` is mapped here too; it is raised only by `bt signal check`, which is not built yet | `StaticCheckError`, `SignalContractError`, `GateError`, `CasesError` |
| 130 | interrupted with Ctrl-C | `KeyboardInterrupt` |

The checks run in this order: interrupt, report failed, usage (`UsageError`), spec (the stored spec of `bt report` first), approval records (`RecordError`, `ApprovalFormatError`: code 5), refusals (`ConfirmationError`, `NotApprovedError`, `ApprovalError`: code 8), rejected code (`StaticCheckError`, `CasesError`, `GateError`, `SignalContractError`: code 9), run changed, data, journal, everything else. The order matters because
`JournalFormatError` is both a `JournalError` and a `ValueError` (so it is code 5, while any other `ValueError`, a bug for
example, is code 1), `ExperimentReportError` is a `RuntimeError`, `RecordError` and `NotApprovedError` are kinds of `GateError` (code 9) and
`ApprovalFormatError` is a kind of `ApprovalError` (code 8), so each comes before its base class, and `SignalContractError` is a
`ValueError` that is code 9, not 1. Code 4 versus 1: only an exception raised inside a call
into the data provider becomes code 4 (the guard below); the same exception raised anywhere else is code 1. Code 5, which of
the messages: `run_experiment` checks the report folder first, so a report folder alone gives "report folder already exists",
and both folders together give "run id already exists". A run that was interrupted before the
journal committed leaves nothing behind (`record_run` rolls back); one that failed with code 6 stays in the journal and
counts as a trial.

## Errors

stdout carries results only; stderr carries errors and warnings. An error is one block on stderr and no traceback:

```
bt: error: <what went wrong>
hint: <what to do>
```

The first line is the message, the second the hint (not every error has a hint; a spec error lists its field paths between
the two lines).

`--debug` prints the full traceback (with the chained cause) before the block. The hints:

| Situation | Hint |
|---|---|
| stale index, or an index that cannot be read (not a database) | run `bt journal rebuild --runs-dir <dir>`; a run folder that was deleted is forgotten by the rebuild. `show` reads only `run.json` and works anyway; an empty index file counts as a missing one (stale) |
| busy index | another process is writing to the journal; try again in a moment |
| run id exists | wait one second and run again (the run id has a resolution of one second); nothing was changed or counted |
| report folder exists, run not logged | remove that folder or choose another `--reports-dir`; nothing was logged |
| run not found | `bt journal list` shows the runs of this journal |
| data problem | check the symbols, the dates and your connection (`--cache-dir`) |
| spec invalid | the fields are described in `docs/strategy-spec.md`; the message already lists every field path |
| report failed after logging | `bt report <run id>` writes it again without logging the run twice |
| report folder exists, `bt report` | pass `--overwrite` to replace the files in it, or choose another `--reports-dir` |
| stored spec no longer validates | the run folder is untouched; the spec schema or a signal changed since the run |
| run changed, data (`bt report`) | the stored run is untouched; use the cache the run was made with (`--cache-dir`) or log a new run with `bt run` |
| run changed, metrics (`bt report`) | the stored run is untouched; the metric code or the stored values changed; log a new run with `bt run` |
| a refusal: code or idea not approved, the file cannot be read, an approval error | `approvals are made with bt approve; see docs/coded-signals.md` |
| `--sha` missing or wrong | `read the code printed above; if you accept it, run: bt approve SPEC --code --sha <8 hex>` (repeats `--approvals-dir` and `--strategies-dir` when they were given and are not the defaults) |
| in `bt run`, `bt validate --data`, `bt data fetch` and `bt report` (the gate, `RecordError`): a record or an archive that is missing or changed, an idea that is not in the record or a stored spec without a pin in stored mode, **and an approval record that is not valid** (the message line then says what is wrong with it: `is not valid JSON in UTF-8`, `must be an object with exactly the keys ...`, `schema_version must be 1, got 2`) | `the approvals folder (--approvals-dir) has to hold the record and the archived code this run used` (the same text in a first `bt run`, when there is no earlier run) |
| in `bt validate` and `bt approve` (they read the record themselves, `ApprovalFormatError`): an approval record that is not valid | `an approval record is not valid; restore it from version control (docs/coded-signals.md)` |
| code rejected (static check, load, examples) | `the rules a coded signal has to follow are in docs/coded-signals.md` |
| a signal breaks the signal contract | `a signal has to follow the signal contract (docs/strategy-spec.md)` |
| `--sha` with `--idea` | `bt approve --help describes the arguments` |

**The provider guard.** Only the calls into the data provider are wrapped: any exception that is not a `DataError`
(a connection error of the HTTP layer, for example) becomes a `DataError` ("the data provider failed (Type: message)") with the
original as its cause. The engine, the journal and the report are never wrapped, and `KeyboardInterrupt` passes through.

**Warnings.** Every warning raised during a command (for example `InsufficientWarmupWarning` when the provider has less
history than the signal needs) is printed once, as `warning: <message>`, on stderr, without file paths. Nothing is hidden.

## Windows and encodings

The words of `bt` itself are plain ASCII. Text that comes from a spec or from data (names, symbols, messages) goes through
the same cleaning as the report (`reporting.model.text`: whitespace collapsed, control characters replaced), so it cannot
break a line or send a terminal escape. `bt` does **not** force UTF-8: on a console with another code page (cp1252, cp437)
that would print mojibake, and PowerShell 5.1 pipes use the console encoding. Instead both streams are set to
`errors="backslashreplace"`: a character the console can show is printed as it is, any other is printed as `\uXXXX`, and
nothing can raise a `UnicodeEncodeError`. The report files are UTF-8 (the writer). The commands work in PowerShell 5.1
(chain with `;`, no `&&`).

## The data window

`run_backtest` loads `get_prices(universe, fetch_start, period.end)` with

```
rows_needed = warmup_rows + delay_bars
buffer_days = 2 * rows_needed + 14
fetch_start = period.start - buffer_days days
```

The benchmark is a second run of `benchmark_spec(spec)` (symbol `benchmark`, signal `buy_and_hold`, warm-up 0) with its own
window: for delay 1 it is `2 * 1 + 14 = 16` days before `period.start`. `bt data fetch` and `bt validate --data` fetch
exactly these two requests, so a later `bt run` is served from the cache. Requests whose end is today or later are never
cached ([data.md](data.md)).

The formula is `warmup_window(spec)` and the load is `load_history(spec, provider)`, both in `engine/history.py`
([engine.md](engine.md)); `bt` calls them and nothing else, for the spec and for `benchmark_spec(spec)`. Two worked
windows: the benchmark above (delay 1, warm-up 0, `N = 1`, 16 days); and `strategies/sma_crossover.yaml` with `slow: 200`,
whose warm-up is 199 rows (`bt validate` prints `Warm-up:    199 rows`) plus `delay_bars: 1`: `N = 199 + 1 = 200`,
`buffer_days = 2 * 200 + 14 = 414`, so for `period.start` 2010-01-01 the first day of the request is
`2010-01-01 - 414 days = 2008-11-13`.

## Example: one run, with the arithmetic

The tests run this with an injected provider (no network). It is the world of fixture R3b in [metrics.md](metrics.md) and
H23 in [engine.md](engine.md): a buy-and-hold strategy on `A` against the benchmark `B`, with costs of 25 percent
(commission 1000, half-spread 1000, slippage 500 bps) so that the arithmetic stays visible.

`strategy.yaml`:

```yaml
schema_version: 1
name: Buy and hold A
universe: [A]
period: {start: 2024-01-02, end: 2024-01-08}
data: {provider: yfinance}
signal: {id: buy_and_hold, params: {}}
execution: {delay_bars: 1, price: open, allow_same_bar_execution: false}
sizing: {method: equal_weight}
rebalance: on_signal
costs: {commission_bps: 1000, spread_bps: 1000, slippage_bps: 500}
benchmark: B
initial_capital: 1000
```

Prices (daily bars on 2024-01-02, 03, 04, 05 and 08; the warm-up of the signal is 0 rows, so no bar before `period.start` is
needed, although the run still asks the provider for 16 days before it, see "The data window"):

| | open | close |
|---|---|---|
| A | 100, 100, 110, 121, 133.1 | 100, 110, 121, 133.1, 146.41 |
| B | 50, 50, 55, 49.5, 54.45 | 50, 55, 49.5, 54.45, 49.005 |

The command, with the clock at 2026-01-15 10:30:05 UTC, in an empty folder:

```powershell
bt run strategy.yaml
```

The arithmetic (the detail is in R3b and H23). The three cost numbers add up to `1000 + 1000 + 500 = 2500` bps, 25 percent of
the traded value, charged as cash on top of every buy. An order is filled at the open of the bar after the signal
(`delay_bars: 1`, `price: open`); a buy that cash plus its own fee cannot cover is scaled down by one factor; shares are
fractional in general (here the factor happens to give whole shares). The statistics use the bar returns of the equity path,
including the first bar (measured against the initial capital, so 0 here) and, for the drawdown, the initial capital as the
first peak:

- **Strategy.** The signal of 2024-01-02 is executed at the open of 2024-01-03, price 100. The wish is 10 shares (1000 /
  100); buying them costs `1000 + 0.25 * 1000 = 1250`, more than the cash 1000, so every buy is scaled by `1000 / 1250 = 0.8`:
  8 shares, notional 800, fee 200, cash 0. Equity: `1000` (Jan 2), `8 * 110 = 880`, `8 * 121 = 968`, `8 * 133.1 = 1064.8`,
  `8 * 146.41 = 1171.28`. Returns `[0, -0.12, 0.1, 0.1, 0.1]`.
  Total return `1171.28 / 1000 - 1 = 0.17128` -> **17.13%**. Maximum drawdown (peak 1000, trough 880): `-0.12` ->
  **-12.00%**.
- **Benchmark B**, the same rules and costs: price 50, 20 shares wanted, scaled by 0.8 to 16 shares. Equity `1000`,
  `16 * 55 = 880`, `16 * 49.5 = 792`, `16 * 54.45 = 871.2`, `16 * 49.005 = 784.08`. Returns `[0, -0.12, -0.1, 0.1, -0.1]`.
  Total return `784.08 / 1000 - 1 = -0.21592` -> **-21.59%**; maximum drawdown (peak 1000, trough 784.08) the same, **-21.59%**.
- **Annualization** uses 252 bars a year, counted in bars: `years = 5 / 252`. CAGR is `(1 + T)^(252 / 5) - 1`. Strategy:
  `1.17128^50.4 - 1 = 2886.358248844...` -> **288,635.82%** (five bars annualize to a meaningless number; that is the formula, not
  a bug). Benchmark: `0.78408^50.4 - 1 = -0.99999526...` -> **-100.00%**.
- **Sharpe** is `mean(r) / std(r) * sqrt(252)` with the sample standard deviation (n - 1) and a risk-free rate of 0. Strategy:
  mean `0.036`, deviations `-0.036, -0.156, 0.064, 0.064, 0.064`, sum of squares `0.03792`, variance `0.03792 / 4 = 0.00948`, std
  `0.097365...`; `0.036 / 0.097365... * 15.8745... = 5.8694...` -> **5.87**. Benchmark: mean `-0.044`, std `0.093166...`;
  `-0.044 / 0.093166... * 15.8745... = -7.4970...` -> **-7.50**.
- **Excess return** over the compared window (R3b): `0.17128 - (-0.21592) = 0.3872` -> **+38.72%**.
- **Trials.** The first run of the family `buy_and_hold` is run 1 and a new variant ([journal.md](journal.md)).
- **Risk flags.** The costs are not zero and are applied, the delay is 1: none.

Output. The last 8 characters of the run id are a hash of the inputs of the run (the spec including its name, both data
hashes, the metric assumptions and whether costs were applied), not of the time; they are written `HHHHHHHH` here, and the
second run below has the same eight characters as the first (same inputs), only the time differs ([ADR 0014](adr/0014-report.md)):

```
Run:        20260115T103005Z-buy-and-hold-a-HHHHHHHH
Strategy:   Buy and hold A (family buy_and_hold)
Trials:     family buy_and_hold: 1 distinct variant in 1 run as of this run. This run is run 1, a new variant (variant 1). Counts cover only runs logged in this journal.
Period:     2024-01-02 to 2024-01-08, 5 bars
Costs:      applied

Metric               Strategy  Benchmark (B)
Total return           17.13%        -21.59%
CAGR              288,635.82%       -100.00%
Sharpe ratio             5.87          -7.50
Maximum drawdown      -12.00%        -21.59%

Excess return (compared window): +38.72%

Risk flags: none
Journal:    runs/20260115T103005Z-buy-and-hold-a-HHHHHHHH/run.json
Report:     reports/20260115T103005Z-buy-and-hold-a-HHHHHHHH/report.md and report.html
```

Exit code 0. With `--no-costs` the line `Costs:      NOT applied (the result overstates what trading would return)` appears, the
risk flags line reads `Risk flags: strategy run: costs_not_applied; benchmark run: costs_not_applied`, and the numbers are
the cost-free ones of R3c (strategy `1464.1 / 1000 - 1` = 46.41%, benchmark `980.1 / 1000 - 1` = -1.99%, excess +48.40%).

Running the same command again one second later (clock 10:30:06) is a repeat of variant 1, because two runs are the same variant when their specs are equal apart from the name and the
description ([journal.md](journal.md), "Variant hash"); a changed number or symbol, or twice the initial capital, is a new
variant:

```
Trials:     family buy_and_hold: 1 distinct variant in 2 runs as of this run. This run is run 2, a repeat of variant 1. Counts cover only runs logged in this journal.
```

Running it again with the same clock (10:30:05) is refused: nothing is logged twice, stdout is empty, the exit code is 5 and
stderr says

```
bt: error: run id already exists; use a later generated_at: 20260115T103005Z-buy-and-hold-a-HHHHHHHH
hint: wait one second and run again (the run id has a resolution of one second)
```

`bt journal list` after the first run:

```
RUN ID                                    FAMILY        RUN  VARIANT  NEW  NAME
20260115T103005Z-buy-and-hold-a-HHHHHHHH  buy_and_hold  1    1        yes  Buy and hold A

1 run listed
```

`bt journal show 20260115T103005Z-buy-and-hold-a-HHHHHHHH` prints the block of `bt run` down to the `Risk flags` line and
then (the `Report:` line only if the report folder exists):

```
Generated:  2026-01-15 10:30:05 UTC
Code:       <12 characters of the commit> (clean)     (or: (has uncommitted changes), or: (state unknown); exactly one)
Data:       strategy <64 hex characters>
            benchmark <64 hex characters>
Spec:       runs/<run id>/spec.yaml
Journal:    runs/<run id>/run.json
Report:     reports/<run id>/report.md and report.html
```

After the second run (one second later) `bt journal list` prints, newest first (the 8 hash characters are the same in both
ids, the third column is the run number, `NEW` is `no` for a repeat):

```
RUN ID                                    FAMILY        RUN  VARIANT  NEW  NAME
20260115T103006Z-buy-and-hold-a-HHHHHHHH  buy_and_hold  2    1        no   Buy and hold A
20260115T103005Z-buy-and-hold-a-HHHHHHHH  buy_and_hold  1    1        yes  Buy and hold A

2 runs listed
```

## Example: the data commands, with the arithmetic

The same world as above (`strategy.yaml` of "Example: one run"), so the tests can run it without the network. The provider
holds one frame with the symbols `A` and `B`. **The frame, exactly** (every value is `float64`): five rows, on the dates
2024-01-02, 2024-01-03, 2024-01-04, 2024-01-05 and 2024-01-08 (Tuesday to Monday; there is no row before 2024-01-02). For
each symbol the `open` and `close` columns are the table of the example above; for **every row** `high = max(open, close)`
and `low = min(open, close)`, and `volume = 1000.0` where a close exists. A request returns the requested symbols with all
five fields (`open`, `high`, `low`, `close`, `volume`) and the rows between its first and last day, here all five. The data
hash of a request is [`hash_frame`](data.md#data-hash) of that returned frame: for the request of `A` it is the hash of a
frame with one symbol, five rows and five columns, and likewise for `B`.

```powershell
bt data fetch strategy.yaml
```

The strategy has warm-up 0 and `delay_bars: 1`, so `N = 0 + 1 = 1`, `buffer_days = 2 * 1 + 14 = 16` and the request starts
`2024-01-02 - 16 days = 2023-12-17` (a Sunday) and ends on `period.end`, 2024-01-08. The benchmark is a buy-and-hold with warm-up
0 and the same delay, so its request has the same window. The requests the provider receives are exactly
`(A, 2023-12-17, 2024-01-08)` and `(B, 2023-12-17, 2024-01-08)`. The data starts on 2024-01-02: the business days (Monday to
Friday) from 2023-12-17 up to, not including, 2024-01-02 are December 18 to 22 (5), December 25 to 29 (5) and January 1 (1),
11 in all, more than the 3 that [data.md](data.md) allows, so each symbol gets one `starts_late` info (`count` 11) and no
other check fires: the data ends on the requested last day, high and low follow open and close, the volume is 1000, no day
is missing between two rows, the largest move is 10 percent and no close repeats. Output (exit code 0, stderr empty):

```
Spec:       Buy and hold A
Strategy:   2023-12-17 to 2024-01-08 (16 days before the period start)
  A         5 rows
  Checks:   0 errors, 0 warnings, 1 info
  Data:     61669f6e7476623e1289ff7dad8c8b767f36be44961c05ec4def3f45c15dd090
Benchmark:  2023-12-17 to 2024-01-08 (16 days before the period start)
  B         5 rows
  Checks:   0 errors, 0 warnings, 1 info
  Data:     ff487f9000d166df03fa5e84640c7524f7414b58173ed654e33fab7f1df0b094
```

The two hashes were computed with `hashlib` from the layout of [data.md](data.md) alone and are the `strategy` and
`benchmark` data hashes that `bt run` stores for this spec.

**A window that differs between the two requests.** The same command for a spec whose name is `SMA 2/4 on A` and whose
signal is `sma_crossover` with `fast: 2` and `slow: 4` (everything else as above). The slow average needs `4 - 1 = 3`
warm-up rows, `N = 3 + 1 = 4`, `buffer_days = 2 * 4 + 14 = 22`, so the request of `A` starts `2024-01-02 - 22 days =
2023-12-11` (a Monday); the benchmark keeps its 16 days. The returned frames are the same five rows, so the hashes are the
same; the `starts_late` of `A` now counts 16 business days (December 11 to 15, 18 to 22, 25 to 29 and January 1) instead of
11, which `bt validate --data` would print:

```
Spec:       SMA 2/4 on A
Strategy:   2023-12-11 to 2024-01-08 (22 days before the period start)
  A         5 rows
  Checks:   0 errors, 0 warnings, 1 info
  Data:     61669f6e7476623e1289ff7dad8c8b767f36be44961c05ec4def3f45c15dd090
Benchmark:  2023-12-17 to 2024-01-08 (16 days before the period start)
  B         5 rows
  Checks:   0 errors, 0 warnings, 1 info
  Data:     ff487f9000d166df03fa5e84640c7524f7414b58173ed654e33fab7f1df0b094
```

**`bt validate strategy.yaml --data` with a broken frame.** The frame of `A` differs from the one above in two values: its
`close` of 2024-01-04 is missing (NaN; `open` 110, `high` 121, `low` 110 and `volume` 1000.0 of that row stay as in the
frame above) and its `volume` of
2024-01-05 is missing (NaN). `B` is unchanged. The row of 2024-01-04 still has data (its `open`), so `A` still has 5 rows.
A row with data and a missing close is `nan_in_history` (an error, field `close`, count 1, first date 2024-01-04); a row
with data and a missing volume is `nan_volume` (a warning, field `volume`, count 1, first date 2024-01-05); `starts_late` is
as before. The hash of the frame of `A` changes (a NaN is hashed as the one canonical NaN, see [data.md](data.md)). Output
on stdout:

```
OK: strategy.yaml is a valid spec
Name:       Buy and hold A
Family:     buy_and_hold
Universe:   A
Benchmark:  B
Period:     2024-01-02 to 2024-01-08
Warm-up:    0 rows
Risk flags: none

Strategy:   2023-12-17 to 2024-01-08 (16 days before the period start)
  A         5 rows
  Checks:   1 error, 1 warning, 1 info
  Data:     2717f62b8122d8a9189132458fc9ede5f1ae8ff2ee6e2927c7a51d2e7f6b7e49
  error   nan_in_history           A.close     count 1, first 2024-01-04
  warning nan_volume               A.volume    count 1, first 2024-01-05
  info    starts_late              A           count 11, first 2024-01-02
Benchmark:  2023-12-17 to 2024-01-08 (16 days before the period start)
  B         5 rows
  Checks:   0 errors, 0 warnings, 1 info
  Data:     ff487f9000d166df03fa5e84640c7524f7414b58173ed654e33fab7f1df0b094
  info    starts_late              B           count 11, first 2024-01-02
```

stderr is `bt: error: the data has 1 validation error (listed above)` and the exit code is 4. `bt data fetch strategy.yaml` on the
same data prints the same two blocks without the issue lines (the `Spec:` line first), exits 0, and stderr is
`warning: 1 validation error(s); a run would fail; bt validate strategy.yaml --data lists them`.

## Example: `bt report`, unchanged and with other prices

After the first run of "Example: one run" (run id `20260115T103005Z-buy-and-hold-a-HHHHHHHH`), the report folder is deleted and
the same provider is used again:

```powershell
bt report 20260115T103005Z-buy-and-hold-a-HHHHHHHH
```

```
Run:        20260115T103005Z-buy-and-hold-a-HHHHHHHH
Checked:    spec, evaluation, trades and costs equal the journal record
Journal:    runs/20260115T103005Z-buy-and-hold-a-HHHHHHHH/run.json (unchanged)
Report:     reports/20260115T103005Z-buy-and-hold-a-HHHHHHHH/report.md and report.html
```

Exit code 0, stderr empty. `report.md`, `report.html`, `equity.svg` and `drawdown.svg` are byte for byte the files of the
first run, `run.json` and `runs/index.sqlite` are unchanged, and no run was logged. If the run was the second of its family
and a third was logged since, the trial line still says "run 2" ("as of this run").

With another price instead: the provider returns the same frame except that the last `close` of `A` (2024-01-08) is `150`
instead of `146.41` (the `high` of that row follows, `150`; its `low` stays `133.1`, the open). The frame of `A` then hashes to
`84cff02fdbf6860d463ec79c2cebba456c5dac2a6331d47831eb2f9602ea01d7`, and the metrics move: the strategy's last equity is `8 * 150 =
1200`, its total return `1200 / 1000 - 1 = 0.2` and the excess return over the benchmark `0.2 - (-0.21592) = 0.41592`.
Exit code 7, stdout empty, stderr. The program finds N = 18 differences: the strategy's data hash, the four changed entries
of `evaluation.relative` (`excess_return`, `information_ratio`, `strategy_return_compared`, `tracking_error`; the
benchmark's entries and `alignment` do not change), eight metrics of `evaluation.strategy.metrics` (`best_month`, `cagr`,
`calmar`, `sharpe`, `sortino`, `total_return`, `volatility`, `worst_month`) and five numbers of `costs.strategy`
(`cost_drag`, `cost_share`, `gross_final_equity`, `gross_return`, `net_return`). Sorted as in the paragraph **Paths and order** of the section `bt report RUN_ID` (inside `evaluation`: `assumptions`, `benchmark`, `relative`, `strategy`),
with the data hash first, the first five are the hash and the four `relative` entries, so `excess_return` is the second
line and 13 (N-5) are left over: the eight `evaluation.strategy.metrics.*` entries in the order just given, then the five
`costs.strategy.*` entries in the order just given (1 + 4 + 8 + 5 = 18). By hand only the hash, the excess return and `strategy_return_compared` (0.17128 before,
0.2 now) are derived here; the values of `information_ratio` and `tracking_error` follow the formulas of
[metrics.md](metrics.md) and are the program's:

```
bt: error: run 20260115T103005Z-buy-and-hold-a-HHHHHHHH no longer reproduces: data changed (18 differences)
  evaluation.strategy.data_hash: stored 61669f6e7476623e1289ff7dad8c8b767f36be44961c05ec4def3f45c15dd090, now 84cff02fdbf6860d463ec79c2cebba456c5dac2a6331d47831eb2f9602ea01d7
  evaluation.relative.excess_return: stored 0.3872, now 0.41591999999999985
  evaluation.relative.information_ratio: stored 11.59310139695154, now 11.554740195295285
  evaluation.relative.strategy_return_compared: stored 0.1712800000000001, now 0.19999999999999996
  evaluation.relative.tracking_error: stored 1.738965209542734, now 1.8623870882809872
  ... and 13 more
hint: the stored run is untouched; use the cache the run was made with (--cache-dir) or log a new run with bt run
```

(The derivation gives `0.41592`; the digits of `0.41591999999999985` past the twelfth come from the program, from the
rounding of binary floating point, not from the derivation. A float is printed with all its digits because the
comparison works at the 1e-9 level.) No report folder is created.

## Example: a coded signal, from approval to run

The tests run this with an injected provider (no network). It is the world of "Example: one run" (`strategy.yaml`, fixture
R3b) with one change: the signal is `hold_a`, a coded signal that does what `buy_and_hold` does, so the numbers must be the
numbers of that example. `spec.yaml` is `strategy.yaml` with this signal block:

```yaml
signal:
  id: hold_a
  params: {}
  coded:
    brief: "Hold A for the whole period."
```

`strategies/signals/hold_a.py` (13 lines, 426 bytes with LF line ends, the file that the review below prints; the signal
holds every symbol from its first trading row on):

```text
"""Buy and hold, written as a coded signal."""
import pandas as pd
from pydantic import Field
from backtest_agent.spec.signals import SignalParams, per_symbol_signal, register_signal


class Params(SignalParams):
    scale: float = Field(1.0, ge=0.0, le=1.0)


@register_signal("hold_a", params=Params)
def hold_a(prices, params):
    return per_symbol_signal(prices, lambda close: pd.Series(params.scale, index=close.index))
```

**1. The idea** (clock 2026-01-15 10:30:05 UTC). `bt validate spec.yaml` first says `Signal:     coded, idea not approved`
(the block of "bt validate" above) and `bt run spec.yaml` is refused with exit code 8. Then:

```powershell
bt approve spec.yaml --idea
```

```
Signal:     hold_a
Idea:       approved (sha bc1586a4)
Approved:   2026-01-15T10:30:05Z
Record:     approvals/hold_a.json
Brief:      Hold A for the whole period.
```

**2. The review** (clock 10:31:05). The person reads the code, then asks for it:

```powershell
bt approve spec.yaml --code
```

stdout (exit code 8):

```
Signal:     hold_a
File:       strategies/signals/hold_a.py
Size:       426 bytes, 13 lines
Sha256:     8b0b3234cf07e5cf0807b5c5fd9122479babcce5719ff56fffd630e117e9a6ab
Static:     ok

 1 | """Buy and hold, written as a coded signal."""
 2 | import pandas as pd
 3 | from pydantic import Field
 4 | from backtest_agent.spec.signals import SignalParams, per_symbol_signal, register_signal
 5 |
 6 |
 7 | class Params(SignalParams):
 8 |     scale: float = Field(1.0, ge=0.0, le=1.0)
 9 |
10 |
11 | @register_signal("hold_a", params=Params)
12 | def hold_a(prices, params):
13 |     return per_symbol_signal(prices, lambda close: pd.Series(params.scale, index=close.index))
```

stderr:

```
bt: error: the code is not approved yet; confirm it with --sha 8b0b3234
hint: read the code printed above; if you accept it, run: bt approve spec.yaml --code --sha 8b0b3234
```

**3. The code** (clock 10:31:05):

```powershell
bt approve spec.yaml --code --sha 8b0b3234
```

```
Signal:     hold_a
Code:       approved (sha 8b0b3234)
Approved:   2026-01-15T10:31:05Z
Archive:    approvals/code/8b0b3234cf07e5cf0807b5c5fd9122479babcce5719ff56fffd630e117e9a6ab.py
Record:     approvals/hold_a.json
Pin:        not set (signal.coded.code_sha256: 8b0b3234cf07e5cf0807b5c5fd9122479babcce5719ff56fffd630e117e9a6ab)
```

`bt validate spec.yaml` now has the line `Signal:     coded, idea and code approved (sha 8b0b3234)`; it still shows `n/a` as the warm-up,
because it loads nothing.

**4. The run** (clock 10:32:05). The gate hashes `strategies/signals/hold_a.py`, finds the hash approved, loads the archived
bytes and runs them. The eight characters `HHHHHHHH` are the hash of the inputs, as in "Example: one run":

```powershell
bt run spec.yaml
```

```
Run:        20260115T103205Z-buy-and-hold-a-HHHHHHHH
Strategy:   Buy and hold A (family hold_a)
Trials:     family hold_a: 1 distinct variant in 1 run as of this run. This run is run 1, a new variant (variant 1). Counts cover only runs logged in this journal.
Period:     2024-01-02 to 2024-01-08, 5 bars
Costs:      applied

Metric               Strategy  Benchmark (B)
Total return           17.13%        -21.59%
CAGR              288,635.82%       -100.00%
Sharpe ratio             5.87          -7.50
Maximum drawdown      -12.00%        -21.59%

Excess return (compared window): +38.72%

Risk flags: none
Journal:    runs/20260115T103205Z-buy-and-hold-a-HHHHHHHH/run.json
Report:     reports/20260115T103205Z-buy-and-hold-a-HHHHHHHH/report.md and report.html
```

What the run left behind. `run.json` holds the resolved spec: `signal.coded.code_sha256` is
`8b0b3234cf07e5cf0807b5c5fd9122479babcce5719ff56fffd630e117e9a6ab`, `signal.params` is `{"scale": 1.0}` (the default of the
params model, written out), the family is `hold_a` and the variant hash is
`ec8c4c28e116f8d24d0aed06063dcabb112d891364b7b84719276339176fc9ae`. The same spec with `code_sha256: 8b0b3234...` written in it
is the same variant (run 2 of variant 1). After an edit of `hold_a.py`, `bt run spec.yaml` is exit code 8 with
`code not approved: the file has sha <8 hex>` until the new file is approved with `bt approve`; the new hash is then a new
variant of the same family (variant 2, run 3 of the family). `bt report 20260115T103205Z-buy-and-hold-a-<hash>` loads the
**archived** code of `8b0b3234` and never reads the working file, so it still reproduces the first run after the edit.
