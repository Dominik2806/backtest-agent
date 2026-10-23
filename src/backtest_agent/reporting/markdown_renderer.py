"""The Markdown report: a pure function of a ``ReportModel`` (docs/report.md, "Layout").

The renderer adds no content and decides no number format; it lays the model out and escapes every text for Markdown,
so a name, a symbol or a validation message from the spec or the data cannot break a table or inject markup. The charts
are linked as separate SVG files by the relative paths of the model (``equity.svg``, ``drawdown.svg``).
"""

import re

from backtest_agent.reporting.model import DataRun, HeatmapSection, ReportModel, Table

_SPECIAL = re.compile(r"([\\|`*<>\[\]&])")


def md_escape(value: str) -> str:
    """Text for a Markdown line or table cell: the characters that give structure or markup get a backslash.

    ``\\ | ` * < > [ ] &`` are escaped; line breaks become spaces (a table row is one line).
    """
    return _SPECIAL.sub(r"\\\1", " ".join(value.split()))


def md_code(value: str) -> str:
    """Inline code for a value such as a hash or a run id; uses a longer fence if the value contains a backtick."""
    fence = "`" * (max((len(m) for m in re.findall(r"`+", value)), default=0) + 1)
    pad = " " if value.startswith("`") or value.endswith("`") else ""
    return f"{fence}{pad}{' '.join(value.split())}{pad}{fence}"


def _table(table: Table) -> list[str]:
    lines = ["| " + " | ".join(md_escape(h) for h in table.headers) + " |"]
    lines.append("|" + "|".join(" --- " for _ in table.headers) + "|")
    lines.extend("| " + " | ".join(md_escape(cell) for cell in row) + " |" for row in table.rows)
    return lines


def _bullets(items: tuple[str, ...]) -> list[str]:
    return [f"- {md_escape(item)}" for item in items]


def _data_run(run: DataRun) -> list[str]:
    lines = [
        f"### {md_escape(run.label)}",
        "",
        f"- **Symbols:** {md_escape(run.symbols)}",
        f"- **Data hash:** {md_code(run.data_hash)}",
        f"- **Validation:** {md_escape(run.summary)}",
        "",
    ]
    if not run.issues:
        return [*lines, "No validation warnings or infos.", ""]
    table = Table(
        ("Severity", "Code", "Symbol", "Field", "Rows", "First dates", "Message"),
        tuple((i.severity, i.code, i.symbol, i.field, i.count, i.first_dates, i.message) for i in run.issues),
    )
    return [*lines, *_table(table), ""]


def _heatmap(heatmap: HeatmapSection) -> list[str]:
    table = Table(
        ("Year", *heatmap.months),
        tuple((str(year), *(cell.text for cell in row)) for year, row in zip(heatmap.years, heatmap.rows, strict=True)),
    )
    return [*_table(table), "", md_escape(heatmap.footnote), ""]


def render_markdown(model: ReportModel) -> str:
    """The whole report as Markdown text with ``\\n`` line ends."""
    header, data, charts = model.header, model.data, model.charts
    out: list[str] = [
        f"# Backtest report: {md_escape(header.strategy_name)}",
        "",
        f"- **Run id:** {md_code(header.run_id)}",
        f"- **Generated at:** {md_escape(header.generated_at)}",
        f"- **Period:** {md_escape(header.period)}",
        f"- **Bars:** {md_escape(header.bars)}",
        f"- **Universe:** {md_escape(header.universe)}",
        f"- **Benchmark:** {md_escape(header.benchmark)}",
        "",
        "## Spec summary",
        "",
        *_table(model.spec),
        "",
        "## Data",
        "",
    ]
    for run in data.runs:
        out += _data_run(run)
    out += [
        "### Warm-up",
        "",
        *_table(data.warmup),
        "",
        *_table(data.warmup_symbols),
        "",
        md_escape(data.benchmark_warmup),
        "",
    ]

    out += ["## Risk flags", ""]
    if model.flags:
        flags = Table(
            ("Run", "Flag", "Engine message", "What it means"),
            tuple((f.run, f.code, f.message, f.explanation) for f in model.flags),
        )
        out += [*_table(flags), ""]
    else:
        out += ["No risk flags.", ""]

    out += [
        "## Metrics",
        "",
        "### Assumptions",
        "",
        *_table(model.metrics.assumptions),
        "",
        "### Performance",
        "",
        *_table(model.metrics.performance),
        "",
        "### Relative to the benchmark",
        "",
        *_table(model.metrics.relative),
        "",
        "## Benchmark alignment",
        "",
        *_table(model.alignment.table),
        "",
        md_escape(model.alignment.base_rule),
        "",
    ]
    if model.alignment.notes:
        out += [*_bullets(model.alignment.notes), ""]

    out += ["## Costs", "", *_table(model.costs.table), "", *_bullets(model.costs.notes), ""]

    out += [
        "## Charts",
        "",
        "### Equity",
        "",
        f"![{md_escape(charts.equity.description)}]({charts.equity_file})",
        "",
        md_escape(charts.equity_caption),
        "",
        "### Drawdown",
        "",
        f"![{md_escape(charts.drawdown.description)}]({charts.drawdown_file})",
        "",
        md_escape(charts.drawdown_caption),
        "",
        "## Monthly returns",
        "",
        *_heatmap(model.heatmap),
        "## Trade statistics",
        "",
        *_table(model.trades.summary),
        "",
        *_table(model.trades.per_symbol),
        "",
        *_bullets(model.trades.notes),
        "",
        "## Assumptions and caveats",
        "",
        "### Fixed caveats",
        "",
        *(f"- **{md_escape(c.title)}.** {md_escape(c.text)}" for c in model.fixed_caveats),
        "",
        "### This run",
        "",
        *(_bullets(model.run_caveats) or ["No run-specific caveats."]),
        "",
    ]
    return "\n".join(out)
