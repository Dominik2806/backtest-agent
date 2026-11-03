"""``bt signal check``: the check of a candidate before it is approved (docs/cli.md, ADR 0018 addendum).

The hashes are literals taken with ``hashlib`` outside the project. The candidates are
``good_source("x_signal", "0.5")``
(a signal that holds 0.5 on every row of every symbol that trades; sha ``81d30b98...``, ``SHA_HALF``) and the canary of
``coded_helpers``, whose import writes a line to a marker file under ``tmp_path``: it shows whether, and how often, the
candidate was executed (it needs the static check switched off, as in the tests of the gate). The expected output is a
literal. Every test changes into ``tmp_path``.
"""

import io
from pathlib import Path

import pytest

from backtest_agent.cli import main
from backtest_agent.coded import loader
from backtest_agent.coded.working import FILE_LIMIT
from backtest_agent.spec import SIGNALS
from cli_helpers import NoNetworkProvider, at, run_cli, write_spec
from coded_helpers import (
    CANARY_ID,
    World,
    canary_source,
    coded_spec,
    good_source,
    registry_and_modules_are_restored,  # noqa: F401 - autouse fixture
    sha_of,
)
from runner_helpers import make_spec

ID = "x_signal"
SHA_HALF = "81d30b983518137333e6868e5db31497951cbb1709bb10464544f0dcc7bb2d77"  # good_source("x_signal", "0.5")
SHA_ZERO = "382c5d1b2f9cbeebb6aa13a34c6ec93636b256e5e35ee103b2d73358071cb122"  # good_source("x_signal")
CONSENT = (
    "bt: executing strategies/signals/x_signal.py (sha {sha8}, NOT approved) in this process, with your permissions "
    "and no time or memory limit; the static check is a tripwire, not a sandbox"
)
GOOD_CASES = """\
cases:
  - name: holds one half
    prices:
      AAA: [10, 11, 12]
      BBB: [null, 20, 21]
    expected:
      AAA: [0.5, 0.5, 0.5]
      BBB: [0, 0.5, 0.5]
"""
CANARY_CASES = """cases:
  - name: holds nothing
    prices:
      AAA: [10, 11, 12]
    expected:
      AAA: [0, 0, 0]
"""
WORSE_CASES = GOOD_CASES.replace("AAA: [0.5, 0.5, 0.5]", "AAA: [0.25, 0.25, 0.25]")
GOOD_OUT = [
    "Signal:     x_signal",
    "File:       strategies/signals/x_signal.py",
    f"Sha256:     {SHA_HALF}",
    "Static:     ok",
    "Contract:   ok (frames of 300 rows)",
    "Cases:      ok (1 case in x_signal.cases.yaml)",
    f"Pin:        not set (signal.coded.code_sha256: {SHA_HALF})",
    "Checked:    nothing was approved or written",
    "Next, if not done yet:",
    "  bt approve spec.yaml --idea",
    "  bt approve spec.yaml --code --sha 81d30b98",
]


@pytest.fixture
def cwd(world: World, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(world.root)
    return world.root


@pytest.fixture
def static_off(monkeypatch: pytest.MonkeyPatch, static_check_off: None) -> None:
    """The static check of the gate tests is off, and so is the one of the command: the canary can then be executed."""
    monkeypatch.setattr("backtest_agent.cli.signal_check.check_source", lambda data, signal_id: None)


def put(folder: Path, signal_id: str, source: bytes, cases: str | None = GOOD_CASES) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{signal_id}.py").write_bytes(source)
    if cases is not None:
        (folder / f"{signal_id}.cases.yaml").write_text(cases, encoding="utf-8")


def candidate(cwd: Path, source: bytes | None = None, cases: str | None = GOOD_CASES, **spec_args) -> None:
    """spec.yaml (x_signal) and its file and cases in strategies/signals."""
    write_spec(cwd, coded_spec(ID, **spec_args))
    put(cwd / "strategies" / "signals", ID, good_source(ID, "0.5") if source is None else source, cases)


def consent_lines(err: str) -> list[str]:
    return [line for line in err.splitlines() if line.startswith("bt: executing")]


def tree_of(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# --- success ---


def test_a_good_candidate_prints_the_literal_block_and_exits_0(cwd: Path) -> None:
    candidate(cwd)
    result = run_cli(["signal", "check", "spec.yaml"])
    assert (result.code, result.out.splitlines()) == (0, GOOD_OUT)
    assert result.err.splitlines() == [CONSENT.format(sha8="81d30b98")]


def test_it_writes_nothing_reads_no_approvals_requests_no_data_and_leaves_the_registry(cwd: Path) -> None:
    candidate(cwd)
    before, registry = tree_of(cwd), SIGNALS.snapshot()
    assert run_cli(["signal", "check", "spec.yaml"]).code == 0  # the provider of run_cli raises if it is reached
    assert tree_of(cwd) == before
    assert not (cwd / "approvals").exists()
    assert SIGNALS.snapshot() == registry and loader._CHECKED == set()


def test_a_damaged_approval_record_does_not_matter_because_the_record_is_not_read(cwd: Path) -> None:
    candidate(cwd)
    (cwd / "approvals").mkdir()
    (cwd / "approvals" / f"{ID}.json").write_bytes(b"{")
    assert run_cli(["signal", "check", "spec.yaml"]).out.splitlines() == GOOD_OUT


def test_a_file_with_crlf_has_the_sha_of_its_lf_form_which_is_the_sha_that_bt_approve_prints(cwd: Path) -> None:
    candidate(cwd, good_source(ID, "0.5").replace(b"\n", b"\r\n"))
    checked = run_cli(["signal", "check", "spec.yaml"])
    assert checked.out.splitlines()[2] == f"Sha256:     {SHA_HALF}"
    assert run_cli(["approve", "spec.yaml", "--idea"], clock=at(0)).code == 0
    review = run_cli(["approve", "spec.yaml", "--code"], clock=at(60))
    assert (review.code, f"Sha256:     {SHA_HALF}" in review.out.splitlines()) == (8, True)


def test_a_candidate_can_be_checked_before_its_idea_is_approved_and_after_the_code_is_approved(cwd: Path) -> None:
    candidate(cwd)
    assert run_cli(["signal", "check", "spec.yaml"]).code == 0  # no record at all
    run_cli(["approve", "spec.yaml", "--idea"], clock=at(0))
    run_cli(["approve", "spec.yaml", "--code", "--sha", "81d30b98"], clock=at(60))
    assert run_cli(["signal", "check", "spec.yaml"]).out.splitlines() == GOOD_OUT  # approved code is checked too


def test_a_strategies_dir_is_read_and_repeated_in_the_commands_of_next(cwd: Path) -> None:
    write_spec(cwd, coded_spec(ID))
    put(cwd / "other" / "dir", ID, good_source(ID, "0.5"))
    result = run_cli(["signal", "check", "spec.yaml", "--strategies-dir", "other/dir"])
    assert result.code == 0
    assert result.out.splitlines()[1] == "File:       other/dir/x_signal.py"
    assert result.out.splitlines()[-2:] == [
        "  bt approve spec.yaml --idea --strategies-dir other/dir",
        "  bt approve spec.yaml --code --sha 81d30b98 --strategies-dir other/dir",
    ]
    assert consent_lines(result.err) == [CONSENT.format(sha8="81d30b98").replace("strategies/signals", "other/dir")]


def test_a_spec_path_with_a_space_is_quoted_in_the_commands_of_next(cwd: Path) -> None:
    candidate(cwd)
    (cwd / "spec.yaml").rename(cwd / "my spec.yaml")
    assert run_cli(["signal", "check", "my spec.yaml"]).out.splitlines()[-2:] == [
        '  bt approve "my spec.yaml" --idea',
        '  bt approve "my spec.yaml" --code --sha 81d30b98',
    ]


def test_the_pin_line_compares_the_spec_with_the_file(cwd: Path) -> None:
    candidate(cwd, pin=SHA_HALF)
    assert run_cli(["signal", "check", "spec.yaml"]).out.splitlines()[6] == "Pin:        matches"
    candidate(cwd, pin=SHA_ZERO)
    assert run_cli(["signal", "check", "spec.yaml"]).out.splitlines()[6] == "Pin:        differs (spec pins 382c5d1b)"


# --- the checks that stop it ---


def refuses(code: int, message: str) -> str:
    result = run_cli(["signal", "check", "spec.yaml"])
    assert (result.code, result.out) == (code, "")
    assert "bt: error: " in result.err and message in result.err, result.err
    return result.err


def test_a_spec_without_a_coded_block_is_exit_3_and_nothing_is_executed(cwd: Path) -> None:
    write_spec(cwd, make_spec(signal="buy_and_hold", params={}))
    err = refuses(3, "the spec has no coded block; only a coded signal is checked")
    assert consent_lines(err) == []


def test_a_file_that_is_missing_is_exit_9_not_8_because_nothing_waits_for_an_approval(cwd: Path) -> None:
    write_spec(cwd, coded_spec(ID))
    err = refuses(9, "strategies/signals/x_signal.py cannot be read (")
    assert consent_lines(err) == []
    assert "docs/coded-signals.md" in err.splitlines()[-1]  # the hint of rejected code, not the one of an approval


def test_a_working_file_that_is_not_a_regular_file_is_exit_9(cwd: Path) -> None:
    write_spec(cwd, coded_spec(ID))
    (cwd / "strategies" / "signals" / "x_signal.py").mkdir(parents=True)  # a folder where the file should be
    err = refuses(9, "strategies/signals/x_signal.py cannot be read (")
    assert consent_lines(err) == []


def test_the_examples_run_with_the_params_of_the_cases_file_not_with_the_params_of_the_spec(cwd: Path) -> None:
    """The spec says scale 0.0 (the contract check runs with it); the cases file has no params, so the examples run with
    the default 1.0 * 0.5 and expect 0.5. Both pass; with the params of the spec the examples would see 0.0 and fail."""
    candidate(cwd, params={"scale": 0.0})
    result = run_cli(["signal", "check", "spec.yaml"])
    assert (result.code, result.out.splitlines()[5]) == (0, "Cases:      ok (1 case in x_signal.cases.yaml)")


def test_a_file_that_is_too_large_is_exit_9(cwd: Path) -> None:
    candidate(cwd, b"#" * (FILE_LIMIT + 1))
    err = refuses(9, "x_signal.py is larger than the limit; approved code is at most 64 KiB")
    assert consent_lines(err) == []


def test_a_candidate_that_fails_the_static_check_is_exit_9_and_is_not_executed(cwd: Path) -> None:
    candidate(cwd, canary_source(ID))  # open() and os: refused by the real static check
    err = refuses(9, "the signal source breaks")
    assert consent_lines(err) == [] and not (cwd / "marker.txt").exists()


@pytest.mark.parametrize(
    ("cases", "message"),
    [
        (None, "canary_signal.cases.yaml is missing; the signal coder writes the examples of 'canary_signal' in it"),
        ("cases: []\n", "canary_signal.cases.yaml is not valid (1 problem):"),
        ("signal: other_one\ncases: []\n", "canary_signal.cases.yaml is not valid"),
        ("{", "(yaml): syntax error"),
    ],
    ids=["missing", "empty list", "wrong signal and empty", "not yaml"],
)
def test_a_cases_file_that_is_missing_or_invalid_is_exit_9_before_anything_is_executed(
    cwd: Path, static_off: None, cases: str | None, message: str
) -> None:
    write_spec(cwd, coded_spec(CANARY_ID))
    put(cwd / "strategies" / "signals", CANARY_ID, canary_source(), cases)
    err = refuses(9, message)
    assert consent_lines(err) == []
    assert not (cwd / "marker.txt").exists()  # the canary would have written it


# --- once the candidate is executed ---


def test_a_contract_failure_is_exit_9_and_the_consent_line_was_written_once(cwd: Path) -> None:
    candidate(cwd, good_source(ID, "2.0"))
    err = refuses(9, "x_signal on the plain frame:")
    assert len(consent_lines(err)) == 1
    assert ID not in SIGNALS


def test_a_failing_example_is_exit_9_with_the_differences_and_the_consent_line_was_written_once(cwd: Path) -> None:
    candidate(cwd, cases=WORSE_CASES)
    result = run_cli(["signal", "check", "spec.yaml"])
    assert (result.code, result.out) == (9, "")
    assert result.err.splitlines()[1:6] == [
        "bt: error: 3 differences in the examples:",
        "  - x_signal on the case 'holds one half': AAA row 0 (2024-01-02): expected 0.25, got 0.5",
        "  - x_signal on the case 'holds one half': AAA row 1 (2024-01-03): expected 0.25, got 0.5",
        "  - x_signal on the case 'holds one half': AAA row 2 (2024-01-04): expected 0.25, got 0.5",
        "hint: the rules a coded signal has to follow are in docs/coded-signals.md",
    ]
    assert len(consent_lines(result.err)) == 1
    assert ID not in SIGNALS


@pytest.mark.parametrize(
    ("extra", "message"),
    [("raise SystemExit(3)", "failed when it was loaded: SystemExit: 3"), ("raise KeyError('k')", "KeyError: 'k'")],
)
def test_a_candidate_that_raises_when_it_is_loaded_is_exit_9_and_the_consent_line_was_written_once(
    cwd: Path, static_off: None, extra: str, message: str
) -> None:
    candidate_world(cwd, canary_source(extra=(extra,)))
    err = refuses(9, message)
    assert len(consent_lines(err)) == 1
    assert (cwd / "marker.txt").read_text(encoding="utf-8").splitlines() == ["imported 0.0"]


def candidate_world(cwd: Path, source: bytes) -> None:
    """The spec of the canary and its files; the canary holds 0.0, so that is what its example expects."""
    write_spec(cwd, coded_spec(CANARY_ID))
    put(cwd / "strategies" / "signals", CANARY_ID, source, CANARY_CASES)


def test_params_of_the_spec_that_do_not_fit_the_model_of_the_candidate_are_exit_3(cwd: Path) -> None:
    candidate(cwd, params={"nope": 1})
    result = run_cli(["signal", "check", "spec.yaml"])
    assert (result.code, result.out) == (3, "")
    assert "signal.params.nope: unknown field 'nope'; allowed fields: scale" in result.err
    assert len(consent_lines(result.err)) == 1  # the candidate had to be loaded to know its model
    assert ID not in SIGNALS


# --- the consent line comes before the code runs ---


class WatchedStderr(io.StringIO):
    """A stderr that records, at the moment the consent line is written, whether the canary has run already."""

    def __init__(self, marker: Path) -> None:
        super().__init__()
        self.marker = marker
        self.marker_existed: list[bool] = []

    def write(self, text: str) -> int:
        if text.startswith("bt: executing"):
            self.marker_existed.append(self.marker.exists())
        return super().write(text)


def test_the_consent_line_is_written_before_the_candidate_is_executed(cwd: Path, static_off: None) -> None:
    candidate_world(cwd, canary_source())
    err = WatchedStderr(cwd / "marker.txt")
    code = main(
        ["signal", "check", "spec.yaml"],
        provider_factory=lambda cache_dir: NoNetworkProvider(),
        clock=at(0),
        stdout=io.StringIO(),
        stderr=err,
    )
    assert code == 0, err.getvalue()
    assert err.marker_existed == [False]  # written once, and the canary had not run
    assert (cwd / "marker.txt").read_text(encoding="utf-8").splitlines() == ["imported 0.0"]  # ... and then it ran


# --- interruption, and no cache ---


def test_ctrl_c_while_the_candidate_is_loaded_is_exit_130_and_the_registry_is_as_it_was(
    cwd: Path, static_off: None
) -> None:
    candidate_world(cwd, canary_source(extra=("raise KeyboardInterrupt",)))
    before = SIGNALS.snapshot()
    result = run_cli(["signal", "check", "spec.yaml"])
    assert (result.code, result.out) == (130, "")
    assert result.err.splitlines()[-1] == "bt: error: interrupted"
    assert SIGNALS.snapshot() == before and loader._CHECKED == set()


@pytest.mark.parametrize("stage", ["check_signal_contract", "run_cases"])
def test_ctrl_c_while_the_candidate_is_checked_is_exit_130_and_the_registry_is_as_it_was(
    cwd: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    candidate(cwd)

    def interrupt(*args, **kwargs):
        assert ID in SIGNALS  # the candidate is registered while it is checked
        raise KeyboardInterrupt

    monkeypatch.setattr(f"backtest_agent.cli.signal_check.{stage}", interrupt)
    before = SIGNALS.snapshot()
    result = run_cli(["signal", "check", "spec.yaml"])
    assert (result.code, result.out) == (130, "")
    assert SIGNALS.snapshot() == before and ID not in SIGNALS


def test_the_same_code_and_params_are_checked_again_every_time_and_the_cache_of_the_gate_is_not_used(
    cwd: Path, monkeypatch: pytest.MonkeyPatch, static_off: None
) -> None:
    candidate_world(cwd, canary_source())
    from backtest_agent.cli import signal_check

    original, rows = signal_check.check_signal_contract, []

    def spy(signal, params, frames):
        rows.append(len(frames["plain"]))
        return original(signal, params, frames)

    monkeypatch.setattr(signal_check, "check_signal_contract", spy)
    key = loader.checked_key(sha_of(canary_source()), {})  # the key the gate builds; the canary has no params
    loader._CHECKED.add(key)  # the gate has checked this code with these params before
    for _ in range(2):
        assert run_cli(["signal", "check", "spec.yaml"]).code == 0
    assert rows == [300, 300]  # twice, on the frames of 300 rows
    assert (cwd / "marker.txt").read_text(encoding="utf-8").splitlines() == ["imported 0.0", "imported 0.0"]
    assert loader._CHECKED == {key}  # nothing was added


# --- nothing before the consent line can execute code ---


def test_a_cases_file_with_a_python_tag_is_refused_as_data_and_creates_nothing(cwd: Path, static_off: None) -> None:
    """The cases file is read before the consent line. Loaded with an unsafe YAML loader, this tag would call
    ``builtins.open`` and create ``tagged.txt``; the safe loader refuses it. The canary behind it is not run either."""
    write_spec(cwd, coded_spec(CANARY_ID))
    tagged = (cwd / "tagged.txt").as_posix()
    put(
        cwd / "strategies" / "signals",
        CANARY_ID,
        canary_source(),
        f"cases: !!python/object/apply:builtins.open ['{tagged}', w]\n",
    )
    err = refuses(9, "canary_signal.cases.yaml is not valid (1 problem):")
    assert "(yaml): syntax error" in err
    assert consent_lines(err) == []
    assert not (cwd / "tagged.txt").exists() and not (cwd / "marker.txt").exists()


# --- a spec with an id that is not allowed is refused before any file is read ---


@pytest.mark.parametrize("bad", ["../evil", "con"])
def test_a_spec_id_that_a_coded_signal_may_not_have_is_exit_3_before_any_file_is_read(
    cwd: Path, monkeypatch: pytest.MonkeyPatch, static_off: None, bad: str
) -> None:
    data = coded_spec(ID).to_dict()
    data["signal"]["id"] = bad
    write_spec(cwd, data)
    put(cwd / "strategies", "evil", canary_source("evil"), CANARY_CASES)  # what ../evil would reach

    def read(path, shown):
        raise AssertionError(f"the command read {shown}")

    monkeypatch.setattr("backtest_agent.cli.signal_check.read_working_file", read)
    result = run_cli(["signal", "check", "spec.yaml"])
    assert (result.code, result.out) == (3, "")
    assert "Invalid strategy spec" in result.err and "signal.id" in result.err
    assert consent_lines(result.err) == [] and not (cwd / "marker.txt").exists()


# --- a params model that cannot hold its own defaults ---

OVER = "Field(1.0, ge=0.0, le=1.0)"


def broken_defaults(replacement: str, old: str = "scale: float = " + OVER) -> bytes:
    return good_source(ID, "0.5").decode().replace(old, replacement).encode()


def test_a_default_that_the_model_of_the_candidate_does_not_accept_is_exit_9(cwd: Path) -> None:
    """The default 2.0 is outside ``le=1.0`` and is not validated when the model is built, so the model takes the empty
    params of the spec and then refuses its own dumped defaults: a ``GateError`` (the code is at fault), exit 9."""
    candidate(cwd, broken_defaults("scale: float = Field(2.0, ge=0.0, le=1.0)"))
    err = refuses(
        9,
        "the params model of the code does not accept its own defaults: scale: Input should be less than or equal to 1",
    )
    assert len(consent_lines(err)) == 1 and ID not in SIGNALS


def test_a_default_that_a_spec_cannot_hold_is_exit_9(cwd: Path) -> None:
    candidate(cwd, broken_defaults("scale: float | None = None"))
    err = refuses(9, "the params model of the code has a default that a spec cannot hold: 'scale' is None")
    assert len(consent_lines(err)) == 1


def test_today_an_out_of_range_default_with_validate_default_is_exit_3_not_the_wanted_9(cwd: Path) -> None:
    """Current behaviour, reported in the review: with ``validate_default=True`` the empty params of the spec already
    fail the model, so the error is a ``SpecError`` naming ``signal.params.scale`` (exit 3); the code is at fault."""
    candidate(cwd, broken_defaults("scale: float = Field(2.0, ge=0.0, le=1.0, validate_default=True)"))
    err = refuses(3, "signal.params.scale: Input should be less than or equal to 1")
    assert len(consent_lines(err)) == 1
