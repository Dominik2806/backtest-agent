# 0010: Cost model

- **Status:** Accepted

## Context

Results are only honest when they include what trading costs. The spec has three rates (`commission_bps`,
`spread_bps`, `slippage_bps`) and, from Phase 5, an optional `min_commission`. How they turn into money, how a purchase
is paid when fees are due, and what "gross" means decide every number downstream (metrics, benchmark, report, auditor).
The details are specified in "Costs" of [engine.md](../engine.md).

## Decision

- **Fee, not a worse fill price.** A cost is a cash fee charged on the bar of the fill. The `price` of a trade stays the
  open or close of that bar and the fee is a separate column (`cost`) and a per-bar series. Reasons: the trades can be
  checked against the data (the price is a fact, not a model output); commission, spread and slippage stay separable and
  the total is exact; turnover and notional keep their meaning; gross and net differ by exactly the fees and a twin run
  gives the gross path; hand calculations stay short. The price of this choice: slippage is not visible in the fill
  price. For spread and slippage the two forms are economically close, the difference is second order (a fee is paid in
  cash after the fill, a worse price changes the number of shares bought).
- **Half-spread.** `spread_bps` is the half-spread, as the spec has always stated. A trade pays
  `spread_bps / 10000 * notional`; it is not halved again.
- **Cost of a fill.** `max(commission_bps / 10000 * N, min_commission) + spread_bps / 10000 * N + slippage_bps / 10000 * N`,
  on the notional `N` of the actual fill, for buys and sells alike. A deferred order is charged on the bar where it
  fills. The minimum applies to the commission only, per trade (one symbol on one bar), in account currency, and its
  default 0 means no minimum.
- **A sale pays out of its proceeds.** The fee of a sale is capped at its notional, so a sale never brings in a negative
  amount and cash cannot go negative through a sale. Buys are not capped: a buy that cannot pay even its minimum fee is
  not made.
- **Funding rule.** Sells are filled first, net of their fees. Buys need notional plus fee. If the cash cannot cover
  all of them, all buys are scaled down by one factor `f`, found by bisection on the model's own cost function (exact
  when trading is free). This makes a fully invested target unreachable by exactly the fees, which is correct.
- **Remainder rule.** The part of a buy that cash could not cover even without fees stays open (cash that is still to
  come, as in H12); the part that only the fees kept from being bought is dropped. Otherwise every rebalance to a
  fully invested portfolio would leave a tiny pending remainder and inflate `deferred_orders` and `unfilled_orders`.
  With zero costs the behaviour is identical to Phase 4 (tested bit for bit).
- **Untrusted models.** The core raises `EngineInvariantError` for a negative, NaN or infinite cost and when cash would
  end up negative, because a custom `CostModel` is not trusted.
- **Gross definition.** The gross result is the same simulation with all costs at zero (a twin run). Costs compound, so
  adding the total costs back to the net equity would be wrong. The cost drag is the gross return minus the net return,
  and the share of the gross return that costs ate is the drag divided by the gross return (none if that is not positive).
  `run_backtest` reports them in the second part of Phase 5.
- **"More turnover means higher costs" is tested in the form in which it is true.** As a general statement it is not a
  theorem: costs are in currency while turnover is a ratio to the portfolio value, and a minimum commission depends on the
  number of trades, so a strategy with higher turnover on lower prices or a smaller portfolio can pay less. What holds
  exactly, and is tested: without a minimum fee the cost of every trade is the combined rate times its notional (costs
  are a strictly increasing function of the traded notional); and on a world with flat prices and fixed costs, adding a
  round trip to the signal strictly raises both total turnover and total costs, because each round trip loses the same
  fraction of the equity and nothing else changes between the runs.

Alternatives rejected: costs as an adverse fill price (hides the components, mixes a model output into a data fact);
keeping every remainder pending (counters would count fees); dropping every remainder when no sale is open (would change
the Phase 4 behaviour for stale deferred quantities even with zero costs); halving `spread_bps` again; closed-form scale
factors only (cannot express a minimum fee for a general model).

## Consequences

- The cost fixtures use a documented tolerance of 1e-9 because the bisection leaves a residual at the floating point
  resolution; the zero-cost behaviour is compared exactly.
- Orders are sized on the value before costs, so after a rebalance the weights are below target by the fees.
- A portfolio can be ruined by fees: equity 0, weights and turnover are then 0 instead of NaN.
- A minimum fee can make the engine sell for a buy that then cannot be paid (H19b, Jan 4): the fee of the sale is lost and the portfolio ends slightly off target. This follows the rules and is not an error.
- Phase 6 runs the benchmark through the same engine with the same costs and uses the gross and net results.
