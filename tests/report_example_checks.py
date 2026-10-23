"""Checks shared by the offline example reports (test_report_examples.py) and the live ones (test_report_network.py)."""

import re
from datetime import UTC, datetime
from pathlib import Path

from backtest_agent.metrics import Evaluation
from backtest_agent.reporting import build_report_model, write_report
from backtest_agent.run_id import make_run_id
from html_helpers import FORBIDDEN_TAGS, cell_texts, markdown_tables, parse, structure, text_of

WHEN = datetime(2026, 1, 15, 10, 30, 5, tzinfo=UTC)
FILES = ("drawdown.svg", "equity.svg", "report.html", "report.md")


def check_written_report(evaluation: Evaluation, reports_dir: Path) -> Path:
    """Write the report of ``evaluation`` and check the four files. Returns the run folder."""
    paths = write_report(evaluation, reports_dir, generated_at=WHEN)
    folder = paths.directory
    assert folder.name == paths.run_id == make_run_id(evaluation, WHEN)
    assert sorted(p.name for p in folder.iterdir()) == list(FILES)
    for name in FILES:
        assert (folder / name).stat().st_size > 0, name

    markdown = paths.markdown.read_text(encoding="utf-8")
    html = paths.html.read_text(encoding="utf-8")

    # The Markdown links resolve to written files; the HTML needs no other file at all.
    links = re.findall(r"\]\(([^)]+)\)", markdown)
    assert links == ["equity.svg", "drawdown.svg"]
    assert all((folder / link).is_file() for link in links)
    root = parse(html)  # strict XML
    found = structure(html)
    assert not set(found.tags) & FORBIDDEN_TAGS and "http" not in html
    assert all(value.startswith("#") for _, key, value in found.attrs if key in ("href", "src"))
    parse((folder / "equity.svg").read_text(encoding="utf-8"))
    parse((folder / "drawdown.svg").read_text(encoding="utf-8"))

    # The caveats and both data hashes are in the HTML (and in the Markdown).
    model = build_report_model(evaluation, run_id=paths.run_id, generated_at=WHEN)
    items = [" ".join(text_of(li).split()) for li in root.iter("li")]
    for caveat in model.fixed_caveats:
        assert f"{caveat.title}. {caveat.text}" in items, caveat.title
    for data_hash in (evaluation.result.data_hash, evaluation.benchmark_result.data_hash):
        assert len(data_hash) == 64
        assert data_hash in cell_texts(root) + [text_of(code) for code in root.iter("code")]
        assert data_hash in markdown

    # The numbers of the HTML are those of the Markdown: every cell of every table, in order, from the same model.
    markdown_cells = [cell for table in markdown_tables(markdown) for row in table for cell in row]
    assert cell_texts(root) == markdown_cells
    return folder
