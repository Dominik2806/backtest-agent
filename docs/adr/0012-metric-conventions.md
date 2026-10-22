# 0012: Metric conventions

- **Status:** Accepted

## Context

Every run is judged with the same numbers, and a different convention for one of them (the year, the standard
deviation, what a drawdown is measured from) changes the verdict. The conventions have to be fixed once, written down
and testable by hand. The formulas, the assumptions and the fixtures are in [metrics.md](../metrics.md).

## Decision

- **Pure functions on the net return series.** Metrics are functions of `BacktestResult.returns` (first bar against the
  initial equity), plus the weights and turnover of the run for exposure and turnover. Total return reuses
  `BacktestResult.net_return`; there is no second formula. The result type holds plain `float`, `int`, `str` or `None`.
- **Explicit assumptions, stored with the result.** `periods_per_year` (default 252) and the annual `risk_free_rate`
  (default 0) are parameters and are part of `PerformanceMetrics`, so a report can print them. The risk-free rate is
  converted per bar by compounding, `(1 + rf)^(1/P) - 1`; the standard deviation is the sample one (`ddof = 1`).
- **CAGR is counted in bars**, `(1 + T)^(P / n) - 1`. The first bar is measured against the initial equity, so `n`
  returns cover `n` periods; a date-based year would count `n - 1` intervals. The limitation (holidays, 24/7 markets) is
  documented, and `periods_per_year` is the lever.
- **Undefined is `None`, never NaN or inf.** Ratios whose denominator is zero (Sharpe, Sortino, Calmar), too few bars,
  and an empty series give `None`; each case is listed in metrics.md. Ruin is defined (total return, CAGR and drawdown
  -1) and needs `BacktestResult.returns` to be 0.0 after the ruin instead of 0/0 (changed in Phase 6, see ROADMAP).
- **A tolerance, not an exact zero.** A per-bar standard deviation, downside deviation or drawdown below `1e-12` counts as
  zero, because the standard deviation of a constant series is about 1e-18 in floating point and dividing by it would turn
  an undefined Sharpe ratio into a huge number. The tolerance is documented and tested with constants that are inexact in
  binary (0.01, 0.1, 1/3).
- **Drawdown** is measured on the equity path that starts with the initial equity as the first peak, so a loss on the
  first bar is a drawdown. The duration is the distance from a peak to its recovery (or to the end if it never recovers),
  in bars and in calendar days, for the stretch with the most bars. Calmar is CAGR over the absolute maximum drawdown.
- **Hit rate is a statistic of bars** (positive bars over all bars, bars in cash count as misses). Trade-level
  statistics belong to the report of Phase 7.
- **Turnover is reported two-sided and one-sided.** The engine's turnover is two-sided (buying everything is 1.0); the
  one-sided figure is half of it. Both are annualized by the years of the run and labelled in the type and the docs.
- **Months are calendar months of the bar dates**, compounded. The first and the last month are taken as measured and
  can be partial; the label and the number of months make that visible.

Alternatives rejected: calendar-day years for CAGR (inconsistent with the first bar, needs a dated start); `rf / P` as
the per-bar rate (does not compound to `rf`); exact equality to detect a zero deviation (float residue gives huge
ratios); NaN or inf for undefined metrics (not serializable, easy to miss); dropping partial months (needs an
exchange calendar); a hit rate over invested bars only (a different statistic that needs the weights).

## Consequences

- Hand-calculated fixtures can use `periods_per_year` 4 or 5 and round numbers.
- Every number a report prints has one definition; the Phase 8 journal stores `PerformanceMetrics.to_dict()` unchanged.
- Calmar and CAGR of short runs are strongly annualized; this is stated in the docs, not hidden.
