"""load_history: the one loader of a run (window, checks, validation result and hash); literals of fixture R3b."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from backtest_agent.data import DataUnavailableError, DataValidationError
from backtest_agent.engine import LoadedHistory, WarmupWindow, load_history, run_backtest
from backtest_agent.metrics import benchmark_spec
from report_helpers import spec_for, world
from runner_helpers import LiteralProvider

# SHA-256 of the frames of A and B of the R3b world, computed with hashlib from the layout of docs/data.md
HASH_A = "61669f6e7476623e1289ff7dad8c8b767f36be44961c05ec4def3f45c15dd090"
HASH_B = "ff487f9000d166df03fa5e84640c7524f7414b58173ed654e33fab7f1df0b094"
WINDOW_16 = WarmupWindow(required_rows=0, delay_bars=1, rows_needed=1, buffer_days=16, fetch_start=date(2023, 12, 17))


def test_the_strategy_request_is_the_universe_over_the_window_with_its_hash_and_counts() -> None:
    provider = LiteralProvider(world())
    loaded = load_history(spec_for(), provider)
    assert isinstance(loaded, LoadedHistory)
    assert provider.calls == [(("A",), date(2023, 12, 17), date(2024, 1, 8))]
    assert loaded.window == WINDOW_16
    assert list(loaded.frame.columns.get_level_values("symbol").unique()) == ["A"]
    assert len(loaded.frame) == 5
    assert loaded.data_hash == HASH_A
    # the data starts 2024-01-02, 11 business days after 2023-12-17 (tolerance 3): one starts_late info
    assert [(i.code, i.symbol, i.count) for i in loaded.validation.infos] == [("starts_late", "A", 11)]
    assert loaded.validation.errors == () and loaded.validation.warnings == ()


def test_the_benchmark_request_is_its_own_spec() -> None:
    provider = LiteralProvider(world())
    loaded = load_history(benchmark_spec(spec_for()), provider)
    assert provider.calls == [(("B",), date(2023, 12, 17), date(2024, 1, 8))]
    assert loaded.window == WINDOW_16
    assert loaded.data_hash == HASH_B


def test_validation_errors_are_returned_while_run_backtest_still_raises_them() -> None:
    frame = world()
    frame.loc[pd.Timestamp("2024-01-04"), ("A", "close")] = np.nan
    loaded = load_history(spec_for(), LiteralProvider(frame))
    assert loaded.validation.has_errors
    assert {issue.code for issue in loaded.validation.errors} == {"nan_in_history"}
    assert len(loaded.data_hash) == 64 and loaded.data_hash != HASH_A
    with pytest.raises(DataValidationError):
        run_backtest(spec_for(), LiteralProvider(frame))


def test_a_symbol_the_provider_did_not_deliver_raises() -> None:
    provider = LiteralProvider(world(("B",)), strict=False)
    with pytest.raises(DataUnavailableError, match=r"the provider returned no data for \['A'\]"):
        load_history(spec_for(), provider)


def test_rows_after_period_end_raise() -> None:
    spec = spec_for()
    provider = LiteralProvider(world(), clip_end=False)
    shorter = spec.model_copy(update={"period": spec.period.model_copy(update={"end": date(2024, 1, 5)})})
    with pytest.raises(ValueError, match="rows after period.end 2024-01-05 .last: 2024-01-08"):
        load_history(shorter, provider)
