"""``bt approve``: the idea and the code of a coded signal (docs/cli.md, docs/coded-signals.md, ADR 0018).

Every expected line is a literal. The sizes, line counts and hashes were computed with ``hashlib`` and ``json`` in a
throwaway script outside the project (no project code is used to compute an expected value). Clock: ``at(0)`` is
2026-01-15 10:30:05 UTC and ``at(60)`` is 10:31:05. The tests change into a temporary folder, so the default folders
(``approvals``, ``strategies/signals``) are relative to it.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from backtest_agent.cli.argtypes import sha_prefix
from backtest_agent.cli.render import ascii_escape
from backtest_agent.data import FakeProvider
from backtest_agent.spec import SIGNALS
from cli_helpers import at, run_cli
from coded_helpers import canary_source, coded_modules, coded_spec
from runner_helpers import make_spec

ID = "rsi_pullback"
BRIEF = "Buy the dip.\n\nHold while RSI(2) < 10.\nExit at 50."

SOURCE = (
    b'"""A signal that holds a constant."""\n'
    b"from pydantic import Field\n"
    b"from backtest_agent.spec.signals import SignalParams, per_symbol_signal, register_signal\n"
    b"\n"
    b"\n"
    b"class Params(SignalParams):\n"
    b"    scale: float = Field(1.0, ge=0.0, le=1.0)\n"
    b"\n"
    b"\n"
    b'@register_signal("rsi_pullback", params=Params)\n'
    b"def rsi_pullback(prices, params):\n"
    b"    return per_symbol_signal(prices, lambda close: close * 0.0 + 0.0 * params.scale)\n"
)
OTHER = SOURCE.replace(b"0.0 * params.scale", b"1.0 * params.scale")

IDEA_SHA = "69b960c5ead04423ebe95fe32ed5ca5f8623bdc59b2ccb74b16b0a374f2f14ca"
UNICODE_IDEA_SHA8 = "52e7f6a4"
SHA = "2dd4906aab2f817dc071472f59a7029e06bfa026f20df4db0e5a620bc7137c8c"  # SOURCE, and the same with CRLF line ends
NO_NEWLINE_SHA = "833e675dbcb3be49da9d8a631f9e0dad95848659fbb55c668896fabeb043119c"  # SOURCE without the last newline
UNICODE_TAB_SHA = "f269570169ef9e6f41a65cfd874b95d94149ae13b890bfc64ab3d310edfd46f0"
CONTROL_SHA = "a3e8dc1325e989928502812a1fa93d22241341af8e4bb1d17d29371157acef22"

UNICODE_TAB = "# caf\u00e9\ttab \U0001f600\n".encode() + SOURCE  # 416 bytes, 13 lines
CONTROL = b"# a\x1b[31mb\rc\n" + SOURCE  # 411 bytes, 13 lines

RECORD_AFTER_IDEA = (
    '{"ideas":[{"approved_at":"2026-01-15T10:30:05Z","code":[],"idea_sha256":"' + IDEA_SHA + '"}],'
    '"schema_version":1,"signal_id":"rsi_pullback"}\n'
).encode()
RECORD_AFTER_CODE = (
    '{"ideas":[{"approved_at":"2026-01-15T10:30:05Z","code":[{"approved_at":"2026-01-15T10:31:05Z","sha256":"'
    + SHA
    + '"}],"idea_sha256":"'
    + IDEA_SHA
    + '"}],"schema_version":1,"signal_id":"rsi_pullback"}\n'
).encode()

IDEA_LINES = [
    "Signal:     rsi_pullback",
    "Idea:       approved (sha 69b960c5)",
    "Approved:   2026-01-15T10:30:05Z",
    "Record:     approvals/rsi_pullback.json",
    "Brief:      Buy the dip.",
    "",
    "            Hold while RSI(2) < 10.",
    "            Exit at 50.",
]

REVIEW_HEAD = [
    "Signal:     rsi_pullback",
    "File:       strategies/signals/rsi_pullback.py",
    "Size:       399 bytes, 12 lines",
    f"Sha256:     {SHA}",
    "Static:     ok",
    "",
]
REVIEW_BODY = [
    ' 1 | """A signal that holds a constant."""',
    " 2 | from pydantic import Field",
    " 3 | from backtest_agent.spec.signals import SignalParams, per_symbol_signal, register_signal",
    " 4 |",
    " 5 |",
    " 6 | class Params(SignalParams):",
    " 7 |     scale: float = Field(1.0, ge=0.0, le=1.0)",
    " 8 |",
    " 9 |",
    '10 | @register_signal("rsi_pullback", params=Params)',
    "11 | def rsi_pullback(prices, params):",
    "12 |     return per_symbol_signal(prices, lambda close: close * 0.0 + 0.0 * params.scale)",
]
REVIEW = REVIEW_HEAD + REVIEW_BODY

CODE_LINES = [
    "Signal:     rsi_pullback",
    "Code:       approved (sha 2dd4906a)",
    "Approved:   2026-01-15T10:31:05Z",
    f"Archive:    approvals/code/{SHA}.py",
    "Record:     approvals/rsi_pullback.json",
    f"Pin:        not set (signal.coded.code_sha256: {SHA})",
]

NEUTRAL_HINT = "hint: approvals are made with bt approve; see docs/coded-signals.md"
CONFIRM_HINT = "hint: read the code printed above; if you accept it, run: bt approve spec.yaml --code --sha 2dd4906a"


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def write_spec(workdir: Path, *, brief: str = BRIEF, pin: str | None = None, signal_id: str = ID) -> None:
    spec = coded_spec(signal_id, brief=brief, pin=pin)
    (workdir / "spec.yaml").write_text(yaml.safe_dump(spec.to_dict(), sort_keys=False), encoding="utf-8")


def put(workdir: Path, data: bytes, signal_id: str = ID, *, folder_name: str = "strategies/signals") -> Path:
    folder = workdir / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{signal_id}.py"
    path.write_bytes(data)
    return path


@pytest.fixture
def spec(workdir: Path) -> Path:
    write_spec(workdir)
    return workdir / "spec.yaml"


def tree(workdir: Path) -> list[str]:
    folder = workdir / "approvals"
    return sorted(p.relative_to(workdir).as_posix() for p in folder.rglob("*")) if folder.exists() else []


def approved_idea(clock: Callable[[], datetime] | None = None) -> None:
    assert run_cli(["approve", "spec.yaml", "--idea"], clock=clock if clock is not None else at(0)).code == 0


# --- the idea ---


def test_the_idea_is_approved_and_the_record_is_written(spec: Path, workdir: Path) -> None:
    result = run_cli(["approve", "spec.yaml", "--idea"], clock=at(0))
    assert (result.code, result.err) == (0, "")
    assert result.out.splitlines() == IDEA_LINES
    assert (workdir / "approvals" / "rsi_pullback.json").read_bytes() == RECORD_AFTER_IDEA
    assert tree(workdir) == ["approvals/rsi_pullback.json"]


def test_a_repeat_says_already_approved_with_the_first_time_and_changes_no_byte(spec: Path, workdir: Path) -> None:
    approved_idea(at(0))
    record = workdir / "approvals" / "rsi_pullback.json"
    before = record.read_bytes()
    result = run_cli(["approve", "spec.yaml", "--idea"], clock=at(60))
    assert (result.code, result.err) == (0, "")
    assert result.out.splitlines() == [
        "Signal:     rsi_pullback",
        "Idea:       already approved (sha 69b960c5)",
        "Approved:   2026-01-15T10:30:05Z",
        "Record:     approvals/rsi_pullback.json",
        "Brief:      Buy the dip.",
        "",
        "            Hold while RSI(2) < 10.",
        "            Exit at 50.",
    ]
    assert record.read_bytes() == before == RECORD_AFTER_IDEA


def test_a_non_ascii_brief_is_printed_as_an_escape(workdir: Path) -> None:
    write_spec(workdir, brief="Caf\u00e9 dip")
    result = run_cli(["approve", "spec.yaml", "--idea"], clock=at(0))
    assert result.code == 0
    assert result.out.splitlines()[1] == "Idea:       approved (sha 52e7f6a4)"
    assert result.out.splitlines()[4] == "Brief:      Caf\\u00e9 dip"


def test_a_changed_brief_is_a_second_idea_and_the_first_stays(spec: Path, workdir: Path) -> None:
    approved_idea(at(0))
    write_spec(workdir, brief="Caf\u00e9 dip")
    result = run_cli(["approve", "spec.yaml", "--idea"], clock=at(60))
    assert result.code == 0 and "Idea:       approved (sha 52e7f6a4)" in result.out.splitlines()
    ideas = json.loads((workdir / "approvals" / "rsi_pullback.json").read_text(encoding="utf-8"))["ideas"]
    assert [entry["idea_sha256"][:8] for entry in ideas] == ["69b960c5", UNICODE_IDEA_SHA8]
    assert [entry["approved_at"] for entry in ideas] == ["2026-01-15T10:30:05Z", "2026-01-15T10:31:05Z"]


# --- the code: review, confirmation, approval ---


def test_without_sha_the_code_is_shown_and_nothing_is_written(spec: Path, workdir: Path) -> None:
    approved_idea()
    put(workdir, SOURCE)
    before = tree(workdir)
    record = (workdir / "approvals" / "rsi_pullback.json").read_bytes()
    result = run_cli(["approve", "spec.yaml", "--code"], clock=at(60))
    assert result.code == 8
    assert result.out.splitlines() == REVIEW
    assert result.err.splitlines() == [
        "bt: error: the code is not approved yet; confirm it with --sha 2dd4906a",
        CONFIRM_HINT,
    ]
    assert tree(workdir) == before == ["approvals/rsi_pullback.json"]  # no archive folder, no lock file
    assert (workdir / "approvals" / "rsi_pullback.json").read_bytes() == record == RECORD_AFTER_IDEA


def test_a_wrong_sha_shows_the_review_again_names_the_sha_of_the_current_file_and_writes_nothing(
    spec: Path, workdir: Path
) -> None:
    approved_idea()
    put(workdir, SOURCE)
    before = tree(workdir)
    result = run_cli(["approve", "spec.yaml", "--code", "--sha", "00000000"], clock=at(60))
    assert result.code == 8
    assert result.out.splitlines() == REVIEW
    assert result.err.splitlines() == [
        "bt: error: --sha 00000000 is not the start of the hash of strategies/signals/rsi_pullback.py; "
        "the file has sha 2dd4906a",
        CONFIRM_HINT,
    ]
    assert tree(workdir) == before
    assert (workdir / "approvals" / "rsi_pullback.json").read_bytes() == RECORD_AFTER_IDEA


def test_the_sha_of_a_file_that_changed_since_the_review_is_refused_with_the_new_review(
    spec: Path, workdir: Path
) -> None:
    approved_idea()
    put(workdir, SOURCE)
    put(workdir, OTHER)  # edited after the person read SOURCE
    result = run_cli(["approve", "spec.yaml", "--code", "--sha", "2dd4906a"], clock=at(60))
    assert result.code == 8
    assert result.out.splitlines()[3] == "Sha256:     44e50adacf12405da1f1fc701f55e35d222de5829ae72494daa6298486c82bbb"
    assert result.out.splitlines()[-1] == (
        "12 |     return per_symbol_signal(prices, lambda close: close * 0.0 + 1.0 * params.scale)"
    )
    assert result.err.splitlines()[-1] == (
        "hint: read the code printed above; if you accept it, run: bt approve spec.yaml --code --sha 44e50ada"
    )
    assert tree(workdir) == ["approvals/rsi_pullback.json"]


def test_the_right_sha_approves_and_archives_the_bytes_that_were_shown(spec: Path, workdir: Path) -> None:
    approved_idea(at(0))
    put(workdir, SOURCE)
    result = run_cli(["approve", "spec.yaml", "--code", "--sha", "2dd4906a"], clock=at(60))
    assert (result.code, result.err) == (0, "")
    assert result.out.splitlines() == CODE_LINES
    assert (workdir / "approvals" / "code" / f"{SHA}.py").read_bytes() == SOURCE
    assert (workdir / "approvals" / "rsi_pullback.json").read_bytes() == RECORD_AFTER_CODE
    assert tree(workdir) == ["approvals/code", f"approvals/code/{SHA}.py", "approvals/rsi_pullback.json"]


def test_the_sha_is_accepted_in_capitals(spec: Path, workdir: Path) -> None:
    approved_idea(at(0))
    put(workdir, SOURCE)
    result = run_cli(["approve", "spec.yaml", "--code", "--sha", "2DD4906A"], clock=at(60))
    assert result.code == 0
    assert result.out.splitlines() == CODE_LINES


def test_a_repeat_of_the_code_says_already_approved_with_the_first_time_and_changes_no_byte(
    spec: Path, workdir: Path
) -> None:
    approved_idea(at(0))
    put(workdir, SOURCE)
    assert run_cli(["approve", "spec.yaml", "--code", "--sha", "2dd4906a"], clock=at(60)).code == 0
    record = (workdir / "approvals" / "rsi_pullback.json").read_bytes()
    archive = (workdir / "approvals" / "code" / f"{SHA}.py").read_bytes()
    result = run_cli(["approve", "spec.yaml", "--code", "--sha", "2dd4906a"], clock=at(3600))
    assert (result.code, result.err) == (0, "")
    assert result.out.splitlines() == [
        line.replace("Code:       approved", "Code:       already approved") for line in CODE_LINES
    ]
    assert (workdir / "approvals" / "rsi_pullback.json").read_bytes() == record == RECORD_AFTER_CODE
    assert (workdir / "approvals" / "code" / f"{SHA}.py").read_bytes() == archive == SOURCE


def test_a_file_with_windows_line_ends_has_the_same_review_and_the_same_sha(spec: Path, workdir: Path) -> None:
    approved_idea(at(0))
    put(workdir, SOURCE.replace(b"\n", b"\r\n"))
    review = run_cli(["approve", "spec.yaml", "--code"])
    assert review.code == 8
    assert review.out.splitlines() == REVIEW  # 399 bytes: the LF-normalised bytes that are hashed
    approved = run_cli(["approve", "spec.yaml", "--code", "--sha", "2dd4906a"], clock=at(60))
    assert approved.out.splitlines() == CODE_LINES
    assert (workdir / "approvals" / "code" / f"{SHA}.py").read_bytes() == SOURCE  # archived with LF


def test_a_last_line_without_a_newline_counts_as_a_line(spec: Path, workdir: Path) -> None:
    approved_idea()
    put(workdir, SOURCE[:-1])
    result = run_cli(["approve", "spec.yaml", "--code"])
    assert result.code == 8
    assert result.out.splitlines()[2:4] == ["Size:       398 bytes, 12 lines", f"Sha256:     {NO_NEWLINE_SHA}"]
    assert result.out.splitlines()[-1] == REVIEW_BODY[-1]


def test_tab_and_non_ascii_characters_are_shown_as_escapes(spec: Path, workdir: Path) -> None:
    approved_idea()
    put(workdir, UNICODE_TAB)
    result = run_cli(["approve", "spec.yaml", "--code"])
    assert result.code == 8
    assert result.out.splitlines()[2:4] == ["Size:       416 bytes, 13 lines", f"Sha256:     {UNICODE_TAB_SHA}"]
    assert result.out.splitlines()[6] == " 1 | # caf\\u00e9\\x09tab \\U0001f600"
    assert result.out.splitlines()[7] == ' 2 | """A signal that holds a constant."""'
    assert result.out.isascii()


def test_the_static_check_refuses_an_escape_character_before_anything_is_shown(spec: Path, workdir: Path) -> None:
    approved_idea()
    put(workdir, b"# a\x1b[31mb\n" + SOURCE)
    result = run_cli(["approve", "spec.yaml", "--code"])
    assert result.code == 9
    assert result.out == ""
    assert result.err.splitlines() == [
        "bt: error: the signal source breaks 1 rule of the static check:",
        "  - line 1: the character U+001B (Cc) is not allowed [character]",
        "hint: the rules a coded signal has to follow are in docs/coded-signals.md",
    ]
    assert tree(workdir) == ["approvals/rsi_pullback.json"]


def test_control_characters_are_escaped_in_the_review_even_if_the_static_check_missed_them(
    spec: Path, workdir: Path, monkeypatch
) -> None:
    """Defence in depth: the real static check refuses these (test above); here it is switched off in the command."""
    approved_idea()
    monkeypatch.setattr("backtest_agent.cli.coded.check_source", lambda data, signal_id: None)
    put(workdir, CONTROL)
    result = run_cli(["approve", "spec.yaml", "--code"])
    assert result.code == 8
    assert result.out.splitlines()[2:4] == ["Size:       411 bytes, 13 lines", f"Sha256:     {CONTROL_SHA}"]
    assert result.out.splitlines()[6] == " 1 | # a\\x1b[31mb\\x0dc"
    assert "\x1b" not in result.out and "\r" not in result.out.replace("\r\n", "")


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("\x1b", "\\x1b"),
        ("\r", "\\x0d"),
        ("\x00", "\\x00"),
        ("\x08", "\\x08"),
        ("\x7f", "\\x7f"),
        ("\t", "\\x09"),
        ("\u00e9", "\\u00e9"),
        ("\u202e", "\\u202e"),
        ("\U0001f600", "\\U0001f600"),
        ("~ and space", "~ and space"),
        # the exact boundaries of the rule written in docs/cli.md
        (chr(0x1F), chr(92) + "x1f"),  # the last character below the space
        (chr(0x20), " "),  # the first character that is printed as it is
        (chr(0x7E), "~"),  # the last one
        (chr(0x80), chr(92) + "u0080"),  # the C1 range goes to the four-digit form, not to the two-digit one
        (chr(0x9F), chr(92) + "u009f"),
        (chr(0xA0), chr(92) + "u00a0"),
        (chr(0xFFFF), chr(92) + "uffff"),
        (chr(0x10000), chr(92) + "U00010000"),
    ],
)
def test_ascii_escape_of_one_character(raw: str, shown: str) -> None:
    assert ascii_escape(raw) == shown


# --- the hint repeats the folder options that were given ---

CONFIRM = "hint: read the code printed above; if you accept it, run: bt approve spec.yaml --code --sha 2dd4906a"


@pytest.mark.parametrize(
    ("options", "shown"),
    [
        ((), ""),
        (("--approvals-dir", "appr"), " --approvals-dir appr"),
        (("--strategies-dir", "src/signals"), " --strategies-dir src/signals"),
        (
            ("--strategies-dir", "src_signals", "--approvals-dir", "appr"),
            " --approvals-dir appr --strategies-dir src_signals",
        ),
        (("--approvals-dir", "my approvals"), ' --approvals-dir "my approvals"'),
        (("--approvals-dir", "approvals", "--strategies-dir", "strategies/signals"), ""),
    ],
    ids=["defaults", "approvals", "strategies", "both-in-fixed-order", "space", "given-but-default"],
)
@pytest.mark.parametrize("sha", [[], ["--sha", "00000000"]], ids=["missing-sha", "wrong-sha"])
def test_the_confirmation_hint_repeats_the_given_folders(
    options: tuple[str, ...], shown: str, sha: list[str], spec: Path, workdir: Path
) -> None:
    folder = options[options.index("--strategies-dir") + 1] if "--strategies-dir" in options else "strategies/signals"
    put(workdir, SOURCE, folder_name=folder)
    assert run_cli(["approve", "spec.yaml", "--idea", *options], clock=at(0)).code == 0
    result = run_cli(["approve", "spec.yaml", "--code", *sha, *options], clock=at(60))
    assert result.code == 8
    assert result.err.splitlines()[-1] == CONFIRM + shown
    assert result.out.splitlines()[:5] == [
        "Signal:     rsi_pullback",
        f"File:       {folder}/rsi_pullback.py",
        "Size:       399 bytes, 12 lines",
        f"Sha256:     {SHA}",
        "Static:     ok",
    ]


# --- refusals: nothing is printed when the idea is not approved ---


def test_the_code_of_an_idea_that_is_not_approved_prints_nothing_and_exits_8(spec: Path, workdir: Path) -> None:
    put(workdir, SOURCE)
    result = run_cli(["approve", "spec.yaml", "--code"])
    assert result.code == 8
    assert result.out == ""
    assert result.err.splitlines() == [
        "bt: error: the idea of 'rsi_pullback' is not approved; approve the idea first",
        NEUTRAL_HINT,
    ]
    assert tree(workdir) == []  # the approvals folder was not even created


def test_the_idea_of_another_brief_is_not_the_approved_idea(spec: Path, workdir: Path) -> None:
    approved_idea()
    write_spec(workdir, brief="Another idea")
    put(workdir, SOURCE)
    result = run_cli(["approve", "spec.yaml", "--code", "--sha", "2dd4906a"])
    assert (result.code, result.out) == (8, "")
    assert result.err.splitlines()[0] == "bt: error: the idea of 'rsi_pullback' is not approved; approve the idea first"
    assert tree(workdir) == ["approvals/rsi_pullback.json"]


def test_a_missing_file_and_a_folder_are_code_8_with_the_neutral_hint(spec: Path, workdir: Path) -> None:
    approved_idea()
    missing = run_cli(["approve", "spec.yaml", "--code"])
    assert (missing.code, missing.out) == (8, "")
    # the reason in the parentheses is the operating system's own words (its language), so only its frame is pinned
    first, hint = missing.err.splitlines()
    assert first.startswith("bt: error: strategies/signals/rsi_pullback.py cannot be read (") and first.endswith(")")
    assert hint == NEUTRAL_HINT
    (workdir / "strategies" / "signals" / "rsi_pullback.py").mkdir(parents=True)
    folder = run_cli(["approve", "spec.yaml", "--code"])
    assert (folder.code, folder.out) == (8, "")
    assert folder.err.splitlines() == [
        "bt: error: strategies/signals/rsi_pullback.py cannot be read (not a regular file)",
        NEUTRAL_HINT,
    ]


def test_code_that_breaks_the_static_check_is_code_9_and_prints_nothing(spec: Path, workdir: Path) -> None:
    approved_idea()
    put(workdir, SOURCE.replace(b"from pydantic import Field\n", b"import os\nfrom pydantic import Field\n"))
    result = run_cli(["approve", "spec.yaml", "--code", "--sha", "2dd4906a"])
    assert (result.code, result.out) == (9, "")
    assert result.err.splitlines() == [
        "bt: error: the signal source breaks 1 rule of the static check:",
        "  - line 2: import of 'os' is not allowed [import]",
        "hint: the rules a coded signal has to follow are in docs/coded-signals.md",
    ]
    assert tree(workdir) == ["approvals/rsi_pullback.json"]


@pytest.mark.parametrize("sha", [[], ["--sha", "00000000"], ["--sha", "2dd4906a"]], ids=["review", "wrong", "right"])
def test_a_working_file_that_is_not_utf_8_is_a_static_check_error_and_nothing_else(
    sha: list[str], spec: Path, workdir: Path
) -> None:
    """The bytes are refused by the static check before anything decodes them: exit code 9, never 1, no traceback."""
    approved_idea()
    put(workdir, b"x = '\xff'\n")
    result = run_cli(["approve", "spec.yaml", "--code", *sha])
    assert (result.code, result.out) == (9, "")
    assert result.err.splitlines() == [
        "bt: error: the signal source breaks 1 rule of the static check:",
        "  - the source is not UTF-8 (invalid start byte at byte 5) [encoding]",
        "hint: the rules a coded signal has to follow are in docs/coded-signals.md",
    ]
    assert "Traceback" not in result.err
    assert tree(workdir) == ["approvals/rsi_pullback.json"]


def test_a_stale_lock_is_code_8_and_the_idea_is_not_written(spec: Path, workdir: Path) -> None:
    (workdir / "approvals").mkdir()
    (workdir / "approvals" / ".lock").write_bytes(b"")
    result = run_cli(["approve", "spec.yaml", "--idea"])
    assert (result.code, result.out) == (8, "")
    assert result.err.splitlines() == [
        "bt: error: another approval is in progress (.lock exists in the approvals folder); if no other bt approve "
        "is running, delete that file and try again",
        NEUTRAL_HINT,
    ]
    assert tree(workdir) == ["approvals/.lock"]


def test_a_damaged_record_is_code_5(spec: Path, workdir: Path) -> None:
    (workdir / "approvals").mkdir()
    (workdir / "approvals" / "rsi_pullback.json").write_bytes(b"{")
    result = run_cli(["approve", "spec.yaml", "--idea"])
    assert (result.code, result.out) == (5, "")
    assert result.err.splitlines()[0].startswith("bt: error: rsi_pullback.json: ")
    assert result.err.splitlines()[-1] == (
        "hint: an approval record is not valid; restore it from version control (docs/coded-signals.md)"
    )


def test_a_spec_without_a_coded_block_is_code_3(workdir: Path) -> None:
    (workdir / "spec.yaml").write_text(yaml.safe_dump(make_spec().to_dict(), sort_keys=False), encoding="utf-8")
    result = run_cli(["approve", "spec.yaml", "--idea"])
    assert (result.code, result.out) == (3, "")
    assert result.err.splitlines() == [
        "bt: error: Invalid strategy spec in spec.yaml (1 problem):",
        "  - signal.coded: the spec has no coded block; only a coded signal is approved",
        "hint: the fields of a spec are described in docs/strategy-spec.md",
    ]
    assert tree(workdir) == []


# --- the pin line ---


def test_the_pin_line_has_three_states(workdir: Path) -> None:
    put(workdir, SOURCE)
    lines = {}
    for name, pin in (("matches", SHA), ("differs", "ab" * 32)):
        write_spec(workdir, pin=pin)
        approved_idea()
        result = run_cli(["approve", "spec.yaml", "--code", "--sha", "2dd4906a"], clock=at(60))
        assert result.code == 0
        lines[name] = result.out.splitlines()[-1]
    assert lines == {"matches": "Pin:        matches", "differs": "Pin:        differs (spec pins abababab)"}


# --- arguments (exit code 2) ---


@pytest.mark.parametrize(
    ("args", "last_line"),
    [
        (["approve", "spec.yaml"], "bt approve: error: one of the arguments --idea --code is required"),
        (
            ["approve", "spec.yaml", "--idea", "--code"],
            "bt approve: error: argument --code: not allowed with argument --idea",
        ),
        (
            ["approve", "spec.yaml", "--code", "--sha", "zz"],
            "bt approve: error: argument --sha: 'zz' is not 8 hexadecimal characters (the start of the hash)",
        ),
        (
            ["approve", "spec.yaml", "--code", "--sha", "2dd4906ab"],
            "bt approve: error: argument --sha: '2dd4906ab' is not 8 hexadecimal characters (the start of the hash)",
        ),
        (
            ["approve", "spec.yaml", "--code", "--sha", "2dd490"],
            "bt approve: error: argument --sha: '2dd490' is not 8 hexadecimal characters (the start of the hash)",
        ),
    ],
    ids=["neither", "both", "not-hex", "nine-hex", "six-hex"],
)
def test_a_wrong_combination_or_a_malformed_sha_is_a_usage_error(
    args: list[str], last_line: str, spec: Path, workdir: Path
) -> None:
    result = run_cli(args)
    assert (result.code, result.out) == (2, "")
    assert result.err.splitlines()[-1] == last_line
    assert tree(workdir) == []


def test_sha_with_the_idea_is_a_usage_error_and_writes_nothing(spec: Path, workdir: Path) -> None:
    result = run_cli(["approve", "spec.yaml", "--idea", "--sha", "2dd4906a"])
    assert (result.code, result.out) == (2, "")
    assert result.err.splitlines() == [
        "bt: error: --sha goes with --code; the idea needs no confirmation",
        "hint: bt approve --help describes the arguments",
    ]
    assert tree(workdir) == []


def test_sha_prefix_is_lowercased_and_exactly_eight_hex() -> None:
    assert sha_prefix("2DD4906a") == "2dd4906a"
    for bad in ("", "2dd4906", "2dd4906aa", "2dd4906g", " 2dd4906a"):
        with pytest.raises(Exception, match="8 hexadecimal"):
            sha_prefix(bad)


# --- the file is read once; the clock once; no data; nothing is executed ---


def test_the_file_is_read_once_and_the_bytes_shown_hashed_and_archived_are_those_bytes(
    spec: Path, workdir: Path, monkeypatch
) -> None:
    from backtest_agent.cli import coded

    approved_idea()
    path = put(workdir, SOURCE)
    reads: list[bytes] = []
    real = coded.read_working_file

    def read_then_change(file: Path, shown: str) -> bytes:
        data = real(file, shown)
        reads.append(data)
        path.write_bytes(OTHER)  # the file changes right after the one read
        return data

    monkeypatch.setattr(coded, "read_working_file", read_then_change)
    result = run_cli(["approve", "spec.yaml", "--code", "--sha", "2dd4906a"], clock=at(60))
    assert result.code == 0
    assert result.out.splitlines() == CODE_LINES
    assert reads == [SOURCE]
    assert (workdir / "approvals" / "code" / f"{SHA}.py").read_bytes() == SOURCE
    assert path.read_bytes() == OTHER  # the working file is never written by the command


def test_the_clock_is_read_once_per_command_and_no_data_is_requested(spec: Path, workdir: Path) -> None:
    ticks: list[int] = []

    def clock() -> datetime:
        ticks.append(1)
        return at(0)()

    provider = FakeProvider(symbols=("AAA", "BBB"))
    put(workdir, SOURCE)
    for args in (["--idea"], ["--code"], ["--code", "--sha", "2dd4906a"]):
        ticks.clear()
        run_cli(["approve", "spec.yaml", *args], clock=clock, provider=provider)
        assert ticks == [1]
    assert provider.calls == []


def test_bt_approve_never_executes_the_code(workdir: Path, world, static_check_off, monkeypatch) -> None:
    """A canary writes a line to a marker file when it is imported. Even with every static check switched off, so that
    the command accepts it, the command only reads, hashes and archives the bytes."""
    monkeypatch.setattr("backtest_agent.cli.coded.check_source", lambda data, signal_id: None)
    write_spec(workdir, signal_id="canary_signal", brief="B")
    ids_before = SIGNALS.ids()
    source = canary_source("canary_signal")
    put(workdir, source, "canary_signal")
    assert run_cli(["approve", "spec.yaml", "--idea"]).code == 0
    sha = hashlib.sha256(source.replace(b"\r\n", b"\n")).hexdigest()
    review = run_cli(["approve", "spec.yaml", "--code"])
    assert review.code == 8
    approved = run_cli(["approve", "spec.yaml", "--code", "--sha", sha[:8]])
    assert approved.code == 0
    assert (workdir / "approvals" / "code" / f"{sha}.py").read_bytes() == source
    assert world.marker_lines() == []
    assert coded_modules() == []
    assert SIGNALS.ids() == ids_before


def test_the_real_static_check_stops_the_canary_before_it_is_archived(workdir: Path, world) -> None:
    write_spec(workdir, signal_id="canary_signal", brief="B")
    put(workdir, canary_source("canary_signal"), "canary_signal")
    assert run_cli(["approve", "spec.yaml", "--idea"]).code == 0
    result = run_cli(["approve", "spec.yaml", "--code", "--sha", "00000000"])
    assert (result.code, result.out) == (9, "")
    assert world.marker_lines() == [] and coded_modules() == []
    assert tree(workdir) == ["approvals/canary_signal.json"]


# --- the claims of the "bt approve" section of docs/cli.md that the tests above do not pin ---

STATIC_HINT = "hint: the rules a coded signal has to follow are in docs/coded-signals.md"
WITH_OS = SOURCE.replace(b"from pydantic import Field\n", b"import os\nfrom pydantic import Field\n")
LOCK_MESSAGE = (
    "bt: error: another approval is in progress (.lock exists in the approvals folder); "
    "if no other bt approve is running, delete that file and try again"
)
SIX_LINES = (
    b"from backtest_agent.spec.signals import SignalParams, per_symbol_signal, register_signal\n"
    b"\n"
    b"\n"
    b'@register_signal("rsi_pullback", params=SignalParams)\n'
    b"def rsi_pullback(prices, params):\n"
    b"    return per_symbol_signal(prices, lambda close: close * 0.0)\n"
)  # 243 bytes, 6 lines


def test_a_file_over_128_kib_is_exit_8_and_a_file_of_exactly_128_kib_is_read(spec: Path, workdir: Path) -> None:
    approved_idea()
    put(workdir, b"#" * 131073)
    over = run_cli(["approve", "spec.yaml", "--code"])
    assert (over.code, over.out) == (8, "")
    assert over.err.splitlines() == [
        "bt: error: strategies/signals/rsi_pullback.py is larger than the limit; approved code is at most 64 KiB",
        NEUTRAL_HINT,
    ]
    put(workdir, b"#" * 131072)  # read in full; it is the static check that refuses 131072 bytes (the limit is 65536)
    at_limit = run_cli(["approve", "spec.yaml", "--code"])
    assert (at_limit.code, at_limit.out) == (9, "")
    assert at_limit.err.splitlines() == [
        "bt: error: the signal source breaks 1 rule of the static check:",
        "  - the source has 131072 bytes; the limit is 65536 [size]",
        STATIC_HINT,
    ]


def test_the_file_is_read_before_the_idea_is_checked(spec: Path, workdir: Path) -> None:
    result = run_cli(["approve", "spec.yaml", "--code"])  # no file and no approved idea
    assert (result.code, result.out) == (8, "")
    first = result.err.splitlines()[0]
    assert first.startswith("bt: error: strategies/signals/rsi_pullback.py cannot be read (") and first.endswith(")")


def test_the_idea_is_checked_before_the_static_check(spec: Path, workdir: Path) -> None:
    put(workdir, WITH_OS)  # breaks the static check, and the idea is not approved either
    result = run_cli(["approve", "spec.yaml", "--code"])
    assert (result.code, result.out) == (8, "")
    assert result.err.splitlines() == [
        "bt: error: the idea of 'rsi_pullback' is not approved; approve the idea first",
        NEUTRAL_HINT,
    ]


def test_approving_code_with_a_stale_lock_is_exit_8_and_archives_nothing(spec: Path, workdir: Path) -> None:
    approved_idea()
    put(workdir, SOURCE)
    (workdir / "approvals" / ".lock").write_bytes(b"")
    result = run_cli(["approve", "spec.yaml", "--code", "--sha", "2dd4906a"], clock=at(60))
    assert (result.code, result.out) == (8, "")
    assert result.err.splitlines() == [LOCK_MESSAGE, NEUTRAL_HINT]
    assert tree(workdir) == ["approvals/.lock", "approvals/rsi_pullback.json"]
    assert (workdir / "approvals" / "rsi_pullback.json").read_bytes() == RECORD_AFTER_IDEA


def test_the_approval_checks_the_bytes_again_before_it_archives_them(spec: Path, workdir: Path, monkeypatch) -> None:
    """The command's own static check is switched off here; the check inside the approval still refuses the file."""
    approved_idea()
    monkeypatch.setattr("backtest_agent.cli.coded.check_source", lambda data, signal_id: None)
    put(workdir, WITH_OS)
    sha8 = hashlib.sha256(WITH_OS).hexdigest()[:8]
    result = run_cli(["approve", "spec.yaml", "--code", "--sha", sha8], clock=at(60))
    assert (result.code, result.out) == (9, "")
    assert result.err.splitlines() == [
        "bt: error: the signal source breaks 1 rule of the static check:",
        "  - line 2: import of 'os' is not allowed [import]",
        STATIC_HINT,
    ]
    assert tree(workdir) == ["approvals/rsi_pullback.json"]


def test_the_line_numbers_are_as_wide_as_the_largest_one(spec: Path, workdir: Path) -> None:
    approved_idea()
    put(workdir, SIX_LINES)
    six = run_cli(["approve", "spec.yaml", "--code"]).out.splitlines()
    assert six[2] == "Size:       243 bytes, 6 lines"
    assert six[6:] == [
        "1 | from backtest_agent.spec.signals import SignalParams, per_symbol_signal, register_signal",
        "2 |",
        "3 |",
        '4 | @register_signal("rsi_pullback", params=SignalParams)',
        "5 | def rsi_pullback(prices, params):",
        "6 |     return per_symbol_signal(prices, lambda close: close * 0.0)",
    ]
    put(workdir, SOURCE + b"# padding line\n" * 88)  # 399 + 88 * 15 = 1719 bytes, 12 + 88 = 100 lines
    hundred = run_cli(["approve", "spec.yaml", "--code"]).out.splitlines()
    assert hundred[2] == "Size:       1719 bytes, 100 lines"
    body = hundred[6:]
    assert len(body) == 100
    assert body[0] == '  1 | """A signal that holds a constant."""'
    assert body[3] == "  4 |"
    assert body[9] == ' 10 | @register_signal("rsi_pullback", params=Params)'
    assert body[99] == "100 | # padding line"
