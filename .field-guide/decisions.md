
## 2026-11-23 — Phase 1 executed on NQ 1-minute, 2015-2025 (3.66 M bars)
**Arms and results (one position at a time, NQ costs ≈ $4.50 + 1 tick):**

| arm | components | trades | win% | E[R] gross | E[R] net | PF | t | 95 % CI |
|---|---|---|---|---|---|---|---|---|
| `honest` | vectorised scanner | 45,734 | 32.9 | −0.0127 | −0.1436 | 0.981 | −1.93 | [−0.026, 0.000] |
| `pine_be` | + BE-intact gate | 45,269 | 32.9 | −0.0135 | −0.1450 | 0.980 | −2.03 | [−0.026, −0.000] |
| `pine_leg` | + leg tracker | 25,228 | 34.3 | **+0.0303** | −0.0714 | 1.046 | **+3.38** | **[0.013, 0.048]** |
| `pine` | both | 25,083 | 34.4 | **+0.0317** | −0.0700 | 1.048 | **+3.52** | **[0.014, 0.049]** |
| `doc` | ATR floor + sweep + killzone | 7,399 | 34.1 | +0.0242 | −0.1021 | 1.037 | +1.46 | [−0.008, 0.057] |

**The single most important finding of the project so far:** the *leg tracker* is
the entire source of the edge. Alone it moves E[R] from −0.013 to +0.030 and t from
−1.9 to +3.4; the BE-intact gate on its own does nothing (−0.0135) and adds only
+0.0014 on top of the tracker. The doc's ATR floor + sweep + killzone is a weaker,
non-significant version of the same effect.

**But the edge is 3× too small.** The reference-faithful arm's gross expectancy is
+0.032 R while the NQ round trip costs ≈ 0.10 R, so every arm is net-negative. The
doc's phase-1 gate (profit factor > 1.25) is not met and is not reachable by
tuning: the edge exists, it is simply smaller than the costs.

## 2026-11-23 — three defects found and fixed in the rule engine
1. **The leg tracker's pivots were a 3-bar rolling minimum.** It fires on ~⅓ of all
   bars, so the live gap was discarded long before it could reach the 7-bar
   minimum inversion age: the reference-faithful arm produced **one trade in ten
   years**. Fixed to use the module's own fractal pivots (`causal_pivots`,
   2 left / 2 right), the same definition the origin tracker already used.
   *This single bug was hiding the strategy's entire edge.*
2. **`require_be_intact` was dead configuration** — declared on `RuleConfig` and
   set by the `pine` preset, but never read anywhere. Now implemented: a setup is
   rejected when price already traded through the swing the leg started from
   between the origin and the confirmation.
3. **SMT recorded "no divergence" where the reference instrument had no data.**
   The ES panel starts in 2020-11 while NQ starts in 2015, so every NQ candidate
   before 2020 was labelled `smt_divergence = 0` (absent) instead of `−1`
   (unknown), which poisoned the meta-labeler features. Now `−1`, and the
   all-NaN-slice warning is gone.

## 2026-11-23 — the meta-labeler has no out-of-sample signal
120 monthly purged walk-forward folds on the NQ candidate set: `auc_test` between
**0.47 and 0.53**, i.e. coin flips. The 0.58 gate therefore passes almost nothing
(0 candidates in most folds). Whatever the edge is, it is **not** in the checklist
score, the SMT flag, the VXN regime or the bar geometry that the feature builder
exposes.

## 2026-11-23 — the fold loop scored one row at a time
`walk_forward` called `ModelScorer.score()` **per candidate**, so a ten-year NQ
run issued 430k single-row LightGBM predictions and took over half an hour in
the scoring phase. `ModelScorer.score_many()` now builds the fold's matrix
once and predicts in a single call; the same run takes **four minutes**.
`score()` is kept and `walk_forward` falls back to it for any scorer that does
not implement the batch API, so custom scorers keep working.
