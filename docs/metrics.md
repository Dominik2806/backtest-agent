# Metrics

Performance and risk metrics on the **net** return series of a `BacktestResult` (F-12). The code is in
`src/backtest_agent/metrics/performance.py`, the decisions are in [ADR 0012](adr/0012-metric-conventions.md). The
benchmark comparison (F-13) follows in the second part of Phase 6 and extends this document.

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
float dust of a fill from counting as a position). `None` for `n = 0`.

**Turnover.** The engine's turnover is **two-sided**: the sum of the absolute trade notionals of a bar over the portfolio
value, so buying the whole portfolio from cash is 1.0 and a complete switch from one asset to another is 2.0. The
annualized two-sided turnover is `sum(turnover) / Y`; the **one-sided** figure (the value bought, or equivalently
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
