# Report

One readable file that tells the whole story of a run (F-14): what was run, on which data, what came out next to the
benchmark, and what the number does not mean. The code is in `src/backtest_agent/reporting/` (and `run_id.py`), the
decisions are in [ADR 0014](adr/0014-report.md). The report only formats numbers that already exist in an `Evaluation`
([metrics.md](metrics.md)); the one family that did not exist, the trade statistics, was added to the metrics layer first.

**Status.** Phase 7 part 1 delivers the model, the Markdown report, the SVG charts, the run id and the writer. Part 2
adds the self-contained HTML report (section "HTML (part 2)") and the reports of the three example strategies.

## Pipeline

```
Evaluation ──► build_report_model ──► ReportModel ──► render_markdown ──► report.md
 (metrics)     (pure: all display       (frozen         line_chart_svg  ──► equity.svg, drawdown.svg
                decisions, formats)      display data)  (HTML: part 2)  ──► report.html
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
| `report.html` | Part 2: the same report as one self-contained HTML file with the SVG inline |

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

The model keeps text from the spec or the data (names, symbols, validation messages) raw, with whitespace collapsed and
`(none)` for an empty value. The Markdown renderer escapes `\ | ` * < > [ ] &` with a backslash and turns line breaks into
spaces, so a name cannot break a table or inject markup. The HTML renderer (part 2) escapes `& < > " '`.

## HTML (part 2)

One self-contained file: inline CSS, inline SVG, no external font, script, stylesheet, image or link. The checks of
part 2: the HTML is well-formed (written XML-compatible and parsed with `xml.etree`); a hostile strategy name such as
`<script>alert(1)</script>` appears escaped and not as an element; there is no external reference (no `http` text at all in
the default fixture, and a structural check with `html.parser`: no `<script>`, `<link>`, `<img>`, `<iframe>`, no `src`, no
`href` other than a `#fragment`, no `url(` or `@import` in CSS). The inline SVG has no XML namespace, because the namespace
is an `http://` string. The monthly returns table gets a diverging colour shade per cell; the numbers stay in the cells.
The caveats section and the equity caption are rendered from the same model as in Markdown.

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
| `tests/test_report_writer.py` | Files, links, line ends, atomicity, `FileExistsError`, path traversal, cleanup after a failed write |
| `tests/report_helpers.py` | Synthetic evaluations (equal start, late and early benchmark, insufficient overlap, costs off, benchmark in the universe, flags, insufficient warm-up) |

Part 2 adds `tests/test_report_html.py`, `tests/test_report_examples.py` (a report for each of the three example
strategies on `FakeProvider`) and `tests/test_report_network.py` (the same with real data, marked `network`). The snapshot
was generated once and read through by hand; regenerate it with `uv run python tests/test_report_markdown_snapshot.py`
after a deliberate change and review the diff line by line. The numbers in it are those of the hand-calculated fixtures
(R3b, H23); formats are tested with literals, never with project code.

## The plan items that were cut off in the discussion, restated

These were restated in full at the maintainer's request.

- **`TradeStatistics` fields:** `n_trades`, `n_buys`, `n_sells`, `per_symbol` (a dict of traded symbols, sorted, to
  `SymbolTrades(trades, buys, sells)`), `total_cost`, `average_cost_per_trade` (`float | None`).
- **Test files:** the table above (part 1) and `test_report_html.py`, `test_report_examples.py`, `test_report_network.py`
  (part 2).
- **Slug rules (D3):** see "Run id and the output folder".
- **Determinism (D2), complete:** the model and renderers are pure; `generated_at` is an explicit, timezone-aware
  argument printed in UTC; files are UTF-8 with `\n` on every OS; the snapshot test normalises `\r\n` on read.
- **Self-contained HTML (D5), complete:** see "HTML (part 2)" and [ADR 0014](adr/0014-report.md).
- **Tests of part 2:** HTML parses and is well-formed, a hostile name is escaped, no external reference, a report for
  each example strategy offline and (marked `network`) with real data read through the cache, the files exist and are
  non-empty, the HTML parses and the Markdown links resolve to existing files.
