"""No file of ours contains an invisible character: Unicode categories Cc, Cf, Zl and Zp (docs/coded-signals.md).

The same characters are refused in a brief and in the source of a coded signal, because they hide text from a
reader. A test that needs one writes it as an escape (backslash, u and four hex digits) or with chr(). Only a line
break, a tab and the CR of a CRLF are allowed.
"""

import shutil
import subprocess
import unicodedata
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
    """Every text file that git tracks (root files, .github, .claude, ...); empty if git is not installed."""
    if shutil.which("git") is None:
        return []
    done = subprocess.run(
        ["git", "-c", "core.quotepath=off", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    names = [name for name in done.stdout.split(chr(0)) if name]
    return sorted(p for p in (ROOT / name for name in names) if p.suffix in TRACKED_SUFFIXES and p.is_file())


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


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_the_tracked_files_include_the_root_and_the_workflows() -> None:
    names = {p.relative_to(ROOT).as_posix() for p in tracked_files()}
    assert {"README.md", "CLAUDE.md", "pyproject.toml", "CHANGELOG.md"} <= names
    assert any(name.startswith(".github/") for name in names)


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
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
