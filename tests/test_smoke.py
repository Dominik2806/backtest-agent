import importlib
import tomllib
from pathlib import Path

import pytest

import backtest_agent

SUBPACKAGES = ["data", "spec", "engine", "metrics", "reporting", "journal", "robustness"]


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackage_imports(name: str) -> None:
    module = importlib.import_module(f"backtest_agent.{name}")
    assert module.__doc__


def test_version_matches_pyproject() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    assert backtest_agent.__version__ == expected
