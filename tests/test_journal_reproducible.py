"""Re-running the same spec on the same data hash reproduces identical metrics (Phase 8 "Done when")."""

import pytest

from backtest_agent.journal import get_run
from journal_helpers import (
    hold_spec,
    log,
    no_repo_runs,  # noqa: F401 - fixture used through pytestmark
    other_data_provider,
    sma_spec,
    standard_provider,
)

pytestmark = pytest.mark.usefixtures("no_repo_runs")


def parts(run_id: str) -> tuple[str, str, str]:
    stamp, rest = run_id.split("-", 1)
    slug, digest = rest.rsplit("-", 1)
    return stamp, slug, digest


@pytest.mark.parametrize("spec", [hold_spec(), sma_spec()], ids=["buy_and_hold", "sma_crossover"])
def test_the_same_spec_on_the_same_data_gives_identical_metrics(tmp_path, spec) -> None:
    first = log(tmp_path, spec, 1, standard_provider())
    second = log(tmp_path, spec, 61, standard_provider())  # a new provider, a later time
    one, two = get_run(tmp_path, first.run_id), get_run(tmp_path, second.run_id)
    assert one.evaluation == two.evaluation  # both data hashes, flags, both full metrics dicts, relative, assumptions
    assert one.evaluation["strategy"]["metrics"] == two.evaluation["strategy"]["metrics"]
    assert one.evaluation["benchmark"]["metrics"] == two.evaluation["benchmark"]["metrics"]
    assert one.evaluation["relative"] == two.evaluation["relative"]
    assert one.costs == two.costs
    assert one.trades == two.trades
    assert one.spec == two.spec


def test_the_hash_part_of_the_run_id_is_the_same_and_the_timestamp_part_differs(tmp_path) -> None:
    first = log(tmp_path, hold_spec(), 1)
    second = log(tmp_path, hold_spec(), 61)
    one, two = parts(first.run_id), parts(second.run_id)
    assert one[0] == "20260115T103001Z" and two[0] == "20260115T103101Z"
    assert one[1] == two[1] == "buy-and-hold-a"
    assert one[2] == two[2]
    assert first.run_id != second.run_id


def test_other_data_changes_the_hash_part_but_not_the_variant(tmp_path) -> None:
    first = log(tmp_path, sma_spec(), 1)
    second = log(tmp_path, sma_spec(), 2, other_data_provider())
    assert parts(first.run_id)[2] != parts(second.run_id)[2]
    assert first.evaluation["strategy"]["data_hash"] != second.evaluation["strategy"]["data_hash"]
    assert first.trial.variant_hash == second.trial.variant_hash
