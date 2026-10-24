"""``bt validate``: a spec is checked without data; every problem is listed (exit 3 otherwise)."""

from pathlib import Path

import yaml

from cli_helpers import run_cli, write_spec

REPO_ROOT = Path(__file__).resolve().parent.parent
SMA = str(REPO_ROOT / "strategies" / "sma_crossover.yaml")


def _data(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def test_validate_the_sma_example() -> None:
    result = run_cli(["validate", SMA])
    assert result.code == 0
    assert result.err == ""
    assert result.out.splitlines() == [
        f"OK: {SMA} is a valid spec",
        "Name:       SMA crossover on liquid ETFs",
        "Family:     sma_crossover",
        "Universe:   SPY, QQQ, TLT, GLD",
        "Benchmark:  SPY",
        "Period:     2010-01-01 to 2023-12-31",
        "Warm-up:    199 rows",
        "Risk flags: none",
    ]


def test_validate_shows_the_warmup_of_another_signal_and_the_spec_risk_flags(tmp_path: Path) -> None:
    data = _data(str(REPO_ROOT / "strategies" / "momentum_12_1.yaml"))
    data["costs"] = {"commission_bps": 0.0, "spread_bps": 0.0, "slippage_bps": 0.0}
    data["execution"] = {"delay_bars": 0, "price": "close", "allow_same_bar_execution": True}
    result = run_cli(["validate", str(write_spec(tmp_path, data))])
    assert result.code == 0
    assert "Warm-up:    252 rows" in result.out.splitlines()
    assert "Risk flags: same_bar_execution, zero_costs" in result.out.splitlines()


def test_validate_does_not_touch_the_file_system(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert run_cli(["validate", SMA]).code == 0
    assert list(tmp_path.iterdir()) == []


def test_validate_lists_every_problem_with_its_field_path(tmp_path: Path) -> None:
    data = _data(SMA)
    data["unknown_field"] = 1
    data["signal"]["params"]["fast"] = 300  # not smaller than slow
    result = run_cli(["validate", str(write_spec(tmp_path, data))])
    assert result.code == 3
    assert result.out == ""
    first, *rest = result.err.splitlines()
    assert first.startswith("bt: error: Invalid strategy spec in ")
    assert first.endswith("(2 problems):")
    assert any(line.startswith("  - unknown_field: unknown field 'unknown_field'") for line in rest)
    assert any(line.startswith("  - signal.params") for line in rest)
    assert rest[-1] == "hint: the fields of a spec are described in docs/strategy-spec.md"


def test_validate_a_yaml_syntax_error(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("name: [unclosed\n", encoding="utf-8")
    result = run_cli(["validate", str(path)])
    assert result.code == 3
    assert "YAML syntax error at line" in result.err


def test_validate_a_missing_file(tmp_path: Path) -> None:
    result = run_cli(["validate", str(tmp_path / "nope.yaml")])
    assert result.code == 3
    assert result.out == ""
    assert "cannot read" in result.err


def test_validate_an_unknown_signal_id(tmp_path: Path) -> None:
    data = _data(SMA)
    data["signal"] = {"id": "no_such_signal", "params": {}}
    result = run_cli(["validate", str(write_spec(tmp_path, data))])
    assert result.code == 3
    assert "no_such_signal" in result.err


def test_validate_needs_a_path() -> None:
    result = run_cli(["validate"])
    assert result.code == 2
    assert "the following arguments are required: SPEC" in result.err


def test_validate_help_names_the_command() -> None:
    result = run_cli(["validate", "--help"])
    assert result.code == 0
    assert result.out.startswith("usage: bt validate ")
    assert "--debug" in result.out
