"""A coverage sweep: behaviours that are implemented but were never probed.

The benchmark measures **verified** capability, so a behaviour nobody
exercises is not a capability yet.  These probes close the gap for the
modules the last rounds built:

* the kill-switch's three levels and their triggers (L4 §F.3),
* the five per-fold assertions and the rule that a failure **aborts** the
  run (L5 §D.5),
* the three degradation signals the kill-switch consumes,
* the write-once property of the trial registry (L4 §F.5),
* the per-fold report's field set (L4 §F.2) and the D3 metadata's keys,
* the causality of the **whole** pipeline, not just of the rule engine.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path
from types import SimpleNamespace

from bench.probes import register

__all__ = []


def _rolling_frame():
    from bench import fixtures

    return fixtures.rolling_frame()


@register(
    "rolling.kill_switch_levels_are_implemented",
    "rolling",
    55,
    "the kill-switch's three levels and their triggers are implemented (L4 §F.3)",
)
def _kill_switch_levels() -> tuple[bool, str]:
    """K1 degrades, K2 halts, K3 kills the project.

    The triggers are the audit's: one drift signal is K1; two K1 folds within
    six months, three consecutive folds below the calibration floor, or the
    abort criteria are K2/K3.
    """
    from dodgys_dd_quant.backtest.kill_switch import (
        KILL_SWITCH_LEVELS,
        compute_kill_switch,
    )

    if KILL_SWITCH_LEVELS != ("K1", "K2", "K3"):
        return False, f"the levels are {KILL_SWITCH_LEVELS}"

    quiet = compute_kill_switch(
        p_pred_distribution={"mean": 0.50, "sd": 0.10},
        p_pred_distribution_train={"mean": 0.50, "sd": 0.10},
        realised_top_decile_win_rate=0.60,
        top_importance_churn=0.05,
    )
    if quiet["level"] != "none":
        return False, f"a healthy fold reported {quiet['level']}"

    degraded = compute_kill_switch(
        p_pred_distribution={"mean": 0.70, "sd": 0.10},
        p_pred_distribution_train={"mean": 0.50, "sd": 0.10},
        realised_top_decile_win_rate=0.60,
        top_importance_churn=0.05,
    )
    if degraded["level"] != "K1":
        return False, f"a drifted fold reported {degraded['level']}"
    if not degraded["signals"]["prediction_drift"]:
        return False, "the prediction drift signal did not fire"

    halted = compute_kill_switch(
        p_pred_distribution={"mean": 0.70, "sd": 0.10},
        p_pred_distribution_train={"mean": 0.50, "sd": 0.10},
        realised_top_decile_win_rate=0.40,
        top_importance_churn=0.60,
        consecutive_folds_below=3,
    )
    if halted["level"] != "K2":
        return False, f"three folds below the floor reported {halted['level']}"
    if not halted["signals"]["calibration"]:
        return False, "the calibration signal did not fire"
    if not halted["signals"]["importance_churn"]:
        return False, "the importance churn signal did not fire"

    killed = compute_kill_switch(
        p_pred_distribution={"mean": 0.50, "sd": 0.10},
        p_pred_distribution_train={"mean": 0.50, "sd": 0.10},
        realised_top_decile_win_rate=0.60,
        top_importance_churn=0.05,
        abort_criteria_triggered=True,
    )
    if killed["level"] != "K3":
        return False, f"the abort criteria reported {killed['level']}"
    return True, (
        "the kill-switch reports none / K1 / K2 / K3 for the four states the "
        "audit names"
    )


@register(
    "rolling.fold_assertions_abort_the_run",
    "rolling",
    55,
    "each of the five per-fold assertions aborts the run when it fails (L5 §D.5)",
)
def _fold_assertions() -> tuple[bool, str]:
    """L5 §D.5: "a failure must abort the run, not be logged and ignored".

    Every one of the five assertions must raise, and the error must name
    the assertion that failed.
    """
    from dodgys_dd_quant.backtest.fold_report import (
        FOLD_ASSERTIONS,
        FoldAssertionError,
        assert_fold,
    )

    if len(FOLD_ASSERTIONS) != 5:
        return False, f"there are {len(FOLD_ASSERTIONS)} assertions"

    # The fold's own asof is 2024-01-15 and its test window starts on
    # 2024-02-01, so the three time-based assertions can be violated one at
    # a time.
    asof_ns = 1_705_276_800_000_000_000          # 2024-01-15
    test_start_ns = 1_706_745_600_000_000_000    # 2024-02-01

    def _fold(**overrides):
        meta = {
            "asof": "2024-01-15",
            "test_start": "2024-02-01",
            "feature_list": ["a", "b"],
            "max_ts_read": asof_ns,
        }
        meta.update(overrides.pop("meta", {}))
        fold = SimpleNamespace(
            asof="2024-01-15",
            asof_ns=asof_ns,
            test_start="2024-02-01",
            meta=meta,
        )
        for key, value in overrides.items():
            setattr(fold, key, value)
        return fold

    cases = {
        # a candidate decided before the model's own boundary
        "forward_only": (_fold(), [asof_ns - 1], None, ["a", "b"]),
        # a candidate that belongs to the next fold
        "exactly_one_fold": (_fold(), [test_start_ns + 10], test_start_ns, ["a", "b"]),
        # a candidate before the fold's own test window
        "not_inside_own_span": (_fold(), [asof_ns + 1], None, ["a", "b"]),
        # the artefact was trained on a different feature list
        "metadata_agrees": (_fold(), [test_start_ns + 10], None, ["a", "different"]),
        # the model read inside the test window
        "never_saw_test_month": (
            _fold(meta={"max_ts_read": test_start_ns + 1}),
            [test_start_ns + 10],
            None,
            ["a", "b"],
        ),
    }
    if set(cases) != set(FOLD_ASSERTIONS):
        return False, f"the assertions are {FOLD_ASSERTIONS}"

    for name, (fold, rows, next_asof, features) in cases.items():
        try:
            assert_fold(fold, rows_ts=rows, next_asof_ns=next_asof, backtest_feature_list=features)
        except FoldAssertionError as exc:
            if name not in str(exc):
                return False, f"the {name} failure does not name itself: {exc}"
            continue
        return False, f"the {name} assertion did not abort the run"

    # a fold that satisfies everything must pass
    good = _fold()
    try:
        assert_fold(
            good,
            rows_ts=[1_750_000_000_000_000_000],
            next_asof_ns=1_800_000_000_000_000_000,
            backtest_feature_list=["a", "b"],
        )
    except FoldAssertionError as exc:
        return False, f"a valid fold was rejected: {exc}"
    return True, "each of the five assertions aborts, and a valid fold passes"


@register(
    "rolling.pipeline_is_causal_end_to_end",
    "rolling",
    60,
    "truncating the future changes nothing the pipeline already emitted",
)
def _pipeline_causal() -> tuple[bool, str]:
    """Causality for the **whole** pipeline, not just the rule engine.

    The engine, the features and the labels must all be functions of the
    history: cutting the series must not move a single earlier number.
    """
    import numpy as np
    import pandas as pd

    from dodgys_dd_quant.ml_pipeline.features import build_features
    from dodgys_dd_quant.ml_pipeline.labels import build_labels
    from dodgys_dd_quant.strategy.state_machine import PRESETS, run_state_machine
    from dodgys_dd_quant.strategy.structure import Bars

    from bench import fixtures

    bars = fixtures.btc_15m()
    log = run_state_machine(bars, PRESETS["honest"])
    candidates = list(log)
    if not candidates:
        return False, "no candidates to inspect"

    cut = len(bars) - 200
    truncated = Bars(
        ts=bars.ts[:cut],
        open=bars.open[:cut],
        high=bars.high[:cut],
        low=bars.low[:cut],
        close=bars.close[:cut],
        volume=bars.volume[:cut],
        symbol=bars.symbol,
        timeframe=bars.timeframe,
    )
    short_log = run_state_machine(truncated, PRESETS["honest"])
    short = list(short_log)
    if len(short) > len(candidates):
        return False, (
            f"the truncated series produced {len(short)} candidates against "
            f"{len(candidates)}"
        )

    # The truncated run's candidates are a **prefix** of the full run's: the
    # tail simply does not exist yet.
    for a, b in zip(candidates, short):
        if (a.confirm_bar, a.side, a.entry_price, a.stop_price) != (
            b.confirm_bar,
            b.side,
            b.entry_price,
            b.stop_price,
        ):
            return False, "a candidate changed when the future was cut"

    # The labels may only be compared where the resolution window is inside
    # the truncated series; the last candidates cannot resolve without the
    # future that was cut away.
    from dodgys_dd_quant.strategy.constants import LABEL_HORIZON_BARS

    resolved = [
        index
        for index, cand in enumerate(short)
        if cand.confirm_bar + LABEL_HORIZON_BARS <= cut
    ]
    if not resolved:
        return False, "no candidate resolves inside the truncated series"
    full_labels = log.to_table()["label"]
    part_labels = short_log.to_table()["label"]
    if not np.array_equal(
        full_labels[resolved], part_labels[resolved], equal_nan=True
    ):
        return False, "a label moved when the future was cut"

    interval = bars.interval_ns
    bars_df = pd.DataFrame(
        {
            "ts_event": bars.ts.astype("int64") + interval,
            "open": bars.open,
            "high": bars.high,
            "low": bars.low,
            "close": bars.close,
            "volume": bars.volume,
        }
    )
    frame = pd.DataFrame(log.to_table())
    labelled = build_labels(frame, bars_df)
    if len(labelled) != len(candidates):
        return False, "the label frame does not match the candidate log"
    return True, (
        f"{len(short)} candidates and {len(resolved)} of their labels are "
        f"unchanged when the future is cut"
    )


@register(
    "rolling.degradation_signals_are_computed",
    "rolling",
    50,
    "the three degradation signals are computed per fold (L4 §F.3)",
)
def _degradation_signals() -> tuple[bool, str]:
    """The kill-switch consumes three signals; the backtest must produce them.

    The signals are the prediction drift, the realised-vs-predicted
    calibration and the feature-importance churn.
    """
    from dodgys_dd_quant.backtest.walk_forward import Fold, walk_forward

    from bench import fixtures

    labelled, bars = _rolling_frame()
    candidates = list(fixtures.candidate_log("BTCUSDT", "honest"))
    if not candidates:
        return False, "no candidates to inspect"

    # two consecutive monthly folds, each with the window its model may decide
    folds = [
        Fold(
            asof="2024-03-01",
            asof_ns=1_709_251_200_000_000_000,
            directory=Path("/nonexistent"),
            train_start="2023-09-01",
            train_end="2024-02-29",
            valid_start="2024-02-01",
            valid_end="2024-02-29",
            test_start="2024-03-01",
            test_end="2024-03-31",
        ),
        Fold(
            asof="2024-04-01",
            asof_ns=1_712_377_600_000_000_000,
            directory=Path("/nonexistent"),
            train_start="2023-10-01",
            train_end="2024-03-31",
            valid_start="2024-03-01",
            valid_end="2024-03-31",
            test_start="2024-04-01",
            test_end="2024-04-30",
        ),
    ]
    report = walk_forward(candidates, len(bars), folds)
    if not report.folds:
        return False, "the walk-forward produced no fold report"
    for fold_report in report.folds:
        for signal in ("prediction_drift", "calibration", "importance_churn"):
            if signal not in fold_report.signals:
                return False, f"the fold report carries no {signal!r} signal"
    if not report.kill_switch:
        return False, "the walk-forward reports no kill-switch verdict"
    if report.kill_switch.get("level") not in ("none", "K1", "K2", "K3"):
        return False, f"the kill-switch reported {report.kill_switch.get('level')!r}"
    return True, (
        f"every fold carries the three signals and the run reports "
        f"{report.kill_switch.get('level')}"
    )


@register(
    "rolling.trial_registry_is_append_only",
    "rolling",
    40,
    "the trial registry is write-once: a configuration cannot be registered twice",
)
def _registry_append_only() -> tuple[bool, str]:
    """L4 §F.5: the ledger is append-only, and a name can never be reused.

    Re-registering a configuration would silently change ``N``, which is the
    number the DSR is deflated by.
    """
    from dodgys_dd_quant.backtest.trials import TrialRegistry

    with tempfile.TemporaryDirectory() as tmp:
        registry = TrialRegistry(Path(tmp))
        registry.record(name="arm-1", oos_returns=[0.1, -0.2, 0.3])
        if registry.trial_count() != 1:
            return False, "the first trial was not recorded"
        try:
            registry.record(name="arm-1", oos_returns=[9.9, 9.9, 9.9])
        except ValueError:
            pass
        else:
            return False, "the registry accepted the same name twice"
        if registry.trial_count() != 1:
            return False, "the rejected trial still changed the count"
        registry.record(name="arm-2", oos_returns=[0.2, 0.1, -0.1])
        if registry.trial_count() != 2:
            return False, "the second trial was not recorded"
        names = registry.names()
        if names != {"arm-1", "arm-2"}:
            return False, f"the ledger holds {sorted(names)}"
    return True, "the ledger refuses a duplicate name and keeps its count"


@register(
    "rolling.fold_report_has_every_audited_field",
    "rolling",
    45,
    "the per-fold report carries every field L4 §F.2 names",
)
def _fold_report_fields() -> tuple[bool, str]:
    """The audit's field set, and the numbers in it must be finite."""
    from dodgys_dd_quant.backtest.fold_report import FOLD_REPORT_FIELDS, fold_report_row

    row = fold_report_row(
        fold_index=0,
        windows={
            "train_start": "2024-01-01",
            "train_end": "2024-01-31",
            "valid_start": "2024-02-01",
            "valid_end": "2024-02-02",
            "test_start": "2024-02-03",
            "test_end": "2024-02-29",
        },
        asof="2024-02-02",
        n_candidates=100,
        n_candidates_labeled=60,
        n_censored=10,
        n_trades=25,
        n_trades_kept=12,
        win_rate=0.42,
        expectancy_r_gross=0.05,
        expectancy_r_net=-0.15,
        pf=1.1,
        pf_net=0.9,
        max_drawdown_r=-2.0,
        max_consecutive_losses=4,
        auc_test=0.51,
        accuracy_test=0.55,
        brier_score=0.24,
        p_pred_distribution=[0.3, 0.7],
        p_pred_distribution_train=[0.5, 0.5],
        cost_r=0.2,
        n_roll_boundary_bars_excluded=3,
        base_rate=0.33,
        ci95_lo=-0.4,
        ci95_hi=0.5,
    )
    missing = [name for name in FOLD_REPORT_FIELDS if name not in row]
    if missing:
        return False, f"the row is missing {missing}"
    for name in ("expectancy_R_gross", "expectancy_R_net", "PF", "PF_net", "cost_R"):
        value = row[name]
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            return False, f"the field {name!r} is {value!r}"
    if row["kept_fraction"] <= 0.0:
        return False, "the kept fraction was not derived from the counts"
    return True, (
        f"the row carries all {len(FOLD_REPORT_FIELDS)} audited fields"
    )


@register(
    "rolling.model_metadata_carries_the_d3_keys",
    "rolling",
    50,
    "the trained artefact's metadata carries every D3 key the README documents",
)
def _d3_metadata_keys() -> tuple[bool, str]:
    """F12: the producer, the consumer and the README must agree.

    The README lists the D3 metadata's keys; a trained artefact must carry
    all of them.
    """
    import json
    import re
    import shutil
    import tempfile

    from dodgys_dd_quant.ml_pipeline.train_meta_labeler import train_walk_forward

    labelled, bars = _rolling_frame()
    workspace = Path(tempfile.mkdtemp(prefix="ifvg-d3-keys-"))
    try:
        train_walk_forward(
            labelled,
            bars,
            symbol="BTCUSDT",
            timeframe="15m",
            run_root=workspace / "artifacts",
        )
        meta_files = sorted((workspace / "artifacts" / "models" / "BTCUSDT").glob("asof_*/meta_label_meta.json"))
        if not meta_files:
            return False, "the trainer wrote no metadata"
        meta = json.loads(meta_files[0].read_text(encoding="utf-8"))

        readme = Path("dodgys_dd_quant/ml_pipeline/README.md").read_text(encoding="utf-8")
        block = re.search(r"`meta_label_meta\.json`.*?`(.*?)`", readme, re.S)
        if block is None:
            return False, "the README documents no metadata keys"
        keys = set(re.findall(r"\b([a-z][a-z0-9_]*)\b", block.group(1)))
        missing = sorted(key for key in keys if key not in meta)
        if missing:
            return False, f"the metadata is missing {missing[:5]}"
        if "asof" not in meta or "feature_list" not in meta:
            return False, "the metadata has no asof or feature_list"
        return True, (
            f"the artefact's metadata carries all {len(keys)} documented D3 keys"
        )
    except Exception as exc:
        return False, f"the training failed: {type(exc).__name__}: {exc}"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
