"""The gate's two fixes: calibration and a validation-quantile threshold.

The published runs applied a fixed ``P(Win) >= 0.58`` to uncalibrated
LightGBM scores.  On a 33 % base rate those scores sit in a narrow band around
the base rate, so the gate opened in bursts and stayed closed for years
(61 of 75 ETH 15m folds approved nothing).  These tests pin the two fixes:

* the isotonic fit is monotone and separates a separable sample;
* the scorer takes the threshold from the fold's **validation** quantile, so
  the test window never chooses its own cut.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dodgys_dd_quant.backtest.walk_forward import ModelScorer
from dodgys_dd_quant.backtest.walk_forward import Fold
from dodgys_dd_quant.ml_pipeline.train_meta_labeler import (
    _apply_calibration,
    _isotonic_pava,
)


def test_isotonic_is_monotone_and_separates_a_separable_sample():
    x = np.array([0.30, 0.31, 0.32, 0.70, 0.71, 0.72])
    y = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    cal = _isotonic_pava(x, y)
    assert cal is not None
    fitted = np.asarray(cal["y"], dtype=float)
    assert np.all(np.diff(fitted) >= -1e-12)
    mapped = _apply_calibration(np.array([0.31, 0.71]), cal)
    assert mapped[0] < 0.05 and mapped[1] > 0.95


def test_isotonic_flattens_an_inverted_sample_to_the_base_rate():
    # the model ranks the losers above the winners: calibration must not
    # invent a signal, it collapses to the base rate
    x = np.array([0.9, 0.8, 0.2, 0.1])
    y = np.array([0.0, 0.0, 1.0, 1.0])
    cal = _isotonic_pava(x, y)
    assert cal is not None
    fitted = np.asarray(cal["y"], dtype=float)
    assert np.allclose(fitted, 0.5, atol=1e-12)


def test_calibration_handles_tied_scores():
    x = np.array([0.5, 0.5, 0.5, 0.5])
    y = np.array([0.0, 1.0, 0.0, 1.0])
    cal = _isotonic_pava(x, y)
    assert cal is not None
    assert len(cal["x"]) == 1
    assert cal["y"][0] == pytest.approx(0.5)


def _fold(meta: dict) -> Fold:
    return Fold(asof="2024-01-31", asof_ns=0, directory=Path("."), meta=meta)


def test_the_quantile_gate_reads_the_folds_validation_threshold():
    scorer = ModelScorer(
        _fold({"gate_threshold": 0.41, "feature_list": []}),
        threshold=0.58,
        gate="quantile",
    )
    assert scorer.threshold == pytest.approx(0.41)
    # the model file is absent in this synthetic fold: the scorer says so
    # instead of pretending the model ran
    assert scorer.available is False


def test_the_absolute_gate_keeps_the_documented_threshold():
    scorer = ModelScorer(
        _fold({"gate_threshold": 0.41, "feature_list": []}),
        threshold=0.58,
        gate="absolute",
    )
    assert scorer.threshold == pytest.approx(0.58)
