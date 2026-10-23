"""The only place of the report package that touches the file system.

See docs/report.md, sections "Using it" and "Run id and the output folder".

``render_report`` builds every file of a report in memory. ``write_report`` calls it first and creates
``<reports_dir>/<run-id>/`` only if that worked, so a failure while rendering (for example a NaN reaching the formatter)
leaves nothing on disk. An existing folder is never overwritten unless ``overwrite=True``. Files are written as UTF-8
bytes with ``\\n`` line ends on every operating system.

With ``overwrite=True`` the write is not atomic: if a write fails part-way, the folder is kept and can hold a mix of new
and old files. Files that this call does not write are left alone. Delete the folder and write again if that matters.
"""

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from backtest_agent.metrics.evaluation import Evaluation
from backtest_agent.reporting.charts import line_chart_svg
from backtest_agent.reporting.html_renderer import render_html
from backtest_agent.reporting.markdown_renderer import render_markdown
from backtest_agent.reporting.model import build_report_model
from backtest_agent.run_id import check_run_id, make_run_id

REPORT_MD = "report.md"
REPORT_HTML = "report.html"


@dataclass(frozen=True)
class ReportPaths:
    """Where a report was written."""

    directory: Path
    run_id: str
    files: tuple[Path, ...]

    @property
    def markdown(self) -> Path:
        return self.directory / REPORT_MD

    @property
    def html(self) -> Path:
        return self.directory / REPORT_HTML


def render_report(evaluation: Evaluation, *, run_id: str, generated_at: datetime) -> dict[str, str]:
    """All files of a report as text, by file name, rendered in memory. Nothing is written.

    The order is the order of writing: the HTML report, which embeds the charts and is the file a reader opens, is last.
    """
    model = build_report_model(evaluation, run_id=run_id, generated_at=generated_at)
    charts = model.charts
    return {
        REPORT_MD: render_markdown(model),
        charts.equity_file: line_chart_svg(charts.equity, standalone=True),
        charts.drawdown_file: line_chart_svg(charts.drawdown, standalone=True),
        REPORT_HTML: render_html(model),
    }


def write_report(
    evaluation: Evaluation,
    reports_dir: Path | str,
    *,
    generated_at: datetime,
    run_id: str | None = None,
    overwrite: bool = False,
) -> ReportPaths:
    """Write the report of ``evaluation`` to ``<reports_dir>/<run-id>/`` and return the paths.

    ``generated_at`` must be timezone-aware. The run id is ``make_run_id(evaluation, generated_at)`` unless one is
    given (checked by ``check_run_id``). Everything is rendered before the folder is created. Raises
    ``FileExistsError`` if the folder exists and ``overwrite`` is False. If writing a file fails, a folder that this
    call created is removed again.
    """
    chosen = check_run_id(run_id if run_id is not None else make_run_id(evaluation, generated_at))
    files = render_report(evaluation, run_id=chosen, generated_at=generated_at)  # may raise: nothing is on disk yet

    base = Path(reports_dir)
    directory = base / chosen
    if directory.resolve().parent != base.resolve():
        raise ValueError(f"the run folder {directory} would not be directly inside {base}")
    existed = directory.exists()
    if existed and not overwrite:
        raise FileExistsError(f"{directory} already exists; pass overwrite=True to replace its files")
    directory.mkdir(parents=True, exist_ok=overwrite)
    try:
        written = []
        for name, text in files.items():
            path = directory / name
            path.write_bytes(text.encode("utf-8"))
            written.append(path)
    except BaseException:
        if not existed:
            shutil.rmtree(directory, ignore_errors=True)
        raise
    return ReportPaths(directory=directory, run_id=chosen, files=tuple(written))
