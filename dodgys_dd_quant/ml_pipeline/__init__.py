"""Rolling meta-labeling pipeline (leaf M1).

This module is the **single constants module** of the ML pipeline: every tunable
threshold lives here, never inline in the logic (``AGENTS.md``, "Code Conventions").

Contract references
--------------------
* ``.herd-swarm/decisions.md`` **D2** -- the candidate log this package consumes.
* ``.herd-swarm/decisions.md`` **D3** -- the model artefact this package emits.
* ``.herd-swarm/decisions.md`` **D4** -- the honest baseline (the rule engine has
  no edge; the ML is measured *against that*, not against zero).
* ``.herd-swarm/decisions.md`` **D8** -- ``checklist_score`` is reported, never filtered on.
* ``.herd-swarm/decisions.md`` **D9** -- costs live in the backtest config, not here.
* ``.herd-swarm/decisions.md`` **D12** -- the vision columns are optional; the
  pipeline degrades gracefully and records the exclusion.
* ``research/docs/RULE_SPEC.md`` **T24/T25** -- 6 months train / 1 month validate /
  1 month test, rolled monthly, purged, with an embargo.

Public API is re-exported lazily (PEP 562) so that importing the package never
pulls in LightGBM or any other optional dependency.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# D3 decision rule: take the trade iff P(Win) >= threshold.
# ---------------------------------------------------------------------------
DECISION_THRESHOLD = 0.58

# ---------------------------------------------------------------------------
# Walk-forward geometry (RULE_SPEC T24/T25).
# ---------------------------------------------------------------------------
TRAIN_MONTHS = 6
VALID_MONTHS = 1
TEST_MONTHS = 1
FOLD_STEP_MONTHS = 1

# ---------------------------------------------------------------------------
# Label horizon.  The horizon *is* the maximum holding period: a candidate that
# has hit neither its stop nor its target after LABEL_HORIZON_BARS is "still
# open" and stays unlabelled (D2: label = -1).  The walk-forward embargo is
# derived from it in ``splits.py`` -- it is never assumed.
# ---------------------------------------------------------------------------
LABEL_HORIZON_BARS = 240
DEFAULT_BAR_INTERVAL_MINUTES = 1

# ---------------------------------------------------------------------------
# LightGBM hyper-parameters and the degenerate-fold guards.
# ---------------------------------------------------------------------------
LGBM_NUM_LEAVES = 15
LGBM_LEARNING_RATE = 0.05
LGBM_N_ESTIMATORS = 500
LGBM_EARLY_STOPPING_ROUNDS = 50
LGBM_SEED = 20261122
LGBM_BAGGING_FRACTION = 0.9
LGBM_FEATURE_FRACTION = 0.9

#: A fold with fewer rows than this cannot support a model -> recorded as skipped.
MIN_TRAIN_ROWS = 200
#: A fold with fewer positives than this has a degenerate base rate -> skipped.
MIN_POSITIVES_TRAIN = 20
MIN_POSITIVES_VALID = 5

# ---------------------------------------------------------------------------
# D2 candidate-log schema.
# ---------------------------------------------------------------------------
CANDIDATE_COLUMNS: tuple[str, ...] = (
    "ts_event",
    "symbol",
    "side",
    "entry_price",
    "stop_price",
    "target_price",
    "risk",
    "fvg_low",
    "fvg_high",
    "fvg_bar1",
    "fvg_bar3",
    "confirm_bar",
    "bars_to_inversion",
    "minutes_from_us_open",
    "checklist_score",
    "smt_divergence",
    "sweep_detected",
    "vxn_known",
    "vxn_regime",
    "vision_iou",
    "vision_confidence",
    "label",
    "r_multiple",
)

#: Columns without which a candidate log cannot be interpreted at all.
REQUIRED_CANDIDATE_COLUMNS: tuple[str, ...] = (
    "ts_event",
    "side",
    "entry_price",
    "stop_price",
    "target_price",
    "risk",
)

#: Columns of the market series consumed by this package.
REQUIRED_BAR_COLUMNS: tuple[str, ...] = ("ts_event", "open", "high", "low", "close")

__all__ = [
    "DECISION_THRESHOLD",
    "TRAIN_MONTHS",
    "VALID_MONTHS",
    "TEST_MONTHS",
    "FOLD_STEP_MONTHS",
    "LABEL_HORIZON_BARS",
    "DEFAULT_BAR_INTERVAL_MINUTES",
    "LGBM_NUM_LEAVES",
    "LGBM_LEARNING_RATE",
    "LGBM_N_ESTIMATORS",
    "LGBM_EARLY_STOPPING_ROUNDS",
    "LGBM_SEED",
    "LGBM_BAGGING_FRACTION",
    "LGBM_FEATURE_FRACTION",
    "MIN_TRAIN_ROWS",
    "MIN_POSITIVES_TRAIN",
    "MIN_POSITIVES_VALID",
    "CANDIDATE_COLUMNS",
    "REQUIRED_CANDIDATE_COLUMNS",
    "REQUIRED_BAR_COLUMNS",
    "build_features",
    "build_labels",
    "make_folds",
]


def __getattr__(name: str) -> Any:
    """Lazily re-export the pipeline's public API (PEP 562)."""
    if name == "build_features":
        from dodgys_dd_quant.ml_pipeline.features import build_features

        return build_features
    if name == "build_labels":
        from dodgys_dd_quant.ml_pipeline.labels import build_labels

        return build_labels
    if name == "make_folds":
        from dodgys_dd_quant.ml_pipeline.splits import make_folds

        return make_folds
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
