"""Helpers for the tests of a coded signal through the command line: the coded twin of fixture R3b of docs/cli.md.

The strategy is ``hold_a``, a coded signal that does what ``buy_and_hold`` does, on the world of docs/cli.md (A against
B, 25 percent costs), so a run must print the numbers of that document. The sources and every hash below are
literals computed with ``hashlib`` and ``json`` in a throwaway script outside the project; nothing here computes an
expected value.
"""

from pathlib import Path

import yaml

from cli_helpers import at, run_cli
from report_helpers import spec_for

BRIEF = "Hold A for the whole period."
IDEA_SHA8 = "bc1586a4"


def _source(docstring: str) -> bytes:
    return (
        f'"""{docstring}"""\n'
        "import pandas as pd\n"
        "from pydantic import Field\n"
        "from backtest_agent.spec.signals import SignalParams, per_symbol_signal, register_signal\n"
        "\n"
        "\n"
        "class Params(SignalParams):\n"
        "    scale: float = Field(1.0, ge=0.0, le=1.0)\n"
        "\n"
        "\n"
        '@register_signal("hold_a", params=Params)\n'
        "def hold_a(prices, params):\n"
        "    return per_symbol_signal(prices, lambda close: pd.Series(params.scale, index=close.index))\n"
    ).encode()


HOLD_A = _source("Buy and hold, written as a coded signal.")  # 426 bytes
HOLD_B = _source("Buy and hold, written as a coded signal (second version).")  # 443 bytes
SHA_A = "8b0b3234cf07e5cf0807b5c5fd9122479babcce5719ff56fffd630e117e9a6ab"
SHA_B = "3d6935997808cac07daf75ff6688af6ed427d9dd008c35c17c5621338ce7df9d"
VARIANT_A = "ec8c4c28e116f8d24d0aed06063dcabb112d891364b7b84719276339176fc9ae"  # of the logged spec with SHA_A
VARIANT_B = "a111844c782bd13092db6b389b89ea5e86c620450e3e50bf34ceb9a1b05de73e"  # of the logged spec with SHA_B


def logged_spec(code_sha256: str) -> dict:
    """The spec of the coded run as ``run.json`` stores it: R3b with the coded signal, params with their defaults."""
    return {
        "benchmark": "B",
        "costs": {"commission_bps": 1000.0, "min_commission": 0.0, "slippage_bps": 500.0, "spread_bps": 1000.0},
        "data": {"provider": "yfinance"},
        "description": "A spec used in tests.",
        "execution": {"allow_same_bar_execution": False, "delay_bars": 1, "price": "open"},
        "initial_capital": 1000.0,
        "name": "Buy and hold A",
        "period": {"end": "2024-01-08", "start": "2024-01-02"},
        "rebalance": "on_signal",
        "schema_version": 1,
        "signal": {
            "coded": {"brief": BRIEF, "code_sha256": code_sha256},
            "id": "hold_a",
            "params": {"scale": 1.0},
        },
        "sizing": {"fraction": None, "method": "equal_weight"},
        "universe": ["A"],
    }


def write_hold_spec(workdir: Path, name: str = "spec.yaml", *, pin: str | None = None) -> Path:
    """The spec of R3b with the coded signal ``hold_a``; the unpinned spec has no ``code_sha256``."""
    data = spec_for().to_dict()
    coded = {"brief": BRIEF} | ({} if pin is None else {"code_sha256": pin})
    data["signal"] = {"id": "hold_a", "params": {}, "coded": coded}
    path = workdir / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def put_source(workdir: Path, data: bytes, *, folder: str = "strategies/signals") -> Path:
    path = workdir / folder / "hold_a.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def approve_all(
    workdir: Path, data: bytes, sha8: str, *, spec: str = "spec.yaml", options: tuple[str, ...] = ()
) -> None:
    """Approve the idea and the code the way a person does, with the command (the review step is skipped)."""
    put_source(workdir, data, folder=_strategies_folder(options))
    assert run_cli(["approve", spec, "--idea", *options], clock=at(0)).code == 0
    assert run_cli(["approve", spec, "--code", "--sha", sha8, *options], clock=at(0)).code == 0


def _strategies_folder(options: tuple[str, ...]) -> str:
    return options[options.index("--strategies-dir") + 1] if "--strategies-dir" in options else "strategies/signals"


def summary(run_id: str, family: str, trials: str) -> list[str]:
    """The lines of ``bt run`` for R3b; the numbers are the literals of docs/cli.md ("Example: one run")."""
    return [
        f"Run:        {run_id}",
        f"Strategy:   Buy and hold A (family {family})",
        f"Trials:     {trials}",
        "Period:     2024-01-02 to 2024-01-08, 5 bars",
        "Costs:      applied",
        "",
        "Metric               Strategy  Benchmark (B)",
        "Total return           17.13%        -21.59%",
        "CAGR              288,635.82%       -100.00%",
        "Sharpe ratio             5.87          -7.50",
        "Maximum drawdown      -12.00%        -21.59%",
        "",
        "Excess return (compared window): +38.72%",
        "",
        "Risk flags: none",
        f"Journal:    runs/{run_id}/run.json",
        f"Report:     reports/{run_id}/report.md and report.html",
    ]


TAIL = "Counts cover only runs logged in this journal."
FIRST = (
    "family hold_a: 1 distinct variant in 1 run as of this run. This run is run 1, a new variant (variant 1). " + TAIL
)
REPEAT = "family hold_a: 1 distinct variant in 2 runs as of this run. This run is run 2, a repeat of variant 1. " + TAIL
NEW_VARIANT = (
    "family hold_a: 2 distinct variants in 3 runs as of this run. This run is run 3, a new variant (variant 2). " + TAIL
)
