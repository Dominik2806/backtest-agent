import pytest
from pydantic import ValidationError

from backtest_agent.spec import get_signal, list_signals
from backtest_agent.spec.builtin_signals import BuyAndHoldParams, Momentum121Params, SmaCrossoverParams
from frames import literal_frame

NAN = float("nan")


def generate(signal_id: str, frame, **params):
    return get_signal(signal_id).generate(frame, params)


def test_the_three_builtins_are_registered() -> None:
    assert list_signals() == ("buy_and_hold", "momentum_12_1", "sma_crossover")
    for signal_id in list_signals():
        assert get_signal(signal_id).description


# --- sma_crossover ---


def test_sma_crossover_on_a_literal_series() -> None:
    # closes 1 2 3 2 1 2 4 with fast = 2 and slow = 3, SMA on the rows that have enough history:
    #   row   0    1    2     3      4    5      6
    #   fast  -    1.5  2.5   2.5    1.5  1.5    3.0
    #   slow  -    -    2.0   2.333  2.0  1.667  2.333
    #   fast > slow:    yes   yes    no   no     yes
    # warm-up rows 0 and 1 (slow average undefined) are 0.0
    frame = literal_frame({"AAA": [1, 2, 3, 2, 1, 2, 4]})
    out = generate("sma_crossover", frame, fast=2, slow=3)
    assert out["AAA"].tolist() == [0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0]


def test_sma_crossover_needs_a_strict_cross() -> None:
    out = generate("sma_crossover", literal_frame({"AAA": [5, 5, 5, 5, 5]}), fast=2, slow=3)
    assert out["AAA"].tolist() == [0.0] * 5  # equal averages are not "above"


def test_sma_crossover_counts_windows_in_the_symbols_own_trading_rows_and_carries_over_holidays() -> None:
    # Row 3 is a holiday of AAA: the averages ignore it, and the signal of row 2 is carried over it.
    frame = literal_frame({"AAA": [1, 2, 3, NAN, 2, 1, 2, 4]})
    out = generate("sma_crossover", frame, fast=2, slow=3)
    assert out["AAA"].tolist() == [0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 1.0]


def test_sma_crossover_is_computed_per_symbol() -> None:
    frame = literal_frame({"UP": [1, 2, 3, 4, 5], "DOWN": [5, 4, 3, 2, 1]})
    out = generate("sma_crossover", frame, fast=2, slow=3)
    assert out["UP"].tolist() == [0.0, 0.0, 1.0, 1.0, 1.0]
    assert out["DOWN"].tolist() == [0.0] * 5


def test_sma_crossover_params() -> None:
    assert SmaCrossoverParams().fast == 50 and SmaCrossoverParams().slow == 200
    assert SmaCrossoverParams().warmup_rows() == 199
    assert SmaCrossoverParams(fast=2, slow=3).warmup_rows() == 2
    for bad in ({"fast": 10, "slow": 10}, {"fast": 30, "slow": 10}):
        with pytest.raises(ValidationError, match="slow must be larger than fast"):
            SmaCrossoverParams(**bad)
    for bad in ({"fast": 0}, {"fast": "5"}, {"fast": True}, {"slow": 1}, {"fast": 2.5}, {"fats": 5}):
        with pytest.raises(ValidationError):
            SmaCrossoverParams(**bad)


# --- momentum_12_1 ---

MOMENTUM = {
    "A": [10, 11, 12, 13, 14, 15],
    "B": [20, 18, 16, 20, 25, 24],
    "C": [5, 5, 5, 6, 7, 9],
}
# With lookback_days = 3 and skip_days = 1 the score of row k is close[k-1] / close[k-3] - 1, first defined on row 3:
#   row 3:  A 12/10-1 = 0.2000   B 16/20-1 = -0.2000   C 5/5-1 = 0.0000
#   row 4:  A 13/11-1 = 0.1818   B 20/18-1 =  0.1111   C 6/5-1 = 0.2000
#   row 5:  A 14/12-1 = 0.1667   B 25/16-1 =  0.5625   C 7/5-1 = 0.4000


def momentum(**params):
    params = {"lookback_days": 3, "skip_days": 1, **params}
    return generate("momentum_12_1", literal_frame(MOMENTUM), **params)


def test_momentum_holds_the_top_symbol() -> None:
    out = momentum(top_n=1)
    assert out["A"].tolist() == [0, 0, 0, 1, 0, 0]
    assert out["B"].tolist() == [0, 0, 0, 0, 0, 1]
    assert out["C"].tolist() == [0, 0, 0, 0, 1, 0]


def test_momentum_holds_the_top_two_symbols() -> None:
    out = momentum(top_n=2)
    assert out["A"].tolist() == [0, 0, 0, 1, 1, 0]  # rows 3, 4: A in the top 2; row 5: B 0.5625 and C 0.4 beat A
    assert out["B"].tolist() == [0, 0, 0, 0, 0, 1]  # row 3: B has the lowest score
    assert out["C"].tolist() == [0, 0, 0, 1, 1, 1]


def test_momentum_positive_filter_holds_fewer_than_top_n() -> None:
    out = momentum(top_n=3, positive_only=True)
    assert out["A"].tolist() == [0, 0, 0, 1, 1, 1]
    assert out["B"].tolist() == [0, 0, 0, 0, 1, 1]  # row 3: -0.2 is not positive
    assert out["C"].tolist() == [0, 0, 0, 0, 1, 1]  # row 3: 0.0 is not strictly positive


def test_momentum_without_the_filter_holds_negative_scores_too() -> None:
    out = momentum(top_n=3)
    assert out.iloc[3].tolist() == [1.0, 1.0, 1.0]  # all three, although B is negative


def test_momentum_ties_go_to_the_first_column() -> None:
    frame = literal_frame({"D": [10, 11, 12, 13], "E": [10, 11, 12, 13]})
    out = generate("momentum_12_1", frame, lookback_days=3, skip_days=1, top_n=1)
    assert out["D"].tolist() == [0, 0, 0, 1]
    assert out["E"].tolist() == [0, 0, 0, 0]


def test_momentum_keeps_a_held_symbol_over_its_holiday() -> None:
    # B misses row 3. Its own rows are 0 1 2 4 5, scores (lookback 2, skip 0): 0.2, 0.2727, 0.0833, carried over row 3.
    # A is flat (score 0), so B leads from its first score on.
    frame = literal_frame({"A": [10] * 6, "B": [10, 11, 12, NAN, 14, 13]})
    out = generate("momentum_12_1", frame, lookback_days=2, skip_days=0, top_n=1)
    assert out["B"].tolist() == [0, 0, 1, 1, 1, 1]
    assert out["A"].tolist() == [0, 0, 0, 0, 0, 0]


def test_momentum_symbol_in_warmup_is_not_eligible() -> None:
    # C starts on row 2, so its own rows are 5 6 7 100 and its first score is on row 5: 7/5 - 1 = 0.4.
    # Until then only A competes (A scores 12/10 - 1 on row 3, 13/11 - 1 on row 4, 14/12 - 1 = 0.1667 on row 5).
    frame = literal_frame({"A": [10, 11, 12, 13, 14, 15], "C": [NAN, NAN, 5, 6, 7, 100]})
    out = generate("momentum_12_1", frame, lookback_days=3, skip_days=1, top_n=1)
    assert out["A"].tolist() == [0, 0, 0, 1, 1, 0]
    assert out["C"].tolist() == [0, 0, 0, 0, 0, 1]  # beats A on row 5


def test_momentum_params() -> None:
    params = Momentum121Params()
    assert (params.lookback_days, params.skip_days, params.top_n, params.positive_only) == (252, 21, 3, False)
    assert params.warmup_rows() == 252
    assert Momentum121Params(lookback_days=10, skip_days=2).warmup_rows() == 10
    with pytest.raises(ValidationError, match="skip_days must be smaller than lookback_days"):
        Momentum121Params(lookback_days=20, skip_days=20)
    for bad in ({"top_n": 0}, {"top_n": "3"}, {"skip_days": -1}, {"positive_only": 1}, {"lookback_days": 0}):
        with pytest.raises(ValidationError):
            Momentum121Params(**bad)


# --- buy_and_hold ---


def test_buy_and_hold_is_all_ones() -> None:
    out = generate("buy_and_hold", literal_frame({"A": [1, 2, 3], "B": [3, 2, 1]}))
    assert out.to_numpy().tolist() == [[1.0, 1.0]] * 3
    assert out.columns.tolist() == ["A", "B"]


def test_buy_and_hold_is_zero_before_the_first_price_and_carries_over_holidays() -> None:
    frame = literal_frame({"A": [1, 2, 3, 4, 5], "LATE": [NAN, NAN, 3, NAN, 5]})
    out = generate("buy_and_hold", frame)
    assert out["A"].tolist() == [1.0] * 5
    assert out["LATE"].tolist() == [0.0, 0.0, 1.0, 1.0, 1.0]


def test_buy_and_hold_has_no_params_and_no_warmup() -> None:
    assert BuyAndHoldParams().warmup_rows() == 0
    assert get_signal("buy_and_hold").warmup_rows() == 0
    with pytest.raises(ValidationError):
        BuyAndHoldParams(anything=1)
