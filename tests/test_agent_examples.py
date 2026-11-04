"""The three example specs in ``strategies/examples/`` (Phase 10 part 4b).

They are read by the agents as examples of the shape of a spec. The first uses a built-in signal; the other two carry a
``coded`` block (id and brief) and have **no code**: nothing unapproved is committed. Expected values are literals.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from backtest_agent.spec import SpecError, get_signal, load_spec, parse_spec
from backtest_agent.spec.coded_spec import check_brief, coded_id_problem
from cli_helpers import run_cli
from frames import literal_frame

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "strategies" / "examples"
NAMES = ["trend_filter_etfs", "rsi_pullback", "vol_filtered_trend"]
CODED = ["rsi_pullback", "vol_filtered_trend"]
TREND = EXAMPLES / "trend_filter_etfs.yaml"
SIGNAL_IDS = {
    "trend_filter_etfs": "sma_crossover",
    "rsi_pullback": "rsi_pullback",
    "vol_filtered_trend": "vol_filtered_trend",
}


def tracked(*prefixes: str) -> list[str]:
    """The files that git tracks under the given paths (the same call as the guard in test_no_invisible_characters).

    The files of a coded example may exist on the disk of the maintainer once the example has been used for real; what
    must never happen is that they are committed. Skips only where git itself is not available.
    """
    if shutil.which("git") is None:
        pytest.skip("git is not available")
    try:
        done = subprocess.run(
            ["git", "-c", "core.quotepath=off", "ls-files", "-z", "--", *prefixes],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    except OSError:
        pytest.skip("git cannot be run")
    if done.returncode != 0:  # not a repository (a source archive, for example)
        pytest.skip("not a git repository")
    return [name for name in done.stdout.split(chr(0)) if name]


def text(name: str) -> str:
    return (EXAMPLES / f"{name}.yaml").read_text(encoding="utf-8")


def test_the_examples_folder_holds_exactly_the_three_specs() -> None:
    assert sorted(path.name for path in EXAMPLES.iterdir()) == sorted(f"{name}.yaml" for name in NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_an_example_loads_has_no_risk_flag_and_waits_one_bar(name: str) -> None:
    spec = load_spec(EXAMPLES / f"{name}.yaml")
    assert spec.risk_flags() == () and spec.execution.delay_bars >= 1
    assert spec.signal.id == SIGNAL_IDS[name]
    assert spec.benchmark in spec.universe and spec.period.start.isoformat() == "2012-01-01"


@pytest.mark.parametrize("name", NAMES)
def test_the_header_says_example_not_a_recommendation_not_investment_advice(name: str) -> None:
    header = "\n".join(line for line in text(name).splitlines() if line.startswith("#"))
    flat = " ".join(header.split())
    assert "example" in flat.lower() and "not a recommendation" in flat and "not investment advice" in flat


# --- trend_filter_etfs ---


def test_trend_filter_etfs_is_an_sma_crossover_of_one_against_one_hundred_on_four_etfs() -> None:
    spec = load_spec(TREND)
    assert spec.signal.id == "sma_crossover" and spec.signal.params == {"fast": 1, "slow": 100}
    assert list(spec.universe) == ["SPY", "EFA", "TLT", "GLD"] and spec.benchmark == "SPY"
    assert spec.warmup_rows == 99  # slow - 1 rows of history


def test_bt_validate_exits_0_and_prints_all_four_tickers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    result = run_cli(["validate", "strategies/examples/trend_filter_etfs.yaml"])
    assert (result.code, result.err) == (0, "")
    assert result.out.splitlines() == [
        "OK: strategies/examples/trend_filter_etfs.yaml is a valid spec",
        "Name:       Trend filter on four ETFs",
        "Family:     sma_crossover",
        "Universe:   SPY, EFA, TLT, GLD",
        "Benchmark:  SPY",
        "Period:     2012-01-01 to 2023-12-31",
        "Warm-up:    99 rows",
        "Risk flags: none",
    ]


def test_the_schema_accepts_fast_1_and_refuses_fast_0() -> None:
    assert parse_spec(text("trend_filter_etfs")).signal.params["fast"] == 1
    with pytest.raises(SpecError):
        parse_spec(text("trend_filter_etfs").replace("fast: 1\n", "fast: 0\n"))


def test_fast_1_means_the_close_against_its_average_on_a_literal_series() -> None:
    # closes 10 12 11 13, fast 1 (the close itself), slow 2; SMA(2) on the rows that have 2 closes:
    #   row     0    1     2      3
    #   close   10   12    11     13
    #   SMA(2)  -    11    11.5   12
    #   above?       12>11 11>11.5 13>12
    #   signal  0    1     0      1       (row 0 is warm-up)
    out = get_signal("sma_crossover").generate(literal_frame({"AAA": [10, 12, 11, 13]}), {"fast": 1, "slow": 2})
    assert out["AAA"].tolist() == [0.0, 1.0, 0.0, 1.0]


# --- the two coded examples ---


@pytest.mark.parametrize("name", CODED)
def test_a_coded_example_has_an_id_a_valid_brief_and_no_code(name: str) -> None:
    spec = load_spec(EXAMPLES / f"{name}.yaml")
    assert spec.signal.coded is not None and spec.signal.id == name
    assert coded_id_problem(spec.signal.id) is None
    assert check_brief(spec.signal.coded.brief) == spec.signal.coded.brief.replace("\r\n", "\n")
    assert spec.signal.coded.code_sha256 is None  # no pin: nothing is approved
    # no code and no approval is committed (a file on the disk of the maintainer is not an error)
    assert (
        tracked(f"strategies/signals/{name}.py", f"strategies/signals/{name}.cases.yaml", f"approvals/{name}.json")
        == []
    )


@pytest.mark.parametrize("name", CODED)
def test_bt_validate_says_coded_idea_not_approved(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    result = run_cli(["validate", f"strategies/examples/{name}.yaml"])
    lines = result.out.splitlines()
    assert (result.code, result.err) == (0, "")
    assert "Signal:     coded, idea not approved" in lines
    assert "Warm-up:    n/a (coded signal, not loaded)" in lines
    assert lines[-1] == "Risk flags: none"


def test_the_briefs_name_every_parameter_and_the_history_needed() -> None:
    for name, parameters in (
        ("rsi_pullback", ("window", "entry_below")),
        ("vol_filtered_trend", ("trend_window", "vol_window", "max_daily_vol")),
    ):
        brief = " ".join(load_spec(EXAMPLES / f"{name}.yaml").signal.coded.brief.split())
        assert all(re.search(rf"\b{p}\b", brief) for p in parameters), name
        assert "Needs" in brief and "rows of history" in brief
        assert len(brief) <= 2000


def test_the_rsi_brief_says_which_rsi() -> None:
    brief = " ".join(load_spec(EXAMPLES / "rsi_pullback.yaml").signal.coded.brief.split())
    assert "The RSI is the simple one: 100 minus 100 / (1 + RS)" in brief
    assert (
        "RS is the simple mean of the gains divided by the simple mean of the losses over the last window rows" in brief
    )


def test_a_brief_of_2001_characters_is_refused() -> None:
    brief = "x" * 2001
    with pytest.raises(ValueError):
        check_brief(brief)
