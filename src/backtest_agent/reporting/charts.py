"""SVG line charts of the report (equity against benchmark, drawdown), written by hand: no dependency, no network.

``line_chart_svg`` is a pure function of a ``LineChart`` of the report model. Every coordinate is printed with two
decimals, so the output is stable across platforms and the tests can compare exact numbers. A series is told apart by
colour *and* line style (the benchmark is dashed), so the chart reads in greyscale; the numbers behind it are in the
tables of the report. The standalone file (``standalone=True``, for the Markdown report) carries the XML namespace; the
inline version for the HTML report does not, so that the HTML contains no ``http`` text at all.

Layout, in SVG user units: a 720 x 360 canvas, the plot area inside the margins ``LEFT``, ``RIGHT``, ``TOP`` and
``BOTTOM``.
The x axis is linear in calendar days from the first to the last date of all series; the y axis runs over the "nice"
tick range that covers the data (1, 2 or 5 times a power of ten).
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta
from html import escape

from backtest_agent.reporting import format as fmt
from backtest_agent.reporting.model import ChartSeries, LineChart

WIDTH, HEIGHT = 720, 360
LEFT, RIGHT, TOP, BOTTOM = 72, 24, 56, 44
PLOT_WIDTH = WIDTH - LEFT - RIGHT  # 624
PLOT_HEIGHT = HEIGHT - TOP - BOTTOM  # 260
MAX_SERIES = 2
MAX_X_TICKS = 7
LEGEND_LABEL_LIMIT = 40

# Colours: categorical slots 1 and 2 of the reference palette (blue, orange), light and dark surface; the CSS lives in
# the SVG so a standalone file and an inline chart look the same. Plain string, not an f-string.
STYLE = (
    ".bt-bg{fill:#fcfcfb}.bt-text{fill:#0b0b0b;font:12px sans-serif}.bt-muted{fill:#52514e;font:11px sans-serif}"
    ".bt-heading{fill:#0b0b0b;font:600 14px sans-serif}"
    ".bt-grid{stroke:#e3e2de;stroke-width:1}.bt-axis{stroke:#9a998f;stroke-width:1}"
    ".bt-line{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}"
    ".bt-s1{stroke:#2a78d6}.bt-s2{stroke:#eb6834}.bt-dash{stroke-dasharray:6 4}"
    ".bt-dot1{fill:#2a78d6}.bt-dot2{fill:#eb6834}"
    "@media (prefers-color-scheme: dark){"
    ".bt-bg{fill:#1a1a19}.bt-text{fill:#f0efec}.bt-muted{fill:#c3c2b7}.bt-heading{fill:#f0efec}"
    ".bt-grid{stroke:#3a3a37}.bt-axis{stroke:#77766e}.bt-s1{stroke:#3987e5}.bt-s2{stroke:#d95926}"
    ".bt-dot1{fill:#3987e5}.bt-dot2{fill:#d95926}}"
)


def nice_ticks(low: float, high: float, target: int = 5) -> list[float]:
    """Tick values at a step of 1, 2 or 5 times a power of ten that cover ``[low, high]`` (first tick <= low).

    About ``target`` intervals; ``low < high`` is required.
    """
    if not (math.isfinite(low) and math.isfinite(high)) or low >= high:
        raise ValueError(f"nice_ticks needs finite low < high, got {low!r}, {high!r}")
    raw = (high - low) / target
    exponent = math.floor(math.log10(raw))
    mantissa = raw / 10**exponent
    step = next(m for m in (1, 2, 5, 10) if mantissa <= m + 1e-12) * 10.0**exponent
    first, last = math.floor(low / step + 1e-12), math.ceil(high / step - 1e-12)
    return [round(i * step, 12) for i in range(first, last + 1)]


def date_ticks(first: date, last: date) -> list[tuple[date, str]]:
    """Dates and labels for the x axis: years (``2012``), months (``2024-02``) or days (``2024-01-03``) by span."""
    span = (last - first).days
    if span <= 0:
        return [(first, first.isoformat())]
    if span >= 2 * 365:
        for step in (1, 2, 5, 10, 20, 50):
            years = [y for y in range(first.year, last.year + 1) if y % step == 0 and first <= date(y, 1, 1) <= last]
            if 0 < len(years) <= MAX_X_TICKS:
                return [(date(y, 1, 1), str(y)) for y in years]
    if span >= 60:
        for step in (1, 2, 3, 6, 12):
            months = []
            year, month = first.year, first.month
            while (year, month) <= (last.year, last.month):
                if (month - 1) % step == 0 and first <= date(year, month, 1) <= last:
                    months.append(date(year, month, 1))
                year, month = (year + 1, 1) if month == 12 else (year, month + 1)
            if 0 < len(months) <= MAX_X_TICKS:
                return [(d, f"{d.year:04d}-{d.month:02d}") for d in months]
    for step in (1, 2, 7, 14, 30, 61, 122, 365):
        days = [first + timedelta(days=k) for k in range(0, span + 1, step)]
        if len(days) <= MAX_X_TICKS:
            return [(d, d.isoformat()) for d in days]
    raise AssertionError("unreachable: a step of 365 days gives at most 7 ticks below 2 * 365 days")  # pragma: no cover


@dataclass(frozen=True)
class Frame:
    """The mapping from dates and values to canvas coordinates of one chart."""

    first: date
    last: date
    y_ticks: tuple[float, ...]

    @property
    def y_low(self) -> float:
        return self.y_ticks[0]

    @property
    def y_high(self) -> float:
        return self.y_ticks[-1]

    def x(self, day: date) -> float:
        span = (self.last - self.first).days
        if span == 0:
            return LEFT + PLOT_WIDTH / 2
        return LEFT + (day - self.first).days / span * PLOT_WIDTH

    def y(self, value: float) -> float:
        return TOP + (self.y_high - value) / (self.y_high - self.y_low) * PLOT_HEIGHT


def _check(chart: LineChart) -> list[tuple[ChartSeries, list[date]]]:
    if not 1 <= len(chart.series) <= MAX_SERIES:
        raise ValueError(f"a chart needs 1 to {MAX_SERIES} series, got {len(chart.series)}")
    parsed = []
    for series in chart.series:
        if not series.dates or len(series.dates) != len(series.values):
            raise ValueError(f"series {series.label!r}: dates and values must be non-empty and of the same length")
        if not all(math.isfinite(v) for v in series.values):
            raise ValueError(f"series {series.label!r}: values must be finite")
        days = [date.fromisoformat(d) for d in series.dates]
        if any(b <= a for a, b in zip(days, days[1:], strict=False)):
            raise ValueError(f"series {series.label!r}: dates must be strictly increasing")
        parsed.append((series, days))
    return parsed


def chart_frame(chart: LineChart) -> Frame:
    """The axes of a chart: the date range of all series and the nice y range that covers all values.

    Equity: a flat series gets a margin of 5 percent (at least 1) around it. Drawdown: the top is exactly 0 and a
    chart without any drawdown spans -1 percent to 0.
    """
    parsed = _check(chart)
    first = min(days[0] for _, days in parsed)
    last = max(days[-1] for _, days in parsed)
    values = [v for series, _ in parsed for v in series.values]
    low, high = min(values), max(values)
    if chart.kind == "drawdown":
        if high > 1e-12 or low < -1.0 - 1e-12:
            raise ValueError("drawdown values must lie between -1 and 0")
        low, high = min(low, -0.01), 0.0
    elif chart.kind == "equity":
        if low == high:
            pad = max(abs(low) * 0.05, 1.0)
            low, high = low - pad, high + pad
    else:
        raise ValueError(f"unknown chart kind {chart.kind!r}")
    return Frame(first, last, tuple(nice_ticks(low, high)))


def series_points(series: ChartSeries, frame: Frame) -> list[tuple[float, float]]:
    """Canvas coordinates of the points of a series."""
    return [(frame.x(date.fromisoformat(d)), frame.y(v)) for d, v in zip(series.dates, series.values, strict=True)]


def _xy(point: tuple[float, float]) -> str:
    return f"{point[0]:.2f},{point[1]:.2f}"


def path_data(points: list[tuple[float, float]]) -> str:
    """``M x,y L x,y ...`` with two decimals."""
    return "M" + " L".join(_xy(p) for p in points)


def _y_label(chart: LineChart, value: float, step: float) -> str:
    if chart.kind == "drawdown":
        decimals = max(0, -math.floor(math.log10(step * 100) + 1e-9))
        return fmt.percent(value, "chart y tick", decimals=decimals)
    decimals = max(0, -math.floor(math.log10(step) + 1e-9))
    return fmt.number(value, "chart y tick", decimals=decimals)


def _legend_label(label: str) -> str:
    return label if len(label) <= LEGEND_LABEL_LIMIT else label[: LEGEND_LABEL_LIMIT - 3] + "..."


def line_chart_svg(chart: LineChart, *, standalone: bool, id_prefix: str | None = None) -> str:
    """The SVG text of ``chart``. ``standalone`` adds the XML namespace (a file); inline SVG in HTML leaves it out."""
    parsed = _check(chart)
    frame = chart_frame(chart)
    prefix = id_prefix or f"bt-{chart.kind}"
    step = frame.y_ticks[1] - frame.y_ticks[0] if len(frame.y_ticks) > 1 else 1.0
    out: list[str] = []
    ns = ' xmlns="http://www.w3.org/2000/svg"' if standalone else ""
    out.append(
        f'<svg{ns} viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" role="img" '
        f'aria-labelledby="{prefix}-title {prefix}-desc">'
    )
    out.append(f'<title id="{prefix}-title">{escape(chart.title)}</title>')
    out.append(f'<desc id="{prefix}-desc">{escape(chart.description)}</desc>')
    out.append(f"<style>{STYLE}</style>")
    out.append(f'<rect class="bt-bg" x="0" y="0" width="{WIDTH}" height="{HEIGHT}"/>')
    out.append(f'<text class="bt-heading" x="{LEFT}" y="22">{escape(chart.title)}</text>')

    legend_x = float(LEFT)
    for index, (series, _) in enumerate(parsed, start=1):
        dash = " bt-dash" if series.dashed else ""
        sample_end = legend_x + 24
        out.append(
            f'<line class="bt-line bt-s{index}{dash}" x1="{legend_x:.2f}" y1="40.00" x2="{sample_end:.2f}" y2="40.00"/>'
        )
        label = _legend_label(series.label)
        out.append(f'<text class="bt-text" x="{legend_x + 30:.2f}" y="44.00">{escape(label)}</text>')
        legend_x += 30 + 7 * len(label) + 24

    for tick in frame.y_ticks:
        y = frame.y(tick)
        out.append(f'<line class="bt-grid" x1="{LEFT}" y1="{y:.2f}" x2="{WIDTH - RIGHT}" y2="{y:.2f}"/>')
        out.append(
            f'<text class="bt-muted" x="{LEFT - 8}" y="{y + 4:.2f}" text-anchor="end">'
            f"{escape(_y_label(chart, tick, step))}</text>"
        )
    out.append(
        f'<line class="bt-axis" x1="{LEFT}" y1="{TOP + PLOT_HEIGHT}" x2="{WIDTH - RIGHT}" y2="{TOP + PLOT_HEIGHT}"/>'
    )
    for day, label in date_ticks(frame.first, frame.last):
        x = frame.x(day)
        out.append(
            f'<line class="bt-axis" x1="{x:.2f}" y1="{TOP + PLOT_HEIGHT}" x2="{x:.2f}" y2="{TOP + PLOT_HEIGHT + 5}"/>'
        )
        out.append(
            f'<text class="bt-muted" x="{x:.2f}" y="{TOP + PLOT_HEIGHT + 20}" text-anchor="middle">'
            f"{escape(label)}</text>"
        )

    # The first series (the strategy) is drawn last, so it lies on top of the benchmark.
    for index, (series, _) in reversed(list(enumerate(parsed, start=1))):
        points = series_points(series, frame)
        dash = " bt-dash" if series.dashed else ""
        if len(points) == 1:
            x, y = points[0]
            out.append(f'<circle class="bt-dot{index}" cx="{x:.2f}" cy="{y:.2f}" r="4"/>')
        else:
            out.append(f'<path class="bt-line bt-s{index}{dash}" d="{path_data(points)}"/>')
    out.append("</svg>")
    return "\n".join(out) + "\n"
