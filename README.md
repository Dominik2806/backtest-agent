# backtest-agent

[![CI](https://github.com/Dominik2806/backtest-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Dominik2806/backtest-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](pyproject.toml)

An AI-assisted backtesting tool for trading strategies. You describe a strategy in plain language, Claude subagents
turn it into a validated strategy spec and a small signal function, and a deterministic, tested engine runs it on
historical data. An independent auditor agent then checks the result for look-ahead bias, survivorship bias, missing
costs and overfitting before an honest verdict is written. The core principle: the LLM never writes the engine.

> **Disclaimer:** this project is educational and not investment advice. Backtest results are not a prediction of
> future performance.

## What it does

You write an idea such as "buy the three assets with the strongest 12-month momentum and rebalance monthly". The
strategy architect turns it into a YAML spec and lists its assumptions. After you approve the spec, the engine runs it
on daily data with execution delay, costs and slippage, and compares it with a buy-and-hold benchmark.

You get a report with metrics, charts and a fixed section of caveats, a log of every run with a trial counter per
strategy family, and the auditor's findings. The trial counter makes overfitting visible: ten tried variants are not
the same as one.

The project is built in phases, see the [roadmap status](#roadmap-status). Today the project skeleton, the data
layer, the strategy spec, the engine with `run_backtest` (Phases 4 and 5, with commission, spread and slippage), the
performance metrics of a run next to its buy-and-hold benchmark (Phase 6), and the Markdown and HTML reports with charts
and caveats (Phase 7), and the run journal with its trial counter (Phase 8) exist; the other features described above
arrive in the phases named in the [roadmap](docs/ROADMAP.md).

## Requirements

- [uv](https://docs.astral.sh/uv/) (manages Python 3.12 and the virtual environment)
- Git
- [Claude Code](https://claude.com/claude-code) for the agent workflow (from Phase 10 on)

## Quickstart

```powershell
git clone https://github.com/Dominik2806/backtest-agent.git; cd backtest-agent
uv sync
uv run pytest
```

The tests should pass without network access. The `bt` command line is arriving in Phase 9 (see [Command line](#command-line); its quickstart for a fresh clone
follows with the second part). Besides it there is the test suite and the Python library: the data layer ([docs/data.md](docs/data.md)) and the engine
(`run_backtest`, see below):

```python
from datetime import date
from backtest_agent.data import hash_frame, validate_prices
from backtest_agent.data.cache import CachedProvider
from backtest_agent.data.yfinance_provider import YFinanceProvider

start, end = date(2023, 1, 2), date(2023, 3, 31)
prices = CachedProvider(YFinanceProvider()).get_prices(["AAPL", "SAP.DE"], start, end)
result = validate_prices(prices, start=start, end=end)  # reports errors, warnings and infos
result.raise_for_errors()  # raises DataValidationError if there is an error
print(hash_frame(prices))  # SHA-256 of the exact data
```

A strategy is a YAML spec (see [`strategies/`](strategies) and [docs/strategy-spec.md](docs/strategy-spec.md)) that
loads into a validated object with every problem listed at once:

```python
from backtest_agent.spec import load_spec

spec = load_spec("strategies/sma_crossover.yaml")
print(spec.signal.id, spec.warmup_rows, spec.risk_flags())
```

A run loads history with a warm-up for the signal, validates and hashes it, and returns a result (equity, cash,
positions, trades, turnover, risk flags). The costs of the spec are deducted and the result also reports the gross
path and what the costs ate (`result.total_costs`, `result.cost_share`; [docs/engine.md](docs/engine.md)):

```python
from datetime import date
from backtest_agent.data import FakeProvider  # offline; use CachedProvider(YFinanceProvider()) for real prices
from backtest_agent.engine import run_backtest
from backtest_agent.spec import load_spec

spec = load_spec("strategies/buy_and_hold.yaml")
spec = spec.model_copy(update={"period": spec.period.model_copy(update={"start": date(2020, 1, 1)})})
result = run_backtest(spec, FakeProvider(symbols=spec.universe))
print(result.equity.iloc[-1], result.total_costs, [flag.code for flag in result.risk_flags], result.warmup.sufficient)
```

A standard run goes through `run_experiment`: it evaluates the spec next to its benchmark, logs the run under
`runs/<run-id>/` (counted per strategy family) and writes the report with the trial line, how many distinct variants in
how many runs the family has had, into `reports/<run-id>/`
([docs/journal.md](docs/journal.md), [docs/report.md](docs/report.md)):

```python
from datetime import UTC, datetime
from backtest_agent.experiment import run_experiment

experiment = run_experiment(
    spec, FakeProvider(symbols=spec.universe), runs_dir="runs", reports_dir="reports", generated_at=datetime.now(UTC)
)
print(experiment.record.trial, experiment.report.markdown)
```

A report written with `write_report` alone says `Trials: not recorded`; the journal cannot force a run to be logged, so
this is a convention plus a visible marker.

One live test against yfinance exists and is excluded by default; run it manually with `uv run pytest -m network`.

## Command line

`uv sync` installs the `bt` script (`python -m backtest_agent` is the same command). What exists today, relative to the
current directory (details, options, output and exit codes: [docs/cli.md](docs/cli.md)):

```powershell
uv run bt validate strategies/sma_crossover.yaml   # check a spec; no data is fetched
uv run bt run strategies/sma_crossover.yaml        # evaluate, log the run in runs/, write reports/<run id>/
uv run bt journal list                             # the logged runs, newest first
uv run bt journal show RUN_ID                      # one run: summary, code version, data hashes, paths
uv run bt journal rebuild                          # build the journal index again from the run folders
```

`bt run` fetches prices from yfinance (cached under `data/cache/`), so it needs a network connection the first time. The
journal and the trial counter belong to one `--runs-dir`: run from the same folder to count your runs together. The commands
`bt data fetch` and `bt report` and the full quickstart arrive with the second part of Phase 9.

## What is inside

| Part | What it does | Where |
|---|---|---|
| Data layer | Provider interface, yfinance and fake providers, Parquet cache, data quality validation and data hash. See [docs/data.md](docs/data.md) | [`src/backtest_agent/data/`](src/backtest_agent/data) |
| Strategy spec | Pydantic schema for YAML specs, signal interface and registry, built-in signals; see [docs/strategy-spec.md](docs/strategy-spec.md) | [`src/backtest_agent/spec/`](src/backtest_agent/spec) |
| Example specs | SMA crossover, 12-1 momentum and buy and hold on liquid ETFs | [`strategies/`](strategies) |
| Engine | Portfolio simulation with execution delay, rebalancing and costs (commission, half-spread, slippage), long-only, multi-asset, and `run_backtest` (data with warm-up, validation, hash, net and gross result). See [docs/engine.md](docs/engine.md) | [`src/backtest_agent/engine/`](src/backtest_agent/engine) |
| Metrics | CAGR, volatility, Sharpe, Sortino, drawdown, Calmar, hit rate, turnover, exposure and monthly returns of a run, and `evaluate`, which runs the buy-and-hold benchmark through the same engine and reports excess return, tracking error and information ratio. See [docs/metrics.md](docs/metrics.md) | [`src/backtest_agent/metrics/`](src/backtest_agent/metrics) |
| Reporting | `write_report(evaluation, reports_dir, generated_at=...)` writes `reports/<run-id>/report.md`, a self-contained `report.html` and the equity and drawdown charts as SVG files: spec, data hashes and validation, risk flags with explanations, metrics next to the benchmark, costs, monthly returns, trade statistics and a fixed section of caveats. See [docs/report.md](docs/report.md) | [`src/backtest_agent/reporting/`](src/backtest_agent/reporting) |
| Journal | `run_experiment(spec, provider, runs_dir=..., generated_at=...)` evaluates, logs the run under `runs/<run-id>/` (`run.json`, SQLite index) and, with `reports_dir`, writes the report with its trial line; trial counter per strategy family (runs and distinct variants). See [docs/journal.md](docs/journal.md) | [`src/backtest_agent/journal/`](src/backtest_agent/journal), [`experiment.py`](src/backtest_agent/experiment.py) |
| Robustness (planned) | Out-of-sample, walk-forward, sensitivity, regimes, deflated Sharpe | [`src/backtest_agent/robustness/`](src/backtest_agent/robustness) |
| CLI | The `bt` command: `run`, `validate`, `journal list`, `show`, `rebuild` (Phase 9, part 1). See [docs/cli.md](docs/cli.md) | [`src/backtest_agent/cli/`](src/backtest_agent/cli) |
| Agents (planned) | The Claude Code subagents and the `/backtest` command | see [roadmap](docs/ROADMAP.md) |

How the parts fit together: [docs/architecture.md](docs/architecture.md). Why they are built this way:
[docs/adr/](docs/adr/README.md).

## Safety

- The engine shifts signals by at least one bar before executing them, so look-ahead is impossible by default.
- Nothing runs until the maintainer approves the strategy spec.
- Agents never write or change the engine.
- Market data, run outputs, keys and `.env` files are never committed.
- Prices come from yfinance, an unofficial source for personal use. Treat results as an experiment, not as a basis
  for financial decisions.

These are the design goals; they are enforced by the phases listed in the roadmap and not all of them exist yet.

## Development

```powershell
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pytest -m network   # optional live test, uses the network
```

`main` is protected: one branch per change (`feature/`, `fix/`, `docs/`, `chore/`), Conventional Commits, squash-merged
pull requests with a CHANGELOG entry. See [CONTRIBUTING.md](CONTRIBUTING.md). Further reading:
[roadmap](docs/ROADMAP.md), [changelog](CHANGELOG.md), [releasing](docs/RELEASING.md).

## Roadmap status

| Phase | Result | Status |
|---|---|---|
| 0 | Project skeleton, CI, templates | Done |
| 1 | Provider interface, yfinance provider, Parquet cache | Done |
| 2 | Data checks and a reproducibility hash | Done |
| 3 | YAML strategy spec, signal interface, example strategies | Done |
| 4 | Engine with execution delay, proven by hand-calculated tests | Done |
| 5 | Commission, spread and slippage models | Done |
| 6 | Performance metrics and buy-and-hold comparison | Done |
| 7 | Markdown and HTML report with charts and caveats | Done |
| 8 | Run log with trial counter | Done |
| 9 | `bt` command; release `v0.1.0` | In progress (part 1 of 2) |
| 10 | Strategy architect and signal coder subagents | Planned |
| 11 | Bias auditor and report interpreter subagents | Planned |
| 12 | `/backtest` command with approval gate; release `v0.2.0` | Planned |
| 13 | Out-of-sample split and walk-forward analysis | Planned |
| 14 | Parameter sensitivity and market regime analysis | Planned |
| 15 | Automated look-ahead test and deflated Sharpe ratio; release `v1.0.0` | Planned |

Outlook (not started): further data providers and historical index constituents, short selling, leverage and intraday
bars, portfolio optimization, a standalone Claude Agent SDK version of the workflow.

## License

[MIT](LICENSE)
