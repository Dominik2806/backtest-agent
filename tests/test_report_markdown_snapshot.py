"""Snapshot of the Markdown report of the R3b run (docs/metrics.md R3b, docs/engine.md H23) with a fixed time.

The snapshot ``tests/snapshots/report.md`` protects the structure: headings in order, table headers, the caveats. It was
generated once and read through by hand; the numbers in it are those of the hand-calculated fixtures (for example total
return 17.13% = 0.17128, costs 200.00, cost share 63.09% = 292.82 / 464.1). Numeric formats are tested with literals in
test_report_format.py and test_report_model.py.

To regenerate it after a deliberate change, run from the repository root::

    uv run python tests/test_report_markdown_snapshot.py

and review the diff of ``tests/snapshots/report.md`` line by line before committing.
"""

import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from backtest_agent.reporting.markdown_renderer import render_markdown
from backtest_agent.reporting.model import build_report_model

SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "report.md"
WHEN = datetime(2026, 1, 15, 10, 30, 5, tzinfo=UTC)
RUN_ID = "20260115T103005Z-buy-and-hold-a-a85a59ee"


def current() -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from report_helpers import equal_start

    return render_markdown(build_report_model(equal_start(), run_id=RUN_ID, generated_at=WHEN))


def test_the_markdown_matches_the_snapshot() -> None:
    expected = SNAPSHOT.read_bytes().decode("utf-8").replace("\r\n", "\n")  # a git checkout may have changed the ends
    assert current() == expected


def test_the_snapshot_has_the_caveats_and_no_placeholder_text() -> None:
    text = SNAPSHOT.read_text(encoding="utf-8")
    assert "## Assumptions and caveats" in text and "not investment advice" in text
    assert not re.search(r"\b(nan|None|inf)\b|\{\{|\}\}", text)


if __name__ == "__main__":  # regenerate the snapshot
    SNAPSHOT.parent.mkdir(exist_ok=True)
    with SNAPSHOT.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(current())
    print(f"wrote {SNAPSHOT}")
