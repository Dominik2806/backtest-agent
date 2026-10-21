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
tests, GitHub Actions for CI (ubuntu-latest and windows-latest). There are no runtime dependencies yet; each phase adds
the libraries it needs (see the tech stack in `docs/ROADMAP.md`). The version lives only in `pyproject.toml`.

## Commands

The maintainer works on Windows with PowerShell. These commands work in PowerShell, other shells and CI.

```powershell
uv sync                       # install dependencies
uv run pytest                 # run tests
uv run ruff check .           # lint
uv run ruff format .          # format (CI runs the check variant: uv run ruff format --check .)
```

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
- **Never commit** secrets, `.env`, market data, run outputs or reports (`data/`, `runs/`, `reports/`, `*.parquet`).
- Update this file when new commands or conventions are introduced.
