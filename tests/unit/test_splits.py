"""Unit tests for the purged, embargoed walk-forward splits.

Run with::

    .venv-ml/bin/python -m pytest tests/unit -q

These tests need neither the data lake nor the network.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from dodgys_dd_quant.ml_pipeline.kaggle_export import (
    export_kaggle_dataset,
    render_fold_kernel_source,
)
from dodgys_dd_quant.ml_pipeline.labels import max_holding_minutes
from dodgys_dd_quant.ml_pipeline.splits import make_folds

ANCHOR = pd.Timestamp("2024-01-01", tz="UTC")


def _candidate(ts: pd.Timestamp, **extra) -> dict:
    row = {
        "ts_event": int(ts.value),
        "symbol": "TEST",
        "side": 1,
        "entry_price": 100.0,
        "stop_price": 99.0,
        "target_price": 102.0,
        "risk": 1.0,
        "fvg_low": 99.5,
        "fvg_high": 100.5,
        "fvg_bar1": 0,
        "fvg_bar3": 1,
        "confirm_bar": 2,
        "bars_to_inversion": 1,
        "minutes_from_us_open": 0,
        "checklist_score": 3.0,
        "smt_divergence": -1,
        "sweep_detected": 1,
        "vxn_known": np.nan,
        "vxn_regime": np.nan,
        "vision_iou": np.nan,
        "vision_confidence": np.nan,
    }
    row.update(extra)
    return row


def _monthly_candidates(n_months: int = 14, per_month: int = 3) -> pd.DataFrame:
    """A synthetic candidate log spread over ``n_months`` months."""
    rows = []
    for m in range(n_months):
        start = ANCHOR + pd.DateOffset(months=m)
        for k in range(per_month):
            rows.append(_candidate(start + pd.Timedelta(days=1, hours=8 + k)))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 1. geometry
# ---------------------------------------------------------------------------
def test_fold_geometry_is_6_1_1():
    candidates = _monthly_candidates()
    folds = make_folds(candidates, embargo_minutes=240, bar_interval_minutes=1)
    assert len(folds) >= 2
    first = folds[0]
    assert first.train_start == ANCHOR
    assert first.train_end == ANCHOR + pd.DateOffset(months=6)
    assert first.valid_end - first.valid_start >= pd.Timedelta(days=27)
    assert first.test_end - first.test_start >= pd.Timedelta(days=27)


def test_folds_are_monotonic_and_contiguous():
    """The fold list steps forward by exactly one month and the test windows tile."""
    candidates = _monthly_candidates()
    folds = make_folds(candidates, embargo_minutes=240, bar_interval_minutes=1)
    for previous, current in zip(folds, folds[1:]):
        assert current.index == previous.index + 1
        assert current.train_start > previous.train_start
        assert current.train_end > previous.train_end
        assert current.asof > previous.asof
        # the out-of-sample windows are consecutive -> the OOS predictions can
        # be concatenated into one continuous series
        assert current.test_start == previous.test_end


def test_embargo_separates_train_from_validation():
    candidates = _monthly_candidates()
    embargo = 240
    folds = make_folds(candidates, embargo_minutes=embargo, bar_interval_minutes=1)
    for fold in folds:
        gap = fold.valid_start - fold.train_end
        assert gap >= pd.Timedelta(minutes=embargo)


def test_embargo_must_cover_the_maximum_holding_period():
    """A too-small embargo is rejected: a training label could resolve in the
    validation window."""
    candidates = _monthly_candidates()
    horizon = max_holding_minutes(1)
    assert horizon == 240
    with pytest.raises(ValueError, match="embargo"):
        make_folds(candidates, embargo_minutes=horizon - 1, bar_interval_minutes=1)
    # the default is derived from the label construction, not assumed
    folds = make_folds(candidates, bar_interval_minutes=1)
    assert folds[0].embargo_minutes == horizon


def test_purge_keeps_training_labels_inside_the_training_window():
    """No training sample may own time that reaches into the validation window."""
    candidates = _monthly_candidates()
    folds = make_folds(candidates, embargo_minutes=240, bar_interval_minutes=1)
    horizon_ns = 240 * 60 * 1_000_000_000
    ts = candidates["ts_event"].to_numpy()
    for fold in folds:
        if not fold.train_idx.size:
            continue
        assert (ts[fold.train_idx] + horizon_ns <= fold.train_end.value).all()


def test_no_train_valid_or_test_overlap():
    candidates = _monthly_candidates()
    folds = make_folds(candidates, embargo_minutes=240, bar_interval_minutes=1)
    for fold in folds:
        assert set(fold.train_idx.tolist()) & set(fold.valid_idx.tolist()) == set()
        assert set(fold.train_idx.tolist()) & set(fold.test_idx.tolist()) == set()
        assert set(fold.valid_idx.tolist()) & set(fold.test_idx.tolist()) == set()


def test_validation_tail_is_purged_so_early_stopping_cannot_see_the_test_window():
    """A validation label resolved with test-window bars would leak into the model."""
    candidates = _monthly_candidates()
    folds = make_folds(candidates, embargo_minutes=240, bar_interval_minutes=1)
    horizon_ns = 240 * 60 * 1_000_000_000
    ts = candidates["ts_event"].to_numpy()
    for fold in folds:
        if not fold.valid_idx.size:
            continue
        assert (ts[fold.valid_idx] + horizon_ns <= fold.valid_end.value).all()


# ---------------------------------------------------------------------------
# 2. the synthetic leak case
# ---------------------------------------------------------------------------
def test_asof_is_the_end_of_the_validation_window():
    """D3 forward-only rule: the model may only be used after ``asof``.
    ``asof`` is the end of the *validation* window, not the end of the
    training window: the early-stopping decision was taken on the validation
    labels, so the model must not be applied inside that window.  With this
    choice the folds tile exactly -- fold *i*'s model is in force over fold
    *i*'s test window.
    """
    candidates = _monthly_candidates()
    folds = make_folds(candidates, embargo_minutes=240, bar_interval_minutes=1)
    for fold in folds:
        assert fold.asof == fold.valid_end
        assert fold.asof == fold.test_start
        assert fold.asof > fold.train_end


def test_a_naive_split_would_leak_but_the_purged_split_does_not():
    """A candidate just before the training boundary resolves inside the
    validation window.  A naive calendar split would train on it."""
    candidates = _monthly_candidates()
    folds = make_folds(candidates, embargo_minutes=240, bar_interval_minutes=1)
    fold = folds[0]

    boundary = fold.train_end - pd.Timedelta(hours=1)
    leaky = pd.DataFrame([_candidate(boundary)])
    leaky_index = len(candidates)
    candidates = pd.concat([candidates, leaky], ignore_index=True)

    horizon_ns = 240 * 60 * 1_000_000_000
    naive_train = np.nonzero(candidates["ts_event"].to_numpy() < fold.train_end.value)[0]
    assert leaky_index in naive_train.tolist(), "the naive split would have leaked it"

    folds = make_folds(candidates, embargo_minutes=240, bar_interval_minutes=1)
    fold = folds[0]
    assert leaky_index not in fold.train_idx.tolist()
    ts = candidates["ts_event"].to_numpy()
    assert ts[leaky_index] + horizon_ns > fold.train_end.value  # it really would have leaked
    assert (ts[fold.train_idx] + horizon_ns <= fold.train_end.value).all()


def test_folds_are_generated_only_while_test_data_exists():
    candidates = _monthly_candidates(n_months=4)
    folds = make_folds(candidates, embargo_minutes=240, bar_interval_minutes=1)
    # 4 months of data cannot fill a 6-month training window
    assert folds == [] or folds[0].train_idx.size == 0


# ---------------------------------------------------------------------------
# 3. the Kaggle path
# ---------------------------------------------------------------------------
def test_kaggle_export_never_ships_the_test_fold(tmp_path):
    """The kernel must not be able to see the test fold -- not even by accident."""
    candidates = _monthly_candidates()
    folds = make_folds(candidates, embargo_minutes=240, bar_interval_minutes=1)
    frame = candidates.copy()
    frame["label"] = 1
    frame["r_multiple"] = 2.0

    features = ["checklist_score", "bars_to_inversion"]
    manifest = export_kaggle_dataset(
        frame,
        folds,
        out_dir=tmp_path / "dataset",
        symbol="TEST",
        timeframe="1m",
        feature_columns=features,
    )

    assert manifest["folds"], "no fold was exported"
    for entry in manifest["folds"]:
        parquet = pd.read_parquet(tmp_path / "dataset" / entry["parquet"])
        ts = parquet["ts_event"].to_numpy()
        fold = folds[entry["index"]]
        # no exported row may fall inside the test window
        assert not ((ts >= fold.test_start.value) & (ts < fold.test_end.value)).any()
        assert ts.max() < fold.test_start.value
        assert entry["test_rows_exported"] == 0
        # the train and valid splits are present and disjoint
        train = parquet[parquet["split"] == "train"]
        valid = parquet[parquet["split"] == "valid"]
        assert not set(train["ts_event"]) & set(valid["ts_event"])
        assert len(train) + len(valid) == len(parquet)


def test_generated_kernel_asserts_the_test_fold_is_absent(tmp_path):
    candidates = _monthly_candidates()
    folds = make_folds(candidates, embargo_minutes=240, bar_interval_minutes=1)
    source = render_fold_kernel_source(
        folds[0],
        symbol="TEST",
        timeframe="1m",
        feature_columns=["checklist_score"],
        expected_rows=42,
    )
    assert "LEAK" in source
    assert "TEST_START_NS" in source
    assert "meta_label_lgbm.txt" in source
    assert "meta_label_meta.json" in source
    # the generated file must be valid python
    compile(source, "kernel", "exec")


def test_generated_kernel_refuses_a_parquet_that_contains_the_test_fold(tmp_path):
    """The kernel's own guard must actually fire (the kernel is executed here)."""
    pytest.importorskip("lightgbm")
    candidates = _monthly_candidates()
    folds = make_folds(candidates, embargo_minutes=240, bar_interval_minutes=1)
    frame = candidates.copy()
    frame["label"] = 1
    frame["r_multiple"] = 2.0
    export_kaggle_dataset(
        frame,
        folds,
        out_dir=tmp_path / "dataset",
        symbol="TEST",
        timeframe="1m",
        feature_columns=["checklist_score"],
    )
    source = (tmp_path / "dataset" / "fold_kernel_000.py").read_text()
    source = source.replace(
        'DATASET_DIR = "/kaggle/input/YOUR_USER/dodgysdd-ifvg-folds"',
        f'DATASET_DIR = "{tmp_path / "dataset"}"',
    )
    source = source.replace(
        'WORK_DIR = "/kaggle/working/artifacts/models/TEST/',
        f'WORK_DIR = "{tmp_path / "out"}/TEST/',
    )
    parquet = tmp_path / "dataset" / "fold_000.parquet"
    df = pd.read_parquet(parquet)
    tampered = pd.concat([df, df.head(1)])
    tampered.loc[tampered.index[-1], "ts_event"] = (
        int(folds[0].test_start.value) + 3_600_000_000_000
    )
    tampered.to_parquet(parquet, index=False)
    source = source.replace(f"EXPECTED_ROWS = {len(df)}", f"EXPECTED_ROWS = {len(tampered)}")
    with pytest.raises(AssertionError, match="LEAK"):
        exec(compile(source, "kernel", "exec"), {"__name__": "__main__"})


def test_trainer_refuses_a_degenerate_fold_and_records_it_as_skipped(tmp_path):
    """A fold with no positives must be skipped, not trained into a useless model."""
    pytest.importorskip("lightgbm")
    from dodgys_dd_quant.ml_pipeline.train_meta_labeler import train_walk_forward

    rows = []
    for m in range(9):
        start = ANCHOR + pd.DateOffset(months=m)
        for k in range(60):
            ts = start + pd.Timedelta(days=1, hours=k)
            row = _candidate(ts)
            row["bars_to_inversion"] = 1 + (k % 5)
            row["minutes_from_us_open"] = 0.0
            # the first six months are all losers -> the first fold is degenerate
            row["label"] = 0 if m < 6 else (k % 2)
            row["r_multiple"] = -1.0 if row["label"] == 0 else 2.0
            rows.append(row)
    frame = pd.DataFrame(rows)

    report = train_walk_forward(
        frame, None, symbol="TEST", timeframe="1m", run_root=tmp_path / "run"
    )
    folds = report["index"]["folds"]
    first = folds[0]
    assert first["status"] == "skipped"
    assert "MIN_POSITIVES_TRAIN" in first["reason"]
    assert first["model_dir"] == ""
    assert not (tmp_path / "run" / "models" / "TEST" / first["asof"].replace("-", "")).exists()
    assert any(f["status"] == "trained" for f in folds)
    assert (tmp_path / "run" / "walk_forward_index.json").exists()
def test_dataset_and_kernel_metadata_are_valid_json(tmp_path):
    candidates = _monthly_candidates()
    folds = make_folds(candidates, embargo_minutes=240, bar_interval_minutes=1)
    frame = candidates.copy()
    frame["label"] = 1
    frame["r_multiple"] = 2.0
    export_kaggle_dataset(
        frame,
        folds,
        out_dir=tmp_path / "dataset",
        symbol="TEST",
        timeframe="1m",
        feature_columns=["checklist_score"],
    )
    dataset_meta = json.loads((tmp_path / "dataset" / "dataset-metadata.json").read_text())
    kernel_meta = json.loads((tmp_path / "dataset" / "kernel-metadata.json").read_text())
    plan = json.loads((tmp_path / "dataset" / "fold_plan.json").read_text())
    assert dataset_meta["id"].endswith("/dodgysdd-ifvg-folds")
    assert kernel_meta["kernel_type"] == "script"
    assert kernel_meta["dataset_sources"] == ["YOUR_USER/dodgysdd-ifvg-folds"]
    assert plan["folds"] and plan["folds"][0]["test_rows_exported"] == 0
