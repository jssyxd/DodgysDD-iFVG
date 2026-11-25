ETHUSDT 15m — the timeframe test (E3)
=====================================

Why
---
The published E2E (``E2E_MODEL_WALKFORWARD.txt``) ran the rule engine on
**BTCUSDT 1-minute** bars with Binance costs, and its verdict (K3) is what the
repository quotes.  Measured afterwards: on Binance 1-minute bars the
round-trip fee is **1.5 x a 1-ATR stop** (the strategy's actual stop is ~2.6
ATR, so the median cost is **0.588 R**).  That cost structure, not the rule
set, decides the sign of the result.  This run changes **one thing**: the bar
interval (and the instrument, because ETH has a six-year 15m lane and BTC's
15m lane starts in 2024).

The question it answers: is the "no edge" verdict a property of the rules, or
of the 1-minute reference?

Data and command
----------------
::

  data   crypto/futures_um/ETHUSDT/15m/ETHUSDT_15m_consolidated.parquet
         239,520 bars  2020-01-01 -> 2026-10-31
  regime crypto DVOL (BTCDVOL_1h, lagged), SMT reference BTCUSDT 15m
  costs  cost profile "binance", 1 tick of slippage
  preset "honest" (the engine's own window, (1, 15), unless stated)
  python -m dodgys_dd_quant.backtest.runner --symbol ETHUSDT --timeframe 15m \
      --regime dvol --reference-symbol BTCUSDT --cost-profile binance \
      --slippage-ticks 1 --candidates-out /tmp/eth15_candidates.parquet \
      --models-root /tmp/eth15_artifacts/models

One position at a time, drop accounting (D4) throughout.

1. The timeframe effect, same instrument, same features, same costs
------------------------------------------------------------------
| run | n | win% | E[R] gross | t | CI95 | mean cost | E_net | PF_net |
|---|---|---|---|---|---|---|---|---|
| ETHUSDT 1m + DVOL | 39,645 | 35.0 | **-0.0003** | -0.04 | [-0.014, +0.013] | **0.636** | -0.636 | 1.000 |
| ETHUSDT 15m + DVOL | 4,221 | 35.4 | **+0.0475** | **2.17** | **[+0.005, +0.090]** | **0.111** | -0.063 | 0.912 |

The sign flips with the bar interval, and the reason is mechanical: the fee
relative to the stop falls by a factor of ~6, and the gross edge improves from
zero to +0.0475 R.

For reference, the published 1-minute run: BTCUSDT 1m, n = 32,521,
win 32.7 %, E[R] -0.0183, mean cost 0.61 R, E_net -0.633, PF 0.973.

2. The cost ladder (measured, same 1 ATR stop)
----------------------------------------------
| instrument | 1m | 5m | 15m |
|---|---|---|---|
| NQ, $4.50 round turn + 1 tick | 0.068 R | 0.029 R | **0.016 R** |
| BTCUSDT, Binance 0.08 % + 1 tick | 1.502 R | 0.551 R | **0.286 R** |

(The strategy's stop is wider than 1 ATR, which is why its realised median cost
is 0.588 R on BTC 1m and 0.111 R on ETH 15m.)

3. Ablations on ETH 15m (rule-only)
-----------------------------------
| config | n | win% | E[R] gross | t | CI95 |
|---|---|---|---|---|---|
| plain (1, 15), no regime | 5,119 | 34.4 | +0.0326 | 1.64 | [-0.006, +0.072] |
| + DVOL regime | 4,221 | 35.4 | +0.0475 | 2.17 | [+0.005, +0.090] |
| + BTC SMT reference only | 5,119 | 34.4 | +0.0326 | 1.64 | identical to plain |
| + DVOL, doc window (7, 15) | 3,462 | 35.0 | +0.0485 | 2.00 | [+0.001, +0.096] |

* The regime filter is the only layer that changes the population: it removes
  ~900 trades and lifts the win rate 34.4 -> 35.4 %.
* The SMT reference leaves the rule-only arm **identical** -- by design (D8):
  the checklist is reported, never filtered, so a reference instrument can only
  reach the ML as a feature.

4. The meta-labeler, rolling 6/1/1 with the same artefacts
----------------------------------------------------------
| arm | n | win% | E[R] | t | mean cost | E_net | PF_net |
|---|---|---|---|---|---|---|---|
| rule-only | 4,221 | 35.4 | +0.0475 | 2.17 | 0.111 | -0.063 | 0.912 |
| ML-gated, P(Win) >= 0.58 | 208 | 33.2 | **-0.0553** | -0.58 | 0.098 | -0.154 | 0.790 |

* 75 folds; **61 of them approve zero candidates** (81 %).  The fixed absolute
  threshold is applied to uncalibrated probabilities (no isotonic/Platt step),
  so the gate opens in bursts and is closed for years at a time -- the same
  pathology as the 1-minute run (31 of 39 folds empty, 2026-09 admitting
  201 of 8,298).
* `auc_test` is 0.38-0.60 across the folds, centred on 0.50: the six
  doc features (four usable here) carry no signal at this horizon either.
* Verdict: K3 (importance_churn), abort criteria A1, A2 and A4 fire.

5. Per-fold table (model arm)
-----------------------------
fold        mode         cands   appr  trades   win%     E[R]    E_net     PF      t                CI95
--------------------------------------------------------------------------------------------------------
2020-08-01  model          349      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2020-09-01  model          338      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2020-10-01  model          358      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2020-11-01  model          359      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2020-12-01  model          351      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2021-01-01  model          337      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2021-02-01  model          326      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2021-03-01  model          298      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2021-04-01  model          362      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2021-05-01  model          356      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2021-06-01  model          331      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2021-07-01  model          272      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2021-08-01  model          302      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2021-09-01  model          335      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2021-10-01  model          389      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2021-11-01  model          360      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2021-12-01  model          331      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2022-01-01  model          343      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2022-02-01  model          283      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2022-03-01  model          377      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2022-04-01  model          301      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2022-05-01  model          354      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2022-06-01  model          301      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2022-07-01  model          298      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2022-08-01  model          315      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2022-09-01  model          302      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2022-10-01  model          295      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2022-11-01  model          296      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2022-12-01  model          298      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2023-01-01  model          309      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2023-02-01  model          243      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2023-03-01  model          305      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2023-04-01  model          319      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2023-05-01  model          267      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2023-06-01  model          338      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2023-07-01  model          335      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2023-08-01  model          420      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2023-09-01  model          378      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2023-10-01  model          127      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2023-11-01  model          116      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2023-12-01  model          129      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2024-01-01  model           92      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2024-02-01  model          111      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2024-03-01  model           71     19      12   36.4   0.0909   0.0420  1.143   0.20      [-0.804,0.985]
2024-04-01  model           73      1       1    0.0  -1.0000  -1.0593  0.000    n/a           [n/a,n/a]
2024-05-01  model          120      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2024-06-01  model           93      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2024-07-01  model           83      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2024-08-01  model           93     17      16   37.5   0.2187   0.1211  1.350   0.53      [-0.586,1.024]
2024-09-01  model           94     22      15   28.6  -0.1429  -0.2365  0.800  -0.37      [-0.894,0.608]
2024-10-01  model          140      5       5   40.0   0.4000   0.2571  1.667   0.47      [-1.280,2.080]
2024-11-01  model           93      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2024-12-01  model           96      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2025-01-01  model          111      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2025-02-01  model           82      3       1    0.0  -1.0000  -1.0669  0.000    n/a           [n/a,n/a]
2025-03-01  model           87      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2025-04-01  model           87     31      21   42.9   0.0952   0.0262  1.167   0.34      [-0.461,0.651]
2025-05-01  model           79      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2025-06-01  model           67      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2025-07-01  model           81     61      32   33.3  -0.1667  -0.2365  0.750  -0.76      [-0.596,0.262]
2025-08-01  model           78     25      21   28.6  -0.2857  -0.3643  0.600  -1.13      [-0.781,0.209]
2025-09-01  model           87      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2025-10-01  model           95      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2025-11-01  model          148      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2025-12-01  model          123      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2026-01-01  model          109      1       1  100.0   1.5000   1.4270    inf    n/a           [n/a,n/a]
2026-02-01  model           77      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2026-03-01  model          101      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2026-04-01  model          114     38      26   26.9  -0.0962  -0.2239  0.868  -0.32      [-0.684,0.492]
2026-05-01  model           85      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2026-06-01  model          111     29      15   35.7   0.1786   0.1071  1.278   0.40      [-0.691,1.048]
2026-07-01  model          115      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
2026-08-01  model          116     31      19   44.4   0.2222   0.0604  1.400   0.66      [-0.442,0.886]
2026-09-01  model           96     38      29   24.1  -0.3621  -0.4886  0.523  -1.67      [-0.786,0.062]
2026-10-01  model          116      0       0    nan      n/a      n/a    n/a    n/a           [n/a,n/a]
--------------------------------------------------------------------------------------------------------
PORTFOLIO (1 at a time, drop)    n=208     win%= 33.2  E[R]= -0.0553  E_net= -0.1535  PF= 0.917  t= -0.58  CI95=[-0.241,0.131]
BASELINE  (rule-only, drop)      n=4221    win%= 35.4  E[R]=  0.0475  E_net= -0.0632  PF= 1.074  t=  2.17  CI95=[0.005,0.090]
candidates=18869  approved=321  trades=214
Sharpe (per trade) = -0.0404   deflated Sharpe = 0.0042   DSR p-value = 0.9958   trials = 32
KILL-SWITCH: K3   signals fired: importance_churn
ABORT CRITERIA (L4 C.6): fired A1, A2, A4

6. What this does and does not establish
----------------------------------------
**Established (measured):**
* The 1-minute reference is the dominant cause of the negative result: the same
  rules, instrument, features and costs give -0.0003 R at 1m and +0.0475 R
  (t = 2.17) at 15m.
* On ETH 15m the rule engine has a **positive gross edge for the first time**
  in this repository, and it is *exactly* cancelled by the Binance fee: the
  break-even round-trip cost is 0.0475 R, the measured one is 0.111 R.
* The meta-labeler does not help at any horizon tested: the gated arm is worse
  than the rule-only arm and its probability threshold is effectively broken by
  the absence of calibration.

**Not established (do not claim):**
* That the strategy is profitable.  At the measured Binance cost it is not
  (E_net -0.063 R), and the crypto fee is not negotiable at retail.
* That the same edge exists on NQ/ES.  The *cost* there is measured (0.016 R at
  15m); the *edge* on NQ is unknown, because no multi-year NQ 15m/1m lane
  exists in the lake (NQ 1m is one week).
* That 240 bars (= 60 hours at 15m) is the right holding period: it is the
  engine's constant, carried over from the 1-minute configuration, and it
  outlives the intraday killzone premise.

7. Next decisions (ordered)
---------------------------
1. NQ/ES 15m with the CME cost model is the **decisive** test: the fee there is
   0.016 R, i.e. one third of the measured gross edge.  It needs a multi-year
   NQ/ES 15m lane (Databento ~$10-30) -- the lake's NQ 1m is one week.
2. Fix the gate before trusting any gated number: calibrate on the validation
   fold (isotonic/Platt) and replace the absolute 0.58 with a per-fold
   quantile/top-k rule.  The 61 empty folds are a threshold artefact, not a
   model verdict.
3. Make the holding period time-based (minutes, or "to session close") instead
   of 240 bars, so the same configuration means the same thing at 1m, 5m and 15m.
4. Keep 1-minute (or tick) series for **execution** only: HTF setups, LTF
   trigger, tick-level fill ambiguity.
