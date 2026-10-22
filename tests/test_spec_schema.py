import json
from datetime import date

import pytest
import yaml
from pydantic import ValidationError

from backtest_agent.spec import RiskFlag, StrategySpec, parse_spec
from backtest_agent.spec.builtin_signals import SmaCrossoverParams
from specs import to_yaml, valid


def spec_of(data: dict) -> StrategySpec:
    return parse_spec(to_yaml(data))


def test_a_valid_spec_loads_into_a_frozen_object() -> None:
    spec = spec_of(valid())
    assert spec.schema_version == 1
    assert spec.name == "SMA test"
    assert spec.universe == ["SPY", "QQQ"]
    assert (spec.period.start, spec.period.end) == (date(2015, 1, 1), date(2020, 12, 31))
    assert spec.data.provider == "yfinance"
    assert spec.signal.id == "sma_crossover"
    assert spec.execution.delay_bars == 1 and spec.execution.price == "open"
    assert spec.sizing.method == "equal_weight" and spec.sizing.fraction is None
    assert spec.rebalance == "on_signal"
    assert (spec.costs.commission_bps, spec.costs.spread_bps, spec.costs.slippage_bps) == (1.0, 2.0, 2.0)
    assert spec.benchmark == "SPY"
    assert spec.initial_capital == 100000.0
    with pytest.raises(ValidationError):
        spec.name = "other"  # type: ignore[misc]


def test_yaml_dates_without_quotes_are_accepted() -> None:
    text = (
        to_yaml(valid())
        .replace("start: '2015-01-01'", "start: 2015-01-01")
        .replace("end: '2020-12-31'", "end: 2020-12-31")
    )
    assert "start: 2015-01-01" in text
    assert parse_spec(text).period.start == date(2015, 1, 1)


def test_optional_blocks_have_documented_defaults() -> None:
    data = valid()
    for key in ("description", "data", "execution"):
        del data[key]
    spec = spec_of(data)
    assert spec.description == ""
    assert spec.data.provider == "yfinance"
    assert (spec.execution.delay_bars, spec.execution.price, spec.execution.allow_same_bar_execution) == (
        1,
        "open",
        False,
    )


def test_signal_params_are_stored_with_defaults_filled_in() -> None:
    data = valid()
    data["signal"] = {"id": "sma_crossover", "params": {"fast": 10}}
    spec = spec_of(data)
    assert spec.signal.params == {"fast": 10, "slow": 200}
    del data["signal"]["params"]
    assert spec_of(data).signal.params == {"fast": 50, "slow": 200}
    assert isinstance(spec.signal.params_model(), SmaCrossoverParams)
    assert spec.signal.params_model().slow == 200


def test_integers_are_accepted_where_numbers_are_expected() -> None:
    data = valid()
    data["costs"] = {"commission_bps": 0, "spread_bps": 1, "slippage_bps": 0}
    data["initial_capital"] = 5000
    spec = spec_of(data)
    assert spec.costs.spread_bps == 1.0
    assert spec.initial_capital == 5000.0


def test_warmup_rows_of_the_signal() -> None:
    assert spec_of(valid()).warmup_rows == 99  # slow = 100
    data = valid()
    data["signal"] = {"id": "momentum_12_1"}
    assert spec_of(data).warmup_rows == 252
    data["signal"] = {"id": "momentum_12_1", "params": {"lookback_days": 40, "skip_days": 5}}
    assert spec_of(data).warmup_rows == 40
    data["signal"] = {"id": "buy_and_hold"}
    assert spec_of(data).warmup_rows == 0


def test_fixed_fraction_sizing_and_symbols_kept_as_written() -> None:
    data = valid()
    data["sizing"] = {"method": "fixed_fraction", "fraction": 0.25}
    data["universe"] = ["SAP.DE", "^GSPC", "eurusd=x"]
    data["benchmark"] = "^GDAXI"  # a benchmark outside the universe is fine
    spec = spec_of(data)
    assert spec.sizing.fraction == 0.25
    assert spec.universe == ["SAP.DE", "^GSPC", "eurusd=x"]
    assert spec.benchmark == "^GDAXI"


def test_same_bar_execution_is_possible_only_with_the_explicit_flag_and_price_close() -> None:
    data = valid()
    data["execution"] = {"delay_bars": 0, "price": "close", "allow_same_bar_execution": True}
    assert spec_of(data).execution.delay_bars == 0


# --- risk flags ---


def test_a_normal_spec_has_no_risk_flags() -> None:
    assert spec_of(valid()).risk_flags() == ()


def test_same_bar_execution_is_flagged() -> None:
    data = valid()
    data["execution"] = {"delay_bars": 0, "price": "close", "allow_same_bar_execution": True}
    (flag,) = spec_of(data).risk_flags()
    assert flag.code == "same_bar_execution"
    assert "look-ahead" in flag.message


def test_zero_costs_are_flagged_only_when_all_three_are_zero() -> None:
    data = valid()
    data["costs"] = {"commission_bps": 0, "spread_bps": 0, "slippage_bps": 0}
    (flag,) = spec_of(data).risk_flags()
    assert flag.code == "zero_costs"
    data["costs"] = {"commission_bps": 0, "spread_bps": 0, "slippage_bps": 0.5}
    assert spec_of(data).risk_flags() == ()


def test_risk_flags_come_in_a_fixed_order_and_serialize() -> None:
    data = valid()
    data["execution"] = {"delay_bars": 0, "price": "close", "allow_same_bar_execution": True}
    data["costs"] = {"commission_bps": 0, "spread_bps": 0, "slippage_bps": 0}
    flags = spec_of(data).risk_flags()
    assert [f.code for f in flags] == ["same_bar_execution", "zero_costs"]
    assert all(isinstance(f, RiskFlag) for f in flags)
    assert set(flags[0].to_dict()) == {"code", "message"}
    json.dumps([f.to_dict() for f in flags])


# --- serialization ---


def test_to_dict_is_json_and_round_trips() -> None:
    spec = spec_of(valid())
    data = spec.to_dict()
    assert data["period"] == {"start": "2015-01-01", "end": "2020-12-31"}
    assert data["signal"] == {"id": "sma_crossover", "params": {"fast": 20, "slow": 100}}
    json.dumps(data)
    assert parse_spec(yaml.safe_dump(data)) == spec


def test_equal_specs_are_equal() -> None:
    assert spec_of(valid()) == spec_of(valid())
    other = valid()
    other["name"] = "other"
    assert spec_of(other) != spec_of(valid())


# --- min_commission ---


def test_min_commission_defaults_to_zero_and_accepts_a_value() -> None:
    assert spec_of(valid()).costs.min_commission == 0.0
    data = valid()
    data["costs"]["min_commission"] = 1
    assert spec_of(data).costs.min_commission == 1.0
    assert spec_of(data).to_dict()["costs"]["min_commission"] == 1.0
    assert parse_spec(yaml.safe_dump(spec_of(data).to_dict())) == spec_of(data)


def test_min_commission_is_a_cost_for_the_zero_costs_flag() -> None:
    data = valid()
    data["costs"] = {"commission_bps": 0, "spread_bps": 0, "slippage_bps": 0, "min_commission": 1}
    assert spec_of(data).risk_flags() == ()
    data["costs"]["min_commission"] = 0
    assert [f.code for f in spec_of(data).risk_flags()] == ["zero_costs"]
