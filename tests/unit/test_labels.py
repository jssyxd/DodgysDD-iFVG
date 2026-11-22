"""Unit tests for the binary meta-label and for the no-look-ahead guarantee.

Run with::

    .venv-ml/bin/python -m pytest tests/unit -q

These tests need neither the data lake nor the network.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from dodgys_dd_quant.ml_pipeline.features import (
    assert_no_lookahead,
    build_features,
    candidate_consistency_report,
    minutes_from_us_open,
    resolve_feature_list,
)
from dodgys_dd_quant.ml_pipeline.labels import (
    LABEL_STOP,
    LABEL_TARGET,
    LABEL_UNLABELLED,
    build_labels,
    summarize_labels,
)

BASE = pd.Timestamp("2024-01-01", tz="UTC")
NS_MIN = 60 * 1_000_000_000


def ts(minute: int) -> int:
    """Epoch-ns of ``minute`` minutes after the base timestamp."""
    return int(BASE.value) + minute * NS_MIN


def make_bars(rows: list[tuple[int, float, float, float, float]]) -> pd.DataFrame:
    """Build a bar frame from ``(minute, open, high, low, close)`` tuples."""
    return pd.DataFrame(
        {
            "ts_event": [ts(m) for m, *_ in rows],
            "open": [r[1] for r in rows],
            "high": [r[2] for r in rows],
            "low": [r[3] for r in rows],
            "close": [r[4] for r in rows],
        }
    )


def make_candidate(
    minute: int = 0,
    *,
    side: int = 1,
    entry: float = 100.0,
    stop: float = 99.0,
    target: float = 102.0,
    risk: float | None = None,
) -> dict:
    """One D2-shaped candidate row (long by default, 1R stop, 2R target)."""
    event = ts(minute)
    open_minutes = float(minutes_from_us_open(pd.Series([event])).iloc[0])
    return {
        "ts_event": event,
        "symbol": "TEST",
        "side": side,
        "entry_price": entry,
        "stop_price": stop,
        "target_price": target,
        "risk": (abs(entry - stop) if risk is None else risk),
        "fvg_low": 99.5,
        "fvg_high": 100.5,
        "fvg_bar1": minute - 3,
        "fvg_bar3": minute - 1,
        "confirm_bar": minute,
        "bars_to_inversion": 1,
        "minutes_from_us_open": open_minutes,
        "checklist_score": 3.0,
        "smt_divergence": -1,
        "sweep_detected": 1,
        "vxn_known": np.nan,
        "vxn_regime": np.nan,
        "vision_iou": np.nan,
        "vision_confidence": np.nan,
    }


# ---------------------------------------------------------------------------
# 1. label correctness
# ---------------------------------------------------------------------------
def test_target_hit_is_label_one():
    bars = make_bars(
        [
            (0, 100.0, 100.5, 99.5, 100.0),
            (1, 100.0, 101.0, 99.8, 100.5),
            (2, 100.5, 103.0, 100.2, 102.5),
        ]
    )
    labelled = build_labels(pd.DataFrame([make_candidate(0)]), bars)
    row = labelled.iloc[0]
    assert row["label"] == LABEL_TARGET
    assert row["r_multiple"] == pytest.approx(2.0)
    assert row["bars_held"] == 2


def test_stop_hit_is_label_zero():
    bars = make_bars(
        [
            (0, 100.0, 100.5, 99.5, 100.0),
            (1, 100.0, 100.2, 98.0, 98.5),
        ]
    )
    labelled = build_labels(pd.DataFrame([make_candidate(0)]), bars)
    row = labelled.iloc[0]
    assert row["label"] == LABEL_STOP
    assert row["r_multiple"] == pytest.approx(-1.0)


def test_tie_resolves_as_stop():
    """A bar that touches both the stop and the target resolves as a **stop**."""
    bars = make_bars(
        [
            (0, 100.0, 100.5, 99.5, 100.0),
            (1, 100.0, 103.0, 98.0, 100.0),
        ]
    )
    labelled = build_labels(pd.DataFrame([make_candidate(0)]), bars)
    row = labelled.iloc[0]
    assert row["label"] == LABEL_STOP
    assert row["r_multiple"] == pytest.approx(-1.0)


def test_short_trade_labels():
    """A short trade mirrors the long conventions."""
    bars = make_bars(
        [
            (0, 100.0, 100.5, 99.5, 100.0),
            (1, 100.0, 100.2, 98.0, 98.5),
        ]
    )
    candidate = make_candidate(0, side=-1, entry=100.0, stop=101.0, target=98.0)
    labelled = build_labels(pd.DataFrame([candidate]), bars)
    row = labelled.iloc[0]
    assert row["label"] == LABEL_TARGET
    assert row["r_multiple"] == pytest.approx(2.0)


def test_still_open_is_unlabelled_not_zero():
    """A trade that never resolves stays unlabelled -- it is NOT a loss."""
    bars = make_bars(
        [
            (0, 100.0, 100.5, 99.5, 100.0),
            (1, 100.0, 100.4, 99.6, 100.1),
            (2, 100.1, 100.6, 99.7, 100.2),
        ]
    )
    labelled = build_labels(pd.DataFrame([make_candidate(0)]), bars)
    row = labelled.iloc[0]
    assert row["label"] == LABEL_UNLABELLED
    assert np.isnan(row["r_multiple"])
    assert pd.isna(row["bars_held"])


def test_trade_open_at_the_end_of_the_series_is_unlabelled():
    bars = make_bars([(0, 100.0, 100.5, 99.5, 100.0), (1, 100.0, 100.5, 99.5, 100.0)])
    labelled = build_labels(pd.DataFrame([make_candidate(1)]), bars)
    assert labelled.iloc[0]["label"] == LABEL_UNLABELLED


def test_horizon_bounds_the_scan():
    """A stop that only appears after the horizon leaves the trade unlabelled."""
    rows = [(0, 100.0, 100.5, 99.5, 100.0)]
    rows += [(m, 100.0, 100.2, 99.8, 100.0) for m in range(1, 5)]
    rows += [(5, 100.0, 100.2, 98.0, 98.5)]
    bars = make_bars(rows)
    labelled = build_labels(pd.DataFrame([make_candidate(0)]), bars, horizon_bars=3)
    assert labelled.iloc[0]["label"] == LABEL_UNLABELLED
    labelled = build_labels(pd.DataFrame([make_candidate(0)]), bars, horizon_bars=6)
    assert labelled.iloc[0]["label"] == LABEL_STOP


def test_entry_bar_itself_cannot_resolve_the_trade():
    """Only bars strictly after ``ts_event`` may resolve the trade."""
    bars = make_bars([(0, 100.0, 103.0, 98.0, 100.0), (1, 100.0, 100.5, 99.5, 100.0)])
    labelled = build_labels(pd.DataFrame([make_candidate(0)]), bars)
    # the confirmation bar touched both sides, but the trade did not exist yet
    assert labelled.iloc[0]["label"] == LABEL_UNLABELLED


# ---------------------------------------------------------------------------
# 2. data integrity
# ---------------------------------------------------------------------------
def test_non_positive_risk_is_rejected():
    bars = make_bars([(0, 100.0, 100.5, 99.5, 100.0)])
    candidate = make_candidate(0, risk=0.0)
    with pytest.raises(ValueError, match="risk"):
        build_labels(pd.DataFrame([candidate]), bars)


def test_target_on_the_wrong_side_is_rejected():
    bars = make_bars([(0, 100.0, 100.5, 99.5, 100.0)])
    candidate = make_candidate(0, target=98.0)
    with pytest.raises(ValueError, match="target"):
        build_labels(pd.DataFrame([candidate]), bars)


def test_stop_on_the_wrong_side_is_rejected():
    bars = make_bars([(0, 100.0, 100.5, 99.5, 100.0)])
    candidate = make_candidate(0, stop=101.0)
    with pytest.raises(ValueError, match="stop"):
        build_labels(pd.DataFrame([candidate]), bars)


# ---------------------------------------------------------------------------
# 3. base rate / class balance
# ---------------------------------------------------------------------------
def test_base_rate_and_class_balance():
    """The base rate counts the labelled rows only -- unlabelled rows are excluded."""
    bars = make_bars(
        [
            (0, 100.0, 100.5, 99.5, 100.0),
            (1, 100.0, 100.2, 98.0, 98.5),   # stop
            (2, 100.0, 100.2, 99.8, 100.0),
            (3, 100.0, 103.0, 99.8, 102.0),   # target
            (4, 100.0, 100.2, 99.8, 100.0),
            (5, 100.0, 100.2, 99.8, 100.0),
            (6, 100.0, 100.2, 99.8, 100.0),
            (7, 100.0, 100.2, 99.8, 100.0),   # never resolves -> unlabelled
        ]
    )
    candidates = pd.DataFrame([make_candidate(m) for m in (0, 1, 2, 3)])
    candidates = pd.concat([candidates, pd.DataFrame([make_candidate(6)])], ignore_index=True)
    labelled = build_labels(candidates, bars)
    summary = summarize_labels(labelled)
    assert summary["n_candidates"] == 5
    assert summary["n_target"] == 2
    assert summary["n_stop"] == 1
    assert summary["n_unlabelled"] == 2
    assert summary["n_labelled"] == 3
    assert summary["base_rate"] == pytest.approx(2 / 3)
    assert summary["class_balance_neg_to_pos"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 4. no look-ahead
# ---------------------------------------------------------------------------
def _feature_fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = [
        (m, 100.0 + m * 0.1, 100.6 + m * 0.1, 99.4 + m * 0.1, 100.1 + m * 0.1)
        for m in range(30)
    ]
    bars = make_bars(rows)
    candidates = pd.DataFrame([make_candidate(m) for m in (1, 5, 9, 13, 20)])
    return candidates, bars


def test_features_are_invariant_to_the_future():
    """Rewriting the market data after ``ts_event`` must not change the features."""
    candidates, bars = _feature_fixture()
    features = build_features(candidates, bars, extra_features=True)
    assert_no_lookahead(
        candidates,
        features,
        bars=bars,
        perturb_from=ts(15),
        extra_features=True,
    )


def test_look_ahead_check_detects_a_leaky_feature():
    """Negative control: a feature computed from the future *must* be caught."""
    candidates, bars = _feature_fixture()
    features = build_features(candidates, bars)
    leaky = features.copy()
    # a value that is only knowable in the future: the last close of the series
    leaky["checklist_score"] = float(bars["close"].iloc[-1])
    with pytest.raises(AssertionError, match="look-ahead"):
        assert_no_lookahead(candidates, leaky, bars=bars, perturb_from=ts(15))


def test_look_ahead_check_rejects_an_undeclared_column():
    candidates, bars = _feature_fixture()
    features = build_features(candidates, bars)
    features["mystery"] = 1.0
    with pytest.raises(AssertionError, match="undeclared"):
        assert_no_lookahead(candidates, features, bars=bars, perturb_from=ts(15))


def test_vision_feature_is_excluded_when_absent_or_all_nan():
    """D12: the pipeline runs without the vision layer and records the exclusion."""
    candidates, bars = _feature_fixture()
    features = build_features(candidates, bars)
    used, excluded = resolve_feature_list(features)
    assert "vision_confidence" not in used
    assert "vision_confidence" in excluded
    assert "checklist_score" in used

    with_vision = features.copy()
    with_vision["vision_confidence"] = 0.42
    used2, excluded2 = resolve_feature_list(with_vision)
    assert "vision_confidence" in used2
    assert "vision_confidence" not in excluded2


def test_strict_mode_rejects_an_inconsistent_log():
    """The recomputed definition wins; ``strict=True`` turns the mismatch into an error."""
    candidates, bars = _feature_fixture()
    candidates["minutes_from_us_open"] = 999.0
    with pytest.raises(ValueError, match="minutes_from_us_open"):
        build_features(candidates, bars, strict=True)
    report = candidate_consistency_report(candidates)
    assert report["minutes_from_us_open_mismatches"] == len(candidates)
    # the default is forgiving: the recomputed value is used
    features = build_features(candidates, bars)
    assert (features["minutes_from_us_open"] != 999.0).all()
def test_minutes_from_us_open_is_recomputed_from_ts_event():
    """09:30 ET == 0 minutes; 11:00 ET == 90 minutes."""
    candidates = pd.DataFrame([make_candidate(0)])
    candidates["ts_event"] = [
        int(pd.Timestamp("2024-01-02 14:30", tz="UTC").value),  # 09:30 ET (January, EST)
        ]
    bars = make_bars([(0, 100.0, 100.5, 99.5, 100.0)])
    features = build_features(candidates, bars)
    assert features["minutes_from_us_open"].iloc[0] == pytest.approx(0.0)
