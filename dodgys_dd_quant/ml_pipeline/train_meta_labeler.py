"""Rolling walk-forward training of the iFVG meta-labeler.

What this module does
---------------------
1. reads a D2 candidate log (and the market series),
2. builds the feature frame (``features.build_features``) and the binary
   meta-label (``labels.build_labels``),
3. cuts the purged, embargoed walk-forward folds (``splits.make_folds``),
4. trains a LightGBM binary classifier per fold -- early stopping on the
   **validation** fold, the **test** fold is scored **once**, at the end,
5. writes exactly the D3 artefact:
   ``artifacts/models/{symbol}/{asof}/meta_label_lgbm.txt`` +
   ``meta_label_meta.json`` + ``walk_forward_index.json``.

Honesty rules that are enforced in code
---------------------------------------
* **D4** -- the rule engine has no edge.  Nothing here claims an improvement;
  every fold reports the *unfiltered* baseline (base rate, expectancy) next to
  the gated numbers, and the gated expectancy is computed on a **census** of
  candidates, not on the one-position-at-a-time accounting.  The authoritative
  expectancy comparison belongs to the backtest leaf.
* **D8** -- ``checklist_score`` is a *feature*, never a filter.
* **D9** -- costs are not applied here; they live in the backtest config.
* **INV4** -- unlabelled (still open) candidates stay in the log; they are
  dropped only from the training matrix.

Dependencies
------------
LightGBM is **not** installed in the project's main 3.11 interpreter.  Use the
dedicated virtualenv::

    uv venv --python 3.11 .venv-ml
    VIRTUAL_ENV=.venv-ml uv pip install lightgbm pandas pyarrow numpy pytest
    .venv-ml/bin/python -m dodgys_dd_quant.ml_pipeline.train_meta_labeler ...

This module imports cleanly **without** LightGBM; the missing dependency is
only reported when a training run is actually requested.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from dodgys_dd_quant.ml_pipeline import (
    DECISION_THRESHOLD,
    DEFAULT_BAR_INTERVAL_MINUTES,
    LGBM_BAGGING_FRACTION,
    LGBM_EARLY_STOPPING_ROUNDS,
    LGBM_FEATURE_FRACTION,
    LGBM_LEARNING_RATE,
    LGBM_N_ESTIMATORS,
    LGBM_NUM_LEAVES,
    LGBM_NUM_THREADS,
    LGBM_SEED,
    MIN_POSITIVES_TRAIN,
    MIN_POSITIVES_VALID,
    MIN_TRAIN_ROWS,
    REQUIRED_BAR_COLUMNS,
    REQUIRED_CANDIDATE_COLUMNS,
    TEST_MONTHS,
    TRAIN_MONTHS,
    VALID_MONTHS,
)
from dodgys_dd_quant.ml_pipeline.features import (
    FEATURE_AVAILABILITY,
    FEATURE_SOURCES,
    build_features,
    candidate_consistency_report,
    resolve_feature_list,
)
from dodgys_dd_quant.ml_pipeline.labels import (
    LABEL_TARGET,
    LABEL_UNLABELLED,
    build_labels,
    max_holding_minutes,
    summarize_labels,
)
from dodgys_dd_quant.ml_pipeline.splits import Fold, make_folds

__all__ = [
    "LightGBMUnavailable",
    "load_candidates",
    "load_bars",
    "model_dir_for",
    "train_walk_forward",
    "plan_folds",
    "main",
]

MODEL_FILENAME = "meta_label_lgbm.txt"
META_FILENAME = "meta_label_meta.json"
INDEX_FILENAME = "walk_forward_index.json"


def model_dir_for(run_root: str | Path, symbol: str, asof_compact: str) -> Path:
    """The D3 model directory of one fold.

    The layout is ``{run_root}/models/{symbol}/asof_{YYYYMMDD}/``.  It is the
    single source of truth for the artefact path: the README documents it and
    the backtest's reader looks for it, so both must follow this function
    (F12).
    """
    return Path(run_root) / "models" / symbol / f"asof_{asof_compact}"


_LGBM_INSTALL_HINT = (
    "LightGBM is not installed for this interpreter.  Create the dedicated "
    "virtualenv and use it:\n"
    "    uv venv --python 3.11 .venv-ml\n"
    "    VIRTUAL_ENV=.venv-ml uv pip install lightgbm pandas pyarrow numpy pytest\n"
    "    .venv-ml/bin/python -m dodgys_dd_quant.ml_pipeline.train_meta_labeler ..."
)


class LightGBMUnavailable(RuntimeError):
    """Raised when a training run is requested without LightGBM installed."""


def _require_lightgbm() -> Any:
    try:
        import lightgbm as lgb
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise LightGBMUnavailable(_LGBM_INSTALL_HINT) from exc
    return lgb


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------
def load_candidates(path: str | Path) -> pd.DataFrame:
    """Load a D2 candidate log (Parquet)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"candidate log not found: {p}")
    frame = pd.read_parquet(p)
    missing = [c for c in REQUIRED_CANDIDATE_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(
            f"candidate log {p} is missing required D2 column(s): {missing}. "
            f"Expected at least {list(REQUIRED_CANDIDATE_COLUMNS)}."
        )
    frame = frame.copy()
    frame["ts_event"] = frame["ts_event"].astype("int64")
    return frame.sort_values("ts_event", kind="stable").reset_index(drop=True)


def load_bars(path: str | Path) -> pd.DataFrame:
    """Load the market series (Parquet) into the canonical bar frame.

    **The frame's ``ts_event`` is the bar's CLOSE time**, which is the same
    convention the D2 candidate log uses (``ts_event`` = the close of the
    confirmation bar) and the same one the backtest's runner builds.  The
    governed lake stamps its bars at the **open** (left-open convention), so
    the loader adds one bar interval to reach the close.

    Keeping one convention everywhere is what lets the engine's outcome join
    and the ML pipeline's label join agree row for row (F6).  With the two
    conventions mixed, the label scan starts a bar too late and the two
    definitions disagree on the intrabar ties.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"bars file not found: {p}")
    frame = pd.read_parquet(p)
    if "ts_event" not in frame.columns:
        if "timestamp" in frame.columns:
            open_ns = frame["timestamp"].astype("int64") * 1_000_000
            frame["ts_event"] = open_ns + _bar_interval_ns(open_ns.to_numpy())
        else:
            raise ValueError(
                f"bars file {p} has neither 'ts_event' (ns) nor 'timestamp' (ms) column"
            )
    frame = frame.copy()
    frame["ts_event"] = frame["ts_event"].astype("int64")
    missing = [c for c in REQUIRED_BAR_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"bars file {p} is missing required column(s): {missing}")
    return frame.sort_values("ts_event", kind="stable").reset_index(drop=True)


def _bar_interval_ns(open_ns: np.ndarray) -> int:
    """The bar spacing in nanoseconds (the modal gap of a regular series)."""
    if open_ns.size < 2:
        return 60_000_000_000
    deltas = np.diff(open_ns)
    values, counts = np.unique(deltas, return_counts=True)
    return int(values[int(np.argmax(counts))])


def _infer_bar_interval_minutes(bars: pd.DataFrame) -> int:
    ts = bars["ts_event"].astype("int64").to_numpy()
    if len(ts) < 2:
        return DEFAULT_BAR_INTERVAL_MINUTES
    step_ns = int(np.median(np.diff(ts)))
    return max(1, int(round(step_ns / 60_000_000_000)))


# ---------------------------------------------------------------------------
# metrics (no scikit-learn dependency)
# ---------------------------------------------------------------------------
def _auc(y_true: np.ndarray, score: np.ndarray) -> float:
    """Mann-Whitney AUC with tie-corrected ranks."""
    y = np.asarray(y_true).astype(int)
    s = np.asarray(score, dtype="float64")
    n_pos = int((y == 1).sum())
    n_neg = int((y == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(s, kind="mergesort")
    sorted_s = s[order]
    ranks = np.empty(len(s), dtype="float64")
    base = np.arange(1, len(s) + 1, dtype="float64")
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and sorted_s[j + 1] == sorted_s[i]:
            j += 1
        ranks[order[i : j + 1]] = base[i : j + 1].mean()
        i = j + 1
    sum_pos = float(ranks[y == 1].sum())
    return (sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


# ---------------------------------------------------------------------------
# training
# ---------------------------------------------------------------------------
@dataclass
class FoldResult:
    """Everything that is known about one fold after the run."""

    fold: Fold
    status: str = "trained"
    reason: str = ""
    n_train: int = 0
    n_valid: int = 0
    n_test: int = 0
    positives_train: int = 0
    positives_valid: int = 0
    positives_test: int = 0
    auc_test: float | None = None
    accuracy_test: float | None = None
    metrics: dict = field(default_factory=dict)
    model_dir: str = ""
    #: The fold directory **relative to the models root** -- the root the
    #: backtest points at with ``--models-root`` (D3).
    model_rel_dir: str = ""


def _json_safe(value: Any) -> Any:
    """Make a structure strict-JSON safe (NaN/Inf -> null)."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (np.floating,)) and (math.isnan(float(value)) or math.isinf(float(value))):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _matrix(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    return frame.loc[:, list(columns)].astype("float64")


def _count_positives(frame: pd.DataFrame) -> int:
    """Number of label==1 rows (0 for an empty frame)."""
    if frame.empty or "label" not in frame.columns:
        return 0
    return int((frame["label"].astype("int8") == LABEL_TARGET).sum())


def _train_one_fold(
    lgb: Any,
    train: pd.DataFrame,
    valid: pd.DataFrame,
    features: Sequence[str],
    *,
    seed: int = LGBM_SEED,
) -> tuple[Any, dict]:
    """Train one LightGBM binary classifier; early stopping on the validation fold."""
    x_train = _matrix(train, features)
    x_valid = _matrix(valid, features)
    y_train = train["label"].astype("int8").to_numpy()
    y_valid = valid["label"].astype("int8").to_numpy()
    n_pos = int((y_train == 1).sum())
    n_neg = int((y_train == 0).sum())
    if n_pos == 0 or n_neg == 0:
        raise ValueError("degenerate training fold: a class is missing")
    scale_pos_weight = n_neg / n_pos

    params = {
        "objective": "binary",
        "metric": "auc",
        "learning_rate": LGBM_LEARNING_RATE,
        "num_leaves": LGBM_NUM_LEAVES,
        "scale_pos_weight": scale_pos_weight,
        "bagging_fraction": LGBM_BAGGING_FRACTION,
        "bagging_freq": 1,
        "feature_fraction": LGBM_FEATURE_FRACTION,
        "seed": seed,
        "deterministic": True,
        "force_row_wise": True,
        # LightGBM is only reproducible for a **fixed** thread count: with
        # ``deterministic`` on, the result still depends on how many threads
        # split the data.  Pinning it makes the trained artefact -- and the
        # numbers quoted from it -- reproducible run to run.
        "num_threads": LGBM_NUM_THREADS,
        "verbose": -1,
    }
    dtrain = lgb.Dataset(x_train, label=y_train, feature_name=list(features), free_raw_data=False)
    dvalid = lgb.Dataset(x_valid, label=y_valid, reference=dtrain, feature_name=list(features))
    booster = lgb.train(
        params,
        dtrain,
        num_boost_round=LGBM_N_ESTIMATORS,
        valid_sets=[dvalid],
        valid_names=["valid"],
        callbacks=[lgb.early_stopping(LGBM_EARLY_STOPPING_ROUNDS, verbose=False)],
    )
    info = {
        "scale_pos_weight": scale_pos_weight,
        "best_iteration": int(booster.best_iteration or LGBM_N_ESTIMATORS),
        "n_train_rows": int(len(train)),
        "n_valid_rows": int(len(valid)),
    }
    return booster, info


def _isotonic_pava(x: np.ndarray, y: np.ndarray) -> dict | None:
    """Isotonic (monotone, least-squares) calibration by PAVA.

    A fixed absolute gate threshold is only meaningful on **calibrated**
    probabilities.  LightGBM's raw scores on a 33 % base rate sit in a narrow
    band around the base rate, so ``P(Win) >= 0.58`` opened in bursts and
    closed for years at a time (61 of 75 folds approved nothing on ETH 15m).

    The calibration is fitted on the **validation** fold, which is known before
    the test window opens, so it is causal.  The returned breakpoints are
    stored in the D3 metadata and applied by the backtest's scorer.
    """
    if len(x) == 0 or len(x) != len(y):
        return None
    order = np.argsort(x, kind="mergesort")
    xs = np.asarray(x, dtype="float64")[order]
    ys = np.asarray(y, dtype="float64")[order]
    # pool adjacent violators (unit weights -> integer block sizes)
    values: list[float] = []
    weights: list[int] = []
    for v in ys:
        cur, w = float(v), 1
        while values and values[-1] > cur:
            prev_v = values.pop()
            prev_w = weights.pop()
            cur = (prev_v * prev_w + cur * w) / (prev_w + w)
            w += prev_w
        values.append(cur)
        weights.append(w)
    fitted = np.asarray(
        [v for v, w in zip(values, weights) for _ in range(w)], dtype="float64"
    )
    if fitted.size != xs.size:  # pragma: no cover - defensive
        return None
    # collapse duplicate scores (a probe callback can tie) into one breakpoint
    uniq, inverse = np.unique(xs, return_inverse=True)
    if uniq.size != xs.size:
        sums = np.zeros(uniq.size)
        counts = np.zeros(uniq.size)
        np.add.at(sums, inverse, fitted)
        np.add.at(counts, inverse, 1.0)
        fitted = sums / np.maximum(counts, 1.0)
    return {
        "x": [float(v) for v in uniq],
        "y": [float(v) for v in fitted],
        "n_valid": int(xs.size),
    }


def _apply_calibration(prob: np.ndarray, calibration: dict | None) -> np.ndarray:
    if not calibration:
        return prob
    xs = calibration.get("x") or []
    ys = calibration.get("y") or []
    if len(xs) != len(ys) or not xs:
        return prob
    return np.interp(prob, xs, ys)


def _evaluate(
    booster: Any,
    test: pd.DataFrame,
    features: Sequence[str],
    threshold: float,
    calibration: dict | None = None,
) -> dict:
    """Score the test fold -- **once**, at the very end of the fold's life."""
    if test.empty:
        return {}
    x = _matrix(test, features)
    y = test["label"].astype("int8").to_numpy()
    score = booster.predict(x, num_iteration=booster.best_iteration)
    raw = np.asarray(score, dtype="float64")
    # AUC is rank-invariant, so it is measured on the raw score; the *gate*
    # is applied to the calibrated probability.
    prob = _apply_calibration(raw, calibration)
    pred_at_half = (prob >= 0.5).astype(int)
    accuracy = float((pred_at_half == y).mean()) if len(y) else float("nan")

    take = prob >= threshold
    n_pass = int(take.sum())
    pass_pos = int((y[take] == 1).sum()) if n_pass else 0
    pass_rate = (pass_pos / n_pass) if n_pass else float("nan")
    r = pd.to_numeric(test["r_multiple"], errors="coerce").to_numpy()
    base_rate = float((y == 1).mean()) if len(y) else float("nan")
    base_expectancy = float(np.nanmean(r)) if len(r) else float("nan")
    pass_expectancy = float(np.nanmean(r[take])) if n_pass else float("nan")
    return {
        "auc_test": _auc(y, raw),
        "accuracy_test": accuracy,
        "accuracy_test_at_threshold": float(((prob >= threshold).astype(int) == y).mean()),
        "base_rate_test": base_rate,
        "expectancy_r_test": base_expectancy,
        "n_pass": n_pass,
        "pass_rate": (n_pass / len(y)) if len(y) else float("nan"),
        "pass_win_rate": pass_rate,
        "pass_expectancy_r": pass_expectancy,
        "expectancy_lift_r": (pass_expectancy - base_expectancy),
    }


def _model_diagnostics(
    booster: Any,
    train: pd.DataFrame,
    features: Sequence[str],
) -> dict:
    """The artefacts the degradation monitor needs (L4 §F.3).

    * the **training prediction distribution** -- the live fold's P(Win) is
      compared against it to detect a distribution drift;
    * the **feature importances** -- the churn between consecutive folds is
      the third degradation signal.

    Both are properties of the *model that was actually used*, so they are
    recorded in the fold's D3 metadata.
    """
    out: dict = {}
    if not train.empty:
        x = _matrix(train, features)
        prob = np.asarray(
            booster.predict(x, num_iteration=booster.best_iteration), dtype=np.float64
        )
        finite = prob[np.isfinite(prob)]
        if finite.size:
            out["train_prediction_distribution"] = {
                "mean": float(finite.mean()),
                "sd": float(finite.std(ddof=1)) if finite.size > 1 else 0.0,
                "n": int(finite.size),
            }
    try:
        gains = np.asarray(
            booster.feature_importance(importance_type="gain"), dtype=np.float64
        )
    except Exception:  # pragma: no cover - depends on the runtime
        gains = np.empty(0, dtype=np.float64)
    if gains.size:
        order = np.argsort(gains)[::-1][:10]
        out["feature_importances_top10"] = [
            [str(features[i]) if i < len(features) else f"feature_{i}", float(gains[i])]
            for i in order
        ]
    return out


def _prepare(frame: pd.DataFrame, features: Sequence[str]) -> pd.DataFrame:
    """Drop the unlabelled rows and the rows with a missing feature value."""
    usable = frame[frame["label"].astype("int8") != LABEL_UNLABELLED].copy()
    if len(usable):
        usable = usable.dropna(subset=list(features))
    return usable


def plan_folds(
    labelled: pd.DataFrame,
    *,
    embargo_minutes: int | None = None,
    bar_interval_minutes: int = DEFAULT_BAR_INTERVAL_MINUTES,
    train_months: int = TRAIN_MONTHS,
    valid_months: int = VALID_MONTHS,
    test_months: int = TEST_MONTHS,
    horizon_bars: int | None = None,
) -> list[Fold]:
    """The fold plan of a run (thin wrapper around ``splits.make_folds``).

    ``horizon_bars`` is the label horizon **in bars**, so the purge and the
    embargo follow the horizon the labels were built with rather than the
    default constant (F7).
    """
    return make_folds(
        labelled,
        train_months=train_months,
        valid_months=valid_months,
        test_months=test_months,
        embargo_minutes=embargo_minutes,
        bar_interval_minutes=bar_interval_minutes,
        horizon_bars=horizon_bars,
    )


def train_walk_forward(
    candidates: pd.DataFrame,
    bars: pd.DataFrame | None = None,
    *,
    symbol: str,
    timeframe: str = "1m",
    run_root: str | Path = "artifacts",
    decision_threshold: float = DECISION_THRESHOLD,
    gate_quantile: float = 0.95,
    extra_features: bool = False,
    horizon_bars: int | None = None,
    embargo_minutes: int | None = None,
    bar_interval_minutes: int | None = None,
    dry_run: bool = False,
) -> dict:
    """Train the walk-forward meta-labeler and write the D3 artefacts.

    Returns the run report (also written to ``walk_forward_index.json``).
    """
    run_root = Path(run_root)
    # The D3 layout is ``{run_root}/models/{symbol}/{asof_YYYYMMDD}/``, and
    # the backtest's default ``--models-root`` is ``artifacts/models`` -- the
    # same directory when the run root is ``artifacts`` (F2).
    models_root = run_root / "models"
    interval = bar_interval_minutes
    if interval is None:
        interval = (
            _infer_bar_interval_minutes(bars) if bars is not None else DEFAULT_BAR_INTERVAL_MINUTES
        )

    consistency = candidate_consistency_report(candidates)
    features_frame = build_features(candidates, bars, extra_features=extra_features)
    used, excluded = resolve_feature_list(features_frame, extra_features=extra_features)
    if not used:
        raise ValueError(
            "no usable feature: every declared feature was excluded "
            f"(excluded={excluded}). The candidate log must carry at least one of "
            f"{list(FEATURE_SOURCES)}."
        )

    if bars is None:
        if "label" not in features_frame.columns:
            raise ValueError(
                "no bars supplied and the candidate log carries no 'label' column -- "
                "the outcome cannot be resolved"
            )
        labelled = features_frame.copy()
    else:
        labelled = build_labels(features_frame, bars, horizon_bars=horizon_bars)

    summary = summarize_labels(labelled)
    nan_fractions = {
        name: (float(labelled[name].isna().mean()) if name in labelled.columns else None)
        for name in used
    }
    folds = plan_folds(
        labelled,
        embargo_minutes=embargo_minutes,
        bar_interval_minutes=interval,
        horizon_bars=horizon_bars,
    )

    report: dict[str, Any] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decision_threshold": decision_threshold,
        "feature_list": used,
        "excluded_features": excluded,
        "feature_availability": {
            name: FEATURE_AVAILABILITY.get(name, "") for name in used + excluded
        },
        "embargo_minutes": folds[0].embargo_minutes if folds else embargo_minutes,
        "horizon_minutes": max_holding_minutes(interval),
        "label_horizon_bars": horizon_bars,
        "bar_interval_minutes": interval,
        "label_summary": summary,
        "candidate_consistency": consistency,
        "feature_nan_fraction": nan_fractions,
        "n_folds": len(folds),
        "folds": [],
    }

    if dry_run:
        report["dry_run"] = True
        report["fold_plan"] = [f.to_dict() for f in folds]
        return report

    lgb = _require_lightgbm()

    results: list[FoldResult] = []
    for fold in folds:
        result = FoldResult(fold=fold)
        train_all = labelled.iloc[fold.train_idx]
        valid_all = labelled.iloc[fold.valid_idx]
        test_all = labelled.iloc[fold.test_idx]
        train = _prepare(train_all, used)
        valid = _prepare(valid_all, used)
        test = _prepare(test_all, used)

        result.n_train = len(train)
        result.n_valid = len(valid)
        result.n_test = len(test)
        result.positives_train = _count_positives(train)
        result.positives_valid = _count_positives(valid)
        result.positives_test = _count_positives(test)

        # --- degenerate-fold guard ----------------------------------------
        if len(train) < MIN_TRAIN_ROWS:
            result.status = "skipped"
            result.reason = f"n_train={len(train)} < MIN_TRAIN_ROWS={MIN_TRAIN_ROWS}"
        elif result.positives_train < MIN_POSITIVES_TRAIN:
            result.status = "skipped"
            result.reason = (
                f"positives_train={result.positives_train} < "
                f"MIN_POSITIVES_TRAIN={MIN_POSITIVES_TRAIN} "
                "(degenerate base rate)"
            )
        elif len(valid) == 0:
            result.status = "skipped"
            result.reason = "empty validation fold"
        elif result.positives_valid < MIN_POSITIVES_VALID:
            result.status = "skipped"
            result.reason = (
                f"positives_valid={result.positives_valid} < "
                f"MIN_POSITIVES_VALID={MIN_POSITIVES_VALID}"
            )

        if result.status == "trained":
            booster, info = _train_one_fold(lgb, train, valid, used)
            # --- calibration + the gate threshold (validation fold) -------
            calibration = None
            gate_threshold = float(decision_threshold)
            if not valid.empty:
                vp = np.asarray(
                    booster.predict(_matrix(valid, used), num_iteration=booster.best_iteration),
                    dtype="float64",
                )
                vy = valid["label"].astype("int8").to_numpy()
                calibration = _isotonic_pava(vp, vy)
                vp_cal = _apply_calibration(vp, calibration)
                if vp_cal.size:
                    gate_threshold = float(np.quantile(vp_cal, float(gate_quantile)))
            metrics = _evaluate(
                booster, test, used, gate_threshold, calibration=calibration
            )
            metrics["gate_threshold"] = gate_threshold
            metrics["gate_quantile"] = float(gate_quantile)
            metrics["calibration"] = calibration
            result.metrics = {
                **info,
                **metrics,
                **_model_diagnostics(booster, train, used),
            }
            result.auc_test = metrics.get("auc_test")
            result.accuracy_test = metrics.get("accuracy_test")

            model_dir = model_dir_for(run_root, symbol, fold.asof_compact)
            model_dir.mkdir(parents=True, exist_ok=True)
            booster.save_model(
                str(model_dir / MODEL_FILENAME), num_iteration=booster.best_iteration
            )
            meta = _meta_json(
                symbol=symbol,
                timeframe=timeframe,
                fold=fold,
                decision_threshold=decision_threshold,
                features=used,
                excluded=excluded,
                result=result,
                summary=summary,
                bar_interval_minutes=interval,
            )
            (model_dir / META_FILENAME).write_text(
                json.dumps(_json_safe(meta), indent=2, allow_nan=False), encoding="utf-8"
            )
            # The D3 layout is ``artifacts/models/{symbol}/{asof_YYYYMMDD}/``,
            # so the index records the path **relative to the models root** --
            # that is the root the backtest's ``--models-root`` points at.
            result.model_dir = str(model_dir)
            result.model_rel_dir = f"{symbol}/asof_{fold.asof_compact}"

        results.append(result)

    index = _index_json(report, results)
    for result in results:
        if result.model_dir:
            (Path(result.model_dir) / INDEX_FILENAME).write_text(
                json.dumps(_json_safe(index), indent=2, allow_nan=False), encoding="utf-8"
            )
    # The index lives beside the models, under the D3 layout, so that the
    # backtest finds it at its default ``--models-root`` (F2).
    models_root.mkdir(parents=True, exist_ok=True)
    (models_root / symbol / INDEX_FILENAME).write_text(
        json.dumps(_json_safe(index), indent=2, allow_nan=False), encoding="utf-8"
    )
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / INDEX_FILENAME).write_text(
        json.dumps(_json_safe(index), indent=2, allow_nan=False), encoding="utf-8"
    )
    report["index"] = index
    return report


def _meta_json(
    *,
    symbol: str,
    timeframe: str,
    fold: Fold,
    decision_threshold: float,
    features: Sequence[str],
    excluded: Sequence[str],
    result: FoldResult,
    summary: dict,
    bar_interval_minutes: int,
) -> dict:
    """The D3 metadata document (every D3 key present, plus the D12 exclusions)."""
    meta = {
        "symbol": symbol,
        "timeframe": timeframe,
        "asof": fold.asof.strftime("%Y-%m-%d"),
        "asof_basis": "end of the validation window (= the start of the test window)",
        "train_start": fold.train_start.strftime("%Y-%m-%d"),
        "train_end": fold.train_end.strftime("%Y-%m-%d"),
        "valid_start": fold.valid_start.strftime("%Y-%m-%d"),
        "valid_end": fold.valid_end.strftime("%Y-%m-%d"),
        "test_start": fold.test_start.strftime("%Y-%m-%d"),
        "test_end": fold.test_end.strftime("%Y-%m-%d"),
        "embargo_minutes": fold.embargo_minutes,
        "feature_list": list(features),
        "decision_threshold": decision_threshold,
        "gate_threshold": result.metrics.get("gate_threshold"),
        "gate_quantile": result.metrics.get("gate_quantile"),
        "calibration": result.metrics.get("calibration"),
        "n_train": result.n_train,
        "n_valid": result.n_valid,
        "n_test": result.n_test,
        "positives_train": result.positives_train,
        "positives_test": result.positives_test,
        "auc_test": result.auc_test,
        "accuracy_test": result.accuracy_test,
        # --- informative extras (D12 requires the exclusions to be recorded) ---
        "excluded_features": list(excluded),
        "horizon_minutes": fold.horizon_minutes,
        "bar_interval_minutes": int(bar_interval_minutes),
        "scale_pos_weight": result.metrics.get("scale_pos_weight"),
        "best_iteration": result.metrics.get("best_iteration"),
        # the degradation monitor's inputs (L4 §F.3): the training
        # prediction distribution and the feature importances
        "train_prediction_distribution": result.metrics.get(
            "train_prediction_distribution"
        ),
        "feature_importances_top10": result.metrics.get("feature_importances_top10"),
        "base_rate_train": (
            result.positives_train / result.n_train if result.n_train else None
        ),
        "base_rate_test": result.metrics.get("base_rate_test"),
        "accuracy_test_at_threshold": result.metrics.get("accuracy_test_at_threshold"),
        "n_pass": result.metrics.get("n_pass"),
        "pass_win_rate": result.metrics.get("pass_win_rate"),
        "expectancy_r_test": result.metrics.get("expectancy_r_test"),
        # the model's lift over the base rate -- A3's input (a high-AUC model
        # with no lift has learned the cost, not the edge)
        "expectancy_lift_r": result.metrics.get("expectancy_lift_r"),
        "pass_expectancy_r": result.metrics.get("pass_expectancy_r"),
        "accuracy_test_definition": "accuracy of the classifier's own argmax (prob >= 0.5)",
        "accounting_note": (
            "expectancy_r_test / pass_expectancy_r are computed on the per-fold CENSUS of "
            "candidates, not on the one-position-at-a-time accounting (D4). The "
            "authoritative expectancy comparison is the backtest leaf's job."
        ),
        "label_summary": summary,
    }
    return meta


def _index_json(report: dict, results: Sequence[FoldResult]) -> dict:
    """The ordered list of fold directories (D3)."""
    return {
        "symbol": report["symbol"],
        "timeframe": report["timeframe"],
        "generated_at": report["generated_at"],
        "decision_threshold": report["decision_threshold"],
        "feature_list": report["feature_list"],
        "excluded_features": report["excluded_features"],
        "embargo_minutes": report["embargo_minutes"],
        "horizon_minutes": report["horizon_minutes"],
        "label_summary": report["label_summary"],
        "candidate_consistency": report["candidate_consistency"],
        "feature_nan_fraction": report["feature_nan_fraction"],
        "folds": [
            {
                **r.fold.to_dict(),
                "status": r.status,
                "reason": r.reason,
                "model_dir": r.model_rel_dir or r.model_dir,
                "model_file": f"{r.model_rel_dir}/{MODEL_FILENAME}" if r.model_rel_dir else None,
                "meta_file": f"{r.model_rel_dir}/{META_FILENAME}" if r.model_rel_dir else None,
                "auc_test": r.auc_test,
                "accuracy_test": r.accuracy_test,
                "metrics": r.metrics,
            }
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m dodgys_dd_quant.ml_pipeline.train_meta_labeler",
        description="Rolling walk-forward meta-labeler (D3 artefact producer).",
    )
    parser.add_argument(
        "--candidates",
        default=None,
        help="D2 candidate log (Parquet); defaults to the rule-only archive "
             "logs/rule_candidates/candidates.parquet when it exists",
    )
    parser.add_argument("--bars", default=None, help="market series (Parquet)")
    parser.add_argument("--symbol", default=None, help="symbol id (default: from the log)")
    parser.add_argument("--timeframe", default="1m")
    parser.add_argument("--run-root", default="artifacts", help="run root (D3: artifacts/)")
    parser.add_argument("--decision-threshold", type=float, default=DECISION_THRESHOLD)
    parser.add_argument(
        "--gate-quantile",
        type=float,
        default=0.95,
        help="the share of the validation fold the gate admits (0.95 = top 5%%); "
             "the resulting probability is stored as the fold's gate_threshold",
    )
    parser.add_argument("--horizon-bars", type=int, default=None, help="label horizon in bars")
    parser.add_argument("--embargo-minutes", type=int, default=None)
    parser.add_argument("--bar-interval-minutes", type=int, default=None)
    parser.add_argument("--extra-features", action="store_true", help="enable the causal extras")
    parser.add_argument(
        "--dry-run", action="store_true", help="validate the schemas, plan the folds, train nothing"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.candidates is None:
        default = Path("logs/rule_candidates/candidates.parquet")
        if not default.exists():
            raise SystemExit(
                "no --candidates given and logs/rule_candidates/candidates.parquet "
                "does not exist; run the matrix first (dodgys_dd_quant.backtest.matrix)"
            )
        args.candidates = str(default)
        print(f"candidates: {default} (the rule-only archive)")
    candidates = load_candidates(args.candidates)
    bars = load_bars(args.bars) if args.bars else None
    symbol = args.symbol
    if symbol is None:
        if "symbol" in candidates.columns and candidates["symbol"].nunique() == 1:
            symbol = str(candidates["symbol"].iloc[0])
        else:
            raise SystemExit("--symbol is required (the log has no single 'symbol' value)")

    try:
        report = train_walk_forward(
            candidates,
            bars,
            symbol=symbol,
            timeframe=args.timeframe,
            run_root=args.run_root,
            decision_threshold=args.decision_threshold,
            gate_quantile=args.gate_quantile,
            extra_features=args.extra_features,
            horizon_bars=args.horizon_bars,
            embargo_minutes=args.embargo_minutes,
            bar_interval_minutes=args.bar_interval_minutes,
            dry_run=args.dry_run,
        )
    except LightGBMUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    summary = report["label_summary"]
    print(f"symbol            : {report['symbol']} ({report['timeframe']})")
    print(f"candidates        : {summary['n_candidates']}")
    print(
        f"labelled          : {summary['n_labelled']} "
        f"(target {summary['n_target']}, stop {summary['n_stop']}, "
        f"unlabelled {summary['n_unlabelled']})"
    )
    print(f"base rate         : {summary['base_rate']:.4f}")
    print(f"features used     : {report['feature_list']}")
    if report["excluded_features"]:
        print(f"features excluded : {report['excluded_features']}")
    print(f"embargo           : {report['embargo_minutes']} min")
    print(f"folds             : {report['n_folds']}")

    if args.dry_run:
        print("\nfold plan (dry run -- nothing was trained):")
        for fold in report["fold_plan"]:
            print(
                f"  #{fold['index']:>2}  train {fold['train_start']}..{fold['train_end']} "
                f"({fold['n_train']:>7})  valid {fold['valid_start']}..{fold['valid_end']} "
                f"({fold['n_valid']:>6})  test {fold['test_start']}..{fold['test_end']} "
                f"({fold['n_test']:>7})"
            )
        return 0

    print("\nfold results:")
    for fold in report["index"]["folds"]:
        if fold["status"] != "trained":
            print(f"  #{fold['index']:>2}  SKIPPED: {fold['reason']}")
            continue
        m = fold["metrics"]
        auc = m.get("auc_test")
        auc_text = "n/a" if auc is None or math.isnan(auc) else f"{auc:.4f}"
        print(
            f"  #{fold['index']:>2}  asof {fold['asof']}  n_train {fold['n_train']:>7}  "
            f"n_test {fold['n_test']:>6}  auc_test {auc_text}  "
            f"pass {m.get('n_pass')}  pass_win {m.get('pass_win_rate')}  "
            f"E[R] base {m.get('expectancy_r_test')}  E[R] gated {m.get('pass_expectancy_r')}"
        )
    # The two E[R] figures above are **census** statistics: every candidate in
    # the test fold is scored as if it were a trade, so many of them are open
    # at the same time.  D4 records that the concurrent arm's t-statistic
    # (t = 15.28) is an artefact of exactly that, and that only the
    # one-position-at-a-time arm may be quoted.  These numbers are printed
    # for diagnosis and must not be read as a result.
    print(
        "\nNOTE: the E[R] figures above are a CENSUS over the test fold -- every\n"
        "      candidate is scored as if it were an open trade, so many overlap in\n"
        "      time.  They are NOT a result: D4 shows the concurrent arm's\n"
        "      t-statistic is an artefact of that.  Quote only the\n"
        "      one-position-at-a-time portfolio from the backtest (D4)."
    )
    print(f"\nartefacts: {Path(args.run_root) / 'models' / report['symbol']}/<asof>/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
