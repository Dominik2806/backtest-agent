"""Family and variant hash (docs/journal.md, "Strategy family" and "Variant hash")."""

import hashlib
from pathlib import Path

import pytest

from backtest_agent.journal import canonical_json, family_of, variant_hash
from journal_helpers import no_repo_runs  # noqa: F401 - fixture used through pytestmark
from report_helpers import spec_for
from runner_helpers import make_spec

pytestmark = pytest.mark.usefixtures("no_repo_runs")

# Copied from the worked example in docs/journal.md (the strategy of R3b without name and description).
DOC_PAYLOAD = (
    '{"benchmark":"B","costs":{"commission_bps":1000.0,"min_commission":0.0,"slippage_bps":500.0,'
    '"spread_bps":1000.0},"data":{"provider":"yfinance"},"execution":{"allow_same_bar_execution":false,'
    '"delay_bars":1,"price":"open"},"initial_capital":1000.0,"period":{"end":"2024-01-08","start":"2024-01-02"},'
    '"rebalance":"on_signal","schema_version":1,"signal":{"id":"buy_and_hold","params":{}},'
    '"sizing":{"fraction":null,"method":"equal_weight"},"universe":["A"]}'
)
DOC_DIGEST = "a7b3d3b5b0e2a72814fcb465bc7d203f96ae332c45eff8880ac85e5a9a492cad"
DOCS = Path(__file__).resolve().parent.parent / "docs" / "journal.md"


def test_the_literals_of_this_test_are_the_ones_in_the_document() -> None:
    text = DOCS.read_text(encoding="utf-8")
    assert DOC_PAYLOAD in text
    assert DOC_DIGEST in text


def test_the_worked_example_hashes_to_the_documented_digest() -> None:
    assert hashlib.sha256(DOC_PAYLOAD.encode("utf-8")).hexdigest() == DOC_DIGEST


def test_the_variant_hash_of_the_worked_example_strategy_is_the_documented_digest() -> None:
    assert variant_hash(spec_for()) == DOC_DIGEST


def test_name_and_description_are_not_part_of_a_variant() -> None:
    base = spec_for()
    renamed = spec_for(name="A completely different name").model_copy(update={"description": "Other text"})
    assert variant_hash(renamed) == variant_hash(base) == DOC_DIGEST


def make(**changes):
    options = {
        "universe": ("A",),
        "benchmark": "B",
        "start": "2024-01-02",
        "end": "2024-01-08",
        "signal": "sma_crossover",
        "params": {"fast": 2, "slow": 3},
        "costs": (1000.0, 1000.0, 500.0),
        "capital": 1000,
    }
    options.update(changes)
    return make_spec(**options)


@pytest.mark.parametrize(
    "changes",
    [
        {"universe": ("A", "C")},
        {"universe": ("C",)},
        {"benchmark": "C"},
        {"start": "2024-01-03"},
        {"end": "2024-01-05"},
        {"params": {"fast": 2, "slow": 4}},
        {"params": {"fast": 1, "slow": 3}},
        {"delay": 2},
        {"price": "close"},
        {"rebalance": "weekly"},
        {"method": "fixed_fraction", "fraction": 0.5},
        {"costs": (1.0, 1000.0, 500.0)},
        {"costs": (1000.0, 1.0, 500.0)},
        {"costs": (1000.0, 1000.0, 1.0)},
        {"capital": 2000},
    ],
    ids=lambda changes: ",".join(changes),
)
def test_every_other_field_of_the_spec_makes_a_new_variant(changes) -> None:
    assert variant_hash(make(**changes)) != variant_hash(make())


def test_the_order_of_the_universe_counts() -> None:
    assert variant_hash(make(universe=("A", "C"))) != variant_hash(make(universe=("C", "A")))


def test_default_params_and_explicit_defaults_are_the_same_variant() -> None:
    explicit = make(params={"fast": 50, "slow": 200})
    implicit = make(params={})  # make_spec passes {} through; the spec fills in the defaults
    assert variant_hash(explicit) == variant_hash(implicit)


def test_the_variant_hash_is_64_lowercase_hex_characters() -> None:
    digest = variant_hash(make())
    assert len(digest) == 64
    assert digest == digest.lower()
    assert int(digest, 16) >= 0


def test_the_family_is_the_signal_id() -> None:
    assert family_of(make()) == "sma_crossover"
    assert family_of(make(signal="buy_and_hold", params={})) == "buy_and_hold"
    assert family_of(make(universe=("A", "C"), start="2024-01-04", costs=(1.0, 1.0, 1.0))) == "sma_crossover"
    assert family_of(spec_for(name="sma_crossover")) == "buy_and_hold"  # the name is not the family


def test_canonical_json_is_sorted_compact_ascii_and_refuses_nan() -> None:
    accent = chr(0xE9)
    expected = '{"a":"' + chr(92) + 'u00e9","b":[1,2.5,null]}'
    assert canonical_json({"b": [1, 2.5, None], "a": accent}) == expected
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            canonical_json({"x": bad})
