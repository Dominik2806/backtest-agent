"""The HTML report: a pure function of a ``ReportModel`` (docs/report.md, "HTML").

One self-contained file: inline CSS, inline SVG (without the XML namespace, so no ``http`` text at all), no script, no
external font, stylesheet, image or link. Same sections in the same order as the Markdown report; the renderer adds no
content and decides no number format.

The markup is built with two helpers, ``tag`` and ``block``, and nothing else: a plain ``str`` child or attribute value
is always escaped, and only a ``Markup`` (made by the helpers, or wrapped once for the constant CSS and the SVG text of
``charts.py``) passes through. Joining a ``Markup`` with a ``str`` gives a plain ``str`` again, so a text cannot become
markup by accident. The output is written XML-compatible (closed tags, quoted attributes, only the five predefined
entities and numeric ones), so ``xml.etree`` is a strict well-formedness test.
"""

import re

from backtest_agent.reporting.charts import line_chart_svg
from backtest_agent.reporting.model import DataRun, HeatmapSection, LineChart, ReportModel, Table

# Monthly returns are shaded by the *unrounded* return, symmetric around 0: four steps of 2.5 percent up to a cap of 10
# percent (returns beyond the cap use the darkest step). Below the first break a cell stays neutral. The number is
# always printed in the cell, so the shade is a help and not the information.
SHADE_BREAKS = (0.0125, 0.0375, 0.0625, 0.0875)
OUTSIDE_CLASS = "bt-out"

# Light tokens on :root, dark tokens in the media query. The heatmap colours (blue positive, orange negative) have no
# relation to the series colours of the charts. The page classes all start with "bt-" and differ from the class names
# inside the inline SVGs (their style rules are global to the page). A plain string: no placeholder, no external
# reference.
CSS = (
    ":root{color-scheme:light dark;--bg:#fcfcfb;--text:#0b0b0b;--muted:#52514e;--rule:#e3e2de;--head:#f1f0ec;"
    "--pos-1:#e6effa;--pos-2:#c5dcf6;--pos-3:#9cc3ef;--pos-4:#6aa6e6;"
    "--neg-1:#fdece4;--neg-2:#fad3c0;--neg-3:#f6b394;--neg-4:#f08d5e}\n"
    "@media (prefers-color-scheme: dark){\n"
    ":root{--bg:#1a1a19;--text:#f0efec;--muted:#c3c2b7;--rule:#3a3a37;"
    "--head:#262624;"
    "--pos-1:#1c2a3d;--pos-2:#1f3f66;--pos-3:#245890;--pos-4:#2a68a8;"
    "--neg-1:#3a2418;--neg-2:#5c3320;--neg-3:#8a4524;--neg-4:#a8501f}\n}\n"
    "*,*::before,*::after{box-sizing:border-box}\n"
    "html{-webkit-text-size-adjust:100%}\n"
    'body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,'
    "sans-serif}\n"
    "main{max-width:64rem;margin:0 auto;padding:16px}\n"
    "h1{font-size:1.6rem;line-height:1.25;margin:0 0 .5rem;overflow-wrap:anywhere}\n"
    "h2{font-size:1.25rem;margin:2rem 0 .5rem;padding-top:.5rem;border-top:1px solid var(--rule)}\n"
    "h3{font-size:1.05rem;margin:1.25rem 0 .5rem}\n"
    "ul{padding-left:1.25rem}\n"
    "li{margin:.2rem 0;overflow-wrap:anywhere}\n"
    "p{overflow-wrap:anywhere}\n"
    "code{font:.9em ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;overflow-wrap:anywhere;word-break:break-all}\n"
    ".bt-table-wrap{overflow-x:auto;max-width:100%;margin:.5rem 0 1rem;border:1px solid var(--rule)}\n"
    ".bt-table-wrap:focus-visible{outline:2px solid var(--muted)}\n"
    "table{border-collapse:collapse;width:100%;font-size:.9rem;font-variant-numeric:tabular-nums}\n"
    "th,td{padding:.35rem .6rem;text-align:left;vertical-align:top;border-bottom:1px solid var(--rule)}\n"
    "thead th{background:var(--head)}\n"
    "tbody th{font-weight:600}\n"
    ".bt-heat td{text-align:right;white-space:nowrap}\n"
    ".bt-heat td.bt-out{color:var(--muted)}\n"
    ".bt-pos-1{background:var(--pos-1)}.bt-pos-2{background:var(--pos-2)}"
    ".bt-pos-3{background:var(--pos-3)}.bt-pos-4{background:var(--pos-4)}\n"
    ".bt-neg-1{background:var(--neg-1)}.bt-neg-2{background:var(--neg-2)}"
    ".bt-neg-3{background:var(--neg-3)}.bt-neg-4{background:var(--neg-4)}\n"
    "figure{margin:.5rem 0 1rem}\n"
    "figure svg{display:block;max-width:100%;height:auto}\n"
    "figcaption{color:var(--muted);font-size:.9rem;margin-top:.25rem}\n"
)

_ESCAPES = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})
_NAME = re.compile(r"[a-z][a-z0-9-]*")
_VOID = frozenset({"meta"})


class Markup(str):
    """Text that is already markup: made by ``tag`` and ``block``, and by the renderer for its two trusted constants."""

    __slots__ = ()


def esc(value: str) -> str:
    """Text for an element or an attribute value: ``& < > " '`` become ``&amp; &lt; &gt; &quot; &#39;``."""
    return value.translate(_ESCAPES)


def _open(element: str, attrs: dict[str, str]) -> str:
    if not _NAME.fullmatch(element):
        raise ValueError(f"{element!r} is not a valid tag name")
    parts = [element]
    for key, value in attrs.items():
        attr = key.rstrip("_").replace("_", "-")  # class_ -> class, aria_labelledby -> aria-labelledby
        if not _NAME.fullmatch(attr):
            raise ValueError(f"{key!r} is not a valid attribute name")
        if not isinstance(value, str):
            raise TypeError(f"attribute {attr!r}: expected a string, got {value!r}")
        parts.append(f'{attr}="{esc(value)}"')
    return " ".join(parts)


def _children(children: tuple[str, ...]) -> list[str]:
    for child in children:
        if not isinstance(child, str):
            raise TypeError(f"a child of an element must be a string or Markup, got {child!r}")
    return [child if isinstance(child, Markup) else esc(child) for child in children]


def tag(element: str, /, *children: str, **attrs: str) -> Markup:
    """``<name attrs>children</name>`` on one line; plain ``str`` children and attribute values are escaped."""
    opening = _open(element, attrs)
    if element in _VOID:
        if children:
            raise ValueError(f"<{element}> cannot have children")
        return Markup(f"<{opening}/>")
    return Markup(f"<{opening}>{''.join(_children(children))}</{element}>")


def block(element: str, /, *children: str, **attrs: str) -> Markup:
    """Like ``tag``, with the opening tag, every child and the closing tag on their own lines."""
    inner = "\n".join(_children(children))
    return Markup(f"<{_open(element, attrs)}>\n{inner}\n</{element}>")


# --- parts ------------------------------------------------------------------------------------------------------------


def slug(heading: str) -> str:
    """An id from a fixed heading text: lower case, runs of other characters become one ``-``."""
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")


def shade_class(value: float) -> str | None:
    """The CSS class of a monthly return: ``bt-pos-1`` to ``bt-pos-4``, ``bt-neg-1`` to ``bt-neg-4``, or ``None``.

    Uses the unrounded value: the level is the number of ``SHADE_BREAKS`` that ``abs(value)`` reaches (a break belongs
    to the darker step), so a cell that prints 1.25% can still be neutral.
    """
    level = sum(abs(value) >= edge for edge in SHADE_BREAKS)
    if level == 0:
        return None
    return f"bt-{'pos' if value > 0 else 'neg'}-{level}"


def _heading(level: int, heading: str) -> Markup:
    return tag(f"h{level}", heading, id=slug(heading))


def _wrap(table: Markup, heading: str) -> Markup:
    return block("div", table, class_="bt-table-wrap", role="region", tabindex="0", aria_labelledby=slug(heading))


def _table(table: Table, heading: str, *, row_headers: bool = True) -> Markup:
    head = block("thead", tag("tr", *(tag("th", h, scope="col") for h in table.headers)))
    rows = [
        tag(
            "tr",
            *(
                tag("th", cell, scope="row") if row_headers and index == 0 else tag("td", cell)
                for index, cell in enumerate(row)
            ),
        )
        for row in table.rows
    ]
    return _wrap(block("table", head, block("tbody", *rows)), heading)


def _list(items: tuple[str, ...]) -> Markup:
    return block("ul", *(tag("li", item) for item in items))


def _item(label: str, *value: str) -> Markup:
    return tag("li", tag("strong", label + ":"), " ", *value)


def _data_run(run: DataRun) -> list[Markup]:
    out = [
        _heading(3, run.label),
        block(
            "ul",
            _item("Symbols", run.symbols),
            _item("Data hash", tag("code", run.data_hash)),
            _item("Validation", run.summary),
        ),
    ]
    if not run.issues:
        return [*out, tag("p", "No validation warnings or infos.")]
    table = Table(
        ("Severity", "Code", "Symbol", "Field", "Rows", "First dates", "Message"),
        tuple((i.severity, i.code, i.symbol, i.field, i.count, i.first_dates, i.message) for i in run.issues),
    )
    return [*out, _table(table, run.label, row_headers=False)]


def _figure(chart: LineChart, caption: str) -> Markup:
    svg = Markup(line_chart_svg(chart, standalone=False).rstrip("\n"))
    return block("figure", svg, tag("figcaption", caption))


def _heatmap(heatmap: HeatmapSection, heading: str) -> list[Markup]:
    head = block("thead", tag("tr", *(tag("th", h, scope="col") for h in ("Year", *heatmap.months))))
    rows = []
    for year, row in zip(heatmap.years, heatmap.rows, strict=True):
        cells = []
        for cell in row:
            css = OUTSIDE_CLASS if cell.value is None else shade_class(cell.value)
            cells.append(tag("td", cell.text, class_=css) if css else tag("td", cell.text))
        rows.append(tag("tr", tag("th", str(year), scope="row"), *cells))
    table = block("table", head, block("tbody", *rows), class_="bt-heat")
    return [_wrap(table, heading), tag("p", heatmap.footnote)]


def _section(heading: str, *content: Markup) -> Markup:
    return block("section", _heading(2, heading), *content, aria_labelledby=slug(heading))


def render_html(model: ReportModel) -> str:
    """The whole report as one HTML document with ``\\n`` line ends."""
    header, data, charts = model.header, model.data, model.charts
    title = ("Backtest report: ", header.strategy_name)

    top = block(
        "header",
        tag("h1", *title, id="report-title"),
        block(
            "ul",
            _item("Run id", tag("code", header.run_id)),
            _item("Generated at", header.generated_at),
            _item("Period", header.period),
            _item("Bars", header.bars),
            _item("Universe", header.universe),
            _item("Benchmark", header.benchmark),
            _item("Trials", model.trials),
        ),
    )

    sections = [
        _section("Spec summary", _table(model.spec, "Spec summary")),
        _section(
            "Data",
            *(item for run in data.runs for item in _data_run(run)),
            _heading(3, "Warm-up"),
            _table(data.warmup, "Warm-up"),
            _table(data.warmup_symbols, "Warm-up"),
            tag("p", data.benchmark_warmup),
        ),
    ]

    if model.flags:
        flags = Table(
            ("Run", "Flag", "Engine message", "What it means"),
            tuple((f.run, f.code, f.message, f.explanation) for f in model.flags),
        )
        sections.append(_section("Risk flags", _table(flags, "Risk flags", row_headers=False)))
    else:
        sections.append(_section("Risk flags", tag("p", "No risk flags.")))

    sections += [
        _section(
            "Metrics",
            _heading(3, "Assumptions"),
            _table(model.metrics.assumptions, "Assumptions"),
            _heading(3, "Performance"),
            _table(model.metrics.performance, "Performance"),
            _heading(3, "Relative to the benchmark"),
            _table(model.metrics.relative, "Relative to the benchmark"),
        ),
        _section(
            "Benchmark alignment",
            _table(model.alignment.table, "Benchmark alignment"),
            tag("p", model.alignment.base_rule),
            *([_list(model.alignment.notes)] if model.alignment.notes else []),
        ),
        _section("Costs", _table(model.costs.table, "Costs"), _list(model.costs.notes)),
        _section(
            "Charts",
            _heading(3, "Equity"),
            _figure(charts.equity, charts.equity_caption),
            _heading(3, "Drawdown"),
            _figure(charts.drawdown, charts.drawdown_caption),
        ),
        _section("Monthly returns", *_heatmap(model.heatmap, "Monthly returns")),
        _section(
            "Trade statistics",
            _table(model.trades.summary, "Trade statistics"),
            _table(model.trades.per_symbol, "Trade statistics"),
            _list(model.trades.notes),
        ),
        _section(
            "Assumptions and caveats",
            _heading(3, "Fixed caveats"),
            block("ul", *(tag("li", tag("strong", c.title + "."), " ", c.text) for c in model.fixed_caveats)),
            _heading(3, "This run"),
            _list(model.run_caveats) if model.run_caveats else tag("p", "No run-specific caveats."),
        ),
    ]

    head = block(
        "head",
        tag("meta", charset="utf-8"),
        tag("meta", name="viewport", content="width=device-width, initial-scale=1"),
        tag("meta", name="color-scheme", content="light dark"),
        tag("title", *title),
        tag("style", Markup("\n" + CSS)),
    )
    document = block("html", head, block("body", block("main", top, *sections)), lang="en")
    return "<!DOCTYPE html>\n" + document + "\n"
