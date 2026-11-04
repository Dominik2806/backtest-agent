# CLAUDE.md

## Project goal

`backtest-agent` is an AI-assisted backtesting tool for trading strategies. Claude subagents turn a plain-language idea
into a validated strategy spec and a small signal function, a deterministic and tested engine runs it on historical
data, and an independent auditor agent checks the result for bias and overfitting. Core principle: **the LLM never
writes the engine.** The project is educational and not investment advice.

**Read `docs/ROADMAP.md` at the start of each phase.** It is the source of truth for scope, architecture,
git workflow and the Definition of Done. Work on one phase at a time.

## Tech stack

Python 3.12 managed with `uv` (src layout, package `backtest_agent`), `ruff` for linting and formatting, `pytest` for
tests, GitHub Actions for CI (ubuntu-latest and windows-latest). Runtime dependencies so far: `pandas`, `numpy`,
`pyarrow` and `yfinance` (Phase 1), `pydantic` v2 and `pyyaml` (Phase 3, YAML only through the safe loader); each phase adds the libraries it needs (see the tech stack in `docs/ROADMAP.md`)
with `uv add`, and `uv.lock` stays committed. The version lives only in `pyproject.toml`.

## Commands

The maintainer works on Windows with PowerShell. These commands work in PowerShell, other shells and CI.

```powershell
uv sync                       # install dependencies (CI runs: uv sync --locked)
uv run pytest                 # run tests (offline; tests marked "network" are excluded)
uv run pytest -m network      # live test against yfinance, run manually, never in CI
uv run ruff check .           # lint
uv run ruff format .          # format (CI runs the check variant: uv run ruff format --check .)
```

Tests never touch the network: use `FakeProvider` or mock `yfinance`. A test that needs the network must carry
`@pytest.mark.network`. Data caches go under `data/cache/` (git-ignored); never commit them. The golden hash in
`tests/test_data_hash.py` is a literal: a change of the hash layout needs a `HASH_VERSION` bump and an ADR first.

Engine: `run_backtest(spec, provider)` in `backtest_agent.engine` is the one entry point that loads data with warm-up,
validates, hashes, runs the signal and returns a `BacktestResult`. It deducts the costs of the spec (`BpsCosts`) and
reports the gross path from a twin run; `apply_costs=False` gives a cost-free run (it keeps the flag `costs_not_applied`),
which the zero-cost regressions (H14, buy and hold equals the asset return) use. A test that expects the short-history
`InsufficientWarmupWarning` must catch it (`pytest.warns`); the test summary shows no warnings.
A test signal is registered per test with `monkeypatch` (see `tests/runner_helpers.py`), never permanently.

Journal and entry point (`docs/journal.md`, ADR 0015): `run_experiment(spec, provider, *, runs_dir, generated_at,
reports_dir=None, ...)` in `backtest_agent.experiment` is how a **standard run** is made. It evaluates (pure), logs the run
with `record_run` and then, if `reports_dir` is given, writes the report with the same run id, `generated_at` and
`trial=record.trial`. Module map: `journal/` (the log, the index and the counters; never imports `reporting`),
`reporting/` (imports only the `TrialInfo` type of the journal), `experiment.py` (the only module that uses both).
`evaluate()` and `run_backtest()` stay pure and write nothing. Standard runs go through `run_experiment`; this is a
convention plus a visible marker, not a guarantee: `write_report` without a trial stays legal and its report says
`Trials: not recorded`. A report that fails after logging raises `ExperimentReportError`; `error.retry()` writes the report
again without logging twice. Tests that log write to `tmp_path` only; the expected values of the trial lines and counters
are the literals of `docs/journal.md` and `docs/report.md`.

Command line (`docs/cli.md`, ADR 0016): `bt` is `backtest_agent.cli:main` (`uv run bt ...`, `python -m backtest_agent`);
`main(argv, *, provider_factory, clock, stdout, stderr) -> int` never calls `sys.exit`. Module map of `src/backtest_agent/cli/`:
`parser.py` and `argtypes.py` (arguments), `commands.py` (handlers; they get everything from the `Context`: provider
factory, clock, streams), `render.py` (every printed line), `errors.py` (every exit code), `provider.py` (the default
`CachedProvider(YFinanceProvider())` and `GuardedProvider`), `data.py` (`bt data fetch` and `bt validate --data`: the two
requests of a run, made only through `engine.load_history`, which uses `engine.warmup_window`, the one place that knows
the data window), `compare.py` and `report.py` (`bt report`: `reproduce` rebuilds the stored spec, reads the stored
`costs_applied` and metric assumptions, runs `evaluate` and compares the fresh record with the stored one; `compare.py` is
pure and tested with literal dictionaries). Rules: CLI code runs a standard run only through `run_experiment`, and
**`bt report` never does**: it logs nothing, never opens the index, and calls `write_report` with the stored run id, time
and trial only when the comparison found no difference (otherwise exit code 7, `RunChangedError`); `generated_at` comes
from the injected clock, read only in `cli`; **all printed output is built in `cli/render.py`** (numbers through
`reporting/format.py`, free text through `reporting.model.text`, no second format); **exit codes are defined only in
`cli/errors.py`** (mind the order of `classify`: `JournalFormatError` is a `ValueError`, `StoredSpecError` comes before
`SpecError` and `RunChangedError` before `DataError`); every new command adds its row to the exit-code table and its
section to `docs/cli.md`. Tests call `main` through `tests/cli_helpers.py::run_cli` with a literal provider and a fixed
clock (a test that gives no provider fails if it reaches the network); the expected lines are the literals of
`docs/cli.md` (the data hashes of its examples were computed with `hashlib` from `docs/data.md`, not with project code),
and every `bt` line of a code block in the README or `docs/` must parse (`tests/test_docs_commands.py`). The `bt` entry
point is checked by `tests/test_cli_entry_point.py`; the live tests are in `tests/test_cli_network.py` (marked
`network`).

Signal contract (details in `docs/strategy-spec.md`, ADR 0006): a signal `fn(prices, params) -> DataFrame` returns
float64 in [0, 1] without NaN on the input index with one column per symbol, computed per symbol on its own trading
rows, using only data up to the date, without modifying its input. Its params model declares `warmup_rows`, and every
registered signal must pass `tests/signal_contract.py` (a re-export of `backtest_agent.coded.contract`). `warmup_rows()` must
return a Python `int` of at least 0 (a NumPy integer is refused). `Signal.generate` also checks, on every call, that a symbol's
exposure is 0.0 before its (W+1)-th trading row (ADR 0017). Every `strategies/*.yaml` is loaded by a test.

Coded signals (`docs/coded-signals.md`, ADR 0018): a signal that an agent writes is named by `signal.coded` (`brief`,
`code_sha256`) in the spec and approved in two steps by a person, the idea `{signal_id, brief}` and then the sha256 of the
code (CRLF turned into LF). The approvals are an append-only history in `approvals/<id>.json`; the approved bytes are archived
as `approvals/code/<sha256>.py`, and the archive is what runs, never the editable `strategies/signals/<id>.py`.
**Nothing imports or executes a coded signal before both approvals**; `coded/loader.py` is the **only module in `src/`**
that may compile or execute strategy code, and `tests/test_coded_source_tree.py` reads the syntax trees to check that (no
other `exec`, builtin `compile`, `eval`, `__import__`, `importlib` beyond `importlib.metadata` in the package `__init__`,
`runpy`, `pkgutil`, `codeop`, `import_module` or `types.ModuleType`; the registry methods `set_sha256`, `unregister`,
`restore`, `snapshot` and the `sha256` marker of a `Signal` only in the loader and `spec/signals.py`). Module map:
`spec/coded_spec.py` (the block, the id and brief rules, `check_brief`), `coded/static.py` (the AST tripwire, whole tree,
not a sandbox), `coded/approvals.py` (hashes, records, archive, the lock `approvals/.lock`), `coded/loader.py`
(`resolve_coded(spec, approvals_dir=, strategies_dir=)`: the gate; `strategies_dir=None` is the stored mode of `bt report`,
a folder the run mode of `bt run`), `coded/contract.py` (the contract check on synthetic frames, `check_before_run` with 120
rows), `coded/cases.py` (`cases.yaml`, the examples of a coded signal as data), `coded/errors.py`. `SignalSpec.resolve_signal()`
is the one place where a spec finds its signal (the pin check); `Signal.sha256` is the hash of the code a registered signal
was loaded from. Rules: `resolve_coded` raises only `NotApprovedError` (exit 8), `RecordError` (5),
`StaticCheckError`/`SignalContractError` (9), `SpecError` (3) and `GateError` (9; the gate never runs
`cases.yaml`: `CasesError`, exit 9, is raised only by `bt signal check`), and the registry is exactly what it was whenever it raises; what a coded signal raises (`SystemExit` included, not `KeyboardInterrupt`/`GeneratorExit`) while it is
loaded, checked or called through `Signal.generate` is a contract error (code reached anywhere else, such as
`params.warmup_rows()` in `warmup_window`, is not covered: known gap 5 of the ADR); the params model of a coded signal has defaults that are numbers, text,
true or false, or lists of those (no `None`, tuple or dict) and accepts them. `cli/errors.py` maps all of them: 8 for refusals
(`NotApprovedError`, `ApprovalError`, `ConfirmationError`), 9 for rejected code (`SignalContractError` for **every** signal), 5 for
`RecordError` and `ApprovalFormatError`; `classify` checks the subclasses of `GateError` and `ApprovalError` first. Commands:
`cli/coded.py` (`cmd_approve`, and `resolve_for_run`, the one place where a command passes a coded spec through the gate in run
mode: `bt run`, `bt validate --data`, `bt data fetch`), `cli/report.py` (`stored_coded_spec`: the stored mode of `bt report`),
`coded/working.py` (`read_working_file`: bytes only, shared by the gate, `bt approve` and `bt signal check`), `cli/signal_check.py`
(`cmd_signal_check`), `coded/status.py` (`approval_state`: the
`Signal:` line of `bt validate`, from the record alone: no file, no archive, nothing loaded), `cli/context.py` (`Context`).
`bt approve` reads the file once and shows, hashes and archives those bytes; it imports and executes nothing; a person has to read
the printed code; the agents are fenced from it by the rules of `.claude/settings.json` and the hook (below, `docs/agents.md`). `bt signal check` (`cli/signal_check.py`, ADR 0018 addendum, `docs/cli.md`)
**executes a candidate that nobody approved**, in the process of the command, with the permissions of whoever runs it and no time
or memory limit (known gap 6): it reads the file as bytes, runs the static check and reads `cases.yaml` as data, writes ONE consent
line to stderr, and only then calls `load_candidate`, checks the contract on frames of 300 rows and runs the examples; it reads no
approvals, writes nothing and caches nothing. **Only `cli/signal_check.py` may use `load_candidate` or import `coded/cases.py`**
(`tests/test_coded_source_tree.py` and `tests/test_cli_docs_coded.py` read the syntax trees); `load_candidate` restores the registry
however its block ends. Exit codes of the command: 3 (no coded block, params that do not fit), 9 (everything rejected, a file that
cannot be read too), never 8. Not built: running a candidate in a subprocess with a
time and memory limit. Tests that register or load a signal use the fixtures of `tests/coded_helpers.py`
(the registry is restored, no module of a coded signal may appear in `sys.modules`, canary marker files are written under
`tmp_path` only). `approvals/` and `strategies/signals/` are tracked, so public; they are LF
(`.gitattributes`) and excluded from ruff (`extend-exclude`), because the bytes are hashed. A stale `approvals/.lock` is
deleted by hand. Expected hashes in tests are literals computed with `hashlib` outside project code; the examples in
`docs/coded-signals.md` are checked by `tests/test_coded_docs.py`; the worked example of `bt approve` in `docs/cli.md`, its
exit-code table, hints and option names by `tests/test_cli_docs_coded.py`.

PowerShell 5.1 has no `&&`; chain commands with `;` and check `$LASTEXITCODE` where it matters.

Agent guardrails (`docs/agents.md`, ADR 0019): `.claude/settings.json` denies `bt approve` in many spellings (Bash and PowerShell;
the explicit `uv run`, `python -m`, `py -m` and `python3 -m` rules are redundant on purpose), asks before every `bt signal check`
and registers the PreToolUse hook `.claude/hooks/restrict_writes.py` with `"onFailure": "block"` (Claude Code 2.1.295 or later; the
SchemaStore schema does not know the key). The hook is standard library only, decides by the `agent_type` of the call (none, or
another agent: silent exit 0, so the main session never starts `uv`), allows the `strategy-architect` only
`strategies/drafts/<name>.yaml` and `bt validate` of a draft, and the `signal-coder` only `strategies/signals/<id>.py`,
`<id>.cases.yaml`, `bt validate` and `bt signal check`, the last **only when `permission_mode` of the call is `default`** (any other
value, a missing field or a non-string is refused; the ask rule is a second layer). Read, Glob and Grep get no objection; any other
tool is refused. **It never prints a `permissionDecision`**: it exits 0 without output or exits 2 with the reason on stderr (any
other exit code lets a call through unless the entry has `onFailure` `block`), and any error of the script is exit 2. A Bash
command passes only if every character is in `[A-Za-z0-9_./ -]` and the words are one of the allowed forms; a backslash is refused.
The `~digit` guard of 8.3 names looks below the project directory only. These are fences, not boundaries, and nothing says they hold
under `bypassPermissions` (not tested). A change of a rule or of the hook needs a row in its table test
(`tests/test_agent_deny_rules.py`, `tests/test_restrict_writes*.py`) and a mutation table at the stop; the reference matcher of the
deny test is our reading of the documented semantics, not Claude Code's. `strategies/drafts/` is git-ignored (`.gitkeep` only);
`strategies/signals/` and `approvals/` are tracked, so `git add` them only after reading the code. The agent files `.claude/agents/strategy-architect.md` and
`signal-coder.md` list exactly `Read, Glob, Grep, Write, Edit, Bash` and carry a matcherless copy of the hook entry with the agent name
as argument (`tests/test_agent_files.py`); their prompts name only commands that the hook allows that agent, say that they are
instructions and not enforcement, and give the person the `bt approve` steps. Documents tie each claim to a
test or say `(not tested)` (`tests/test_agents_docs.py`).

## Workflow

- Start each phase in Plan Mode: write the plan, list every file you will create or change, name the decisions that
  need confirmation, and wait for approval before changing anything.
- Work on one phase and one branch at a time, created from `main`. Make small commits, one per task group.
- Before a commit or pull request run `uv run pytest`, `uv run ruff check .` and `uv run ruff format --check .`, and
  fix what they report. Do not hide failures: report them.
- Never push, open or merge pull requests, or change GitHub settings (branch protection, secrets, releases)
  unless the maintainer asks for it explicitly in that message.
- Never start the next phase before the current one is merged.
- If a hook, permission or guardrail blocks an action, do not work around it: stop, say what was blocked and ask.
- Record every deviation from the plan under "Deviations from the plan" in `docs/ROADMAP.md`.

## Conventions

- **Language:** English for code, commits, docs and README.
- **Layout:** source in `src/backtest_agent/`, tests in `tests/`, docs in `docs/`, decisions in `docs/adr/`. Generated
  and local-only paths are git-ignored: `data/`, `runs/`, `reports/`, `*.parquet`, `.venv/`, `.env`.
- **Docs:** every relative markdown link in `README.md` and `docs/**/*.md` must resolve. Decisions go into
  `docs/adr/` (one short ADR per decision, listed in its `README.md`).
- **Branches:** one per phase or change, created from `main`, named `feature/`, `fix/`, `docs/` or `chore/` plus a
  short kebab-case description. Never push directly to `main`.
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/) with types `feat`, `fix`, `docs`,
  `test`, `chore` (e.g. `feat(engine): add vectorized portfolio engine (F-09)`). Use the stable feature IDs
  (`F-01` to `F-27`) from the roadmap.
- **Commit and PR text:** commit messages and pull request descriptions contain only the Conventional Commit message
  or the plain description. Never add `Co-Authored-By`, `Claude-Session` or "Generated with Claude Code" lines, links
  to Claude sessions, or any other attribution trailer.
- **PRs:** squash-merged; add a CHANGELOG entry under "Unreleased".
- **Releases:** follow `docs/RELEASING.md`.
- **Engine tests:** the expected values of engine tests are hand-calculated literals written out step by step in
  `docs/engine.md` (`tests/test_engine_hand_calculated.py`, `tests/test_engine_costs_hand_calculated.py`,
  `tests/test_engine_runner_costs.py`); never compute an expected value with engine code or a helper that mirrors it.
  Random-world tests use fixed seeds. Zero-cost behaviour is compared exactly, the cost fixtures with a tolerance of
  1e-9 (the funding search leaves a float residual). `tests/cost_reference.py` is the engine-free reference for costs; no
  test asserts a sign of `cost_drag` or a bound of `cost_share` in general.
- **Metrics tests:** the expected values of `tests/test_metrics_hand_calculated.py` (M1 to M14) are literals written out in
  `docs/metrics.md`, compared with 1e-9 (relative and absolute); never compute one with project code. A metric that is
  not defined is `None`, never NaN or inf; a per-bar deviation below 1e-12 counts as zero (`docs/metrics.md`). Turnover
  is reported two-sided (the engine's) and one-sided (half). `BacktestResult.returns` is 0.0 after a ruin.
- **Benchmark tests:** `evaluate(spec, provider)` in `backtest_agent.metrics` runs the strategy and its buy-and-hold benchmark
  (`benchmark_spec`) through `run_backtest` with the same provider, costs and execution; `run_backtest` loads no benchmark.
  The expected values of R1 to R3 (`tests/test_metrics_relative_hand_calculated.py`, `tests/test_metrics_evaluation.py`)
  are literals written out in `docs/metrics.md`; never compute one with project code. The alignment is on equity levels
  of the common dates (rule in `docs/metrics.md`), never silent; relative metrics with fewer than 2 observations are `None`.
- **Report tests:** `write_report(evaluation, reports_dir, generated_at=...)` in `backtest_agent.reporting` writes
  `reports/<run-id>/report.md`, `equity.svg`, `drawdown.svg` and `report.html` (in this write order, so a failure on any
  write removes the folder the call created; `overwrite=True` is not atomic); `docs/report.md` and ADR 0014 are the
  reference. The model (`reporting/model.py`) is a pure function of an `Evaluation`, a run id and an explicit timezone-aware
  `generated_at`: no clock, locale or file access in the model or the renderers, and the report recomputes no metric (a
  new number goes into `backtest_agent.metrics` first, with hand-calculated fixtures such as T1 to T6 in
  `docs/metrics.md`). The "Assumptions and caveats" section is `fixed_caveats()`, a function without parameters, and
  `ReportModel` raises if it differs in any way; a new `RiskFlag` code needs an explanation in `reporting/caveats.py`.
  `None` prints as `n/a`, NaN and infinity raise a `ValueError` that names the field; text from the spec or the data is
  escaped by the renderer. `write_report` renders in memory first and never overwrites a folder silently. The snapshot
  `tests/snapshots/report.md` is reviewed by hand (regenerate with `uv run python tests/test_report_markdown_snapshot.py`);
  chart and heatmap tests use hand-calculated literals; the report adds no dependency.
- **HTML report tests:** `render_html(model)` in `backtest_agent.reporting.html_renderer` is a pure function of the
  `ReportModel` and adds no content and no number format. The markup is built only with `tag` and `block` (a plain `str`
  child or attribute value is always escaped, only `Markup` passes through; no f-string with a data value), the CSS is one
  constant string, and there is no script, external font, stylesheet, image or link (no `http` text at all, no `src`, only
  `#fragment` hrefs, no `url(` or `@import`); the inline SVG has no namespace. The HTML must parse with `xml.etree` (the
  doctype is accepted as it is). The monthly returns are shaded by CSS class from the unrounded return, and every text and
  background colour pair of the CSS must have a WCAG contrast of at least 4.5 in both themes (formula in the test, no
  library). Characters that XML forbids are replaced once, in `text()` of the model. Offline tests that write reports
  install a `monkeypatch` guard on `socket.socket.connect`; live tests are in `tests/test_report_network.py` (marked
  `network`). The structural snapshot `tests/snapshots/report_html_outline.txt` is reviewed by hand (regenerate with
  `uv run python tests/test_report_html_outline.py`).
- **No double brace:** no source file, tests included, contains the two-character sequence of two opening braces outside
  `.github/` (a template-placeholder check greps for it); build such strings from constants, for example
  `OPEN * 2` with `OPEN = chr(123)`.
- **No invisible characters:** no file that git tracks (`.py .md .yaml .yml .toml .json .txt .cfg`) contains a character of the
  Unicode categories Cc, Cf, Zl or Zp except a line break, a tab and the CR of a CRLF (`tests/test_no_invisible_characters.py`).
  A test that needs one writes it as an escape (backslash, `u` and four hex digits) or with `chr()`.
- **Never commit** secrets, `.env`, market data, run outputs or reports (`data/`, `runs/`, `reports/`, `*.parquet`).
- Update this file when new commands or conventions are introduced.
