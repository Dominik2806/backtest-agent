"""Helpers for the tests of the gate: a world of folders, signal sources, specs and the fixtures that keep tests apart.

They build inputs only; no expected value of a test is computed here (the hashes of the sources are taken with
``hashlib`` by the tests that need them).

Rules every test that registers or loads a signal follows: the registry is restored afterwards (the autouse fixture
below), marker files of the canary are written under ``tmp_path`` only, and ``sys.modules`` is checked for modules of
coded signals.
"""

import hashlib
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backtest_agent.coded.approvals import approve_code, approve_idea
from backtest_agent.coded.loader import clear_checked, resolve_coded
from backtest_agent.spec import SIGNALS, StrategySpec
from runner_helpers import make_spec

BRIEF = "B"
CANARY_ID = "canary_signal"


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 2, hour, minute, 0, tzinfo=UTC)


def sha_of(source: bytes) -> str:
    """SHA-256 of the LF form of a source (taken with hashlib, not with project code)."""
    return hashlib.sha256(source.replace(b"\r\n", b"\n")).hexdigest()


def good_source(signal_id: str = "x_signal", factor: str = "0.0") -> bytes:
    """A source that passes the static check: a params model with one field and a constant signal."""
    lines = [
        '"""A signal that holds a constant."""',
        "from pydantic import Field",
        "from backtest_agent.spec.signals import SignalParams, per_symbol_signal, register_signal",
        "",
        "",
        "class Params(SignalParams):",
        "    scale: float = Field(1.0, ge=0.0, le=1.0)",
        "",
        "",
        f'@register_signal("{signal_id}", params=Params)',
        f"def {signal_id}(prices, params):",
        f"    return per_symbol_signal(prices, lambda close: close * 0.0 + {factor} * params.scale)",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def canary_source(signal_id: str = CANARY_ID, factor: str = "0.0", extra: tuple[str, ...] = ()) -> bytes:
    """A source whose import writes a line to the file named by the environment variable CANARY_MARKER.

    It uses ``open`` and ``os``, which the static check refuses, so tests that load it switch the static check off; the
    marker then shows whether the gate loaded the code. ``extra`` lines are put after the marker line.
    """
    lines = [
        '"""A canary: importing it leaves a trace."""',
        "import os",
        "from backtest_agent.spec.signals import SignalParams, per_symbol_signal, register_signal",
        "",
        'with open(os.environ["CANARY_MARKER"], "a") as marker:',
        f'    marker.write("imported {factor}" + chr(10))',
        *extra,
        "",
        "",
        f'@register_signal("{signal_id}", params=SignalParams)',
        f"def {signal_id}(prices, params):",
        f"    return per_symbol_signal(prices, lambda close: close * 0.0 + {factor})",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def coded_spec(
    signal_id: str = "x_signal", *, brief: str = BRIEF, pin: str | None = None, params: dict | None = None
) -> StrategySpec:
    """A valid spec for the fake provider (AAA, BBB) with the coded signal ``signal_id``."""
    data = make_spec(signal="buy_and_hold", params={}).to_dict()
    coded = {"brief": brief} | ({} if pin is None else {"code_sha256": pin})
    data["signal"] = {"id": signal_id, "params": params or {}, "coded": coded}
    return StrategySpec.model_validate(data)


def with_id(spec: StrategySpec, signal_id: str) -> StrategySpec:
    """The same spec with another signal id, built around the rules of the parser (a forged spec)."""
    return spec.model_copy(update={"signal": spec.signal.model_copy(update={"id": signal_id})})


@dataclass
class World:
    """The folders of one test: approvals, the editable signals folder and the canary marker, all under tmp_path."""

    root: Path

    @property
    def approvals(self) -> Path:
        return self.root / "approvals"

    @property
    def signals(self) -> Path:
        return self.root / "strategies" / "signals"

    @property
    def marker(self) -> Path:
        return self.root / "marker.txt"

    def put_file(self, signal_id: str, source: bytes) -> Path:
        self.signals.mkdir(parents=True, exist_ok=True)
        path = self.signals / f"{signal_id}.py"
        path.write_bytes(source)
        return path

    def approve_idea(self, signal_id: str, brief: str = BRIEF, hour: int = 10) -> None:
        approve_idea(self.approvals, signal_id, brief, at(hour))

    def approve_code(self, signal_id: str, source: bytes, brief: str = BRIEF, hour: int = 11) -> str:
        return approve_code(self.approvals, signal_id, brief, source, at(hour))[1]

    def approve_both(self, signal_id: str, source: bytes, brief: str = BRIEF) -> str:
        self.approve_idea(signal_id, brief)
        return self.approve_code(signal_id, source, brief)

    def resolve(self, spec: StrategySpec, *, stored: bool = False) -> StrategySpec:
        return resolve_coded(spec, approvals_dir=self.approvals, strategies_dir=None if stored else self.signals)

    def marker_lines(self) -> list[str]:
        return self.marker.read_text(encoding="utf-8").splitlines() if self.marker.exists() else []


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    monkeypatch.setenv("CANARY_MARKER", str(tmp_path / "marker.txt"))
    return World(tmp_path)


@pytest.fixture
def static_check_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the static check accept anything, in the approvals and in the loader, so that the canary can be loaded.

    Only the gate tests use it, to see whether the gate would have loaded the code. The static check has its own tests,
    and one test shows that the real check refuses the canary.
    """
    monkeypatch.setattr("backtest_agent.coded.approvals.check_source", lambda data, signal_id: None)
    monkeypatch.setattr("backtest_agent.coded.loader.check_source", lambda data, signal_id: None)


def coded_modules() -> list[str]:
    return sorted(name for name in sys.modules if name.startswith("coded_signal_") or "canary" in name)


@pytest.fixture(autouse=True)
def registry_and_modules_are_restored() -> Iterator[None]:
    """Every test starts and ends with the registry it found, and no module of a coded signal is ever created."""
    before = SIGNALS.snapshot()
    clear_checked()
    assert coded_modules() == []
    yield
    SIGNALS.restore(before)
    clear_checked()
    assert coded_modules() == []
