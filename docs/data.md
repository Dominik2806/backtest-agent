# Data

How daily prices enter `backtest-agent`: one standard frame, produced by any provider, optionally served from a local
Parquet cache. Code lives in `src/backtest_agent/data/`; validation checks and the data hash arrive in Phase 2 (see
the [roadmap](ROADMAP.md)). The decision behind the format is [ADR 0003](adr/0003-standard-price-frame.md).

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
would hide gaps; Phase 2 validation is where such rows get judged. A symbol with no rows at all in the range is an
error, not a column of NaN.

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
  silently non-reproducible). Use `refresh=True` to download again. The data hash planned for Phase 2 will make such
  changes visible, because the same request then yields a different hash.
- **Damaged files:** an unreadable cache file counts as a miss. Online it is downloaded again, offline it raises
  `OfflineCacheMissError`. Files are written atomically (temporary file, then rename).

## Errors

| Error | When |
|---|---|
| `ValueError` | empty or duplicate symbols, `start` after `end`, `start` or `end` not a `date` |
| `DataUnavailableError` | a symbol is unknown or empty at yfinance, or has no rows in the range; the message names every failing symbol |
| `OfflineCacheMissError` | offline mode and the data is not cached (or the range ends today or later) |
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
- **Data can be wrong.** Yahoo has missing days, wrong splits, bad dividend adjustments and revised history. Phase 2
  adds checks, but they cannot prove the data is right.
- **Requests can be rate-limited or fail.** Fetch once, rely on the cache afterwards.
- **Survivorship bias:** tickers that exist today are the survivors. Delisted companies are mostly missing.
- **Data is never committed.** Market data and the cache are git-ignored (`data/`, `*.parquet`) because the source's
  terms do not allow redistribution and the files would go stale.

This is educational software, not investment advice.
