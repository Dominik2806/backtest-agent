"""docs/cli.md is true about ``bt approve`` and the coded commands (the claims of the documents of Phase 10 part 3).

The worked example of the document is what the commands print; the exit-code table and the hints are the ones of
``classify``; every option the document names exists; the known limits it states are the behaviour; and what it says
is not built is not built. The expected blocks are literals (hashes and sizes: ``tests/coded_cli_helpers.py``,
``tests/test_cli_approve.py``); the expected output is never computed with project code.
"""

import ast
import re
from pathlib import Path

import pytest
import yaml

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
from coded_helpers import coded_spec, registry_and_modules_are_restored  # noqa: F401 - autouse fixture
from report_helpers import world as r3b_world
from runner_helpers import LiteralProvider
from test_cli_approve import CODE_LINES, CONFIRM_HINT, IDEA_LINES, SOURCE
from test_cli_record_hints import COMMANDS, CONTENTS, DOCUMENTED

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
    assert in_doc(["bt: error: the code is not approved yet; confirm it with --sha 2dd4906a", CONFIRM_HINT])
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


def table_row_with(text: str) -> str:
    rows = [line for line in DOC.splitlines() if line.startswith("|") and text in line]
    assert len(rows) == 1, text
    return rows[0]


def test_the_hint_table_says_which_commands_get_which_record_hint() -> None:
    """The rows are tied to the cases of ``tests/test_cli_record_hints.py``: every command that test runs on a damaged
    record is named in the row of the format hint, and the gate row names only the gate commands."""
    damaged = table_row_with(f"`{errors.RECORD_FORMAT_HINT}`")
    gate = table_row_with(f"`{errors.RECORD_HINT}`")
    for name, (_, through_the_gate) in COMMANDS.items():
        shown = f"`{DOCUMENTED[name]}`"
        assert shown in damaged, name
        assert (shown in gate) is through_the_gate, name
    assert "`ApprovalFormatError`" in damaged and "`RecordError`" in damaged and "`RecordError`" in gate
    messages = (
        "is not valid JSON in UTF-8",
        "must be an object with exactly the keys",
        "schema_version must be 1, got 2",
    )
    for message in messages:
        assert f"`{message}" in damaged, message
    assert all(what.startswith(messages) for _, what in CONTENTS.values())  # the document names every message tested
    assert "`cannot be read (...)`" in damaged
    assert "this run used" in gate and "in a first `bt run`" in gate
    assert "ApprovalFormatError" not in gate


def test_the_exit_code_row_says_that_the_hint_of_a_damaged_record_is_the_same_everywhere() -> None:
    row = table_row_with("approvals: an approval record that is not valid")
    assert "the hint is the same in all of them" in row and "the hint differs" not in row


def test_the_document_states_the_file_limits_of_the_review() -> None:
    assert "Approved code is at most 64 KiB, counted after CRLF became LF" in TEXT
    assert "A file larger than 128 KiB" in TEXT and "is not read: exit code 8" in TEXT
    assert "the static check refuses it: exit code 9, with the finding `[size]`" in TEXT
    assert "U+00A0, the no-break space, is accepted and printed as" in TEXT
    assert "visible non-ASCII" not in TEXT


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


def test_bt_signal_check_is_a_command_with_usage_errors_for_what_argparse_sees() -> None:
    assert run_cli(["signal", "check"]).code == 2  # no SPEC
    assert run_cli(["signal"]).code == 2  # no action
    assert run_cli(["signal", "check", "spec.yaml", "--approvals-dir", "a"]).code == 2  # the record is never read
    missing = run_cli(["signal", "check", "no-such-spec.yaml"])
    assert (missing.code, missing.out) == (3, "")  # it got as far as reading the spec


CASES_MODULE = "backtest_agent.coded.cases"


def imported_names(path: Path, src_root: Path) -> set[str]:
    """Every module a file imports, as an absolute dotted name; ``from a import b`` counts ``a`` and ``a.b``.

    A relative import is resolved against the package of the file (``.`` is that package, ``..`` its parent). A string
    constant that contains the name of the cases module (``import_module("backtest_agent.coded.cases")``,
    ``__import__(...)``, a string handed to ``exec``) counts as an import of it; so would a docstring that names the
    module, which is meant: say it some other way. **Not seen:** a dynamic import whose module name is computed at run
    time (a concatenation, a format string, a name read from a file or the environment).
    """
    package = list(path.relative_to(src_root).parent.parts)
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and CASES_MODULE in node.value:
            found.add(CASES_MODULE)
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - (node.level - 1)] if node.level else []
            module = ".".join([*base, *([node.module] if node.module else [])])
            found.add(module)
            found.update(f"{module}.{alias.name}" for alias in node.names)
    return found


def importers_of_cases(src_root: Path) -> list[str]:
    """The files under ``src_root`` other than ``coded/cases.py`` that import ``backtest_agent.coded.cases``."""
    found = []
    for path in sorted(src_root.rglob("*.py")):
        if path.relative_to(src_root).as_posix() == "backtest_agent/coded/cases.py":
            continue
        names = imported_names(path, src_root)
        if any(name == CASES_MODULE or name.startswith(CASES_MODULE + ".") for name in names):
            found.append(path.relative_to(src_root).as_posix())
    return found


def test_only_the_handler_of_bt_signal_check_imports_the_cases_module_so_no_other_command_runs_the_examples() -> None:
    """``bt signal check`` is the only caller of the functions of ``coded/cases.py`` (``cases_path``, ``read_cases``,
    ``parse_cases`` and ``run_cases``): exactly one module imports it, so no other command runs ``cases.yaml`` and
    nothing else raises ``CasesError`` from it."""
    assert importers_of_cases(ROOT / "src") == ["backtest_agent/cli/signal_check.py"]
    assert (ROOT / "src" / "backtest_agent" / "coded" / "cases.py").is_file()  # the scan looks at the right tree


@pytest.mark.parametrize(
    ("relative_path", "line"),
    [
        ("backtest_agent/cli/a.py", "import backtest_agent.coded.cases"),
        ("backtest_agent/cli/a.py", "import backtest_agent.coded.cases as cases"),
        ("backtest_agent/cli/a.py", "from backtest_agent.coded.cases import run_cases"),
        ("backtest_agent/cli/a.py", "from backtest_agent.coded import cases"),
        ("backtest_agent/cli/a.py", "from backtest_agent.coded import errors, cases"),
        ("backtest_agent/cli/a.py", "from ..coded import cases"),
        ("backtest_agent/cli/a.py", "from ..coded.cases import run_cases"),
        ("backtest_agent/coded/loader.py", "from .cases import run_cases"),
        ("backtest_agent/coded/loader.py", "from . import cases"),
        ("backtest_agent/cli/a.py", "def f():\n    from backtest_agent.coded.cases import run_cases"),
    ],
)
def test_the_scan_sees_every_form_of_import(tmp_path: Path, relative_path: str, line: str) -> None:
    target = tmp_path / "src" / relative_path
    target.parent.mkdir(parents=True)
    target.write_text(line + "\n", encoding="utf-8")
    assert importers_of_cases(tmp_path / "src") == [relative_path]


@pytest.mark.parametrize(
    "line",
    [
        'import_module("backtest_agent.coded.cases")',
        'importlib.import_module("backtest_agent.coded.cases").run_cases',
        '__import__("backtest_agent.coded.cases")',
        'exec("from backtest_agent.coded.cases import run_cases")',
        'MODULE = "backtest_agent.coded.cases"',
    ],
)
def test_the_scan_sees_the_name_of_the_module_in_a_string_constant(tmp_path: Path, line: str) -> None:
    target = tmp_path / "src" / "backtest_agent" / "cli" / "a.py"
    target.parent.mkdir(parents=True)
    target.write_text(line + "\n", encoding="utf-8")
    assert importers_of_cases(tmp_path / "src") == ["backtest_agent/cli/a.py"]


def test_the_scan_does_not_see_a_name_that_is_computed_at_run_time(tmp_path: Path) -> None:
    """The documented limit of the scan, written down as a test so that nobody believes it is covered."""
    target = tmp_path / "src" / "backtest_agent" / "cli" / "a.py"
    target.parent.mkdir(parents=True)
    target.write_text('import_module("backtest_agent.coded." + "cas" + "es")\n', encoding="utf-8")
    assert importers_of_cases(tmp_path / "src") == []


@pytest.mark.parametrize(
    "line",
    [
        "from backtest_agent.coded.errors import CasesError",
        "from backtest_agent.coded import errors",
        "import backtest_agent.coded.static",
        "from backtest_agent.cli import errors",
    ],
)
def test_the_scan_ignores_the_other_modules_of_the_package(tmp_path: Path, line: str) -> None:
    target = tmp_path / "src" / "backtest_agent" / "cli" / "a.py"
    target.parent.mkdir(parents=True)
    target.write_text(line + "\n", encoding="utf-8")
    cases = tmp_path / "src" / "backtest_agent" / "coded" / "cases.py"
    cases.parent.mkdir(parents=True)
    cases.write_text("from backtest_agent.coded.cases import run_cases\n", encoding="utf-8")  # the one exempt file
    assert importers_of_cases(tmp_path / "src") == []


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
