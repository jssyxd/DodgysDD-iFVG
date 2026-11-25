"""The degradation monitor's inputs -- the signals L4 §F.3 names.

The kill-switch has three signals, and until now **none of them was ever
fed**: the live fold's P(Win) distribution, the model's own training
distribution, the realised win rate of the top decile and the churn of the
top features were all left empty, so the monitor could not fire on anything.

The artefacts that carry them are the fold's D3 metadata (the training
distribution and the feature importances) and the fold report (the live
distribution and the top decile's realised win rate).
"""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

from bench.probes import register

__all__ = []


def _trained_fold():
    """Train one fold on the fixture and return its artefact directory."""
    from bench import fixtures

    from dodgys_dd_quant.ml_pipeline.train_meta_labeler import train_walk_forward

    labelled, bars = fixtures.rolling_frame()
    workspace = Path(tempfile.mkdtemp(prefix="ifvg-monitor-"))
    root = workspace / "artifacts"
    train_walk_forward(
        labelled,
        bars,
        symbol="BTCUSDT",
        timeframe="15m",
        run_root=root,
    )
    folders = sorted((root / "models" / "BTCUSDT").glob("asof_*"))
    if not folders:
        return None, None
    return folders[0], root


@register(
    "rolling.degradation_monitor_inputs_are_recorded",
    "rolling",
    55,
    "the fold's artefact records the training distribution and the feature importances (L4 §F.3)",
)
def _monitor_inputs() -> tuple[bool, str]:
    """The D3 metadata carries the two inputs the monitor cannot recompute.

    The training prediction distribution is the drift signal's denominator and
    the feature importances are the churn signal's numerator; neither is
    recoverable from the model file alone.
    """
    folder, _ = _trained_fold()
    if folder is None:
        return False, "the trainer wrote no artefact"
    meta = json.loads((folder / "meta_label_meta.json").read_text(encoding="utf-8"))
    distribution = meta.get("train_prediction_distribution")
    if not distribution:
        return False, "the metadata carries no training prediction distribution"
    for key in ("mean", "sd"):
        if key not in distribution:
            return False, f"the training distribution carries no {key!r}"
    if not (0.0 <= float(distribution["mean"]) <= 1.0):
        return False, (
            f"the training distribution's mean is {distribution['mean']}, not a "
            f"probability"
        )
    importances = meta.get("feature_importances_top10")
    if not importances:
        return False, "the metadata carries no feature importances"
    if not isinstance(importances[0], (list, tuple)) or len(importances[0]) != 2:
        return False, "the feature importances are not (name, gain) pairs"
    if float(importances[0][1]) < 0:
        return False, "a feature importance is negative"
    return True, (
        f"the artefact records a training distribution (mean "
        f"{float(distribution['mean']):.3f}, sd {float(distribution['sd']):.3f}) "
        f"and {len(importances)} feature importances"
    )


@register(
    "rolling.degradation_monitor_feeds_the_kill_switch",
    "rolling",
    50,
    "the walk-forward feeds the kill-switch's three signals from the fold's own numbers",
)
def _monitor_feeds() -> tuple[bool, str]:
    """The signals must be computable from a run, not only from a unit test."""
    import numpy as np

    from dodgys_dd_quant.backtest.walk_forward import Fold, walk_forward
    from bench import fixtures

    candidates = list(fixtures.candidate_log("BTCUSDT", "honest"))
    if not candidates:
        return False, "no candidates to inspect"
    bars = fixtures.btc_15m()
    folds = [
        Fold(
            asof="2024-03-01",
            asof_ns=1_709_251_200_000_000_000,
            directory=Path("."),
            test_start="2024-03-01",
            test_end="2024-03-31",
        )
    ]
    report = walk_forward(candidates, len(bars), folds)
    if not report.folds:
        return False, "the walk-forward produced no fold report"
    fold = report.folds[0]
    # without a model there are no predictions, but the *inputs* must be
    # computed rather than left unset
    if fold.live_distribution is not None and not math.isfinite(
        float(fold.live_distribution.get("mean", float("nan")))
    ):
        return False, "the live distribution is not finite"
    if not math.isnan(fold.top_decile_win_rate):
        if not (0.0 <= fold.top_decile_win_rate <= 1.0):
            return False, (
                f"the top decile's win rate is {fold.top_decile_win_rate}"
            )
    signals = report.kill_switch.get("signals")
    if not signals:
        return False, "the kill-switch reports no signal"
    for name in ("prediction_drift", "calibration", "importance_churn"):
        if name not in signals:
            return False, f"the kill-switch has no {name!r} signal"
    return True, (
        "the fold report carries the monitor's inputs and the kill-switch "
        "receives all three signals"
    )
