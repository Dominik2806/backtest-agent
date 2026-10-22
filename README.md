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
layer, the strategy spec and the pure portfolio simulation of the engine (Phase 4, part 1) exist; the other features described above arrive in the phases named in the
[roadmap](docs/ROADMAP.md).

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

The tests should pass without network access. The `bt` command line arrives in Phase 9; until then there is nothing
to run besides the test suite and the data layer as a Python library, see [docs/data.md](docs/data.md):

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

One live test against yfinance exists and is excluded by default; run it manually with `uv run pytest -m network`.

## What is inside

| Part | What it does | Where |
|---|---|---|
| Data layer | Provider interface, yfinance and fake providers, Parquet cache, data quality validation and data hash. See [docs/data.md](docs/data.md) | [`src/backtest_agent/data/`](src/backtest_agent/data) |
| Strategy spec | Pydantic schema for YAML specs, signal interface and registry, built-in signals; see [docs/strategy-spec.md](docs/strategy-spec.md) | [`src/backtest_agent/spec/`](src/backtest_agent/spec) |
| Example specs | SMA crossover, 12-1 momentum and buy and hold on liquid ETFs | [`strategies/`](strategies) |
| Engine (part 1 of 2) | Portfolio simulation with execution delay, rebalancing and a cost hook, long-only, multi-asset; the runner with data, warm-up and the result object follows. See [docs/engine.md](docs/engine.md) | [`src/backtest_agent/engine/`](src/backtest_agent/engine) |
| Metrics (planned) | Performance and risk metrics, benchmark comparison | [`src/backtest_agent/metrics/`](src/backtest_agent/metrics) |
| Reporting (planned) | Markdown and HTML reports with charts and caveats | [`src/backtest_agent/reporting/`](src/backtest_agent/reporting) |
| Journal (planned) | Run log with trial counter per strategy family | [`src/backtest_agent/journal/`](src/backtest_agent/journal) |
| Robustness (planned) | Out-of-sample, walk-forward, sensitivity, regimes, deflated Sharpe | [`src/backtest_agent/robustness/`](src/backtest_agent/robustness) |
| CLI and agents (planned) | The `bt` command and the Claude Code subagents | see [roadmap](docs/ROADMAP.md) |

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
| 4 | Engine with execution delay, proven by hand-calculated tests | In progress (part 1 of 2 merged) |
| 5 | Commission, spread and slippage models | Planned |
| 6 | Performance metrics and buy-and-hold comparison | Planned |
| 7 | Markdown and HTML report with charts and caveats | Planned |
| 8 | Run log with trial counter | Planned |
| 9 | `bt` command; release `v0.1.0` | Planned |
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
