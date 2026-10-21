# 0003: One standard price frame, adjusted prices, caching as a wrapper

- **Status:** Accepted

## Context

Every later phase (validation, engine, metrics) consumes price data, and the data comes from sources with different
shapes, timezones and adjustment conventions. The format chosen now is the contract for all of them. Results must be
reproducible and tests must never need the network.

## Decision

- Every provider returns one `pandas.DataFrame`: a daily, timezone-naive, sorted, unique `DatetimeIndex` named `date`
  and `MultiIndex` columns `(symbol, field)` with the lowercase fields `open`, `high`, `low`, `close`, `volume`, all
  `float64`. Dates in requests are inclusive on both ends.
- Prices are adjusted for splits and dividends, and `close` is the adjusted close, which means total return with
  dividends reinvested. The engine does not handle dividends separately.
- Symbols with different calendars are joined on the union of dates with NaN, never forward-filled, so that
  validation can see the gaps.
- Caching is a wrapper (`CachedProvider`) around any provider, not part of the yfinance provider. It stores one
  Parquet file per symbol and exact request, never caches requests that end today or later, has no expiry and offers
  `refresh` and `offline` modes.

Alternatives rejected: a dict of one frame per symbol or a long ("tidy") frame (more code for every consumer, and
cross-sectional operations such as momentum ranking are natural on a wide frame); unadjusted prices plus a separate
dividend series (the engine would need dividend handling, which is a source of errors); a cache inside the yfinance
provider (the cache logic could then only be tested against yfinance, and would be duplicated for later providers);
reusing a wider cached range for a narrower request and cache expiry (more logic and silent non-reproducibility, can be
added later).

## Consequences

- Phase 2 and later phases can rely on one shape and test against `FakeProvider`.
- Adjusted history changes with every new dividend or split, so cached files can go stale; the data hash planned for
  Phase 2 makes such a change visible and `refresh` re-downloads.
- Adjusted prices are not the quoted historical prices.
- A wide frame with several calendars contains NaN rows that every consumer must handle.
- See [data.md](../data.md) for the details and the data source caveats.
