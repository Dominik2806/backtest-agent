"""No file of ours contains an invisible character: Unicode categories Cc, Cf, Zl and Zp (docs/coded-signals.md).

The same characters are refused in a brief and in the source of a coded signal, because they hide text from a
reader. A test that needs one writes it as an escape (backslash, u and four hex digits) or with chr(). Only a line
break, a tab and the CR of a CRLF are allowed.
"""

import os
import shutil
import subprocess
import unicodedata
from collections.abc import Mapping
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ["src", "tests", "docs", "strategies", "approvals"]
SUFFIXES = {".py", ".md", ".yaml"}
TRACKED_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".toml", ".json", ".txt", ".cfg"}
FORBIDDEN = {"Cc", "Cf", "Zl", "Zp"}
ALLOWED = {"\n", "\t"}


def files() -> list[Path]:
    found = []
    for folder in FOLDERS:
        base = ROOT / folder
        if base.is_dir():
            found += [
                p for p in base.rglob("*") if p.is_file() and p.suffix in SUFFIXES and "__pycache__" not in p.parts
            ]
    return sorted(found)


def tracked_files() -> list[Path]:
    """Every text file that git tracks (root files, .github, .claude, ...); empty if git is missing or fails."""
    if shutil.which("git") is None:
        return []
    try:
        done = subprocess.run(
            ["git", "-c", "core.quotepath=off", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True
        )
    except OSError:
        return []
    if done.returncode != 0:  # not a repository (a source archive, for example)
        return []
    names = [name for name in done.stdout.split(chr(0)) if name]
    return sorted(p for p in (ROOT / name for name in names) if p.suffix in TRACKED_SUFFIXES and p.is_file())


def require_tracked_files(files: list[Path], environ: Mapping[str, str]) -> None:
    """Decide what an empty list of tracked files means.

    In CI (the variable ``CI`` is set and not empty) it is a failure, because the guard for the root files, ``.github``
    and ``.claude`` would be off without anyone noticing. Elsewhere it is a skip (no git, or not a repository).
    """
    if files:
        return
    if environ.get("CI"):
        pytest.fail(
            "git did not list the tracked files in CI: the invisible-character guard for root files, .github and "
            ".claude would be off; check git safe.directory"
        )
    pytest.skip("git is not installed or this is not a git repository")


def invisible(text: str) -> list[tuple[int, str]]:
    """(line, 'U+XXXX (category)') of every forbidden character; the CR of a CRLF does not count."""
    found = []
    for number, line in enumerate(text.replace("\r\n", "\n").split("\n"), start=1):
        for character in line:
            if character not in ALLOWED and unicodedata.category(character) in FORBIDDEN:
                found.append((number, f"U+{ord(character):04X} ({unicodedata.category(character)})"))
    return found


def test_there_are_files_to_check() -> None:
    names = {p.relative_to(ROOT).as_posix() for p in files()}
    assert "src/backtest_agent/coded/static.py" in names
    assert "docs/ROADMAP.md" in names
    assert "strategies/sma_crossover.yaml" in names


@pytest.mark.parametrize("path", files(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_invisible_character_in(path: Path) -> None:
    assert invisible(path.read_text(encoding="utf-8")) == []


def check_listing(files: list[Path], environ: Mapping[str, str]) -> None:
    """An empty list fails in CI and skips elsewhere; a list must include the root files and the workflows."""
    require_tracked_files(files, environ)
    names = {p.relative_to(ROOT).as_posix() for p in files}
    assert {"README.md", "CLAUDE.md", "pyproject.toml", "CHANGELOG.md"} <= names
    assert any(name.startswith(".github/") for name in names)


def test_the_tracked_files_include_the_root_and_the_workflows() -> None:
    check_listing(tracked_files(), os.environ)


@pytest.mark.parametrize("path", tracked_files(), ids=lambda p: "tracked:" + p.relative_to(ROOT).as_posix())
def test_no_invisible_character_in_tracked(path: Path) -> None:
    assert invisible(path.read_text(encoding="utf-8")) == []


def test_the_detector_finds_each_category_and_ignores_the_allowed_ones() -> None:
    text = "a\u202eb\nc\u200bd\r\ne\u2028f\tg\u2029h\x07i\x85j\rk\ufeffl"
    assert invisible(text) == [
        (1, "U+202E (Cf)"),
        (2, "U+200B (Cf)"),
        (3, "U+2028 (Zl)"),
        (3, "U+2029 (Zp)"),
        (3, "U+0007 (Cc)"),
        (3, "U+0085 (Cc)"),
        (3, "U+000D (Cc)"),
        (3, "U+FEFF (Cf)"),
    ]
    assert invisible("plain\r\ncafé   中文\tx\n") == []  # CRLF, accents, NBSP (Zs), CJK, tab


# --- tracked_files() never fails at collection time ---


def test_tracked_files_is_empty_when_git_is_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert tracked_files() == []


def test_tracked_files_is_empty_when_git_cannot_be_started(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args, **kwargs):
        raise OSError("no git")

    monkeypatch.setattr(subprocess, "run", refuse)
    assert tracked_files() == []


def test_tracked_files_is_empty_when_this_is_not_a_git_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(command, **kwargs):
        # git failed (128) although stdout has a name: a failed command's output is never used
        return subprocess.CompletedProcess(
            command, 128, stdout="README.md" + chr(0), stderr="fatal: not a git repository"
        )

    monkeypatch.setattr(subprocess, "run", failing)
    assert tracked_files() == []


# --- an empty list of tracked files is a failure in CI and a skip elsewhere ---

CI_MESSAGE = (
    "git did not list the tracked files in CI: the invisible-character guard for root files, .github and .claude "
    "would be off; check git safe.directory"
)
SKIP_MESSAGE = "git is not installed or this is not a git repository"
LISTING = [
    ROOT / name for name in ("README.md", "CLAUDE.md", "pyproject.toml", "CHANGELOG.md", ".github/workflows/ci.yml")
]


def outcome(files: list[Path], environ: dict[str, str]) -> tuple[str, str]:
    """What ``check_listing`` does: ``("fail", message)``, ``("skip", message)`` or ``("ok", "")``.

    A skipped test is not a failed one, so a test that only expects an exception could not tell a skip from a failure.
    """
    try:
        check_listing(files, environ)
    except pytest.fail.Exception as error:
        return "fail", str(error)
    except pytest.skip.Exception as error:
        return "skip", str(error)
    return "ok", ""


@pytest.mark.parametrize("environ", [{"CI": "true"}, {"CI": "1"}, {"CI": "false", "OTHER": "x"}])
def test_an_empty_list_fails_when_ci_is_set(environ: dict[str, str]) -> None:
    assert outcome([], environ) == ("fail", CI_MESSAGE)


@pytest.mark.parametrize("environ", [{}, {"CI": ""}, {"OTHER": "x"}])
def test_an_empty_list_skips_when_ci_is_unset_or_empty(environ: dict[str, str]) -> None:
    assert outcome([], environ) == ("skip", SKIP_MESSAGE)


@pytest.mark.parametrize("environ", [{}, {"CI": "true"}, {"CI": ""}])
def test_a_complete_list_is_accepted_whatever_the_environment(environ: dict[str, str]) -> None:
    assert outcome(LISTING, environ) == ("ok", "")


def test_a_list_without_the_workflows_or_the_root_files_is_an_assertion_error() -> None:
    with pytest.raises(AssertionError):
        check_listing(LISTING[:-1], {})  # no .github file
    with pytest.raises(AssertionError):
        check_listing(LISTING[1:], {"CI": "true"})  # no README.md


def run_root_test() -> tuple[str, str]:
    """Call the test of the root files and report what it did, so a skip cannot pass for a failure."""
    try:
        test_the_tracked_files_include_the_root_and_the_workflows()
    except pytest.fail.Exception as error:
        return "fail", str(error)
    except pytest.skip.Exception as error:
        return "skip", str(error)
    return "ok", ""


def test_the_listing_test_reads_the_real_environment_and_the_real_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(globals(), "tracked_files", lambda: [])  # as if git listed nothing
    monkeypatch.setenv("CI", "1")
    assert run_root_test() == ("fail", CI_MESSAGE)
    monkeypatch.setenv("CI", "")
    assert run_root_test() == ("skip", SKIP_MESSAGE)
    monkeypatch.delenv("CI")
    assert run_root_test() == ("skip", SKIP_MESSAGE)
