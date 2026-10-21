# 0005: Canonical data hash

- **Status:** Accepted

## Context

Every result must be tied to the exact data it used, so the same spec on the same data hash reproduces the same
numbers, and a change in the data (for example after a new dividend rewrites adjusted history) is visible. The hash
is stored in the journal, so its definition must not change silently. Parquet and pickle bytes differ between library
versions and platforms, so they cannot be hashed.

## Decision

`hash_frame` returns the SHA-256 hex digest of a canonical byte string built from the frame itself, not from any file:

- a version tag (`backtest-agent/frame-hash/v1`), the row and symbol counts, the length-prefixed UTF-8 symbol and field
  names, the index as `int64` days since 1970-01-01, and the values column by column as little-endian `float64`;
- columns sorted by symbol (fields in the standard order), so the order of the request does not matter;
- every NaN has one bit pattern and negative zero equals positive zero;
- the frame must follow the standard format, otherwise `ValueError`.

The full layout is in [data.md](../data.md). **Any change of the layout bumps `HASH_VERSION`** and needs a new ADR, and
a test with a hard-coded digest, which also runs in CI on Windows and Linux, guards the current layout.

Alternatives rejected: hashing Parquet or pickle bytes or `pandas.util.hash_pandas_object` (not stable across library
versions); hashing a CSV rendering (float formatting is not a stable contract); a tolerance-based hash (hashes must be
exact, and rounding hides real changes).

## Consequences

- The same data gives the same hash on Windows and Linux and across pandas, numpy and Parquet versions.
- The hash is bitwise: values that differ in the last bit give a different hash. Re-downloading data after the source
  rewrote history gives a new hash, which is the point.
- The Parquet cache round trip is lossless for `float64`, so cache hit and miss give the same hash (tested).
- The frame must be in the standard format before it can be hashed, which makes validation of the format a
  precondition.
