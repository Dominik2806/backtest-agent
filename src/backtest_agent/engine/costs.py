"""Cost hook and the basis-point cost model (see "Costs" in docs/engine.md and ADR 0010)."""

from dataclasses import dataclass
from typing import Protocol

from backtest_agent.spec.schema import CostsSpec

_BPS = 10_000.0


class CostModel(Protocol):
    """Cost of one trade."""

    def cost(self, symbol: str, notional: float) -> float:
        """Cost in currency of trading ``notional`` (absolute traded value) of ``symbol``; finite and 0 or more.

        The core does not trust a model: a negative, NaN or infinite value raises ``EngineInvariantError``.
        """
        ...


class NoCosts:
    """Trading is free."""

    def cost(self, symbol: str, notional: float) -> float:
        return 0.0


@dataclass(frozen=True)
class BpsCosts:
    """Commission, half-spread and slippage in basis points of the traded value, with an optional minimum commission.

    ``cost = max(commission_bps / 10000 * N, min_commission) + spread_bps / 10000 * N + slippage_bps / 10000 * N``
    for a trade of notional ``N > 0``. ``spread_bps`` is the half-spread as the spec states it; it is not halved again.
    The minimum applies to the commission only. A trade without notional costs nothing.
    """

    commission_bps: float
    spread_bps: float
    slippage_bps: float
    min_commission: float = 0.0

    @classmethod
    def from_spec(cls, costs: CostsSpec) -> "BpsCosts":
        return cls(costs.commission_bps, costs.spread_bps, costs.slippage_bps, costs.min_commission)

    def cost(self, symbol: str, notional: float) -> float:
        if notional <= 0.0:
            return 0.0
        commission = max(self.commission_bps / _BPS * notional, self.min_commission)
        return commission + self.spread_bps / _BPS * notional + self.slippage_bps / _BPS * notional
