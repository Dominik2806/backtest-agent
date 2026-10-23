# Metrics

Performance and risk metrics on the **net** return series of a `BacktestResult` (F-12). The code is in
`src/backtest_agent/metrics/performance.py`, the decisions are in [ADR 0012](adr/0012-metric-conventions.md). The
benchmark comparison (F-13, `benchmark.py`, `relative.py`, `evaluation.py`, [ADR 0013](adr/0013-benchmark-comparison.md))
is described in "Benchmark and relative metrics" at the end of this document.

All functions are pure: a metric is a function of a return series (and, for exposure and turnover, of the weights and the
turnover of the run). Results are plain `float`, `int`, `str` or `None`, so the journal (Phase 8) can serialize them.
**A metric that is not defined is `None`, never NaN and never inf**; the table "When a metric is None" lists every case.

## Assumptions

| Assumption | Value | Where it matters |
|---|---|---|
| `periods_per_year` `P` | 252 by default, an explicit parameter | CAGR, volatility, Sharpe, Sortino, turnover (every annualized number) |
| `risk_free_rate` `rf` | 0.0 by default, **annual** | Sharpe and Sortino (the target return) |
| Per-bar risk-free return `rho` | `(1 + rf)^(1/P) - 1` (compound), 0 when `rf = 0` | Sharpe, Sortino |
| Standard deviation | **sample** standard deviation, `ddof = 1` | volatility, Sharpe, tracking error |
| Zero tolerance `eps` | `1e-12` on a per-bar quantity | "is this deviation zero?" (see below) |
| Drawdown tolerance | `1e-12` | "is the portfolio below its peak?" (see below) |
| Exposure tolerance | `1e-9` of equity | "does the portfolio hold a position on this bar?" |

Both assumptions are stored in every `PerformanceMetrics` (`assumptions`), so a report can print them. `rf` must be
above -1 and `P` must be a positive integer, otherwise `ValueError`.

**Why a tolerance and not an exact zero.** The standard deviation of a constant series such as `[0.01] * 4` is not
exactly 0 in floating point; it can be around 1e-18. Dividing by it would turn a Sharpe ratio that is not defined into a
huge number. So a per-bar standard deviation, downside deviation or tracking error **below `eps = 1e-12` counts as
zero**: the volatility is then reported as exactly 0.0 and the ratios that divide by it are `None`. `1e-12` is far above
the rounding noise (about 1e-16 times the size of the returns) and far below any real daily volatility (about 1e-3).
Likewise a drawdown above -1e-12 is treated as no drawdown (a recovery that rounding leaves 2e-16 short still counts as
recovered).

**Input.** Returns are `pd.Series` of `float64` with a sorted, unique `DatetimeIndex`; NaN, infinity or a return below
-1 raise `ValueError` (that is a bug upstream, not data). `BacktestResult.returns` is the net series: the first bar is
measured against `initial_equity`, and after a ruin (equity 0) every later bar is 0.0 (see `engine.md`).

## Notation

`n` is the number of bars (returns) `r_1 ... r_n` on the dates `d_1 ... d_n`; `years Y = n / P`. The **equity path** has
`n + 1` points: `p_0 = 1` (initial equity, scaled to 1, so no metric depends on the capital) and `p_k = p_{k-1} * (1 +
r_k)`. The date of point `k >= 1` is `d_k`; the date of `p_0` is `d_1` (the initial equity has no date of its own, it
is dated on the first bar).

## Formulas

**Total return.** `T = p_n - 1 = (1 + r_1) ... (1 + r_n) - 1`. For a `BacktestResult` this is **`net_return`** (final
equity over `initial_equity` minus 1); the metrics reuse that property and do not define a second formula. For `n = 0`
it is `None`.

**CAGR.** `(1 + T)^(1 / Y) - 1 = (1 + T)^(P / n) - 1`, counted in **bars**: the first bar is measured against the
initial equity, so `n` returns cover `n` periods. `1 + T = 0` (ruin) gives -1.0. `None` for `n = 0` or if the result is
not finite (a huge gain over very few bars). *Limitation:* a year is assumed to have `P` bars. A calendar with
holidays has fewer than 252 bars in some years, and a market that trades every day (crypto) has 365; set
`periods_per_year` accordingly. A run shorter than a year is annualized strongly: 10 percent in one bar is 1.1^252 - 1.

**Volatility.** `s = sqrt( sum (r_i - mean)^2 / (n - 1) )`, `vol = s * sqrt(P)`. `None` for `n < 2`. If `s < eps`, `vol = 0.0`.

**Sharpe.** `(mean(r) - rho) / s * sqrt(P)`. `None` for `n < 2` or `s < eps`. (The standard deviation of the excess
return equals `s` because `rho` is constant.)

**Sortino.** Downside deviation against the same target over **all** bars: `D = sqrt( (1 / n) * sum min(r_i - rho,
0)^2 )`; `Sortino = (mean(r) - rho) / D * sqrt(P)`. `None` for `n < 2` or `D < eps` (no bar below the target; the ratio
is not defined, not infinite).

**Drawdown.** With the running maximum `M_k = max(p_0 ... p_k)` (it includes the initial equity, so a loss on the first
bar is a drawdown) the drawdown of point `k` is `DD_k = p_k / M_k - 1`, 0 or less. A point is **underwater** if `DD_k <
-1e-12`.
- `max_drawdown = min_k DD_k` (a negative fraction), 0.0 if no point is underwater. `None` for `n = 0`.
- `current_drawdown = DD_n` (0.0 if not underwater).
- **Longest drawdown.** A stretch is a maximal run of consecutive underwater points `a ... b`; its **peak** is the point
  `a - 1` (not underwater) and its **recovery** is the point `b + 1`, the first point back at or above the peak, if it
  exists (`b < n`). Its length is the distance from the peak to the recovery in **bars** (point numbers), or to the last
  point `n` if it never recovered, and in **calendar days** between the dates of the same two points. The reported
  stretch is the one with the most bars (the first on a tie); `longest_drawdown_bars` and `longest_drawdown_days` belong
  to it. Without any underwater point both are 0; `None` for `n = 0`.

**Calmar.** `CAGR / |max_drawdown|`. `None` if the drawdown is 0 or the CAGR is `None`.

**Hit rate.** `#(r_i > 0) / n`, over **all** bars. A bar in cash (return 0) is a miss, so a strategy that is often out of
the market has a low hit rate. This is a statistic of bars; trade-level statistics (win rate, profit factor) belong to
the report of Phase 7. `None` for `n = 0`.

**Exposure.** With `s_i` the sum of the weights of bar `i` (`BacktestResult.weights`, share of equity at the end of the
bar, cash is the rest): `exposure_mean = mean(s_i)`; `exposure_invested_share = #(s_i > 1e-9) / n` (the tolerance keeps
float dust of a fill from counting as a position; the mean itself includes the dust, which changes it only at the
15th digit). `None` for `n = 0`.

**Turnover.** The engine's turnover is **two-sided**: the sum of the absolute trade notionals of a bar over the portfolio
value, so buying the whole portfolio from cash is 1.0 and a complete switch from one asset to another is 2.0. The
annualized two-sided turnover is `sum(turnover) / Y` (`Y = n / P` over all `n` bars, the first one included); the **one-sided** figure (the value bought, or equivalently
sold, per year; the figure that most sources call turnover) is **half of it**. Both are reported and labelled
(`turnover_two_sided_annual`, `turnover_one_sided_annual`). `None` for `n = 0`.

**Best and worst month.** Bars are grouped by the calendar month of their date; the return of a month is the compounded
return of its bars, `prod(1 + r_i) - 1`. `best_month` and `worst_month` are the largest and smallest, with the label
`"YYYY-MM"`; `n_months` is the number of months that have at least one bar. The first and the last month are taken as
they are, over the bars present. They can be partial (a period that starts on the 15th), and the first bar of the first
month is measured against the initial equity. A partial month is not dropped, because telling it from a full one would
need an exchange calendar; the label and `n_months` make it visible. A series with one month has the same best and
worst month. `None` for `n = 0`.

### When a metric is None

| Metric | `None` when |
|---|---|
| every metric | `n = 0` (an empty series; `n_bars` is 0 and `n_months` 0) |
| `total_return`, `years`, `hit_rate`, drawdowns, exposure, turnover, months | only for `n = 0` |
| `cagr` | `n = 0`, or the result is not finite |
| `volatility`, `sharpe`, `sortino` | `n < 2` |
| `sharpe` | also if the standard deviation is below `eps` |
| `sortino` | also if the downside deviation is below `eps` |
| `calmar` | `max_drawdown` is 0, or `cagr` is `None` |

A single bar therefore has a total return, CAGR, drawdown and hit rate but no volatility, Sharpe or Sortino. A series
whose returns are all equal (positive, negative or 0) has volatility 0.0 and no Sharpe. A series without a bar below the
target has no Sortino. A portfolio ruined by fees has total return -1, CAGR -1, drawdown -1, and finite volatility and
Sharpe, because the returns after the ruin are 0.0.

## Hand-calculated fixtures

The expected values are literals taken from this document; `tests/test_metrics_hand_calculated.py` never computes one with
project code or a helper that mirrors it. Fixtures M1 to M11 are pure series (`P = 4` unless stated, so `Y = n / 4`
and the arithmetic stays exact; dates are consecutive business days from 2024-01-02 unless stated: Jan 2, 3, 4, 5, 8).
M12 and M13 run through `run_backtest` (`P = 5`, so `Y = 1`). The comparison tolerance is `1e-9` (relative and
absolute): the decimals below are written to 12 or more digits, and exact values (0.21, 10, ...) hold to far more.
`sqrt` values are given as the closed form and as a decimal.

### M1 A mixed path (`P = 4`, `rf = 0`)

Input: `r = [+0.10, -0.20, +0.25, +0.10]`.

- Equity points: `1, 1.1, 0.88, 1.1, 1.21` (1.1 * 0.8 = 0.88; 0.88 * 1.25 = 1.1; 1.1 * 1.1 = 1.21).
- `T = 0.21`; `Y = 4 / 4 = 1`; `CAGR = 1.21^1 - 1 = 0.21`.
- `mean = 0.25 / 4 = 0.0625`. Deviations `0.0375, -0.2625, 0.1875, 0.0375`; squares `0.00140625, 0.06890625, 0.03515625,
  0.00140625`, sum `0.106875`; `/ 3 = 0.035625`; `s = sqrt(0.035625) = 0.188745860882`. `vol = 2 s = 0.377491721764`.
- `Sharpe = 0.0625 / 0.188745860882 * 2 = 0.662266178533`.
- Downside against 0: only `-0.20`; `D = sqrt(0.04 / 4) = 0.1`; `Sortino = 0.0625 / 0.1 * 2 = 1.25`.
- Hit rate `3 / 4 = 0.75`.
- Drawdown: `M = 1, 1.1, 1.1, 1.1, 1.21`; `DD = 0, 0, 0.88/1.1 - 1 = -0.2, 0, 0`. Max drawdown `-0.2`; current `0`.
  One stretch: underwater point 2, peak point 1 (date Jan 2), recovery point 3 (date Jan 4): **2 bars, 2 days**.
- `Calmar = 0.21 / 0.2 = 1.05`.
- Months: all four bars are in January: `0.21`, label `2024-01`, best = worst, `n_months = 1`.

### M2 The same series with a risk-free rate (`P = 4`, `rf = 0.4641`)

`rho = 1.4641^(1/4) - 1 = 1.1 - 1 = 0.1` (1.1^4 = 1.4641). Everything that does not use `rho` is as in M1.

- `r - rho = [0, -0.30, +0.15, 0]`; mean excess `-0.15 / 4 = -0.0375`.
- `Sharpe = -0.0375 / 0.188745860882 * 2 = -0.397359707120`.
- Downside against 0.1: only `-0.30`; `D = sqrt(0.09 / 4) = 0.15`; `Sortino = -0.0375 / 0.15 * 2 = -0.5`.

### M3 Starts under water and never recovers (`P = 4`, `rf = 0`)

Input: `r = [-0.10, -0.10, +0.05]`, dates Jan 2, 3, 4.

- Equity points `1, 0.9, 0.81, 0.8505`. `T = -0.1495`. `Y = 3 / 4 = 0.75`; `CAGR = 0.8505^(4/3) - 1 = -0.194190424329`.
- `mean = -0.15 / 3 = -0.05`; deviations `-0.05, -0.05, +0.10`; squares sum `0.0025 + 0.0025 + 0.01 = 0.015`; `/ 2 = 0.0075`;
  `s = sqrt(0.0075) = 0.086602540378`; `vol = 2 s = 0.173205080757`; `Sharpe = -0.05 / s * 2 = -1.154700538379`.
- Downside against 0: `0.01, 0.01, 0`; `D = sqrt(0.02 / 3) = 0.081649658093`; `Sortino = -0.05 / D * 2 = -1.224744871392`.
- Drawdown: the peak is the initial equity (point 0, dated on the first bar, Jan 2). `DD = 0, -0.1, -0.19, 0.8505 - 1 =
  -0.1495`. Max drawdown `-0.19`; current drawdown `-0.1495`. One stretch, points 1 to 3, no recovery: **3 bars**
  (point 3 minus point 0), **2 days** (Jan 2 to Jan 4).
- `Calmar = -0.194190424329 / 0.19 = -1.022054864889`. Hit rate `1 / 3`.

### M4a and M4b Constant returns (values that are inexact in binary)

`P = 4`, `rf = 0`, four bars.

| | M4a `r = [0.01] * 4` | M4b `r = [0.1] * 4` |
|---|---|---|
| total return and CAGR (`Y = 1`) | `1.01^4 - 1 = 0.04060401` | `1.1^4 - 1 = 0.4641` |
| volatility | `0.0` (the standard deviation is 0, the float residue is below `eps`) | `0.0` |
| Sharpe, Sortino, Calmar | `None` (zero deviation; no bar below the target; no drawdown) | `None` |
| max drawdown, current drawdown | `0.0`, `0.0` | `0.0`, `0.0` |
| longest drawdown | 0 bars, 0 days | 0 bars, 0 days |
| hit rate | `1.0` | `1.0` |

### M5 Only zeros (`P = 4`)

`r = [0, 0, 0, 0]`. Total return `0`, CAGR `0`, volatility `0.0`, Sharpe, Sortino and Calmar `None`, drawdowns 0, hit rate `0.0`
(no bar above zero), months `0.0`.

### M6 A single bar (`P = 4`)

`r = [0.10]`. `n = 1`, `Y = 0.25`, total return `0.1`, `CAGR = 1.1^4 - 1 = 0.4641`, hit rate `1.0`, drawdowns 0 (0 bars,
0 days), best and worst month `0.1`. Volatility, Sharpe and Sortino are `None` (`n < 2`), Calmar is `None` (no drawdown).

### M7 An empty series

`n = 0`: `n_bars = 0`, `n_months = 0`, every other number `None`; the function does not raise.

### M8 A ruined portfolio (`P = 4`, `rf = 0`)

`r = [+0.10, -1.0, 0.0, 0.0]` (the form `BacktestResult.returns` has after a ruin), dates Jan 2, 3, 4, 5.

- Equity points `1, 1.1, 0, 0, 0`. `T = -1`; `CAGR = -1` (`1 + T = 0`).
- `mean = -0.9 / 4 = -0.225`; deviations `0.325, -0.775, 0.225, 0.225`; squares `0.105625 + 0.600625 + 0.050625 + 0.050625 =
  0.8075`; `/ 3 = 0.269166667`; `s = 0.518812747209`; `vol = 2 s = 1.037625494418`; `Sharpe = -0.225 / s * 2 = -0.867364964374`.
- Downside against 0: `1.0` on one bar; `D = sqrt(1 / 4) = 0.5`; `Sortino = -0.225 / 0.5 * 2 = -0.9`.
- Drawdown: `M = 1, 1.1, 1.1, 1.1, 1.1`; `DD = 0, 0, -1, -1, -1`. Max and current drawdown `-1`. One stretch, peak point 1 (Jan 2),
  no recovery: **3 bars** (point 4 minus point 1) and **3 days** (Jan 2 to Jan 5). `Calmar = -1 / 1 = -1`. Hit rate `1 / 4`.

### M9 A round Sharpe ratio (`P = 4`, `rf = 0`)

`r = [0.04, 0.06, 0.04, 0.06, 0.05]`, `n = 5`, five consecutive business days.

- `mean = 0.25 / 5 = 0.05`; deviations `-0.01, +0.01, -0.01, +0.01, 0`; sum of squares `4 * 0.0001 = 0.0004`; `/ 4 = 0.0001`;
  `s = 0.01`. `vol = 0.01 * 2 = 0.02`; `Sharpe = 0.05 / 0.01 * 2 = 10`.
- No bar below 0: Sortino `None`. Hit rate `1.0`; no drawdown: Calmar `None`.
- `T = 1.04 * 1.06 * 1.04 * 1.06 * 1.05 - 1 = 1.1024^2 * 1.05 - 1 = 1.21528576 * 1.05 - 1 = 0.27605005` (exactly 0.276050048).
  `Y = 5 / 4 = 1.25`; `CAGR = 1.276050048^0.8 - 1 = 0.215329854800`.

### M10 Calendar months (`P = 4`)

Dates `2024-01-30, 2024-01-31, 2024-02-01, 2024-02-28, 2024-03-01` (not consecutive), `r = [+0.10, -0.10, +0.20, +0.10,
-0.50]`.

- January: `1.1 * 0.9 - 1 = -0.01`. February: `1.2 * 1.1 - 1 = 0.32`. March (one bar): `-0.50`.
- `best_month = 0.32` (`2024-02`), `worst_month = -0.5` (`2024-03`), `n_months = 3`. The first month (starts on the 30th) and the
  last (one bar) are partial and are included.
- Total return: `1.1 * 0.9 * 1.2 * 1.1 * 0.5 - 1 = 0.6534 - 1 = -0.3466`.

### M11 Turnover and exposure (pure series)

- `P = 4`, `n = 4` (`Y = 1`), `turnover = [1.0, 0, 0.5, 0]`: sum `1.5`; **two-sided `1.5`**, **one-sided `0.75`**.
  Weight sums `[0, 1, 0.5, 1]`: `exposure_mean = 2.5 / 4 = 0.625`; invested share `3 / 4 = 0.75`.
- Float dust: weight sums `[1e-14, 1, 0.5, 1]`: invested share still `0.75`; `exposure_mean = 2.5 / 4 = 0.625` to `1e-9`.
- `P = 4`, `n = 2` (`Y = 0.5`), `turnover = [1.0, 1.0]`: sum 2; **two-sided `2 / 0.5 = 4`**, **one-sided `2`**.

### M12 A whole run through `run_backtest`: H23 (`P = 5`, `rf = 0`)

The run of H23 in [engine.md](engine.md) (buy and hold on the world of H1 with 25 percent costs): equity `1000, 880, 968,
1064.8, 1171.28` on Jan 2, 3, 4, 5, 8; `returns = [0, -0.12, 0.1, 0.1, 0.1]`; turnover `[0, 0.8, 0, 0, 0]`; weights (sum)
`[0, 1, 1, 1, 1]`. `n = 5`, `Y = 1`.

- `total_return = net_return = 0.17128`; `CAGR = 0.17128`.
- `mean = 0.18 / 5 = 0.036`; deviations `-0.036, -0.156, 0.064, 0.064, 0.064`; squares `0.001296 + 0.024336 + 3 * 0.004096 =
  0.03792`; `/ 4 = 0.00948`; `s = 0.097365291557`; `vol = s * sqrt(5) = 0.217715410571`; `Sharpe = 0.036 / s * sqrt(5) = 0.826767381914`.
- Downside against 0: `-0.12` only; `D = sqrt(0.0144 / 5) = 0.053665631460`; `Sortino = 0.036 / D * sqrt(5) = 0.036 * 5 / 0.12 = 1.5`.
- Drawdown (points `1000, 1000, 880, 968, 1064.8, 1171.28`, the first two equal, the running maximum 1000 until Jan 5): `DD` is
  `0, 0, -0.12, -0.032, 0` (1064.8 is a new peak) and `0`, so max drawdown `-0.12`, current `0`. One stretch: peak point 1 (Jan 2), recovery
  point 4 (Jan 5): **3 bars, 3 days**. `Calmar = 0.17128 / 0.12 = 1.427333333333`.
- Hit rate `3 / 5 = 0.6`. Exposure mean `4 / 5 = 0.8`, invested share `0.8`. Turnover: sum `0.8`, two-sided `0.8`, one-sided `0.4`.
- Months: all in January, `0.17128` (`2024-01`), `n_months = 1`.

### M13 H23c through `run_backtest` (`P = 5`, `rf = 0`)

The ruined portfolio of H23c: equity `1000, 1000, 500, 0, 0`; `returns = [0, 0, -0.5, -1, 0]`; weight sums `[0, 0, 1, 0, 0]`;
turnover `[0, 0, 0.5, 1, 0]` (buy 500 of a 1000 portfolio, then sell 500 of a 500 portfolio). Dates Jan 2, 3, 4, 5, 8.

- `total_return = -1`; `CAGR = -1`. `mean = -1.5 / 5 = -0.3`; deviations `0.3, 0.3, -0.2, -0.7, 0.3`; squares `0.09 + 0.09 + 0.04 + 0.49
  + 0.09 = 0.8`; `/ 4 = 0.2`; `s = 0.447213595500`; `vol = s * sqrt(5) = 1.0`; `Sharpe = -0.3 / s * sqrt(5) = -1.5`.
- Downside against 0: `0.25 + 1 = 1.25`, `/ 5 = 0.25`, `D = 0.5`; `Sortino = -0.3 / 0.5 * sqrt(5) = -1.341640786500`.
- Drawdown: `DD = 0, 0, 0, -0.5, -1, -1`. Max and current drawdown `-1`; one stretch, peak point 2 (Jan 3), no recovery: **3 bars**
  (point 5 minus point 2), **5 days** (Jan 3 to Jan 8). `Calmar = -1 / 1 = -1`. Hit rate `0`.
- Exposure mean `1 / 5 = 0.2`, invested share `0.2`. Turnover sum `1.5`: two-sided `1.5`, one-sided `0.75`. Months: January, `-1`.
- No value is NaN or inf.

### M14 Invalid input

A series with NaN or infinity, a return below -1, an unsorted or duplicated index, `periods_per_year` below 1 and a
`risk_free_rate` of -1 or less raise `ValueError`.

## Property tests

On seeded random return series: the maximum drawdown is between -1 and 0; the drawdown path is 0 at every new high; the sign
of the Sharpe ratio is the sign of the mean excess return; a constant series (any value, including 0.01, 0.1 and 1/3) has
volatility 0.0, no Sharpe and, if positive, no drawdown; the best month is at least the worst month; the one-sided turnover is
half the two-sided one; no output is NaN or inf, also for degenerate series; and the metrics of a run do not change when its
initial capital is doubled (tolerance 1e-9).

## Benchmark and relative metrics

A run is judged next to a benchmark (F-13). The code is in `src/backtest_agent/metrics/` (`benchmark.py`, `relative.py`,
`evaluation.py`), the decisions are in [ADR 0013](adr/0013-benchmark-comparison.md). `evaluate(spec, provider)` is the
single entry point: it runs the strategy, runs the benchmark, and reports the metrics of both and the relative metrics.
`run_backtest` itself loads no benchmark.

### The benchmark

The benchmark is a buy-and-hold run through the **same `run_backtest`**, loaded through the **same provider**. Its spec is
derived from the strategy spec by `benchmark_spec(spec)`:

| Field | Value |
|---|---|
| `universe` | `[spec.benchmark]` |
| `signal` | `buy_and_hold`, params `{}` |
| `sizing` | `equal_weight` (a `fixed_fraction` strategy still gets a fully invested benchmark) |
| `rebalance` | `on_signal` |
| `benchmark` | unchanged |
| `name` | `"<name> (benchmark <SYM>)"`; the strategy name is cut so that the whole name stays within the 100 characters the spec allows |
| `period`, `initial_capital`, `execution` (delay, price, same-bar flag), `costs`, `data`, `description`, `schema_version` | copied unchanged |

The benchmark therefore pays the strategy's costs and executes with the strategy's delay and price rule, so the first bar
is measured identically. If the benchmark symbol is also in the universe there is **no special case**: the benchmark is
its own `run_backtest` call with its own provider call, its own data hash and its own validation. A benchmark whose data
cannot be loaded raises the provider's error unchanged; no partial result is returned.

### Alignment on equity levels

Strategy and benchmark may not have the same bar dates (different exchange holidays, a benchmark that starts late or ends
early). A per-bar return across a date that exists in only one series covers a different holding period, so the comparison
does **not** align per-bar returns. It aligns the **equity levels** on the common dates and computes the returns from them.

Inputs: the equity series of both runs (one point per bar) and their initial equities. The rule:

1. `common` is the intersection of the bar dates of both results, sorted; `n_common = len(common)`.
2. If `n_common > 0` and `common[0]` is the first bar of **both** runs, the base of the first return is the **initial equity**
   of each run (nothing is lost): the returns are `bar_returns(equity[common], initial_equity)`, so the first return is
   `equity[common[0]] / initial_equity - 1`, and `n_compared = n_common`. `base = "initial_equity"`.
3. Otherwise the base is the **equity at `common[0]`** of each run, and that date has no return: the returns are
   `bar_returns(equity[common[1:]], equity[common[0]])` and `n_compared = max(n_common - 1, 0)`. `base = "first_common_date"`,
   `base_date = common[0]`. (`bar_returns` is the engine's: a base of 0, a ruined portfolio, gives 0.0, never NaN.) With no
   common date (`n_common = 0`) there is no base point: `base` is `"first_common_date"` and `base_date` is `None`.
4. `n_dropped_strategy = n_strategy_bars - n_common`, `n_dropped_benchmark = n_benchmark_bars - n_common`;
   `dates_dropped` is True if either is above 0; `insufficient_overlap` is True if `n_compared < 2`.
5. Nothing is dropped silently and the function never raises because the calendars differ. No common date gives
   `n_compared = 0`.

A return across a gap in the common grid (a date missing in one series) is the ratio of the two levels on the common dates
around it, so it covers the same holding period in both series.

**What is lost, stated plainly.** When the first common date is not the first bar of both runs (rule 3), the first-bar
return of each run, measured against its initial equity, is **not part of the compared window**; the window starts at the
equity of `common[0]`. This applies to the strategy as well as to the benchmark. Hence the excess return (computed over the
window) can differ from the difference of the two `net_return`s of the results, which cover each run's own full path. They
are equal when `base = "initial_equity"` and nothing is dropped at the end. `RelativeMetrics` reports the two window totals
(`strategy_return_compared`, `benchmark_return_compared`) so the window is visible, and the `Alignment` fields below.

`Alignment` (scalars only, JSON-ready; the frames are not part of it):

| Field | Meaning |
|---|---|
| `n_strategy_bars`, `n_benchmark_bars` | bars of each result |
| `n_common` | size of the intersection |
| `n_compared` | return observations after the alignment (rule 2 or 3) |
| `n_dropped_strategy`, `n_dropped_benchmark` | bars of each result that are not on the common grid |
| `dates_dropped` | True if either dropped count is above 0 |
| `insufficient_overlap` | True if `n_compared < 2`; the relative metrics are then `None` |
| `base` | `"initial_equity"` or `"first_common_date"` |
| `base_date` | ISO date of the base point when `base = "first_common_date"`, else `None` |
| `first_compared_date`, `last_compared_date` | ISO dates of the first and the last return; set whenever `n_compared >= 1` (also when the metrics are `None` for lack of observations), else `None` |

### Relative metrics

With the aligned returns `r_s` (strategy) and `r_b` (benchmark) on the `n_compared` dates, the per-bar **active return** is
`a_i = r_s,i - r_b,i`. `P` and the zero tolerance `eps = 1e-12` are the assumptions of part 1 (`periods_per_year`; the
risk-free rate is not used).

- **Excess return.** `prod(1 + r_s) - prod(1 + r_b)`, the compounded totals over the compared window.
- **Tracking error.** `std(a, ddof = 1) * sqrt(P)`. If the per-bar standard deviation is below `eps` the tracking error is
  exactly 0.0.
- **Information ratio.** `mean(a) * P / TE`, which equals `mean(a) / std(a) * sqrt(P)` (annualized mean active return over
  the tracking error). `None` if the tracking error is 0.0.
- `strategy_return_compared`, `benchmark_return_compared`: the two totals above.

All of them are `None` if `n_compared < 2` (with `insufficient_overlap = True`), and for `n_compared >= 2` only the
information ratio can still be `None`. The standard deviation is computed without the input check of `volatility`, because
an active return can be below -1. No output is NaN or inf.

The `PerformanceMetrics` of each run are those of the run's own full result. They agree with the relative metrics when
nothing is dropped and `base = "initial_equity"`.

### `evaluate` and `evaluate_result`

`evaluate(spec, provider, *, allow_short_warmup=True, apply_costs=True, assumptions=DEFAULT_ASSUMPTIONS)` runs the
strategy, then `run_backtest(benchmark_spec(spec), provider, ...)` with the same `allow_short_warmup` and `apply_costs`,
computes `PerformanceMetrics` for both and the relative metrics. `evaluate_result(result, benchmark_result, assumptions)`
is the pure part: it raises `ValueError` unless `benchmark_result.spec == benchmark_spec(result.spec)` and both have the
same `costs_applied`, so a result is never compared with a different yardstick.

`Evaluation.to_dict()` is JSON serializable (`float`, `int`, `str`, `bool`, `None`, `dict` and lists of strings; no frames):

```
{"strategy":  {"name", "data_hash", "costs_applied", "risk_flags": [codes], "metrics": {...}},
 "benchmark": {"symbol", "name", "data_hash", "costs_applied", "risk_flags": [codes], "metrics": {...}},
 "relative":  {"excess_return", "tracking_error", "information_ratio",
               "strategy_return_compared", "benchmark_return_compared", "alignment": {...}},
 "assumptions": {...}}
```

`risk_flags` are the flag codes (strings); the messages stay on the results.

### Benchmark fixtures R1 to R3

The expected values are literals taken from this document; the tests never compute one with project code or a helper that
mirrors it. Tolerance `1e-9` (relative and absolute). Dates are consecutive business days from 2024-01-02 unless stated.

#### R1 Pure relative numbers (`P = 4`)

Dates Jan 2, 3, 4, 5, 8. Strategy returns `[0.14, 0.16, 0.14, 0.16, 0.15]`, benchmark `0.10` on every bar.

- Active `[0.04, 0.06, 0.04, 0.06, 0.05]`; mean `0.25 / 5 = 0.05`; deviations `-0.01, +0.01, -0.01, +0.01, 0`; sum of
  squares `4 * 0.0001 = 0.0004`; `/ 4 = 0.0001`; std `0.01`.
- `TE = 0.01 * sqrt(4) = 0.02`. `IR = 0.05 * 4 / 0.02 = 10`.
- Strategy total `1.14 * 1.16 * 1.14 * 1.16 * 1.15 - 1 = 1.3224^2 * 1.15 - 1 = 1.74874176 * 1.15 - 1 = 1.011053024`.
  Benchmark total `1.1^5 - 1 = 0.61051`. Excess return `0.400543024`.

#### R2a Calendar mismatch (`P = 4`, both initial equities 1000)

Strategy bars Jan 2, 3, 4, 5 with equity `1000, 1100, 1210, 1089`. Benchmark bars Jan 3, 4, 5, 8 with equity
`1000, 1050, 1102.5, 1157.625`.

- Common dates: Jan 3, 4, 5, so `n_common = 3`. Jan 3 is the strategy's second bar, so the base is the equity at Jan 3
  (1100 and 1000) and Jan 3 has no return: `n_compared = 3 - 1 = 2`, `base = first_common_date`, `base_date = 2024-01-03`.
- Counts: dropped from the strategy `4 - 3 = 1` (Jan 2), dropped from the benchmark `4 - 3 = 1` (Jan 8); `dates_dropped =
  True`, `insufficient_overlap = False`. First and last compared date Jan 4 and Jan 5.
- Strategy returns: Jan 4 `1210 / 1100 - 1 = 0.1`, Jan 5 `1089 / 1210 - 1 = -0.1`. Benchmark: Jan 4 `1050 / 1000 - 1 =
  0.05`, Jan 5 `1102.5 / 1050 - 1 = 0.05`.
- Active `[0.05, -0.15]`; mean `-0.05`; deviations `+0.10, -0.10`; sum of squares `0.02`; `/ 1 = 0.02`; std `sqrt(0.02) =
  0.141421356237`.
- `TE = 0.141421356237 * 2 = 0.282842712475` (`sqrt(0.08)`). `IR = -0.05 * 4 / 0.282842712475 = -0.707106781187`
  (`-1 / sqrt(2)`).
- Window totals: strategy `1.1 * 0.9 - 1 = -0.01` (`1089 / 1100 - 1`), benchmark `1.05^2 - 1 = 0.1025`. Excess return
  `-0.01 - 0.1025 = -0.1125`.
- The own net returns are `1089 / 1000 - 1 = 0.089` and `1157.625 / 1000 - 1 = 0.157625`; their difference `-0.068625` is
  not the excess return, because the own paths cover different dates (the strategy's own first-bar return and the
  benchmark's are not part of the window).

#### R2b Fewer than two observations (`P = 4`)

Strategy Jan 2, 3, 4 with `1000, 1100, 1210`; benchmark Jan 3, 4, 5 with `1000, 1050, 1102.5`. Common Jan 3, 4: `n_common =
2`, base Jan 3, `n_compared = 1`, dropped 1 and 1, `dates_dropped = True`, `insufficient_overlap = True`. Excess return,
tracking error and information ratio are all `None`.

**R2b'** (no common date): strategy Jan 2, 3 with `1000, 1100`; benchmark Jan 4, 5 with `1000, 1050`. `n_common = 0`,
`n_compared = 0`, dropped 2 and 2, both flags True, `base_date = None`, everything `None`, no exception.

#### R2c Identical calendars (`P = 4`)

Jan 2, 3, 4, 5, both initial equities 1000. Benchmark equity `1100, 1210, 1331, 1464.1` (0.10 per bar); strategy `1200,
1392, 1670.4, 1937.664` (returns `0.20, 0.16, 0.20, 0.16`).

- The first common date (Jan 2) is the first bar of both runs: base is the initial equity, `n_compared = 4`, nothing
  dropped, `dates_dropped = False`, `insufficient_overlap = False`, `base_date = None`.
- Active `[0.10, 0.06, 0.10, 0.06]`; mean `0.08`; deviations `+0.02, -0.02, +0.02, -0.02`; sum of squares `0.0016`; `/ 3 =
  0.000533333`; std `0.04 / sqrt(3) = 0.023094010768`.
- `TE = 0.023094010768 * 2 = 0.046188021535`. `IR = 0.08 * 4 / 0.046188021535 = 4 * sqrt(3) = 6.928203230276`.
- Totals: strategy `1.2 * 1.16 * 1.2 * 1.16 - 1 = 1.392^2 - 1 = 0.937664`, benchmark `1.1^4 - 1 = 0.4641`. Excess
  `0.473564`.

#### R2d The first common date is the first bar of only one run (`P = 4`)

Benchmark bars Jan 2, 3, 4, 5 with `1000, 1100, 1210, 1331`; strategy bars Jan 3, 4, 5 with `1000, 1200, 1440`.

- Common Jan 3, 4, 5. Jan 3 is the strategy's first bar but the benchmark's second, so rule 3 applies: base is the equity at
  Jan 3 (1000 and 1100), `n_compared = 2`, dropped from the strategy 0, from the benchmark 1, `dates_dropped = True`.
- Strategy returns `1200 / 1000 - 1 = 0.2`, `1440 / 1200 - 1 = 0.2`. Benchmark `1210 / 1100 - 1 = 0.1`, `1331 / 1210 - 1 =
  0.1`. Active `[0.1, 0.1]`: std 0, `TE = 0.0`, `IR = None`.
- Totals: strategy `1.2^2 - 1 = 0.44`, benchmark `1.1^2 - 1 = 0.21`; excess `0.23`. (With the initial equity as the base the
  benchmark total would be `1331 / 1000 - 1 = 0.331`, a window the strategy never had.)

#### R3 Through `evaluate` with a literal provider (`P = 5`)

Setup of H23 in [engine.md](engine.md): capital 1000, period 2024-01-02 to 2024-01-08, signal `buy_and_hold` (warm-up 0),
`equal_weight`, `on_signal`, delay 1, open fills, costs commission 1000, spread 1000, slippage 500 bps (25 percent). The
fetch start is `2024-01-02` minus `2 * (0 + 1) + 14 = 16` days = 2023-12-17. A: open `100, 100, 110, 121, 133.1`; close
`100, 110, 121, 133.1, 146.41`. The signal of Jan 2 is executed at the Jan 3 open (delay 1): 8 shares of A bought at 100
after the 25 percent funding rule of H23 (as H23, equity `1000, 880, 968, 1064.8, 1171.28`, returns `[0, -0.12, 0.1, 0.1, 0.1]`, net
return `0.17128`).

**R3a Benchmark equals the strategy's symbol.** Strategy on A with `benchmark: A`. The benchmark spec is the same run, so
both equities and returns are those of H23 and both `PerformanceMetrics` equal the M12 literals (total return `0.17128`,
Sharpe `0.826767381914`, Sortino `1.5`, max drawdown `-0.12`, ...). Active returns are all 0: excess return `0.0`, tracking
error `0.0`, information ratio `None`; nothing dropped, `base = initial_equity`, `n_compared = 5`. The provider is called
twice with `(("A",), 2023-12-17, 2024-01-08)`.

**R3b Strategy on A, benchmark B, with costs.** Prices of B (each open equals the previous close, moves of +-10 percent):
open `50, 50, 55, 49.5, 54.45`; close `50, 55, 49.5, 54.45, 49.005`. The strategy is buy and hold on A as in R3a.

- Benchmark net run: Jan 3 open 50, V = 1000, q = 1000 / 50 = 20 shares (notional 1000), the outlay 1000 + 0.25 * 1000 = 1250
  exceeds the cash 1000, so `f = 1000 / 1250 = 0.8`: 16 shares, notional 800, fee 200, cash 0. Equity: Jan 2 `1000`, Jan 3
  `16 * 55 = 880`, Jan 4 `16 * 49.5 = 792`, Jan 5 `16 * 54.45 = 871.2`, Jan 8 `16 * 49.005 = 784.08`. Returns `[0,
  -0.12, -0.1, 0.1, -0.1]`. Net return `784.08 / 1000 - 1 = -0.21592`; total costs 200; hit rate `1 / 5`; maximum drawdown
  (peak 1000, trough 784.08) `-0.21592`.
- The benchmark without costs (the wrong yardstick): 20 shares, equity `1000, 1100, 990, 1089, 980.1`, return `-0.0199`.
- Active `[0, 0, 0.2, 0, 0.2]` (strategy `[0, -0.12, 0.1, 0.1, 0.1]` minus benchmark `[0, -0.12, -0.1, 0.1, -0.1]`); mean `0.4 / 5 =
  0.08`; deviations `-0.08, -0.08, +0.12, -0.08, +0.12`; sum of squares `3 * 0.0064 + 2 * 0.0144 = 0.048`; `/ 4 = 0.012`;
  std `0.109544511501`.
- `TE = 0.109544511501 * sqrt(5) = sqrt(0.06) = 0.244948974278`. `IR = 0.08 * 5 / 0.244948974278 = 1.632993161855` (`2 *
  sqrt(6) / 3`).
- Excess return `0.17128 - (-0.21592) = 0.3872`. With a cost-free benchmark it would be `0.17128 + 0.0199 = 0.19118`: the
  difference proves that the benchmark carries the strategy's costs.
- The provider is called twice: `(("A",), 2023-12-17, 2024-01-08)` for the universe and `(("B",), 2023-12-17, 2024-01-08)`
  for the benchmark.

**R3c `apply_costs=False` on the world of R3b.** Both runs are cost-free and carry the flag `costs_not_applied`,
`costs_applied` is False. Strategy equity `1000, 1100, 1210, 1331, 1464.1` (return `0.4641`), benchmark `-0.0199`; excess
return `0.4641 + 0.0199 = 0.4840`. Active is again `[0, 0, 0.2, 0, 0.2]`, so tracking error and information ratio equal R3b.

### Tests (beyond the fixtures)

`benchmark_spec` copies period, capital, execution (also delay 0 with price close and the same-bar flag) and costs, sets the
universe to `[benchmark]`, the signal to `buy_and_hold` with no params, the sizing to `equal_weight` (also for a
`fixed_fraction` strategy), keeps the benchmark field, builds the name and does not change the strategy spec; a benchmark
that is also in the universe is its own run. `evaluate_result` raises `ValueError` for a benchmark result of another spec and
for another `costs_applied`. Swapping strategy and benchmark in `compare_equity` flips the sign of excess return and
information ratio and keeps the tracking error. A strategy against itself has tracking error 0.0 and no information ratio.
No output is NaN or inf, also for seeded random series and degenerate inputs (a single bar, constants, a ruin before the
base, no common date, empty series). `to_dict` is JSON serializable (`json.dumps`) and contains both data hashes, both
names, the risk flag codes and the alignment. `apply_costs=False` reaches both runs. A benchmark that starts late or ends
early aligns without an error, and a benchmark with no data raises the provider's error unchanged.

## Trade statistics

Counts and costs of the fills of a run (F-14, Phase 7). The code is in `src/backtest_agent/metrics/trades.py`; the report
(see [report.md](report.md)) prints them and recomputes nothing. They are a function of `BacktestResult.trades` only and are
not part of `Evaluation`.

**Definition.** A **trade** is one fill: one row of `BacktestResult.trades` (one symbol on one bar; a rebalance of three
symbols on one bar is three trades). A **buy** has `shares > 0`, a **sell** `shares < 0`.

- `n_trades` = number of rows; `n_buys`, `n_sells` = rows with positive, negative `shares`; `n_trades = n_buys + n_sells`.
- `per_symbol[s]` = `trades`, `buys`, `sells` of the rows of symbol `s`. Only symbols that were traded are listed, sorted by
  symbol; a symbol of the universe that was never traded is absent (the report shows it as 0).
- `total_cost` = sum of the `cost` column (the fees of the fills). It equals `BacktestResult.total_costs`.
- `average_cost_per_trade` = `total_cost / n_trades`; **None with 0 trades**, 0.0 with trades that cost nothing.
- Invalid input raises `ValueError`: a missing column (`symbol`, `shares`, `cost`), `shares` of 0, NaN or infinity, `cost`
  negative, NaN or infinity.

Exposure and annualized turnover are not repeated here: they are `exposure_mean`, `exposure_invested_share` and
`turnover_two_sided_annual`, `turnover_one_sided_annual` of `PerformanceMetrics` (M11). `deferred_orders` and
`unfilled_orders` are existing fields of `BacktestResult` (engine.md); they are not trade statistics.

All expected values are literals written out here; tolerance 1e-9 (relative and absolute) for the floats, the counts are exact.
Tests: `tests/test_metrics_trades.py`.

### T1 No trades

An empty table (also the `trades` of a run that never trades, such as the Jan 5 first-bar example of "Initial decision" in [engine.md](engine.md)): `n_trades = 0`, `n_buys = 0`, `n_sells = 0`,
`per_symbol = {}`, `total_cost = 0.0`, **`average_cost_per_trade = None`**.

### T2 One trade (the fill of H23)

H23 in [engine.md](engine.md): Jan 3 A +8 @ 100, notional +800, cost 200. `n_trades = 1`, `n_buys = 1`, `n_sells = 0`,
`per_symbol = {A: (1, 1, 0)}`, `total_cost = 200`, `average_cost_per_trade = 200 / 1 = 200`.

### T3 Several symbols (the six fills of H22)

H22 in [engine.md](engine.md), listed as (date, symbol, shares, price, notional, cost): (Jan 3, A, +4, 100, +400, 100),
(Jan 3, B, +8, 50, +400, 100), (Jan 4, A, -0.4, 125, -50, 12.5), (Jan 4, B, +0.6, 50, +30, 7.5), (Jan 5, A, -11/30, 150, -55,
13.75), (Jan 5, B, +0.66, 50, +33, 8.25).

- `n_trades = 6`; buys: A +4, B +8, B +0.6, B +0.66 = `n_buys = 4`; sells: A -0.4, A -11/30 = `n_sells = 2`.
- `per_symbol`: A `(3, 1, 2)`, B `(3, 3, 0)`.
- `total_cost = 100 + 100 + 12.5 + 7.5 + 13.75 + 8.25 = 242`; `average_cost_per_trade = 242 / 6 = 40.333333333333`.
- The order of the rows does not matter: the same rows in reverse order give the same result, with the symbols sorted A, B.

### T4 Trades that cost nothing

Two fills: (Jan 3, A, +10, 100, +1000, 0) and (Jan 5, A, -10, 110, -1100, 0). `n_trades = 2`, `n_buys = 1`, `n_sells = 1`,
`per_symbol = {A: (2, 1, 1)}`, `total_cost = 0.0`, **`average_cost_per_trade = 0.0`** (not None: there are trades).

### T5 Through `run_backtest`: H23 and H23c

The trades table of the run H23 (buy and hold with 25 percent costs) is the single fill of T2, so the statistics are those of
T2 and `total_cost` equals `total_costs = 200`. H23c (a flat fee of 500 per trade, ruined portfolio): buy 5 shares and sell 5
shares of A, so `n_trades = 2`, `n_buys = 1`, `n_sells = 1`, `per_symbol = {A: (2, 1, 1)}`, `total_cost = 500 + 500 = 1000`
(`total_costs` of H23c), `average_cost_per_trade = 500`.

### T6 Invalid input

A table without the column `shares`, a fill with `shares` 0, NaN or infinity, and a fill with `cost` -1, NaN or infinity raise
`ValueError`.
