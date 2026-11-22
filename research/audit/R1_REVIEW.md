# R1 — Adversarial review of the merged tree (Leaf R1)

**Reviewer:** Leaf R1 (adversarial) · **Date:** 2026-11-22
**Tree reviewed:** `HEAD = cc143ec` ("chore: push via API sequentially") **plus the uncommitted
working-tree modifications** to the ML pipeline (`features.py`, `kaggle_export.py`, `splits.py`,
`train_meta_labeler.py`, `tests/unit/test_labels.py`, `tests/unit/test_splits.py`), to
`dodgys_dd_quant/backtest/walk_forward.py` and `dodgys_dd_quant/backtest/runner.py` (both edited
**after** my first pass, while this review was being written — the reader now probes several
artefact layouts and the runner builds a feature frame; see A.2, A.5, F2, F3), to
`research/audit/L5_ENV.md` (modified *after* my first pass, cited below as the concurrently-edited
design document) and one untracked file (`dodgys_dd_quant/ml_pipeline/README.md`). The tree moved
several times during the review (`33ee063` → `daf02a3` → `cc143ec` + dirty, with the backtest and
ML files edited *while this review was being written*); every number and every finding
below was re-measured on the final state. `.herd-swarm/decisions.md` was **not** modified, and the
only file this review wrote is this one.

**Contracts read:** `.herd-swarm/decisions.md` (D2 §L25, D3 §L63, D4 §L94, D8 §L166, D9 §L175) and
`research/audit/L2_RULES.md`.

**Commands run**

```bash
.venv-ml/bin/python -m pytest tests/unit -q                 # -> 81 passed in ~16 s
                                                             #    (79 passed / 2 skipped in 1.2 s on the
                                                             #     main 3.11 interpreter: no lightgbm)
.venv-ml/bin/python -m dodgys_dd_quant.backtest.runner \
    --symbol BTCUSDT --timeframe 1m --cost-profile binance --slippage-ticks 1 \
    --preset honest --no-write-candidates
.venv-ml/bin/python -m dodgys_dd_quant.backtest.runner --symbol BTCUSDT --preset e1 \
    --portfolio defer --cost-profile binance --slippage-ticks 0 --no-write-candidates
.venv-ml/bin/python -m dodgys_dd_quant.backtest.runner --symbol BTCUSDT --preset doc  ...
.venv-ml/bin/python -m dodgys_dd_quant.backtest.runner --symbol BTCUSDT --preset pine ...
```

---

## A. Contract conformance

### A.1 D2 — the candidate log: **schema exact, semantics wrong in one column**

The 23 D2 columns are implemented column-for-column with the specified dtypes
(`state_machine.py:340-375`; verified on the **full 423,770-row** log written by the runner:
`ts_event int64`, `symbol object`, `side int8`, all prices/risk/fvg/features `float64`,
`fvg_bar1/fvg_bar3/confirm_bar int64`, `bars_to_inversion int32`, `minutes_from_us_open int32`,
`smt_divergence/sweep_detected/vxn_regime/label int8` — an exact match to the D2 table).
`fvg_bar1`/`fvg_bar3` map to the **oldest**/**newest** candle as D2 requires,
`bars_to_inversion = confirm_bar − fvg_bar3` ✓, `risk = |entry − stop|` ✓, `vision_*` are NaN
(D12) ✓, `label ∈ {1,0,−1}` ✓, and `smt_divergence = −1` when no reference instrument exists ✓
(no guessing).

**Deviation (F5, medium).** `minutes_from_us_open` is specified as *"minutes since 09:30 ET on that
day"*. The engine writes **minutes since local midnight**
(`state_machine.py:824`, fed by `minutes[confirm_bar]`). Measured on the real log:

| quantity | value |
|---|---|
| rows where the D2 column ≠ the D2 definition | **423,770 / 423,770 (100 %)** |
| max drift | **869 min** |
| example (10:30 ET) | logged `1341`, defined `471.3` |

`features.py:136` silently **recomputes** the column correctly, so the D2 parquet and the ML
feature of the same name disagree — the log's own `candidate_consistency_report` detects it
(`minutes_from_us_open_mismatches = 423,770`, `max_drift_minutes = 869.0`) but the runner never
calls it and the default is non-strict. The ML feature table is right; the frozen D2 artefact is
wrong.

**Deviation (F6, medium).** D2 defines `label` as `1 = hit target` but says nothing about a
horizon, and **two label definitions now coexist**: the engine's (no horizon — a target hit ten
hours later is `1`) and the ML's (240-bar horizon, otherwise `−1`), and the trainer **overwrites**
the engine's label. Measured on the full 423,770-row log:

| label | `1` | `0` | `−1` (unlabelled) |
|---|---|---|---|
| engine (no horizon) | 145,980 | 277,779 | 11 |
| ML (240-bar horizon) | 143,624 | 274,393 | 5,753 |

Of the **418,017** rows both label, **1,050 disagree (0.25 %)** — 337 engine=1/ML=0 and 713
engine=0/ML=1 (the latter is a trade that hit its stop *after* the 4-hour horizon, which the
engine counts as a loss and the ML leaves out of the base rate entirely). A consumer of the frozen
D2 file cannot know which of the two it holds.

**Minor.** `vxn_regime` uses `−1` for "no index attached" — a value outside D2's `0/1/2`
vocabulary (undocumented sentinel). The D2 **path** (`research/candidates/…`) is not what the
runner writes (`data/candidates/…`); the backtest README states this deviation explicitly ✓ (not a
finding).

### A.2 D3 — the model artefact: **the producer and the consumer do not interoperate** (F2, high)

D3 freezes `artifacts/models/{symbol}/{asof_YYYYMMDD}/` + `meta_label_lgbm.txt` +
`meta_label_meta.json` + `walk_forward_index.json`. The producer
(`train_meta_labeler.py:479,503,508`) and the consumer (`walk_forward.py:136-159`) disagree in
**three independent ways**. Measured against artefacts I trained for real (17 folds, LightGBM 4.7,
`/tmp/artifacts`):

| # | producer writes | consumer expects | measured |
|---|---|---|---|
| a | index at `{run_root}/walk_forward_index.json` (= `artifacts/`) and inside each fold dir | `{models_root}/walk_forward_index.json` or `{models_root}/{symbol}/walk_forward_index.json`; the CLI default `--models-root` is `artifacts/models` | **0 folds read** |
| b | index entries carry `model_dir` (`train_meta_labeler.py:592`) | `dir` / `path` / `directory` (`walk_forward.py:151`) | key never read |
| c | folder name `{asof_compact}` = `20230701` | `{root}/{symbol}/asof_{YYYYMMDD}` (`walk_forward.py:159`), and the producer's **own README** documents `asof_YYYYMMDD` | resolved dir `/tmp/artifacts/BTCUSDT/asof_20230701` **does not exist** |

Consequence, measured on the final working tree: with the **default** `--models-root
artifacts/models` the reader still finds **0 folds** (the index is not where it looks), so the
runner prints *"no walk-forward index found -> rule-only baseline over the whole sample"* and
**the model path never executes** — silently, while still printing a "WALK-FORWARD REPORT".

**Partially fixed by a concurrent edit.** The final working tree adds `model_dir` to the accepted
keys and probes six candidate layouts. Measured on the same 17 real artefacts: with
`--models-root artifacts` the reader now reads **17 folds**, resolves
`/tmp/artifacts/models/BTCUSDT/20230701` and `ModelScorer.available = True` — i.e. **the model
file is now found and can be loaded**. The **index path** is still wrong at the default root
(0 folds), so the runner as shipped still never uses a model. Two consequences: (a) F2 is
partially closed and the remaining hole is the index location; (b) **F1 and F3 become live** —
once a model *is* loaded, the runner will score every fold with `folds[-1]`'s model and the
predict call will raise (A.3, A.5).

The D3 `meta_label_meta.json` itself is **conformant**: all 22 D3 keys are present and correct
(`asof`, windows, `embargo_minutes`, `feature_list`, `decision_threshold`, `n_train/n_valid/n_test`,
`positives_*`, `auc_test`, `accuracy_test`) plus the documented extras.

### A.3 Forward-only enforcement: **the guard is vacuous** (F1, high)

D3: *"a model trained with `asof = T` may only be used to decide trades with `ts_event > T`. The
backtest leaf must assert this."*

`assert_forward_only(fold, ts_event)` (`walk_forward.py:194-206`) compares `ts_event` against
**`fold.asof_ns`** — the *fold's* asof — and **never consults the model artefact's own `asof`**. The
guard therefore proves only "the trade is after this fold's window", not "the model is not from the
future". Two consequences:

1. **The runner scores every fold with the last fold's model**
   (`runner.py:211`: `scorer = ModelScorer(folds[-1], …)`), so a model trained up to 2024-11-01 is
   applied to 2023-08 candidates. `assert_forward_only` fires on the *fold's* asof, which is later
   than the candidate — **no `ForwardOnlyViolation` is raised**.
2. A reviewer supplying the wrong scorer (a later fold's) bypasses the check entirely.

Failing test (evidence, `/tmp/evidence_tests.py::test_E2_…`):

```python
fold = Fold(asof="2023-07-01", …, test_start="2023-08-01", test_end="2023-09-01")
class LateScorer:  # a model trained with asof = 2024-11-01
    available = True
    def score(self, c): return 0.99
rep = walk_forward([cand_2023_08_10], n_bars=100, folds=[fold], scorer=LateScorer())
assert rep.n_approved == 0   # FAILS: the 2024 model approved a 2023 trade
```

The backtest README (§3) claims *"Each fold's model decides only the candidates of its own test
window"* — false in the code. (A concurrent edit *tightened* the rule: `fold.asof_ns` is now the
**start** of the asof day instead of its end — correct and stricter, and it does not close F1.)

**The repo's own design document already specifies the correct rule.** `research/audit/L5_ENV.md`
§D.5 (being edited concurrently) states the consumption rule — *"a fold's model is in force ONLY on
(fold.asof, next_asof)"*, `p = fold.booster.predict(features(rows))`, `keep = p >= 0.58` — and lists
**five assertions** the backtest must make, of which (1) is the forward-only rule, (2) "every
candidate is decided by exactly one fold, the most recent one", (4) "the artefact's own metadata
agrees with the index … feature drift" and (5) "the model never saw the test month"
(`fold.meta["max_ts_read"] < fold.meta["test_start"]`). **None of the five is implemented in the
merged backtest leaf**, and (5) cannot even be written: the D3 artefact carries no `max_ts_read`
field. L5 §D.5 also reads the index from `artifacts/models/{symbol}/walk_forward_index.json` — the
path the *producer* does not write (A.2). The merged code is behind its own design, and the design
and the code disagree with each other.

### A.4 One-position-at-a-time accounting: **correct and D4-faithful**

`simulate_portfolio` (`walk_forward.py:262-284`) opens at most one position, drops signals whose
entry bar falls inside an open position, and keeps each selected row's original outcome (the
portfolio only *selects*). The `defer` arm reproduces the experiment harness's queue. The
`e1`/`defer` arm reproduces D4 **exactly**:

```
mine : n=15 928  win=32.7 %  E[R]=-0.0197  PF=0.971  t=-1.76  CI95=[-0.042,+0.002]  maxL=22
E-1  : n=15 928  win=32.7 %  E[R]=-0.020   PF=0.971  t=-1.76  CI95=[-0.042,+0.002]  maxL=22
```

**Defect (F4, high).** `report.baseline` is *not* the rule-only baseline.
`walk_forward.py:585-588`:

```python
baseline_trades = (portfolio_trades if portfolio_trades is not None
                   else simulate_portfolio(ordered, n_bars))
```

`portfolio_trades` is always assigned at line 573, so the `else` branch (the rule-only population)
is **dead code** and the "BASELINE (rule-only)" line printed by the runner is a *duplicate of the
PORTFOLIO line*. With a model that rejects everything, the baseline is **empty** — D4's "report
against the rule-only baseline" is then impossible. Failing test:
`test_E3_the_baseline_is_the_rule_only_population_not_the_gated_one` → `assert 0 == 5` (F).

### A.5 The model scorer cannot predict (F3, high)

Two independent breakages on the model path:

* `ModelScorer.score` (`walk_forward.py:255`) calls
  `self.model.predict(lgb.Dataset([row], feature_name=…))`. **LightGBM ≥ 4 rejects a `Dataset` for
  prediction**. Confirmed against a real artefact on the final tree: `TypeError: Cannot use
  Dataset instance for prediction, please use raw data instead`. The producer's own README
  documents the correct call (`predict(frame[feature_list])`).
* `walk_forward.py:536` calls `scorer.score(cand)` when `feature_fn is None` — and the runner
  never sets `feature_fn` (`runner.py:209`) — while `ModelScorer.score` expects a **dict**
  Confirmed against a real artefact: `AttributeError: 'Candidate' object has no attribute 'get'`.

So even with F2 fixed, the model path raises instead of scoring.

**Note on the in-flight fix.** A concurrent edit to `runner.py` now builds the feature frame with
`ml_pipeline.features.build_features` and passes a `feature_fn` (closing the *argument* half of
F3b). Two caveats: (i) it does **not** fix the `predict(lgb.Dataset(...))` call (F3a is still on
`walk_forward.py:276`), and (ii) the feature frame is keyed by `ts_event`, but the real log has
**77,929 rows sharing a `ts_event`** (423,770 candidates over 345,841 distinct timestamps — two
FVGs can be confirmed on the same bar) → the dict keeps one row per timestamp and the colliding
candidate is silently scored with the **other** candidate's features. Key the frame by
`(ts_event, side)` or by row index.

---

## B. Look-ahead hunt

### B.1 Rule engine — **no look-ahead found**

| area | verdict |
|---|---|
| FVG detection | 3-candle geometry on closed bars only ✓ |
| inversion confirmation | body-close penetration of the far edge, `confirm_bar ≥ fvg_bar3` ✓ |
| ATR (Wilder) | trailing, past-only ✓ |
| swing/pivot detection | confirmed only after the confirming bar (`test_a_pivot_is_only_usable_after_its_confirming_bar`) ✓ |
| session extremes (PDH/PDL) | previous **completed** calendar day, shifted one day ✓ |
| killzones | window membership of the current bar ✓ |
| SMT | reference bar aligned `asof` (≤ the traded bar), legs from the past ✓ |
| stop placement | window `[fvg_newest … confirm_bar]` (or `+1` in the E-1-matching arm, which is E-1's own semantics) ✓ |
| entry fill | next bar's open ✓ (no same-bar fill) |

The **future-truncation test** (`test_truncating_the_future_does_not_change_the_signals`, presets
`honest`/`pine`/`doc`) is the right instrument and it passes.

### B.2 Regime — **no look-ahead found**

Daily VXN is read with `Close.shift(1).bfill()` and the regime label is derived from the lagged
value; `test_the_regime_never_sees_the_current_day_close` passes. (`Fold.asof` was changed during
the review from `train_end` to `valid_end` — that is *more* conservative and correct: the
early-stopping decision used validation labels, so the model must not be applied inside the
validation window.)

### B.3 Features — **no look-ahead found**

`build_features` merges the market context `asof` (≤ `ts_event`), and the mechanical proof is
`assert_no_lookahead`: the features are re-derived from a series whose future was wrecked and the
pre-perturbation rows must be bit-identical. The **negative control** (a deliberately leaky feature
injected into `checklist_score`) fires ✓. `feature_cutoff_ns ≤ ts_event` is emitted as a
machine-checkable invariant ✓.

### B.4 Labels — **correct by construction**

Only bars **strictly after** `ts_event` can resolve a trade; a bar touching both stop and target
resolves as a **stop** (conservative); an unresolved trade stays `−1` (never silently `0`); a
non-positive risk raises. The geometry comes from the log's own prices, never re-derived. No
look-ahead.

### B.5 Splits — **one reachable leak** (F7, medium)

The purge and the embargo are correct *for the horizon actually used* — except that the horizon is
**not** the one actually used. `splits.py:176-181` derives the embargo from
`max_holding_minutes(bar_interval_minutes)` = **`LABEL_HORIZON_BARS` (240) × interval**, while
`build_labels` uses the caller-supplied `horizon_bars` — and `train_meta_labeler` exposes
`--horizon-bars` (documented in the ML README). The docstring claims the embargo is *"derived from
the label construction … and never assumed here"* — false in this path.

Proof (`--horizon-bars 1000`, one-minute bars, `embargo_minutes=None`):

```
embargo actually applied : 240 min   (label horizon actually used: 1000 bars)
a training sample at 2023-06-30 18:00 IS in train_idx
  its 1000-bar label resolves at 2023-07-01 10:40
  -> inside the validation window (2023-07-01 04:00 .. 2023-08-01 04:00):  True
```

With the default `horizon_bars = 240` the configuration is safe; the hole is reachable from the
CLI. `test_purge_keeps_training_labels_inside_the_training_window` and
`test_a_naive_split_would_leak_but_the_purged_split_does_not` pin the *default* behaviour only.

### B.6 Kaggle export — **no leak**

The generated kernel asserts, before training, that the loaded rows are strictly before
`TEST_START_NS`, that no row falls inside the test window, that train/valid are disjoint, that no
train row falls inside the validation window, and that the row count matches. Strong.

---

## C. Test suite

`pytest tests/unit -q` → **81 passed in 1.40 s** on `.venv-ml` (LightGBM 4.7 installed) and
**79 passed, 2 skipped in 1.19 s** on the project's *main* 3.11 interpreter, which has no
LightGBM — both lightgbm-dependent tests are `importorskip`ped there
(`tests/unit/test_splits.py:256,293`). Fully offline, deterministic, synthetic data only (no lake,
no network, no clock dependence) ✓.

**What the tests genuinely pin** (good): the FVG geometry; the inversion window bounds; the
one-position portfolio accounting; the cost model ladder; the purge/embargo; the label conventions
(stop wins, `−1` stays `−1`, non-positive risk raises); the regime lag; the pivot confirmation lag;
the future-truncation invariance of the signals and of the features; the leaky-feature negative
control; the D2 column tuple and dtypes; the D4 "no census t-statistic" guard.

**Gaps (in priority order)**

1. **The D3 producer has exactly one test, and it pins the deviation.** The uncommitted working-tree
   changes add `test_trainer_refuses_a_degenerate_fold_and_records_it_as_skipped`
   (`tests/unit/test_splits.py:291`), the only test that touches `train_meta_labeler.py`. It
   covers the degenerate-fold skip path — and it *asserts*
   `not (run/"models"/"TEST"/{asof}).exists()` and `(run/"walk_forward_index.json").exists()`,
   i.e. it **pins the directory naming and the index path that contradict D3 and that the reader
   cannot consume** (A.2). It also cannot run on the main interpreter (`importorskip`). The
   producer's contract is therefore *locked in* in the wrong shape.
2. **No test exercises `backtest/runner.py`** — the CLI, the path resolution, the model-root
   discovery, the report assembly are untested; A.2/F3 would have been caught by a 10-line
   round-trip test ("train → read the index → find the model file").
3. `test_walk_forward_index_is_read_in_order` builds a **hand-made** index using the key `dir` —
   a shape the producer never writes — so it pins a contract that does not exist in production.
4. `test_checklist_is_reported_but_never_filters` compares two runs of the *same* configuration
   (tautological) instead of comparing the population with the checklist gate on vs off.
5. `test_candidate_log_has_the_frozen_d2_schema` checks names and a few dtypes but not the
   **semantics** of `minutes_from_us_open` or `label` (F5/F6).
6. No test covers the embargo/horizon mismatch (F7) or the model-asof forward-only rule (F1).

---

## D. Does it run end to end? — **Yes, on real data**

Real BTCUSDT 1-minute, **2,046,240 bars**, 2023-01-01 → 2026-11-21, from the governed lake
partition (the local checkout copy; the NFS lake copy is byte-identical — same 58,262,259 bytes,
same mtime). Cost profile `binance`, 1 tick of slippage; "gross" = before costs.

| arm | candidates | trades (1 at a time) | win % | **E[R] gross** | **E[R] net** | **PF gross** | PF net | t | 95 % CI | mean cost |
|---|---|---|---|---|---|---|---|---|---|---|
| `e1` / defer — **D4 accounting** | 423,770 | 15,929 | 32.7 | **−0.0197** | −0.4317 | **0.971** | 0.549 | −1.76 | [−0.042, +0.002] | 0.412 R |
| `honest` / drop | 423,770 | 42,093 | 33.6 | **+0.0087** | −0.8208 | **1.013** | 0.340 | +1.26 | [−0.005, +0.022] | 0.830 R |
| `doc` / drop (ATR + sweep + killzone) | 14,743 | 6,804 | 33.8 | **+0.0147** | −0.7907 | **1.022** | 0.350 | +0.85 | [−0.019, +0.048] | 0.805 R |
| `pine` / drop (reference leg tracker) | 5,029 | 4,951 | 19.8 | **−0.4062** | −1.9484 | **0.494** | 0.075 | −23.91 | [−0.439, −0.373] | 1.542 R |

Break-even round-trip cost: 0.009 R (`honest`), 0.015 R (`doc`) — against a **measured** cost of
0.41–1.54 R per trade. DSR p-value 0.799 (32 trials) for `honest`; Sharpe (per trade) 0.0104.

**Comparison with the D4 baseline.** D4 measures one-position-at-a-time expectancy in
**[−0.024 R, +0.014 R]** with **PF ≤ 1.051**, every CI including zero. The `honest` arm's gross
E[R] = **+0.0087 R** sits *inside* that interval and its PF **1.013 < 1.051** → it **does not beat
the baseline**; it is the baseline re-measured with a different portfolio policy (drop vs defer ⇒
42,093 vs 15,929 trades, so not even the same population). The `doc` arm's +0.0147 R is the top of
D4's range with a CI that includes zero, and is **−0.79 R net**. No arm has a gross PF above 1.03
and no arm has a net PF above 0.55 — the doc's gate is **PF > 1.25 after costs**. The edge
(≤ 0.015 R gross) is **20–100× smaller than the cost of trading it** (0.41–1.54 R).

**The ML layer, run for real.** I trained 17 walk-forward folds (2023-01 → 2024-12, 213,509
candidates, LightGBM 4.7 in `.venv-ml`): **AUC_test 0.496 – 0.521, mean 0.506** — no edge, exactly
consistent with D4. The artefacts are well-formed (D3 keys complete) but **unusable by the backtest**
(A.2).

---

## E. Honesty audit

| claim | verdict |
|---|---|
| "The `e1`/`defer` arm is bit-identical to E-1" | **verified independently** — n, win %, E[R], PF, t, CI, max-loss streak all match `E1_RESULTS.md` §3.0 |
| "No arm beats the baseline; the cost dominates and it is structural" | **verified** — reproduced to 4 decimals |
| "the `pine` arm is the author's *intent*, not the replica's behaviour" (README §6.6) | **honest and correctly caveated** — the `ta.lowestbars` v5/v6 semantics are flagged as an open research question, and the `pine` numbers are labelled accordingly |
| "`vision_iou`/`vision_confidence` are always NaN (D12)" | **true** ✓ |
| "`checklist_score` is reported, never used as a filter (D8)" | **true** ✓ — no grade filter anywhere in the tree |
| "The reader is deliberately tolerant … the index format is *not* frozen" (README §6.1) | **honest, but the tolerance does not cover the producer's actual output** (A.2) — the known gap was documented without noticing that it is already broken |
| "The data is resolved from the **NFS lake** … and falls back to the local checkout" (README §1) | **false in practice** — `LAKE_ROOTS` uses `Path("~/iflow_lake/…")` and `Path.is_dir()` does **not** expand `~` (measured `False`), so the authoritative NFS lake is **never** used for market data; the run always takes the local checkout. (PyArrow *does* expand `~`, so the VXN/DVOL paths do hit the NFS mount — the market data does not.) |
| "The census agrees too: 423 759 closed concurrent trades, exactly E-1's number" (README §5.1) | **imprecise** — the engine's census is **423,770** candidates and it implements **no** concurrent arm; the sentence compares a candidate count with E-1's closed-trade count |
| "`lightgbm` is not installed for the 3.11 interpreter, so the model scoring path could not be executed end-to-end" (README §6.3) | **now outdated and misleading** — the model path *can* be exercised (`.venv-ml` has LightGBM 4.7) and **it fails** (A.2/F3). "LightGBM is unavailable" and "the model path is broken" are different problems and the README currently hides the second behind the first |
| ML README: "writes **exactly** the D3 layout: `artifacts/models/{symbol}/{asof_YYYYMMDD}/`" | **false** — the code writes `{asof_compact}` = `20230701` (no `asof_` prefix) |
| ML README: "call `predict(frame[feature_list])`" | **contradicted by the consumer**, which calls `predict(lgb.Dataset(...))` (F3) |
| ML README: "the embargo (default: the maximum holding period)" | **imprecise** — the default is the *constant* 240-bar horizon, not the horizon actually used (F7) |
| trainer CLI: `E[R] base 0.1299  E[R] gated 0.4286` (fold 0 of my run) | **D4 trap, un-caveated on the terminal** — these are **census** expectancies over 10,684 (resp. 63) *simultaneous* positions. `meta_label_meta.json` carries an `accounting_note`; the CLI print-out does **not**. D4 says the census t = 15.28 "is an artefact and is not a result" — the same figure without the note is exactly what will be quoted |
| `REGIME_PARAMETERS` / `regime_parameters()` / `MARKET_PARAMS.session_windows` / `MARKET_PARAMS.smt_reference` / `is_extreme` | **implemented but never called** — the doc's regime-driven RR (1.5 / 2.5 / 3) and ATR floor, and the per-market session windows, are inert; every symbol uses the NY killzones and the SMT reference must be passed by hand |

**Losing setups / D8 / thresholds.** No losing setup is erased: the D2 log keeps every candidate
including `label = −1` (INV4 ✓, and `hideLosing` appears nowhere in the tree). The grade is
**reported, never filtered on** (D8 ✓). `DECISION_THRESHOLD = 0.58` is applied in the walk-forward
gate ✓. The `0.58` gate is *unreachable in practice* in the current run (A.2) — but note the
threshold is only ever applied to `P(Win)` from a model that cannot load. The cost model lives
only in `cost_model.py` (D9 ✓) and every report prints the break-even cost in R ✓. The D9 ladder
is correct ($9.50 / $14.50 / $19.50 for NQ with one tick of crossing already inside) ✓. One
defect: `checklist_score` is the **unweighted** count of the five flags, while `constants.py`
defines a *weighted* rubric (SMT = 2) used by the `grade` property — the D2 column and the grade
therefore disagree by construction (D8 says "as a score", so this is defensible, but it is not the
same number).

---

## F. Findings, most severe first

| # | sev | finding | evidence |
|---|---|---|---|
| **F1** | **high** | Forward-only enforcement is **vacuous**: `assert_forward_only` checks the *fold's* asof, never the *model artefact's* asof, and the runner scores **every** fold with `folds[-1]`'s model → a model trained 16 months later decides 2023 trades with no violation. The README's "each fold's model decides only its own test window" is false. The repo's own design (`L5_ENV.md` §D.5) already specifies the correct rule and five assertions — none implemented. **Live**: as soon as F2's index path is fixed, the wrong model is actually used. | `walk_forward.py:194-206,535`; `runner.py:211`; `L5_ENV.md` §D.5; failing test `test_E2_…` |
| **F2** | **high** *(partially fixed concurrently)* | The D3 producer and consumer **cannot interoperate** as shipped: the index is written where the reader does not look (**0 folds read** at the default `--models-root`), the entries use `model_dir`, the folder name lacks the `asof_` prefix → the ML layer has **never** run inside the backtest, silently. A concurrent edit to the reader now probes six layouts and **does** find the model when the index is found; the **index path** is still wrong, and the only trainer test **pins** the non-conformant shape. | `train_meta_labeler.py:479,503,508,592` vs `walk_forward.py:136-180`; `tests/unit/test_splits.py:318,320`; measured with 17 real artefacts |
| **F3** | **high** | The model path **cannot predict**: `predict(lgb.Dataset(...))` raises on LightGBM ≥ 4 (still on `walk_forward.py:276`), and `scorer.score(candidate)` was called with a `Candidate` where a dict is expected (the argument half is closed by an in-flight `runner.py` edit; the `predict` half is not). The in-flight fix also keys features by `ts_event`, but **77,929 rows share a `ts_event`** → colliding candidates would be scored with each other's features. | `walk_forward.py:276,536`; `runner.py` (dirty); confirmed against a real artefact |
| **F4** | **high** | The "rule-only baseline" is **not** the rule-only population: `baseline_trades` is always the (already gated) portfolio; the rule-only branch is dead code → with a rejecting model the baseline is empty → D4's comparison is impossible. | `walk_forward.py:573,585-588`; failing test `test_E3_…` |
| **F5** | medium | D2's `minutes_from_us_open` is written as minutes since **midnight**, not since 09:30 ET → **423,770 / 423,770 rows wrong** (max drift 869 min); the ML feature of the same name is recomputed correctly, so the log and the feature disagree. | `state_machine.py:824`; measured on the full log |
| **F6** | medium | Two `label` definitions coexist (engine: no horizon; ML: 240-bar horizon) and the trainer overwrites the D2 one → **1,050 of 418,017** jointly-labelled rows disagree (0.25 %), and 5,753 rows are unlabelled under one definition and labelled under the other. | measured on the full log |
| **F7** | medium | The purge/embargo horizon is the **constant** 240 bars, not the horizon used to build the labels; `--horizon-bars 1000` leaves a training label resolving inside the validation window. The docstring's "never assumed here" is false. | `splits.py:176-181`; `labels.py:59-65`; proof in `/tmp/evidence3.py` |
| **F8** | medium | The trainer's CLI prints **census** expectancies (`E[R] base 0.1299`, `E[R] gated 0.4286`) with no D4 caveat — the exact artefact D4 forbids quoting. The note exists only in `meta_label_meta.json`. | `train_meta_labeler.py:719` vs `:588` |
| **F9** | low | `LAKE_ROOTS` never expands `~` → the "authoritative NFS lake" is never used for market data; the README says otherwise. | `runner.py` `LAKE_ROOTS`; measured `Path("~/iflow_lake/…").is_dir() == False` |
| **F10** | low | `REGIME_PARAMETERS`, `MARKET_PARAMS.session_windows`, `MARKET_PARAMS.smt_reference`, `is_extreme` are implemented and never called — the doc's regime-driven RR/ATR floor and per-market sessions are inert. | grep over `dodgys_dd_quant/` |
| **F11** | low | `checklist_score` (unweighted count) ≠ the weighted rubric used by `grade`; `vxn_regime = −1` is outside D2's vocabulary; the census count is 423,770 vs E-1's 423,759 and the README calls them "exactly E-1's number". | `state_machine.py`, `constants.py`, README §5.1 |
| **F12** | low | The producer/consumer/README trio documents the artefact layout, the predict API and the embargo default — **all three** disagree with the code. | ML README vs `train_meta_labeler.py` / `walk_forward.py` |

**Not findings** (checked and clean): the rule engine's look-ahead surface; the regime lag; the
feature look-ahead proof and its negative control; the label construction; the Kaggle kernel's
test-window guarantees; the one-position-at-a-time accounting; the D9 cost ladder; INV4 (no losing
setup erased); D8 (no grade filtering); the E-1 reproduction.

---

## G. Verdict

```
VERDICT:          CONDITIONAL FAIL
                  The rule engine, the D2/D3 artefact schemas, the cost model and the
                  one-position-at-a-time accounting PASS and reproduce D4 exactly.
                  The ML -> backtest path FAILS: as shipped it has never executed on real
                  data, and its forward-only guard cannot fail. (A concurrent edit has
                  already closed half of F2 — the reader now finds the model file — which
                  makes F1 and F3 LIVE rather than dormant.)

HIGHEST-SEVERITY FINDING (F1, high):
                  Forward-only enforcement is vacuous. `assert_forward_only` compares the
                  trade time against the FOLD's asof, never against the MODEL ARTEFACT's
                  own `asof`, and `runner.py:211` scores every fold with `folds[-1]`'s
                  model. A model trained with asof=2024-11-01 therefore decides 2023-08
                  trades without raising ForwardOnlyViolation, while D3 requires
                  "a model trained with asof = T may only be used to decide trades with
                  ts_event > T". Proof: /tmp/evidence_tests.py::test_E2_... (fails on the
                  final tree). Fix: assert against the scorer/model's asof (from
                  meta_label_meta.json) and score each fold with ITS OWN model.

SECOND (F3, high): the model path cannot predict -- predict(lgb.Dataset(...)) raises
                TypeError on LightGBM >= 4, and the walk-forward passes a Candidate where
                a feature dict is expected (AttributeError). Both confirmed against a
                real artefact.
THIRD  (F4, high): the "rule-only baseline" is the gated portfolio; the rule-only
                branch in walk_forward.py:585-588 is dead code, so D4's "report against
                the rule-only baseline" cannot be done (test_E3_... fails).

LOOK-AHEAD VERDICT: no look-ahead found in the rule engine, the regime, the features,
                  the labels or the Kaggle kernel. One reachable leak: the purge/embargo
                  horizon is the constant 240 bars, not the horizon the labels were built
                  with (F7) -- safe at the default, reachable via --horizon-bars.

E2E NUMBERS (real BTCUSDT 1m, 2,046,240 bars, 2023-01-01 -> 2026-11-21, binance, 1 tick):
  honest/drop : 423,770 cands | 42,093 trades | E[R] gross +0.0087 | E[R] net -0.8208
                | PF gross 1.013 | PF net 0.340 | t +1.26 | CI95 [-0.005, +0.022]
                | mean cost 0.830 R | break-even cost 0.009 R | DSR p 0.799 (32 trials)
  e1/defer (D4 accounting): 423,770 cands | 15,929 trades | E[R] -0.0197 | PF 0.971
                | t -1.76 | CI95 [-0.042, +0.002]  == E-1 exactly (n=15,928)
  doc/drop    : 14,743 cands | 6,804 trades | E[R] gross +0.0147 | net -0.7907 | PF 1.022
  pine/drop   : 5,029 cands | 4,951 trades | E[R] gross -0.4062 | net -1.9484 | PF 0.494
  D4 baseline : E[R] in [-0.024, +0.014], PF <= 1.051, every CI includes zero.
  VERDICT vs D4: DOES NOT BEAT THE BASELINE. The gross edge (<= 0.015 R) is 20-100x
                smaller than the measured round-trip cost (0.41-1.54 R); net PF <= 0.55
                everywhere, against the doc's PF > 1.25 gate. ML (17 real folds,
                AUC_test 0.496-0.521) shows no edge either.

NEXT ACTION: fix F1/F3/F4 and the remaining half of F2 before any ML result is reported
                -- the model path must load the RIGHT model per fold, predict, and be
                audited against the rule-only baseline.
```

**Evidence left behind** (scratch only, under `/tmp`): `evidence_tests.py` (four failing tests
E1–E4), `evidence2.py` / `evidence3.py` (the D2 column and the embargo proofs), `drop_probe.py`
(0 of 423,770 candidates dropped for want of a stop), `pine_run.log`.
