"""``bt data fetch`` and ``bt validate --data``: the two requests of a run, the output and the exit codes.

The expected lines are the literals of docs/cli.md ("Example: the data commands", the world of fixture R3b); the hashes
were computed with hashlib from the layout of docs/data.md, not with project code. A consistency test compares them with
what a run stores, so the commands cannot drift from the runner.
"""

import io
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest_agent.cli import main
from backtest_agent.cli.render import issue_line
from backtest_agent.data import DataUnavailableError
from backtest_agent.data.validation import Severity, ValidationIssue
from backtest_agent.engine import run_backtest
from cli_helpers import at, run_cli, write_spec
from report_helpers import spec_for, world
from runner_helpers import LiteralProvider, nan_rows

HASH_A = "61669f6e7476623e1289ff7dad8c8b767f36be44961c05ec4def3f45c15dd090"
HASH_B = "ff487f9000d166df03fa5e84640c7524f7414b58173ed654e33fab7f1df0b094"
HASH_A_BROKEN = "2717f62b8122d8a9189132458fc9ede5f1ae8ff2ee6e2927c7a51d2e7f6b7e49"
END = date(2024, 1, 8)


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def spec_path(workdir: Path) -> Path:
    return write_spec(workdir, spec_for(), "strategy.yaml")


def broken_world() -> pd.DataFrame:
    """A's close of 2024-01-04 and A's volume of 2024-01-05 are missing."""
    frame = world()
    frame.loc[pd.Timestamp("2024-01-04"), ("A", "close")] = np.nan
    frame.loc[pd.Timestamp("2024-01-05"), ("A", "volume")] = np.nan
    return frame


FETCH_R3B = [
    "Spec:       Buy and hold A",
    "Strategy:   2023-12-17 to 2024-01-08 (16 days before the period start)",
    "  A         5 rows",
    "  Checks:   0 errors, 0 warnings, 1 info",
    f"  Data:     {HASH_A}",
    "Benchmark:  2023-12-17 to 2024-01-08 (16 days before the period start)",
    "  B         5 rows",
    "  Checks:   0 errors, 0 warnings, 1 info",
    f"  Data:     {HASH_B}",
]
BLOCKS_BROKEN = [
    "Strategy:   2023-12-17 to 2024-01-08 (16 days before the period start)",
    "  A         5 rows",
    "  Checks:   1 error, 1 warning, 1 info",
    f"  Data:     {HASH_A_BROKEN}",
    "  error   nan_in_history           A.close     count 1, first 2024-01-04",
    "  warning nan_volume               A.volume    count 1, first 2024-01-05",
    "  info    starts_late              A           count 11, first 2024-01-02",
    "Benchmark:  2023-12-17 to 2024-01-08 (16 days before the period start)",
    "  B         5 rows",
    "  Checks:   0 errors, 0 warnings, 1 info",
    f"  Data:     {HASH_B}",
    "  info    starts_late              B           count 11, first 2024-01-02",
]
VALIDATE_HEAD = [
    "OK: strategy.yaml is a valid spec",
    "Name:       Buy and hold A",
    "Family:     buy_and_hold",
    "Universe:   A",
    "Benchmark:  B",
    "Period:     2024-01-02 to 2024-01-08",
    "Warm-up:    0 rows",
    "Risk flags: none",
    "",
]


def test_data_fetch_prints_the_two_blocks_of_the_example(spec_path: Path) -> None:
    result = run_cli(["data", "fetch", "strategy.yaml"], provider=LiteralProvider(world()))
    assert result.code == 0
    assert result.err == ""
    assert result.out.splitlines() == FETCH_R3B


def test_data_fetch_makes_exactly_the_two_requests_of_a_run(spec_path: Path) -> None:
    provider = LiteralProvider(world())
    run_cli(["data", "fetch", "strategy.yaml"], provider=provider)
    assert provider.calls == [(("A",), date(2023, 12, 17), END), (("B",), date(2023, 12, 17), END)]


def test_the_two_windows_differ_for_a_signal_with_a_warm_up(workdir: Path) -> None:
    # sma 2/4: warm-up 3, N = 3 + 1 = 4, 2 * 4 + 14 = 22 days before 2024-01-02 is 2023-12-11; the benchmark: 16 days
    spec = spec_for("B", signal="sma_crossover", params={"fast": 2, "slow": 4}, name="SMA 2/4 on A")
    path = write_spec(workdir, spec, "strategy.yaml")
    provider = LiteralProvider(world())
    result = run_cli(["data", "fetch", str(path)], provider=provider)
    assert provider.calls == [(("A",), date(2023, 12, 11), END), (("B",), date(2023, 12, 17), END)]
    assert result.out.splitlines() == [
        "Spec:       SMA 2/4 on A",
        "Strategy:   2023-12-11 to 2024-01-08 (22 days before the period start)",
        "  A         5 rows",
        "  Checks:   0 errors, 0 warnings, 1 info",
        f"  Data:     {HASH_A}",
        "Benchmark:  2023-12-17 to 2024-01-08 (16 days before the period start)",
        "  B         5 rows",
        "  Checks:   0 errors, 0 warnings, 1 info",
        f"  Data:     {HASH_B}",
    ]


def test_validate_data_for_the_sma_spec_counts_16_missing_business_days(workdir: Path) -> None:
    spec = spec_for("B", signal="sma_crossover", params={"fast": 2, "slow": 4}, name="SMA 2/4 on A")
    path = write_spec(workdir, spec, "strategy.yaml")
    out = run_cli(["validate", str(path), "--data"], provider=LiteralProvider(world())).out.splitlines()
    assert "  info    starts_late              A           count 16, first 2024-01-02" in out
    assert "  info    starts_late              B           count 11, first 2024-01-02" in out


def test_the_symbols_of_the_universe_are_listed_in_spec_order(workdir: Path) -> None:
    path = write_spec(workdir, spec_for(universe=("B", "A")), "strategy.yaml")
    out = run_cli(["data", "fetch", str(path)], provider=LiteralProvider(world())).out.splitlines()
    assert out[2:4] == ["  B         5 rows", "  A         5 rows"]
    assert re.fullmatch(r"  Data:     [0-9a-f]{64}", out[5])


def test_rows_are_the_rows_with_data_not_the_rows_of_the_frame(spec_path: Path) -> None:
    # A does not trade on 2024-01-03 (all fields NaN): the row is in the frame but not a row with data of A
    frame = nan_rows(world(), "A", between=("2024-01-03", "2024-01-03"))
    out = run_cli(["data", "fetch", "strategy.yaml"], provider=LiteralProvider(frame)).out.splitlines()
    assert out[2] == "  A         4 rows"
    assert out[6] == "  B         5 rows"


def test_a_run_stores_the_hashes_that_data_fetch_prints(spec_path: Path) -> None:
    # cross-check beside the literals: the same provider, the runner and the commands see the same data
    provider = LiteralProvider(world())
    result = run_backtest(spec_for(), provider)
    assert result.data_hash == HASH_A
    assert result.validation.to_dict()["counts"] == {"error": 0, "warning": 0, "info": 1}
    shown = run_cli(["data", "fetch", "strategy.yaml"], provider=LiteralProvider(world())).out
    assert f"Data:     {result.data_hash}" in shown


def test_data_fetch_writes_nothing_into_the_working_directory(spec_path: Path, workdir: Path) -> None:
    run_cli(["data", "fetch", "strategy.yaml"], provider=LiteralProvider(world()))
    assert sorted(path.name for path in workdir.iterdir()) == ["strategy.yaml"]


def test_the_cache_dir_goes_to_the_provider_factory(spec_path: Path) -> None:
    seen: list[Path] = []

    def factory(cache_dir: Path) -> LiteralProvider:
        seen.append(cache_dir)
        return LiteralProvider(world())

    for command in (["data", "fetch", "strategy.yaml"], ["validate", "strategy.yaml", "--data"]):
        seen.clear()
        assert (
            main(
                [*command, "--cache-dir", "elsewhere"],
                provider_factory=factory,
                clock=at(0),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
            == 0
        )
        assert seen == [Path("elsewhere")]


def test_validate_data_without_errors_prints_the_head_the_blocks_and_every_info(spec_path: Path) -> None:
    result = run_cli(["validate", "strategy.yaml", "--data"], provider=LiteralProvider(world()))
    assert result.code == 0
    assert result.err == ""
    assert result.out.splitlines() == [
        *VALIDATE_HEAD,
        "Strategy:   2023-12-17 to 2024-01-08 (16 days before the period start)",
        "  A         5 rows",
        "  Checks:   0 errors, 0 warnings, 1 info",
        f"  Data:     {HASH_A}",
        "  info    starts_late              A           count 11, first 2024-01-02",
        "Benchmark:  2023-12-17 to 2024-01-08 (16 days before the period start)",
        "  B         5 rows",
        "  Checks:   0 errors, 0 warnings, 1 info",
        f"  Data:     {HASH_B}",
        "  info    starts_late              B           count 11, first 2024-01-02",
    ]


def test_validate_data_with_errors_prints_everything_then_one_line_and_exits_4(spec_path: Path) -> None:
    result = run_cli(["validate", "strategy.yaml", "--data"], provider=LiteralProvider(broken_world()))
    assert result.code == 4
    assert result.out.splitlines() == [*VALIDATE_HEAD, *BLOCKS_BROKEN]
    assert result.err == "bt: error: the data has 1 validation error (listed above)\n"


def test_two_errors_are_counted_in_the_plural(spec_path: Path) -> None:
    frame = broken_world()
    frame.loc[pd.Timestamp("2024-01-03"), ("B", "close")] = np.nan
    result = run_cli(["validate", "strategy.yaml", "--data"], provider=LiteralProvider(frame))
    assert result.code == 4
    assert result.err == "bt: error: the data has 2 validation errors (listed above)\n"


def test_data_fetch_with_errors_warns_and_exits_0(spec_path: Path) -> None:
    result = run_cli(["data", "fetch", "strategy.yaml"], provider=LiteralProvider(broken_world()))
    assert result.code == 0
    assert result.out.splitlines() == [
        "Spec:       Buy and hold A",
        "Strategy:   2023-12-17 to 2024-01-08 (16 days before the period start)",
        "  A         5 rows",
        "  Checks:   1 error, 1 warning, 1 info",
        f"  Data:     {HASH_A_BROKEN}",
        "Benchmark:  2023-12-17 to 2024-01-08 (16 days before the period start)",
        "  B         5 rows",
        "  Checks:   0 errors, 0 warnings, 1 info",
        f"  Data:     {HASH_B}",
    ]
    assert result.err == (
        "warning: 1 validation error(s); a run would fail; bt validate strategy.yaml --data lists them\n"
    )


class FailingProvider(LiteralProvider):
    def get_prices(self, symbols, start, end):
        raise DataUnavailableError("no data for A")


@pytest.mark.parametrize("command", [["data", "fetch", "strategy.yaml"], ["validate", "strategy.yaml", "--data"]])
def test_a_provider_failure_is_exit_4_with_nothing_on_stdout(spec_path: Path, command: list[str]) -> None:
    result = run_cli(command, provider=FailingProvider(world()))
    assert result.code == 4
    assert result.out == ""
    assert result.err.startswith("bt: error: no data for A\nhint: ")


def test_validate_without_data_never_reaches_the_provider(spec_path: Path) -> None:
    result = run_cli(["validate", "strategy.yaml"])  # the default provider raises AssertionError if it is reached
    assert result.code == 0
    assert result.out.splitlines() == VALIDATE_HEAD[:-1]


def test_a_missing_spec_is_exit_3_for_both_commands(workdir: Path) -> None:
    assert run_cli(["data", "fetch", "nothing.yaml"]).code == 3
    assert run_cli(["validate", "nothing.yaml", "--data"]).code == 3


@pytest.mark.parametrize(
    ("command", "options"),
    [
        (["data", "fetch"], ["SPEC", "--cache-dir DIR", "--debug"]),
        (["validate"], ["SPEC", "--data", "--cache-dir DIR", "--debug"]),
    ],
)
def test_the_help_names_the_options(command: list[str], options: list[str]) -> None:
    result = run_cli([*command, "--help"])
    assert result.code == 0
    assert result.out.startswith(f"usage: bt {' '.join(command)} ")
    for option in options:
        assert option in result.out


def test_the_data_help_lists_its_action() -> None:
    assert "\n    fetch " in run_cli(["data", "--help"]).out


@pytest.mark.parametrize(
    ("issue", "expected"),
    [
        (
            ValidationIssue(Severity.ERROR, "nan_in_history", "A", "close", 1, (date(2024, 1, 4),), "x"),
            "  error   nan_in_history           A.close     count 1, first 2024-01-04",
        ),
        (
            ValidationIssue(Severity.INFO, "starts_late", "A", None, 11, (date(2024, 1, 2),), "x"),
            "  info    starts_late              A           count 11, first 2024-01-02",
        ),
        (
            ValidationIssue(
                Severity.WARNING,
                "stale_price",
                "SPY",
                "close",
                9,
                tuple(date(2024, 1, d) for d in (2, 3, 4, 5, 8)),
                "x",
            ),
            "  warning stale_price              SPY.close   count 9, first 2024-01-02, 2024-01-03, 2024-01-04, "
            "2024-01-05, 2024-01-08",
        ),
        (
            ValidationIssue(Severity.ERROR, "no_data", "A", None, 0, (), "x"),
            "  error   no_data                  A           count 0",
        ),
        (
            ValidationIssue(Severity.ERROR, "unsorted_dates", None, None, 2, (date(2024, 1, 3),), "x"),
            "  error   unsorted_dates           -           count 2",
        ),
        (
            ValidationIssue(Severity.ERROR, "duplicate_dates", None, None, 1, (date(2024, 1, 3),), "x"),
            "  error   duplicate_dates          -           count 1",
        ),
        (
            ValidationIssue(
                Severity.WARNING, "ohlc_close_outside_range", "LONGSYMBOL1", "close", 1, (date(2024, 1, 3),), "x"
            ),
            "  warning ohlc_close_outside_range LONGSYMBOL1.close count 1, first 2024-01-03",
        ),
    ],
)
def test_an_issue_line_comes_from_the_structured_fields_only(issue: ValidationIssue, expected: str) -> None:
    assert issue_line(issue) == expected
