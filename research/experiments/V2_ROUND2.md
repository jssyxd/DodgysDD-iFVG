# V2 round 2 — the target R, the gates, the ablations, and the 15/15/30 planner

NQ, `nq` costs, 1 tick, one position at a time (drop). Everything net unless
stated.

## 1. The target R — on the HTF-gated arm it matters, monotonically

`pine_htf15only` (reference rules + NY killzone + **the last closed 15m bar
agrees with the side**):

| RR | trades | win% | E[R] gross | **E[R] net** | PF | t | DSR p | total R net |
|---|---|---|---|---|---|---|---|---|
| 1.0 | 4,937 | 53.2 | +0.0638 | +0.0063 | 1.136 | 4.49 | 0.0174 | 315 |
| 1.5 | 4,590 | 43.1 | +0.0779 | +0.0206 | 1.137 | 4.26 | 0.0283 | — |
| 2.0 | 4,280 | 36.1 | +0.0822 | +0.0251 | 1.129 | 3.73 | 0.0829 | 352 |
| 2.5 | 4,035 | 31.7 | +0.1086 | +0.0514 | 1.159 | 4.23 | 0.0279 | — |
| 3.0 | 3,828 | 28.1 | +0.1254 | +0.0685 | 1.174 | 4.31 | 0.0223 | — |
| **4.0** | **3,457** | 23.2 | **+0.1614** | **+0.1047** | **1.210** | **4.49** | **0.0129** | **558** |

**The curve is monotone, and it is the outcome, not portfolio selection.** The
census (every candidate, standalone) confirms it: at RR = 2 the killzone census
is +0.0561 R over 11,132 setups; at RR = 4 the HTF-gated census is **+0.1681 R
over 5,573**. The portfolio (+0.1614) tracks the census, so the gate is not
manufacturing the result by picking winners.

This **contradicts the earlier finding** that "the edge is in the entry, not the
payoff". That was measured on the *ungated* arm, where E[R] is flat across
RR 1→4 (+0.031, +0.024, +0.032, +0.027, +0.027, +0.033). The HTF gate changes
the trade population so that a distant target pays: at RR = 4 the win rate
(23.2 %) still clears the 20 % break-even by 3.2 points, and the payoff
multiplies that margin by 4.

## 2. The drawdown of the best arm

`pine_htf15only` at **RR 4**, net of costs:

| | baseline `pine` RR 2 | **`pine_htf15only` RR 4** |
|---|---|---|
| trades | 6,745 | 3,457 |
| total R net | +78.1 | **+361.8** |
| max drawdown net | 113.9 R | **73.5 R** |
| total / DD | 0.69 | **4.92** |
| Sortino | 0.011 | **0.099** |

**This is the first configuration whose drawdown is smaller than its profit.**
The cost is a 23.2 % win rate and up to **24 consecutive losses** — the curve is
lumpy.

**Caveat, stated plainly:** the DSR p of 0.0129 is computed against 64 trials,
but this round added 6 RR values × several gate configs. The effective trial
count is closer to 100, so the true p is larger than 0.013. Treat it as a
promising hypothesis, not an established edge.

## 3. Ablation — the gates

| gate | trades | E[R] gross | **E[R] net** | PF | t |
|---|---|---|---|---|---|
| none | 6,745 | +0.0697 | +0.0116 | 1.108 | 3.98 |
| **15m bias agrees** | 4,280 | **+0.0822** | **+0.0251** | 1.129 | 3.73 |
| 1H bias agrees | 4,280 | +0.0801 | +0.0230 | 1.125 | 3.64 |
| ≥2R liquidity target | 5,399 | +0.0224 | **−0.0402** | 1.034 | 1.16 |
| both | 2,936 | +0.0504 | −0.0081 | 1.078 | 1.91 |

**The liquidity precondition is the harmful half.** The gate's *census* edge is
+0.0734 R (agrees, n=4,807) vs +0.0443 (disagrees, n=6,205) — a two-proportion
**z of only +1.06** (1H: +1.34). So the bias gate is directionally right but
**not statistically significant on its own**; the portfolio-level improvement
also includes path effects.

## 4. Ablation — the features (single-feature AUC)

Rank-based AUC against the label, on the 11,132-candidate killzone log:

| feature | AUC | | feature | AUC |
|---|---|---|---|---|
| minutes_from_us_open | 0.4867 | | gap_quality | 0.4951 |
| volume_zscore_60 | 0.4897 | | risk_atr | 0.4970 |
| dist_to_htf_liquidity | 0.4901 | | recent_same_side_wr | 0.4971 |
| checklist_score | 0.4907 | | vxn_level | 0.4974 |
| smt_divergence | 0.4912 | | vxn_regime | 0.4983 |
| htf_bias_1h | 0.5066 | | vision_confidence | 0.5011 |
| gap_atr | 0.4934 | | bars_to_inversion | 0.4992 |
| atr14 | 0.4935 | | inversion_speed | 0.5008 |
| vxn_zscore | 0.5059 | | session_quality | constant |
| htf_bias_15m | 0.5052 | | | |

**Every feature is 0.487–0.507.** Nothing above |AUC − 0.5| = 0.014. This is a
stronger statement than the correlation table (AUC is monotone-invariant): as a
*score*, no feature carries signal. Yet `htf_bias_15m` *as a gate* still helps —
a feature can be useless for ranking and useful as a rule condition, because the
gate interacts with the side and the stop geometry rather than adding a term.

## 5. The 15/15/30 day planner — implemented, and two hard blockers

The planner (`dodgys_dd_quant/ml_pipeline/splits.py::make_folds_days`) is built
and verified: 128 folds on NQ, `test_start > asof` in all of them, no overlapping
test windows, the same purge/embargo contract as the monthly scheme.

**Blocker 1 — candidate density.** A 15-day training window needs
`MIN_TRAIN_ROWS = 200`, i.e. **13.3 candidates/day**:

| arm | candidates/day | per 15-day window |
|---|---|---|
| ungated pine | 13.3 | 200 (exactly at the floor) |
| killzone | 2.9 | 43 |
| **htf15 (the arm with the edge)** | **1.4** | **22** |

The filters that create the edge also thin the sample below what a 15-day window
can train on. **A workable scheme for the filtered arms needs ~90 training
days**, not 15 (200 / 2.9 ≈ 69 usable days + the embargo).

**Blocker 2 — a sparse optional feature silently gutted the sample.** The
trainer drops every row with a NaN in *any* used feature.
`vision_confidence` is 94.9 % NaN in the `NQ_1m_pine` log (the vision layer was
run over a 5.9 % sample), so a 15-day window with 176 candidates yielded
**3 usable rows** and all 128 folds were skipped. `resolve_feature_list` only
excluded a column that was *entirely* NaN. **Fixed**: a feature with more than
`MAX_FEATURE_NAN_FRAC = 0.20` missing is now excluded (never imputed), and the
usable rows went from 3 % to **97.9 %**.

**After the fix**, on the ungated pine census: 53 of 128 folds trained (the rest
have <200 rows in their 15-day window), median out-of-sample **AUC 0.5131**
(min 0.4322, max 0.5639) — the best the meta-labeler has managed, and still
barely above a coin flip.

**The rolling gated backtest (day-scheme models, killzone arm):**

| | trades | win% | E[R] gross | E[R] net | PF | t |
|---|---|---|---|---|---|---|
| ML-gated (15/15/30) | 4,064 | 36.0 | +0.0792 | **+0.0055** | 1.124 | 3.51 |
| rule-only, same candidates | 6,745 | 35.7 | +0.0697 | **+0.0116** | 1.108 | 3.98 |

**The rolling ML gate lowers the net expectancy** — it raises the gross by
selecting better-looking setups but removes trades that were paying their cost.

## 6. What this round establishes

1. **The target R matters, but only on the gated arm** — RR 4 turns a +0.025 R
   arm into a **+0.105 R** arm, with the drawdown smaller than the profit.
2. **The 15m/1H bias gate is worth keeping; the ≥2R liquidity precondition is
   not.**
3. **No feature carries single-feature signal** (all AUC 0.487–0.507), so the
   meta-labeler cannot lift the expectancy — the rolling ML gate *lowers* it.
4. **The 15/15/30 scheme cannot train on the filtered arms** at 1.4–2.9
   candidates/day; it needs ~90-day training windows there.
5. A sparse optional feature was silently discarding 95 % of the training rows;
   fixed with an explicit NaN-fraction exclusion.
