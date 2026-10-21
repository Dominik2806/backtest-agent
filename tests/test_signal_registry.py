import pandas as pd
import pytest
from pydantic import ValidationError

from backtest_agent.spec import (
    SIGNALS,
    SignalContractError,
    SignalParams,
    SignalRegistry,
    UnknownSignalError,
    get_signal,
    list_signals,
    validate_signal_output,
)
from backtest_agent.spec.signals import per_symbol_signal
from signal_contract import check_signal_contract, contract_frames, fake_prices


class WindowParams(SignalParams):
    window: int = 3

    def warmup_rows(self) -> int:
        return self.window - 1


class DishonestParams(WindowParams):
    def warmup_rows(self) -> int:
        return 0  # declares no warm-up although the signal needs window - 1 rows


def above_mean(prices: pd.DataFrame, params: WindowParams) -> pd.DataFrame:
    """1.0 while the close is above its rolling mean."""

    def compute(close: pd.Series) -> pd.Series:
        mean = close.rolling(params.window, min_periods=params.window).mean()
        return (close > mean).astype("float64").where(mean.notna())

    return per_symbol_signal(prices, compute)


def make_registry() -> SignalRegistry:
    registry = SignalRegistry()
    registry.register("above_mean", params=WindowParams)(above_mean)
    registry.register("dishonest", params=DishonestParams)(above_mean)
    return registry


def prices(rows: int = 12) -> pd.DataFrame:
    return fake_prices(["AAA", "BBB"], rows)


# --- registry ---


def test_register_get_and_ids_with_a_private_registry() -> None:
    registry = make_registry()
    assert registry.ids() == ("above_mean", "dishonest")
    assert "above_mean" in registry and "nope" not in registry
    signal = registry.get("above_mean")
    assert signal.function is above_mean
    assert signal.params_model is WindowParams
    assert signal.description == "1.0 while the close is above its rolling mean."


def test_unknown_id_names_the_available_ids() -> None:
    with pytest.raises(UnknownSignalError, match=r"'nope'.*above_mean, dishonest"):
        make_registry().get("nope")
    with pytest.raises(UnknownSignalError, match="none registered"):
        SignalRegistry().get("nope")
    assert issubclass(UnknownSignalError, LookupError)


def test_duplicate_and_invalid_registration_is_rejected() -> None:
    registry = make_registry()
    with pytest.raises(ValueError, match="already registered"):
        registry.register("above_mean", params=WindowParams)(above_mean)
    for bad_id in ("Above", "1abc", "has space", ""):
        with pytest.raises(ValueError, match="signal id"):
            registry.register(bad_id)
    with pytest.raises(TypeError):
        registry.register("x", params=dict)  # type: ignore[arg-type]


def test_default_registry_functions_delegate() -> None:
    assert list_signals() == SIGNALS.ids()
    for signal_id in list_signals():
        assert get_signal(signal_id) is SIGNALS.get(signal_id)


# --- params ---


def test_parse_params_validates_and_applies_defaults() -> None:
    signal = make_registry().get("above_mean")
    assert signal.parse_params(None) == WindowParams(window=3)
    assert signal.parse_params({"window": 5}).window == 5
    instance = WindowParams(window=7)
    assert signal.parse_params(instance) is instance
    with pytest.raises(ValidationError):
        signal.parse_params({"window": "5"})  # strict: no str as int
    with pytest.raises(ValidationError):
        signal.parse_params({"windw": 5})  # unknown field
    with pytest.raises(TypeError):
        signal.parse_params(SignalParams())  # the params of another signal


def test_params_models_are_frozen_and_have_zero_default_warmup() -> None:
    assert SignalParams().warmup_rows() == 0
    assert WindowParams(window=5).warmup_rows() == 4
    assert make_registry().get("above_mean").warmup_rows({"window": 10}) == 9
    with pytest.raises(ValidationError):
        WindowParams().window = 9  # type: ignore[misc]


# --- generate enforces the contract ---


def test_generate_returns_a_valid_signal_frame() -> None:
    frame = prices()
    out = make_registry().get("above_mean").generate(frame, {"window": 3})
    validate_signal_output(frame, out)
    assert out.index.equals(frame.index)
    assert out.columns.name == "symbol"


def test_generate_rejects_a_non_standard_input() -> None:
    with pytest.raises(ValueError):
        make_registry().get("above_mean").generate(prices().iloc[::-1])


def test_generate_protects_the_callers_frame_from_in_place_changes() -> None:
    registry = SignalRegistry()

    @registry.register("vandal")
    def vandal(prices: pd.DataFrame, params: SignalParams) -> pd.DataFrame:
        prices.iloc[0, 0] = 999.0  # in-place write to the input
        return per_symbol_signal(prices, lambda close: close * 0.0 + 1.0)

    frame = prices()
    snapshot = frame.copy(deep=True)
    registry.get("vandal").generate(frame)
    pd.testing.assert_frame_equal(frame, snapshot, check_exact=True)


def with_value(frame: pd.DataFrame, value: float) -> pd.DataFrame:
    out = frame.copy()
    out.iloc[2, 0] = value
    return out


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        (lambda s: with_value(s, float("nan")), "NaN"),
        (lambda s: s + 1.5, "outside"),
        (lambda s: s - 0.6, "outside"),
        (lambda s: with_value(s, float("inf")), "infinite"),
        (lambda s: s.set_axis(s.index + pd.Timedelta(days=1)), "index"),
        (lambda s: s[["BBB", "AAA"]], "columns"),
        (lambda s: s[["AAA"]], "columns"),
        (lambda s: s.rename(columns={"AAA": "ZZZ"}), "columns"),
        (lambda s: s.rename_axis(columns="ticker"), "named 'symbol'"),
        (lambda s: s.astype("float32"), "float64"),
        (lambda s: s.astype("int64"), "float64"),
        (lambda s: s.iloc[:-1], "index"),
    ],
)
def test_validate_signal_output_rejects_violations(bad, message) -> None:
    frame = prices()
    good = make_registry().get("above_mean").generate(frame, {"window": 3}) * 0.0 + 0.5
    validate_signal_output(frame, good)
    with pytest.raises(SignalContractError, match=message):
        validate_signal_output(frame, bad(good))


def test_validate_signal_output_rejects_non_frames_and_lists_every_problem() -> None:
    frame = prices()
    with pytest.raises(SignalContractError, match="DataFrame"):
        validate_signal_output(frame, [1.0])  # type: ignore[arg-type]
    broken = pd.DataFrame(1.5, index=frame.index, columns=["X"]).astype("float32")
    with pytest.raises(SignalContractError) as info:
        validate_signal_output(frame, broken)
    assert "columns" in str(info.value) and "float64" in str(info.value)


def test_generate_raises_for_a_bad_signal_function() -> None:
    registry = SignalRegistry()

    @registry.register("too_big")
    def too_big(prices: pd.DataFrame, params: SignalParams) -> pd.DataFrame:
        return per_symbol_signal(prices, lambda close: close * 0.0 + 2.0)

    with pytest.raises(SignalContractError, match="outside"):
        registry.get("too_big").generate(prices())


# --- the reusable contract check itself ---


def test_contract_check_passes_for_an_honest_signal() -> None:
    signal = make_registry().get("above_mean")
    check_signal_contract(signal, WindowParams(window=4), contract_frames(rows=60))


def test_contract_check_catches_a_dishonest_warmup() -> None:
    signal = make_registry().get("dishonest")
    with pytest.raises(AssertionError):
        check_signal_contract(signal, DishonestParams(window=5), contract_frames(rows=60))


def test_per_symbol_signal_carries_forward_over_holidays_and_is_zero_before_the_first_row() -> None:
    frame = prices(8)
    for field in ("open", "high", "low", "close", "volume"):
        frame.loc[frame.index[[0, 1, 4]], ("BBB", field)] = float("nan")  # late start and a holiday
    out = per_symbol_signal(frame, lambda close: pd.Series(1.0, index=close.index))
    assert list(out["BBB"]) == [0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]  # row 4 carries 1.0
    assert list(out["AAA"]) == [1.0] * 8
