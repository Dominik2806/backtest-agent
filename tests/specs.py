"""Helpers to build spec YAML for tests."""

import copy
from typing import Any

import yaml

VALID: dict[str, Any] = {
    "schema_version": 1,
    "name": "SMA test",
    "description": "A spec used in tests.",
    "universe": ["SPY", "QQQ"],
    "period": {"start": "2015-01-01", "end": "2020-12-31"},
    "data": {"provider": "yfinance"},
    "signal": {"id": "sma_crossover", "params": {"fast": 20, "slow": 100}},
    "execution": {"delay_bars": 1, "price": "open", "allow_same_bar_execution": False},
    "sizing": {"method": "equal_weight"},
    "rebalance": "on_signal",
    "costs": {"commission_bps": 1.0, "spread_bps": 2.0, "slippage_bps": 2.0},
    "benchmark": "SPY",
    "initial_capital": 100000,
}


def valid() -> dict[str, Any]:
    return copy.deepcopy(VALID)


def to_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False)
