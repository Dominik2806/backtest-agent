"""The writer: files, links, atomicity, the folder guards, the line ends and the sample report in memory."""

import inspect
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backtest_agent.reporting import write_report
from backtest_agent.reporting.writer import check_run_id, render_report
from report_helpers import equal_start, late_benchmark

WHEN = datetime(2026, 1, 15, 10, 30, 5, tzinfo=UTC)
GOLDEN_ID = "20260115T103005Z-buy-and-hold-a-a85a59ee"


def tree(path: Path) -> list[str]:
    return sorted(str(p.relative_to(path)) for p in path.rglob("*")) if path.exists() else []


# --- what is written ---------------


def test_the_report_and_the_two_charts_are_written_to_the_run_folder(tmp_path: Path) -> None:
    paths = write_report(equal_start(), tmp_path / "reports", generated_at=WHEN)
    assert paths.run_id == GOLDEN_ID
    assert paths.directory == tmp_path / "reports" / GOLDEN_ID
    assert tree(paths.directory) == ["drawdown.svg", "equity.svg", "report.md"]
    assert paths.markdown == paths.directory / "report.md"
    assert set(paths.files) == {paths.directory / name for name in ("report.md", "equity.svg", "drawdown.svg")}
    for path in paths.files:
        assert path.stat().st_size > 0


def test_every_relative_link_of_the_markdown_resolves_to_a_written_file(tmp_path: Path) -> None:
    paths = write_report(late_benchmark(), tmp_path, generated_at=WHEN)
    text = paths.markdown.read_text(encoding="utf-8")
    links = re.findall(r"\]\(([^)]+)\)", text)
    assert links == ["equity.svg", "drawdown.svg"]
    for link in links:
        assert (paths.directory / link).is_file()


def test_the_files_have_unix_line_ends_whatever_the_platform(tmp_path: Path) -> None:
    paths = write_report(equal_start(), tmp_path, generated_at=WHEN)
    for path in paths.files:
        data = path.read_bytes()
        assert b"\r" not in data and data.endswith(b"\n")
        data.decode("utf-8")


def test_the_written_markdown_is_the_rendered_markdown(tmp_path: Path) -> None:
    rendered = render_report(equal_start(), run_id=GOLDEN_ID, generated_at=WHEN)
    paths = write_report(equal_start(), tmp_path, generated_at=WHEN)
    assert list(rendered) == ["report.md", "equity.svg", "drawdown.svg"]
    for name, text in rendered.items():
        assert (paths.directory / name).read_bytes() == text.encode("utf-8")


def test_the_standalone_charts_carry_the_namespace(tmp_path: Path) -> None:
    paths = write_report(equal_start(), tmp_path, generated_at=WHEN)
    for name in ("equity.svg", "drawdown.svg"):
        assert (
            (paths.directory / name).read_text(encoding="utf-8").startswith('<svg xmlns="http://www.w3.org/2000/svg"')
        )


def test_the_reports_folder_is_created_when_it_is_missing(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "reports"
    assert not target.exists()
    write_report(equal_start(), target, generated_at=WHEN)
    assert (target / GOLDEN_ID / "report.md").is_file()


def test_a_given_run_id_is_used(tmp_path: Path) -> None:
    paths = write_report(equal_start(), tmp_path, generated_at=WHEN, run_id="my-run_1.0")
    assert paths.directory == tmp_path / "my-run_1.0" and (paths.directory / "report.md").is_file()
    assert "`my-run_1.0`" in paths.markdown.read_text(encoding="utf-8")


def test_the_signature_has_no_parameter_that_touches_the_caveats() -> None:
    names = list(inspect.signature(write_report).parameters)
    assert names == ["evaluation", "reports_dir", "generated_at", "run_id", "overwrite"]


# --- atomicity ---------------


def test_a_failure_while_rendering_leaves_nothing_on_disk(tmp_path: Path) -> None:
    evaluation = equal_start()
    broken = replace(evaluation, metrics=replace(evaluation.metrics, sharpe=float("nan")))
    target = tmp_path / "reports"
    with pytest.raises(ValueError, match="strategy.sharpe"):
        write_report(broken, target, generated_at=WHEN)
    assert not target.exists()  # not even the reports folder


def test_a_failure_while_rendering_leaves_an_existing_reports_folder_untouched(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("x")
    evaluation = equal_start()
    broken = replace(evaluation, relative=replace(evaluation.relative, excess_return=float("inf")))
    with pytest.raises(ValueError, match="excess_return"):
        write_report(broken, tmp_path, generated_at=WHEN)
    assert tree(tmp_path) == ["keep.txt"]


def test_a_naive_generated_at_leaves_nothing_on_disk(tmp_path: Path) -> None:
    target = tmp_path / "reports"
    with pytest.raises(ValueError, match="timezone-aware"):
        write_report(equal_start(), target, generated_at=datetime(2026, 1, 15, 10, 30, 5))
    assert not target.exists()


def test_a_failure_while_writing_removes_the_folder_it_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = Path.write_bytes
    calls = []

    def failing(self: Path, data: bytes) -> int:
        calls.append(self.name)
        if len(calls) == 2:
            raise OSError("disk full")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", failing)
    with pytest.raises(OSError, match="disk full"):
        write_report(equal_start(), tmp_path / "reports", generated_at=WHEN)
    assert calls == ["report.md", "equity.svg"]
    assert tree(tmp_path / "reports") == []  # the run folder is gone again


def test_a_failure_while_overwriting_keeps_the_existing_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_report(equal_start(), tmp_path, generated_at=WHEN)
    real = Path.write_bytes

    def failing(self: Path, data: bytes) -> int:
        if self.name == "equity.svg":
            raise OSError("disk full")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", failing)
    with pytest.raises(OSError, match="disk full"):
        write_report(equal_start(), tmp_path, generated_at=WHEN, overwrite=True)
    assert (tmp_path / GOLDEN_ID).is_dir()


# --- the folder guards ---------------


def test_an_existing_run_folder_is_not_overwritten(tmp_path: Path) -> None:
    first = write_report(equal_start(), tmp_path, generated_at=WHEN)
    first.markdown.write_text("edited by hand", encoding="utf-8")
    with pytest.raises(FileExistsError, match="overwrite=True"):
        write_report(equal_start(), tmp_path, generated_at=WHEN)
    assert first.markdown.read_text(encoding="utf-8") == "edited by hand"


def test_overwrite_true_replaces_the_files(tmp_path: Path) -> None:
    first = write_report(equal_start(), tmp_path, generated_at=WHEN)
    first.markdown.write_text("edited by hand", encoding="utf-8")
    again = write_report(equal_start(), tmp_path, generated_at=WHEN, overwrite=True)
    assert again.directory == first.directory
    assert again.markdown.read_text(encoding="utf-8").startswith("# Backtest report")


def test_the_same_inputs_at_another_time_go_to_a_new_folder(tmp_path: Path) -> None:
    first = write_report(equal_start(), tmp_path, generated_at=WHEN)
    second = write_report(equal_start(), tmp_path, generated_at=datetime(2026, 1, 15, 10, 30, 6, tzinfo=UTC))
    assert first.directory != second.directory
    assert first.run_id.split("-")[-1] == second.run_id.split("-")[-1]  # the same inputs, recognisable


@pytest.mark.parametrize(
    "bad",
    [
        "../escape",
        "..",
        ".",
        "a/b",
        "a\\b",
        "C:evil",
        "/abs",
        "",
        ".hidden",
        "trailing.",
        "trailing ",
        "a..b",
        "x" * 121,
        "CON",
        "nul.txt",
        "com1",
        "has space",
        "new\nline",
    ],
)
def test_a_run_id_that_could_leave_the_folder_is_rejected(tmp_path: Path, bad: str) -> None:
    target = tmp_path / "reports"
    with pytest.raises(ValueError, match="safe run id"):
        write_report(equal_start(), target, generated_at=WHEN, run_id=bad)
    assert not target.exists() and tree(tmp_path) == []


@pytest.mark.parametrize("good", ["20260115T103005Z-name-ab12cd34", "a", "A.b_c-d", "x" * 120, "console", "con-1"])
def test_ordinary_run_ids_pass(good: str) -> None:
    assert check_run_id(good) == good


def test_a_folder_that_would_resolve_outside_the_reports_folder_is_rejected(tmp_path: Path, monkeypatch) -> None:
    # Defence in depth: even if a run id passed the name check, the folder must be directly inside reports_dir.
    monkeypatch.setattr("backtest_agent.reporting.writer.check_run_id", lambda run_id: "../outside")
    with pytest.raises(ValueError, match="directly inside"):
        write_report(equal_start(), tmp_path / "reports", generated_at=WHEN)
    assert not (tmp_path / "outside").exists()
