# Report

One readable file that tells the whole story of a run (F-14): what was run, on which data, what came out next to the
benchmark, and what the number does not mean. The code is in `src/backtest_agent/reporting/` (and `run_id.py`), the
decisions are in [ADR 0014](adr/0014-report.md). The report only formats numbers that already exist in an `Evaluation`
([metrics.md](metrics.md)); the one family that did not exist, the trade statistics, was added to the metrics layer first.

**Status.** Phase 7 is done. Part 1 delivered the model, the Markdown report, the SVG charts, the run id and the writer.
Part 2 delivers the self-contained HTML report (section "HTML"), `report.html` in the writer, and the reports of the three
example strategies (offline and, marked `network`, with real data).

## Pipeline

```
Evaluation ──► build_report_model ──► ReportModel ──► render_markdown ──► report.md
 (metrics)     (pure: all display       (frozen         line_chart_svg  ──► equity.svg, drawdown.svg
                decisions, formats)      display data)  render_html     ──► report.html
                                                              │
                                              write_report (the only file I/O)
```

| Layer | Module | Does | Does not |
|---|---|---|---|
| Model | `reporting/model.py` | Reads the `Evaluation`, decides what is shown and how (`n/a`, formats, flag explanations, sentences) | read a clock, locale, environment or file |
| Formats | `reporting/format.py` | The one place for number, date and money formats | print a raw float |
| Caveats | `reporting/caveats.py` | Fixed caveats, run caveats, flag explanations | take a parameter that could switch the fixed text off |
| Facts | `reporting/facts.py` | First and last bar of strategy and benchmark | compute a metric |
| Charts | `reporting/charts.py` | SVG text of a line chart from the model's series | read the `Evaluation` |
| Markdown | `reporting/markdown_renderer.py` | Lays the model out, escapes text for Markdown | decide a format or add content |
| HTML | `reporting/html_renderer.py` | Lays the model out as one self-contained HTML file, escapes every text, shades the monthly returns | decide a format, add content or reference anything external |
| Writer | `reporting/writer.py` | Renders everything in memory, then writes the files | render |
| Run id | `run_id.py` | `<UTC timestamp>-<slug>-<8 hex>` | run inside a renderer |

## Using it

```python
from datetime import datetime, timezone
from backtest_agent.metrics import evaluate
from backtest_agent.reporting import write_report

evaluation = evaluate(spec, provider)
paths = write_report(evaluation, "reports", generated_at=datetime.now(timezone.utc))
print(paths.markdown)
```

`write_report(evaluation, reports_dir, *, generated_at, run_id=None, overwrite=False)` creates `reports_dir/<run-id>/` and
returns `ReportPaths(directory, run_id, files)`. `generated_at` must be timezone-aware. The wall clock is read by the
caller, never by the report. `render_report(...)` returns the same files as `{name: text}` without touching the disk.
`reports/` is git-ignored; no report, data or run output is ever committed.

Files of one report:

| File | Content |
|---|---|
| `report.md` | The report as Markdown; links `equity.svg` and `drawdown.svg` by relative path |
| `equity.svg`, `drawdown.svg` | The charts as standalone SVG files (with the XML namespace) |
| `report.html` | The same report as one self-contained HTML file with the SVG inline; needs no other file |

The files are written in this order: `report.md`, `equity.svg`, `drawdown.svg`, `report.html`. The HTML report, the file a
reader opens first, is written last, so it exists only if everything else was written. `ReportPaths` has the properties
`markdown` and `html`.

## Sections, in this order

The headings are protected by the snapshot test `tests/snapshots/report.md`.

1. **Header.** Strategy name, run id, generation time (UTC), requested period, number of bars and first and last bar,
   universe, benchmark.
2. **Spec summary.** Name, description, universe, period, data provider, signal and its parameters, warm-up rows, rebalance,
   sizing, execution delay and price, same-bar flag, initial capital, the costs block (commission, spread, slippage,
   minimum commission), benchmark.
3. **Data.** For the strategy run and for the benchmark run: the symbols, the **data hash**, and the validation findings
   (warnings and infos in a table; errors cannot exist, they stop a run). Then the **warm-up** of the strategy run
   (rows required, delay, rows needed, history loaded from, first bar, first decision date, sufficient or not, rows per
   symbol and the target weights of the first decision) and one line for the benchmark's warm-up.
4. **Risk flags.** The flags of both runs. Each row has the engine's own message and a plain-language explanation of what
   it means for the numbers (`same_bar_execution`, `zero_costs`, `costs_not_applied`, `insufficient_warmup`). A new flag
   code without an explanation fails a test.
5. **Metrics.** The assumptions printed first (`periods_per_year`, annual `risk_free_rate`), then the performance table
   (strategy next to benchmark) and the table "Relative to the benchmark" (excess return, tracking error, information
   ratio, and the two returns over the compared window).
6. **Benchmark alignment.** The numbers of the comparison (bars of each run, common dates, compared observations, dropped
   dates of each run, `insufficient_overlap`, the base rule and its date, first and last compared date), the base rule in
   words, and a sentence when the benchmark starts later or earlier, or ends earlier or later, than the strategy.
7. **Costs.** Costs applied or not, total costs, final equity net and gross, net and gross return, cost drag and cost share,
   for strategy and benchmark.
8. **Charts.** The equity curve against the benchmark with its caption, and the drawdown chart.
9. **Monthly returns.** A year-by-month table.
10. **Trade statistics.** Trades (fills), buys, sells, total cost, average cost per trade, turnover per year two-sided and
    one-sided, exposure, share of bars with a position, deferred and unfilled orders, and a table per symbol.
11. **Assumptions and caveats.** Always last, always present (see below).

### Where the numbers come from

Nothing is recomputed in the report. Metrics come from `PerformanceMetrics` (`evaluation.metrics`,
`evaluation.benchmark_metrics`), relative metrics and alignment from `RelativeMetrics` / `Alignment`, costs from the
`BacktestResult` properties (`total_costs`, `gross_final_equity`, `net_return`, `gross_return`, `cost_drag`,
`cost_share`), the data hash, validation and warm-up from the `BacktestResult`, the monthly returns from
`monthly_returns`, the drawdown from `drawdown_path`. The trade counts and the average cost per trade come from
`metrics.trade_statistics` (see [metrics.md](metrics.md), "Trade statistics"). **Deferred and unfilled orders** are the
fields `BacktestResult.deferred_orders` and `unfilled_orders` of the engine (an order is deferred when its symbol has no
price on the bar or cash is short, and unfilled if it is still open after the last bar); they are not trade statistics and
the report says so. The model only arranges the monthly returns into a year-by-month grid and takes the first and last
bar dates of the equity series.

### Benchmark that starts later

Both curves start with the same initial capital but each on its own first date, so they are **not comparable over the
whole chart** when the benchmark starts later (or earlier). The caption under the equity chart, in Markdown and in HTML,
says so, names both first dates and states the base rule the relative metrics used (`Alignment.base`): either the return
of the first bar is measured against each run's initial equity (equal start), or the equity of both runs on the first
common date is the starting point and that date has no return. With an equal start the caption says the curves are
comparable from the first bar. The same facts appear as sentences in "Benchmark alignment" and as a run caveat.

## Formats

All in `reporting/format.py`, tested with literal input and output pairs in `tests/test_report_format.py`.

| Kind | Format | Example |
|---|---|---|
| Percentage | a fraction times 100, 2 decimals, thousands separators, `%` | `0.17128` → `17.13%` |
| Signed percentage (excess return) | as above with `+` for positive values | `0.3872` → `+38.72%` |
| Ratio (Sharpe, Sortino, Calmar, information ratio) | 2 decimals | `0.826767` → `0.83` |
| Money | 2 decimals, thousands separators, no currency symbol (the spec has none) | `1171.28` → `1,171.28` |
| Basis points | up to 2 decimals, trailing zeros dropped | `1.0` → `1 bps` |
| Count | integer, thousands separators | `1234` → `1,234` |
| Date | ISO `YYYY-MM-DD` | `2024-01-03` |
| Time | `YYYY-MM-DD HH:MM:SS UTC` | `2026-01-15 10:30:05 UTC` |
| Undefined (`None`) | `n/a`, with a reason where one exists | `n/a (gross return is not positive)` |
| Minus sign | ASCII `-`; a value that rounds to zero prints without a sign | `-0.00001` → `0.00%` |

NaN and infinity are not "n/a": the formatter raises a `ValueError` that names the field, because a metric is `None` when
it is not defined and a non-finite number is a bug upstream. The cost share is a percentage when defined (it can be
negative or above 100%, the report says why), and `n/a (gross return is not positive)` when `None`, never with a `%`.
Turnover and exposure are percentages (buying the whole portfolio from cash is 100%). The heatmap uses the percentage
format; `*` marks the first and last month of the run, `·` a month outside the run.

## Run id and the output folder

`<YYYYMMDDTHHMMSSZ>-<slug>-<8 hex>`, for example `20260115T103005Z-buy-and-hold-a-a85a59ee`.

- **Timestamp:** `generated_at` in UTC.
- **Slug of the strategy name:** folded to ASCII, lower case, every run of characters outside `[a-z0-9]` becomes one `-`,
  leading and trailing `-` removed, cut at 40 characters, `run` if nothing is left. Windows-forbidden characters, a trailing
  dot or space and device names cannot occur (the id starts with the timestamp).
- **8 hex characters:** the first 8 characters of the SHA-256 of the canonical JSON of the spec, both data hashes, the
  `costs_applied` flag and the metric assumptions. The exact input and a worked example are in
  [ADR 0014](adr/0014-report.md).
- **Re-run, same inputs, another time:** a new folder; the 8 hex characters are the same. **Same id again:**
  `FileExistsError` unless `overwrite=True`. A run id that could leave the reports folder is rejected.
- **Atomic:** everything is rendered in memory before the folder is created; if rendering raises, nothing is left on
  disk. If a write fails, a folder this call created is removed.
- **Not atomic with `overwrite=True`:** the existing folder is kept, so a write that fails part-way can leave a mix of new
  and old files. Files that the call does not write are left alone. Delete the folder and write again if that matters. A
  temporary folder with a directory swap was considered and left out: it needs two renames with a rollback, behaves
  differently on Windows (a folder open in a viewer blocks a rename) and would need its own failure tests.

## Charts

Written by hand in `reporting/charts.py`, no dependency (ADR 0014). A 720 x 360 canvas, up to two series, a linear time
axis from the first to the last date of all series, "nice" y ticks (1, 2 or 5 times a power of ten), coordinates with two
decimals. The strategy is a solid line in categorical colour 1 (blue), the benchmark a dashed line in colour 2 (orange), so
the chart reads in greyscale; the legend names both. The light and dark colours are inside the SVG
(`prefers-color-scheme`). Each chart has a `<title>` and a `<desc>` with the key numbers. There is no hover layer: the
report is a static document, and every number the chart shows is in a table.

Degenerate inputs: one bar is a dot; a flat equity gets a margin of 5% around it; all-zero returns give a drawdown axis
from -1% to 0; equity that went to 0 ends on the bottom line; a series that is shorter or starts later keeps its own dates.

## Assumptions and caveats

Produced by `fixed_caveats()`, a function without parameters, and checked by `ReportModel`, which raises if the fixed
text is not exactly `fixed_caveats()`. Fixed, in this order: Execution, Costs, Adjusted prices, Survivorship, Annualization
of short runs, Partial months, Selection bias, Not investment advice. The text says: orders are filled `delay_bars` after
the signal at the named price and a same-bar fill can hide look-ahead bias; costs are bps fees, zero costs overstate the
return and taxes are not modelled; prices are split- and dividend-adjusted (total return) and adjusted history changes
with every new dividend or split; the universe is today's constituents unless the spec says otherwise (survivorship);
CAGR, Calmar and the other annualized figures are strongly extrapolated for runs of a year or less; the first and last
month can be partial; the report does not know how many other variants were tried; a backtest is educational and not
investment advice. "This run" lists what follows from the run: the actual delay and price, risk flag codes, a window of a
year or less, a benchmark that starts later or ends earlier, insufficient overlap. It never replaces the fixed text.

## Escaping

The model keeps text from the spec or the data (names, symbols, validation messages) with whitespace collapsed, `(none)` for
an empty value, and characters that XML 1.0 forbids (NUL and the other control characters except tab, line feed and
carriage return) replaced by U+FFFD. That replacement is in `text()` of `reporting/model.py`, once, so the Markdown, the HTML
and the standalone SVG files are all well-formed. The Markdown renderer escapes `\ | ` * < > [ ] &` with a backslash and
turns line breaks into spaces, so a name cannot break a table or inject markup. The HTML renderer escapes `& < > " '`
(see "HTML").

## HTML

`reporting/html_renderer.py`, `render_html(model) -> str`: a pure function of the `ReportModel`. It adds no content and no
number format. The sections and headings are those of the Markdown report in the same order, the fixed caveats come from
`model.fixed_caveats`, and the equity caption is `model.charts.equity_caption`. There is no table of contents (it would be
new content) and no theme switch.

**One self-contained file.** Inline CSS, inline SVG (`line_chart_svg(chart, standalone=False)`, which has no XML
namespace, because the namespace is an `http://` string), no script, no external font, stylesheet, image or link. The
Markdown report links `equity.svg` and `drawdown.svg`; the HTML embeds the same charts in a `<figure>` with the caption as
`<figcaption>`, so the file needs no other file.

**Escaping cannot be forgotten.** The markup is built with two helpers only, `tag(element, *children, **attrs)` (one line)
and `block(...)` (children on their own lines):

- A plain `str` child or attribute value is always escaped (`& < > " '` become `&amp; &lt; &gt; &quot; &#39;`, so only the
  five predefined and numeric entities occur). Only a `Markup` (made by the helpers, or wrapped by the renderer for the two
  trusted constants, the CSS and the SVG text) passes through. Joining a `Markup` with a `str` gives a plain `str` again.
- Element and attribute names must match `[a-z][a-z0-9-]*` (`class_` becomes `class`, `aria_labelledby` becomes
  `aria-labelledby`); an attribute value that is not a string raises; a void element (`meta`) takes no children.
- No attribute value comes from the spec or the data: attributes are constants or ids made from fixed heading texts.

**XML-compatible.** Closed tags, quoted attributes, no named HTML entities. `<!DOCTYPE html>` has no internal subset, so
`xml.etree` parses the file as it is (checked, no stripping of the first line is needed); the rest of the document is
checked strictly. `html.parser` is a second, independent reading for the structural checks.

**Structure and accessibility.** `<html lang="en">`, a `<title>`, a viewport meta tag, one `h1` and `h2`/`h3` headings in
order without skipped levels, each `h2` section a `<section aria-labelledby>`. Every table sits in a scroll container
(`<div class="bt-table-wrap" role="region" tabindex="0" aria-labelledby=...>`), so a wide table scrolls inside its own box and
never makes the page scroll sideways. Header cells are `<th scope="col">`; the first column of the label tables (Item,
Metric, Assumption, Symbol, Year) is `<th scope="row">`; the validation-issue table and the risk-flag table have no row
header. Hashes and the run id are in `<code>`. The charts keep their `<title>` and `<desc>`.

**Monthly returns shading.** The numbers are always printed in the cell, so the table reads without colour and in
greyscale. A cell is shaded by class (`bt-pos-1` to `bt-pos-4`, `bt-neg-1` to `bt-neg-4`), symmetric around 0, in four steps
of 2.5 percent up to a cap of 10 percent; beyond the cap the darkest step is used:

| \|monthly return\| | Class (positive / negative) |
|---|---|
| below 1.25 % (including 0) | none, neutral |
| 1.25 % up to below 3.75 % | `bt-pos-1` / `bt-neg-1` |
| 3.75 % up to below 6.25 % | `bt-pos-2` / `bt-neg-2` |
| 6.25 % up to below 8.75 % | `bt-pos-3` / `bt-neg-3` |
| 8.75 % and more (10 % and beyond is clipped) | `bt-pos-4` / `bt-neg-4` |

A boundary belongs to the darker step (`SHADE_BREAKS = (0.0125, 0.0375, 0.0625, 0.0875)`). **The shading uses the unrounded
monthly return**, so a cell that prints `1.25%` can still be neutral (0.012499 prints as 1.25% and has no shade; 0.0125
is the first step). A month outside the run (`·`) has the class `bt-out` and no shade; the first and last month of the run
keep the `*` of the Markdown report and are shaded by their value.

**The heatmap colours (blue for positive, orange for negative) have no relation to the colours of the chart series** (blue
strategy and orange benchmark in the charts). In the table blue only means a positive month and orange a negative one,
and the sign is always printed in the cell.

Colours and contrast, as shipped in the CSS (text colour `#0b0b0b` in the light theme and `#f0efec` in the dark theme;
the contrast is computed with the WCAG formula by `tests/test_report_html.py`, minimum 4.5):

| Theme and sign | Step 1 | Step 2 | Step 3 | Step 4 |
|---|---|---|---|---|
| light, blue (positive) | `#e6effa` 16.96 | `#c5dcf6` 14.00 | `#9cc3ef` 10.75 | `#6aa6e6` 7.69 |
| light, orange (negative) | `#fdece4` 17.15 | `#fad3c0` 14.19 | `#f6b394` 11.05 | `#f08d5e` 8.13 |
| dark, blue (positive) | `#1c2a3d` 12.61 | `#1f3f66` 9.31 | `#245890` 6.36 | `#2a68a8` 5.01 |
| dark, orange (negative) | `#3a2418` 12.63 | `#5c3320` 9.37 | `#8a4524` 6.18 | `#a8501f` 4.77 |

The other pairs: text on the page background 19.17 (light) and 15.15 (dark), muted text on the background 7.73 and 9.72,
text on the table header background 17.26 and 13.18.

**CSS (`CSS` in `html_renderer.py`).** One plain constant string, written out with its colours, no f-string and no template
placeholder (no source file contains the two-character sequence of two opening braces; the tests build such strings from
constants). Light colour tokens on `:root`, dark tokens in `@media (prefers-color-scheme: dark)`, which sets every token,
so no light colour is left over in dark mode. The rules:

- `box-sizing: border-box`; `body` with the system font stack, 16px, 1.5 line height, `background` and `color` from the
  tokens; `main` with `max-width: 64rem` and a 16px side padding (no fixed width, no horizontal page scroll at phone width).
- Headings with fixed sizes and `overflow-wrap: anywhere`; `li` and `p` with `overflow-wrap: anywhere`; `code` in a
  monospace stack with `overflow-wrap: anywhere` and `word-break: break-all`, so a 64-character hash wraps.
- `.bt-table-wrap` with `overflow-x: auto`, `max-width: 100%` and a visible focus outline (`:focus-visible`); tables with
  `font-variant-numeric: tabular-nums`; `thead th` with the `--head` background; `.bt-heat td` right-aligned and not wrapped.
- `.bt-pos-N` and `.bt-neg-N` set `background` from their own token (a test checks every mapping); `.bt-out` text uses
  the muted colour.
- `figure svg` with `display: block; max-width: 100%; height: auto`, `figcaption` muted.
- No `@import`, no `url(`, no `http`, no `//`, no `&`, no `<`, no `@font-face`, no double brace. A test checks the constant
  and also parses the shade colours out of it for the contrast test.
- All class names of the page start with `bt-` and differ from the class names inside the inline SVGs (their `<style>`
  rules are global to the page).

## What is deliberately not in the report

- The command line (`bt report`, Phase 9) and the journal: trial counter, code version, run store (Phase 8). The report says
  that it does not know how many variants were tried.
- Auditor and interpreter sections (Phase 11), out-of-sample, walk-forward, sensitivity and regime sections (Phases 13
  and 14), the deflated Sharpe ratio (Phase 15).
- PDF, a JSON export of the model, interactive or zoomable charts, a log axis, a gross-equity line, a benchmark heatmap,
  year totals in the heatmap, a list of single trades, weight or exposure charts, a switch for theme, locale or currency.
- Any recomputation of a metric, and any number that the metrics layer does not define.

## Tests

| File | Protects |
|---|---|
| `tests/test_metrics_trades.py` | Trade statistics: fixtures T1 to T6, runs through `run_backtest`, no zero-share fill in valid runs, each guard |
| `tests/test_run_id.py` | Slug rules, hash input and its sensitivity to each input, UTC and naive datetime, the worked example of ADR 0014 |
| `tests/test_report_format.py` | Every format with literal pairs, `None` and NaN/inf handling, negative zero |
| `tests/test_report_caveats.py` | Fixed caveats without parameters, no URL, every flag code explained, run caveats |
| `tests/test_report_model.py` | Literal display strings (R3b, H23, T2), heatmap grid with partial months, equity caption for equal, late and early start, table and caveats guards |
| `tests/test_report_charts.py` | Hand-calculated ticks, coordinates and paths, degenerate inputs, escaping, guards |
| `tests/test_report_markdown.py` | Headings and table headers in order, links, escaping of hostile text, caveats for every kind of run |
| `tests/test_report_markdown_snapshot.py`, `tests/snapshots/report.md` | The reviewed structure of the whole Markdown report |
| `tests/test_report_none_values.py` | `None` never prints as `nan`, `None` or an empty cell; NaN and infinity raise with the field name |
| `tests/test_report_writer.py` | Four files in write order, links, line ends, atomicity (a render failure, a failure on any write including the HTML write, which is the last one), `FileExistsError`, path traversal, cleanup after a failed write |
| `tests/report_helpers.py` | Synthetic evaluations (equal start, late and early benchmark, insufficient overlap, costs off, benchmark in the universe, flags, insufficient warm-up) |
| `tests/test_report_html.py` | The helpers (`esc`, `tag`, `block`, `Markup`), well-formed XML for every kind of run, headings, tables and cells equal to the Markdown report, `scope`, scroll containers, caveats, hostile text, no external reference, the shade table with every boundary and its mirror, the contrast of every colour pair in both themes |
| `tests/test_report_html_outline.py`, `tests/snapshots/report_html_outline.txt` | The outline of the HTML (headings and ids, table headers, row headers, scroll containers, figures); not the numbers |
| `tests/test_report_xml_safe.py` | `text()` replaces characters that XML forbids; a NUL in a name or message leaves the Markdown clean and the HTML and both SVG files parsable |
| `tests/test_report_examples.py`, `tests/report_example_checks.py` | A written report for each of the three example strategies on `FakeProvider`, offline (a `monkeypatch` guard blocks sockets); the shared checks |
| `tests/test_report_network.py` | The same with real data through `CachedProvider`; marked `network`, run manually with `-m network` |
| `tests/html_helpers.py` | Strict XML parsing, table cells, the outline, an `html.parser` reading; computes no expected value |

The Markdown snapshot was generated once and read through by hand; regenerate it with
`uv run python tests/test_report_markdown_snapshot.py` after a deliberate change and review the diff line by line. The HTML
outline is regenerated with `uv run python tests/test_report_html_outline.py`, reviewed the same way. The numbers in the
Markdown snapshot are those of the hand-calculated fixtures (R3b, H23); formats are tested with literals, never with project
code. `uv run python tests/test_report_html.py` prints the contrast table of the shipped colours.

The example reports (period 2018-01-01 to 2019-12-31 on the fake history, benchmark SPY, which is in the universe of all
three) have 522 bars each and 34 (SMA crossover), 83 (12-1 momentum) and 72 (buy and hold) trades. With real data (period
2022-01-03 to 2023-12-29, `uv run pytest -m network tests/test_report_network.py -s`) they have 501 bars each and 42, 81
and 72 trades, and no validation warnings (on the day of the check). The tests assert more than 0 trades and consistent
dates and cash, not these counts.

## The plan items that were cut off in the discussion, restated

These were restated in full at the maintainer's request.

- **`TradeStatistics` fields:** `n_trades`, `n_buys`, `n_sells`, `per_symbol` (a dict of traded symbols, sorted, to
  `SymbolTrades(trades, buys, sells)`), `total_cost`, `average_cost_per_trade` (`float | None`).
- **Slug rules (D3):** see "Run id and the output folder".
- **Determinism (D2), complete:** the model and renderers are pure; `generated_at` is an explicit, timezone-aware
  argument printed in UTC; files are UTF-8 with `\n` on every OS; the snapshot tests normalise `\r\n` on read.
- **Self-contained HTML (D5), complete:** see "HTML" and [ADR 0014](adr/0014-report.md).
- **Tests of part 2:** HTML parses and is well-formed, a hostile name is escaped, no external reference, a report for
  each example strategy offline and (marked `network`) with real data read through the cache, the files exist and are
  non-empty, the HTML parses and the Markdown links resolve to existing files.

The parts of the plan for part 2 that were cut off, restated:

1. **The six commits of part 2**, in this order, Conventional Commits, no attribution lines:
   1. `docs(report): fix review items of part 1` (README list, writer docstring headings, ADR package count, the
      `overwrite=True` note).
   2. `fix(reporting): use the singular in the validation line` (`1 info`, `1 warning`, `1 error`; `2 infos`; the Markdown
      snapshot changes in two lines).
   3. `feat(reporting): add the self-contained HTML renderer (F-14)` (with the `text()` replacement of XML-illegal characters).
   4. `feat(reporting): write report.html with the other report files (F-14)`.
   5. `test(reporting): reports for the example strategies, offline and with real data (F-14)`.
   6. `docs: finish Phase 7 (report, ADR 0014, README, CLAUDE.md, CHANGELOG, ROADMAP)`.
2. **The light-blue row of the colour table** is in "HTML": `#e6effa` 16.96, `#c5dcf6` 14.00, `#9cc3ef` 10.75, `#6aa6e6` 7.69
   against `#0b0b0b`; all four rows of the table pass 4.5, the tightest is dark orange step 4 with 4.77.
3. **The rest of the CSS rule list (H4)** is in "HTML", under "CSS": table container, tables, heatmap cells, shade classes,
   figures, and what the constant must not contain.
4. **The outline snapshot (the rest of that paragraph).** `tests/snapshots/report_html_outline.txt` lists the headings with
   level and id, each table with its headers, whether it has a scroll container and whether its first body cell is a row
   header, and each figure with `<title>` and `<desc>`. It covers ids and `scope`, which the Markdown snapshot cannot. It
   contains no numbers. **The writer test for a failed HTML write:** `test_a_failure_on_the_html_write_removes_the_folder_it_created`
   makes `Path.write_bytes` fail on `report.html`, asserts that the four writes happened in the order `report.md`,
   `equity.svg`, `drawdown.svg`, `report.html` and that the run folder is gone again;
   `test_a_failure_on_the_html_write_keeps_an_existing_folder_when_overwriting` shows that an existing folder is kept with
   `overwrite=True`; `test_a_failure_while_rendering_the_html_leaves_nothing_on_disk` shows that a render failure leaves not
   even the reports folder.
5. **The guard table (which test fails without which guard).** `esc` handles each of `& < > " '` (one literal per
   character); `tag` escapes `str` children and trusts only `Markup`; the tag and attribute name check (bad names raise);
   the replacement of XML-illegal characters in `text()` (a NUL in a name makes the HTML and the SVG files unparsable
   without it); the shade thresholds and the cap (the literal class table, every boundary and its mirror); `bt-out` has no
   shade (the outside-run cell test); the row-header `scope` rules; **`standalone=False` for the inline SVG** (the HTML must
   have no `xmlns` and no `http` text; a standalone SVG would add `http://www.w3.org/2000/svg`); the HTML last in the writer
   (the failure test and the order literal); the singular in the validation line (0/1/2 literals); the socket guard (a test
   proves that `socket.socket.connect` and `connect_ex` are blocked, and another that `monkeypatch` removes the guard).
6. **The end of the docs list:** this file, [ADR 0014](adr/0014-report.md) (status, what changed), the README (feature
   row, Phase 7 Done, the list sentence), `CLAUDE.md` (rules for the HTML renderer and its tests), the `CHANGELOG`, and
   `docs/ROADMAP.md` (the Phase 7 status block, the phase table row and the deviations). All relative links in the README
   and `docs/` resolve, and no file outside `.github/` contains the two-character sequence of two opening braces.
