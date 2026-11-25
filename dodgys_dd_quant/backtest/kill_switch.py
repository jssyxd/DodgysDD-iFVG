"""The degradation signals and the kill-switch (L4 §F.3).

L4 §F.3 names three observable signals, in order of usefulness, and three
levels:

1. **Prediction-distribution drift** -- the live fold's ``P̂(Win)``
   distribution against the model's own training distribution.  A monotone
   shift of the median by more than 0.05 absolute, or a collapse of the
   spread (``σ < 50 %`` of its training value), means the input
   distribution has moved.
2. **Realised-vs-predicted calibration** -- the realised win rate in the
   top decile of ``P̂`` falls below 0.45 for two consecutive folds.
3. **Feature-importance churn** -- the top features change between
   consecutive folds by more than half their gain.

| Level | Trigger | Action |
|---|---|---|
| **K1** -- degrade | any one of the three signals | stop trading the affected fold; retrain with a longer window; log everything |
| **K2** -- halt | K1 twice within 6 months, or the top-decile win rate below 0.45 for 3 consecutive folds | stop trading entirely; the model is retired |
| **K3** -- kill the project | the §C.6 abort criteria trigger on the concatenated OOS | the strategy is abandoned; publish the negative result |

The levels live in the **backtest**, not in strategy logic: the kill-switch
decides whether to keep trading, and strategy logic decides what to trade.
"""

from __future__ import annotations

import math
from typing import Any

from dodgys_dd_quant.backtest.accounting import accounting_fields

__all__ = [
    "KILL_SWITCH_LEVELS",
    "compute_kill_switch",
]


#: The three levels, in order of severity.
KILL_SWITCH_LEVELS: tuple[str, ...] = ("K1", "K2", "K3")

#: A median shift of more than this (absolute) is a distribution drift.
DRIFT_MEDIAN_SHIFT: float = 0.05

#: The live spread below this fraction of the training spread is a collapse.
DRIFT_SPREAD_COLLAPSE: float = 0.50

#: The realised win rate the top decile of ``P̂`` must clear.
TOP_DECILE_WIN_RATE_FLOOR: float = 0.45

#: How many consecutive folds below the floor the calibration signal needs.
CALIBRATION_FOLDS: int = 2

#: How many consecutive folds below the floor the K2 halt needs.
K2_CALIBRATION_FOLDS: int = 3


def _mean_sd(distribution: dict | None) -> tuple[float, float]:
    if not distribution:
        return float("nan"), float("nan")
    mean = distribution.get("mean")
    sd = distribution.get("sd")
    return (
        float(mean) if mean is not None else float("nan"),
        float(sd) if sd is not None else float("nan"),
    )


def compute_kill_switch(
    *,
    abort_report: Any | None = None,
    p_pred_distribution: dict | None = None,
    p_pred_distribution_train: dict | None = None,
    realised_top_decile_win_rate: float = float("nan"),
    top_importance_churn: float = float("nan"),
    consecutive_folds_below: int = 0,
    k1_folds_within_6_months: int = 0,
    abort_criteria_triggered: bool = False,
) -> dict[str, Any]:
    """Compute the three degradation signals and the level they imply.

    Parameters
    ----------
    p_pred_distribution:
        The live fold's prediction distribution: ``{"mean": ..., "sd": ...}``.
    p_pred_distribution_train:
        The model's own training distribution, the same shape.
    realised_top_decile_win_rate:
        The realised win rate of the candidates the model scored highest.
    top_importance_churn:
        The share of the top features' gain that changed since the previous
        fold.
    consecutive_folds_below:
        How many consecutive folds the top-decile win rate has been below
        the floor.
    k1_folds_within_6_months:
        How many K1 folds there have been in the last six months.
    abort_criteria_triggered:
        Whether the §C.6 abort criteria triggered on the concatenated OOS
        -- the K3 condition.

    Returns
    -------
    dict
        ``level`` -- ``"none"``, ``"K1"``, ``"K2"`` or ``"K3"``; plus the
        three signals and the reason.
    """
    signals: dict[str, bool] = {}

    # The K3 level is the **verdict** of L4 §C.6's five criteria, not a flag
    # somebody has to remember to set.  The explicit flag stays available for
    # the caller that already knows the verdict.
    abort_payload: dict[str, Any] = {}
    if abort_report is not None:
        abort_criteria_triggered = abort_criteria_triggered or bool(
            getattr(abort_report, "triggered", False)
        )
        abort_payload = (
            abort_report.as_dict() if hasattr(abort_report, "as_dict") else {}
        )

    # --- signal 1: prediction-distribution drift ---------------------------
    live_mean, live_sd = _mean_sd(p_pred_distribution)
    train_mean, train_sd = _mean_sd(p_pred_distribution_train)
    shift = (
        abs(live_mean - train_mean)
        if math.isfinite(live_mean) and math.isfinite(train_mean)
        else float("nan")
    )
    spread_ratio = (
        live_sd / train_sd
        if math.isfinite(live_sd) and math.isfinite(train_sd) and train_sd > 0
        else float("nan")
    )
    drift = bool(
        (math.isfinite(shift) and shift > DRIFT_MEDIAN_SHIFT)
        or (math.isfinite(spread_ratio) and spread_ratio < DRIFT_SPREAD_COLLAPSE)
    )
    signals["prediction_drift"] = drift

    # --- signal 2: realised-vs-predicted calibration ----------------------
    below_floor = bool(
        math.isfinite(realised_top_decile_win_rate)
        and realised_top_decile_win_rate < TOP_DECILE_WIN_RATE_FLOOR
    )
    calibration = bool(below_floor and int(consecutive_folds_below) >= CALIBRATION_FOLDS)
    signals["calibration"] = calibration

    # --- signal 3: feature-importance churn -------------------------------
    churn = bool(
        math.isfinite(top_importance_churn) and top_importance_churn > DRIFT_SPREAD_COLLAPSE
    )
    signals["importance_churn"] = churn

    # --- the level ---------------------------------------------------------
    n_signals = sum(1 for fired in signals.values() if fired)
    if abort_criteria_triggered:
        level = "K3"
    elif (
        int(consecutive_folds_below) >= K2_CALIBRATION_FOLDS
        or int(k1_folds_within_6_months) >= 2
        or (n_signals >= 2 and int(consecutive_folds_below) >= CALIBRATION_FOLDS)
    ):
        level = "K2"
    elif n_signals >= 1:
        level = "K1"
    else:
        level = "none"

    return {
        **accounting_fields(),
        "abort_criteria": abort_payload,
        "level": level,
        "signals": signals,
        "n_signals": n_signals,
        "drift_median_shift": shift,
        "drift_spread_ratio": spread_ratio,
        "realised_top_decile_win_rate": float(realised_top_decile_win_rate),
        "top_importance_churn": float(top_importance_churn),
        "consecutive_folds_below": int(consecutive_folds_below),
        "k1_folds_within_6_months": int(k1_folds_within_6_months),
    }
