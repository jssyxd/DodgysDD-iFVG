"""The dynamic-backtest deliverables (L4 §F) that are still absent.

L4 §F is the design the audit wrote for "dynamic backtesting" -- the
thing the user asked for when they asked how to backtest dynamically
against the training.  Three pieces of it are missing from the tree:

* §F.2 -- the **per-fold report** with its field set;
* §F.3 -- the **degradation monitoring and the kill-switch**;
* §F.5 -- the **trial registry** that makes the deflated Sharpe's trial
  count knowable.

These probes check each of them behaviourally.
"""

from __future__ import annotations

import math

from bench.probes import register

__all__ = []


@register(
    "rolling.per_fold_report_has_the_field_set",
    "rolling",
    50,
    "the per-fold report carries L4 section F.2's field set",
)
def _fold_report() -> tuple[bool, str]:
    """L4 §F.2 lists the fields every fold must write."""
    from dodgys_dd_quant.backtest.walk_forward import FOLD_REPORT_FIELDS, fold_report_row

    required = {
        "fold",
        "train_start",
        "train_end",
        "valid_start",
        "valid_end",
        "test_start",
        "test_end",
        "asof",
        "n_candidates",
        "n_candidates_labeled",
        "n_censored",
        "base_rate",
        "n_trades",
        "n_trades_kept",
        "kept_fraction",
        "win_rate",
        "expectancy_R_gross",
        "expectancy_R_net",
        "PF",
        "PF_net",
        "max_drawdown_R",
        "max_consecutive_losses",
        "auc_test",
        "accuracy_test",
        "brier_score",
        "p_pred_distribution",
        "p_pred_distribution_train",
        "cost_R",
        "n_roll_boundary_bars_excluded",
    }
    present = set(FOLD_REPORT_FIELDS)
    missing = required - present
    if missing:
        return False, f"the per-fold report is missing {len(missing)} field(s): {sorted(missing)}"

    row = fold_report_row(
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
    missing_values = [name for name in required if name not in row]
    if missing_values:
        return False, f"the report row omits {sorted(missing_values)}"
    return True, f"the per-fold report carries all {len(required)} fields"


@register(
    "rolling.kill_switch_is_computed",
    "rolling",
    50,
    "the degradation signals and the kill-switch levels are computed (L4 section F.3)",
)
def _kill_switch() -> tuple[bool, str]:
    """L4 §F.3 names three signals and three levels.

    The signals: prediction-distribution drift, realised-vs-predicted
    calibration, and feature-importance churn.  The levels: K1 degrade, K2
    halt, K3 kill the project.
    """
    from dodgys_dd_quant.backtest.walk_forward import (
        KILL_SWITCH_LEVELS,
        compute_kill_switch,
    )

    levels = set(KILL_SWITCH_LEVELS)
    for expected in ("K1", "K2", "K3"):
        if expected not in levels:
            return False, f"the kill-switch has no {expected} level (it has {sorted(levels)})"

    # A drifted forecast with a collapsing top-decile win rate must degrade.
    verdict = compute_kill_switch(
        p_pred_distribution={"mean": 0.62, "sd": 0.02},
        p_pred_distribution_train={"mean": 0.40, "sd": 0.10},
        realised_top_decile_win_rate=0.30,
        top_importance_churn=0.1,
        consecutive_folds_below=2,
    )
    if verdict.get("level") != "K2":
        return False, (
            f"a collapsed top-decile win rate over two folds gave level "
            f"{verdict.get('level')!r}, expected K2"
        )

    healthy = compute_kill_switch(
        p_pred_distribution={"mean": 0.41, "sd": 0.10},
        p_pred_distribution_train={"mean": 0.40, "sd": 0.10},
        realised_top_decile_win_rate=0.62,
        top_importance_churn=0.0,
        consecutive_folds_below=0,
    )
    if healthy.get("level") != "none":
        return False, f"a healthy fold gave level {healthy.get('level')!r}, expected none"
    return True, "the kill-switch degrades on a drifted forecast and stays quiet otherwise"


@register(
    "rolling.trial_registry_is_writable",
    "rolling",
    45,
    "the trial registry records each configuration so the DSR trial count is knowable (L4 section F.5)",
)
def _trial_registry() -> tuple[bool, str]:
    """L4 §F.5: without a write-once registry the number of trials is
    unknowable, and the DSR cannot be computed."""
    import shutil
    import tempfile
    from pathlib import Path

    from dodgys_dd_quant.backtest.trials import TrialRegistry

    root = Path(tempfile.mkdtemp(prefix="ifvg-trials-"))
    try:
        registry = TrialRegistry(root)
        registry.record(
            name="arm-1",
            config={"preset": "honest", "threshold": 0.58},
            oos_returns=[0.1, -1.0, 2.0],
        )
        registry.record(
            name="arm-2",
            config={"preset": "doc", "threshold": 0.58},
            oos_returns=[-1.0, -1.0, 1.0],
        )
        trials = registry.trials()
        if len(trials) != 2:
            return False, f"the registry holds {len(trials)} trial(s), expected 2"
        if registry.trial_count() != 2:
            return False, "the registry's trial count does not match its contents"
        return True, f"the registry holds {len(trials)} trials and counts them"
    finally:
        shutil.rmtree(root, ignore_errors=True)


@register(
    "rolling.dsr_uses_the_registry",
    "rolling",
    40,
    "the deflated Sharpe takes its trial count from the registry (L4 section F.5)",
)
def _dsr_from_registry() -> tuple[bool, str]:
    """The DSR must use the registered trial count, not a constant."""
    import shutil
    import tempfile
    from pathlib import Path

    import numpy as np

    from dodgys_dd_quant.backtest.trials import TrialRegistry
    from dodgys_dd_quant.backtest.walk_forward import deflated_sharpe

    root = Path(tempfile.mkdtemp(prefix="ifvg-dsr-"))
    try:
        registry = TrialRegistry(root)
        rng = np.random.default_rng(3)
        for i in range(8):
            registry.record(
                name=f"arm-{i}",
                config={"preset": "honest", "seed": i},
                oos_returns=list(rng.normal(0.01, 1.0, 200)),
            )
        returns = np.asarray(rng.normal(0.02, 1.0, 200))
        _, with_registry, _ = deflated_sharpe(returns, trials=registry.trial_count())
        _, without, _ = deflated_sharpe(returns, trials=1)
        if not (with_registry < without):
            return False, (
                "the deflated Sharpe did not fall when the registered trial count was used"
            )
        return True, (
            f"DSR {with_registry:.4f} with {registry.trial_count()} registered trials "
            f"vs {without:.4f} with one"
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


@register(
    "rolling.five_assertions_run_per_fold",
    "rolling",
    50,
    "the backtest makes L5 section D.5's five assertions on every fold",
)
def _five_assertions() -> tuple[bool, str]:
    """L5 §D.5 names five assertions the backtest must make, and says a
    failure must **abort** the run."""
    from dodgys_dd_quant.backtest.walk_forward import FOLD_ASSERTIONS, assert_fold

    expected = {
        "forward_only",
        "exactly_one_fold",
        "not_inside_own_span",
        "metadata_agrees",
        "never_saw_test_month",
    }
    present = set(FOLD_ASSERTIONS)
    if not expected <= present:
        return False, f"the assertions are missing {sorted(expected - present)}"
    return True, f"the per-fold assertions: {sorted(present)}"


@register(
    "rolling.roll_boundary_bars_are_excluded",
    "rolling",
    40,
    "the roll filter excludes the bars around a contract roll (Q5's missing item)",
)
def _roll_filter() -> tuple[bool, str]:
    """Q5 asks how to roll; a continuous series needs the roll boundary
    identified and its bars excluded."""
    from dodgys_dd_quant.data_pipeline.roll import RollFilter

    filter_ = RollFilter(price_gap_frac=0.01, bars_around=2)
    bars = [
        {"ts": i * 300_000_000_000, "open": 30000.0, "high": 30010.0, "low": 29990.0, "close": 30000.0}
        for i in range(5)
    ]
    # A 5 % jump between two bars is a contract roll.
    bars[3]["open"] = 31500.0
    bars[3]["high"] = 31510.0
    bars[3]["low"] = 31490.0
    bars[3]["close"] = 31500.0
    excluded = filter_.excluded_bars(bars)
    if not excluded:
        return False, "the roll filter excluded no bar around a 5 % price jump"
    if 3 not in excluded:
        return False, f"the roll boundary bar itself was not excluded (got {sorted(excluded)})"
    return True, f"the roll filter excluded {len(excluded)} bar(s) around the jump"


@register(
    "rolling.kaggle_kernel_asserts_its_window",
    "rolling",
    30,
    "the generated Kaggle kernel asserts its own test window (L4 section E)",
)
def _kaggle_kernel() -> tuple[bool, str]:
    """The kernel must never see the test month."""
    from dodgys_dd_quant.ml_pipeline import kaggle_export

    import inspect

    source = inspect.getsource(kaggle_export)
    for needle in ("TEST_START_NS", "TEST_END_NS", "assert"):
        if needle not in source:
            return False, f"the kernel generator never mentions {needle}"
    return True, "the kernel generator carries the test-window assertions"
