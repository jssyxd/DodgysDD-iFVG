
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

## 2026-11-25 — the timezone helper silently returned UTC (a real bug, now fixed)
`dodgys_dd_quant/strategy/structure.py`'s `_utc_offsets` built the offset in
**seconds** and then cast it with `.astype("timedelta64[ns]")`, which reads the
integer as *nanoseconds*: the offset was effectively zero, so
`local_minutes_of_day` returned **UTC** minutes, not Eastern.

Consequences: the killzone gate and `session_extremes` (PDH/PDL, session
highs/lows) ran on **UTC** windows, and the D2 `minutes_from_us_open` column
was wrong by 4–5 hours in every log.

Fixed with `day_offsets[inverse] * 1_000_000_000`, verified across a DST
boundary. **Re-measured:** the killzone arm's gross E[R] went
+0.0637 → **+0.0697** (t 3.72 → 3.98) and net −0.0198 → **+0.0116** (now
positive). The ungated arm is byte-identical (51,391 candidates, +0.0317), as
it must be — the gate is not applied there.

`test_the_local_minutes_helper_actually_applies_the_timezone` pins it.

## 2026-11-25 — the runner's hand-built candidate frame lost `label`
`runner.py` built the ML feature frame as
`{name: getattr(c, name, args.symbol) for name in log.D2_COLUMNS}`. But
`label` and `r_multiple` are **derived from `outcome` inside `to_table()`** and
are not attributes of `Candidate`, so the fallback filled them with the
*string* `"NQ"` — any feature touching the label crashed with
`int('NQ')`. Now the runner uses `pd.DataFrame(log.to_table())`, the same
source the trainer reads.

## 2026-11-25 — a fixed embargo cannot make a "recent win-rate" feature causal
The maximum holding time on NQ 1-minute is **15,039 bars** (p99.9 = 788), so any
constant embargo either leaks or discards most of the sample.
`recent_same_side_wr` therefore gates each past candidate on its **own
resolution bar** (`exit_bar < current confirm_bar`), re-derived from the bars
with the engine's first-touch rule (chunked, capped at 20,000 bars; a longer
trade is treated as unresolved, which only *removes* it from the history).

## 2026-11-25 — the herdr worker CLIs are rate-limited
`herd-dispatch assign --kind codex` fails: `codex` is not on PATH. `--kind pi`
starts, but both workers died within ~30 s with
`429 … 已达到 Token Plan 用量上限` (the `minimax-cn` plan is exhausted). The
worktree was left clean, so nothing was lost. When the quota is gone, the
captain implements directly.

## 2026-11-28 — the day-based walk-forward planner (`splits.make_folds_days`)
`dodgys_dd_quant/ml_pipeline/splits.py` gains a second planner:
15 train / 15 validate / 30 test **days**, stepping forward 30 days per fold
(128 folds on the ten-year NQ killzone log, 2015-01-02 → 2025-07-24).  The
monthly plan is byte-identical before and after the change (120 folds, same
windows, same `asof`).

**Surprise 1 — the day scheme is geometrically fine but statistically starved.**
A 15-day training window holds **16–64 rows** (median 42) on
`logs/NQ_1m_pine_kz.parquet` and **83–286** (median 202) on
`logs/NQ_1m_pine.parquet`, against `MIN_TRAIN_ROWS = 200`: **all 128 folds
would be skipped as degenerate** on the killzone log and **57 of 128** on the
unfiltered one.  The monthly 6-month window holds 353–624 / 1383–3076 rows and
every fold trains.  The day scheme therefore needs a longer training window, a
lower `MIN_TRAIN_ROWS`, or a shorter label horizon -- the *geometry* is not
the problem, the *sample size* is.  (Measured with the trainer's own dry run:
`.venv`/`python3.11 -m dodgys_dd_quant.ml_pipeline.train_meta_labeler
--dry-run --slice-days`.)

**Surprise 2 — somebody has to pay for the embargo, and it is the training
window.**  train + valid + gap = 30 days exactly, so the embargo (240 min by
default) cannot be added on top.  It is taken from the **tail of the training
window** (`train_end = valid_start - embargo`), which makes `train_end` the
only boundary off the midnight-UTC grid.  The alternatives were rejected:
shifting the valid/test windows by the embargo would break "a day boundary is
midnight UTC" and would leave `asof` ambiguous (the monthly planner can do it
because month arithmetic preserves the embargo's time-of-day, which is why
the monthly `asof` is `2015-08-01 04:00` and not midnight).

**Surprise 3 — the two schemes use two different `asof` conventions.**  The
monthly `asof` is the **instant** the test window opens (`valid_end ==
test_start`); the day `asof` is the **last calendar day** before the test
window (`test_start - 1 day`), because the model may know the validation
days.  `backtest/walk_forward.py` accepts both (its guard is
`_date_minus_day(test_start) <= asof < test_end`), but the D3 artefact's
`asof` string therefore means different things per scheme -- the metadata
now records which one in `asof_basis`.

**Surprise 4 — the day scheme's training windows do not overlap.**  15-day
windows with a 30-day step are disjoint, where the monthly 6-month/1-month
windows share five sixths of their data.  The *test* windows still tile
exactly (step == test), so the out-of-sample predictions concatenate into one
continuous series exactly as in the monthly scheme.

Note: the day constants (`TRAIN_DAYS`, `VALID_DAYS`, `TEST_DAYS`,
`FOLD_STEP_DAYS`) live in `splits.py`, not in the package constants module
(`ml_pipeline/__init__.py`), which was outside this task's file ownership.

## 2026-11-28 — a 95 %-missing optional feature silently discarded 95 % of the training rows
The trainer builds the training set by dropping every row with a NaN in **any**
used feature. `resolve_feature_list` only excluded a column that was *entirely*
NaN. So `vision_confidence` (94.9 % NaN in `NQ_1m_pine.parquet`, because the
vision layer was run over a 5.9 % stride sample) stayed in the universe and
reduced a 15-day window from **176 candidates to 3 usable rows** — all 128
day-slice folds were skipped with `n_train=3..16`.
Fixed with `MAX_FEATURE_NAN_FRAC = 0.20`: a feature missing more than 20 % of
its rows is excluded (never imputed), and the usable rows went 3 % → **97.9 %**.
**Any "optional" feature must be checked for fill rate, not just for existence.**

## 2026-11-28 — the NFS lake dropped AGAIN (second occurrence)
`mount | grep iflow` was empty and the runner silently read the **7,490-bar**
stale copy underneath the mount point, producing 15 candidates in 3 s instead of
5,573 in 3 min. Re-mounting (`sudo -n mount -t nfs ... fnos2.local:/fs/1000/nfs
~/iflow_lake`) restored the 3,664,241-bar file with no data loss.
**Every batch script must assert the expected row count before running** — a
sweep silently produced 6 wrong arms this way. The guard now used is
`rows < 3_000_000 -> ABORT`.
