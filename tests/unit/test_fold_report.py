"""Tests for the per-fold report, the kill-switch, the trial registry and the roll filter."""

from __future__ import annotations

import numpy as np
import pytest

from dodgys_dd_quant.backtest.fold_report import (
    FOLD_ASSERTIONS,
    FOLD_REPORT_FIELDS,
    FoldAssertionError,
    assert_fold,
    fold_report_row,
)
from dodgys_dd_quant.backtest.kill_switch import KILL_SWITCH_LEVELS, compute_kill_switch
from dodgys_dd_quant.backtest.trials import TrialRegistry
from dodgys_dd_quant.data_pipeline.roll import RollFilter


# ---------------------------------------------------------------------------
# The per-fold report (L4 section F.2)
# ---------------------------------------------------------------------------


def _row(**overrides):
    kwargs = dict(
        fold_index=0,
        windows={
            "train_start": "2023-01-01",
            "train_end": "2023-06-01",
            "valid_start": "2023-06-01",
            "valid_end": "2023-07-01",
            "test_start": "2023-07-01",
            "test_end": "2023-08-01",
        },
        asof="2023-07-01",
        n_candidates=100,
        n_candidates_labeled=96,
        n_censored=4,
        n_trades=10,
        n_trades_kept=4,
        win_rate=0.3,
        expectancy_r_gross=0.02,
        expectancy_r_net=-0.01,
        pf=1.01,
        pf_net=0.98,
        max_drawdown_r=1.2,
        max_consecutive_losses=5,
        auc_test=0.51,
        accuracy_test=0.5,
        brier_score=0.25,
        p_pred_distribution=[0.1, 0.3, 0.5, 0.7, 0.9],
        p_pred_distribution_train=[0.1, 0.3, 0.5, 0.7, 0.9],
        cost_r=0.05,
        n_roll_boundary_bars_excluded=0,
    )
    kwargs.update(overrides)
    return fold_report_row(**kwargs)


def test_the_report_carries_every_field():
    row = _row()
    missing = [name for name in FOLD_REPORT_FIELDS if name not in row]
    assert missing == []


def test_the_kept_fraction_is_the_funnel_ratio():
    assert _row()["kept_fraction"] == pytest.approx(4 / 10)


def test_the_base_rate_is_per_fold_not_assumed():
    assert np.isnan(_row()["base_rate"])
    assert _row(base_rate=0.31)["base_rate"] == pytest.approx(0.31)


# ---------------------------------------------------------------------------
# The five assertions (L5 section D.5)
# ---------------------------------------------------------------------------


def _ns(text: str) -> int:
    """``YYYY-MM-DD`` -> nanoseconds since the epoch (UTC midnight)."""
    import datetime as dt

    y, m, d = (int(x) for x in text.split("-"))
    return int(dt.datetime(y, m, d, tzinfo=dt.timezone.utc).timestamp() * 1_000_000_000)


class _Fold:
    def __init__(self, **kwargs):
        self.asof = kwargs.get("asof", "2023-07-01")
        self.asof_ns = kwargs.get("asof_ns", _ns(self.asof))
        self.test_start = kwargs.get("test_start", "2023-07-01")
        self.meta = kwargs.get("meta", {})


def test_the_five_assertions_are_named():
    assert set(FOLD_ASSERTIONS) == {
        "forward_only",
        "exactly_one_fold",
        "not_inside_own_span",
        "metadata_agrees",
        "never_saw_test_month",
    }


def test_a_clean_fold_passes():
    fold = _Fold(meta={"asof": "2023-07-01", "max_ts_read": _ns("2023-06-30")})
    assert_fold(
        fold,
        rows_ts=[_ns("2023-07-01") + 3_600_000_000_000],
        next_asof_ns=_ns("2023-08-01"),
    )


def test_a_candidate_before_the_boundary_fails_the_forward_only_assertion():
    fold = _Fold()
    with pytest.raises(FoldAssertionError, match="forward_only"):
        assert_fold(fold, rows_ts=[_ns("2023-06-30")])


def test_a_candidate_inside_the_own_test_span_fails():
    # The asof is the day *before* the test window, so a candidate in
    # between is forward-only-clean but still inside the fold's own span.
    fold = _Fold(asof="2023-06-30", meta={"test_start": "2023-07-01"})
    with pytest.raises(FoldAssertionError, match="not_inside_own_span"):
        assert_fold(fold, rows_ts=[_ns("2023-06-30") + 3_600_000_000_000])


def test_a_candidate_belonging_to_the_next_fold_fails():
    fold = _Fold()
    with pytest.raises(FoldAssertionError, match="exactly_one_fold"):
        assert_fold(
            fold,
            rows_ts=[_ns("2023-08-01") + 1],
            next_asof_ns=_ns("2023-08-01"),
        )


def test_feature_drift_fails_the_metadata_assertion():
    fold = _Fold(meta={"asof": "2023-07-01", "feature_list": ["a", "b"]})
    with pytest.raises(FoldAssertionError, match="metadata_agrees"):
        assert_fold(
            fold,
            rows_ts=[_ns("2023-07-01") + 3_600_000_000_000],
            backtest_feature_list=["a", "c"],
        )


def test_a_model_that_read_the_test_month_fails():
    fold = _Fold(meta={"max_ts_read": _ns("2023-07-02"), "test_start": "2023-07-01"})
    with pytest.raises(FoldAssertionError, match="never_saw_test_month"):
        assert_fold(fold, rows_ts=[_ns("2023-07-02") + 1])


# ---------------------------------------------------------------------------
# The kill-switch (L4 section F.3)
# ---------------------------------------------------------------------------


def test_the_three_levels_exist():
    assert KILL_SWITCH_LEVELS == ("K1", "K2", "K3")


def test_a_healthy_fold_raises_nothing():
    verdict = compute_kill_switch(
        p_pred_distribution={"mean": 0.41, "sd": 0.10},
        p_pred_distribution_train={"mean": 0.40, "sd": 0.10},
        realised_top_decile_win_rate=0.62,
        top_importance_churn=0.0,
        consecutive_folds_below=0,
    )
    assert verdict["level"] == "none"


def test_a_single_signal_degrades():
    verdict = compute_kill_switch(
        p_pred_distribution={"mean": 0.41, "sd": 0.10},
        p_pred_distribution_train={"mean": 0.40, "sd": 0.10},
        realised_top_decile_win_rate=0.30,
        top_importance_churn=0.0,
        consecutive_folds_below=2,
    )
    assert verdict["level"] == "K1"
    assert verdict["signals"]["calibration"] is True
    assert verdict["signals"]["prediction_drift"] is False


def test_drift_and_a_collapsed_calibration_halt():
    verdict = compute_kill_switch(
        p_pred_distribution={"mean": 0.62, "sd": 0.02},
        p_pred_distribution_train={"mean": 0.40, "sd": 0.10},
        realised_top_decile_win_rate=0.30,
        top_importance_churn=0.1,
        consecutive_folds_below=2,
    )
    assert verdict["level"] == "K2"


def test_three_consecutive_folds_below_the_floor_halt():
    verdict = compute_kill_switch(
        realised_top_decile_win_rate=0.40,
        consecutive_folds_below=3,
    )
    assert verdict["level"] == "K2"


def test_the_abort_criteria_kill_the_project():
    verdict = compute_kill_switch(abort_criteria_triggered=True)
    assert verdict["level"] == "K3"


# ---------------------------------------------------------------------------
# The trial registry (L4 section F.5)
# ---------------------------------------------------------------------------


def test_the_registry_counts_its_trials(tmp_path):
    registry = TrialRegistry(tmp_path)
    registry.record(name="a", config={"x": 1}, oos_returns=[0.1, -1.0, 2.0])
    registry.record(name="b", config={"x": 2}, oos_returns=[-1.0, -1.0, 1.0])
    assert registry.trial_count() == 2
    assert len(registry.trials()) == 2


def test_the_registry_is_write_once(tmp_path):
    registry = TrialRegistry(tmp_path)
    registry.record(name="a", oos_returns=[1.0])
    with pytest.raises(ValueError, match="write-once"):
        registry.record(name="a", oos_returns=[1.0])


def test_the_registry_survives_a_new_instance(tmp_path):
    TrialRegistry(tmp_path).record(name="a", oos_returns=[1.0, 2.0, 3.0])
    assert TrialRegistry(tmp_path).trial_count() == 1


def test_the_registry_reports_the_trial_statistics(tmp_path):
    registry = TrialRegistry(tmp_path)
    for i in range(4):
        registry.record(
            name=f"arm-{i}",
            oos_returns=list(np.random.default_rng(i).normal(0.01, 1.0, 100)),
        )
    stats = registry.trial_statistics()
    assert stats["n_trials"] == 4
    assert np.isfinite(stats["trial_sharpe_variance"])


# ---------------------------------------------------------------------------
# The roll filter (Q5)
# ---------------------------------------------------------------------------


def _bars(prices):
    return [
        {"ts": i * 300_000_000_000, "open": p, "high": p, "low": p, "close": p}
        for i, p in enumerate(prices)
    ]


def test_a_continuous_series_has_no_roll_boundary():
    filter_ = RollFilter(price_gap_frac=0.01, bars_around=2)
    assert filter_.excluded_bars(_bars([30000.0] * 10)) == set()


def test_a_price_jump_is_a_roll_boundary():
    filter_ = RollFilter(price_gap_frac=0.01, bars_around=2)
    excluded = filter_.excluded_bars(_bars([30000.0, 30000.0, 30000.0, 31500.0, 31500.0]))
    assert 3 in excluded


def test_the_filter_excludes_the_boundary_and_its_neighbours():
    filter_ = RollFilter(price_gap_frac=0.01, bars_around=2)
    kept, removed = filter_.filter(_bars([30000.0, 30000.0, 30000.0, 31500.0, 31500.0]))
    # The boundary is bar 3; two bars on each side covers bars 1..4.
    assert removed == 4
    assert len(kept) == 1


def test_the_gap_threshold_is_configurable():
    strict = RollFilter(price_gap_frac=0.10)
    assert strict.excluded_bars(_bars([30000.0, 30000.0, 31500.0])) == set()
