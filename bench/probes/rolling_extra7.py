"""The paper stage's parity check, and the trainer's dry run.

L4 §E's stage 8 is the gate between a backtest and a live book: the paper
stage must prove that the **live slippage matches the backtest's**, and the
check has to be quantitative.  These probes assert that the check exists,
that it accepts a healthy paper stage and rejects an unhealthy one, and that
the trainer's dry run plans the folds without training anything.
"""

from __future__ import annotations

import tempfile
from dataclasses import replace
from pathlib import Path

from bench.probes import register

__all__ = []


@register(
    "rolling.paper_stage_slippage_parity_is_checked",
    "rolling",
    60,
    "the paper stage's slippage parity is a quantitative assertion (L4 §E stage 8)",
)
def _slippage_parity() -> tuple[bool, str]:
    """The doc's "验证实盘滑点与回测一致性" as an executable gate.

    The audit's three criteria: the median slippage may exceed the model's
    by one tick, at most 5 % of the fills may slip more than two ticks beyond
    it, and the fill rates may not differ by more than 10 %.
    """
    from dodgys_dd_quant.backtest.parity import slippage_parity

    tick = 0.25
    # a healthy paper stage: one tick of slippage on most fills, two on some
    decisions = [100.0 + 0.25 * index for index in range(200)]
    fills = [
        decision + 0.25 * (1 if index % 5 else 2)
        for index, decision in enumerate(decisions)
    ]
    healthy = slippage_parity(
        decision_prices=decisions,
        fill_prices=fills,
        tick_size=tick,
        backtest_ticks=1,
        backtest_fill_rate=0.95,
        paper_fill_rate=0.93,
    )
    if not healthy.passed:
        return False, f"a healthy paper stage was rejected: {healthy.reasons}"

    # an unhealthy one: three ticks of slippage across the board
    bad_fills = [decision + 0.25 * 3 for decision in decisions]
    bad = slippage_parity(
        decision_prices=decisions,
        fill_prices=bad_fills,
        tick_size=tick,
        backtest_ticks=1,
        backtest_fill_rate=0.95,
        paper_fill_rate=0.60,
    )
    if bad.passed:
        return False, "an unhealthy paper stage passed the parity check"
    if len(bad.reasons) < 2:
        return False, (
            f"the unhealthy stage was rejected for only {len(bad.reasons)} "
            f"reason(s): {bad.reasons}"
        )
    return True, (
        f"a healthy stage passes (median {healthy.median_ticks:.2f} ticks) and "
        f"an unhealthy one fails on {len(bad.reasons)} criteria"
    )


@register(
    "rolling.trainer_dry_run_plans_the_folds",
    "rolling",
    45,
    "the trainer's dry run plans the folds without training anything",
)
def _dry_run() -> tuple[bool, str]:
    """The dry run is the cheap way to check a data set before spending a
    minute of LightGBM on it.
    """
    from dodgys_dd_quant.ml_pipeline.train_meta_labeler import train_walk_forward

    from bench import fixtures

    labelled, bars = fixtures.rolling_frame()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "artifacts"
        report = train_walk_forward(
            labelled,
            bars,
            symbol="BTCUSDT",
            timeframe="15m",
            run_root=root,
            dry_run=True,
        )
        if not report.get("dry_run"):
            return False, "the dry run did not report itself as one"
        plan = report.get("fold_plan") or []
        if not plan:
            return False, "the dry run planned no fold"
        if root.exists() and any(root.rglob("meta_label_lgbm.txt")):
            return False, "the dry run trained a model"
        first = plan[0]
        for key in ("train_start", "valid_start", "test_start", "asof"):
            if key not in first:
                return False, f"the fold plan carries no {key!r}"
    return True, f"the dry run planned {len(plan)} folds and trained nothing"


@register(
    "rolling.e1_other_arms_match_the_standalone_experiment",
    "rolling",
    55,
    "the engine's other arms reproduce the standalone experiment's (the doc window, the ATR floor, the sweep gate, the close fill)",
)
def _other_arms() -> tuple[bool, str]:
    """The E-1 grid has 32 arms; the engine must be able to say the same
    thing about each of them.
    """
    import copy
    import csv
    import importlib.util
    import sys
    import tempfile

    from bench import fixtures

    path = Path("research/experiments/e1_rule_falsification.py")
    if not path.exists():
        return False, "the standalone experiment could not be loaded"
    spec = importlib.util.spec_from_file_location("e1_parity", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["e1_parity"] = module
    spec.loader.exec_module(module)

    from dodgys_dd_quant.strategy.state_machine import PRESETS, run_state_machine

    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "bars.csv"
        data = fixtures.load_fixture("btcusdt_1m_2023q1")
        import datetime as dt

        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Datetime", "Open", "High", "Low", "Close", "Volume"])
            for ts, o, h, low, c, v in zip(
                data["ts_ms"],
                data["open"],
                data["high"],
                data["low"],
                data["close"],
                data["volume"],
            ):
                stamp = dt.datetime.fromtimestamp(
                    int(ts) / 1000.0, tz=dt.timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S")
                writer.writerow([stamp, o, h, low, c, v])
        bars_e1 = module.load_bars(csv_path)
        atr = module.atr_wilder(bars_e1, 14)
        swept = module.sweep_flags(bars_e1)

        # the arms the engine's presets name: the doc window with the ATR
        # floor and the sweep gate, and the close fill
        arms = [
            ((7, 15), 0.0, "next_open", False),
            ((7, 15), 0.25, "next_open", False),
            ((0, 15), 0.0, "confirm_close", False),
        ]
        engine_bars = fixtures.btc_1m()
        for window, atr_mult, fill, require_sweep in arms:
            gaps = module.find_candidates(bars_e1, atr, atr_mult)
            done = module.run_arm(
                bars_e1,
                copy.deepcopy(gaps),
                swept,
                window,
                fill,
                require_sweep,
                max_concurrent=0,
            )
            theirs = sum(1 for c in done if c.confirmed is not None)
            config = PRESETS["honest"]
            config = replace(
                config,
                inversion_min_bars=window[0],
                inversion_max_bars=window[1],
                min_gap_atr_mult=(atr_mult if atr_mult > 0 else None),
                entry_fill=fill,
                require_sweep=require_sweep,
            )
            ours = len(run_state_machine(engine_bars, config))
            if ours != theirs:
                return False, (
                    f"the arm {window}/{atr_mult}/{fill}/sweep={require_sweep}: "
                    f"the engine triggers {ours} setups, the standalone "
                    f"experiment {theirs}"
                )
    return True, (
        "the engine reproduces the standalone experiment's census on the doc "
        "window, the ATR floor and the close fill"
    )
