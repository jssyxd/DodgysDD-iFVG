# `dodgys_dd_quant.ml_pipeline` — the rolling meta-labeling pipeline

Leaf **M1**.  This package turns the rule engine's candidate log into a
walk-forward-trained binary meta-labeler and writes the model artefact that the
backtest leaf consumes.

```
candidate log (D2)  ──►  features.py  ──►  labels.py  ──►  splits.py  ──►  train_meta_labeler.py
                                            (label + R)     (purged folds)        (LightGBM)
                                                                                        │
                                                        kaggle_export.py  ◄────────────┘
```

---

## 1. What the artefact means

The trainer writes **exactly** the D3 layout:

```
artifacts/models/{symbol}/{asof_YYYYMMDD}/
    meta_label_lgbm.txt       LightGBM native text format
    meta_label_meta.json      the metadata (D3 keys + the D12 exclusions)
    walk_forward_index.json   the ordered list of fold directories
artifacts/walk_forward_index.json    the same index at the run root
```

* **`meta_label_lgbm.txt`** — a `lgb.Booster` saved with `save_model()`.  Load it
  with `lgb.Booster(model_file=...)` and call `predict(frame[feature_list])`.
  The probability it returns is `P(Win)` for the meta-label.
* **`meta_label_meta.json`** — every D3 key is present:
  `symbol, timeframe, asof, train_start, train_end, valid_start, valid_end,
  test_start, test_end, embargo_minutes, feature_list, decision_threshold,
  n_train, n_valid, n_test, positives_train, positives_test, auc_test,
  accuracy_test`, plus the informative extras `excluded_features`,
  `scale_pos_weight`, `best_iteration`, `base_rate_*`, `pass_*`,
  `expectancy_r_test`, `feature_nan_fraction` and the `accounting_note`.
* **`walk_forward_index.json`** — the ordered folds.  Each entry carries the
  window boundaries, the index-set sizes, the model directory, the status
  (`trained` / `skipped`) and the out-of-sample metrics.

**Forward-only rule (D3).**  A model trained with `asof = T` may only be used
to decide trades with `ts_event > T`.  `asof` is the **end of the validation
window** of its fold (= the start of its test window), *not* the end of the
training window: the early-stopping decision was taken on the validation
labels, so the model must not be applied to trades inside that window.  With
this choice the folds tile exactly -- fold *i*'s model is in force over fold
*i*'s test window, fold *i+1*'s over the next one.  The meta json spells all
the windows out (and repeats the rule in `asof_basis`) so the backtest leaf
can assert it without guessing.

**How the backtest leaf should consume the index.**  For a live/paper run at
time `t`, pick the fold whose `asof` is the **latest** value `<= t`; that
model was in force from `asof` until the next fold's `asof`.  A fold with
`status == "skipped"` has **no** model directory and must fall back to the
previous fold's model (or to "take no trade" if there is none).

**Decision rule.**  Take the trade iff `P(Win) >= decision_threshold`
(default `0.58`, D3).  The threshold is stored in the meta json, so the
consumer never hard-codes it.

---

## 2. How to run it

### 2.1 The interpreter

LightGBM is **not** installed in the project's main 3.11 interpreter.  Use the
dedicated virtualenv (it is git-ignored through `.git/info/exclude`):

```bash
cd /home/da/桌面/DodgysDD_ifvg
uv venv --python 3.11 .venv-ml
VIRTUAL_ENV=.venv-ml uv pip install lightgbm pandas pyarrow numpy pytest
```

The package imports **without** LightGBM; the missing dependency is only
reported when a training run is actually requested
(`LightGBMUnavailable`, exit code 2).

### 2.2 Train

```bash
cd /home/da/桌面/DodgysDD_ifvg
.venv-ml/bin/python -m dodgys_dd_quant.ml_pipeline.train_meta_labeler \
    --candidates research/candidates/BTCUSDT_1m.parquet \
    --bars       research/candidates/BTCUSDT_1m_bars.parquet \
    --symbol BTCUSDT --timeframe 1m --run-root artifacts
```

Useful flags:

| flag | meaning |
|---|---|
| `--dry-run` | validate the schemas and print the fold plan; **trains nothing** |
| `--decision-threshold` | the D3 gate (default `0.58`) |
| `--horizon-bars` | the label horizon in bars (default `240` = 4 h on 1-minute bars) |
| `--embargo-minutes` | the walk-forward embargo (default: the maximum holding period) |
| `--extra-features` | add the causal ATR/volume context features (off by default) |
| `--run-root` | where the artefacts go (default `artifacts`) |

`--bars` accepts either an explicit `ts_event` (int64 **ns**) or a governed-lake
`timestamp` (int64 **ms**); the loader converts.

### 2.3 Tests

```bash
cd /home/da/桌面/DodgysDD_ifvg
.venv-ml/bin/python -m pytest tests/unit -q
```

The tests need neither the lake nor the network.

---

## 3. The four modules

### 3.1 `features.py` — the feature table

`build_features(candidates, bars, *, extra_features=False, strict=False)`
returns the candidate log with the feature columns added and a
`feature_cutoff_ns` column (the information cut-off; `feature_cutoff_ns <=
ts_event` for every row — the look-ahead invariant in machine-checkable form).

The **declared feature universe** is the discussion's L146 list, with two
documented departures:

| feature | source | status |
|---|---|---|
| `checklist_score` | D2 `checklist_score` | **[FACT]** available; **reported, never filtered on** (D8) |
| `smt_divergence` | D2 `smt_divergence` | **[FACT]** available; `-1` = unknown (no reference instrument) |
| `vxn_level` | D2 `vxn_known` (the **lagged** VXN close) | **[FACT]** available |
| `vxn_regime` | D2 `vxn_regime`, recomputed here from the lagged level | **[FACT]** available |
| `bars_to_inversion` | D2 `bars_to_inversion` | **[FACT]** available |
| `minutes_from_us_open` | D2 `minutes_from_us_open`, recomputed here from `ts_event` | **[FACT]** available |
| `vision_confidence` | D2 `vision_confidence` | **[ABSENT]** — the vision layer does not exist (D12) |
| ~~VXN 1-hour change rate~~ | — | **dropped**: the lake only has *daily* VXN, so a 1-hour change rate cannot be computed without fabricating it (`RULE_SPEC` A18 (b)) |
| `atr14`, `risk_atr`, `gap_atr`, `volume_zscore_60` | the market series | **[DERIVED]** causal extras, **off by default** (`--extra-features`) |

A feature is **excluded** when its column is missing or entirely NaN (the
vision columns today, `checklist_score` for a log produced without a checklist,
`vxn_level` for a crypto log).  Exclusions are never imputed silently — they
are recorded in `meta_label_meta.json` under `excluded_features` (D12) and in
the walk-forward index.

Two values are **recomputed** here rather than trusted:

* `minutes_from_us_open` — the **signed** minutes from the same day's 09:30
  `America/New_York` open (`+90` = 11:00 ET, `-60` = 08:30 ET).  The sign is
  kept: for a 24/7 market a pre-open candidate is *before* the open.
* `vxn_regime` — binned from the **lagged** level with the corrected bins of
  `RULE_SPEC` §1.9 (`<18 → 0`, `[18,28] → 1`, `>28 → 2`); the discussion's
  literal `pd.cut(bins=[0,18,28,200])` is right-closed and disagrees at 18/28
  (`I05`).

`candidate_consistency_report(candidates)` reports how many rows of the log
disagree with those definitions; `strict=True` turns the disagreement into a
`ValueError` instead.

**No look-ahead.**  `assert_no_lookahead(candidates, features, bars=..., perturb_from=...)`
re-derives the features from a market series whose *future* has been wrecked
and requires the pre-perturbation rows to be bit-identical.  A feature that
reads a future price changes, and the assertion fires.  The negative control
(lEAKY feature injected into `checklist_score`) is in `tests/unit/test_labels.py`.

### 3.2 `labels.py` — the binary meta-label

`build_labels(candidates, bars, *, horizon_bars=None)` adds `label`,
`r_multiple`, `bars_held` and `exit_ts_event`.

* `label = 1` — the trade reached its **target** (phase 1: the 2R price).
* `label = 0` — the trade hit its **stop**.
* `label = -1` — **unlabelled**: neither within the horizon (or the series
  ended first).  A still-open trade is *not* forced to `0`; doing so would
  rewrite the base rate.  Unlabelled rows stay in the log (**INV4**) and are
  dropped only from the training matrix.

Conventions (identical to the rule engine's):

* the entry happens at the close of the confirmation bar, so **only bars
  strictly after `ts_event`** can resolve the trade;
* a bar that touches both the stop and the target resolves as a **stop**;
* the trade geometry comes from the **log's own** `entry_price` / `stop_price` /
  `target_price` / `risk` — the pipeline never re-derives it;
* a non-positive risk, or a target/stop on the wrong side of the entry, is a
  data-integrity violation and **raises**.

`summarize_labels(frame)` returns the class balance and the base rate
(`positives / labelled`).

### 3.3 `splits.py` — purged walk-forward with an embargo

`make_folds(candidates, *, train_months=6, valid_months=1, test_months=1,
step_months=1, embargo_minutes=None, bar_interval_minutes=1)` returns a list
of `Fold` objects with **explicit positional index sets** into the frame it was
given.

* **Purge.**  A sample owns the time span `[ts_event, ts_event + horizon]`
  (its label is only known once the trade resolves).  A training sample is kept
  only when `ts_event + horizon <= train_end`, so no training sample overlaps
  the validation or the test window.  The same rule trims the **validation**
  tail, because early stopping on the validation fold is a model-selection
  decision and a validation label resolved with test-window bars would leak.
* **Embargo.**  `valid_start = train_end + embargo`.  The embargo must be at
  least the **maximum holding period**, which is *derived* from the label
  construction (`labels.max_holding_minutes()` = `LABEL_HORIZON_BARS × bar
  interval`) and never assumed; a smaller embargo is **rejected** with a
  `ValueError`.
* **Contiguity.**  With a one-month step and a one-month test window the test
  windows tile: `folds[i+1].test_start == folds[i].test_end`.  The
  out-of-sample predictions can therefore be concatenated into one continuous
  series.

### 3.4 `train_meta_labeler.py` — training

* LightGBM binary classifier, `objective=binary`, `metric=auc`.
* **Early stopping on the validation fold**; the **test fold is scored once**,
  at the very end of the fold's life.
* **Class imbalance:** `scale_pos_weight = n_neg / n_pos` (the standard
  choice).  It is written into the meta json.  Note that it *distorts* the
  probability scale — which is one reason the 0.58 gate fires so rarely on a
  signal-free rule engine.
* **Degenerate folds are refused**, not silently trained: a fold with fewer
  than `MIN_TRAIN_ROWS` (200) rows, fewer than `MIN_POSITIVES_TRAIN` (20)
  positives in the training window, an empty validation window, or fewer than
  `MIN_POSITIVES_VALID` (5) validation positives is recorded in the index with
  `status = "skipped"` and a `reason`, and **no model directory is created**.
* **D8:** `checklist_score` is a feature; nothing is filtered on a grade.
* **D9:** no costs are applied here — they live in the backtest config.

### 3.5 `kaggle_export.py` — the Kaggle path

`export_kaggle_dataset(frame, folds, out_dir=..., feature_columns=[...])` writes

```
fold_000.parquet      ts_event | symbol | split ("train"/"valid") | <features> | label | r_multiple
fold_001.parquet
...
fold_kernel_000.py   the generated kernel source for that fold
dataset-metadata.json
kernel-metadata.json
fold_plan.json
```

**The test fold is never exported.**  The kernel source *asserts*, before it
trains, that the data it loaded contains no row inside the test window and
that the train and validation row sets are disjoint; the fold plan records the
test window so the fold can be scored locally afterwards.  The generated
kernel writes exactly the D3 artefact layout under
`/kaggle/working/artifacts/models/{symbol}/{asof}/`.

Kaggle notebooks ship LightGBM, so the kernel needs no wheel installation; the
dataset is uploaded with the Kaggle CLI (`kaggle datasets create`,
`kaggle kernels push`).

---

## 4. The honest caveats

1. **The rule engine has no edge (D4).**  The measured baseline on the real
   BTCUSDT 1-minute census is a **base win rate of 0.337** and a **gross mean of
   +0.012 R per setup**, with every confidence interval covering zero.  A
   meta-labeler must be measured **against that baseline**, not against zero.
   A model that turns +0.012 R into +0.02 R has found nothing; a model that
   turns it into −0.02 R has destroyed the baseline.
2. **The reported `expectancy_r_test` / `pass_expectancy_r` are computed on the
   per-fold *census* of candidates**, not on the one-position-at-a-time
   accounting.  The census t-statistic is inflated by correlated trades (D4's
   trap).  The authoritative expectancy comparison — one position at a time,
   with D9's costs — is the backtest leaf's job.
3. **The 0.58 gate is a *probability* threshold on a `scale_pos_weight`-fitted
   model.**  Such a model is not calibrated to the base rate, so 0.58 is not
   "58 % chance of winning" in any absolute sense.  It is the frozen decision
   rule of D3 and is applied verbatim; treat it as a *ranking* threshold.
4. **The measured predictive power of the meta-labeler on the real data is, at
   best, marginal** (see the numbers in the leaf deliverable: pooled
   out-of-sample AUC 0.5035 with a monthly block-bootstrap CI of
   [0.4991, 0.5076] for the doc's feature list).  The CI covers 0.5.  The
   honest conclusion is **"no measurable predictive power"**, not "a weak
   edge".
5. **The demo numbers were produced with the E-1 falsification harness**, not
   with the L2-conformant engine (which does not exist yet, D13), and on
   BTCUSDT rather than NQ.  When the real engine lands, the candidate
   population changes and every number has to be re-measured.
6. **The vision layer is not on the critical path (D12).**  Without it the
   pipeline still runs; the feature is excluded and the exclusion is recorded.

---

## 5. Interoperability notes for the other leaves

* The candidate log is the **D2** schema.  The trainer consumes
  `ts_event` (int64 **ns**), `side`, `entry_price`, `stop_price`,
  `target_price`, `risk`; everything else is optional but is used when present.
* `minutes_from_us_open` and `vxn_regime` are **recomputed** by
  `features.py` from `ts_event` / `vxn_known`.  If the rule engine uses a
  different definition, the recomputed value wins and the disagreement is
  counted in `candidate_consistency`.
* `label` and `r_multiple` in the D2 schema are **produced by this package**.
  If the log already carries them, they are recomputed and overwritten.
* A candidate that is still open at the end of the series stays in the log with
  `label = -1`; **never** delete it (**INV4**).
