"""Reporting: Markdown and HTML reports with charts and caveats (F-14; see docs/report.md)."""

from backtest_agent.reporting.caveats import Caveat, fixed_caveats
from backtest_agent.reporting.html_renderer import render_html
from backtest_agent.reporting.markdown_renderer import render_markdown
from backtest_agent.reporting.model import ReportModel, build_report_model
from backtest_agent.reporting.writer import ReportPaths, render_report, write_report

__all__ = [
    "Caveat",
    "ReportModel",
    "ReportPaths",
    "build_report_model",
    "fixed_caveats",
    "render_html",
    "render_markdown",
    "render_report",
    "write_report",
]
