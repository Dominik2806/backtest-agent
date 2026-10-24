# 0016: Command line

- **Status:** Accepted. Phase 9 is delivered in three parts. Part 1 delivers `run`, `validate` (spec only) and
  `journal list|show|rebuild`; part 2 adds `data fetch` and `validate --data`; part 3 adds `report` and the
  quickstart. The part 3 decisions below (`bt report`, the release order) are decided here and built in part 3.

## Context

The whole backtester has to run from one command without any agent (F-16). Everything it needs exists: `run_experiment`
([ADR 0015](0015-experiment-journal.md)), the journal read API, the report formatters ([ADR 0014](0014-report.md)), the
spec loader and the providers. The command line must add no logic of its own to a result: a number, a trial sentence or a
risk flag looks the same in the terminal, in `bt journal show` and in the report. The commands, options, output formats and
the exit-code table are in [cli.md](../cli.md).

## Decision

- **argparse, not typer.** The standard library is enough for a handful of commands and keeps the dependency list unchanged.
  The ROADMAP tech stack named `typer`; this is a deviation, recorded in the ROADMAP. Alternatives rejected: `typer` or
  `click` (a new dependency for subcommands and help text that argparse already gives), a hand-written parser.
- **A package, `src/backtest_agent/cli/`, not one module.** The roadmap and the architecture said `cli.py`. Parser, error
  mapping, output formats, provider guard and command handlers are different jobs; one file would pass 700 lines.
  `[project.scripts] bt = "backtest_agent.cli:main"` is the same either way, and a `__main__.py` gives
  `python -m backtest_agent`. Adding the entry point changes no dependency and not `uv.lock`.
- **`main` returns the exit code and is fully injectable.** `main(argv=None, *, provider_factory, clock, stdout, stderr)
  -> int` never calls `sys.exit` (argparse's `SystemExit` is caught and turned into its code). The provider factory takes
  the cache folder, the clock is a callable and the streams are file objects (`None` means the process streams, looked up at
  call time). So tests run the whole command line with a literal provider, a fixed clock and string streams, and no test
  reaches the network or the real time. The clock is read in `cli` and nowhere else; `generated_at` of a run comes from it.
  Handlers get everything from a `Context`.
- **`bt run` is `run_experiment`.** It loads the spec and calls `run_experiment(spec, provider, runs_dir=..., generated_at=
  clock(), reports_dir=None if --no-report, apply_costs=not --no-costs)`. `evaluate()` and `run_backtest()` stay pure and
  unchanged, and no CLI path logs without the journal or reports without a trial. `allow_short_warmup` and the metric
  assumptions keep their defaults. A run that succeeds under a strict mode gives the same numbers as under the default; the
  flag only turns an error into the risk flag `insufficient_warmup` plus a warning. So the default never changes a number
  and hides nothing. A strict flag would need a stored field in `run.json` to show which mode a run used; there is no flag
  for now, and the agent phases may add one together with such a field. `--no-costs` is visible in the output and sets the existing risk flag.
- **The provider guard wraps only the calls into the provider.** `GuardedProvider` turns any exception that is not a
  `DataError` into a `DataError` with the original as its cause, so "no network" is a data problem (exit code 4) and not a
  bug. The engine, the journal and the report are never wrapped, and `KeyboardInterrupt` is not an `Exception`, so it
  passes. Alternative rejected: catching every exception around the whole run (it would hide bugs as data problems).
- **Exit codes live in one place.** `cli/errors.py` is the only module that maps an exception to a code, a message and a
  hint: 0 success, 1 unexpected, 2 usage, 3 spec, 4 data, 5 journal or an existing output, 6 the run is logged but its
  report failed (the hint is `bt report RUN_ID`), 7 `bt report` found changed data or metrics, 130 interrupted. The order of
  the checks matters. `JournalFormatError` is both a `JournalError` and a `ValueError`, so it must be tested as a journal
  problem before anything generic (any other `ValueError` is a bug, code 1); `ExperimentReportError` is a `RuntimeError`
  and is tested first. A `sqlite3.Error` (an index file that is not a database) is code 5 with the rebuild hint, ahead of the
  generic branch; a busy index is already a `JournalBusyError`, so it keeps its own message. A `FileExistsError` (run id or
  report folder exists) is code 5 because nothing was changed. Alternative rejected: one code per exception class (too many
  to remember), and a generic "failure" code (a script could not tell a data problem from a bad spec).
- **stdout is results, stderr is everything else.** An error is `bt: error: <message>` and an optional `hint:` line; the
  traceback only with `--debug`, which never changes a code. Every warning raised during a command is printed once as
  `warning: <message>` without paths, so nothing is hidden (and Python's own warning output, which shows the path of the
  source file, never appears). Alternative rejected: logging module configuration (more machinery for one line).
- **No second formatting logic.** All printed output is built in `cli/render.py`. Numbers go through
  `reporting/format.py`, the Trials sentence through `trial_line`, and any text from a spec or the data through
  `reporting.model.text`. `bt run` and `bt journal show` print their common block from the stored record (`RunRecord`) with
  one function, so they cannot disagree.
- **Windows output.** The words of `bt` are ASCII. The two streams are set to `errors="backslashreplace"`: what the console
  can show is shown, anything else prints as `\uXXXX`, and nothing raises `UnicodeEncodeError`. Forcing UTF-8 was rejected
  (mojibake on a cp1252 or cp437 console, and PowerShell 5.1 pipes use the console encoding). Control characters in
  messages become `?`.
- **The journal belongs to one `--runs-dir`.** Every default is relative to the current directory, so the trial counter of
  a family counts the runs of one journal folder, and running the same strategy from two folders gives two counters. This is
  documented where users look, and `bt run` prints the journal path every time. Alternatives rejected: a per-user data
  folder, an environment variable or a config file (hidden state that changes what a "trial" means), looking for the
  repository root (it would make behaviour depend on where the files happen to be).
- **`bt journal rebuild` exists because the stale-index error needs an answer.** It wraps `rebuild_index`, prints the number
  of runs found and, if the old index could be read, the number of rows it had, and warns on stderr when runs were lost. The
  old rows are counted by reading the file directly, because the read API refuses a stale index, which is exactly the case
  in which the old count matters. A deleted run folder is forgotten (documented in the journal); a gap in the run numbers is
  refused.
- **Three parts, and what the data commands decide (part 2).** The phase was planned as two pull requests. With the
  shared window and loader refactor (`warmup_window` and `load_history` in `engine/history.py`, behaviour-only) and the
  `bt report` core it exceeds one reviewable pull request twice over, so it ships in three: part 2 is the engine
  helpers plus `bt data fetch` and `bt validate --data`, part 3 is `bt report` and the quickstart. The CLI never
  computes a window or loads data itself: it calls `load_history` for the spec and for `benchmark_spec(spec)`, so the
  two requests of `bt data fetch` are the two requests of a run by construction (a test pins the literal requests).
  `bt validate --data` exits with code 4 when the fetched data has validation errors, because a run on it would fail,
  and prints every issue on stdout (one short line on stderr, so nothing is printed twice); `bt data fetch` exits 0
  with the same errors and prints a warning on stderr, because the fetch itself worked. Issue lines are built from
  the structured fields only, and the `first` dates are printed only where [data.md](../data.md) defines them.
- **`bt report` re-evaluates and refuses (part 3).** `run.json` holds dictionaries, not an `Evaluation`, so the report
  cannot be rendered from the journal alone. `bt report RUN_ID` rebuilds the spec from `run.json`, evaluates it on the cached
  data with the stored `costs_applied` and metric assumptions, builds the record again and compares `spec`, `evaluation`,
  `trades` and `costs` with the stored ones (not `code_version`, `generated_at`, `run_number`, `trial_number`,
  `trial_count`). Data hashes must be equal; floats are equal if `abs(a - b) <= 1e-9 * max(1, |a|, |b|)`; `None` against a
  number is a difference; strings and integers are exact. A difference is code 7 and names the first paths. Only then
  `write_report` is called with the stored run id, `generated_at` and trial, never `run_experiment`, so nothing is logged and
  an unchanged run gives the original `report.md` byte for byte. Alternatives rejected: rendering from the stored
  dictionaries (a second renderer that could disagree with the report), storing the whole evaluation in `run.json` (the file
  would grow by the equity curves and the journal format would change), and re-running without comparing (a report that
  does not belong to the logged run).
- **The release comes after the last part.** The order is: part 3 merged, then `chore/release-v0.1.0` (version, `uv lock`,
  CHANGELOG cut) merged, then a fresh-clone check (`git clone`, `uv sync`, `uv run bt run strategies/sma_crossover.yaml`),
  and only then the tag and the GitHub release ([RELEASING.md](../RELEASING.md)). The tag points to a commit on `main`.

## Consequences

- A user can run, validate, list and inspect without writing Python, and the output matches the report.
- The CLI has no domain logic, so a change of a number format or a metric label is made once, in the report layer.
- There are two places a new command has to touch: its handler and its row in the exit-code table and `cli.md`. Tests pin
  both the literals of `docs/cli.md` and every exit code with a realistic trigger.
- A guard that treats every provider failure as a data problem can name a bug of a provider as "data problem"; the cause is
  chained and `--debug` shows it.
- The per-folder journal can surprise someone who runs from two directories; the documentation says so and the journal path is
  printed.
- `bt report` can refuse a report that the journal would allow if the cached data is gone and the provider has revised its
  prices; the run itself stays valid in the journal.
