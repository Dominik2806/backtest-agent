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
from backtest_agent.spec.signals import Signal, SignalParams, per_symbol_signal

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


# --- the gate, the check before a run and cases.yaml ---


class UpParams(SignalParams):
    threshold: float = 0.0

    def warmup_rows(self) -> int:
        return 1


def up_day(prices, params):
    """1.0 where the close is above the previous close of the symbol."""
    return per_symbol_signal(prices, lambda close: (close - close.shift(1) > params.threshold).astype("float64"))


def test_the_worked_example_of_cases_yaml_is_parsed_and_holds_for_the_signal_it_describes() -> None:
    from backtest_agent.coded.cases import parse_cases, run_cases

    found = [b for b in re.findall(r"```yaml\n(.*?)```", DOC, flags=re.DOTALL) if "cases:" in b and "coded:" not in b]
    assert len(found) == 1
    cases = parse_cases(found[0].encode("utf-8"), "up_day")
    assert [c.name for c in cases.cases] == ["rises, falls and rises"]
    assert run_cases(Signal("up_day", UpParams, up_day), cases) == 1


def test_the_limits_and_numbers_of_the_gate_in_the_document_are_the_ones_of_the_code() -> None:
    from backtest_agent.coded.cases import MAX_CASES, MAX_FILE_BYTES, MAX_FLOW_DEPTH, MAX_ROWS, MAX_SYMBOLS
    from backtest_agent.coded.contract import PRE_RUN_ROWS
    from backtest_agent.coded.loader import FILE_LIMIT

    assert (MAX_CASES, MAX_SYMBOLS, MAX_ROWS, MAX_FILE_BYTES, MAX_FLOW_DEPTH) == (50, 10, 400, 256 * 1024, 20)
    assert (PRE_RUN_ROWS, FILE_LIMIT) == (120, 128 * 1024)
    for text in [
        "1 to 50 cases",
        "1 to 10 symbols",
        "1 to 400",
        "at most 256 KiB",
        "nested at most 20 deep",
        "synthetic frames\nof 120 rows",
        "frames of 300 rows",
        "at most 128 KiB",
        "at most one byte more than the\nlimit is read",
    ]:
        assert text in DOC, text


def test_the_messages_of_the_pin_versus_file_table_are_the_ones_of_the_loader() -> None:
    loader = (Path(__file__).resolve().parents[1] / "src" / "backtest_agent" / "coded" / "loader.py").read_text("utf-8")
    for message in [
        "code not approved: the file has sha",
        "code not approved: no code is approved for the idea",
        "the spec pins",
        "cannot be read (not a regular file)",
        "is larger than the limit; approved code is at most",
    ]:
        assert message in loader, message
    for fragment in [
        "code not approved: the file has sha <first 8 hex>",
        "the spec pins <8 hex> but strategies/signals/<id>.py has sha <8 hex>",
        "cannot be read (not a regular file)",
        "is larger than the limit; approved code is at most 64 KiB",
        "code not approved: no code is approved for the idea",
    ]:
        assert fragment in DOC, fragment


def test_the_documented_rules_for_params_models_are_listed_in_the_document() -> None:
    for refused in ["no `None` default", "no tuple", "no dict", "no nested list", "no NaN or infinity"]:
        assert refused in DOC, refused
