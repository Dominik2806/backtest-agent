"""Approvals of coded signals (backtest_agent.coded.approvals): hashes, the append-only history and what is written.

Digests are SHA-256 values of hand-written byte strings, computed outside project code with ``hashlib`` (the byte
strings are written out next to them). The expected file contents are literals.
"""

import json
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from backtest_agent.coded.approvals import (
    approve_code,
    approve_idea,
    code_path,
    code_sha256,
    format_time,
    idea_sha256,
    normalise_source,
    parse_record,
    read_archived_code,
    read_record,
    record_path,
    render_record,
)
from backtest_agent.coded.errors import ApprovalError, ApprovalFormatError, StaticCheckError


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 11, 2, hour, minute, second, tzinfo=UTC)


def source(factor: str) -> bytes:
    lines = [
        '"""A signal that is scaled by a constant."""',
        "from backtest_agent.spec.signals import SignalParams, per_symbol_signal, register_signal",
        "",
        "",
        '@register_signal("x_signal", params=SignalParams)',
        "def x_signal(prices, params):",
        f"    return per_symbol_signal(prices, lambda close: close * {factor})",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


# SHA-256 of the exact bytes of source("0.0"), source("0.5") and source("0.25").
S1 = "83e18fb4daa4d96e203d83fa9f17c1b28c183c44fb75c677db99eabd8ffa5370"
S2 = "88451989452e176f4c53d94081c08eb6f9d53e084de3de0d6001ae89f96aef19"
S3 = "6cfc77c2770e00f68acf6985666f289817111699b9827ab6232afee2e41ec90e"
# SHA-256 of {"brief":"B","signal_id":"x_signal"} and the same with "C".
IDEA_B = "deba52ffffb76ac1a954fd11e28370ea6cbf9afeca4358901fe3d7b0050cdebc"
IDEA_C = "6d360b6aff89621de3131637bd247485c7c35283f75e8bda20551d522f99a27f"


# --- the hashes ---


def test_the_idea_hash_of_the_documented_example_is_the_literal_digest() -> None:
    # The hashed bytes are {"brief":"Buy when RSI(14) < 30.","signal_id":"rsi_pullback"}
    assert idea_sha256("rsi_pullback", "Buy when RSI(14) < 30.") == (
        "5c4e9e9af8ed5b0f84bf6d4e5b3aec9391a08a374335db9c115121536625a55f"
    )


@pytest.mark.parametrize(
    ("signal_id", "brief", "digest"),
    [
        # {"brief":"a\nb","signal_id":"x_signal"}: CRLF turned into LF, written as the JSON escape \n
        ("x_signal", "a\r\nb", "9ba96a0c177373ed575249d1402cc33668c4b05f98d2bf3de0d055522d0631d2"),
        ("x_signal", "a\nb", "9ba96a0c177373ed575249d1402cc33668c4b05f98d2bf3de0d055522d0631d2"),
        # {"brief":"café","signal_id":"x_signal"}: ASCII only, the e with acute is the escape é
        ("x_signal", "café", "7ed330ea4f48823e7f6ed130e5c5e61f76e14d12d605f3aef197da71e2deea4c"),
        # {"brief":" x ","signal_id":"x_signal"}: nothing is stripped
        ("x_signal", " x ", "df46de2a17dc90b8d306d9ce73831b850628a940f02ab8fce4aff6c874319e2c"),
        ("x_signal", "B", IDEA_B),
        ("x_signal", "C", IDEA_C),
    ],
)
def test_idea_hashes_are_the_digests_of_the_canonical_json(signal_id: str, brief: str, digest: str) -> None:
    assert idea_sha256(signal_id, brief) == digest


def test_the_idea_depends_on_the_id_and_the_brief_only() -> None:
    assert idea_sha256("x_signal", "B") != idea_sha256("y_signal", "B")
    assert idea_sha256("x_signal", "B") != idea_sha256("x_signal", "B ")
    assert idea_sha256("x_signal", "a\rb") != idea_sha256("x_signal", "a\nb")  # only CRLF is normalised


def test_code_hashes_are_the_digests_of_the_lf_bytes() -> None:
    assert code_sha256(source("0.0")) == S1
    assert code_sha256(source("0.0").replace(b"\n", b"\r\n")) == S1
    assert code_sha256(source("0.5")) == S2
    assert code_sha256(source("0.25")) == S3
    # b"x = 1\ny = 2\n"
    assert code_sha256(b"x = 1\r\ny = 2\r\n") == "8353afe579a16d27abc038055bf713459ba6ef418c65b143b526a09dd529e500"
    # b"x = 1": no newline is added
    assert code_sha256(b"x = 1") == "8ff436def1451285599a1b1ad70800493b8dcafde2912e1a38345633054e4c26"
    assert (
        normalise_source(b"a\r\nb\rc\n") == b"a\nb\rc\n"
    )  # a lone CR is not touched here (the static check refuses it)


# --- time and paths ---


def test_times_are_utc_with_whole_seconds() -> None:
    assert format_time(datetime(2026, 11, 2, 10, 0, 0, tzinfo=UTC)) == "2026-11-02T10:00:00Z"
    assert format_time(datetime(2026, 11, 2, 12, 30, 5, 999999, tzinfo=timezone(timedelta(hours=2)))) == (
        "2026-11-02T10:30:05Z"
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        format_time(datetime(2026, 11, 2, 10, 0, 0))


def test_paths_are_derived_from_the_id_and_the_hash_only(tmp_path: Path) -> None:
    assert record_path(tmp_path, "x_signal") == tmp_path / "x_signal.json"
    assert code_path(tmp_path, S1) == tmp_path / "code" / f"{S1}.py"
    for bad in ["../x", "X", "con", "a/b", "a\\b", "sma_crossover", ""]:
        with pytest.raises(ValueError):
            record_path(tmp_path, bad)
    for bad in ["", "../" + S1, S1.upper(), S1[:-1], S1 + "0", "g" * 64]:
        with pytest.raises(ValueError, match="64 lowercase hex"):
            code_path(tmp_path, bad)


# --- the append-only history ---


def files(directory: Path) -> list[str]:
    return sorted(p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file())


def test_the_history_only_grows(tmp_path: Path) -> None:
    path = tmp_path / "x_signal.json"

    # 1. approve the idea B
    record, changed = approve_idea(tmp_path, "x_signal", "B", at(10))
    assert changed is True
    expected_1 = (
        '{"ideas":[{"approved_at":"2026-11-02T10:00:00Z","code":[],"idea_sha256":"' + IDEA_B + '"}],'
        '"schema_version":1,"signal_id":"x_signal"}\n'
    ).encode()
    assert path.read_bytes() == expected_1

    # 2. the same idea again is a no-op; the first time stays
    record, changed = approve_idea(tmp_path, "x_signal", "B", at(10, 5))
    assert changed is False and path.read_bytes() == expected_1

    # 3. approve code for B (the CRLF form of the file is the same code)
    record, sha, changed = approve_code(tmp_path, "x_signal", "B", source("0.0").replace(b"\n", b"\r\n"), at(11))
    assert (sha, changed) == (S1, True)
    expected_3 = (
        '{"ideas":[{"approved_at":"2026-11-02T10:00:00Z","code":[{"approved_at":"2026-11-02T11:00:00Z",'
        '"sha256":"' + S1 + '"}],"idea_sha256":"' + IDEA_B + '"}],"schema_version":1,"signal_id":"x_signal"}\n'
    ).encode()
    assert path.read_bytes() == expected_3
    assert (tmp_path / "code" / f"{S1}.py").read_bytes() == source("0.0")  # archived with LF line ends

    # 4. the same code again is a no-op
    record, sha, changed = approve_code(tmp_path, "x_signal", "B", source("0.0"), at(11, 1))
    assert (sha, changed) == (S1, False) and path.read_bytes() == expected_3

    # 5. changed code of the same idea is a second code entry; the first stays
    record, sha, changed = approve_code(tmp_path, "x_signal", "B", source("0.5"), at(12))
    assert (sha, changed) == (S2, True)
    assert [c.sha256 for c in record.idea(IDEA_B).code] == [S1, S2]  # type: ignore[union-attr]
    assert record.idea(IDEA_B).latest_code.sha256 == S2  # type: ignore[union-attr]

    # 6. a changed brief is a new idea entry with no code; B and its code are untouched
    record, changed = approve_idea(tmp_path, "x_signal", "C", at(13))
    assert changed is True
    assert [i.idea_sha256 for i in record.ideas] == [IDEA_B, IDEA_C]
    assert record.idea(IDEA_C).code == ()  # type: ignore[union-attr]
    assert [c.sha256 for c in record.idea(IDEA_B).code] == [S1, S2]  # type: ignore[union-attr]

    # 7. code for C goes to C only
    record, sha, changed = approve_code(tmp_path, "x_signal", "C", source("0.25"), at(14))
    assert (sha, changed) == (S3, True)

    # 8. approving B again changes nothing and does not move it
    record, changed = approve_idea(tmp_path, "x_signal", "B", at(15))
    assert changed is False

    assert (
        path.read_bytes()
        == (
            '{"ideas":['
            '{"approved_at":"2026-11-02T10:00:00Z","code":['
            '{"approved_at":"2026-11-02T11:00:00Z","sha256":"' + S1 + '"},'
            '{"approved_at":"2026-11-02T12:00:00Z","sha256":"' + S2 + '"}],"idea_sha256":"' + IDEA_B + '"},'
            '{"approved_at":"2026-11-02T13:00:00Z","code":['
            '{"approved_at":"2026-11-02T14:00:00Z","sha256":"' + S3 + '"}],"idea_sha256":"' + IDEA_C + '"}],'
            '"schema_version":1,"signal_id":"x_signal"}\n'
        ).encode()
    )
    assert read_record(tmp_path, "x_signal") == record
    assert files(tmp_path) == sorted(["x_signal.json", f"code/{S1}.py", f"code/{S2}.py", f"code/{S3}.py"])
    assert render_record(record) == path.read_bytes()


def test_an_older_idea_keeps_its_code_when_the_brief_changes_and_changes_back(tmp_path: Path) -> None:
    approve_idea(tmp_path, "x_signal", "B", at(10))
    approve_code(tmp_path, "x_signal", "B", source("0.0"), at(11))
    approve_idea(tmp_path, "x_signal", "C", at(12))
    record, changed = approve_idea(tmp_path, "x_signal", "B", at(13))  # back to the first brief
    assert changed is False
    assert record.idea(IDEA_B).latest_code.sha256 == S1  # type: ignore[union-attr]


def test_different_signals_have_different_files(tmp_path: Path) -> None:
    approve_idea(tmp_path, "x_signal", "B", at(10))
    approve_idea(tmp_path, "y_signal", "B", at(10))
    assert files(tmp_path) == ["x_signal.json", "y_signal.json"]
    assert read_record(tmp_path, "z_signal") is None


# --- refusals write nothing ---


def test_code_needs_an_approved_idea_with_this_brief(tmp_path: Path) -> None:
    with pytest.raises(ApprovalError, match="the idea of 'x_signal' with this brief is not approved"):
        approve_code(tmp_path, "x_signal", "B", source("0.0"), at(10))
    approve_idea(tmp_path, "x_signal", "B", at(10))
    with pytest.raises(ApprovalError, match="with this brief is not approved"):
        approve_code(tmp_path, "x_signal", "C", source("0.0"), at(11))
    assert files(tmp_path) == ["x_signal.json"]


@pytest.mark.parametrize(
    "bad",
    [
        b"import os\n" + source("0.0"),
        b"\xef\xbb\xbf" + source("0.0"),
        source("0.0").replace(b"x_signal(", b"other(").replace(b'"x_signal"', b'"other"'),
        source("0.0") + b"# \xe2\x80\xae\n",
    ],
    ids=["import", "byte order mark", "other id", "right-to-left override"],
)
def test_code_that_fails_the_static_check_is_neither_archived_nor_recorded(tmp_path: Path, bad: bytes) -> None:
    approve_idea(tmp_path, "x_signal", "B", at(10))
    before = (tmp_path / "x_signal.json").read_bytes()
    with pytest.raises(StaticCheckError):
        approve_code(tmp_path, "x_signal", "B", bad, at(11))
    assert (tmp_path / "x_signal.json").read_bytes() == before
    assert files(tmp_path) == ["x_signal.json"]


def test_an_archive_file_with_other_bytes_is_refused(tmp_path: Path) -> None:
    approve_idea(tmp_path, "x_signal", "B", at(10))
    (tmp_path / "code").mkdir()
    (tmp_path / "code" / f"{S1}.py").write_bytes(b"changed\n")
    before = (tmp_path / "x_signal.json").read_bytes()
    with pytest.raises(ApprovalError, match="the archived code 83e18fb4 exists with other bytes"):
        approve_code(tmp_path, "x_signal", "B", source("0.0"), at(11))
    assert (tmp_path / "x_signal.json").read_bytes() == before


def test_reading_an_archive_checks_the_hash_of_the_bytes(tmp_path: Path) -> None:
    approve_idea(tmp_path, "x_signal", "B", at(10))
    approve_code(tmp_path, "x_signal", "B", source("0.0"), at(11))
    assert read_archived_code(tmp_path, S1) == source("0.0")
    (tmp_path / "code" / f"{S1}.py").write_bytes(source("0.0") + b"# edited\n")
    with pytest.raises(ApprovalError, match="the archived code 83e18fb4 does not match its hash"):
        read_archived_code(tmp_path, S1)
    (tmp_path / "code" / f"{S1}.py").unlink()
    with pytest.raises(ApprovalError, match="the archived code 83e18fb4 is missing"):
        read_archived_code(tmp_path, S1)


def test_a_naive_time_writes_nothing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        approve_idea(tmp_path, "x_signal", "B", datetime(2026, 11, 2, 10))
    assert files(tmp_path) == []


def test_a_bad_id_writes_nothing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="built-in signal"):
        approve_idea(tmp_path, "sma_crossover", "B", at(10))
    assert files(tmp_path) == []


# --- reading a record that is not valid ---

GOOD = (
    '{"ideas":[{"approved_at":"2026-11-02T10:00:00Z","code":[{"approved_at":"2026-11-02T11:00:00Z",'
    '"sha256":"' + S1 + '"}],"idea_sha256":"' + IDEA_B + '"}],"schema_version":1,"signal_id":"x_signal"}'
)


def test_a_valid_record_parses_whether_or_not_it_is_in_canonical_form() -> None:
    record = parse_record(GOOD.encode(), "x_signal", "x_signal.json")
    assert record.idea(IDEA_B).latest_code.sha256 == S1  # type: ignore[union-attr]
    pretty = json.dumps(json.loads(GOOD), indent=2)
    assert parse_record(pretty.encode(), "x_signal", "x_signal.json") == record


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"not json", "x_signal.json: is not valid JSON in UTF-8"),
        (b"\xff\xfe", "x_signal.json: is not valid JSON in UTF-8"),
        (b"[]", 'x_signal.json: must be an object with exactly the keys "ideas", "schema_version" and "signal_id"'),
        (
            GOOD.replace(',"signal_id":"x_signal"', "").encode(),
            'x_signal.json: must be an object with exactly the keys "ideas", "schema_version" and "signal_id"',
        ),
        (GOOD.replace('"schema_version":1', '"schema_version":2').encode(), "schema_version must be 1, got 2"),
        (GOOD.replace('"schema_version":1', '"schema_version":true').encode(), "schema_version must be 1, got True"),
        (
            GOOD.replace('"signal_id":"x_signal"', '"signal_id":"y_signal"').encode(),
            "signal_id is 'y_signal' but the file is the record of 'x_signal'",
        ),
        (GOOD.replace('"ideas":[', '"ideas":{').replace("}],", "}},", 1).encode(), "is not valid JSON in UTF-8"),
        (GOOD.replace('"ideas":[{', '"ideas":[[],{').encode(), "ideas[0] must be an object with exactly the keys"),
        (
            GOOD.replace("2026-11-02T10:00:00Z", "2026-11-02 10:00:00").encode(),
            "ideas[0].approved_at must be a UTC time such as 2026-11-02T10:00:00Z, got '2026-11-02 10:00:00'",
        ),
        (
            GOOD.replace("2026-11-02T10:00:00Z", "2026-13-02T10:00:00Z").encode(),
            "ideas[0].approved_at is not a valid time, got '2026-13-02T10:00:00Z'",
        ),
        (
            GOOD.replace(IDEA_B, IDEA_B.upper()).encode(),
            f"ideas[0].idea_sha256 must be 64 lowercase hex characters, got '{IDEA_B.upper()}'",
        ),
        (
            GOOD.replace('"code":[{', '"code":[1,{').encode(),
            'ideas[0].code[0] must be an object with exactly the keys "approved_at" and "sha256"',
        ),
        (
            GOOD.replace(S1, S1[:-1]).encode(),
            f"ideas[0].code[0].sha256 must be 64 lowercase hex characters, got '{S1[:-1]}'",
        ),
        (
            GOOD.replace('"code":[{', '"code":{"a":1},"x":[{').encode(),
            'must be an object with exactly the keys "approved_at", "code"',
        ),
    ],
)
def test_a_record_that_is_not_valid_is_refused_with_the_file_and_the_field(raw: bytes, message: str) -> None:
    with pytest.raises(ApprovalFormatError) as info:
        parse_record(raw, "x_signal", "x_signal.json")
    assert message in str(info.value)


def test_duplicates_are_refused() -> None:
    entry = '{"approved_at":"2026-11-02T10:00:00Z","code":[],"idea_sha256":"' + IDEA_B + '"}'
    twice = f'{{"ideas":[{entry},{entry}],"schema_version":1,"signal_id":"x_signal"}}'
    with pytest.raises(ApprovalFormatError, match=r"x_signal.json: ideas\[1\].idea_sha256 appears twice"):
        parse_record(twice.encode(), "x_signal", "x_signal.json")
    code = '{"approved_at":"2026-11-02T11:00:00Z","sha256":"' + S1 + '"}'
    entry = '{"approved_at":"2026-11-02T10:00:00Z","code":[' + code + "," + code + '],"idea_sha256":"' + IDEA_B + '"}'
    with pytest.raises(ApprovalFormatError, match=r"ideas\[0\].code\[1\].sha256 appears twice"):
        parse_record(f'{{"ideas":[{entry}],"schema_version":1,"signal_id":"x_signal"}}'.encode(), "x_signal", "n")


def test_a_file_that_cannot_be_parsed_is_reported_by_read_record(tmp_path: Path) -> None:
    (tmp_path / "x_signal.json").write_bytes(b"{")
    with pytest.raises(ApprovalFormatError, match="x_signal.json: is not valid JSON in UTF-8"):
        read_record(tmp_path, "x_signal")
    with pytest.raises(ApprovalFormatError):
        approve_idea(tmp_path, "x_signal", "B", at(10))  # a broken record is never overwritten
    assert (tmp_path / "x_signal.json").read_bytes() == b"{"


# --- what is written: bytes, privacy ---


def test_written_files_are_lf_only_ascii_json_without_bom_and_leave_no_temporary_file(tmp_path: Path) -> None:
    approve_idea(tmp_path, "x_signal", "café", at(10))
    approve_code(tmp_path, "x_signal", "café", source("0.0").replace(b"\n", b"\r\n"), at(11))
    record = (tmp_path / "x_signal.json").read_bytes()
    assert record.endswith(b"}\n") and record.count(b"\n") == 1 and b"\r" not in record
    record.decode("ascii")
    assert not record.startswith(b"\xef\xbb\xbf")
    archived = (tmp_path / "code" / f"{S1}.py").read_bytes()
    assert b"\r" not in archived and archived == source("0.0")
    assert not [p for p in tmp_path.rglob("*") if p.name.endswith(".tmp")]


def test_nothing_that_identifies_a_user_or_a_machine_is_written(tmp_path: Path) -> None:
    approve_idea(tmp_path, "x_signal", "B", at(10))
    approve_code(tmp_path, "x_signal", "B", source("0.0"), at(11))
    forbidden = {
        str(tmp_path),
        tmp_path.as_posix(),
        str(tmp_path.parent),
        str(Path.home()),
        Path.home().as_posix(),
        Path.home().name,
        tmp_path.drive,
    } - {""}
    pattern = re.compile(rb"[A-Za-z]:[\\/]|/Users/|/home/|\\\\Users\\\\")
    for path in tmp_path.rglob("*"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        text = data.decode("utf-8")
        assert not pattern.search(data), path.name
        for item in forbidden:
            assert item.lower() not in text.lower(), (path.name, item)
