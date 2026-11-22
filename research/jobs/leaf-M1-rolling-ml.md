# Leaf M1 — The rolling meta-labeling pipeline (implementation)

## Context
Project: `/home/da/桌面/DodgysDD_ifvg` — the DodgysDD iFVG quant system on NautilusTrader.
This is an **implementation leaf**. You own exactly the paths listed below; you may not touch anything else.

**You are a worker, not an orchestrator.** Do not spawn other agents, do not run `herdr`/`herd-dispatch`,
do not edit `.herd-swarm/decisions.md`. If you need a decision that is not recorded there, **stop short of
guessing**: state the question in your deliverable and continue with everything else.

## Required reading (before you write a line)
- `.herd-swarm/decisions.md` — **D2** (the candidate-log schema you must consume and produce),
  **D3** (the model-artefact contract you must emit), **D4** (the honest baseline: the rule engine has
  **no edge**; your ML must be measured against that, not against zero), **D8** (no grade filtering),
  **D9** (cost model), **D10** (untracked research corpus — read it from the main tree, read-only).
- `research/audit/L2_RULES.md` — the rule-fidelity matrix. Your input log comes from a rule engine that
  must satisfy it.
- `research/audit/L4_ROLLING.md` — if it exists when you start, read §C (the rolling ML design). It is the
  specification you are implementing; follow it where it does not contradict D2/D3.
- `research/docs/RULE_SPEC.md` — the feature list and its `[UNSPECIFIED]` items.
- `research/experiments/e1_rule_falsification.py` — the existing rule core and the **one-position-at-a-time**
  accounting convention you must reuse.
- `.field-guide/env.md` and `.field-guide/sources.md` — environment facts (the 3.11 interpreter path, the
  NFS lake, what is installed and what is not).

## Ownership (you may create/modify ONLY these)
```
dodgys_dd_quant/__init__.py
dodgys_dd_quant/ml_pipeline/__init__.py
dodgys_dd_quant/ml_pipeline/features.py
dodgys_dd_quant/ml_pipeline/labels.py
dodgys_dd_quant/ml_pipeline/splits.py
dodgys_dd_quant/ml_pipeline/train_meta_labeler.py
dodgys_dd_quant/ml_pipeline/kaggle_export.py
dodgys_dd_quant/ml_pipeline/README.md
tests/unit/test_splits.py
tests/unit/test_labels.py
```
Do **not** create `dodgys_dd_quant/strategy/**` or `dodgys_dd_quant/backtest/**` — another leaf owns those.
Do not modify `research/**`, `AGENTS.md`, `README.md`, `.herd-swarm/**`, `.field-guide/**`.

## The contract you must implement

### 1. `features.py` — the feature table
A pure function that turns a candidate log (the D2 schema) plus the market series into a feature frame.
- Every feature must be computable **at decision time** from information available at `ts_event`.
  Enforce and **test** this: no feature may use a value dated after `ts_event`.
- The doc's feature list (L146) is: checklist score, SMT flag, vision confidence, VXN level + 1-hour
  change, bars-to-inversion, minutes-from-US-open. The **1-hour VXN change rate is dropped** (the user
  decided so — a daily index cannot produce it). The **vision confidence is optional** (the vision layer
  does not exist): if the column is absent or all-NaN, the pipeline must still run, with the feature
  excluded and recorded in the metadata as excluded.
- State the exact feature list and, for each, whether it is `[FACT]` available in this repo today.
- Provide `build_features(candidates: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame` plus a
  `feature_list` constant and a `assert_no_lookahead(...)` helper that the tests use.

### 2. `labels.py` — the binary meta-label
- label `1` = the trade reached the 2R target, `0` = it hit the stop, and an explicit **unlabelled**
  state for trades still open at the end of the series (do **not** force them to 0 — that biases the base
  rate upward).
- The label must be derived from the **candidate log's own** `stop_price` / `target_price` / `entry_price`
  and the subsequent bars, using the same conventions as the rule engine (stop wins ties).
- Report the **base rate** and the class balance for the data you actually have.
- Provide `build_labels(candidates, bars) -> pd.DataFrame` adding `label` and `r_multiple`.

### 3. `splits.py` — purged walk-forward with embargo
- Rolling folds: **6 months train / 1 month validate / 1 month test**, stepping **1 month** forward.
- **Purge**: no training sample may overlap a validation or test sample in time.
- **Embargo**: a gap of `embargo_minutes` between the end of the training window and the start of the
  validation/test window. The embargo must be **at least the maximum holding period** of the strategy —
  derive that maximum from the label-construction code rather than assuming it, and expose it.
- Provide `make_folds(candidates, train_months=6, valid_months=1, test_months=1, embargo_minutes=...)`
  returning fold objects with explicit train/valid/test index sets.
- **Prove** the invariants with tests: monotonic fold order, no train/test overlap, no train/valid
  overlap, embargo respected, and the fold list is contiguous.

### 4. `train_meta_labeler.py` — training
- LightGBM binary classifier. **LightGBM is not installed** for the 3.11 interpreter. Create a dedicated
  virtualenv (e.g. `.venv-ml/` at the repo root, gitignored) with `uv venv --python 3.11` and install
  `lightgbm` + `pandas` + `pyarrow` + `numpy` there. **Do not** install into the system interpreter.
  If the install fails (no network / disk), the module must still **import cleanly** and raise a clear,
  actionable error only when training is actually requested — and you must say so in your deliverable.
- Early stopping on the **validation** fold; the test fold is touched **once**, at the end.
- Class imbalance: report `positives/n`; use `scale_pos_weight` or an equivalent, and state the choice.
- Decision rule: `P(Win) >= 0.58` (D3's `decision_threshold`), configurable.
- **Emit exactly the D3 artefact**: `artifacts/models/{symbol}/{asof}/meta_label_lgbm.txt` +
  `meta_label_meta.json` + the `walk_forward_index.json` at the run root. Do not invent other names.
- The trainer must **refuse to train on a fold whose label base rate is degenerate** (e.g. zero positives)
  and record that fold as skipped rather than silently producing a useless model.
- Accept the candidate log as input (path argument), and provide a `--dry-run` that validates the
  schemas and reports the fold plan without training.

### 5. `kaggle_export.py` — the Kaggle path
The user wants to know whether this can be trained on Kaggle and rolled there.
- Export the candidate log (and the fold plan) as **Kaggle-Dataset-shaped** artefacts: one parquet per
  fold with a stable schema, plus a `dataset-metadata.json` and a `kernel-metadata.json` template that
  emits **exactly** the D3 artefact layout when the kernel runs.
- Provide a function that produces the **notebook/kernel source** for one fold: it must load the fold's
  parquet, train, and write `meta_label_lgbm.txt` + `meta_label_meta.json` to the D3 paths.
- The kernel must **never see the test fold**. Enforce that in the generated source (assert the test
  index is disjoint from the train/valid sets) and show it in a test.

### 6. `README.md` for the package
How to run the trainer, what the artefact means, how the walk-forward index is consumed, and the
**honest caveats** (the baseline has no edge; the ML must beat that baseline, not zero).

## Tests (`tests/unit/`)
- `test_splits.py`: the purge/embargo/monotonicity invariants, and a synthetic case where a naive split
  would leak.
- `test_labels.py`: label correctness on hand-built cases (hit, stop, tie → stop, still open),
  and the base-rate computation.
- Tests must run with `pytest` and **must not need the lake or the network**.

## Constraints
- Python **3.11**; use the interpreter path from `.field-guide/env.md`. Follow the repo conventions in
  `AGENTS.md` (PEP 8, type hints on public functions, `from __future__ import annotations`).
- **No look-ahead anywhere.** This is the single most important property; prove it with tests.
- Do **not** modify the frozen contracts. If you believe a contract is wrong, say so in your deliverable
  and implement the frozen one anyway.
- Do not fabricate results. If you cannot train because data or dependencies are missing, **say that
  plainly** and deliver the code with the limitation documented.
- Report honestly: if the trained model has no predictive power, say so.

## Deliverable
Your final reply must state: what you built, the exact commands to run it, the test results, whether
LightGBM could actually be installed, and whether you could train a real model on real data — and if
not, exactly what is missing. Name the files you created.
