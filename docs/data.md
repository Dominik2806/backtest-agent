# Data

How daily prices enter `backtest-agent`: one standard frame, produced by any provider, optionally served from a local
Parquet cache, then checked by a data quality validation and tied to a hash. Code lives in
`src/backtest_agent/data/`; see the [roadmap](ROADMAP.md) for the phases. The decisions behind this are
[ADR 0003](adr/0003-standard-price-frame.md) (format), [ADR 0004](adr/0004-validation-reports-calendar-heuristic.md)
(validation) and [ADR 0005](adr/0005-canonical-data-hash.md) (hash).

## Standard format

Every provider implements `DataProvider.get_prices(symbols, start, end)` and returns one `pandas.DataFrame`:

| Part | Rule |
|---|---|
| Index | `DatetimeIndex` named `date`: daily, timezone-naive, midnight, sorted ascending, unique, dtype `datetime64[ns]` |
| Columns | `MultiIndex` named `["symbol", "field"]`; symbols in request order, fields `open`, `high`, `low`, `close`, `volume` in this order |
| Values | `float64` everywhere, including `volume` (so a missing value can be NaN) |

```python
from datetime import date
from backtest_agent.data import FakeProvider

frame = FakeProvider().get_prices(["AAA", "BBB"], date(2024, 1, 2), date(2024, 3, 29))
frame["AAA"]["close"]  # one series
frame.xs("close", axis=1, level="field")  # close of all symbols
```

`validate_standard_frame(frame, symbols)` raises `ValueError` if a frame breaks these rules. The reusable contract test
(`tests/contract.py`) runs it against every provider.

### Dates are inclusive

`start` and `end` are plain `datetime.date` values (not `datetime`, not strings) and **both are inclusive**: a request
from 2024-01-02 to 2024-03-29 contains the bars of both days if the market was open. Non-trading days are simply
absent. The yfinance API treats its own `end` as exclusive; the provider adds one day so the convention above holds.

### Several symbols, different calendars

The index is the union of the trading days of all symbols. A symbol that did not trade on a day (for example a German
holiday while the US market is open) has NaN in all five fields on that row. Nothing is forward-filled, because that
would hide gaps; the [validation](#validation) judges such rows per symbol and ignores all-NaN rows. A symbol with no
rows at all in the range is an error, not a column of NaN.

### Timezones

yfinance returns timezone-aware timestamps in the exchange timezone (for example midnight `Europe/Berlin` for `.DE`
tickers). They are converted to plain dates by dropping the timezone **without converting it**, so the index keeps
the exchange's own calendar date. Converting to UTC would move German midnights to the previous day and is avoided on
purpose.

## Adjustment rules

All prices are adjusted for splits **and** dividends (yfinance `auto_adjust=True`), and `close` is the adjusted close.

- Open, high, low and close are scaled by the same factor, so they stay consistent with each other.
- Adjusted prices represent **total return with dividends reinvested**: a buy-and-hold return computed from `close`
  includes dividends. The engine therefore never adds dividends separately.
- Volume is adjusted for splits only, not for dividends.
- Adjusted prices are not the prices that were quoted on a given day. Historical values are rescaled whenever a new
  split or dividend happens, so do not compare them with an old chart or use them for absolute price levels.

## Cache

`CachedProvider(inner, cache_dir="data/cache", offline=False, refresh=False)` wraps any provider. For yfinance:

```python
from backtest_agent.data.cache import CachedProvider
from backtest_agent.data.yfinance_provider import YFinanceProvider

provider = CachedProvider(YFinanceProvider())
```

- **Layout:** one Parquet file per provider, symbol and exact request, for example
  `data/cache/yfinance/AAPL_2020-01-01_2020-12-31.parquet`. Special characters in symbols are percent-encoded
  (`^GSPC` becomes `%5EGSPC`). The directory is configurable with `cache_dir`; the default `data/cache/` is relative
  to the working directory and git-ignored.
- **Hit and miss:** a request is a hit only for the identical symbol, start and end. A wider cached range is not reused
  for a narrower request. Requesting several symbols fetches only the symbols that are missing. A hit and a miss
  return identical frames, and a hit makes no network call.
- **Today and the future are never cached.** If `end` is today or later, the request always goes to the inner
  provider and the result is not written, because the bar of the current day is still partial and the cache would
  keep it forever. The date of "today" is injectable (`today=`) for tests. Only requests that end before today are
  cached.
- **Offline mode:** `offline=True` never calls the inner provider. A request that is not fully cached, or that ends
  today or later, raises `OfflineCacheMissError` naming the missing symbols.
- **Refresh:** `refresh=True` ignores existing files, downloads again and overwrites them. `offline` and `refresh`
  together are rejected.
- **Stale files:** adjusted history changes after every new dividend or split, because all earlier prices are
  rescaled. A cached file therefore becomes stale, and there is deliberately no expiry (an expiry would make runs
  silently non-reproducible). Use `refresh=True` to download again. The [data hash](#data-hash) makes such changes
  visible, because the same request then yields a different hash.
- **Damaged files:** an unreadable cache file counts as a miss. Online it is downloaded again, offline it raises
  `OfflineCacheMissError`. Files are written atomically (temporary file, then rename).

## Validation

`validate_prices(frame, config=None, start=None, end=None)` checks the quality of the data and **reports** instead of
raising. It never modifies the frame (it works on a sorted, de-duplicated copy), and its result is deterministic.
`validate_standard_frame()` stays separate: it raises for format violations of the standard frame, while
`validate_prices` accepts frames with unsorted or duplicate dates because reporting those is part of its job. It raises
`ValueError` only for structural problems (not a timezone-naive `DatetimeIndex`, columns not `(symbol, field)` with
all five fields per symbol, non-numeric values, an empty frame, `start` after `end`).

**Rows with data.** Every per-symbol check looks only at the rows where that symbol has data, meaning at least one
field is not NaN. All-NaN rows are non-trading days (the outer join of different calendars) and are never an issue. A
row with data but a NaN price is the real error.

### Checks

| Code | Severity | Fires when | Default threshold |
|---|---|---|---|
| `unsorted_dates` | error | the index is not ascending (frame level) | none |
| `duplicate_dates` | error | a date appears more than once (frame level) | none |
| `no_data` | error | a symbol has no row with data | none |
| `non_finite_value` | error | a field contains infinity | none |
| `nan_in_history` | error | a row with data has NaN in open, high, low or close | none |
| `non_positive_price` | error | open, high, low or close is 0 or negative | none |
| `negative_volume` | error | volume is negative | none |
| `nan_volume` | warning | a row with data has NaN volume | none |
| `ohlc_high_below_low` | warning | high is below low | `ohlc_tolerance` 0.001 (0.1 percent, relative) |
| `ohlc_close_outside_range` | warning | close is outside the high-low range | `ohlc_tolerance` 0.001 |
| `ohlc_open_outside_range` | warning | open is outside the high-low range | `ohlc_tolerance` 0.001 |
| `calendar_gap` | warning | more missing Mon-Fri days than allowed between two consecutive data dates of a symbol | `max_gap_business_days` 4 |
| `extreme_move` | warning | the close-to-close move is larger than the limit | `max_daily_move` 0.40 (40 percent) |
| `stale_price` | warning | the same close on this many consecutive rows or more | `stale_run_length` 5 |
| `split_artifact` | warning | a close-to-close ratio is within the tolerance of a split ratio | `split_ratios` 1/2, 1/3, 1/4, 1/5, 1/10, 2, 3, 4, 5, 10; `split_tolerance` 0.05 (5 percent of the ratio) |
| `zero_volume` | info | volume is exactly 0 | none |
| `starts_late` | info | the first data date is more business days after `start` than allowed | `range_tolerance_business_days` 3 |
| `ends_early` | info | the last data date is more business days before `end` than allowed | `range_tolerance_business_days` 3 |

Details that matter:

- **Severities.** Errors stop a run, warnings appear in the report, infos are context. Volume is deliberately not an
  error when it is NaN or zero: the engine is price-based, and indices and FX pairs often have no usable volume.
- **One summary per symbol and field.** A check never produces one issue per row. Every issue carries `count` (the
  number of affected rows) and at most `max_dates_per_issue` (default 5) `first_dates`. A symbol whose volume is NaN
  (or zero) on every row gives exactly one `nan_volume` (or `zero_volume`) issue with `count` equal to the number of
  rows, and its message says "every row". For `starts_late` and `ends_early`, `count` is the number of missing
  business days.
- **Strict thresholds.** A move of exactly 40 percent, a gap of exactly 4 missing business days, a stale run of 4
  or a range deviation of exactly 3 business days does not fire; one more does.
- **No cascades.** OHLC checks use only rows whose four prices are finite and positive, and high and low are ordered
  first, so a swapped high and low is one issue. Move, stale and split checks use only rows with a valid close. Moves
  are measured between consecutive data rows, also across gaps.
- **Split-sized jumps fire twice.** A jump to 1/2 or 2 times the price is both `split_artifact` and `extreme_move`;
  they are independent on purpose. Splits of 3 for 2 (1.5) are not in the default ratios and show up as
  `extreme_move` only if larger than the limit; add the ratio to `split_ratios` to flag it.
- **Calendar gaps are a heuristic.** There is no exchange calendar. The check counts missing Monday-to-Friday days
  between a symbol's own consecutive data dates, which works the same for frames where the rows are absent and for
  all-NaN rows. Holidays and Easter stay below the default limit of 4 (the longest real closure I know of is 4 days,
  US markets in September 2001). Limits: **one missing day looks like a holiday and is not detected**, and a frame
  cannot tell a missing day from an exchange holiday. Symbols that trade on weekends (crypto) cause no false gaps.
  See [ADR 0004](adr/0004-validation-reports-calendar-heuristic.md).

### Result, thresholds and errors

```python
from backtest_agent.data import ValidationConfig, validate_prices

result = validate_prices(frame, ValidationConfig(max_daily_move=0.25), start=start, end=end)
result.errors, result.warnings, result.infos  # tuples of ValidationIssue
result.to_json()  # deterministic JSON for the report and the journal
result.raise_for_errors()  # raises DataValidationError if there is any error
```

- A `ValidationIssue` has `severity`, a stable `code`, `symbol` and `field` (both `None` for frame-level issues),
  `count`, `first_dates` and a readable `message`.
- Issues are ordered errors first, then warnings, then infos, and in the fixed order of the table above inside a
  severity (symbols in column order). Equal data and config give an equal result and identical JSON.
- `to_dict()` and `to_json()` (sorted keys, ISO dates) contain `ok`, `counts`, `issues` and the `config` that was
  used, so a stored result states its own thresholds.
- `ValidationConfig` is a frozen dataclass with the defaults of the table; change a threshold per run with a new
  instance or `dataclasses.replace`. Invalid values raise `ValueError`.
- `raise_for_errors()` raises `DataValidationError` (a `DataError`, with the full result in `.result`) if there is at
  least one error, and never for warnings or infos. `run_backtest` (Phase 4, see [engine.md](engine.md)) calls
  it before every run and so will the command line (Phase 9); warnings and infos go into the result.

## Data hash

`hash_frame(frame)` returns the SHA-256 hex digest (64 lowercase characters) of the data, so a result can be tied to
the exact data it used. The frame must follow the standard format (`ValueError` otherwise). The hashed bytes are, in
order (version `HASH_VERSION = "1"`):

1. the ASCII tag `backtest-agent/frame-hash/v1` and a newline (the version prefix);
2. the row count and the symbol count, each as little-endian `uint64`;
3. for every column, with symbols sorted and fields in the order `open`, `high`, `low`, `close`, `volume`: the symbol
   and the field as UTF-8, each prefixed by its byte length as little-endian `uint64`;
4. the index as little-endian `int64`, days since 1970-01-01;
5. the values column by column as little-endian `float64`, with every NaN written as the one canonical NaN
   (`0x7ff8000000000000`) and negative zero written as positive zero.

Consequences: the digest is the same on Windows and Linux and does not depend on the pandas, numpy or Parquet version
(Parquet or pickle bytes are never hashed), on the datetime unit, or on the order in which symbols were requested. Any
single changed value, date, name or row count gives a different digest. A cache round trip keeps the hash. The
hash is bitwise on `float64`, so a provider that returns prices that differ in the last bit gives a different hash.
Any change of this layout must bump `HASH_VERSION` and is recorded in
[ADR 0005](adr/0005-canonical-data-hash.md); a test with a hard-coded digest guards the layout.

## Errors

| Error | When |
|---|---|
| `ValueError` | empty or duplicate symbols, `start` after `end`, `start` or `end` not a `date` |
| `DataUnavailableError` | a symbol is unknown or empty at yfinance, or has no rows in the range; the message names every failing symbol |
| `OfflineCacheMissError` | offline mode and the data is not cached (or the range ends today or later) |
| `DataValidationError` | `ValidationResult.raise_for_errors()` found at least one validation error |
| `DataError` | any other data source failure, for example a yfinance rate limit |

A failing symbol never produces an empty frame or a silently missing column.

## Providers

| Provider | Use |
|---|---|
| `YFinanceProvider` | real daily prices from Yahoo Finance, normally wrapped in `CachedProvider` |
| `FakeProvider` | deterministic synthetic prices (seeded random walk, Monday to Friday, 2015 to 2030) for tests and examples; never touches the network; `calls` records every request |

Tests never use the network. yfinance is mocked, and the single live test is marked `network` and excluded by default:

```powershell
uv run pytest -m network
```

## Data source caveats

- **yfinance is unofficial.** It scrapes Yahoo Finance, is not endorsed by Yahoo, and may break or change without
  notice. Yahoo's terms allow personal use only, which is the scope of this project.
- **Data can be wrong.** Yahoo has missing days, wrong splits, bad dividend adjustments and revised history. The
  [validation](#validation) catches many such problems, but it cannot prove the data is right.
- **Requests can be rate-limited or fail.** Fetch once, rely on the cache afterwards.
- **Survivorship bias:** tickers that exist today are the survivors. Delisted companies are mostly missing.
- **Data is never committed.** Market data and the cache are git-ignored (`data/`, `*.parquet`) because the source's
  terms do not allow redistribution and the files would go stale.

This is educational software, not investment advice.
