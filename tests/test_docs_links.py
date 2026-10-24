"""Every relative markdown link of the README and of docs/ resolves (CLAUDE.md, "Docs"). Offline.

External links (a scheme such as https: or mailto:) are not checked. Links inside code fences and inline code are
ignored. A ``#fragment`` must match a heading of the target file (GitHub's rule for the anchor of a heading).
"""

import re
from pathlib import Path
from urllib.parse import unquote

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FILES = sorted([REPO_ROOT / "README.md", *(REPO_ROOT / "docs").rglob("*.md")])
_FENCE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.DOTALL | re.MULTILINE)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_LINK = re.compile(r"\[[^\]\n]*\]\(\s*(<[^>\n]*>|[^)\s]*)(?:\s+\"[^\"]*\")?\s*\)")
_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$", re.MULTILINE)
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def _prose(text: str) -> str:
    return _INLINE_CODE.sub("", _FENCE.sub("", text))


def anchor_of(heading: str) -> str:
    """GitHub's anchor: lower case, markup and punctuation dropped (``-`` and ``_`` stay), spaces become dashes."""
    plain = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)
    plain = _INLINE_CODE.sub(lambda m: m.group(0).strip("`"), plain).replace("*", "")
    kept = re.sub(r"[^\w\- ]", "", plain.lower())
    return kept.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    found: dict[str, int] = {}
    result = set()
    for heading in _HEADING.findall(_FENCE.sub("", path.read_text(encoding="utf-8"))):
        base = anchor_of(heading)
        count = found.get(base, 0)
        found[base] = count + 1
        result.add(base if count == 0 else f"{base}-{count}")
    return result


def broken_links(path: Path, root: Path = REPO_ROOT) -> list[str]:
    problems = []
    for target in _LINK.findall(_prose(path.read_text(encoding="utf-8"))):
        target = target.strip("<>")
        if not target or _SCHEME.match(target):
            continue
        name, _, fragment = target.partition("#")
        destination = path if not name else (path.parent / unquote(name)).resolve()
        if not destination.exists():
            problems.append(f"{path.relative_to(root)}: {target} -> {name} does not exist")
        elif fragment and destination.suffix == ".md" and unquote(fragment) not in anchors(destination):
            problems.append(f"{path.relative_to(root)}: {target} -> no heading with the anchor #{fragment}")
    return problems


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_every_relative_link_resolves(path: Path) -> None:
    assert broken_links(path) == []


def test_the_checker_finds_a_broken_link_and_a_broken_anchor(tmp_path: Path) -> None:
    (tmp_path / "other.md").write_text("# Title\n\n## A `code` heading, with: punctuation\n", encoding="utf-8")
    page = tmp_path / "page.md"
    page.write_text(
        "[ok](other.md) [ok2](other.md#a-code-heading-with-punctuation) [bad](missing.md) "
        "[bad2](other.md#nope) [web](https://example.com/x) `[in code](missing2.md)`\n"
        "```\n[fenced](missing3.md)\n```\n",
        encoding="utf-8",
    )
    assert broken_links(page, tmp_path) == [
        "page.md: missing.md -> missing.md does not exist",
        "page.md: other.md#nope -> no heading with the anchor #nope",
    ]
