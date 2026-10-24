"""docs/data.md: symbols are sorted as strings by code point, whatever the order of the columns.

The literal is the SHA-256 of the frame computed with a plain ``hashlib`` script from the layout of docs/data.md (no
project code): symbols "a" (the prices of A) and "B" (the prices of B) of the example frame of docs/cli.md, five rows,
sorted "B" (code point 66) before "a" (97); a case-insensitive sort would put "a" first and give another digest.
"""

from backtest_agent.data.hash import hash_frame
from report_helpers import A_CLOSE, A_OPEN, B_CLOSE, B_OPEN
from runner_helpers import price_frame

HASH_B_THEN_A = "a6f535d2bfb16f177e4877645dd4a672b7c0d81c979d82fe664ed80bab270580"


def test_a_capital_symbol_sorts_before_a_small_one_whatever_the_column_order() -> None:
    small_first = price_frame({"a": A_OPEN, "B": B_OPEN}, {"a": A_CLOSE, "B": B_CLOSE})
    capital_first = price_frame({"B": B_OPEN, "a": A_OPEN}, {"B": B_CLOSE, "a": A_CLOSE})
    assert list(small_first.columns.get_level_values("symbol").unique()) == ["a", "B"]
    assert hash_frame(small_first) == HASH_B_THEN_A
    assert hash_frame(capital_first) == HASH_B_THEN_A
