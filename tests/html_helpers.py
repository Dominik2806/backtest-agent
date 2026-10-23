"""Reading the HTML report in tests: strict XML parsing, table cells and the outline. Computes no expected value."""

import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

FORBIDDEN_TAGS = {"script", "link", "img", "iframe", "object", "embed", "base", "form"}


def parse(html: str) -> ET.Element:
    """The document as an element tree; raises ``ET.ParseError`` unless it is well-formed XML (a doctype is fine)."""
    return ET.fromstring(html)


def text_of(element: ET.Element) -> str:
    return "".join(element.itertext())


def tables(root: ET.Element) -> list[ET.Element]:
    return list(root.iter("table"))


def table_headers(table: ET.Element) -> list[str]:
    return [text_of(th) for th in table.find("thead").iter("th")]  # type: ignore[union-attr]


def table_body(table: ET.Element) -> list[list[ET.Element]]:
    return [list(tr) for tr in table.find("tbody")]  # type: ignore[union-attr]


def cell_texts(root: ET.Element) -> list[str]:
    """Every header cell and body cell of every table, in document order."""
    out: list[str] = []
    for table in tables(root):
        out += table_headers(table)
        for row in table_body(table):
            out += [text_of(cell) for cell in row]
    return out


def outline(root: ET.Element) -> list[str]:
    """Headings (level, id), tables (headers, kind of the first body cell, scroll container) and figures, in order."""
    lines: list[str] = []
    parents = {child: parent for parent in root.iter() for child in parent}
    level = 1
    for element in root.iter():
        if re.fullmatch(r"h[1-6]", element.tag):
            level = int(element.tag[1])
            lines.append(f"{'  ' * (level - 1)}h{level} #{element.get('id')}")
        elif element.tag == "table":
            wrapper = parents[element]
            region = "region" if wrapper.get("role") == "region" and wrapper.get("tabindex") == "0" else "bare"
            first = table_body(element)[0][0] if table_body(element) else None
            kind = (
                "none"
                if first is None
                else f"{first.tag}{'(scope=' + first.get('scope') + ')' if first.get('scope') else ''}"
            )
            lines.append(
                f"{'  ' * level}table[{region}, {element.get('class') or '-'}] {' | '.join(table_headers(element))}"
                f" -- first body cell: {kind}"
            )
        elif element.tag == "figure":
            svg = element.find("svg")
            parts = [child.tag for child in svg if child.tag in ("title", "desc")]  # type: ignore[union-attr]
            caption = "figcaption" if element.find("figcaption") is not None else "no caption"
            lines.append(f"{'  ' * level}figure svg({', '.join(parts)}) {caption}")
    return lines


class Structure(HTMLParser):
    """A second, independent reading with the real HTML tokenizer: tags, attributes and the text of ``<style>``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.attrs: list[tuple[str, str, str | None]] = []
        self.css = ""
        self._in_style = False

    def handle_starttag(self, tag, attrs) -> None:
        self.tags.append(tag)
        self.attrs += [(tag, key, value) for key, value in attrs]
        self._in_style = tag == "style"

    def handle_startendtag(self, tag, attrs) -> None:
        self.handle_starttag(tag, attrs)
        self._in_style = False

    def handle_endtag(self, tag) -> None:
        self._in_style = False

    def handle_data(self, data) -> None:
        if self._in_style:
            self.css += data


def structure(html: str) -> Structure:
    parser = Structure()
    parser.feed(html)
    parser.close()
    return parser


def markdown_tables(markdown: str) -> list[list[list[str]]]:
    """Each table as a list of rows of unescaped cells; the separator line is dropped."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("|"):
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return [
        [
            [re.sub(r"\\(.)", r"\1", cell.strip()) for cell in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
            for index, line in enumerate(rows)
            if index != 1
        ]
        for rows in blocks
    ]
