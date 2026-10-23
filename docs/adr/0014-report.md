# 0014: Report

- **Status:** Accepted. Phase 7 is complete: part 1 delivered the model, the Markdown renderer, the charts, the run id and
  the writer; part 2 delivered the HTML renderer, `report.html` in the writer and the example reports. What part 2 decided
  beyond the text below is listed at the end of "Decision".

## Context

The result of a run is a pile of numbers in an `Evaluation`. The reader needs one file that tells the whole story: what was
run, on which data, with which assumptions, what came out next to the benchmark, and what the number does *not* mean. The
report must be reproducible (the same inputs give the same file), must not recompute a metric, must show a missing number
as "n/a" and never as `nan`, and must carry its caveats in every case. Layout, formats and the list of sections are in
[report.md](../report.md).

## Decision

- **Three layers.** `reporting/model.py` is a pure function of an `Evaluation`, a `run_id` and a `generated_at` and makes
  every display decision (what is shown, `n/a`, formats, flag explanations, the sentences about the benchmark comparison).
  The renderers (`markdown_renderer.py`, `html_renderer.py`) only read the model and escape text for their
  format. `writer.py` is the only module with file I/O. Alternative rejected: renderers that read the `Evaluation`
  themselves, which would spread formatting decisions over two places.
- **No recomputation.** The report reads `PerformanceMetrics`, `RelativeMetrics`, `Alignment`, `BacktestResult` properties
  and `monthly_returns` / `drawdown_path` of the metrics layer. The one family of numbers that did not exist, the trade
  statistics, was added to the metrics layer first (`metrics/trades.py`, fixtures T1 to T6 in
  [metrics.md](../metrics.md)), not to the rendering code. A **trade** is one fill, one row of `BacktestResult.trades`;
  the average cost per trade is the total trade cost over the number of trades, `None` with no trades.
  `deferred_orders` and `unfilled_orders` are existing fields of `BacktestResult`, shown in the same section but not part
  of the trade statistics.
- **Determinism (D2).** The model and the renderers read no clock, locale, environment variable or working directory. The
  only time in a report is the `generated_at` argument, which must be timezone-aware (a naive datetime raises
  `ValueError`) and is printed in UTC. Files are written as UTF-8 bytes with `\n` line ends on every operating system; the
  snapshot test reads its file with `\r\n` normalised, so a git checkout with autocrlf cannot break it.
- **Charts (D1): our own SVG, no dependency.** `reporting/charts.py` draws the equity and drawdown lines as SVG text with
  two-decimal coordinates. `matplotlib` would add seven packages (matplotlib, contourpy, kiwisolver, pillow,
  fonttools, pyparsing, cycler), a large `uv.lock` change and CI time on two operating systems, and its SVG output is not
  byte-stable across versions and platforms, which would defeat literal chart tests. The strategy is solid and the
  benchmark dashed (colour and line style), the colours are two slots of the reference palette with a dark variant inside
  the SVG. The Markdown report links separate `equity.svg` and `drawdown.svg` files (they carry the XML namespace); the
  HTML report embeds the same SVG inline **without** the namespace, because the namespace is an `http://` string and the
  HTML must contain none.
- **The monthly heatmap is a table**, in Markdown and in HTML (HTML adds a diverging colour shade per cell). The numbers
  are printed in every cell, so it reads without colour. The first and last month of the run carry `*` ("can be
  partial"); a month outside the run is `·`. There is no year total column (it would be a new number).
- **The equity chart has a caption that says whether the curves are comparable.** Both curves start with the same initial
  capital but each on its own first date. If the benchmark starts on the same date as the strategy, the caption says the
  curves are comparable from the first bar. If it starts later (or earlier), the caption names both first dates, says the
  curves are **not comparable over the whole chart**, and states the base rule the relative metrics used (from
  `Alignment`: `initial_equity`, or the first common date as the starting point). It is in the model, so Markdown and HTML
  show the same text.
- **Number formats (D6)** live in `reporting/format.py` and are listed in [report.md](../report.md). `None` prints as `n/a`
  (with a reason where one exists). **NaN or infinity raises a `ValueError` that names the field**, because it is a bug
  upstream and must not be hidden as "n/a". A negative zero never appears.
- **Run id (D3).** `<UTC timestamp>-<slug>-<8 hex>` built by `run_id.make_run_id(evaluation, generated_at)` outside any
  renderer, in a neutral module so the journal of Phase 8 can use the same id.
  - *Timestamp:* `generated_at` converted to UTC, `%Y%m%dT%H%M%SZ`.
  - *Slug:* the spec name folded to ASCII (NFKD, non-ASCII characters dropped), lower case, every run of characters
    outside `[a-z0-9]` becomes one `-`, leading and trailing `-` removed, cut at 40 characters (and stripped again), `run`
    if nothing is left. No character that Windows or POSIX forbids in a name, no trailing dot or space, and no Windows
    device name (`CON`, `NUL`, ...), because the id starts with the timestamp.
  - *Hash input, exactly:* the SHA-256 of the UTF-8 bytes of the text `json.dumps(payload, sort_keys=True,
    separators=(",", ":"), ensure_ascii=True)`, where `payload` is the dict with exactly these keys:
    - `"assumptions"`: `{"periods_per_year": <int>, "risk_free_rate": <float>}` of the `MetricAssumptions`;
    - `"benchmark_data_hash"`: the 64-character data hash of the benchmark run;
    - `"costs_applied"`: the `costs_applied` flag of the strategy run (`true` or `false`);
    - `"spec"`: `StrategySpec.to_dict()` of the strategy (`model_dump(mode="json")`: dates as ISO strings, all fields
      including defaults, `null` for `sizing.fraction` if unset);
    - `"strategy_data_hash"`: the 64-character data hash of the strategy run.

    The suffix is the **first 8 hexadecimal characters** of the digest. Worked example (the run R3b of
    [metrics.md](../metrics.md) with `periods_per_year` 5, as built by `tests/report_helpers.py`); this text hashes to
    `a85a59ee`, and a test checks that this block is what the code produces:

    ```json
    {"assumptions":{"periods_per_year":5,"risk_free_rate":0.0},"benchmark_data_hash":"ff487f9000d166df03fa5e84640c7524f7414b58173ed654e33fab7f1df0b094","costs_applied":true,"spec":{"benchmark":"B","costs":{"commission_bps":1000.0,"min_commission":0.0,"slippage_bps":500.0,"spread_bps":1000.0},"data":{"provider":"yfinance"},"description":"A spec used in tests.","execution":{"allow_same_bar_execution":false,"delay_bars":1,"price":"open"},"initial_capital":1000.0,"name":"Buy and hold A","period":{"end":"2024-01-08","start":"2024-01-02"},"rebalance":"on_signal","schema_version":1,"signal":{"id":"buy_and_hold","params":{}},"sizing":{"fraction":null,"method":"equal_weight"},"universe":["A"]},"strategy_data_hash":"61669f6e7476623e1289ff7dad8c8b767f36be44961c05ec4def3f45c15dd090"}
    ```

    ```python
    import hashlib

    text = open("payload.json", encoding="utf-8").read().strip()  # the block above
    print(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8])  # a85a59ee
    ```

  - *A re-run with the same inputs* at another time gets a new folder: the timestamp differs and the 8 hex characters are the
    same, so equal inputs are recognisable. The same id again (same second, same inputs) raises `FileExistsError`; there
    is no silent overwrite, and `overwrite=True` is an explicit opt-in. A run id that could leave the reports folder
    (a path separator, `..`, a drive colon, a leading dot, a trailing dot or space, a Windows device name, more than 120
    characters) is rejected, and the folder must resolve to a direct child of the reports folder.
  - *Not in the hash:* the code version (git commit) and the time. Phase 8 adds the commit to the journal.
- **A write is all or nothing (the writer).** `write_report` renders the model, the Markdown and every SVG in memory
  first and creates `reports/<run-id>/` only afterwards, so an exception while rendering (a NaN reaching the formatter,
  a naive `generated_at`) leaves nothing on disk, not even the reports folder. If a write fails half way, a folder this
  call created is removed again.
- **The caveats cannot be switched off.** `fixed_caveats()` has no parameter and returns constant text. `ReportModel`
  compares its `fixed_caveats` with `fixed_caveats()` in `__post_init__` and raises `ValueError` if they differ in any
  way (missing, empty, shortened, changed or reordered), so no renderer or writer can drop or shorten them. Run-specific
  caveats are added in a separate sub-section and never replace the fixed text. The texts contain no URL.
- **Every risk flag is explained.** Each flag code has a plain-language explanation in `reporting/caveats.py`; a test scans
  the source for every `RiskFlag("<code>"` and fails when a new code has no explanation. An unknown code at run time gets
  a fixed fallback sentence next to the engine's own message.
- **Escaping.** Every text from the spec or the data (names, symbols, validation messages) is kept raw in the model and
  escaped by the renderer: Markdown escapes `\ | ` * < > [ ] &` and turns line breaks into spaces; the HTML renderer
  escapes `& < > " '`. A table cell is never empty (`Table` rejects it), so a blank value prints as `(none)`.
- **Self-contained HTML (D5).** One file with inline CSS and inline SVG, no external font, script,
  stylesheet, image or link. The tests parse the HTML (well-formed, written to be XML-compatible so that
  `xml.etree` is a strict check), assert that a hostile strategy name such as `<script>alert(1)</script>` appears
  escaped and not as an element, and assert that there is no external reference: no `http` substring at all in the
  default fixture (the fixed caveats and the inline SVG contain none), and a structural check with `html.parser` that
  forbids `<script>`, `<link>`, `<img>`, `<iframe>`, any `src`, any `href` other than a `#fragment`, and `url(` or
  `@import` in CSS. The CSS is a plain constant string, so no template placeholder appears in the repository.
- **What part 2 decided beyond that text.**
  - *Escaping helpers.* The HTML is built with `tag` and `block`, which escape every plain `str` child and attribute value;
    only a `Markup` passes through, and element and attribute names are checked, so escaping cannot be forgotten in one
    place. Alternative rejected: f-strings with inline values.
  - *XML-illegal characters* (a NUL in a strategy name) are replaced by U+FFFD once, in `text()` of the model, so the
    Markdown, the HTML and the standalone SVG files are all covered; there is no HTML-only pass.
  - *`<!DOCTYPE html>`* needs no special handling: `xml.etree` accepts it unchanged.
  - *Heatmap shading* is by CSS class (four steps per sign, steps of 2.5 percent, cap 10 percent), computed from the
    unrounded monthly return, blue for positive and orange for negative, with light and dark colours in the CSS. These
    colours have no relation to the series colours of the charts. A test computes the WCAG contrast of every text and
    background pair in both themes (at least 4.5).
  - *Scrolling.* Every table sits in its own scroll container; the page never scrolls sideways at phone width.
  - *Writer order.* `report.html` is written last, so it exists only if everything else was written. A failure on any write
    removes the folder this call created; with `overwrite=True` the write is not atomic (a mix of new and old files is
    possible and the folder is kept). A temporary folder with a directory swap was considered and left out.
  - *Plural.* The validation line says `1 info`, `1 warning`, `1 error` and `2 infos`.
  - *Tests.* A structural snapshot of the HTML (headings with ids, table headers, row headers, figures) instead of a
    snapshot of the whole file; the example reports run offline with a `monkeypatch` socket guard and, marked `network`,
    with real data through `CachedProvider`.
- **Entry point (D7).** A plain function, `write_report(evaluation, reports_dir, *, generated_at, run_id=None,
  overwrite=False)`, with `reports_dir` the parent (`reports/`). Left out on purpose: the command line (Phase 9), the
  journal, the trial counter and the code version (Phase 8), the auditor and interpreter sections (Phase 11), the
  out-of-sample, sensitivity and regime sections (Phases 13 and 14), the deflated Sharpe ratio (Phase 15), PDF, a JSON
  export of the report, interactive charts, a log axis, a gross-equity line, a benchmark heatmap, year totals, a list of
  single trades and weight charts.

## Consequences

- A change of what the report shows or how it looks is a change of the model and of the snapshots
  `tests/snapshots/report.md` and `tests/snapshots/report_html_outline.txt`, which are reviewed by hand; a change of the hash input changes every run id suffix and needs
  an update of this ADR and of the golden id in `tests/test_run_id.py`.
- The report adds no runtime dependency and no `uv.lock` change.
- The model is a plain frozen dataclass tree, so a later phase (journal, auditor, interpreter) can add sections or read
  numbers from it without touching the renderers' escaping.
- The charts are simple on purpose: two series, linear axes, no hover. The numbers behind them are in the tables.
