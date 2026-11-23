# Phase 1 — executed on real NQ 1-minute data

Every figure below is parsed out of the executed backtest output in `research/experiments/`; none is written by hand. Render with `python scripts/render_phase1_report.py`.

**Instrument:** NQ (E-mini Nasdaq-100), 1-minute, continuous, **2015-01-01 → 2025** — 3,664,241 bars from the governed lake.

**Costs:** NQ profile — tick 0.25 pt = $5.00, multiplier $20, fee ≈ $4.50 round trip, plus 0/1/2 ticks of slippage. **The round trip is a fixed ≈ $14.50**, so its cost **in R** falls only when the stop gets wider.

**Accounting:** one position at a time (D4). The census arm — one position per candidate — is never quoted.


## 1. The data

|  |  |
| --- | --- |
| NQ 1m source | `mdelcristo/NQ-F_1min_OHLCV_Parquet` (Hugging Face), 2015–2025 |
| ES 1m source | `Khanhpham1992/es-futures-1m` → `es_continuous_1m.parquet` |
| NQ bars | 3,664,241 (duplicates removed, maintenance break dropped, invariants checked) |
| ES bars | 646,948 (2020-11 → 2024-07; the panel covers 528 of 959 weekdays) |
| Roll rule | the quarterly splice is **detected** (the largest 1-minute move near each expiry), ±60 min flagged, not deleted |
| Masked | NQ 6,203 bars = **0.169 %**; ES 1,943 = 0.300 % |

The NQ publisher splices the continuous series at the quarterly expiry: at **37 of 44** expiries there is a 1-minute move of 0.15–1.76 % against a 1-minute sigma of 0.030 %. Those moves are synthetic (two contracts, different prices) and are the exact shape of a liquidity sweep, so they are flagged rather than traded.


## 2. The rule engine, with no ML

### 2.1 Every arm at one tick of slippage

| arm | what it adds | trades | win% | E[R] gross | E[R] net | PF | t | 95 % CI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `e1` | the code-derived scanner | 45734 | 32.9 | **-0.0127** | -0.1430 | 0.981 | -1.93 | [-0.026, 0.000] |
| `honest` | the same scanner with the look-ahead removed | 45734 | 32.9 | **-0.0127** | -0.1436 | 0.981 | -1.93 | [-0.026, 0.000] |
| `doc` | the doc's ATR floor + sweep + killzone | 7399 | 34.1 | **0.0242** | -0.1021 | 1.037 | 1.46 | [-0.008, 0.057] |
| `pine` | the reference-faithful leg tracker + BE-intact gate | 25083 | 34.4 | **0.0317** | -0.0700 | 1.048 | 3.52 | [0.014, 0.049] |
| `pine_leg` | the leg tracker alone | 25228 | 34.3 | **0.0303** | -0.0714 | 1.046 | 3.38 | [0.013, 0.048] |
| `pine_be` | the BE-intact gate alone | 45268 | 32.9 | **-0.0135** | -0.1450 | 0.980 | -2.03 | [-0.026, -0.000] |

### 2.2 Cost sensitivity (rule-only)

| arm | slippage | trades | E[R] gross | E[R] net | PF |
| --- | --- | --- | --- | --- | --- |
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


## 3. Where the edge lives: the payoff sweep

The question the sweep answers: is the edge in the **entry** or in the **payoff**? The reward:risk multiple was swept from 1:1 to 1:4 on the reference-faithful arm, everything else fixed.

| RR | trades | win% | E[R] gross | E[R] net | cost (R) | PF | t | 95 % CI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1.0 | 35927 | 51.6 | **0.0313** | -0.0717 | 0.1029 | 1.065 | 5.93 | [0.021, 0.042] |
| 1.5 | 29726 | 41.0 | **0.0238** | -0.0784 | 0.1021 | 1.040 | 3.33 | [0.010, 0.038] |
| 2.0 | 25083 | 34.4 | **0.0317** | -0.0700 | 0.1017 | 1.048 | 3.52 | [0.014, 0.049] |
| 2.5 | 21472 | 29.3 | **0.0271** | -0.0732 | 0.1002 | 1.038 | 2.49 | [0.006, 0.048] |
| 3.0 | 18692 | 25.7 | **0.0272** | -0.0741 | 0.1013 | 1.037 | 2.13 | [0.002, 0.052] |
| 4.0 | 14545 | 20.7 | **0.0327** | -0.0687 | 0.1014 | 1.041 | 1.95 | [-0.000, 0.066] |

**The payoff is not where the edge is.** Gross E[R] moves inside a band of 0.008 R while the RR triples from 1 to 4 — the signal does not care how far the target is. RR 1.0 gives the best *statistics* (t = 5.93, and the only arm whose deflated Sharpe survives at 32 trials), because a target hit sooner frees the slot for another trade; but the gross expectancy is the same.

What *does* move the edge is **which setups are taken and when** — see §4. And the edge cannot be scaled up by widening the stop either: §5.


## 4. The stop geometry

| stop | RR | trades | E[R] gross | cost (R) | E[R] net | t |
| --- | --- | --- | --- | --- | --- | --- |
| ? | ? | 35927 | **0.0313** | 0.1029 | -0.0717 | 5.93 |
| ? | ? | 39530 | **0.0310** | 0.1223 | -0.0913 | 6.17 |
| ? | ? | 44517 | **0.0130** | 0.2143 | -0.2013 | 2.73 |

A **tighter** stop is strictly worse: the cost is a fixed number of dollars, so a smaller R means a bigger cost in R. The `ifvg` stop (the gap's far edge) doubles the cost in R and halves the edge.

**Widening the stop does not work either.** A `--stop-mult` of 1.5 / 2.0 / 3.0 moves the stop away from the entry and shrinks the edge to −0.026 R at 3×. The edge is not a fixed number of dollars per trade that can be scaled up by moving the stop: it lives in the specific stop geometry (the extreme of the gap→confirmation window) and dies when the stop is moved.


## 5. The entry side: the checklist filter and the session gate

### 5.1 The checklist filter

The doc's phase-1 population filter ("A/A+ only") has **no implementable definition** — no artefact defines a grade (D8). The five *named conditions* are booleans and they are computed, so the closest implementable version of the gate is to require k of them. The score counts only the conditions that could be **decided** (the SMT is undecidable where ES does not cover the window, and the vision condition never exists), and `--min-checklist-known` additionally requires full coverage so the score stays comparable.

| score ≥ | known ≥ | candidates | trades | win% | E[R] gross | E[R] net | cost (R) | PF | t | 95 % CI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0 | 48936 | 24625 | 34.4 | **0.0322** | -0.0695 | 0.1017 | 1.049 | 3.55 | [0.014, 0.050] |
| 2 | 0 | 30890 | 16689 | 34.2 | **0.0273** | -0.0565 | 0.0838 | 1.042 | 2.48 | [0.006, 0.049] |
| 3 | 0 | 11337 | 7364 | 34.8 | **0.0429** | -0.0244 | 0.0673 | 1.066 | 2.58 | [0.010, 0.076] |
| 4 | 0 | 1265 | 1142 | 32.6 | **-0.0228** | -0.0807 | 0.0580 | 0.966 | -0.55 | [-0.104, 0.059] |
| 1 | 4 | 26459 | 12407 | 34.5 | **0.0361** | -0.0193 | 0.0554 | 1.055 | 2.82 | [0.011, 0.061] |
| 2 | 4 | 21249 | 10890 | 34.1 | **0.0229** | -0.0339 | 0.0568 | 1.035 | 1.68 | [-0.004, 0.050] |
| 3 | 4 | 10185 | 6422 | 34.7 | **0.0422** | -0.0168 | 0.0590 | 1.065 | 2.37 | [0.007, 0.077] |
| 4 | 4 | 1265 | 1142 | 32.6 | **-0.0228** | -0.0807 | 0.0580 | 0.966 | -0.55 | [-0.104, 0.059] |

The filter does **two** things at once: it raises the edge per trade and it **lowers the cost ratio**, because the setups it keeps have wider stops (a fixed $14.50 cost is a smaller fraction of a bigger R). Net E[R] goes from −0.070 to −0.017.


### 5.2 The session gate and the components

The doc's killzone (NY 09:30–11:30 and 13:30–15:30 ET) is a **rule** in the doc; the reference computes setups on every bar and gates only the alerts. It was silently ignored by the leg-tracker path — a fourth engine defect, now fixed — and it is the single largest contributor: it doubles the gross edge.

| arm | candidates | trades | win% | E[R] gross | E[R] net | cost (R) | PF_net | t | 95 % CI | DSR p |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| kz=on  rr=2.0 min=3 known=4  (the best arm) | 1991 | 1528 | 36.4 | **0.0916** | **0.0465** | 0.0451 | 1.070 | 2.48 | [0.019, 0.164] | 0.4185 |
| kz=on  rr=2.0 min=0 (no checklist filter) | ? | 7034 | 35.5 | **0.0637** | **-0.0198** | 0.0835 | 0.972 | 3.72 | [0.030, 0.097] | 0.0716 |
| kz=on  rr=2.0 min=1 known=0 | 9912 | 6754 | 35.5 | **0.0656** | **-0.0176** | 0.0832 | 0.975 | 3.75 | [0.031, 0.100] | 0.0672 |
| kz=on  rr=2.0 min=3 known=0 | 2230 | 1744 | 35.9 | **0.0768** | **0.0256** | 0.0512 | 1.038 | 2.23 | [0.009, 0.144] | 0.5198 |
| kz=off rr=2.0 min=3 known=4 | 10185 | 6422 | 34.7 | **0.0422** | **-0.0168** | 0.0590 | 0.976 | 2.37 | [0.007, 0.077] | 0.4636 |
| kz=on  rr=1.0 min=3 known=4 | 1991 | 1698 | 54.1 | **0.0813** | **0.0362** | 0.0451 | 1.075 | 3.36 | [0.034, 0.129] | 0.1420 |
| kz=on  rr=3.0 min=3 known=4 | 1991 | 1402 | 27.8 | **0.1127** | **0.0680** | 0.0447 | 1.090 | 2.35 | [0.019, 0.207] | 0.4692 |
| kz=on rr=2.0 min=3 known=4  [2020-11..2023-06] | 1012 | 785 | 34.3 | **0.0280** | **-0.0237** | 0.0517 | 0.966 | 0.55 | [-0.072, 0.128] | 0.9587 |
| kz=on rr=2.0 min=3 known=4  [2023-07..2025-07] | 977 | 741 | 38.7 | **0.1619** | **0.1239** | 0.0380 | 1.195 | 3.01 | [0.057, 0.267] | 0.2267 |

### 5.3 Year by year

A configuration chosen from ~60 arms on the full sample is not a validated result. The honest test is whether it holds up in time, so the best arm was re-run year by year.

| year | trades | win% | E[R] gross | E[R] net | cost (R) | PF_net | t |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2021 | 398 | 36.4 | **0.0930** | **0.0373** | 0.0557 | 1.056 | 1.28 |
| 2022 | 195 | 32.8 | **-0.0154** | **-0.0537** | 0.0383 | 0.923 | -0.15 |
| 2023 | 327 | 35.8 | **0.0734** | **0.0242** | 0.0492 | 1.036 | 0.92 |
| 2024 | 295 | 39.0 | **0.1695** | **0.1324** | 0.0371 | 1.210 | 1.99 |
| 2025 | 277 | 37.5 | **0.1264** | **0.0935** | 0.0329 | 1.145 | 1.44 |

**Four of the five years are net-positive; 2022 is not.** Splitting the sample in half is less flattering than the year-by-year view: 2020-11 → 2023-06 is net-negative (−0.024) and 2023-07 → 2025-07 is strongly positive (+0.124).


## 6. The ML gate

The meta-labeler is a rolling walk-forward LightGBM (6 months train / 1 month validate / 1 month test, purged with an embargo) that scores each setup and trades it only when P(Win) ≥ 0.58.

| run | trades | approved | win% | E[R] gross | E[R] net | PF | t | 95 % CI | DSR p |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| honest + ML gate | 933 | 2255 | 33.1 | **-0.0064** | -0.2404 | 0.990 | -0.14 | [-0.097, 0.084] | 0.9873 |
| pine + ML gate | 705 | 874 | 35.0 | **0.0511** | -0.0772 | 1.079 | 0.95 | [-0.055, 0.157] | 0.8782 |
| pine, rule-only (baseline) | 25083 | 51391 | 34.4 | **0.0317** | -0.0700 | 1.048 | 3.52 | [0.014, 0.049] | 0.0760 |

The gate **raises** the reference arm's gross expectancy from +0.0317 to +0.0511 R — it selects the better setups — but it trades 705 instead of 25,083, so the t-statistic collapses. Out-of-sample `auc_test` across the 120 monthly folds was **0.47–0.53** on both candidate sets: the meta-labeler is close to a coin flip. Whatever the edge is, it is not in the checklist score, the SMT flag, the VXN regime or the bar geometry that the feature builder exposes — but it *is* in the session and in the checklist, which the meta-labeler never saw as a filter.


## 7. The vision layer

The layer renders 90 candles in the detector's own training style (640×640, white, TradingView candles, no axes), runs `ibtsam/nq-fvg-detector` over the render and scores its box against the rule engine's gap.

**The project's audit of this layer was wrong and is corrected.** `research/analysis/VISION_AUDIT.md` asserted — from a *static* reading of the checkpoint, without ever running the model — that the detector's boxes wrap the third candle's body, which is disjoint from the gap, and that the doc's `IoU > 0.75` gate was therefore unreachable by construction. Measured:

| quantity | measured |
| --- | --- |
| boxes landing on a rule-engine FVG's **middle bar** | **336 / 348 = 96.6 %** |
| the box's class equals the gap's own direction | **96.1 %** |
| 1-D vertical IoU vs the **gap interval** | **median 0.9518**, mean 0.9193 |
| … above the doc's `IoU > 0.75` gate | **94.9 %** |
| 1-D vertical IoU vs the third candle's **body** | median 0.0000 (the body's disjointness is real — but the boxes are *not* the body) |

The detector is named `nq-fvg-detector` and is trained to detect *fair value gaps*: its box wraps the **gap**. The doc's literal metric — the IoU against the FVG price interval in the vertical price axis — is well-posed and reachable.

### 7.1 Does it carry trading information?

Scored over a uniform 5.9 % sample of the reference arm's census (2,646 candidates, 0.45 s each on CPU):


```
filter                            n     win%    E[R]     z vs the rest
```
```
  vision IoU >= 0.75 (the doc's gate)       1923  34.43 +0.0328   z=+1.13   (rest n=  723 win%=32.09 E[R]=-0.0373)
```
```
  detector confidence >= 0.4                1825  35.18 +0.0553   z=+2.26   (rest n=  821 win%=30.69 E[R]=-0.0792)
```
```
  detector confidence >= 0.5                1650  35.03 +0.0509   z=+1.74   (rest n=  996 win%=31.73 E[R]=-0.0482)
```
```
  detector confidence >= 0.6                1366  34.63 +0.0388   z=+0.94   (rest n= 1280 win%=32.89 E[R]=-0.0133)
```
```
  detector confidence >= 0.75                687  33.48 +0.0044   z=-0.20   (rest n= 1959 win%=33.89 E[R]=+0.0168)
```
```
  never detected                             580  31.72 -0.0483   z=-1.19   (rest n= 2066 win%=34.37 E[R]=+0.0310)
```

**The IoU gate itself is uninformative** (point-biserial correlation with the outcome **+0.002**): the rule engine found the gap, so the geometry always matches and the IoU only measures agreement, not quality.

**The detector's confidence is the signal.** A candidate the detector confirms with confidence ≥ 0.4 has a win rate of **35.2 %** against **30.7 %** for the rest, and an expectancy of **+0.055 R** against **−0.079 R** — a two-proportion **z = +2.26**, the first filter in this project with significant discriminating power that is neither the session nor the checklist. The mechanism is plausible: the detector only finds a *confident* gap where the price action is clean, and the low-confidence bucket (conf < 0.4) is the worst group of all (E[R] −0.154).

The confidence is used as the filter, not the IoU. The doc's IoU gate is kept as the **geometry check** — it answers "did the model see the same gap?", which it passes 72.6 % of the time — and the confidence answers "was the price action clean?".


## 8. Does it generalise? The configuration on other instruments

The configuration above was **selected on NQ**. Running it unchanged on two other instruments is the only honest test available: the ES panel (2020-11 → 2024-07, the SMT reference is NQ) and BTCUSDT (2023-01 → 2026-11, a different market and a different period).

| instrument | trades | win% | E[R] gross | E[R] net | cost (R) | PF | t | 95 % CI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ES 1m | 129 | 28.7 | **-0.1395** | -0.2959 | 0.1564 | 0.804 | -1.16 | [-0.375, 0.096] |
| ES 1m | 1000 | 33.6 | **0.0080** | -0.1343 | 0.1423 | 1.012 | 0.18 | [-0.080, 0.096] |
| BTCUSDT 1m (no killzone, no checklist) -- the plain reference arm | 16133 | 34.6 | **0.0380** | -0.4266 | 0.4646 | 1.058 | 3.38 | [0.016, 0.060] |

**The rule engine's gross edge replicates on BTCUSDT** (+0.0380 R, t = 3.38, CI [0.016, 0.060]) — the same magnitude as NQ, on a different market and a different period. That is the strongest evidence that the edge is a property of the *rule*, not of NQ.

**But the filtered configuration does not generalise.** On ES the killzone + checklist arm is **−0.140 R** (t = −1.16), and even without the checklist ES carries only +0.008 R (t = 0.18) — against NQ's +0.032 R. The session and checklist filters were chosen on NQ and they do not carry to a different instrument, and the ES panel's 55 % weekday coverage makes its sample thin as well. **This is the pre-registered test failing, and it is reported as such.**


## 9. Verdict against the design doc's phase-1 gate

| Gate | Required | Measured | Met? |
| --- | --- | --- | --- |
| Profit factor | **> 1.25** | 1.048 rule-only; 1.144 gross / **1.070 net** for the killzone + checklist arm | **No** |
| Expectancy | positive | **+0.047 R net** for that arm (−0.070 R for the plain reference arm) | **Yes**, for that arm |
| Costs | ~$4.50 + 1–2 ticks | applied (0.033–0.045 R on the filtered arm) | yes |
| Population | A/A+ only | not computable — no artefact defines a grade (D8); the five named booleans are used instead | substituted |
| Sample | 10 years, 3.66 M bars | the filtered arm trades 2020-11 → 2025-07 because the SMT is undecidable before ES starts | partly |

### 9.1 The answer to "entry or payoff?"

**The edge is in the entry.** The evidence, in order of size:

| lever | effect on gross E[R] | what it is |
|---|---|---|
| the payoff (RR 1 → 4) | **+0.008 R** (flat) | how far the target is |
| the session (killzone on) | **+0.049 R** | *when* the setup is taken |
| the checklist (score ≥ 3) | **+0.015 R** | *which* setup is taken |
| the stop width (×1.5 … ×3) | **−0.068 R** | where the stop sits |

So the strategy was never a payoff problem: the reference's 1:2 target was fine. It was an **entry** problem — the setups outside the NY session and outside the named conditions are noise, and they cost more in fees than they earn.

### 9.2 What is still missing

**No configuration survives the multiple-testing correction.** The deflated Sharpe is computed against the ~60 arms tried in this project; the best p-value is 0.0672 and the net-positive arms are all above 0.4. A configuration *selected* as the best of 60 on the same sample it is measured on is a hypothesis, not a result.

The right next step is therefore **not** another filter but a **pre-registered confirmation** — and the first such test has already been run and **failed on ES** (§8). What survives is narrower and more honest:

* the **rule engine's gross edge** replicates on BTCUSDT (+0.038 R, t = 3.38), so it is a property of the rule, not of NQ;
* the **filters** (session, checklist) were selected on NQ and do not carry to another instrument;
* **no configuration survives the multiple-testing correction** on the sample it was selected on.

The vision layer is **built and it works**, and it is the one filter with significant discriminating power that is neither the session nor the checklist: the detector's confidence (z = +2.26, §7). It has not yet been run over the *traded* set, so its effect on the portfolio expectancy is still unmeasured — and because the confidence threshold was picked from four candidates, it carries its own selection risk.


## 10. What would move the number

| lever | measured effect | status |
| --- | --- | --- |
| the doc's NY killzone | gross E[R] +0.049 R, net E[R] −0.070 → +0.047 | **done** — and it was silently ignored by the engine until now |
| the named checklist conditions | gross E[R] +0.015 R and the cost ratio halves | **done** |
| the payoff | nothing (±0.008 R across 1:1 → 1:4) | **measured, exhausted** |
| a wider stop | destroys the edge | **measured, exhausted** |
| the doc's mandatory sweep precondition | gross E[R] +0.106, trades halved | **done** — DSR p 0.574 |
| the vision layer's detector confidence | win% 35.2 vs 30.7, E[R] +0.055 vs −0.079, **z = +2.26** | **built** — §7; the effect on the portfolio expectancy is not yet measured |
| the meta-labeler | raises gross E[R] but AUC 0.47–0.53 | **measured, exhausted** on the current features |
| the same configuration on another instrument | BTCUSDT +0.038 R (t = 3.38) — the edge replicates; ES −0.140 R | **done** — the edge generalises, the filters do not |

A pre-registered forward test of the frozen configuration is the only thing left before this can be called an edge.
