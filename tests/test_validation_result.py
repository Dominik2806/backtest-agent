import dataclasses
import json
from datetime import date

import pytest

from backtest_agent.data import (
    DataError,
    DataValidationError,
    Severity,
    ValidationConfig,
    ValidationIssue,
    ValidationResult,
)


def issue(severity: Severity, code: str, symbol: str | None = "AAA", count: int = 1) -> ValidationIssue:
    return ValidationIssue(severity, code, symbol, "close", count, (date(2024, 1, 2),), f"message of {code}")


def test_issues_are_ordered_errors_then_warnings_then_infos_keeping_generation_order() -> None:
    result = ValidationResult(
        (
            issue(Severity.INFO, "i1"),
            issue(Severity.WARNING, "w1"),
            issue(Severity.ERROR, "e1"),
            issue(Severity.WARNING, "w2"),
            issue(Severity.ERROR, "e2"),
        )
    )
    assert [i.code for i in result.issues] == ["e1", "e2", "w1", "w2", "i1"]
    assert [i.code for i in result.errors] == ["e1", "e2"]
    assert [i.code for i in result.warnings] == ["w1", "w2"]
    assert [i.code for i in result.infos] == ["i1"]
    assert result.has_errors


def test_raise_for_errors_raises_with_result_attached() -> None:
    result = ValidationResult((issue(Severity.ERROR, "nan_in_history"), issue(Severity.WARNING, "extreme_move")))
    with pytest.raises(DataValidationError, match="nan_in_history") as info:
        result.raise_for_errors()
    assert info.value.result is result
    assert isinstance(info.value, DataError)
    assert "extreme_move" not in str(info.value)


def test_raise_for_errors_lists_at_most_three_errors() -> None:
    result = ValidationResult(tuple(issue(Severity.ERROR, f"e{n}") for n in range(5)))
    with pytest.raises(DataValidationError, match=r"5 data error.*and 2 more"):
        result.raise_for_errors()


def test_warnings_and_infos_never_raise() -> None:
    result = ValidationResult((issue(Severity.WARNING, "w"), issue(Severity.INFO, "i")))
    result.raise_for_errors()
    assert not result.has_errors


def test_empty_result_is_ok() -> None:
    result = ValidationResult(())
    result.raise_for_errors()
    assert result.to_dict()["ok"] is True
    assert result.to_dict()["counts"] == {"error": 0, "warning": 0, "info": 0}


def test_to_dict_and_json_are_plain_and_deterministic() -> None:
    frame_level = ValidationIssue(Severity.ERROR, "duplicate_dates", None, None, 2, (date(2024, 1, 2),), "m")
    result = ValidationResult((issue(Severity.WARNING, "extreme_move"), frame_level))
    data = result.to_dict()
    assert data["ok"] is False
    assert data["counts"] == {"error": 1, "warning": 1, "info": 0}
    assert data["issues"][0] == {
        "severity": "error",
        "code": "duplicate_dates",
        "symbol": None,
        "field": None,
        "count": 2,
        "first_dates": ["2024-01-02"],
        "message": "m",
    }
    assert json.loads(result.to_json()) == data
    same = ValidationResult((issue(Severity.WARNING, "extreme_move"), frame_level))
    assert result.to_json() == same.to_json()
    assert data["config"] == ValidationConfig().to_dict()


def test_config_is_frozen_and_documented_defaults() -> None:
    config = ValidationConfig()
    assert config.max_daily_move == 0.40
    assert config.max_gap_business_days == 4
    assert config.stale_run_length == 5
    assert config.split_ratios == (1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 10, 2.0, 3.0, 4.0, 5.0, 10.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.max_daily_move = 0.1  # type: ignore[misc]
    assert dataclasses.replace(config, max_daily_move=0.25).max_daily_move == 0.25
    assert json.dumps(config.to_dict())  # serializable


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_daily_move": 0},
        {"ohlc_tolerance": -1},
        {"split_tolerance": 0},
        {"stale_run_length": 0},
        {"max_dates_per_issue": 0},
        {"max_gap_business_days": -1},
        {"range_tolerance_business_days": -1},
        {"split_ratios": ()},
        {"split_ratios": (2.0, 0.0)},
    ],
)
def test_invalid_config_is_rejected(kwargs) -> None:
    with pytest.raises(ValueError):
        ValidationConfig(**kwargs)
