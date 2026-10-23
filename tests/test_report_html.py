"""The HTML report: well-formedness, structure, escaping, no external reference, the heatmap shades and the contrast."""

import re
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from backtest_agent.data.validation import Severity, ValidationIssue, ValidationResult
from backtest_agent.reporting.html_renderer import (
    CSS,
    OUTSIDE_CLASS,
    SHADE_BREAKS,
    Markup,
    block,
    esc,
    render_html,
    shade_class,
    slug,
    tag,
)
from backtest_agent.reporting.markdown_renderer import render_markdown
from backtest_agent.reporting.model import HeatmapCell, HeatmapSection, build_report_model
from html_helpers import FORBIDDEN_TAGS, markdown_tables, parse, structure, table_body, table_headers, tables, text_of
from report_helpers import all_kinds, equal_start

WHEN = datetime(2026, 1, 15, 10, 30, 5, tzinfo=UTC)
RUN_ID = "20260115T103005Z-buy-and-hold-a-a85a59ee"
HOSTILE = "<script>alert(1)</script>"
OPEN, CLOSE = chr(123), chr(125)  # so that this file has no literal double brace (a template placeholder check)


def model_of(evaluation, run_id: str = RUN_ID):
    return build_report_model(evaluation, run_id=run_id, generated_at=WHEN)


def html_of(evaluation, run_id: str = RUN_ID) -> str:
    return render_html(model_of(evaluation, run_id))


@pytest.fixture(scope="module")
def kinds():
    return all_kinds()


def hostile_evaluation(name: str = HOSTILE, message: str = '"><img src=x onerror=alert(1)>', symbol: str = "'><b>x"):
    """The R3b evaluation with a hostile strategy name and a hostile validation issue (dataclasses.replace only)."""
    evaluation = equal_start()
    spec = evaluation.result.spec.model_copy(update={"name": name})
    issue = ValidationIssue(Severity.WARNING, "gap", symbol, "close", 2, (date(2024, 1, 3),), message)
    result = replace(evaluation.result, spec=spec, validation=ValidationResult((issue,)))
    return replace(evaluation, result=result)


# --- the helpers ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, escaped",
    [
        ("plain 12.34%", "plain 12.34%"),
        ("a & b", "a &amp; b"),
        ("<b>", "&lt;b&gt;"),
        ('say "hi"', "say &quot;hi&quot;"),
        ("it's", "it&#39;s"),
        ("&amp;", "&amp;amp;"),
        ("<a href='x'>&</a>", "&lt;a href=&#39;x&#39;&gt;&amp;&lt;/a&gt;"),
    ],
)
def test_esc(raw, escaped) -> None:
    assert esc(raw) == escaped


def test_a_str_child_is_escaped_and_a_markup_child_is_not() -> None:
    assert tag("p", "<b>x</b>") == "<p>&lt;b&gt;x&lt;/b&gt;</p>"
    assert tag("p", Markup("<b>x</b>")) == "<p><b>x</b></p>"
    assert tag("p", tag("b", "<i>")) == "<p><b>&lt;i&gt;</b></p>"
    assert block("ul", tag("li", "a"), "b&c") == "<ul>\n<li>a</li>\nb&amp;c\n</ul>"


def test_joining_a_markup_with_a_str_gives_a_str_that_is_escaped_again() -> None:
    joined = tag("b", "x") + "<i>"
    assert not isinstance(joined, Markup)
    assert tag("p", joined) == "<p>&lt;b&gt;x&lt;/b&gt;&lt;i&gt;</p>"


def test_attribute_values_are_escaped_and_names_are_converted() -> None:
    assert tag("td", "x", title="\"><x onclick='y'>") == '<td title="&quot;&gt;&lt;x onclick=&#39;y&#39;&gt;">x</td>'
    assert tag("td", "x", class_="a", aria_labelledby="b") == '<td class="a" aria-labelledby="b">x</td>'
    assert tag("meta", charset="utf-8") == '<meta charset="utf-8"/>'


@pytest.mark.parametrize(
    "call",
    [
        lambda: tag("P"),
        lambda: tag("p onclick=x"),
        lambda: tag("p><script"),
        lambda: tag(""),
        lambda: tag("p", **{"onclick=x": "y"}),
        lambda: tag("p", **{"Id": "y"}),
        lambda: tag("p", **{'a"b': "y"}),
        lambda: block("1p"),
    ],
)
def test_a_name_that_is_not_plain_is_rejected(call) -> None:
    with pytest.raises(ValueError, match="not a valid"):
        call()


@pytest.mark.parametrize(
    "call",
    [lambda: tag("p", id=1), lambda: tag("p", id=None), lambda: tag("p", hidden=True), lambda: tag("p", 5)],
)
def test_a_value_that_is_not_a_string_is_rejected(call) -> None:
    with pytest.raises(TypeError):
        call()


def test_a_void_element_has_no_children() -> None:
    with pytest.raises(ValueError, match="cannot have children"):
        tag("meta", "x")


def test_slug() -> None:
    assert slug("Relative to the benchmark") == "relative-to-the-benchmark"
    assert slug("Warm-up") == "warm-up"
    assert slug("Assumptions and caveats") == "assumptions-and-caveats"


# --- well-formed, and the same report as the Markdown -----------------------------------------------------------------


def test_every_kind_of_run_is_well_formed_xml(kinds) -> None:
    for name, evaluation in kinds.items():
        html = html_of(evaluation)
        assert html.startswith("<!DOCTYPE html>\n"), name  # xml.etree accepts this line as it is
        assert parse(html).tag == "html", name


def markdown_headings(markdown: str) -> list[str]:
    return [line for line in markdown.splitlines() if re.match(r"#{1,6} ", line)]


def test_the_headings_are_those_of_the_markdown_report_in_the_same_order(kinds) -> None:
    for name, evaluation in kinds.items():
        model = model_of(evaluation)
        root = parse(render_html(model))
        found = [
            "#" * int(element.tag[1]) + " " + text_of(element)
            for element in root.iter()
            if re.fullmatch(r"h[1-6]", element.tag)
        ]
        assert found == markdown_headings(render_markdown(model)), name


def test_the_headings_never_skip_a_level_and_have_unique_ids(kinds) -> None:
    for name, evaluation in kinds.items():
        root = parse(html_of(evaluation))
        headings = [e for e in root.iter() if re.fullmatch(r"h[1-6]", e.tag)]
        levels = [int(e.tag[1]) for e in headings]
        assert levels[0] == 1 and levels.count(1) == 1, name
        assert all(b - a <= 1 for a, b in zip(levels, levels[1:], strict=False)), name
        ids = [e.get("id") for e in headings]
        assert all(ids) and len(set(ids)) == len(ids), name


def test_the_tables_have_the_headers_and_the_cells_of_the_markdown_tables(kinds) -> None:
    for name, evaluation in kinds.items():
        model = model_of(evaluation)
        root = parse(render_html(model))
        expected = markdown_tables(render_markdown(model))
        assert [table_headers(t) for t in tables(root)] == [rows[0] for rows in expected], name
        for table, rows in zip(tables(root), expected, strict=True):
            body = [[text_of(cell) for cell in row] for row in table_body(table)]
            assert body == rows[1:], name


def test_the_header_cells_have_a_scope_and_label_columns_are_row_headers(kinds) -> None:
    for name, evaluation in kinds.items():
        root = parse(html_of(evaluation))
        for table in tables(root):
            head = table.find("thead")
            assert all(th.get("scope") == "col" for th in head.iter("th")), name
            first = table_headers(table)[0]
            for row in table_body(table):
                if first in ("Severity", "Run"):  # the issue and the flag table have no row header
                    assert {cell.tag for cell in row} == {"td"}, (name, first)
                else:
                    assert row[0].tag == "th" and row[0].get("scope") == "row", (name, first)
                    assert {cell.tag for cell in row[1:]} == {"td"}, (name, first)


def test_every_table_scrolls_inside_its_own_container(kinds) -> None:
    for name, evaluation in kinds.items():
        root = parse(html_of(evaluation))
        parents = {child: parent for parent in root.iter() for child in parent}
        ids = {e.get("id") for e in root.iter() if e.get("id")}
        for table in tables(root):
            wrapper = parents[table]
            assert wrapper.tag == "div" and wrapper.get("class") == "bt-table-wrap", name
            assert wrapper.get("role") == "region" and wrapper.get("tabindex") == "0", name
            assert wrapper.get("aria-labelledby") in ids, name


def test_the_fixed_caveats_are_in_every_kind_of_run(kinds) -> None:
    for name, evaluation in kinds.items():
        model = model_of(evaluation)
        root = parse(render_html(model))
        items = [" ".join(text_of(li).split()) for li in root.iter("li")]
        for caveat in model.fixed_caveats:
            assert f"{caveat.title}. {caveat.text}" in items, (name, caveat.title)
        assert len(model.fixed_caveats) == 8


def test_the_equity_caption_is_the_one_of_the_model_for_equal_late_and_early_starts(kinds) -> None:
    for name in ("equal_start", "late_benchmark", "early_benchmark"):
        model = model_of(kinds[name])
        captions = [text_of(c) for c in parse(render_html(model)).iter("figcaption")]
        assert captions == [model.charts.equity_caption, model.charts.drawdown_caption], name
    assert "not comparable" in model_of(kinds["late_benchmark"]).charts.equity_caption


def test_the_page_has_a_language_a_title_and_a_viewport() -> None:
    html = html_of(equal_start())
    root = parse(html)
    assert root.get("lang") == "en" and "xmlns" not in html
    assert text_of(root.find("head/title")) == "Backtest report: Buy and hold A"
    viewport = [m for m in root.iter("meta") if m.get("name") == "viewport"]
    assert [m.get("content") for m in viewport] == ["width=device-width, initial-scale=1"]
    assert root.find("head/meta").get("charset") == "utf-8"
    assert [e.get("id") for e in root.iter("h1")] == ["report-title"]


def test_the_charts_are_inline_svg_with_title_and_description_and_without_a_namespace() -> None:
    html = html_of(equal_start())
    root = parse(html)
    svgs = list(root.iter("svg"))
    assert len(svgs) == 2 and "xmlns" not in html
    for svg in svgs:
        assert svg.find("title") is not None and svg.find("desc") is not None
        assert svg.get("role") == "img" and svg.get("aria-labelledby")
    assert [s.find("title").get("id") for s in svgs] == ["bt-equity-title", "bt-drawdown-title"]
    assert len(list(root.iter("figure"))) == 2


def test_the_text_has_unix_line_ends_and_one_final_newline(kinds) -> None:
    for name, evaluation in kinds.items():
        html = html_of(evaluation)
        assert "\r" not in html and html.endswith("</html>\n") and not html.endswith("\n\n"), name


def test_a_missing_value_prints_as_n_a_never_as_nan_none_or_nothing(kinds) -> None:
    for name, evaluation in kinds.items():
        root = parse(html_of(evaluation))
        cells = [text_of(cell) for table in tables(root) for row in table_body(table) for cell in row]
        assert all(cell.strip() for cell in cells), name
        visible = "\n".join(cells) + "\n".join(text_of(e) for e in root.iter("li"))
        assert not re.search(r"\b(nan|None|inf)\b", visible), name
    assert "n/a" in html_of(kinds["insufficient_overlap"])


# --- escaping ---------------------------------------------------------------------------------------------------------


def test_a_hostile_name_message_and_symbol_never_become_elements_or_attributes() -> None:
    html = html_of(hostile_evaluation())
    root = parse(html)  # still well-formed
    found = structure(html)
    tags = {element.tag for element in root.iter()}
    assert not tags & (FORBIDDEN_TAGS | {"b"}) and not set(found.tags) & (FORBIDDEN_TAGS | {"b"})
    for element in root.iter():
        for key, value in element.attrib.items():
            assert "alert" not in value and "<" not in value and "onerror" not in key and key != "src", (key, value)
    assert "<script" not in html and "<img" not in html and "<b>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert text_of(root.find("head/title")) == f"Backtest report: {HOSTILE}"
    assert text_of(next(root.iter("h1"))) == f"Backtest report: {HOSTILE}"
    messages = [text_of(cell) for table in tables(root) for row in table_body(table) for cell in row]
    assert '"><img src=x onerror=alert(1)>' in messages and "'><b>x" in messages


def test_quotes_and_ampersands_in_a_name_survive_a_round_trip() -> None:
    name = 'Tom\'s "quote" & <co>'
    root = parse(html_of(hostile_evaluation(name=name)))
    assert text_of(root.find("head/title")) == f"Backtest report: {name}"
    assert ("Name", name) in [
        (text_of(row[0]), text_of(row[1])) for table in tables(root) for row in table_body(table) if len(row) == 2
    ]
    svg_titles = [text_of(d) for d in root.iter("desc")]
    assert all(name in d for d in svg_titles)


# --- nothing external -------------------------------------------------------------------------------------------------


def test_the_default_report_has_no_http_text_at_all() -> None:
    assert "http" not in html_of(equal_start())


def test_no_script_link_image_frame_src_or_external_href(kinds) -> None:
    for name, evaluation in kinds.items():
        found = structure(html_of(evaluation))
        assert not set(found.tags) & FORBIDDEN_TAGS, name
        assert not [a for a in found.attrs if a[1] in ("src", "srcset", "data", "action", "poster")], name
        assert all(value.startswith("#") for tag_, key, value in found.attrs if key == "href"), name
        assert not [a for a in found.attrs if a[1].startswith("on")], name
        assert "url(" not in found.css and "@import" not in found.css and "http" not in found.css, name


def test_the_css_is_a_plain_constant_without_external_reference() -> None:
    assert isinstance(CSS, str) and not isinstance(CSS, Markup)
    for forbidden in ("@import", "url(", "http", "//", OPEN * 2, CLOSE * 2, "&", "<", "@font-face", "expression("):
        assert forbidden not in CSS, forbidden
    assert CSS.count("{") == CSS.count("}")
    assert (
        CSS in structure(html_of(equal_start())).css + "\n" or CSS.rstrip("\n") in structure(html_of(equal_start())).css
    )


def test_the_css_makes_the_page_work_at_phone_width() -> None:
    assert "overflow-x:auto" in CSS and "figure svg{display:block;max-width:100%;height:auto}" in CSS
    assert "main{max-width:64rem;margin:0 auto;padding:16px}" in CSS  # 16px gutter, no fixed width
    assert "overflow-wrap:anywhere" in CSS and "prefers-color-scheme: dark" in CSS


# --- the heatmap shades -----------------------------------------------------------------------------------------------

POSITIVE = [
    (0.0, None),
    (0.0124, None),
    (0.0125, "bt-pos-1"),
    (0.025, "bt-pos-1"),
    (0.0374, "bt-pos-1"),
    (0.0375, "bt-pos-2"),
    (0.05, "bt-pos-2"),
    (0.0624, "bt-pos-2"),
    (0.0625, "bt-pos-3"),
    (0.075, "bt-pos-3"),
    (0.0874, "bt-pos-3"),
    (0.0875, "bt-pos-4"),
    (0.10, "bt-pos-4"),
    (0.35, "bt-pos-4"),
]
NEGATIVE = [
    (-0.0, None),
    (-0.0124, None),
    (-0.0125, "bt-neg-1"),
    (-0.025, "bt-neg-1"),
    (-0.0374, "bt-neg-1"),
    (-0.0375, "bt-neg-2"),
    (-0.05, "bt-neg-2"),
    (-0.0624, "bt-neg-2"),
    (-0.0625, "bt-neg-3"),
    (-0.075, "bt-neg-3"),
    (-0.0874, "bt-neg-3"),
    (-0.0875, "bt-neg-4"),
    (-0.10, "bt-neg-4"),
    (-0.35, "bt-neg-4"),
    (-1.0, "bt-neg-4"),
]


@pytest.mark.parametrize("value, expected", POSITIVE + NEGATIVE)
def test_shade_class(value, expected) -> None:
    assert shade_class(value) == expected


def test_the_breaks_are_those_of_the_documented_scale() -> None:
    assert SHADE_BREAKS == (0.0125, 0.0375, 0.0625, 0.0875)
    assert OUTSIDE_CLASS == "bt-out"


def with_heatmap(rows):
    model = model_of(equal_start())
    heatmap = HeatmapSection(
        months=model.heatmap.months, years=tuple(range(2024, 2024 + len(rows))), rows=rows, footnote="note"
    )
    return replace(model, heatmap=heatmap)


def test_a_cell_outside_the_run_has_no_shade_and_a_partial_month_is_shaded_and_marked() -> None:
    outside = HeatmapCell("·", None, False)
    row = (
        HeatmapCell("3.00%*", 0.03, True),
        HeatmapCell("-9.00%", -0.09, False),
        HeatmapCell("0.00%", 0.0, False),
        *([outside] * 9),
    )
    root = parse(render_html(with_heatmap((row,))))
    heat = next(t for t in tables(root) if t.get("class") == "bt-heat")
    cells = table_body(heat)[0]
    assert [text_of(c) for c in cells] == ["2024", "3.00%*", "-9.00%", "0.00%", *["·"] * 9]
    assert [c.get("class") for c in cells] == [None, "bt-pos-1", "bt-neg-4", None, *["bt-out"] * 9]
    assert cells[0].tag == "th" and cells[0].get("scope") == "row"


def test_the_shade_uses_the_unrounded_return() -> None:
    # 0.012499 prints as 1.25% and stays neutral; 0.0125 prints the same and is the first step.
    row = (
        HeatmapCell("1.25%", 0.012499, False),
        HeatmapCell("1.25%", 0.0125, False),
        *([HeatmapCell("·", None, False)] * 10),
    )
    heat = next(t for t in tables(parse(render_html(with_heatmap((row,))))) if t.get("class") == "bt-heat")
    cells = table_body(heat)[0]
    assert [c.get("class") for c in cells[:3]] == [None, None, "bt-pos-1"]


def test_the_default_run_shades_its_one_month_by_the_total_return() -> None:
    # R3b: the net return of the run is 0.17128 = 17.13 percent, so the only month is beyond the cap: darkest blue.
    heat = next(t for t in tables(parse(html_of(equal_start()))) if t.get("class") == "bt-heat")
    cells = table_body(heat)[0]
    assert [text_of(c) for c in cells] == ["2024", "17.13%*", *["·"] * 11]
    assert [c.get("class") for c in cells] == [None, "bt-pos-4", *["bt-out"] * 11]


# --- contrast of the shipped colours ----------------------------------------------------------------------------------


def luminance(color: str) -> float:
    """WCAG 2.x relative luminance of ``#rrggbb``."""

    def channel(byte: int) -> float:
        c = byte / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(first: str, second: str) -> float:
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def themes() -> dict[str, dict[str, str]]:
    """The colour tokens of the shipped CSS: the light ones on :root and the dark ones of the media query."""
    light_part, dark_part = CSS.split("@media (prefers-color-scheme: dark){")
    read = lambda part: dict(re.findall(r"--([a-z0-9-]+):(#[0-9a-f]{6})", part))  # noqa: E731
    light = read(light_part.split("\n")[0])
    dark = {**light, **read(dark_part.split("\n")[1])}  # a token the dark block does not set keeps the light value
    return {"light": light, "dark": dark}


SHADES = [f"{sign}-{level}" for sign in ("pos", "neg") for level in (1, 2, 3, 4)]
PAIRS = [("text", "bg"), ("muted", "bg"), ("text", "head"), *[("text", shade) for shade in SHADES]]


def contrast_table() -> list[tuple[str, str, str, float]]:
    return [
        (theme, f"{fg} on {bg}", f"{tokens[fg]} on {tokens[bg]}", contrast(tokens[fg], tokens[bg]))
        for theme, tokens in themes().items()
        for fg, bg in PAIRS
    ]


def test_the_contrast_function_on_known_pairs() -> None:
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0, abs=1e-9)
    assert contrast("#ffffff", "#000000") == pytest.approx(21.0, abs=1e-9)
    assert contrast("#123456", "#123456") == pytest.approx(1.0, abs=1e-12)
    assert contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)  # the well-known borderline grey
    assert contrast("#767676", "#ffffff") == pytest.approx(4.54, abs=0.01)
    assert luminance("#000000") == 0.0 and luminance("#ffffff") == pytest.approx(1.0, abs=1e-12)


def test_every_text_colour_has_a_contrast_of_at_least_4_5_on_every_background_in_both_themes() -> None:
    rows = contrast_table()
    assert len(rows) == 2 * len(PAIRS) == 2 * 11
    for theme, pair, colors, ratio in rows:
        assert ratio >= 4.5, (theme, pair, colors, ratio)


def test_the_dark_theme_sets_every_colour_token_itself() -> None:
    light_part, dark_part = CSS.split("@media (prefers-color-scheme: dark){")
    light_tokens = set(re.findall(r"--([a-z0-9-]+):#", light_part.split("\n")[0]))
    dark_tokens = set(re.findall(r"--([a-z0-9-]+):#", dark_part.split("\n")[1]))
    assert dark_tokens == light_tokens == {"bg", "text", "muted", "rule", "head", *SHADES}
    both = themes()
    assert all(both["dark"][token] != both["light"][token] for token in light_tokens)  # no light colour left over
    assert both["light"]["bg"] == "#fcfcfb" and both["dark"]["bg"] == "#1a1a19"


def test_each_shade_class_uses_its_own_token() -> None:
    for shade in SHADES:
        assert ".bt-" + shade + OPEN + "background:var(--" + shade + ")" + CLOSE in CSS


if __name__ == "__main__":  # print the contrast table of the shipped colours
    for theme, pair, colors, ratio in contrast_table():
        print(f"{theme:5}  {pair:14}  {colors:19}  {ratio:6.2f}")
