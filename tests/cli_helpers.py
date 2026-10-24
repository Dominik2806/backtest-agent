"""Helpers for the command line tests: run ``main`` with injected streams, clock and provider.

They build inputs only; no expected value of a test is computed here.
"""

import argparse
import io
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from backtest_agent.cli import main
from backtest_agent.data import DataProvider
from backtest_agent.spec import StrategySpec

CLOCK = datetime(2026, 1, 15, 10, 30, 5, tzinfo=UTC)


@dataclass(frozen=True)
class Outcome:
    code: int
    out: str
    err: str


def at(seconds: int) -> Callable[[], datetime]:
    """A clock that always says 2026-01-15 10:30:05 UTC plus ``seconds``."""
    return lambda: CLOCK + timedelta(seconds=seconds)


def run_cli(
    args: Sequence[str],
    *,
    provider: DataProvider | None = None,
    clock: Callable[[], datetime] | None = None,
) -> Outcome:
    """Run ``bt`` in process. The provider (if any) is returned by the factory whatever the cache dir is."""
    out, err = io.StringIO(), io.StringIO()
    kwargs = {}
    if provider is not None:
        kwargs["provider_factory"] = lambda cache_dir: provider
    code = main(list(args), clock=clock if clock is not None else at(0), stdout=out, stderr=err, **kwargs)
    return Outcome(code, out.getvalue(), err.getvalue())


def write_spec(folder: Path, spec: StrategySpec | dict, name: str = "spec.yaml") -> Path:
    """Write a spec (or a raw dict) as YAML into ``folder`` and return the path."""
    data = spec.to_dict() if isinstance(spec, StrategySpec) else spec
    path = folder / name
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def add_test_command(monkeypatch, handler: Callable[[argparse.Namespace, object], int]) -> None:
    """Register the extra command ``probe`` (runs ``handler(args, context)``) for the duration of a test."""
    from backtest_agent.cli import commands

    original = commands.register

    def register(sub, common):
        original(sub, common)
        probe = sub.add_parser("probe", parents=[common])
        probe.set_defaults(handler=handler)

    monkeypatch.setattr(commands, "register", register)
