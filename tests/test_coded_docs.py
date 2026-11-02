"""docs/coded-signals.md is true: its digests, its worked example and its numbers are the ones the code gives."""

import re
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from pathlib import Path

import pytest
import yaml

from backtest_agent.coded.approvals import approve_code, approve_idea, code_sha256, idea_sha256, normalise_source
from backtest_agent.coded.static import ALLOWED_TO_ATTRIBUTES, BANNED_ATTRIBUTES, BANNED_NAMES, MAX_SOURCE_BYTES
from backtest_agent.spec.coded_spec import MAX_BRIEF_LENGTH, MAX_ID_LENGTH
from backtest_agent.spec.schema import SignalSpec

DOC = (Path(__file__).resolve().parents[1] / "docs" / "coded-signals.md").read_text(encoding="utf-8")


def blocks(language: str) -> list[str]:
    return re.findall(r"```" + language + r"\n(.*?)```", DOC, flags=re.DOTALL)


def test_the_idea_digests_of_the_table_are_the_ones_of_the_code() -> None:
    rows = [
        ("rsi_pullback", "Buy when RSI(14) < 30.", "5c4e9e9af8ed5b0f84bf6d4e5b3aec9391a08a374335db9c115121536625a55f"),
        ("x_signal", "a\r\nb", "9ba96a0c177373ed575249d1402cc33668c4b05f98d2bf3de0d055522d0631d2"),
        ("x_signal", " x ", "df46de2a17dc90b8d306d9ce73831b850628a940f02ab8fce4aff6c874319e2c"),
        ("x_signal", "B", "deba52ffffb76ac1a954fd11e28370ea6cbf9afeca4358901fe3d7b0050cdebc"),
    ]
    for signal_id, brief, digest in rows:
        assert idea_sha256(signal_id, brief) == digest
        assert f"`{digest}`" in DOC


def test_the_code_digests_of_the_text_are_the_ones_of_the_code() -> None:
    for data, digest in [
        (b"x = 1\ny = 2\n", "8353afe579a16d27abc038055bf713459ba6ef418c65b143b526a09dd529e500"),
        (b"x = 1\r\ny = 2\r\n", "8353afe579a16d27abc038055bf713459ba6ef418c65b143b526a09dd529e500"),
        (b"x = 1", "8ff436def1451285599a1b1ad70800493b8dcafde2912e1a38345633054e4c26"),
    ]:
        assert code_sha256(data) == digest
        assert f"`{digest}`" in DOC


def test_the_worked_example_produces_the_record_of_the_document(tmp_path: Path) -> None:
    (source,) = blocks("text")
    (record_line,) = blocks("json")
    data = normalise_source(source.encode("utf-8"))
    approve_idea(tmp_path, "x_signal", "B", datetime(2026, 11, 2, 10, 0, 0, tzinfo=UTC))
    _, sha, _ = approve_code(tmp_path, "x_signal", "B", data, datetime(2026, 11, 2, 11, 0, 0, tzinfo=UTC))
    assert sha == "83e18fb4daa4d96e203d83fa9f17c1b28c183c44fb75c677db99eabd8ffa5370"
    assert f"`{sha}`" in DOC
    assert (tmp_path / "x_signal.json").read_bytes() == record_line.encode("utf-8")
    assert (tmp_path / "code" / f"{sha}.py").read_bytes() == data


def test_the_numbers_and_lists_of_the_document_are_the_ones_of_the_code() -> None:
    assert (MAX_ID_LENGTH, MAX_BRIEF_LENGTH, MAX_SOURCE_BYTES) == (64, 2000, 64 * 1024)
    assert "at most 64 characters" in DOC and "1 to 2000 characters" in DOC and "at most 64 KiB" in DOC
    for name in BANNED_NAMES:
        assert f"`{name}`" in DOC, name
    for name in ALLOWED_TO_ATTRIBUTES:
        assert f"`{name}`" in DOC, name


WILDCARDS = ["save*", "read_*"]  # the patterns the document uses for a family of banned attributes


def documented(name: str, text: str) -> bool:
    """True if ``name`` is in backticks in ``text`` or matches a wildcard that is in backticks there."""
    if f"`{name}`" in text:
        return True
    return any(fnmatchcase(name, pattern) and f"`{pattern}`" in text for pattern in WILDCARDS)


def test_every_banned_attribute_is_in_the_document_or_matches_one_of_its_wildcards() -> None:
    missing = sorted(name for name in BANNED_ATTRIBUTES if not documented(name, DOC))
    assert missing == []
    assert all(f"`{pattern}`" in DOC for pattern in WILDCARDS)


def test_the_check_notices_a_name_that_is_removed_from_the_document() -> None:
    for name in sorted(BANNED_ATTRIBUTES):
        if any(fnmatchcase(name, pattern) for pattern in WILDCARDS):
            continue  # covered by its wildcard
        assert f"`{name}`" in DOC, name
        without = DOC.replace(f"`{name}`", name)
        assert not documented(name, without), name


def test_the_wildcards_cover_what_they_say() -> None:
    covered = sorted(name for name in BANNED_ATTRIBUTES if any(fnmatchcase(name, pattern) for pattern in WILDCARDS))
    assert covered == ["save", "savetxt", "savez", "savez_compressed"]  # the read_* family has no listed member


ROOT = Path(__file__).resolve().parents[1]


def yaml_blocks_with_coded(document: str) -> list[str]:
    found = re.findall(r"```yaml\n(.*?)```", document, flags=re.DOTALL)
    return [block for block in found if "coded:" in block]


@pytest.mark.parametrize("name", ["coded-signals.md", "strategy-spec.md"])
def test_every_coded_yaml_example_of_the_documents_is_a_valid_signal_spec(name: str) -> None:
    text = (ROOT / "docs" / name).read_text(encoding="utf-8")
    found = yaml_blocks_with_coded(text)
    assert len(found) >= 1, f"{name} has no yaml block with a coded: block"
    for block in found:
        data = yaml.safe_load(block)
        spec = SignalSpec.model_validate(data["signal"])
        assert spec.coded is not None and spec.coded.brief.strip()
        assert spec.coded.code_sha256 is None  # a spec file does not write the sha
