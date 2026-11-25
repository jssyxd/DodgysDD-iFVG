"""The archive's contract: every candidate is row, with a label and a decision.

The point of these tests is that the archive is **lossless about the
population**: a candidate blocked by an open position, a candidate the gate
rejected, and a candidate that never resolved must all appear, and their
``y`` must be the engine's own label vocabulary (1 target, 0 stop, -1 not
resolved) -- never a silent zero.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from dodgys_dd_quant.backtest.records import (
    candidate_frame,
    run_record,
    summary_markdown,
)
from dodgys_dd_quant.backtest.walk_forward import TradeStats
from dodgys_dd_quant.strategy.state_machine import Candidate

NS = 1_000_000_000


def _cand(ts: int, outcome: str, r: float, side: int = 1) -> Candidate:
    return Candidate(
        ts_event=ts,
        side=side,
        entry_price=100.0,
        stop_price=95.0 if side > 0 else 105.0,
        target_price=110.0 if side > 0 else 90.0,
        risk=5.0,
        outcome=outcome,
        r_multiple=r,
        exit_bar=2,
        checklist_score=1.0,
        smt_divergence=1,
    )


def _log(cands):
    return SimpleNamespace(candidates=list(cands))


def test_every_candidate_is_a_row_with_the_engines_label():
    cands = [
        _cand(1 * NS, "target", 2.0),
        _cand(2 * NS, "stop", -1.0),
        _cand(3 * NS, "expired", float("nan")),
        _cand(4 * NS, "break_even", 0.1),
        _cand(5 * NS, "open", float("nan")),
    ]
    frame = candidate_frame(
        _log(cands),
        run_id="ETHUSDT:15m:honest",
        symbol="ETHUSDT",
        timeframe="15m",
        preset="honest",
        horizon_minutes=3600.0,
        bars=None,
        selected_ids={id(cands[0])},
    )
    assert len(frame) == 5
    assert frame["y"].tolist() == [1, 0, -1, -1, -1]
    assert frame["selected"].tolist() == [True, False, False, False, False]
    # the gate did not run: no candidate is approved, and the flag is False
    assert not frame["gate_approved"].any()
    assert frame["fvg_oldest"].tolist() == [0, 0, 0, 0, 0]  # geometry is preserved
    assert frame["outcome"].tolist() == ["target", "stop", "expired", "break_even", "open"]


def test_a_candidate_inside_no_fold_keeps_an_empty_asof():
    fold = SimpleNamespace(
        asof="2024-03-01",
        asof_ns=0,
        test_start="2024-03-01",
        test_end="2024-04-01",
    )
    inside = _cand(int(pd.Timestamp("2024-03-10", tz="UTC").value), "target", 2.0)
    outside = _cand(int(pd.Timestamp("2024-05-10", tz="UTC").value), "target", 2.0)
    frame = candidate_frame(
        _log([inside, outside]),
        run_id="r",
        symbol="ETHUSDT",
        timeframe="15m",
        preset="honest",
        horizon_minutes=3600.0,
        bars=None,
        selected_ids=set(),
        folds=[fold],
    )
    assert frame["fold_asof"].tolist() == ["2024-03-01", ""]


def test_the_gate_flag_only_marks_the_approved_objects():
    a, b = _cand(1 * NS, "target", 2.0), _cand(2 * NS, "stop", -1.0)
    frame = candidate_frame(
        _log([a, b]),
        run_id="r",
        symbol="ETHUSDT",
        timeframe="15m",
        preset="honest",
        horizon_minutes=3600.0,
        bars=None,
        selected_ids={id(a), id(b)},
        gate_approved_ids={id(a)},
    )
    assert frame["selected"].tolist() == [True, True]
    assert frame["gate_approved"].tolist() == [True, False]


def test_features_are_attached_without_duplicating_a_column():
    cand = _cand(1 * NS, "target", 2.0)
    features = pd.DataFrame(
        {"ts_event": [1 * NS], "side": [1], "checklist_score": [9.0], "atr14": [3.5]}
    )
    frame = candidate_frame(
        _log([cand]),
        run_id="r",
        symbol="ETHUSDT",
        timeframe="15m",
        preset="honest",
        horizon_minutes=3600.0,
        bars=None,
        selected_ids=set(),
        features=features,
    )
    assert frame.loc[0, "atr14"] == pytest.approx(3.5)
    # the engine's own checklist score wins over the feature frame's copy
    assert frame.loc[0, "checklist_score"] == pytest.approx(1.0)


def test_the_run_row_carries_the_statistics_and_the_verdict():
    report = SimpleNamespace(
        portfolio=TradeStats(n=10, n_closed=8, win_rate=0.375, expectancy_r=0.05,
                             expectancy_net_r=-0.02, profit_factor=1.1,
                             profit_factor_net=0.95, t_stat=0.7, ci95_lo=-0.1,
                             ci95_hi=0.2, total_r=0.4, max_consecutive_losses=3,
                             mean_cost_r=0.07, break_even_cost_r=0.05),
        sharpe=0.02,
        deflated_sharpe=0.4,
        dsr_p_value=0.6,
        trials=4,
        n_candidates=20,
        n_approved=12,
        n_trades=10,
        kill_switch={
            "level": "K3",
            "abort_criteria": {
                "criteria": [
                    {"name": "A1", "fired": True, "evaluated": True},
                    {"name": "A2", "fired": False, "evaluated": True},
                ]
            },
        },
    )
    row = run_record(
        run_id="ETHUSDT:15m:honest",
        symbol="ETHUSDT",
        timeframe="15m",
        preset="honest",
        data_path="/tmp/x.parquet",
        n_bars=100,
        first_ts=0,
        last_ts=NS,
        profile_name="binance",
        slippage_ticks=1,
        horizon_minutes=3600.0,
        regime="dvol",
        report=report,
        runtime_s=1.5,
        gate="none",
        models_root="",
        n_folds=0,
    )
    assert row["abort_fired"] == "A1"
    assert row["abort_evaluated"] == "A1,A2"
    assert row["kill_level"] == "K3"
    assert row["n_trades"] == 10
    assert np.isclose(row["expectancy_net_r"], -0.02)


def test_the_summary_renders_one_table_per_preset():
    runs = pd.DataFrame(
        [
            {"symbol": "ETHUSDT", "timeframe": "15m", "preset": "honest",
             "n_trades": 10, "win_rate": 0.4, "expectancy_r": 0.05,
             "expectancy_net_r": -0.02, "profit_factor": 1.1, "t_stat": 0.7,
             "kill_level": "K3", "abort_fired": "A1"},
            {"symbol": "ETHUSDT", "timeframe": "15m", "preset": "doc",
             "n_trades": 5, "win_rate": 0.3, "expectancy_r": -0.01,
             "expectancy_net_r": -0.08, "profit_factor": 0.9, "t_stat": -0.2,
             "kill_level": "", "abort_fired": ""},
        ]
    )
    text = summary_markdown(runs, ["a note"])
    assert "preset `honest`" in text and "preset `doc`" in text
    assert "| ETHUSDT | 15m | honest | 10 | 40.0 |" in text
    assert "* a note" in text
