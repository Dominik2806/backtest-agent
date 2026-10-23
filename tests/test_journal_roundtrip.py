"""What is written can be read back equal; the file format of docs/journal.md ("run.json", "spec.yaml")."""

import json
import math
from datetime import UTC, datetime, timedelta, timezone

import pytest

from backtest_agent.journal import canonical_json, get_run, record_run, variant_hash
from backtest_agent.spec import parse_spec
from journal_helpers import (
    CODE,
    evaluation_of,
    hold_spec,
    log,
    no_repo_runs,  # noqa: F401 - fixture used through pytestmark
    sma_spec,
)

pytestmark = pytest.mark.usefixtures("no_repo_runs")

# The R3b world of docs/engine.md with 25 percent costs, as in tests/snapshots/report.md: strategy A (buy and hold)
# and benchmark B (buy and hold), both with total costs of 200. The strategy: net 1171.28, gross 1464.10 on 1000.
SCALARS = [
    ("total_costs", 200.0, 200.0),
    ("gross_final_equity", 1464.1, 980.1),
    ("net_return", 0.17128, -0.21592),
    ("gross_return", 0.4641, -0.0199),
    ("cost_drag", 0.29282, 0.19602),
    ("cost_share", 0.29282 / 0.4641, None),
]


def test_what_is_written_is_read_back_equal(tmp_path) -> None:
    record = log(tmp_path, hold_spec(), 1)
    assert get_run(tmp_path, record.run_id) == record


def test_the_file_is_canonical_json_with_one_final_newline(tmp_path) -> None:
    record = log(tmp_path, hold_spec(), 1)
    raw = (tmp_path / record.run_id / "run.json").read_bytes()
    text = raw.decode("utf-8")
    assert text.endswith("}\n") and not text.endswith("\n\n")
    assert b"\r" not in raw
    assert text == canonical_json(json.loads(text)) + "\n"  # sorted keys, compact separators, nothing else
    assert raw.isascii()
    assert set(json.loads(text)) == {
        "schema_version",
        "run_id",
        "generated_at",
        "code_version",
        "family",
        "trial",
        "spec",
        "evaluation",
        "trades",
        "costs",
    }


def test_the_header_of_the_file(tmp_path) -> None:
    record = log(tmp_path, hold_spec(), 5)
    data = json.loads((tmp_path / record.run_id / "run.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["run_id"] == record.run_id
    assert record.run_id.startswith("20260115T103005Z-buy-and-hold-a-")
    assert data["generated_at"] == "2026-01-15T10:30:05Z"
    assert data["code_version"] == {"commit": "0123456789abcdef0123456789abcdef01234567", "dirty": False}
    assert data["family"] == "buy_and_hold"
    assert data["trial"] == {
        "variant_hash": variant_hash(hold_spec()),
        "run_number": 1,
        "trial_number": 1,
        "trial_count": 1,
        "new_variant": True,
    }
    assert data["spec"]["name"] == "Buy and hold A"
    assert len(data["evaluation"]["strategy"]["data_hash"]) == 64
    assert len(data["evaluation"]["benchmark"]["data_hash"]) == 64


def test_microseconds_and_other_time_zones_are_cut_and_converted_like_the_run_id(tmp_path) -> None:
    when = datetime(2026, 1, 15, 12, 30, 5, 999999, tzinfo=timezone(timedelta(hours=2)))  # 10:30:05 UTC
    record = record_run(evaluation_of(hold_spec()), tmp_path, generated_at=when, code_version=CODE)
    assert record.run_id.startswith("20260115T103005Z-")
    assert record.generated_at == datetime(2026, 1, 15, 10, 30, 5, tzinfo=UTC)  # whole seconds, in UTC
    assert get_run(tmp_path, record.run_id) == record
    stored = json.loads((tmp_path / record.run_id / "run.json").read_text(encoding="utf-8"))
    assert stored["generated_at"] == "2026-01-15T10:30:05Z"


@pytest.mark.parametrize("key, strategy, benchmark", SCALARS, ids=[s[0] for s in SCALARS])
def test_each_result_scalar_is_stored_explicitly(tmp_path, key, strategy, benchmark) -> None:
    record = log(tmp_path, hold_spec(), 1)
    stored = get_run(tmp_path, record.run_id).costs
    for who, expected in (("strategy", strategy), ("benchmark", benchmark)):
        if expected is None:
            assert stored[who][key] is None
        else:
            assert stored[who][key] == pytest.approx(expected, abs=1e-9, rel=1e-9)


def test_cost_share_none_is_null_in_the_file_and_none_after_reading(tmp_path) -> None:
    record = log(tmp_path, hold_spec(), 1)
    text = (tmp_path / record.run_id / "run.json").read_text(encoding="utf-8")
    benchmark = json.loads(text)["costs"]["benchmark"]
    assert "cost_share" in benchmark and benchmark["cost_share"] is None
    assert get_run(tmp_path, record.run_id).costs["benchmark"]["cost_share"] is None
    assert not math.isnan(get_run(tmp_path, record.run_id).costs["strategy"]["cost_share"])


def test_costs_applied_is_stored_for_both_runs(tmp_path) -> None:
    on = log(tmp_path, hold_spec(), 1)
    off = log(tmp_path, hold_spec(), 2, apply_costs=False)
    assert (on.costs["strategy"]["costs_applied"], on.costs["benchmark"]["costs_applied"]) == (True, True)
    assert (off.costs["strategy"]["costs_applied"], off.costs["benchmark"]["costs_applied"]) == (False, False)


def test_a_cost_free_run_has_zero_costs_and_zero_drag(tmp_path) -> None:
    record = log(tmp_path, hold_spec(), 1, apply_costs=False)
    strategy = record.costs["strategy"]
    assert strategy["total_costs"] == 0.0
    assert strategy["cost_drag"] == 0.0
    assert strategy["cost_share"] == 0.0  # positive gross return: docs/engine.md, zero costs
    assert record.costs["benchmark"]["cost_share"] is None  # the benchmark B loses money


def test_the_trade_statistics_of_the_strategy_are_stored(tmp_path) -> None:
    record = log(tmp_path, hold_spec(), 1)
    assert record.trades["n_trades"] == 1  # one buy of A on the first bar
    assert (record.trades["n_buys"], record.trades["n_sells"]) == (1, 0)
    assert record.trades["total_cost"] == pytest.approx(200.0, abs=1e-9)
    assert record.trades["per_symbol"] == {"A": {"trades": 1, "buys": 1, "sells": 0}}


def test_the_file_holds_no_local_path_or_environment(tmp_path) -> None:
    runs = tmp_path / "some-private-folder"
    record = log(runs, hold_spec(), 1)
    text = (runs / record.run_id / "run.json").read_text(encoding="utf-8")
    assert "some-private-folder" not in text
    assert str(tmp_path) not in text
    assert "Users" not in text


def test_spec_yaml_loads_through_the_normal_loader_to_the_same_variant(tmp_path) -> None:
    for second, spec in enumerate((hold_spec(), sma_spec(), sma_spec(slow=4, start="2024-01-03")), start=1):
        record = log(tmp_path, spec, second)
        loaded = parse_spec((tmp_path / record.run_id / "spec.yaml").read_text(encoding="utf-8"))
        assert variant_hash(loaded) == variant_hash(spec) == record.trial.variant_hash
        assert loaded.to_dict() == spec.to_dict() == record.spec


def test_spec_yaml_is_a_readable_block_file_with_unix_line_ends(tmp_path) -> None:
    record = log(tmp_path, hold_spec(), 1)
    raw = (tmp_path / record.run_id / "spec.yaml").read_bytes()
    assert b"\r" not in raw
    assert raw.decode("utf-8").splitlines()[0] == "benchmark: B"
    assert b"universe:\n- A" in raw


def test_the_folder_holds_exactly_the_two_files(tmp_path) -> None:
    record = log(tmp_path, hold_spec(), 1)
    assert sorted(p.name for p in (tmp_path / record.run_id).iterdir()) == ["run.json", "spec.yaml"]
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(["index.sqlite", record.run_id])
