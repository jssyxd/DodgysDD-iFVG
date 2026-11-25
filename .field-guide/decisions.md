
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

## 2026-11-24 — the vision layer works; VISION_AUDIT's central claim was wrong
`research/analysis/VISION_AUDIT.md` declared the design doc's `IoU > 0.75` gate **unreachable
by construction**, because the detector's boxes were *assumed* to wrap the third candle's body
(which is disjoint from the FVG gap). That premise was **inferred statically from the
checkpoint** — the audit explicitly ran no inference.

Running `ibtsam/nq-fvg-detector` over renders of the real NQ bars (30 windows, 348 boxes):
- **336 / 348 = 96.6 %** of the boxes land on a rule-engine FVG's **middle bar**;
- the class matches the gap's own direction in **96.1 %**;
- the **1-D vertical IoU against the gap interval has a median of 0.9518**, and **94.9 %** of
  the matched boxes clear the doc's 0.75 gate;
- the IoU against the third candle's *body* is indeed ~0 (median 0.0000) — the body's
  disjointness is real, but the boxes are **not** the body: the detector wraps the **gap**.

**The lesson:** the detector is named `nq-fvg-detector` and its classes are
`bullish_fvg`/`bearish_fvg`. A claim of the form "the model cannot achieve X" must be
**measured**, never inferred from a checkpoint's static structure.

## 2026-11-24 — the vision stack lives in its own venv
The uv-managed 3.11 interpreter is **externally managed** (PEP 668): `pip install` into it is
refused, and `--break-system-packages` would risk the runtime env that owns nautilus_trader.
So the vision layer gets its own env, `.venv-vision/` (uv venv --python 3.11), with
`torch`/`torchvision` (CPU wheels), `ultralytics`, `mplfinance`, `opencv-python`, `huggingface_hub`.
The runtime env stays clean; the layer's pure-python parts (the price→pixel transform, the IoU)
import without torch so they can be used from the runtime interpreter.
**There is no GPU on this host** (`nvidia-smi` is absent), so detection runs at **0.45 s per
candidate** on CPU — fine for a filtered subset, hopeless for the full 430 k census.

## 2026-11-25 — the pre-registered forward test FAILED
The frozen configuration (pine + killzone + checklist>=3/known>=4 + RR2) was
pre-registered and committed **before** it ran
(`research/audit/PREREGISTRATION_FORWARD_TEST.md`).

**On the pre-registered criteria it was INCONCLUSIVE**, because the checklist
left only 192/75/115 trades (the criterion demands >= 200). The cause was
mechanical: the **crypto regime index had never been calibrated** —
`DvolRegimeIndex` binned DVOL with the VXN's edges (0/18/28/200), but DVOL's
daily close runs 34-90, so the crypto regime read **81.8% "high", 0% "normal"**
and `vxn_regime_normal` was never true. The checklist collapsed to 3.6% of the
BTC candidates against NQ's 21.1%. The bands are now calibrated to the DVOL
quantiles reproducing the VXN's own occupancy (35.6/48.5/15.9%) =>
`DVOL_REGIME_BINS = (0.0, 45.6, 60.1, 200.0)`.

Re-running the **identical** commands with that fixed gives an adequate sample
and a clear verdict: **FAIL** on all three sub-periods (884/238/644 trades,
net E[R] -0.45/-0.37/-0.47).

**What the test establishes:**
- The **filters do NOT generalise**: on BTCUSDT the frozen config is -0.016 R
  gross while the *plain* arm is +0.038 R. The session + checklist were
  NQ-specific and they actively hurt elsewhere. Same on ES.
- The **rule's gross edge DOES replicate**: BTCUSDT +0.0380 R, t=3.38,
  CI [0.016, 0.060] over 2023-01..2026-11 — the same magnitude as NQ.
- **But not in the only strictly-forward window available** (2025-07-26..
  2026-11-21, after the NQ sample ends): +0.0299 R, t=1.51, CI [-0.009, 0.069]
  — includes zero. The NQ dataset on Hugging Face stops at 2025-07-25, so a
  strictly-forward same-instrument test does not exist yet.
- Net is hopeless on crypto (0.46 R round trip vs a 0.03-0.04 R edge).

**Discipline note:** the configuration was NOT re-tuned after the test, and the
criteria were applied as written. The DVOL fix is labelled post-hoc.
