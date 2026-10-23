"""Run ids: slug rules, the hash input of docs/adr/0014-report.md, and the time rules."""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from backtest_agent.metrics import MetricAssumptions
from backtest_agent.run_id import SLUG_LIMIT, inputs_digest, make_run_id, run_id_hash_input, slugify
from report_helpers import equal_start, make_evaluation, spec_for

NOON = datetime(2026, 1, 15, 10, 30, 5, tzinfo=UTC)


@pytest.mark.parametrize(
    "name, slug",
    [
        ("Buy and hold SPY, TLT and GLD", "buy-and-hold-spy-tlt-and-gld"),
        ("12-1 momentum on liquid ETFs", "12-1-momentum-on-liquid-etfs"),
        ("Café Zürich Größe", "cafe-zurich-groe"),  # NFKD: accents fold, the sharp s has no ASCII fold and drops
        ("<script>alert(1)</script>", "script-alert-1-script"),
        (r'a/b\c:d*e?f"g<h>i|j', "a-b-c-d-e-f-g-h-i-j"),
        ("CON", "con"),
        ("  trailing dot. and space ", "trailing-dot-and-space"),
        ("日本語", "run"),  # nothing ASCII is left
        ("!!!", "run"),
        ("", "run"),
    ],
)
def test_slugify_cases(name: str, slug: str) -> None:
    assert slugify(name) == slug


def test_a_long_name_is_cut_at_the_limit_without_a_trailing_dash() -> None:
    assert slugify("x" * 300) == "x" * SLUG_LIMIT
    cut = slugify("a" * 39 + " b")  # the cut falls right behind a dash: no trailing dash
    assert cut == "a" * 39 and not cut.endswith("-")


def test_the_run_id_has_the_documented_shape() -> None:
    run_id = make_run_id(equal_start(), NOON)
    assert re.fullmatch(r"\d{8}T\d{6}Z-[a-z0-9-]+-[0-9a-f]{8}", run_id)
    assert run_id.startswith("20260115T103005Z-buy-and-hold-a-")


def test_golden_run_id() -> None:
    # A pin of the current algorithm (not a hand calculation): a change of the hash input must be deliberate.
    assert make_run_id(equal_start(), NOON) == "20260115T103005Z-buy-and-hold-a-a85a59ee"


def test_the_digest_can_be_reproduced_from_the_documented_text() -> None:
    ev = equal_start()
    text = run_id_hash_input(ev)
    payload = json.loads(text)
    assert sorted(payload) == ["assumptions", "benchmark_data_hash", "costs_applied", "spec", "strategy_data_hash"]
    assert payload["assumptions"] == {"periods_per_year": 5, "risk_free_rate": 0.0}
    assert payload["costs_applied"] is True
    assert payload["strategy_data_hash"] == ev.result.data_hash
    assert payload["benchmark_data_hash"] == ev.benchmark_result.data_hash
    assert payload["spec"] == ev.result.spec.to_dict()
    assert '", "' not in text and '": ' not in text  # compact separators
    assert inputs_digest(ev) == hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def test_same_inputs_same_id_and_the_time_changes_only_the_prefix() -> None:
    first, second = make_run_id(equal_start(), NOON), make_run_id(equal_start(), NOON + timedelta(hours=3))
    assert make_run_id(equal_start(), NOON) == first
    assert first != second and first.split("-")[-1] == second.split("-")[-1]


def test_the_time_is_written_in_utc() -> None:
    berlin = timezone(timedelta(hours=2))
    assert make_run_id(equal_start(), datetime(2026, 1, 15, 12, 30, 5, tzinfo=berlin)).startswith("20260115T103005Z-")


def test_a_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        make_run_id(equal_start(), datetime(2026, 1, 15, 10, 30, 5))


def test_the_digest_changes_with_each_input() -> None:
    base = inputs_digest(equal_start())
    assert inputs_digest(make_evaluation(spec=spec_for("B", costs=(1.0, 2.0, 2.0)))) != base  # the spec
    assert inputs_digest(make_evaluation(apply_costs=False)) != base  # costs_applied
    assert inputs_digest(make_evaluation(assumptions=MetricAssumptions(5, 0.01))) != base  # the assumptions
    assert inputs_digest(make_evaluation(assumptions=MetricAssumptions(252))) != base


def test_the_digest_changes_with_the_data_hashes() -> None:
    ev = equal_start()
    from dataclasses import replace

    other_strategy = replace(ev, result=replace(ev.result, data_hash="0" * 64))
    other_benchmark = replace(ev, benchmark_result=replace(ev.benchmark_result, data_hash="1" * 64))
    assert inputs_digest(other_strategy) != inputs_digest(ev)
    assert inputs_digest(other_benchmark) != inputs_digest(ev)
    assert inputs_digest(other_strategy) != inputs_digest(other_benchmark)


def test_a_hostile_name_gives_a_safe_id() -> None:
    ev = make_evaluation(spec=spec_for("B", name=r"<script>alert(1)</script> ../..\CON"))
    run_id = make_run_id(ev, NOON)
    assert re.fullmatch(r"[0-9TZ]+-[a-z0-9-]+-[0-9a-f]{8}", run_id)
    assert "/" not in run_id and "\\" not in run_id and ".." not in run_id


def test_the_worked_example_of_adr_0014_is_what_the_code_hashes() -> None:
    adr = Path(__file__).resolve().parents[1] / "docs" / "adr" / "0014-report.md"
    lines = adr.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "```json") + 1
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == "```")
    text = "".join(line.strip() for line in lines[start:end])
    assert text == run_id_hash_input(equal_start())
    assert hashlib.sha256(text.encode("utf-8")).hexdigest()[:8] == "a85a59ee"
