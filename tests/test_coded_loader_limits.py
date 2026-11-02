"""The working file is read with a bound, and the params model of the code cannot hand the spec a bad default.

(ADR 0018.) `resolve_coded` raises only `GateError` (and its two subclasses), `StaticCheckError` and `SpecError`.
"""

import ast
import os
from pathlib import Path

import pytest

from backtest_agent.coded.errors import GateError, NotApprovedError
from backtest_agent.coded.loader import FILE_LIMIT
from backtest_agent.coded.static import MAX_SOURCE_BYTES
from backtest_agent.spec import SIGNALS, SpecError, UnknownSignalError, get_signal
from coded_helpers import (
    World,
    coded_modules,
    coded_spec,
    good_source,
    registry_and_modules_are_restored,  # noqa: F401 - autouse fixture
    sha_of,
)

SHOWN = "strategies/signals/x_signal.py"
TOO_LARGE = f"{SHOWN} is larger than the limit; approved code is at most 64 KiB"


def test_the_limits_are_the_documented_ones() -> None:
    assert MAX_SOURCE_BYTES == 65536 and FILE_LIMIT == 131072


# --- the working file ---


def test_a_file_larger_than_twice_the_limit_is_refused_before_it_is_opened(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.approve_both("x_signal", good_source())
    world.put_file("x_signal", b"#" * (FILE_LIMIT + 1))

    working = world.signals / "x_signal.py"
    real_open, real_read = Path.open, Path.read_bytes

    def guarded(real):
        def call(self, *args, **kwargs):
            if self == working:
                raise AssertionError("the working file was opened")
            return real(self, *args, **kwargs)

        return call

    monkeypatch.setattr(Path, "open", guarded(real_open))
    monkeypatch.setattr(Path, "read_bytes", guarded(real_read))
    with pytest.raises(NotApprovedError) as info:
        world.resolve(coded_spec())
    assert str(info.value) == TOO_LARGE


def test_a_file_of_exactly_twice_the_limit_is_read_and_hashed(world: World) -> None:
    world.approve_both("x_signal", good_source())
    content = b"# " + b"x" * (FILE_LIMIT - 3) + b"\n"
    assert len(content) == FILE_LIMIT
    world.put_file("x_signal", content)
    with pytest.raises(NotApprovedError) as info:
        world.resolve(coded_spec())
    assert str(info.value) == f"code not approved: the file has sha {sha_of(content)[:8]}"


def test_approved_code_of_exactly_the_limit_that_is_saved_with_crlf_is_read_and_loads(world: World) -> None:
    base = good_source()
    padding = b"# " + b"y" * (MAX_SOURCE_BYTES - len(base) - 3) + b"\n"
    source = base + padding
    assert len(source) == MAX_SOURCE_BYTES
    sha = world.approve_both("x_signal", source)
    crlf = source.replace(b"\n", b"\r\n")
    assert MAX_SOURCE_BYTES < len(crlf) <= FILE_LIMIT  # larger than the approved code, inside the bound
    world.put_file("x_signal", crlf)
    assert world.resolve(coded_spec()).signal.coded.code_sha256 == sha  # type: ignore[union-attr]


def test_a_file_that_grew_after_it_was_measured_is_refused_too(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    world.approve_both("x_signal", good_source())
    path = world.put_file("x_signal", b"#" * (FILE_LIMIT + 1))
    real = Path.stat

    def small(self, *args, **kwargs):
        info = real(self, *args, **kwargs)
        if self != path:
            return info
        fields = list(info)
        fields[6] = 10  # st_size: the file looked small when it was measured
        return os.stat_result(fields)

    monkeypatch.setattr(Path, "stat", small)
    with pytest.raises(NotApprovedError) as info:
        world.resolve(coded_spec())
    assert str(info.value) == TOO_LARGE


def test_at_most_the_limit_plus_one_byte_is_asked_of_the_file(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    world.approve_both("x_signal", good_source())
    path = world.put_file("x_signal", good_source())
    asked: list[int] = []
    real_open = Path.open

    class Recording:
        def __init__(self, handle) -> None:
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            self.handle.close()

        def read(self, size: int = -1) -> bytes:
            asked.append(size)
            return self.handle.read(size)

    def opening(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)
        return Recording(handle) if self == path else handle

    monkeypatch.setattr(Path, "open", opening)
    world.resolve(coded_spec())
    assert asked == [FILE_LIMIT + 1]


def test_whether_the_file_counts_is_decided_without_following_links(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # os.path.lexists is true for a link to nothing, Path.exists is not. This test needs no link: Path.exists is made to
    # say "no" for the working file, and the older approved version on disk must still be the one that is found.
    v1, v2 = good_source(factor="0.0"), good_source(factor="0.5")
    world.approve_both("x_signal", v1)
    world.approve_code("x_signal", v2, hour=12)  # the latest approved version is v2
    path = world.put_file("x_signal", v1)
    real = Path.exists
    monkeypatch.setattr(Path, "exists", lambda self, *a, **k: False if self == path else real(self, *a, **k))
    assert world.resolve(coded_spec()).signal.coded.code_sha256 == sha_of(v1)  # type: ignore[union-attr]


def test_a_link_to_nothing_is_a_file_that_cannot_be_read_not_a_missing_file(world: World) -> None:
    world.approve_both("x_signal", good_source())  # the latest approved code would run if the link counted as absent
    world.signals.mkdir(parents=True)
    try:
        os.symlink(world.root / "nowhere.py", world.signals / "x_signal.py")
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available here")
    with pytest.raises(NotApprovedError, match="strategies/signals/x_signal.py cannot be read"):
        world.resolve(coded_spec())


def test_a_folder_where_the_file_should_be_is_not_a_regular_file(world: World) -> None:
    world.approve_both("x_signal", good_source())
    (world.signals / "x_signal.py").mkdir(parents=True)
    with pytest.raises(NotApprovedError) as info:
        world.resolve(coded_spec())
    assert str(info.value) == f"{SHOWN} cannot be read (not a regular file)"


# --- the defaults of the params model ---


def params_source(*fields: str, validator: bool = False, body: str = "return 1 / 0") -> bytes:
    lines = [
        '"""A signal with a params model."""',
        "from pydantic import Field, field_validator",
        "from backtest_agent.spec.signals import SignalParams, per_symbol_signal, register_signal",
        "",
        "",
        "class Params(SignalParams):",
        *(f"    {field}" for field in fields),
        *(
            [
                "",
                '    @field_validator("scale")',
                "    @classmethod",
                "    def _check(cls, scale):",
                f"        {body}",
            ]
            if validator
            else []
        ),
        "",
        "",
        '@register_signal("x_signal", params=Params)',
        "def x_signal(prices, params):",
        "    return per_symbol_signal(prices, lambda close: close * 0.0)",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def resolved_params(world: World, *fields: str, params: dict | None = None) -> dict:
    source = params_source(*fields)
    world.put_file("x_signal", source)
    world.approve_both("x_signal", source)
    return world.resolve(coded_spec(params=params)).to_dict()["signal"]["params"]


CANNOT_HOLD = "the params model of the code has a default that a spec cannot hold: {} is {}; "
RULE = "defaults must be numbers, text, true or false, or lists of those"


@pytest.mark.parametrize(
    ("field", "name", "shown"),
    [
        ("cap: float | None = None", "'cap'", "None"),
        ("limits: dict = {}", "'limits'", "{}"),
        ("limits: dict = {'a': 1}", "'limits'", "{'a': 1}"),
        ("pair: tuple = (1.0, 2.0)", "'pair'", "(1.0, 2.0)"),
        ("nested: list = [1, [2]]", "'nested'", "[1, [2]]"),
        ("rate: float = float('nan')", "'rate'", "nan"),
        ("rate: float = float('inf')", "'rate'", "inf"),
    ],
)
def test_a_default_that_a_spec_cannot_hold_is_a_gate_error_not_a_pydantic_error(
    world: World, field: str, name: str, shown: str
) -> None:
    before = SIGNALS.snapshot()
    source = params_source(field)
    world.put_file("x_signal", source)
    world.approve_both("x_signal", source)
    with pytest.raises(GateError) as info:
        world.resolve(coded_spec())
    assert type(info.value) is GateError
    assert str(info.value) == CANNOT_HOLD.format(name, shown) + RULE
    assert coded_modules() == [] and get_signal("x_signal").sha256 == sha_of(
        source
    )  # it loaded; its params did not fit
    assert SIGNALS.snapshot().keys() >= before.keys()


def test_defaults_of_the_kinds_a_spec_can_hold_are_accepted_and_written_out(world: World) -> None:
    params = resolved_params(
        world,
        "weights: list[float] = [1.0, 2.0]",
        "label: str = 'fast'",
        "flag: bool = True",
        "window: int = 14",
        "rate: float = 0.5",
        "names: list[str] = []",
    )
    assert params == {
        "weights": [1.0, 2.0],
        "label": "fast",
        "flag": True,
        "window": 14,
        "rate": 0.5,
        "names": [],
    }


def test_a_value_given_in_the_spec_replaces_the_default(world: World) -> None:
    params = resolved_params(world, "weights: list[float] = [1.0, 2.0]", params={"weights": [3.0]})
    assert params == {"weights": [3.0]}


def test_a_validator_of_the_code_that_raises_something_else_is_a_gate_error(world: World) -> None:
    source = params_source("scale: float = 1.0", validator=True)
    world.put_file("x_signal", source)
    world.approve_both("x_signal", source)
    with pytest.raises(GateError) as info:
        world.resolve(coded_spec())
    assert str(info.value) == "the params model of 'x_signal' failed: ZeroDivisionError: division by zero"
    assert isinstance(info.value.__cause__, ZeroDivisionError)


def test_a_default_that_the_model_itself_does_not_accept_is_a_gate_error(world: World) -> None:
    source = params_source("scale: float = Field(2.0, le=1.0)")
    world.put_file("x_signal", source)
    world.approve_both("x_signal", source)
    with pytest.raises(GateError) as info:
        world.resolve(coded_spec())
    assert str(info.value) == (
        "the params model of the code does not accept its own defaults: scale: Input should be less than or equal to 1"
    )


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('raise RuntimeError("bad")', "RuntimeError: bad"),
        ('raise KeyError("scale")', "KeyError: 'scale'"),
        ("return 1 / 0", "ZeroDivisionError: division by zero"),
    ],
)
def test_a_validator_that_runs_on_a_value_of_the_spec_and_raises_something_else_is_a_gate_error(
    world: World, body: str, message: str
) -> None:
    source = params_source("scale: float = 1.0", validator=True, body=body)
    world.put_file("x_signal", source)
    world.approve_both("x_signal", source)
    with pytest.raises(GateError) as info:
        world.resolve(coded_spec(params={"scale": 0.5}))  # the value is given, so the validator runs in the first pass
    assert str(info.value) == f"the params model of 'x_signal' failed: {message}"


def test_a_params_error_is_still_a_spec_error(world: World) -> None:
    source = params_source("window: int = 14")
    world.put_file("x_signal", source)
    world.approve_both("x_signal", source)
    with pytest.raises(SpecError) as info:
        world.resolve(coded_spec(params={"window": "many"}))
    assert [p.path for p in info.value.problems] == ["signal.params.window"]


# --- the compile call ---


def test_the_code_is_compiled_without_inheriting_the_future_flags_of_the_loader() -> None:
    tree = ast.parse((Path(__file__).resolve().parents[1] / "src/backtest_agent/coded/loader.py").read_text("utf-8"))
    calls = [
        n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "compile"
    ]
    assert len(calls) == 1
    keywords = {k.arg: k.value for k in calls[0].keywords}
    assert isinstance(keywords.get("dont_inherit"), ast.Constant) and keywords["dont_inherit"].value is True
    assert [a.value for a in calls[0].args[2:3] if isinstance(a, ast.Constant)] == ["exec"]


def test_what_is_not_expected_to_fail_in_the_last_step_is_still_a_gate_error(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.approve_both("x_signal", good_source())
    world.put_file("x_signal", good_source())
    spec = coded_spec()

    def refuse(*args, **kwargs):
        raise UnknownSignalError("the registry changed under the gate")

    monkeypatch.setattr("backtest_agent.coded.loader.StrategySpec.model_validate", refuse)
    with pytest.raises(GateError) as info:
        world.resolve(spec)
    assert str(info.value) == "the resolved spec is not valid: the registry changed under the gate"
