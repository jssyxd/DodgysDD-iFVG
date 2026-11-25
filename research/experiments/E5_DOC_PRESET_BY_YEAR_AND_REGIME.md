E5 — the `doc` preset decomposed by year and by volatility regime
=================================================================

Why
---
The `doc` preset (ATR gap floor + the doc's filters) is the only version whose
**net** expectancy was positive on ETHUSDT 15m: +0.0040 R over 617 trades.
A single aggregate number hides the question that decides whether it is a
lead or a fit: **is it one year (one regime), or is it spread out?**

Setup
-----
* series: ETHUSDT 15m, 238,531 bars, 2020-01 → 2026-10;
* rules: `PRESETS["doc"]`, code inversion window, 240-bar (60 h) horizon;
* regime: DVOL, lagged (the crypto index; `-1` = not yet covered, i.e. the
  trades before DVOL's history starts in 2023-10);
* reference: BTCUSDT 15m (SMT);
* costs: Binance 0.08 % + 1 tick, per trade, expressed in R;
* accounting: one position at a time, drop (D4).

Portfolio: 832 candidates → 651 selected → 617 labelled.

By year
-------
| year | n | win % | E[R] | mean cost | E_net | t |
|---|---|---|---|---|---|---|
| 2020 | 75 | 32.0 | -0.0400 | 0.1149 | **-0.1549** | -0.25 |
| 2021 | 101 | 39.6 | +0.1881 | 0.0491 | **+0.1390** | 1.28 |
| 2022 | 87 | 33.3 | +0.0000 | 0.0638 | -0.0638 | 0.00 |
| 2023 | 102 | 34.3 | +0.0294 | 0.1194 | **-0.0900** | 0.21 |
| 2024 | 80 | 36.2 | +0.0937 | 0.0778 | **+0.0160** | 0.57 |
| 2025 | 100 | 38.0 | +0.1050 | 0.0571 | **+0.0479** | 0.72 |
| 2026 | 72 | 41.7 | +0.2083 | 0.0871 | **+0.1213** | 1.20 |

Reading: the net is positive in **four of seven years** (2021, 2024, 2025,
2026), flat in 2022, negative in 2020 and 2023.  It is *not* one lucky year:
the most recent three years are all positive.  But no single year carries a
t-statistic above 1.3, and the annual samples are ~100 trades each — the
aggregate `t = 1.45` is the honest summary, and it does not reject zero.

By volatility regime (DVOL)
----------------------------
| regime | n | win % | E[R] | mean cost | E_net | t |
|---|---|---|---|---|---|---|
| `-1` unknown (before 2023-10) | 345 | 35.7 | +0.0696 | 0.0857 | -0.0162 | 0.90 |
| `0` low volatility | 102 | 48.0 | +0.2010 | 0.0733 | **+0.1277** | 1.62 |
| `1` normal | 110 | 33.6 | +0.1773 | 0.0760 | **+0.1013** | 1.12 |
| `2` high volatility | 60 | 26.7 | **-0.2000** | 0.0683 | **-0.2683** | -1.16 |

This is the clearest structure the project has produced:

* **the edge lives in low and normal volatility** (+0.13 and +0.10 R net),
  and those two buckets together hold 212 trades;
* **high volatility is a loss generator** (-0.27 R net) on 60 trades — the
  win rate falls to 26.7 %, far under the 33.3 % a 1:2 payoff needs;
* this is exactly what the design doc asserts ("高波恐慌期: 单根 1 分钟 K 线
  即可扫穿 50 点止损 … 将单笔风险敞口减半，并要求更大的 ATR 最小缺口阈值"),
  and it is the first place where a doc rule is **measured** rather than
  implemented.

Year × regime (the interaction)
--------------------------------
| year | regime | n | win % | E_net |
|---|---|---|---|---|
| 2023 | 1 | 10 | 10.0 | -0.7200 |
| 2023 | 2 | 9 | 33.3 | -0.1003 |
| 2024 | 0 | 17 | 58.8 | +0.3864 |
| 2024 | 1 | 37 | 29.7 | -0.0397 |
| 2024 | 2 | 26 | 30.8 | -0.1470 |
| 2025 | 0 | 56 | 39.3 | -0.0765 |
| 2025 | 1 | 36 | 41.7 | +0.4032 |
| 2025 | 2 | 8 | 12.5 | -0.6795 |
| 2026 | 0 | 28 | 57.1 | +0.3347 |
| 2026 | 1 | 27 | 37.0 | +0.1961 |
| 2026 | 2 | 17 | 23.5 | -0.3492 |

Every year's regime-2 bucket is negative.  The regime-0/1 buckets are positive
in 2026, mixed in 2025 and 2024 — the year-to-year variance inside a regime is
as large as the regime effect itself, so the regime split is a *hypothesis*
with a plausible mechanism, not yet a rule that survives multiple testing.

What this establishes
---------------------
* **The +0.004 R is not one year.**  It is positive in the last three years
  and positive in the two calm regimes; 2020 and 2022-2023 are its losses.
* **High volatility is a systematic drain** (all four years negative), which
  is what the doc's risk-halving rule was written for.
* **Neither statement is significant by itself.**  Annual n ≈ 100, the regime
  buckets n = 60-110.  The right next test is therefore not "add a filter and
  re-measure" (that is how a 617-trade sample is fitted to death) but a
  **pre-registered rule** — regime 2 out, or risk-halved — evaluated on a
  different instrument/venue (NQ/ES 15m once the data exists, or a held-out
  crypto venue), with the trial count updated in the registry.

7. Out-of-sample check: the same preset on SOLUSDT 15m
-------------------------------------------------------
The new 15m lane for SOLUSDT (built from the 5m Binance Vision pull, 2023-01 →
2026-10, 134,400 bars) lets the *same* preset run on a **different instrument**
with the same rules, regime index, horizon and costs.

| preset | n | win % | E[R] | E_net | PF | t |
|---|---|---|---|---|---|---|
| `doc` | 341 | 32.3 | **-0.0645** | -0.2465 | 0.905 | -0.87 |
| `e1` | 2,125 | 34.9 | +0.0129 | -0.2419 | 1.020 | 0.43 |

By year (SOL, `doc`): 2023 +0.0930, **2024 -0.4257 (t = -3.03)**, 2025 +0.1029,
2026 -0.1139.
By regime (SOL, `doc`): `-1` +0.1831, `0` -0.1331, `1` -0.1833, `2` -0.0357
— **all four net negative**.

**The ETH structure does not replicate.**  On ETH the calm regimes carried the
edge and high volatility drained it; on SOL the calm regimes are the *worst*
buckets.  The honest reading of both runs: at n ≈ 600 the annual and regime
splits are within the noise of a ~35 % win rate against a 33.3 % break-even,
and the ETH numbers should be treated as **instrument-specific until they
survive a second instrument or a pre-registered rule change**.

This is exactly why the next step is data, not more filtering: the analysis has
now been run on every crypto instrument the lake can offer at 15m, and the
spread between them is larger than the effect being measured.

8. Five instruments on the same configuration (2023-01 → 2026-10/11)
--------------------------------------------------------------------
The new 15m lanes (section 7 of `DATA_LANES_2026-11.md`) allow the identical
run on five instruments.  Same rules, DVOL regime, 60 h horizon, Binance fees
with each symbol's **own tick**, one position at a time:

| symbol | n | win % | E[R] | E_net | PF | t |
|---|---|---|---|---|---|---|
| BTCUSDT | 390 | 34.4 | -0.0051 | -0.1143 | 0.992 | -0.07 |
| ETHUSDT | 355 | 35.5 | +0.0465 | -0.0331 | 1.072 | 0.61 |
| SOLUSDT | 341 | 32.3 | -0.0645 | -0.1326 | 0.905 | -0.87 |
| BNBUSDT | 332 | 35.8 | +0.0452 | -0.0660 | 1.070 | 0.58 |
| XRPUSDT | 320 | 34.7 | +0.0172 | -0.0700 | 1.026 | 0.22 |

Mean gross ≈ **+0.008 R**, no instrument net-positive, no |t| above 0.9.
The ETH figure that motivated this decomposition (+0.004 R net on 2020-2026)
becomes -0.033 R net once the window is restricted to 2023+ and the tick is
the symbol's own — i.e. the "positive net" was a full-sample accident of
2019-2022.

**Cost-model defect found by this table:** the Binance profile carried one
tick (0.10) for every symbol, so XRP (price ≈ 0.5) paid 20 % of its price per
tick of slippage and read **-12 R net per trade**.  `profile_for(symbol)` now
takes each USDT-M perp's own tick (BTC 0.1, ETH/SOL/BNB 0.01, XRP 0.0001);
the XRP figure above is after the fix.

**Verdict:** on every instrument the crypto data can support, the `doc` preset
has no net edge at 15m.  The earlier ETH number should not be quoted as a
result, and no further filter should be fitted to it.
