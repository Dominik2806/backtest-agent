# Command line: `bt`

The whole backtester runs from one command, without any agent (F-16). `bt` is a thin layer over code that already exists
and stays unchanged: a standard run is `run_experiment` ([journal.md](journal.md)), reading the journal is its read API,
the numbers are printed by the formatters of the report ([report.md](report.md)). `evaluate()` and `run_backtest()` stay
pure and write nothing. The code is in `src/backtest_agent/cli/`; the decisions are in ADR 0016 (added with the
housekeeping commit of Phase 9). The project is educational and not investment advice.

**Status.** Phase 9 is delivered in two pull requests. Part 1 (this one) has `run`, `validate` (spec only) and
`journal list`, `journal show`, `journal rebuild`. Part 2 adds `data fetch`, `validate --data` and `report` (exit code 7)
and the README quickstart. Everything marked **(part 2)** below does not exist yet.

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

The spec is found by the path you give, so the examples are `strategies/*.yaml` relative to a clone. `bt` also works
from another folder, but then it writes `runs/`, `reports/` and `data/cache/` into **that** folder. **The journal, and so
the trial counter of a strategy family, belongs to one `--runs-dir`**: running the same strategy from two folders gives
two journals with separate counters, and the trial line of a report only counts runs of its own journal. Use the same
folder (or the same `--runs-dir`) for everything you want counted together. `bt run` prints the path of the journal entry
every time. All three folders are git-ignored in this repository.

## Commands

All commands accept `--help`. Every leaf command also accepts `--debug` (print the full traceback of an error on stderr).
`bt --version` prints `bt <version>`.

### `bt run SPEC`

| Option | Default | Meaning |
|---|---|---|
| `--runs-dir DIR` | `runs` | where the run is logged |
| `--reports-dir DIR` | `reports` | where the report is written |
| `--no-report` | off | log the run, write no report |
| `--no-costs` | off | run without the costs of the spec (`apply_costs=False`); the output says so and the run carries the risk flag `costs_not_applied` |
| `--cache-dir DIR` | `data/cache` | the Parquet cache of the prices |

It loads and validates the spec, then calls

```python
run_experiment(
    spec,
    provider,
    runs_dir=...,
    generated_at=clock(),
    reports_dir=None if --no - report else ...,
    apply_costs=not --no - costs,
)
```

so evaluating, logging and reporting happen in the order of [journal.md](journal.md). `generated_at` is read from the
clock here and nowhere else (UTC, timezone-aware, injectable). `allow_short_warmup` and the metric assumptions
(`periods_per_year` 252, risk-free rate 0) keep their defaults. **`allow_short_warmup` is not stored in `run.json` and has
no command line flag**: it is always the default (True), so a short history gives the risk flag `insufficient_warmup` and
a warning, never an error.

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

Metric            Strategy  Benchmark (<symbol>)       (rows: Total return, CAGR, Sharpe ratio, Maximum drawdown)
Excess return (compared window): <signed percent>

Risk flags: none | strategy run: <codes>; benchmark run: <codes>
Journal:    <runs dir>/<run id>/run.json
Report:     <reports dir>/<run id>/report.md and report.html      (not with --no-report)
```

Paths always use `/`. `n/a` stands for a metric that is not defined (for example the Sharpe ratio of one bar). The
labels of the metric rows are the labels of the report.

### `bt validate SPEC`

Checks the spec only: the schema, a registered signal id and valid parameters (every problem is listed with its field
path). It fetches no data, writes nothing and needs no network. Output:

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

`bt validate SPEC --data` **(part 2)** also fetches the data through the cache and shows the validation result (errors,
warnings, infos) without running a backtest.

### `bt journal list`

| Option | Default | Meaning |
|---|---|---|
| `--family F` | all | only runs of this strategy family (the signal id) |
| `--limit N` | all | at most N runs, N of 1 or more |
| `--runs-dir DIR` | `runs` | the journal |

Newest first. Columns: the run id, the family, the run number in its family (`RUN`), the variant number (`VARIANT`), whether
the run introduced its variant (`NEW`), the strategy name (cut after 40 characters). A journal without runs prints
`No runs in <runs dir>.` and exits 0.

### `bt journal show RUN_ID`

Options `--runs-dir DIR` (`runs`) and `--reports-dir DIR` (`reports`; used only to print the report path if that folder
exists). It prints the block of `bt run` down to the risk flags and then when the run was made, the code version, both data
hashes and the paths.
The run id must be a safe folder name (letters, digits, `.`, `_`, `-`); anything else is a usage error.

### `bt journal rebuild`

Option `--runs-dir DIR` (`runs`). Builds the SQLite index again from the run folders (`rebuild_index`). It is the answer to
a stale index (exit code 5, below). It prints the number of runs found and, if the old index can be read, the number of rows
it had. **If the new index has fewer runs than the old one, those runs are forgotten**: their folders were deleted, and
the trial counter no longer counts them. `bt` then prints a warning on stderr that says so (exit code stays 0).

### `bt data fetch SPEC` **(part 2)**

Fetches what the spec needs into the cache: the universe over `fetch_start` to `period.end` and the benchmark over its own
window, and prints rows per symbol, the validation counts and the data hash.

### `bt report RUN_ID` **(part 2)**

Writes the report of a logged run again, without logging anything. `run.json` holds dictionaries, not an `Evaluation`, so
the report cannot be rendered from the journal alone. `bt report` therefore re-evaluates the stored spec on the (cached)
data and refuses if the result differs from the journal:

- It rebuilds the spec from `run.json` and runs `evaluate` with the stored `costs_applied` and the stored metric
  assumptions, then builds the record again and compares it with the stored one.
- **Compared keys:** `spec`, `evaluation` (both data hashes, all metrics, the alignment, the assumptions), `trades`,
  `costs`. **Not compared:** `code_version`, `generated_at`, `run_number`, `trial_number`, `trial_count`.
- The two data hashes must be equal. Floats are equal if `abs(a - b) <= 1e-9 * max(1, |a|, |b|)`; `None` against a number
  is a difference; strings, integers and booleans must be equal. A changed hash is "data changed", any other difference
  is "metrics changed"; both give exit code 7 and name the first differing paths.
- Then it writes the report with the stored run id, `generated_at` and trial, so with unchanged data and spec `report.md`
  is identical to the original byte for byte. Options: `--runs-dir`, `--reports-dir`, `--cache-dir`, `--overwrite` (an
  existing report folder is refused otherwise, exit code 5).

## Exit codes

| Code | Meaning | Caused by |
|---|---|---|
| 0 | success (also `--help`, `--version`, an empty journal) | |
| 1 | unexpected error: a bug, or an operating system error such as a folder that cannot be written | any other exception |
| 2 | usage error: unknown command or option, a missing argument, `--limit 0`, an unsafe run id | argparse |
| 3 | the spec is invalid or its file cannot be read | `SpecError`, `UnknownSignalError` |
| 4 | data problem: the provider failed, no data, validation errors in the data, a cache miss offline | `DataError` and subclasses; any other exception of a provider call |
| 5 | journal problem or an existing output: stale or busy index, unreadable `run.json` or index, run not found, run id exists, report folder exists | `JournalError`, `JournalFormatError`, `FileExistsError` |
| 6 | the run was logged but its report failed; the message names the run id and the hint is `bt report RUN_ID` | `ExperimentReportError` |
| 7 | `bt report` found changed data or changed metrics **(part 2)** | |
| 130 | interrupted with Ctrl-C | `KeyboardInterrupt` |

The checks run in this order, because `JournalFormatError` is a `ValueError` and `ExperimentReportError` a
`RuntimeError`: interrupt, report failed, spec, data, journal, everything else. A run that was interrupted before the
journal committed leaves nothing behind (`record_run` rolls back); one that failed with code 6 stays in the journal and
counts as a trial.

## Errors

stdout carries results only; stderr carries errors and warnings. An error is one block on stderr and no traceback:

```
bt: error: <what went wrong>
hint: <what to do>
```

`--debug` prints the full traceback (with the chained cause) before the block. The hints:

| Situation | Hint |
|---|---|
| stale index | run `bt journal rebuild --runs-dir <dir>`; a run folder that was deleted is forgotten by the rebuild |
| busy index | another process is writing to the journal; try again in a moment |
| run id exists | wait one second and run again (the run id has a resolution of one second); nothing was changed or counted |
| report folder exists, run not logged | remove that folder or choose another `--reports-dir`; nothing was logged |
| run not found | `bt journal list` shows the runs of this journal |
| data problem | check the symbols, the dates and your connection (`--cache-dir`) |
| spec invalid | the fields are described in `docs/strategy-spec.md`; the message already lists every field path |
| report failed after logging | `bt report <run id>` writes it again without logging the run twice |

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
window: for delay 1 it is `2 * 1 + 14 = 16` days before `period.start`. `bt data fetch` and `bt validate --data` **(part 2)**
fetch exactly these two requests, so a later `bt run` is served from the cache. Requests whose end is today or later are
never cached ([data.md](data.md)).

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

Prices (daily bars on 2024-01-02, 03, 04, 05 and 08; the bars before `period.start` are not needed because the warm-up is 0):

| | open | close |
|---|---|---|
| A | 100, 100, 110, 121, 133.1 | 100, 110, 121, 133.1, 146.41 |
| B | 50, 50, 55, 49.5, 54.45 | 50, 55, 49.5, 54.45, 49.005 |

The command, with the clock at 2026-01-15 10:30:05 UTC, in an empty folder:

```powershell
bt run strategy.yaml
```

The arithmetic (the detail is in R3b and H23):

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

Output (the last 8 characters of the run id are a hash of the inputs, written `HHHHHHHH` here; see ADR 0014):

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

Running the same command again one second later (clock 10:30:06) is a repeat of variant 1:

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
Code:       <12 characters of the commit> (clean) | (has uncommitted changes) | (state unknown)
Data:       strategy <64 hex characters>
            benchmark <64 hex characters>
Spec:       runs/<run id>/spec.yaml
Journal:    runs/<run id>/run.json
Report:     reports/<run id>/report.md and report.html
```
