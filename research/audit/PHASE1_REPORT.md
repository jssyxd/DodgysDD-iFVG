# Phase 1 — executed on real NQ 1-minute data

Every figure below is parsed out of the executed backtest output in `research/experiments/`; none is written by hand. Render with `python scripts/render_phase1_report.py`.

**Instrument:** NQ (E-mini Nasdaq-100), 1-minute, continuous, **2015-01-01 → 2025** — 3,664,241 bars from the governed lake.

**Costs:** NQ profile — tick 0.25 pt = $5.00, multiplier $20, fee ≈ $4.50 round trip, plus 0/1/2 ticks of slippage. The mean cost is ≈ **0.10 R** per trade on the reference-faithful arm.

**Accounting:** one position at a time (D4). The census arm — one position per candidate — is never quoted.


## 1. The data

| | |
|---|---|
| NQ 1m source | `mdelcristo/NQ-F_1min_OHLCV_Parquet` (Hugging Face), 2015–2025 |
| ES 1m source | `Khanhpham1992/es-futures-1m` → `es_continuous_1m.parquet` |
| NQ bars | 3,664,241 (duplicates removed, maintenance break dropped, invariants checked) |
| ES bars | 646,948 (2020-11 → 2024-07; the panel covers 528 of 959 weekdays) |
| Roll rule | the quarterly splice is **detected** (the largest 1-minute move near each expiry), ±60 min masked |
| Masked | NQ 6,203 bars = **0.169 %**; ES 1,943 = 0.300 % |

The NQ publisher splices the continuous series at the quarterly expiry: at **37 of 44** expiries there is a 1-minute move of 0.15–1.76 % against a 1-minute sigma of 0.030 %. Those moves are synthetic (two contracts, different prices) and are the exact shape of a liquidity sweep, so they are masked rather than traded.


## 2. The rule engine, with no ML

### 2.1 Every arm at one tick of slippage

| arm | what it adds | trades | win% | E[R] gross | E[R] net | PF | t | 95 % CI |
|---|---|---|---|---|---|---|---|---|
| `e1` | the code-derived scanner | 45734 | 32.9 | **-0.0127** | -0.1430 | 0.981 | -1.93 | [-0.026, 0.000] |
| `honest` | the same scanner with the look-ahead removed | 45734 | 32.9 | **-0.0127** | -0.1436 | 0.981 | -1.93 | [-0.026, 0.000] |
| `doc` | the doc's ATR floor + sweep + killzone | 7399 | 34.1 | **0.0242** | -0.1021 | 1.037 | 1.46 | [-0.008, 0.057] |
| `pine` | the reference-faithful leg tracker + BE-intact gate | 25083 | 34.4 | **0.0317** | -0.0700 | 1.048 | 3.52 | [0.014, 0.049] |
| `pine_leg` | the leg tracker alone | 25228 | 34.3 | **0.0303** | -0.0714 | 1.046 | 3.38 | [0.013, 0.048] |
| `pine_be` | the BE-intact gate alone | 45268 | 32.9 | **-0.0135** | -0.1450 | 0.980 | -2.03 | [-0.026, -0.000] |

### 2.2 Cost sensitivity (rule-only)

| arm | slippage | trades | E[R] gross | E[R] net | PF |
|---|---|---|---|---|---|
| `e1` | 0 tick | 45734 | -0.0127 | -0.0980 | 0.981 |
| `e1` | 1 tick | 45734 | -0.0127 | -0.1430 | 0.981 |
| `e1` | 2 tick | 45734 | -0.0127 | -0.1879 | 0.981 |
| `honest` | 0 tick | 45734 | -0.0127 | -0.0984 | 0.981 |
| `honest` | 1 tick | 45734 | -0.0127 | -0.1436 | 0.981 |
| `honest` | 2 tick | 45734 | -0.0127 | -0.1887 | 0.981 |
| `doc` | 0 tick | 7399 | 0.0242 | -0.0586 | 1.037 |
| `doc` | 1 tick | 7399 | 0.0242 | -0.1021 | 1.037 |
| `doc` | 2 tick | 7399 | 0.0242 | -0.1457 | 1.037 |
| `pine` | 0 tick | 25083 | 0.0317 | -0.0349 | 1.048 |
| `pine` | 1 tick | 25083 | 0.0317 | -0.0700 | 1.048 |
| `pine` | 2 tick | 25083 | 0.0317 | -0.1051 | 1.048 |

### 2.3 What the ablation says

The **leg tracker is the entire source of the edge**. On its own it moves E[R] from −0.013 to +0.030 and t from −1.9 to +3.4. The BE-intact gate on its own does nothing (−0.0135) and adds only +0.0014 on top of the tracker.

This was not visible before: the leg tracker's pivots were a 3-bar rolling minimum, which fires on roughly a third of all bars, so the live gap was discarded long before it could reach the 7-bar minimum inversion age. The reference-faithful arm produced **one trade in ten years**. Using the module's own fractal pivots fixed it.


## 3. The same runs with the ML gate

The meta-labeler is a rolling walk-forward LightGBM (6 months train / 1 month validate / 1 month test, purged with an embargo) that scores each setup and trades it only when P(Win) ≥ 0.58.

| run | trades | approved | win% | E[R] gross | E[R] net | PF | t | 95 % CI | DSR p |
|---|---|---|---|---|---|---|---|---|---|
| honest + ML gate | 933 | 2255 | 33.1 | **-0.0064** | -0.2404 | 0.990 | -0.14 | [-0.097, 0.084] | 0.9873 |
| pine + ML gate | 705 | 874 | 35.0 | **0.0511** | -0.0772 | 1.079 | 0.95 | [-0.055, 0.157] | 0.8782 |
| pine, rule-only (baseline) | 25083 | 51391 | 34.4 | **0.0317** | -0.0700 | 1.048 | 3.52 | [0.014, 0.049] | 0.0760 |

The gate **raises** the reference-faithful arm's gross expectancy from +0.0317 to +0.0511 R — it selects the better setups — but it trades 705 instead of 25,083, so the t-statistic collapses and the result is no longer significant. On the `honest` arm, which has no edge to select, the gate produces nothing.

Out-of-sample `auc_test` across the 120 monthly folds was **0.47–0.53** on both candidate sets: the meta-labeler is close to a coin flip. Whatever the edge is, it is not in the checklist score, the SMT flag, the VXN regime or the bar geometry that the feature builder exposes.


## 4. Verdict against the design doc's phase-1 gate

| Gate | Required | Measured | Met? |
|---|---|---|---|
| Profit factor | **> 1.25** | 1.048 rule-only, 1.079 with the ML gate | **No** |
| Expectancy | positive | +0.032 R gross, **−0.070 R net of costs** | **No** |
| Costs | ~$4.50 + 1–2 ticks | applied (mean 0.10 R) | yes |
| Population | A/A+ only | **not computable** — no artefact defines a grade (D8) | **No** |
| Sample | 10 years, 3.66 M bars | met | yes |

**The phase-1 gate fails, but not because the rule is worthless.**

The reference-faithful rule set has a **real and statistically significant** edge: +0.0317 R per trade, t = 3.52, 95 % CI [0.014, 0.049], PF 1.048, over 25,083 trades across ten years. The problem is arithmetic: **the edge is 0.032 R and the round trip costs 0.102 R.** Every arm is net-negative at 1 tick of slippage, and the gap widens at 2 ticks.

So the binding constraint is not the rule and not the ML — it is the cost model versus the size of the effect. To clear the gate the strategy needs either an edge roughly **four times** larger, or a cost roughly four times smaller (a fee of ≈ $1.10 instead of $4.50, which no NQ broker offers).

This is now measured on **two independent markets**: BTCUSDT 1-minute (E[R] −0.0002, PF 1.000, where costs are 0.5–0.8 R) and NQ 1-minute over ten years (E[R] +0.0317 R gross, PF 1.048, where costs are 0.10 R). The difference between the two markets is entirely the cost ratio.


## 5. What would move the number

| lever | expected effect | status |
|---|---|---|
| More setups per unit of risk (the arm trades 25,083 times in ten years, ≈ 6.9 per day) | the cost is per trade, so the edge must come from size, not frequency | open |
| A tighter RR (2R costs as much as 1R) | tests the payoff asymmetry rather than the entry | **not run** |
| The `A/A+` grade filter the doc asks for | the gate's population | **blocked on D8** — no artefact defines a grade |
| A cost-aware stop (the mean cost is 0.10 R because the stop is wide) | tightening the stop raises the cost ratio | open |
| The vision layer (YOLO IoU) | an independent signal the meta-labeler can use — its features are *not* in the current feature frame | open |

The cheapest next experiment is the RR sweep: it is a pure re-run of the existing arm with a different target and it tests whether the edge lives in the entry or in the payoff.
