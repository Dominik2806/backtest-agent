"""Snapshot of the outline of the HTML report of the R3b run: headings with their ids, tables, figures.

The snapshot ``tests/snapshots/report_html_outline.txt`` protects the structure only (heading levels and ids, the
headers of each table, whether a table has row headers and a scroll container, the figures with title and description),
not the numbers and not the markup of the whole file. It was generated once and read through by hand.

To regenerate it after a deliberate change, run from the repository root::

    uv run python tests/test_report_html_outline.py

and review the diff of ``tests/snapshots/report_html_outline.txt`` line by line before committing.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "report_html_outline.txt"
WHEN = datetime(2026, 1, 15, 10, 30, 5, tzinfo=UTC)
RUN_ID = "20260115T103005Z-buy-and-hold-a-a85a59ee"


def current() -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from backtest_agent.reporting.html_renderer import render_html
    from backtest_agent.reporting.model import build_report_model
    from html_helpers import outline, parse
    from report_helpers import equal_start

    html = render_html(build_report_model(equal_start(), run_id=RUN_ID, generated_at=WHEN))
    return "\n".join(outline(parse(html))) + "\n"


def test_the_outline_matches_the_snapshot() -> None:
    expected = SNAPSHOT.read_bytes().decode("utf-8").replace("\r\n", "\n")  # a git checkout may have changed the ends
    assert current() == expected


def test_the_snapshot_lists_every_section_and_both_figures() -> None:
    lines = SNAPSHOT.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "h1 #report-title"
    assert sum(line.strip().startswith("h2 ") for line in lines) == 10
    assert sum(line.strip().startswith("figure ") for line in lines) == 2
    assert all("region" in line for line in lines if "table[" in line)


if __name__ == "__main__":  # regenerate the snapshot
    SNAPSHOT.parent.mkdir(exist_ok=True)
    with SNAPSHOT.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(current())
    print(f"wrote {SNAPSHOT}")
