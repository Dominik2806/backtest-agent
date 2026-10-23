# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Report, part 2 of 2 (F-14, Phase 7): `render_html(model)` renders the report as one self-contained HTML file (inline CSS and
  inline SVG, no script, font, stylesheet, image or link; light and dark theme; every table scrolls inside its own container
  at phone width; monthly returns shaded by class from the unrounded return, with a contrast of at least 4.5 checked in the
  tests). The markup is built with escaping helpers, so a hostile strategy name or validation message stays text.
  `write_report` now writes `report.md`, `equity.svg`, `drawdown.svg` and `report.html` (last); `ReportPaths.html`. A report
  is written for each of the three example strategies in the tests, offline on `FakeProvider` and, marked `network`, with
  real data. A structural snapshot protects the HTML outline. With `overwrite=True` a failed write can leave a mix of new
  and old files (documented).
- Report, part 1 of 2 (F-14, Phase 7): `write_report(evaluation, reports_dir, generated_at=...)` writes
  `reports/<run-id>/report.md` and the equity and drawdown charts as SVG files (the self-contained HTML version follows in
  part 2). The report shows the spec, the data hash and validation findings of the strategy and the benchmark run, the
  warm-up, the risk flags with a plain-language explanation each, the metrics next to the benchmark and the relative
  metrics with the assumptions, the benchmark alignment (with a caption under the equity chart that says when the curves
  are not comparable), costs gross versus net, a monthly returns table, trade statistics, and a fixed section "Assumptions
  and caveats" that cannot be switched off. It is built by a pure model (`build_report_model`) from an `Evaluation`, a run id
  and an explicit `generated_at`, rendered by `render_markdown` and the hand-written SVG charts (no new dependency), and
  written in memory first, so a failure leaves nothing on disk. Run ids are `<UTC timestamp>-<slug>-<8 hex>`
  (`backtest_agent.run_id`). Trade statistics (`trade_statistics`: fills, buys and sells per symbol, average cost per
  trade) joined the metrics layer with hand-calculated fixtures T1 to T6. `docs/report.md`, ADR 0014, a snapshot test for
  the Markdown structure.
- Benchmark comparison (F-13, Phase 6 part 2): `evaluate(spec, provider)` runs the strategy and its buy-and-hold benchmark
  (`benchmark_spec`: the benchmark symbol, `buy_and_hold`, `equal_weight`, same period, capital, execution and costs) through
  the same `run_backtest` and provider, and returns an `Evaluation` with both results, both `PerformanceMetrics`, and the
  relative metrics (excess return, tracking error, information ratio). The two runs are aligned on the equity levels of their
  common dates; dropped dates are counted and flagged and nothing raises for different calendars. `evaluate_result` rejects
  a benchmark result of another spec or another `costs_applied`. `Evaluation.to_dict()` is JSON serializable. Hand-calculated
  fixtures R1 to R3 in `docs/metrics.md`, with tests and property tests, ADR 0013. `run_backtest` is unchanged.
- Performance metrics (F-12, Phase 6 part 1): `compute_metrics(result, MetricAssumptions(periods_per_year, risk_free_rate))`
  returns `PerformanceMetrics` (total return from `net_return`, CAGR, annualized volatility, Sharpe, Sortino, maximum and
  current drawdown, longest drawdown in bars and days, Calmar, hit rate, two-sided and one-sided annualized turnover,
  exposure, best and worst month) and the pure functions behind it. Undefined values are `None`, never NaN or inf; a
  per-bar deviation below 1e-12 counts as zero. `docs/metrics.md` has every formula and assumption and the
  hand-calculated fixtures M1 to M14, with tests and property tests, ADR 0012. The benchmark comparison follows in part 2.
- Costs and slippage (F-10): `BpsCosts` applies commission, half-spread and slippage in basis points of the traded
  value, with the optional `costs.min_commission` (per trade, commission only, default 0) in the spec. Costs are cash
  fees on the bar of the fill: the `trades` table has a `cost` column and the portfolio has costs per bar and
  `total_costs`. Sells are filled first and net of their fees (a sale's fee is capped at its proceeds), buys must also
  cover their fees and are scaled down by one factor otherwise; the part of a buy that only fees kept from being bought
  is dropped, so a full rebalance does not inflate the deferred and unfilled counters. With zero costs the behaviour is
  identical to before. Fees can drive a portfolio to zero: its weights and turnover are then 0 instead of NaN.
  Hand-calculated fixtures H16 to H22 and H19c, a bit-exact zero-cost equivalence test, property tests, ADR 0010.
- `run_backtest` deducts the costs of the spec (`costs_applied` True) and reports gross versus net (F-10): the result
  has `costs` per bar, `gross_equity` (a twin run without costs on the same data, signals and orders, only run when the
  spec has costs) and the properties `total_costs`, `gross_final_equity`, `net_return`, `gross_return`, `cost_drag` and
  `cost_share` (none if the gross return is not positive; neither a sign of the drag nor a bound of the share is
  guaranteed). `run_backtest(..., apply_costs=False)` runs without costs and keeps the flag `costs_not_applied` when the
  spec has costs. `CostsSpec.is_zero`. Hand-calculated fixtures H23, H23b and H23c, an independent cost calculation
  (`tests/cost_reference.py`) for the live network test, checked offline too, ADR 0011.
- Project roadmap with 16 phases in `docs/ROADMAP.md`
- Project skeleton (F-01): `pyproject.toml` for Python 3.12 and `uv`, src layout with the package `backtest_agent`,
  a smoke test, `ruff` and `pytest` configuration
- CI on `ubuntu-latest` and `windows-latest` running `uv sync`, `ruff check`, `ruff format --check` and `pytest` (F-02)
- Architecture decision records 0001 (own engine) and 0002 (deterministic core)
- `docs/architecture.md`, README with disclaimer and roadmap status, branch protection section in `CONTRIBUTING.md`
- `.gitignore` entries for `data/`, `runs/`, `reports/`, `*.parquet`, `.venv/` and `.env`
- Data provider interface with the standard price frame (`date` index, `(symbol, field)` columns, adjusted OHLCV) and
  a deterministic `FakeProvider` for tests and examples (F-04)
- yfinance provider with auto-adjusted prices and timezone normalization, and `CachedProvider`, a Parquet cache under
  `data/cache/` with offline and refresh modes that never caches requests ending today or later (F-05)
- `docs/data.md` (format, adjustment rules, cache behaviour, data source caveats) and ADR 0003
- pytest marker `network` for the live yfinance test, excluded by default (`uv run pytest -m network`)
- Runtime dependencies `pandas`, `numpy`, `pyarrow` and `yfinance`
- Data quality validation (F-06): `validate_prices` reports issues with severity, stable code, symbol, field, count and
  first dates instead of raising (duplicate or unsorted dates, NaN, non-positive prices, OHLC inconsistencies,
  calendar gaps, extreme moves, stale prices, split artifacts, volume and range infos), with a frozen
  `ValidationConfig`, JSON-serializable `ValidationResult` and `raise_for_errors()` raising `DataValidationError`
- `hash_frame`, a canonical SHA-256 hash of a standard frame that is stable across platforms and library versions
- ADR 0004 (validation reports, calendar heuristic) and ADR 0005 (canonical data hash); validation and hash sections in
  `docs/data.md`
- Strategy spec (F-07): strict Pydantic v2 schema for YAML specs (`StrategySpec`), `load_spec` and `parse_spec` with
  safe YAML loading, rejection of duplicate keys and unknown fields, one `SpecError` listing every problem with its
  field path, same-bar execution rules, a required costs block and `StrategySpec.risk_flags()` for the report
- Signal interface (F-08): signal functions `fn(prices, params)` with a params model, a registry (`register_signal`,
  `get_signal`, `list_signals`), a contract check of every signal output (`validate_signal_output`) and
  `warmup_rows`, the history a signal needs, exposed as `StrategySpec.warmup_rows`
- Built-in signals `sma_crossover`, `momentum_12_1` and `buy_and_hold`, and example specs of the same names in
  `strategies/`, loaded by a test so every future example is checked by CI
- `docs/strategy-spec.md`, ADR 0006 (signal contract) and ADR 0007 (strict, explicit spec)
- Runtime dependencies `pydantic` and `pyyaml`
- Engine, part 1 of Phase 4 (F-09, F-11): the pure portfolio simulation in `backtest_agent.engine` (`target_weights`,
  `decision_bars`, `execution_orders`, `simulate`, `simulate_signals`, a `CostModel` hook with `NoCosts`). Signals are
  executed `delay_bars` bars later at the open or close, long-only without leverage, with `daily`, `weekly`, `monthly`
  and `on_signal` rebalancing, deferred orders for symbols without a price, two-sided turnover and a well-defined
  return of the first bar. Costs follow in Phase 5. Hand-calculated fixtures (H1 to H13) and seeded invariant tests
  (cash never negative, weights at most 100 percent, determinism, permuted universe, doubled capital, causality)
- `docs/engine.md` (semantics, assumptions and the fixtures with their arithmetic) and ADR 0008 (engine semantics)
- Engine, part 2 of Phase 4 (F-09, F-11): `run_backtest(spec, provider, allow_short_warmup=True)` loads history from
  `period.start` minus a warm-up buffer, validates it (errors stop the run), hashes the frame as loaded, runs the
  registered signal through its contract check and returns a frozen `BacktestResult` (equity, cash, positions,
  weights, trades, turnover, trimmed signals and target weights, deferred and unfilled orders, data hash, validation,
  risk flags, `costs_applied`). `WarmupInfo` reports how much history stood behind the first decision, including
  `first_decision_date` and `initial_target_weights`; too little history gives the flag `insufficient_warmup`, an
  `InsufficientWarmupWarning`, or `InsufficientHistoryError` with `allow_short_warmup=False`. The risk flag
  `costs_not_applied` marks a run whose costs were not deducted (since Phase 5 only `apply_costs=False`). Hand-calculated fixtures H14 and H15,
  invariant tests through the runner (including a causality test that perturbs all prices after a date), the three
  example specs end to end and a live `network` test of buy and hold on SPY, TLT and GLD
- ADR 0009 (run pipeline, warm-up and result object)

### Changed

- The validation line of the report uses the singular: `1 info`, `1 warning`, `1 error` (it said `1 infos`). Strings from the
  spec or the data that contain characters XML 1.0 forbids (such as NUL) now show U+FFFD in the report.
- `Portfolio.returns` and `BacktestResult.returns` are 0.0 after a portfolio was ruined by fees (equity 0) instead of
  NaN (0/0); the bar that ruined it keeps the return -1.
- A symbol without a price on the first bar is valued at its last close from the warm-up bars (before, the core
  raised `EngineError` when such a symbol got an order on the first bar); `simulate` takes the optional
  `initial_last_close`
- Template placeholders filled in `README.md`, `CLAUDE.md` (F-03), `CONTRIBUTING.md`, `LICENSE`, `docs/RELEASING.md`
  and the issue template; line endings are forced to LF in `.gitattributes`

[Unreleased]: https://github.com/Dominik2806/backtest-agent/commits/main
