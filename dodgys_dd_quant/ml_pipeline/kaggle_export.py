"""Export the walk-forward folds as a Kaggle dataset + kernel.

The user asked whether this pipeline can be trained **on Kaggle and rolled
there**.  It can: the training is a single LightGBM fit per fold, and a Kaggle
kernel has LightGBM pre-installed.

The dataset
-----------
One Parquet per fold, with a stable schema::

    fold_000.parquet   ts_event | split ("train"/"valid") | <features> | label | r_multiple
    fold_001.parquet
    ...

**The test fold is never exported.**  A kernel that could read the test rows
would be a leak even if it did not use them, so the export physically omits
them and the generated kernel *asserts* that the data it loaded contains no row
inside the test window.  The fold plan (the test window boundaries) is shipped
separately so the fold can be scored locally afterwards.

The kernel
----------
``fold_kernel_{i:03d}.py`` loads the fold's Parquet, trains with early stopping
on the validation split, and writes exactly the D3 artefact::

    /kaggle/working/artifacts/models/{symbol}/{asof}/meta_label_lgbm.txt
    /kaggle/working/artifacts/models/{symbol}/{asof}/meta_label_meta.json
"""

from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Sequence

import numpy as np
import pandas as pd

from dodgys_dd_quant.ml_pipeline import DECISION_THRESHOLD
from dodgys_dd_quant.ml_pipeline.splits import Fold

__all__ = [
    "export_kaggle_dataset",
    "render_fold_kernel_source",
    "write_dataset_metadata",
    "write_kernel_metadata",
    "KAGGLE_DATASET_METADATA",
    "KAGGLE_KERNEL_METADATA",
]

#: Columns every exported fold parquet carries, in this order.
EXPORT_COLUMNS: tuple[str, ...] = (
    "ts_event",
    "symbol",
    "split",
    "label",
    "r_multiple",
)

KAGGLE_DATASET_METADATA: dict = {
    "title": "DodgysDD iFVG meta-labeler -- walk-forward folds",
    "id": "YOUR_USER/dodgysdd-ifvg-folds",
    "licenses": [{"name": "CC0-1.0"}],
    "keywords": ["iFVG", "meta-labeling", "lightgbm", "walk-forward"],
    "subtitle": "Purged walk-forward folds for the DodgysDD iFVG meta-labeler",
    "description": (
        "One Parquet per walk-forward fold (train + validation only; the test fold is "
        "never exported).  Each row is a candidate setup with its decision-time features "
        "and its binary meta-label (1 = target reached, 0 = stop hit, -1 = unlabelled)."
    ),
    "resources": [],
    "dataset_type": "tabular",
    "licenses_chosen": True,
}

KAGGLE_KERNEL_METADATA: dict = {
    "id": "YOUR_USER/dodgysdd-ifvg-fold",
    "title": "DodgysDD iFVG meta-labeler -- fold",
    "code_file": "fold_kernel_000.py",
    "language": "python",
    "kernel_type": "script",
    "is_private": True,
    "enable_gpu": False,
    "enable_internet": False,
    "dataset_sources": ["YOUR_USER/dodgysdd-ifvg-folds"],
    "competition_sources": [],
    "kernel_sources": [],
    "model_sources": [],
    "environment_type": "cpu",
}


def _fold_filename(index: int) -> str:
    return f"fold_{index:03d}.parquet"


def _kernel_filename(index: int) -> str:
    return f"fold_kernel_{index:03d}.py"


def _split_frame(
    frame: pd.DataFrame,
    fold: Fold,
    feature_columns: Sequence[str],
) -> pd.DataFrame:
    """The train + validation rows of one fold, with a ``split`` column."""
    parts = [fold.train_idx, fold.valid_idx]
    idx = np.concatenate(parts) if any(len(p) for p in parts) else np.empty(0, dtype=np.int64)
    if idx.size == 0:
        return pd.DataFrame(columns=list(EXPORT_COLUMNS) + list(feature_columns))
    idx = np.sort(idx)
    out = frame.iloc[idx].copy()
    out["split"] = "train"
    valid_set = set(int(i) for i in fold.valid_idx)
    mask = out.index.isin(valid_set)
    out.loc[mask, "split"] = "valid"
    columns = [c for c in EXPORT_COLUMNS if c in out.columns] + list(feature_columns)
    return out.loc[:, columns].reset_index(drop=True)


def render_fold_kernel_source(
    fold: Fold,
    *,
    symbol: str,
    timeframe: str = "1m",
    dataset_slug: str = "YOUR_USER/dodgysdd-ifvg-folds",
    feature_columns: Sequence[str],
    decision_threshold: float = DECISION_THRESHOLD,
    expected_rows: int = 0,
    horizon_bars: int = 240,
    embargo_minutes: int = 240,
) -> str:
    """Produce the kernel source of one fold.

    The generated code contains the *hard* guarantee that the kernel never sees
    the test fold: it asserts, before training, that no row it loaded falls
    inside the test window and that the train and validation row sets are
    disjoint.
    """
    fold_file = _fold_filename(fold.index)
    train_start = fold.train_start.strftime("%Y-%m-%d")
    train_end = fold.train_end.strftime("%Y-%m-%d")
    valid_start = fold.valid_start.strftime("%Y-%m-%d")
    valid_end = fold.valid_end.strftime("%Y-%m-%d")
    test_start = fold.test_start.strftime("%Y-%m-%d")
    test_end = fold.test_end.strftime("%Y-%m-%d")
    test_start_ns = int(fold.test_start.value)
    test_end_ns = int(fold.test_end.value)
    feature_list = ", ".join(f'"{c}"' for c in feature_columns)
    asof = fold.asof.strftime("%Y-%m-%d")
    return f'''"""DodgysDD iFVG meta-labeler -- walk-forward fold {fold.index} (Kaggle kernel).

Generated by ``dodgys_dd_quant.ml_pipeline.kaggle_export``; do not edit by hand.

Contract
--------
* train  : {train_start} .. {train_end}
* valid  : {valid_start} .. {valid_end}
* test   : {test_start} .. {test_end}  (NEVER READ)
* embargo: {embargo_minutes} minutes (>= the {horizon_bars}-bar maximum holding period)
* output : artifacts/models/{symbol}/{fold.asof_compact}/meta_label_lgbm.txt + meta_label_meta.json
"""

from __future__ import annotations

import json
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

DATASET_DIR = "/kaggle/input/{dataset_slug}"
WORK_DIR = "/kaggle/working/artifacts/models/{symbol}/{fold.asof_compact}"

FOLD_FILE = "{fold_file}"
FEATURES = [{feature_list}]
TRAIN_START_NS = {int(fold.train_start.value)}
TRAIN_END_NS = {int(fold.train_end.value)}
VALID_START_NS = {int(fold.valid_start.value)}
VALID_END_NS = {int(fold.valid_end.value)}
TEST_START_NS = {test_start_ns}
TEST_END_NS = {test_end_ns}
EXPECTED_ROWS = {expected_rows}
DECISION_THRESHOLD = {decision_threshold}
HORIZON_BARS = {horizon_bars}
EMBARGO_MINUTES = {embargo_minutes}

df = pd.read_parquet(os.path.join(DATASET_DIR, FOLD_FILE))

# ---------------------------------------------------------------------------
# HARD GUARANTEE: this kernel never sees the test fold.
# ---------------------------------------------------------------------------
assert "ts_event" in df.columns, "fold parquet has no ts_event column"
assert len(df) == EXPECTED_ROWS, (
    f"fold parquet has {{len(df)}} rows, expected {{EXPECTED_ROWS}}"
)
assert df["ts_event"].max() < TEST_START_NS, (
    "LEAK: the fold parquet contains rows at or after the test window "
    f"(max ts_event={{int(df['ts_event'].max())}}, test_start={{TEST_START_NS}})"
)
assert not ((df["ts_event"] >= TEST_START_NS) & (df["ts_event"] < TEST_END_NS)).any(), (
    "LEAK: the fold parquet contains test-window rows"
)
assert df["ts_event"].min() >= TRAIN_START_NS, "fold parquet contains rows before the train window"

train = df[df["split"] == "train"].copy()
valid = df[df["split"] == "valid"].copy()
assert len(train) > 0 and len(valid) > 0, "empty train or valid split"
assert set(train["ts_event"]).isdisjoint(set(valid["ts_event"])), "train/valid overlap"
assert (train["ts_event"] < VALID_START_NS).all(), "a train row falls into the validation window"

train = train[train["label"] != -1].dropna(subset=FEATURES)
valid = valid[valid["label"] != -1].dropna(subset=FEATURES)
assert len(train) > 0 and len(valid) > 0, "no usable rows after dropping the unlabelled"

x_train = train[FEATURES].astype("float64")
x_valid = valid[FEATURES].astype("float64")
y_train = train["label"].astype("int8").to_numpy()
y_valid = valid["label"].astype("int8").to_numpy()

n_pos = int((y_train == 1).sum())
n_neg = int((y_train == 0).sum())
assert n_pos > 0 and n_neg > 0, "degenerate training fold"

params = {{
    "objective": "binary",
    "metric": "auc",
    "learning_rate": 0.05,
    "num_leaves": 15,
    "scale_pos_weight": n_neg / n_pos,
    "bagging_fraction": 0.9,
    "bagging_freq": 1,
    "feature_fraction": 0.9,
    "seed": 20261122,
    "deterministic": True,
    "force_row_wise": True,
    "verbose": -1,
}}

dtrain = lgb.Dataset(x_train, label=y_train, feature_name=list(FEATURES))
dvalid = lgb.Dataset(x_valid, label=y_valid, reference=dtrain, feature_name=list(FEATURES))
booster = lgb.train(
    params,
    dtrain,
    num_boost_round=500,
    valid_sets=[dvalid],
    valid_names=["valid"],
    callbacks=[lgb.early_stopping(50, verbose=False)],
)

os.makedirs(WORK_DIR, exist_ok=True)
booster.save_model(
    os.path.join(WORK_DIR, "meta_label_lgbm.txt"), num_iteration=booster.best_iteration
)

meta = {{
    "symbol": "{symbol}",
    "timeframe": "{timeframe}",
    "asof": "{asof}",
    "train_start": "{train_start}",
    "train_end": "{train_end}",
    "valid_start": "{valid_start}",
    "valid_end": "{valid_end}",
    "test_start": "{test_start}",
    "test_end": "{test_end}",
    "embargo_minutes": EMBARGO_MINUTES,
    "feature_list": list(FEATURES),
    "decision_threshold": DECISION_THRESHOLD,
    "n_train": int(len(train)),
    "n_valid": int(len(valid)),
    "n_test": 0,
    "positives_train": n_pos,
    "positives_test": 0,
    "auc_test": None,
    "accuracy_test": None,
    "scale_pos_weight": n_neg / n_pos,
    "best_iteration": int(booster.best_iteration or 500),
    "horizon_bars": HORIZON_BARS,
    "note": "the test fold is not shipped to the kernel; it is scored locally afterwards",
}}

with open(os.path.join(WORK_DIR, "meta_label_meta.json"), "w", encoding="utf-8") as fh:
    json.dump(meta, fh, indent=2)

print("fold {fold.index}: wrote", WORK_DIR)
'''


def write_dataset_metadata(
    out_dir: str | Path, *, symbol: str, timeframe: str, resources: Sequence[str]
) -> Path:
    """Write ``dataset-metadata.json`` (the Kaggle CLI dataset descriptor)."""
    meta = dict(KAGGLE_DATASET_METADATA)
    meta["title"] = f"DodgysDD iFVG meta-labeler folds -- {symbol} {timeframe}"
    meta["subtitle"] = f"Purged walk-forward folds for {symbol} {timeframe} (train+valid only)"
    meta["resources"] = [
        {"path": name, "description": "one walk-forward fold"} for name in resources
    ]
    path = Path(out_dir) / "dataset-metadata.json"
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return path


def write_kernel_metadata(
    out_dir: str | Path, *, symbol: str, timeframe: str, index: int, dataset_slug: str
) -> Path:
    """Write ``kernel-metadata.json`` (the Kaggle CLI kernel descriptor)."""
    meta = dict(KAGGLE_KERNEL_METADATA)
    meta["title"] = f"DodgysDD iFVG meta-labeler -- {symbol} {timeframe} fold {index}"
    meta["code_file"] = _kernel_filename(index)
    meta["dataset_sources"] = [dataset_slug]
    path = Path(out_dir) / "kernel-metadata.json"
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return path


def export_kaggle_dataset(
    frame: pd.DataFrame,
    folds: Sequence[Fold],
    *,
    out_dir: str | Path,
    symbol: str,
    timeframe: str = "1m",
    feature_columns: Sequence[str],
    decision_threshold: float = DECISION_THRESHOLD,
    dataset_slug: str = "YOUR_USER/dodgysdd-ifvg-folds",
) -> dict:
    """Write the Kaggle dataset (one Parquet per fold) + the per-fold kernels.

    Parameters
    ----------
    frame:
        The labelled + featured candidate log (as produced by the trainer).
    folds:
        The walk-forward folds.
    feature_columns:
        The feature columns the kernel trains on.

    Returns
    -------
    A manifest describing what was written (paths, row counts, windows).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    resources: list[str] = []
    manifest_folds: list[dict] = []
    for fold in folds:
        split = _split_frame(frame, fold, feature_columns)
        name = _fold_filename(fold.index)
        split.to_parquet(out_dir / name, index=False, compression="zstd")
        resources.append(name)

        source = render_fold_kernel_source(
            fold,
            symbol=symbol,
            timeframe=timeframe,
            dataset_slug=dataset_slug,
            feature_columns=feature_columns,
            decision_threshold=decision_threshold,
            expected_rows=int(len(split)),
        )
        (out_dir / _kernel_filename(fold.index)).write_text(source, encoding="utf-8")
        write_kernel_metadata(
            out_dir, symbol=symbol, timeframe=timeframe, index=fold.index, dataset_slug=dataset_slug
        )

        manifest_folds.append(
            {
                **fold.to_dict(),
                "parquet": name,
                "kernel": _kernel_filename(fold.index),
                "n_rows": int(len(split)),
                "n_train_rows": int((split["split"] == "train").sum()) if len(split) else 0,
                "n_valid_rows": int((split["split"] == "valid").sum()) if len(split) else 0,
                "test_rows_exported": 0,
            }
        )

    write_dataset_metadata(out_dir, symbol=symbol, timeframe=timeframe, resources=resources)

    plan = {
        "symbol": symbol,
        "timeframe": timeframe,
        "decision_threshold": decision_threshold,
        "feature_list": list(feature_columns),
        "dataset_slug": dataset_slug,
        "note": (
            "The test fold is never exported. The kernel asserts that the data it "
            "loaded contains no row inside the test window; the test window is "
            "recorded here so the fold can be scored locally afterwards."
        ),
        "folds": manifest_folds,
    }
    (out_dir / "fold_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

    return {
        "out_dir": str(out_dir),
        "dataset_metadata": str(out_dir / "dataset-metadata.json"),
        "kernel_metadata": str(out_dir / "kernel-metadata.json"),
        "fold_plan": str(out_dir / "fold_plan.json"),
        "folds": manifest_folds,
    }
