"""The artefacts and the guards: what the pipeline writes, and what it asserts.

A sweep of the package's public surface found behaviour that exists but no
probe ever exercised -- the kind of gap that hides a bug:

* the feature builder's **look-ahead assertion** (the static and the dynamic
  layer) and the **consistency report** that makes F5's drift visible;
* the label summary the trainer publishes;
* the Kaggle **dataset** export (the kernel was probed, the dataset was not);
* the PBO computed from the **trial registry**, and the registry's own
  statistics -- the DSR's other inputs;
* the decision-time **regime state**;
* the RL action space's **grid** (60 actions), not just its safety;
* the **deferred** accounting arm (D-17) beside the drop arm;
* the D2 log's **Parquet** artefact and the lake's storage contract.
"""

from __future__ import annotations

import math
import tempfile
from dataclasses import replace
from pathlib import Path

from bench.probes import register

__all__ = []


def _labelled_and_bars():
    from bench import fixtures

    return fixtures.rolling_frame()


@register(
    "rolling.feature_builder_asserts_no_lookahead",
    "rolling",
    60,
    "the feature builder's look-ahead assertion holds on the honest pipeline and fires on a leak",
)
def _no_lookahead() -> tuple[bool, str]:
    """The static layer (the cut-off is at or before the event) and the
    dynamic layer (wrecking the future leaves the earlier rows identical).
    """
    import numpy as np
    import pandas as pd

    from dodgys_dd_quant.ml_pipeline.features import assert_no_lookahead, build_features
    from dodgys_dd_quant.strategy.state_machine import PRESETS, run_state_machine

    from bench import fixtures

    bars = fixtures.btc_15m()
    log = run_state_machine(bars, PRESETS["honest"])
    candidates = list(log)[:400]
    if not candidates:
        return False, "no candidates to inspect"

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
    frame = pd.DataFrame(log.to_table()).iloc[: len(candidates)].reset_index(drop=True)
    features = build_features(frame, bars_df)

    try:
        assert_no_lookahead(frame, features, bars=bars_df, perturb_from=len(bars) - 50)
    except AssertionError as exc:
        return False, f"the honest pipeline failed its own assertion: {exc}"

    # a feature that reads information dated after its own event must be
    # caught by the static layer
    leaked = features.copy()
    leaked.loc[0, "feature_cutoff_ns"] = int(leaked.loc[0, "ts_event"]) + 1
    try:
        assert_no_lookahead(frame, leaked, bars=bars_df, perturb_from=len(bars) - 50)
    except AssertionError:
        return True, (
            "the assertion holds on the honest pipeline and fires on a "
            "feature that reads the future"
        )
    return False, "a feature dated after its own event was not caught"


@register(
    "rolling.candidate_consistency_report_detects_a_drift",
    "rolling",
    55,
    "the D2 log's derived columns are checked against the recomputed ones (F5)",
)
def _consistency_report() -> tuple[bool, str]:
    """F5: the log's ``minutes_from_us_open`` was minutes since midnight.

    The consistency report makes such a drift **visible** instead of letting
    the recomputed value silently overwrite it.
    """
    import pandas as pd

    from dodgys_dd_quant.ml_pipeline.features import candidate_consistency_report
    from dodgys_dd_quant.strategy.state_machine import PRESETS, run_state_machine

    from bench import fixtures

    bars = fixtures.btc_15m()
    log = run_state_machine(bars, PRESETS["honest"])
    frame = pd.DataFrame(log.to_table())
    if frame.empty:
        return False, "no candidates to inspect"

    report = candidate_consistency_report(frame)
    for key in (
        "minutes_from_us_open_mismatches",
        "max_drift_minutes",
        "vxn_regime_mismatches",
    ):
        if key not in report:
            return False, f"the report carries no {key!r}"
    if report["minutes_from_us_open_mismatches"] != 0:
        return False, (
            f"the log's minutes_from_us_open disagrees with the definition in "
            f"{report['minutes_from_us_open_mismatches']} row(s)"
        )

    # a corrupted log must be reported
    drifted = frame.copy()
    drifted["minutes_from_us_open"] = drifted["minutes_from_us_open"] + 600
    bad = candidate_consistency_report(drifted)
    if bad["minutes_from_us_open_mismatches"] == 0:
        return False, "a drifted log was not reported"
    return True, (
        f"the honest log has no drift; a log off by 600 minutes is reported in "
        f"{bad['minutes_from_us_open_mismatches']} row(s)"
    )


@register(
    "rolling.label_summary_counts_the_census",
    "rolling",
    50,
    "the label summary counts the census and reports the base rate",
)
def _label_summary() -> tuple[bool, str]:
    """The unlabelled rows carry no outcome, so they leave the denominator."""
    from dodgys_dd_quant.ml_pipeline.labels import summarize_labels

    labelled, _ = _labelled_and_bars()
    summary = summarize_labels(labelled)
    for key in (
        "n_candidates",
        "n_labelled",
        "n_target",
        "n_stop",
        "n_unlabelled",
        "base_rate",
    ):
        if key not in summary:
            return False, f"the summary carries no {key!r}"
    if summary["n_candidates"] <= 0:
        return False, "the summary counted nothing"
    if summary["n_target"] + summary["n_stop"] != summary["n_labelled"]:
        return False, "the labelled count does not match the targets and stops"
    if summary["n_labelled"] + summary["n_unlabelled"] != summary["n_candidates"]:
        return False, "the unlabelled rows do not complete the census"
    if not 0.0 <= float(summary["base_rate"]) <= 1.0:
        return False, f"the base rate is {summary['base_rate']}"
    return True, (
        f"{summary['n_target']} targets / {summary['n_stop']} stops of "
        f"{summary['n_candidates']} rows (base rate {summary['base_rate']:.3f})"
    )


@register(
    "rolling.kaggle_dataset_export_is_written",
    "rolling",
    55,
    "the Kaggle dataset export writes the splits, the metadata and the kernels",
)
def _kaggle_dataset() -> tuple[bool, str]:
    """The kernel was probed; the **dataset** -- what goes up -- was not."""
    import json

    from dodgys_dd_quant.ml_pipeline.kaggle_export import (
        export_kaggle_dataset,
        write_dataset_metadata,
        write_kernel_metadata,
    )
    from dodgys_dd_quant.ml_pipeline.splits import make_folds

    labelled, bars = _labelled_and_bars()
    folds = make_folds(labelled, bar_interval_minutes=15, horizon_bars=240)
    if not folds:
        return False, "the fixture produced no folds"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        written = export_kaggle_dataset(
            labelled,
            folds,
            out_dir=root,
            symbol="BTCUSDT",
            timeframe="15m",
            feature_columns=["checklist_score", "bars_to_inversion"],
        )
        files = sorted(p for p in root.rglob("*") if p.is_file())
        if not files:
            return False, "the export wrote nothing"
        names = {p.name for p in files}
        if "dataset-metadata.json" not in names:
            return False, f"the export wrote no dataset metadata: {sorted(names)[:5]}"
        metadata = json.loads((root / "dataset-metadata.json").read_text(encoding="utf-8"))
        if not metadata.get("title"):
            return False, "the dataset metadata has no title"
        if not written:
            return False, "the export reported no files"
        write_dataset_metadata(
            root,
            symbol="BTCUSDT",
            timeframe="15m",
            resources=[p.name for p in files],
        )
        write_kernel_metadata(
            root,
            symbol="BTCUSDT",
            timeframe="15m",
            index=0,
            dataset_slug="opclown/dodgysdd-ifvg-folds",
        )
        return True, (
            f"the export wrote {len(files)} file(s), including the dataset and "
            f"kernel metadata"
        )


@register(
    "rolling.pbo_from_the_trial_registry",
    "rolling",
    55,
    "the PBO can be computed from the registered trials, not only from a matrix",
)
def _pbo_from_registry() -> tuple[bool, str]:
    """The registry holds each trial's OOS return series; the PBO needs them
    segmented into the folds.
    """
    import numpy as np

    from dodgys_dd_quant.backtest.cscv import pbo_from_trials
    from dodgys_dd_quant.backtest.trials import TrialRegistry

    with tempfile.TemporaryDirectory() as tmp:
        registry = TrialRegistry(Path(tmp))
        rng = np.random.default_rng(4)
        for index in range(12):
            series = rng.normal(size=120).tolist()
            registry.record(name=f"arm-{index}", oos_returns=series)
        trials = registry.trials()
        result = pbo_from_trials(trials, n_segments=10)
        if result.n_configurations != len(trials):
            return False, (
                f"the PBO used {result.n_configurations} configurations against "
                f"{len(trials)} trials"
            )
        if result.n_splits != 252:
            return False, f"the PBO used {result.n_splits} splits, expected 252"
        if not 0.0 <= result.pbo <= 1.0:
            return False, f"the PBO is {result.pbo}"
        return True, (
            f"the registry's {len(trials)} trials give a PBO of {result.pbo:.3f} "
            f"over {result.n_splits} splits"
        )


@register(
    "rolling.registry_statistics_feed_the_dsr",
    "rolling",
    45,
    "the registry publishes the DSR's other inputs: the skew, the kurtosis and the Sharpe variance",
)
def _registry_statistics() -> tuple[bool, str]:
    """L4 §F.5 items 3 and 4: the trial series' skew and kurtosis, and the
    variance of the trial Sharpes.
    """
    import numpy as np

    from dodgys_dd_quant.backtest.trials import TrialRegistry

    with tempfile.TemporaryDirectory() as tmp:
        registry = TrialRegistry(Path(tmp))
        rng = np.random.default_rng(6)
        for index in range(8):
            series = rng.normal(loc=0.02 * index, scale=1.0, size=60).tolist()
            registry.record(name=f"arm-{index}", oos_returns=series)
        stats = registry.trial_statistics()
        for key in (
            "n_trials",
            "trial_sharpe_mean",
            "trial_sharpe_variance",
            "trial_skew",
            "trial_kurtosis",
        ):
            if key not in stats:
                return False, f"the statistics carry no {key!r}"
        if stats["n_trials"] != 8:
            return False, f"the registry counted {stats['n_trials']} trials"
        if not math.isfinite(float(stats["trial_sharpe_variance"])):
            return False, "the Sharpe variance is not finite"
        if float(stats["trial_sharpe_variance"]) <= 0.0:
            return False, "the trial Sharpes have no variance"
        return True, (
            f"the registry publishes the skew {stats['trial_skew']:.3f}, the "
            f"kurtosis {stats['trial_kurtosis']:.3f} and the Sharpe variance "
            f"{stats['trial_sharpe_variance']:.4f}"
        )


@register(
    "regime.state_is_decision_time",
    "regime",
    55,
    "the regime state carries only what was knowable at the decision (L3 trap 2)",
)
def _regime_state() -> tuple[bool, str]:
    """The state must never use an observation published after the decision,
    and a carried-forward regime must be visibly stale.
    """
    import numpy as np

    from dodgys_dd_quant.strategy.regime import RegimeSeries, regime_state

    days = np.arange(1000, 1040, dtype=np.int64)
    closes = np.linspace(10.0, 30.0, days.size)
    series = RegimeSeries(days=days, closes=closes, name="TEST")

    day_ns = 86_400_000_000_000
    # a decision two days after the last observation
    asof = int(days[-1] + 2) * day_ns
    state = regime_state("TEST", asof, series)
    if state is None:
        return False, "no state was produced"
    if state.known_at_ns > asof:
        return False, "the state claims a publication after the decision"
    if state.stale_days != 2:
        return False, f"the state is {state.stale_days} days stale, expected 2"
    if not (0.0 <= state.percentile <= 1.0):
        return False, f"the percentile is {state.percentile}"
    if state.level != float(closes[-1]):
        return False, "the state used the wrong observation"

    # a decision before the first observation must produce no state at all
    early = regime_state("TEST", int(days[0] - 1) * day_ns, series)
    if early is not None:
        return False, "a state was produced before the first observation existed"
    return True, (
        f"the state is {state.stale_days} days stale and knowable at "
        f"{state.known_at_ns}"
    )


@register(
    "rl.action_space_is_the_documented_grid",
    "rolling",
    50,
    "the RL's action space is the documented 3 x 4 x 5 grid and can open nothing",
)
def _action_grid() -> tuple[bool, str]:
    """L4 §D.2: the grid is 3 x 4 x 5 = 60 discrete actions, and none of them
    can open a position (INV1).
    """
    from dodgys_dd_quant.rl.action_space import (
        ACTION_SPACE,
        BE_TRIGGER_GRID,
        PARTIAL_TP_GRID,
        POSITION_MULTIPLIER_GRID,
        action_space_size,
        iter_actions,
    )

    expected = (
        len(POSITION_MULTIPLIER_GRID) * len(BE_TRIGGER_GRID) * len(PARTIAL_TP_GRID)
    )
    if expected != 60:
        return False, f"the grid is {expected} actions, expected 60"
    if action_space_size() != expected:
        return False, f"the action space holds {action_space_size()} actions"
    if len(ACTION_SPACE) != expected:
        return False, f"the action space holds {len(ACTION_SPACE)} actions"
    if len(set(ACTION_SPACE)) != expected:
        return False, "the action space holds duplicates"

    for action in iter_actions():
        for name in ("position_multiplier", "be_trigger_r", "partial_tp_ratio"):
            if not hasattr(action, name):
                return False, f"the action has no {name!r} field"
        if not (0.0 <= action.partial_tp_ratio <= 1.0):
            return False, f"the partial take-profit is {action.partial_tp_ratio}"
        if action.position_multiplier > max(POSITION_MULTIPLIER_GRID) + 1e-12:
            return False, "an action exceeds the multiplier grid"
    return True, (
        f"the grid holds {action_space_size()} distinct actions "
        f"({len(POSITION_MULTIPLIER_GRID)} x {len(BE_TRIGGER_GRID)} x "
        f"{len(PARTIAL_TP_GRID)})"
    )


@register(
    "rolling.deferred_accounting_is_reachable",
    "rolling",
    45,
    "the deferred accounting arm (D-17) exists beside the drop arm",
)
def _deferred_arm() -> tuple[bool, str]:
    """D-17: the experiment harness's arm **defers** a blocked signal; the
    real portfolio's arm drops it.  Both must exist and differ.
    """
    from dodgys_dd_quant.backtest.walk_forward import simulate_portfolio
    from dodgys_dd_quant.strategy.state_machine import (
        PRESETS,
        run_deferred_portfolio,
        run_state_machine,
    )

    from bench import fixtures

    bars = fixtures.btc_1m()
    log = run_state_machine(bars, PRESETS["honest"])
    candidates = list(log)
    if not candidates:
        return False, "no candidates to inspect"

    dropped = simulate_portfolio(candidates, len(bars))
    deferred = run_deferred_portfolio(bars, PRESETS["honest"])
    if len(deferred) == len(dropped):
        return False, (
            f"the two arms selected the same {len(dropped)} trades -- the "
            f"deferred arm does something different"
        )
    for trade in deferred:
        if not trade.is_closed and trade.outcome not in ("open", "expired"):
            return False, f"an odd outcome in the deferred arm: {trade.outcome}"
    return True, (
        f"the drop arm selected {len(dropped)} trades, the deferred arm "
        f"{len(deferred)}"
    )


@register(
    "rules.d2_log_parquet_matches_the_lake_contract",
    "rules",
    50,
    "the D2 log's Parquet artefact follows the lake's storage contract",
)
def _d2_parquet() -> tuple[bool, str]:
    """The analytical lake is int64 **ms**, left-open, Parquet **Zstd-7**.

    The D2 log is an analytical artefact, so it follows the same contract.
    """
    import pyarrow.parquet as pq

    from dodgys_dd_quant.strategy.state_machine import PRESETS, run_state_machine

    from bench import fixtures

    bars = fixtures.btc_1m()
    log = run_state_machine(bars, PRESETS["honest"])
    with tempfile.TemporaryDirectory() as tmp:
        target = log.write_parquet(Path(tmp) / "d2.parquet")
        if not target.exists():
            return False, "no Parquet file was written"
        table = pq.read_table(target)
        if tuple(table.column_names) != tuple(log.to_table().keys()):
            return False, "the Parquet columns differ from the log's"
        codec = table.schema.field(0).metadata or {}
        # the round trip must preserve the values
        restored = {name: table.column(name).to_numpy() for name in table.column_names}
        original = log.to_table()
        for name in original:
            left = restored[name]
            right = original[name]
            if left.dtype.kind == "f":
                import numpy as np

                if not np.array_equal(left, right, equal_nan=True):
                    return False, f"the column {name!r} did not survive the round trip"
    return True, (
        f"the D2 log round-trips through Parquet with {table.num_columns} columns"
    )


@register(
    "rolling.portfolio_survives_a_censored_candidate",
    "rolling",
    60,
    "a candidate that never resolves holds the book for the horizon, not for ever",
)
def _portfolio_survives_censored() -> tuple[bool, str]:
    """A censored candidate must not collapse the portfolio.

    A setup that hits neither the stop nor the target inside the label
    horizon is **still open** when the horizon ends: it holds the book for
    the horizon and then lets the next signal in.  Treating it as "never
    resolves" would block every later signal and collapse the portfolio --
    which is exactly what happened when the horizon was introduced.
    """
    from dodgys_dd_quant.backtest.walk_forward import simulate_portfolio
    from dodgys_dd_quant.strategy.constants import LABEL_HORIZON_BARS
    from dodgys_dd_quant.strategy.state_machine import Candidate

    def _cand(entry_bar: int, exit_bar: int) -> Candidate:
        return Candidate(
            ts_event=entry_bar,
            confirm_bar=entry_bar,
            side=1,
            fvg_type=-1,
            entry_bar=entry_bar,
            entry_price=100.0,
            stop_price=99.0,
            target_price=102.0,
            risk=1.0,
            outcome="stop" if exit_bar >= 0 else "open",
            exit_bar=exit_bar,
        )

    censored = _cand(10, -1)
    inside = _cand(20, 25)
    after = _cand(LABEL_HORIZON_BARS + 50, LABEL_HORIZON_BARS + 60)
    portfolio = simulate_portfolio([after, inside, censored], 10_000)

    entries = [c.entry_bar for c in portfolio]
    if entries[:1] != [10]:
        return False, f"the portfolio did not take the first signal: {entries}"
    if LABEL_HORIZON_BARS + 50 not in entries:
        return False, (
            f"the censored candidate blocked the book for ever: the portfolio "
            f"took {entries}"
        )
    if 20 in entries:
        return False, "a signal inside the open position was taken"
    return True, (
        f"the censored candidate held the book for {LABEL_HORIZON_BARS} bars "
        f"and the next signal was taken: {entries}"
    )


@register(
    "rolling.break_even_exit_carries_its_price",
    "rolling",
    50,
    "a break-even exit carries the bar it closed on and the multiple it realised",
)
def _break_even_exit() -> tuple[bool, str]:
    """The reference's break-even exit is a **real** exit.

    It closes the position at the leg's origin, so the row must carry the
    exit bar and the realised multiple -- otherwise the portfolio would hold
    the book for ever (the row looks unresolved).
    """
    from dodgys_dd_quant.strategy.state_machine import PRESETS, run_state_machine

    from bench import fixtures

    bars = fixtures.btc_1m()
    candidates = list(
        run_state_machine(
            bars, replace(PRESETS["honest"], resolve_break_even=True)
        )
    )
    resolved = [c for c in candidates if c.outcome == "break_even"]
    if not resolved:
        return False, "no candidate resolved at its break-even level"
    for cand in resolved:
        if cand.exit_bar < 0:
            return False, "a break-even exit has no exit bar"
        if not cand.is_closed:
            return False, "a break-even exit is not a closed trade"
        if not math.isfinite(cand.r_multiple):
            return False, "a break-even exit has no realised multiple"
        if cand.r_multiple == 0.0:
            return False, "a break-even exit realised exactly zero"
    return True, (
        f"{len(resolved)} break-even exits carry their bar and their multiple "
        f"(median {sorted(c.r_multiple for c in resolved)[len(resolved) // 2]:.3f} R)"
    )
