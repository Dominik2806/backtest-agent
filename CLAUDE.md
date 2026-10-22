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

Signal contract (details in `docs/strategy-spec.md`, ADR 0006): a signal `fn(prices, params) -> DataFrame` returns
float64 in [0, 1] without NaN on the input index with one column per symbol, computed per symbol on its own trading
rows, using only data up to the date, without modifying its input. Its params model declares `warmup_rows`, and every
registered signal must pass `tests/signal_contract.py`. Every `strategies/*.yaml` is loaded by a test.

PowerShell 5.1 has no `&&`; chain commands with `;` and check `$LASTEXITCODE` where it matters.

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
- **Never commit** secrets, `.env`, market data, run outputs or reports (`data/`, `runs/`, `reports/`, `*.parquet`).
- Update this file when new commands or conventions are introduced.
