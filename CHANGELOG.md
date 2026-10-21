# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

### Changed

- Template placeholders filled in `README.md`, `CLAUDE.md` (F-03), `CONTRIBUTING.md`, `LICENSE`, `docs/RELEASING.md`
  and the issue template; line endings are forced to LF in `.gitattributes`

[Unreleased]: https://github.com/Dominik2806/backtest-agent/commits/main
