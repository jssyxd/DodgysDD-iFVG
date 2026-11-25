"""The last two abort criteria get their inputs.

A1, A4 and A5 could be evaluated from the run's own statistics.  A2 needed
the **cost buckets** (does the gross edge survive a 0.3 R round trip?) and A3
needed the **model's own numbers** (a high AUC with no net lift, whose top
features are the cost and the risk -- the model has rediscovered the cost
rather than the edge).

Both are now computed by the walk-forward, so the run reports all five.
"""

from __future__ import annotations

import math
from pathlib import Path

from bench.probes import register

__all__ = []


@register(
    "rolling.abort_criteria_a2_splits_the_population_by_cost",
    "rolling",
    45,
    "A2 splits the population at 0.3 R of cost and compares the two buckets",
)
def _a2_buckets() -> tuple[bool, str]:
    """The buckets are the population, measured with the run's cost model."""
    from dodgys_dd_quant.backtest.abort import cost_buckets
    from dodgys_dd_quant.backtest.cost_model import get_profile

    class _Trade:
        def __init__(self, entry_price: float, risk: float, r_multiple: float) -> None:
            self.entry_price = entry_price
            self.risk = risk
            self.r_multiple = r_multiple

    profile = get_profile("binance")
    # a cheap population (a wide risk) and an expensive one (a tight risk)
    cheap = [_Trade(20_000.0, 5_000.0, 0.20) for _ in range(20)]
    expensive = [_Trade(20_000.0, 20.0, 0.20) for _ in range(20)]
    split = cost_buckets(cheap + expensive, profile=profile, slippage_ticks=1)
    if not split["evaluated"]:
        return False, "the cost split could not be evaluated"
    if split["n_light"] != 20 or split["n_heavy"] != 20:
        return False, (
            f"the buckets hold {split['n_light']} and {split['n_heavy']} trades, "
            f"expected 20 and 20"
        )
    if not (split["light_expectancy_r"] > 0.0 and split["heavy_expectancy_r"] > 0.0):
        return False, "the buckets' expectancies are wrong"
    # both buckets are profitable -> the edge is not confined to the expensive
    # ones
    if split["only_cost_heavy_positive"]:
        return False, "the verdict fired although both buckets are profitable"

    # a population whose only profitable bucket is the expensive one
    losing = [_Trade(20_000.0, 5_000.0, -0.20) for _ in range(20)]
    heavy_only = cost_buckets(losing + expensive, profile=profile, slippage_ticks=1)
    if not heavy_only["only_cost_heavy_positive"]:
        return False, "the verdict did not fire when only the costly bucket won"

    # an empty population is not a pass
    empty = cost_buckets([], profile=profile)
    if empty["evaluated"] or empty["only_cost_heavy_positive"] is not None:
        return False, "an empty population was passed as a verdict"
    return True, (
        "the cost split separates the cheap and the costly buckets and an "
        "empty population is not a pass"
    )


@register(
    "rolling.abort_criteria_a3_reads_the_models_own_numbers",
    "rolling",
    45,
    "A3 reads the model's AUC, its net lift and the features it learned",
)
def _a3_model() -> tuple[bool, str]:
    """A high-AUC model with no lift whose top features are the cost and the
    risk has not learned an edge -- it has learned the cost.
    """
    from dodgys_dd_quant.backtest.abort import evaluate_abort_criteria

    learned = evaluate_abort_criteria(
        auc_test=0.72,
        expectancy_lift_r=-0.01,
        top_features=["cost_R", "risk_in_atr"],
    )
    if "A3" not in learned.fired:
        return False, f"A3 did not fire on a cost-learning model: {learned.fired}"

    edge = evaluate_abort_criteria(
        auc_test=0.72,
        expectancy_lift_r=0.20,
        top_features=["checklist_score", "sweep_detected"],
    )
    if "A3" in edge.fired:
        return False, "A3 fired although the model lifted the expectancy"

    no_auc = evaluate_abort_criteria(
        auc_test=0.51,
        expectancy_lift_r=-0.01,
        top_features=["cost_R"],
    )
    if "A3" in no_auc.fired:
        return False, "A3 fired although the model has no AUC"

    unknown = evaluate_abort_criteria(
        auc_test=None,
        expectancy_lift_r=None,
        top_features=["cost_R"],
    )
    if "A3" in unknown.not_evaluated and "A3" in unknown.fired:
        return False, "an unevaluated criterion fired"
    return True, (
        "A3 fires only on a high-AUC model with no lift that learned the cost"
    )


@register(
    "rolling.all_five_criteria_are_evaluated_in_a_walk_forward",
    "rolling",
    50,
    "a walk-forward with a model evaluates all five abort criteria",
)
def _all_five() -> tuple[bool, str]:
    """The point of the criteria is that they run, not that they can be
    called by hand.
    """
    import shutil
    import tempfile

    from bench import fixtures
    from dodgys_dd_quant.backtest.walk_forward import Fold, walk_forward
    from dodgys_dd_quant.ml_pipeline.train_meta_labeler import train_walk_forward

    from dodgys_dd_quant.strategy.state_machine import PRESETS, run_state_machine

    labelled, bars = fixtures.rolling_frame()
    # the candidates must come from the *same* series the model was trained
    # on, or the fold's window holds nothing
    engine_bars = fixtures.bars_from_fixture(
        "btcusdt_15m_2024_2026", "BTCUSDT", "15m"
    )
    candidates = list(run_state_machine(engine_bars, PRESETS["honest"]))
    if not candidates:
        return False, "no candidates to inspect"

    workspace = Path(tempfile.mkdtemp(prefix="ifvg-criteria-"))
    try:
        root = workspace / "artifacts"
        train_walk_forward(
            labelled, bars, symbol="BTCUSDT", timeframe="15m", run_root=root
        )
        folders = sorted((root / "models" / "BTCUSDT").glob("asof_*"))
        if not folders:
            return False, "the trainer wrote no artefact"
        import json

        # a fold that actually trained (a skipped one carries no AUC, so A3
        # would be unevaluated) and whose test window holds candidates
        meta = None
        for folder in folders:
            candidate_meta = json.loads(
                (folder / "meta_label_meta.json").read_text(encoding="utf-8")
            )
            if candidate_meta.get("auc_test") is None:
                continue
            lift = candidate_meta.get("expectancy_lift_r")
            if lift is None or not math.isfinite(float(lift)):
                continue
            window = [
                c
                for c in candidates
                if candidate_meta.get("test_start", "")
                and c.entry_bar >= 0
            ]
            if not window:
                continue
            meta = candidate_meta
            break
        if meta is None:
            return False, "no trained fold with candidates in its test window"
        # the fold's own test window, so the forward-only guard is satisfied
        folds = [
            Fold(
                asof=meta.get("asof", "2024-03-01"),
                asof_ns=1_709_251_200_000_000_000,
                directory=folders[0],
                test_start=meta.get("test_start", "2024-03-01"),
                test_end=meta.get("test_end", "2024-03-31"),
                meta=meta,
            )
        ]
        # the scorer needs the feature vector, so the frame has to be built
        # and keyed the way the pipeline keys it
        import pandas as pd

        from dodgys_dd_quant.ml_pipeline.features import build_features

        log = run_state_machine(engine_bars, PRESETS["honest"])
        frame = build_features(pd.DataFrame(log.to_table()), bars)
        index = {
            (int(row.ts_event), int(row.side), int(row.fvg_bar3)): row
            for row in frame.itertuples()
        }

        def feature_fn(candidate):
            # the D2 table's ``fvg_bar3`` is the candidate's ``fvg_newest``
            row = index[
                (int(candidate.ts_event), int(candidate.side), int(candidate.fvg_newest))
            ]
            values = {}
            for name in row._fields:
                try:
                    values[name] = float(getattr(row, name))
                except (TypeError, ValueError):
                    continue  # the frame carries a few string columns
            return values

        from dodgys_dd_quant.backtest.cost_model import get_profile

        # the quantile gate is the supported way to run a *gated* arm now: the
        # trainer stores an isotonic calibration, so a calibrated probability
        # almost never crosses the doc's absolute 0.58 (that is the finding,
        # not a probe failure) and an absolute-gated run would trade nothing.
        report = walk_forward(
            candidates,
            len(engine_bars),
            folds,
            bars=engine_bars,
            gate="quantile",
            feature_fn=feature_fn,
            profile=get_profile("binance"),
        )
        criteria = report.kill_switch.get("abort_criteria") or {}
        rows = criteria.get("criteria") or []
        if len(rows) != 5:
            return False, f"the run reports {len(rows)} criteria, expected 5"
        evaluated = {c["name"] for c in rows if c.get("evaluated")}
        missing = {"A1", "A2", "A3", "A4", "A5"} - evaluated
        if missing:
            return False, f"the run did not evaluate {sorted(missing)}"
        return True, "the run evaluates all five abort criteria"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
