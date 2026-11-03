"""docs/cli.md is true about ``bt approve`` and the coded commands (the claims of the documents of Phase 10 part 3).

The worked example of the document is what the commands print; the exit-code table and the hints are the ones of
``classify``; every option the document names exists; the known limits it states are the behaviour; and what it says
is not built is not built. The expected blocks are literals (hashes and sizes: ``tests/coded_cli_helpers.py``,
``tests/test_cli_approve.py``); the expected output is never computed with project code.
"""

import re
from pathlib import Path

import pytest

from backtest_agent.cli import errors
from backtest_agent.cli.errors import ConfirmationError, UsageError, classify
from backtest_agent.coded.errors import (
    ApprovalError,
    ApprovalFormatError,
    CasesError,
    Finding,
    GateError,
    NotApprovedError,
    RecordError,
    StaticCheckError,
)
from backtest_agent.spec.errors import SignalContractError
from cli_helpers import at, run_cli
from coded_cli_helpers import HOLD_A, SHA_A, put_source, write_hold_spec
from coded_helpers import registry_and_modules_are_restored  # noqa: F401 - autouse fixture
from report_helpers import world as r3b_world
from runner_helpers import LiteralProvider
from test_cli_approve import CODE_LINES, CONFIRM_HINT, IDEA_LINES, SOURCE

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs" / "cli.md").read_text(encoding="utf-8").replace("\r\n", "\n")
TEXT = " ".join(DOC.split())


def in_doc(lines: list[str]) -> bool:
    return "\n".join(lines) in DOC


def section(title: str) -> str:
    start = DOC.index(f"### `{title}`")
    end = re.search(r"\n##+ ", DOC[start + 4 :])
    return DOC[start : start + 4 + end.start()] if end else DOC[start:]


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


# --- the worked example: from approval to run ---

STATE_1 = [
    "OK: spec.yaml is a valid spec",
    "Name:       Buy and hold A",
    "Family:     hold_a",
    "Signal:     coded, idea not approved",
    "Universe:   A",
    "Benchmark:  B",
    "Period:     2024-01-02 to 2024-01-08",
    "Warm-up:    n/a (coded signal, not loaded)",
    "Risk flags: none",
]
IDEA = [
    "Signal:     hold_a",
    "Idea:       approved (sha bc1586a4)",
    "Approved:   2026-01-15T10:30:05Z",
    "Record:     approvals/hold_a.json",
    "Brief:      Hold A for the whole period.",
]
REVIEW = [
    "Signal:     hold_a",
    "File:       strategies/signals/hold_a.py",
    "Size:       426 bytes, 13 lines",
    f"Sha256:     {SHA_A}",
    "Static:     ok",
    "",
    ' 1 | """Buy and hold, written as a coded signal."""',
    " 2 | import pandas as pd",
    " 3 | from pydantic import Field",
    " 4 | from backtest_agent.spec.signals import SignalParams, per_symbol_signal, register_signal",
    " 5 |",
    " 6 |",
    " 7 | class Params(SignalParams):",
    " 8 |     scale: float = Field(1.0, ge=0.0, le=1.0)",
    " 9 |",
    "10 |",
    '11 | @register_signal("hold_a", params=Params)',
    "12 | def hold_a(prices, params):",
    "13 |     return per_symbol_signal(prices, lambda close: pd.Series(params.scale, index=close.index))",
]
REVIEW_ERROR = [
    "bt: error: the code is not approved yet; confirm it with --sha 8b0b3234",
    "hint: read the code printed above; if you accept it, run: bt approve spec.yaml --code --sha 8b0b3234",
]
CODE = [
    "Signal:     hold_a",
    "Code:       approved (sha 8b0b3234)",
    "Approved:   2026-01-15T10:31:05Z",
    f"Archive:    approvals/code/{SHA_A}.py",
    "Record:     approvals/hold_a.json",
    f"Pin:        not set (signal.coded.code_sha256: {SHA_A})",
]
RUN = [
    "Run:        20260115T103205Z-buy-and-hold-a-HHHHHHHH",
    "Strategy:   Buy and hold A (family hold_a)",
    "Trials:     family hold_a: 1 distinct variant in 1 run as of this run. "
    "This run is run 1, a new variant (variant 1). Counts cover only runs logged in this journal.",
    "Period:     2024-01-02 to 2024-01-08, 5 bars",
    "Costs:      applied",
    "",
    "Metric               Strategy  Benchmark (B)",
    "Total return           17.13%        -21.59%",
    "CAGR              288,635.82%       -100.00%",
    "Sharpe ratio             5.87          -7.50",
    "Maximum drawdown      -12.00%        -21.59%",
    "",
    "Excess return (compared window): +38.72%",
    "",
    "Risk flags: none",
    "Journal:    runs/20260115T103205Z-buy-and-hold-a-HHHHHHHH/run.json",
    "Report:     reports/20260115T103205Z-buy-and-hold-a-HHHHHHHH/report.md and report.html",
]


def test_the_worked_example_is_what_the_commands_print_and_is_in_the_document(workdir: Path) -> None:
    write_hold_spec(workdir)
    put_source(workdir, HOLD_A)
    spec_bytes = (workdir / "spec.yaml").read_bytes()
    working_file = (workdir / "strategies" / "signals" / "hold_a.py").read_bytes()

    state_1 = run_cli(["validate", "spec.yaml"])
    assert state_1.out.splitlines() == STATE_1
    idea = run_cli(["approve", "spec.yaml", "--idea"], clock=at(0))
    assert idea.out.splitlines() == IDEA
    review = run_cli(["approve", "spec.yaml", "--code"], clock=at(60))
    assert (review.code, review.out.splitlines(), review.err.splitlines()) == (8, REVIEW, REVIEW_ERROR)
    approved = run_cli(["approve", "spec.yaml", "--code", "--sha", "8b0b3234"], clock=at(60))
    assert (approved.code, approved.out.splitlines()) == (0, CODE)
    validated = run_cli(["validate", "spec.yaml"])
    assert "Signal:     coded, idea and code approved (sha 8b0b3234)" in validated.out.splitlines()
    assert "Warm-up:    n/a (coded signal, not loaded)" in validated.out.splitlines()
    run = run_cli(["run", "spec.yaml"], provider=LiteralProvider(r3b_world()), clock=at(120))
    assert run.code == 0, run.err
    run_hash = re.search(r"buy-and-hold-a-([0-9a-f]{8})", run.out).group(1)
    assert run.out.replace(run_hash, "HHHHHHHH").splitlines() == RUN

    # neither the spec nor the working file is ever written by approving or running
    assert (workdir / "spec.yaml").read_bytes() == spec_bytes
    assert (workdir / "strategies" / "signals" / "hold_a.py").read_bytes() == working_file

    for block in (STATE_1, IDEA, REVIEW, REVIEW_ERROR, CODE, RUN):
        assert in_doc(block), block[0]
    assert "`strategies/signals/hold_a.py` (13 lines, 426 bytes" in TEXT


def test_the_approve_section_shows_the_blocks_of_the_tests() -> None:
    wrong = (
        "--sha 00000000 is not the start of the hash of strategies/signals/rsi_pullback.py; the file has sha 2dd4906a"
    )
    assert in_doc(IDEA_LINES)
    assert in_doc(CODE_LINES)
    assert in_doc(
        [
            "bt: error: the code is not approved yet; confirm it with --sha 2dd4906a",
            CONFIRM_HINT.removeprefix("hint: ").join(["hint: ", ""]),
        ]
    )
    assert in_doc([f"bt: error: {wrong}", CONFIRM_HINT])


# --- the exit codes ---

EXIT_CODES = DOC[DOC.index("## Exit codes") : DOC.index("## Errors")]
ROWS = {int(m.group(1)): m.group(0) for m in re.finditer(r"^\| (\d+) \|.*$", EXIT_CODES, flags=re.MULTILINE)}


def row(code: int) -> str:
    return ROWS[code]


SAMPLES = {
    "NotApprovedError": NotApprovedError("x"),
    "ApprovalError": ApprovalError("x"),
    "ConfirmationError": ConfirmationError("s.yaml", "abcdef12", "x"),
    "RecordError": RecordError("x"),
    "ApprovalFormatError": ApprovalFormatError("x"),
    "StaticCheckError": StaticCheckError([Finding(1, 0, "rule", "message")]),
    "SignalContractError": SignalContractError("x"),
    "GateError": GateError("x"),
    "CasesError": CasesError("x"),
    "UsageError": UsageError("x"),
}


@pytest.mark.parametrize("code", sorted({int(c) for c in errors.ExitCode}))
def test_every_exit_code_has_a_row_in_the_table(code: int) -> None:
    assert code in ROWS, code


@pytest.mark.parametrize(("name", "code"), [(n, classify(e).code) for n, e in SAMPLES.items()])
def test_the_table_lists_each_class_in_the_row_of_its_code(name: str, code: int) -> None:
    assert f"`{name}`" in row(code), (name, code)


def test_the_codes_of_the_documented_classes() -> None:
    assert {n: int(classify(e).code) for n, e in SAMPLES.items()} == {
        "NotApprovedError": 8,
        "ApprovalError": 8,
        "ConfirmationError": 8,
        "RecordError": 5,
        "ApprovalFormatError": 5,
        "StaticCheckError": 9,
        "SignalContractError": 9,
        "GateError": 9,
        "CasesError": 9,
        "UsageError": 2,
    }


@pytest.mark.parametrize(
    "hint",
    [
        errors.APPROVAL_HINT,
        errors.RECORD_HINT,
        errors.RECORD_FORMAT_HINT,
        errors.CODE_HINT,
        errors.CONTRACT_HINT,
        "bt approve --help describes the arguments",
        "read the code printed above; if you accept it, run: bt approve SPEC --code --sha <8 hex>",
    ],
)
def test_the_hints_of_the_document_are_the_ones_of_the_code(hint: str) -> None:
    assert f"`{hint}`" in TEXT


def test_the_order_sentence_names_the_new_groups_in_the_order_of_classify() -> None:
    order = [
        "usage (`UsageError`)",
        "approval records (`RecordError`, `ApprovalFormatError`: code 5)",
        "refusals (`ConfirmationError`, `NotApprovedError`, `ApprovalError`: code 8)",
        "rejected code (`StaticCheckError`, `CasesError`, `GateError`, `SignalContractError`: code 9)",
    ]
    positions = [TEXT.index(part) for part in order]
    assert positions == sorted(positions)
    source = (ROOT / "src" / "backtest_agent" / "cli" / "errors.py").read_text(encoding="utf-8")
    names = ["UsageError", "RecordError", "ApprovalFormatError", "ConfirmationError", "NotApprovedError"]
    named = [source.index(f"isinstance(error, {n}") for n in names]
    assert named == sorted(named)


# --- the options ---

OPTIONS = [
    ("bt run SPEC", ["run"], ["--approvals-dir", "--strategies-dir"]),
    ("bt validate SPEC", ["validate"], ["--approvals-dir", "--strategies-dir"]),
    ("bt data fetch SPEC", ["data", "fetch"], ["--approvals-dir", "--strategies-dir"]),
    ("bt report RUN_ID", ["report"], ["--approvals-dir"]),
    ("bt approve SPEC", ["approve"], ["--idea", "--code", "--sha", "--approvals-dir", "--strategies-dir"]),
]


@pytest.mark.parametrize(("title", "command", "options"), OPTIONS, ids=[o[0] for o in OPTIONS])
def test_every_option_the_document_names_exists_and_every_new_option_is_documented(
    title: str, command: list[str], options: list[str]
) -> None:
    help_text = run_cli([*command, "--help"]).out
    for option in options:
        assert option in help_text, option
        assert f"`{option}" in section(title), option


def test_report_has_no_strategies_dir_because_it_never_reads_the_working_file() -> None:
    assert "--strategies-dir" not in run_cli(["report", "--help"]).out
    assert "--strategies-dir" not in section("bt report RUN_ID")


# --- what the document says is not built is not built ---


def test_bt_signal_check_is_not_a_command() -> None:
    result = run_cli(["signal", "check", "spec.yaml"])
    assert (result.code, result.out) == (2, "")
    assert "**`bt signal check` and the agents are not built yet**" in TEXT


def test_nothing_in_the_package_runs_the_examples_so_nothing_raises_cases_error_in_a_command() -> None:
    callers = []
    for path in (ROOT / "src" / "backtest_agent").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in ("run_cases(", "read_cases(", "parse_cases("):
            if name in text and path.name != "cases.py":
                callers.append((path.name, name))
    assert callers == []
    assert classify(CasesError("x")).code == 9  # mapped, so that the command can use it


# --- the known limits are the behaviour ---


def test_a_literal_backslash_u00e9_and_a_real_e_acute_look_the_same_in_the_review(workdir: Path) -> None:
    write_spec_and_idea(workdir)
    shown = {}
    for name, marker in (("literal", chr(92) + "u00e9"), ("real", chr(0xE9))):
        path = workdir / "strategies" / "signals" / "rsi_pullback.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("# " + marker + "\n").encode("utf-8") + SOURCE)
        result = run_cli(["approve", "spec.yaml", "--code"])
        assert result.code == 8
        shown[name] = result.out.splitlines()[6]
    assert shown["literal"] == shown["real"] == " 1 | # " + chr(92) + "u00e9"
    assert chr(92) + "u00e9" in DOC and "look the same in the review" in TEXT


def write_spec_and_idea(workdir: Path) -> None:
    import yaml

    from coded_helpers import coded_spec

    spec = coded_spec("rsi_pullback", brief="B")
    (workdir / "spec.yaml").write_text(yaml.safe_dump(spec.to_dict(), sort_keys=False), encoding="utf-8")
    assert run_cli(["approve", "spec.yaml", "--idea"], clock=at(0)).code == 0


def test_a_path_with_a_dollar_sign_is_put_in_double_quotes_which_powershell_expands() -> None:
    hint = classify(ConfirmationError("my$dir/s.yaml", "abcdef12", "x")).hint
    assert hint.endswith('bt approve "my$dir/s.yaml" --code --sha abcdef12')
    assert "PowerShell expands `$` and the backtick inside double quotes" in TEXT


def test_the_document_says_that_no_rule_denies_the_command_to_an_agent_yet() -> None:
    assert "that rule does not exist yet" in TEXT


# --- the status of the phase ---


def test_the_status_tables_say_that_phase_10_is_in_progress() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    assert "| 10 | Strategy architect and signal coder subagents | In progress |" in readme
    assert re.search(r"^\| 10 \| `feature/agents-architect-coder` .*\| In progress \|$", roadmap, flags=re.MULTILINE)
