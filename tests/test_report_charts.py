"""SVG charts: hand-calculated ticks, coordinates and paths of tiny inputs, degenerate inputs, escaping and guards.

Geometry used below (charts.py): canvas 720 x 360, plot area x from 72 to 696 (width 624), y from 56 to 316
(height 260). x(day) = 72 + days since the first date / span in days * 624;
y(v) = 56 + (top tick - v) / (top tick - bottom tick) * 260.
"""

import xml.etree.ElementTree as ET
from datetime import date

import pytest

from backtest_agent.reporting.charts import (
    chart_frame,
    date_ticks,
    line_chart_svg,
    nice_ticks,
    path_data,
    series_points,
)
from backtest_agent.reporting.model import ChartSeries, LineChart

DAYS4 = ("2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04")


def equity(*series: ChartSeries, title: str = "Equity") -> LineChart:
    return LineChart(title, "equity", "An equity chart.", tuple(series))


def drawdown(*series: ChartSeries) -> LineChart:
    return LineChart("Drawdown", "drawdown", "A drawdown chart.", tuple(series))


def texts(svg: str) -> list[str]:
    root = ET.fromstring(svg)
    return ["".join(el.itertext()) for el in root.iter("{http://www.w3.org/2000/svg}text")]


# --- ticks ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "low, high, ticks",
    [
        (99, 121, [95, 100, 105, 110, 115, 120, 125]),  # range 22 / 5 = 4.4 -> step 5
        (0, 1000, [0, 200, 400, 600, 800, 1000]),
        (-0.12, 0, [-0.15, -0.10, -0.05, 0.0]),  # 0.12 / 5 = 0.024 -> step 0.05
        (-0.1, 0, [-0.10, -0.08, -0.06, -0.04, -0.02, 0.0]),
        (0.5, 1.5, [0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6]),
        (94, 106, [90, 95, 100, 105, 110]),  # 12 / 5 = 2.4 -> step 5
    ],
)
def test_nice_ticks(low, high, ticks) -> None:
    assert nice_ticks(low, high) == pytest.approx(ticks, abs=1e-12)


@pytest.mark.parametrize("low, high", [(1, 1), (2, 1), (float("nan"), 1), (0, float("inf"))])
def test_nice_ticks_rejects_an_empty_or_invalid_range(low, high) -> None:
    with pytest.raises(ValueError, match="nice_ticks"):
        nice_ticks(low, high)


def test_date_ticks_by_span() -> None:
    years = date_ticks(date(2010, 1, 4), date(2023, 12, 29))  # step 1 gives 13 ticks, step 2 gives 6
    assert [label for _, label in years] == ["2012", "2014", "2016", "2018", "2020", "2022"]
    assert years[0][0] == date(2012, 1, 1)
    months = date_ticks(date(2024, 1, 2), date(2024, 6, 28))
    assert [d.isoformat() for d, _ in months] == ["2024-02-01", "2024-03-01", "2024-04-01", "2024-05-01", "2024-06-01"]
    assert [label for _, label in months] == ["2024-02", "2024-03", "2024-04", "2024-05", "2024-06"]
    days = date_ticks(date(2024, 1, 2), date(2024, 1, 8))
    assert [label for _, label in days] == [f"2024-01-0{d}" for d in range(2, 9)]
    assert date_ticks(date(2024, 1, 2), date(2024, 1, 2)) == [(date(2024, 1, 2), "2024-01-02")]


# --- coordinates of a tiny equity path ------------------------------------------------------------


def test_the_points_and_the_path_of_a_four_point_equity() -> None:
    # Values 100, 110, 99, 121: ticks 95 ... 125 (30 high). x: 72, 280, 488, 696 (3 days span, 208 per day).
    # y(100) = 56 + 25/30 * 260 = 272.67; y(110) = 56 + 15/30 * 260 = 186; y(99) = 56 + 26/30 * 260 = 281.33;
    # y(121) = 56 + 4/30 * 260 = 90.67.
    series = ChartSeries("S", DAYS4, (100.0, 110.0, 99.0, 121.0))
    chart = equity(series)
    frame = chart_frame(chart)
    assert frame.y_ticks == pytest.approx((95, 100, 105, 110, 115, 120, 125))
    points = series_points(series, frame)
    flat = [c for point in points for c in point]
    assert flat == pytest.approx([72, 272.6666667, 280, 186.0, 488, 281.3333333, 696, 90.6666667], abs=1e-6)
    assert path_data(points) == "M72.00,272.67 L280.00,186.00 L488.00,281.33 L696.00,90.67"
    svg = line_chart_svg(chart, standalone=True)
    assert '<path class="bt-line bt-s1" d="M72.00,272.67 L280.00,186.00 L488.00,281.33 L696.00,90.67"/>' in svg
    assert texts(svg)[-4:] == ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]  # the x axis, day ticks


def test_the_y_axis_labels_and_gridlines_of_the_four_point_equity() -> None:
    svg = line_chart_svg(equity(ChartSeries("S", DAYS4, (100.0, 110.0, 99.0, 121.0))), standalone=True)
    labels = texts(svg)
    for tick in ("95", "100", "105", "110", "115", "120", "125"):
        assert tick in labels
    assert svg.count('class="bt-grid"') == 7
    assert '<line class="bt-grid" x1="72" y1="56.00" x2="696" y2="56.00"/>' in svg  # the 125 line is the top
    assert '<line class="bt-grid" x1="72" y1="316.00" x2="696" y2="316.00"/>' in svg  # the 95 line is the bottom


def test_the_points_and_path_of_a_drawdown() -> None:
    # Values 0, 0, -0.1, 0: ticks -0.10 ... 0 (0.10 high). y(0) = 56; y(-0.1) = 316.
    series = ChartSeries("S", DAYS4, (0.0, 0.0, -0.1, 0.0))
    frame = chart_frame(drawdown(series))
    assert frame.y_ticks == pytest.approx((-0.10, -0.08, -0.06, -0.04, -0.02, 0.0))
    assert path_data(series_points(series, frame)) == "M72.00,56.00 L280.00,56.00 L488.00,316.00 L696.00,56.00"
    labels = texts(line_chart_svg(drawdown(series), standalone=True))
    for tick in ("-10%", "-8%", "-6%", "-4%", "-2%", "0%"):
        assert tick in labels


def test_two_series_on_their_own_dates_share_one_time_axis() -> None:
    strategy = ChartSeries("S", ("2024-01-02", "2024-01-08"), (100.0, 110.0))
    benchmark = ChartSeries("B", ("2024-01-04", "2024-01-08"), (100.0, 105.0), dashed=True)
    frame = chart_frame(equity(strategy, benchmark))
    assert (frame.first, frame.last) == (date(2024, 1, 2), date(2024, 1, 8))
    assert series_points(benchmark, frame)[0][0] == pytest.approx(72 + 2 / 6 * 624)  # 280.00
    assert series_points(strategy, frame)[0][0] == 72 and series_points(strategy, frame)[-1][0] == 696


def test_the_strategy_is_drawn_after_the_benchmark_and_the_benchmark_is_dashed() -> None:
    strategy = ChartSeries("S", DAYS4, (100.0, 101.0, 102.0, 103.0))
    benchmark = ChartSeries("B", DAYS4, (100.0, 100.0, 100.0, 100.0), dashed=True)
    svg = line_chart_svg(equity(strategy, benchmark), standalone=True)
    assert svg.index('<path class="bt-line bt-s2 bt-dash"') < svg.index('<path class="bt-line bt-s1"')
    assert svg.count('bt-s2 bt-dash"') == 2 and 'bt-s1 bt-dash"' not in svg  # the legend sample and the path
    assert '<line class="bt-line bt-s2 bt-dash"' in svg and '<line class="bt-line bt-s1"' in svg


# --- degenerate inputs ----------------------------------------------------------------------------


def test_one_bar_is_a_dot_at_the_centre_and_has_no_path() -> None:
    svg = line_chart_svg(equity(ChartSeries("S", ("2024-01-02",), (1000.0,))), standalone=False)
    ET.fromstring(svg.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1))
    assert "<path" not in svg
    assert '<circle class="bt-dot1" cx="384.00" cy="186.00" r="4"/>' in svg  # x: 72 + 312; y: middle of 900 ... 1100
    assert texts(svg.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1))[-1] == "2024-01-02"


def test_flat_equity_is_a_straight_line_in_the_middle() -> None:
    # 100, 100, 100: padded by 5 to 95 ... 105, ticks 94 ... 106 (12 high): y(100) = 56 + 6 / 12 * 260 = 186.
    series = ChartSeries("S", DAYS4[:3], (100.0, 100.0, 100.0))
    frame = chart_frame(equity(series))
    assert frame.y_ticks == pytest.approx((94, 96, 98, 100, 102, 104, 106))
    assert path_data(series_points(series, frame)) == "M72.00,186.00 L384.00,186.00 L696.00,186.00"


def test_all_zero_returns_give_a_drawdown_on_the_zero_line_with_a_one_percent_axis() -> None:
    series = ChartSeries("S", DAYS4[:3], (0.0, 0.0, 0.0))
    frame = chart_frame(drawdown(series))
    assert frame.y_ticks == pytest.approx((-0.01, -0.008, -0.006, -0.004, -0.002, 0.0))
    assert path_data(series_points(series, frame)) == "M72.00,56.00 L384.00,56.00 L696.00,56.00"
    labels = texts(line_chart_svg(drawdown(series), standalone=True))
    assert "-1.0%" in labels and "0.0%" in labels


def test_equity_that_went_to_zero_ends_on_the_bottom_line() -> None:
    series = ChartSeries("S", DAYS4[:3], (1000.0, 500.0, 0.0))
    frame = chart_frame(equity(series))
    assert frame.y_ticks == pytest.approx((0, 200, 400, 600, 800, 1000))
    assert path_data(series_points(series, frame)) == "M72.00,56.00 L384.00,186.00 L696.00,316.00"


def test_a_ruined_drawdown_reaches_minus_one() -> None:
    series = ChartSeries("S", DAYS4[:3], (0.0, -0.5, -1.0))
    frame = chart_frame(drawdown(series))
    assert frame.y_low == pytest.approx(-1.0) and frame.y_high == 0.0
    assert series_points(series, frame)[-1][1] == pytest.approx(316.0)


# --- format of the output -------------------------------------------------------------------------


def test_standalone_has_the_namespace_and_inline_has_no_http_text_at_all() -> None:
    chart = equity(ChartSeries("S", DAYS4, (100.0, 110.0, 99.0, 121.0)))
    standalone, inline = line_chart_svg(chart, standalone=True), line_chart_svg(chart, standalone=False)
    assert standalone.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 360"')
    assert ET.fromstring(standalone).tag == "{http://www.w3.org/2000/svg}svg"
    assert "http" not in inline and "xmlns" not in inline
    assert inline == standalone.replace(' xmlns="http://www.w3.org/2000/svg"', "", 1)


def test_the_output_is_deterministic_and_has_no_nan() -> None:
    chart = equity(ChartSeries("S", DAYS4, (100.0, 110.0, 99.0, 121.0)))
    assert line_chart_svg(chart, standalone=True) == line_chart_svg(chart, standalone=True)
    assert "nan" not in line_chart_svg(chart, standalone=True).lower()


def test_hostile_labels_are_escaped() -> None:
    label = '<script>alert(1)</script> & "q"'
    chart = LineChart("T <b>", "equity", "D <i> & more", (ChartSeries(label, DAYS4, (1.0, 2.0, 3.0, 4.0)),))
    svg = line_chart_svg(chart, standalone=True)
    root = ET.fromstring(svg)  # well-formed
    assert "<script>" not in svg and "&lt;script&gt;" in svg
    assert not list(root.iter("{http://www.w3.org/2000/svg}script"))
    assert any(label == t for t in texts(svg))
    assert "".join(root.find("{http://www.w3.org/2000/svg}title").itertext()) == "T <b>"


def test_a_long_label_is_cut_in_the_legend_but_not_in_the_description() -> None:
    long = "x" * 60
    chart = LineChart("T", "equity", f"About {long}", (ChartSeries(long, DAYS4, (1.0, 2.0, 3.0, 4.0)),))
    svg = line_chart_svg(chart, standalone=True)
    assert "x" * 37 + "..." in texts(svg) and long not in texts(svg)
    assert long in svg  # the description keeps the whole name


def test_the_ids_are_unique_per_chart_kind() -> None:
    a = line_chart_svg(equity(ChartSeries("S", DAYS4, (1.0, 2.0, 3.0, 4.0))), standalone=False)
    b = line_chart_svg(drawdown(ChartSeries("S", DAYS4, (0.0, 0.0, -0.1, 0.0))), standalone=False)
    assert 'id="bt-equity-title"' in a and 'id="bt-drawdown-title"' in b


# --- guards ---------------------------------------------------------------------------------------


def test_no_series_or_too_many_series_raise() -> None:
    one = ChartSeries("S", DAYS4, (1.0, 2.0, 3.0, 4.0))
    with pytest.raises(ValueError, match="1 to 2 series"):
        line_chart_svg(equity(), standalone=True)
    with pytest.raises(ValueError, match="1 to 2 series"):
        line_chart_svg(equity(one, one, one), standalone=True)


@pytest.mark.parametrize(
    "series, message",
    [
        (ChartSeries("S", (), ()), "non-empty"),
        (ChartSeries("S", DAYS4, (1.0, 2.0)), "same length"),
        (ChartSeries("S", DAYS4, (1.0, float("nan"), 3.0, 4.0)), "finite"),
        (ChartSeries("S", DAYS4, (1.0, float("inf"), 3.0, 4.0)), "finite"),
        (ChartSeries("S", ("2024-01-02", "2024-01-02"), (1.0, 2.0)), "strictly increasing"),
        (ChartSeries("S", ("2024-01-03", "2024-01-02"), (1.0, 2.0)), "strictly increasing"),
    ],
)
def test_invalid_series_raise(series, message) -> None:
    with pytest.raises(ValueError, match=message):
        line_chart_svg(equity(series), standalone=True)


def test_an_unknown_kind_and_an_impossible_drawdown_raise() -> None:
    series = ChartSeries("S", DAYS4, (0.0, 0.0, -0.1, 0.0))
    with pytest.raises(ValueError, match="unknown chart kind"):
        line_chart_svg(LineChart("T", "bars", "d", (series,)), standalone=True)
    with pytest.raises(ValueError, match="between -1 and 0"):
        line_chart_svg(drawdown(ChartSeries("S", DAYS4, (0.0, 0.1, 0.0, 0.0))), standalone=True)
    with pytest.raises(ValueError, match="between -1 and 0"):
        line_chart_svg(drawdown(ChartSeries("S", DAYS4, (0.0, -1.5, 0.0, 0.0))), standalone=True)
