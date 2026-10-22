"""Cost hook (see docs/engine.md). Phase 4 applies no costs; Phase 5 plugs a model in."""

from typing import Protocol


class CostModel(Protocol):
    """Cost of one trade."""

    def cost(self, symbol: str, notional: float) -> float:
        """Cost in currency of trading ``notional`` (absolute traded value) of ``symbol``; 0 or more."""
        ...


class NoCosts:
    """The only model of Phase 4: trading is free."""

    def cost(self, symbol: str, notional: float) -> float:
        return 0.0
