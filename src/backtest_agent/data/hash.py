"""Canonical SHA-256 hash of a standard price frame (see docs/data.md and ADR 0005)."""

import hashlib
import struct

import numpy as np
import pandas as pd

from backtest_agent.data.provider import FIELDS, validate_standard_frame

#: Version of the byte layout below. Any change of the layout must bump it, so old and new hashes never collide.
HASH_VERSION = "1"

_TAG = f"backtest-agent/frame-hash/v{HASH_VERSION}\n".encode("ascii")


def hash_frame(frame: pd.DataFrame) -> str:
    """Return the SHA-256 hex digest (64 lowercase characters) of the data in ``frame``.

    The frame must follow the standard format (``ValueError`` otherwise). The digest depends only on the values, so
    it is the same on every platform and library version, and does not depend on the order in which the symbols were
    requested. The hashed bytes, in order:

    1. the ASCII tag ``backtest-agent/frame-hash/v<HASH_VERSION>``, newline;
    2. row count and symbol count as little-endian uint64;
    3. for every column (symbols sorted, fields in ``FIELDS`` order): symbol and field as UTF-8, each prefixed by its
       byte length as little-endian uint64;
    4. the index as little-endian int64 days since 1970-01-01;
    5. the values column by column as little-endian float64, every NaN as the one canonical NaN bit pattern and
       negative zero as positive zero.
    """
    validate_standard_frame(frame)
    symbols = sorted(set(frame.columns.get_level_values("symbol")))
    columns = [(symbol, field) for symbol in symbols for field in FIELDS]

    digest = hashlib.sha256()
    digest.update(_TAG)
    digest.update(struct.pack("<QQ", len(frame), len(symbols)))
    for column in columns:
        for name in column:
            encoded = name.encode("utf-8")
            digest.update(struct.pack("<Q", len(encoded)))
            digest.update(encoded)
    digest.update(frame.index.values.astype("datetime64[D]").astype("<i8").tobytes())
    for column in columns:
        values = frame[column].to_numpy(dtype="float64", copy=True)
        values[np.isnan(values)] = np.nan  # one bit pattern for every NaN payload
        values[values == 0.0] = 0.0  # negative zero becomes positive zero
        digest.update(values.astype("<f8").tobytes())
    return digest.hexdigest()
