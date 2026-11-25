"""Unit tests of the walk-forward harness (D3, D4, D9)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from dodgys_dd_quant.backtest.cost_model import get_profile
from dodgys_dd_quant.backtest.walk_forward import (
    Fold,
    ForwardOnlyViolation,
    assert_forward_only,
    deflated_sharpe,
    load_walk_forward_index,
    simulate_portfolio,
    summarise_trades,
    walk_forward,
)
from dodgys_dd_quant.strategy.state_machine import Candidate

NS = 1_000_000_000
DAY = 86_400 * NS


def _cand(ts_event: int, r: float, entry_bar: int = 0, exit_bar: int = 1) -> Candidate:
    return Candidate(
        ts_event=ts_event,
        confirm_bar=entry_bar - 1,
        side=1,
        entry_bar=entry_bar,
        entry_price=100.0,
        stop_price=95.0,
        target_price=110.0,
        risk=5.0,
        outcome="target" if r > 0 else "stop",
        r_multiple=r,
        exit_bar=exit_bar,
    )


# ---------------------------------------------------------------------------
# The forward-only rule (D3)
# ---------------------------------------------------------------------------


def test_forward_only_assertion_raises_when_violated():
    fold = Fold(asof="2026-01-31", asof_ns=100 * DAY, directory=Path("."))
    # a trade *inside* the training period must be rejected
    with pytest.raises(ForwardOnlyViolation):
        assert_forward_only(fold, 50 * DAY)
    with pytest.raises(ForwardOnlyViolation):
        assert_forward_only(fold, fold.asof_ns)
    # a trade after the asof is fine
    assert_forward_only(fold, fold.asof_ns + 1)


class _StubScorer:
    """A model that always says "yes"; it only exists to exercise the checks."""

    available = True

    def __init__(self, p: float = 0.9, threshold: float = 0.58) -> None:
        self.p = p
        # the walk-forward reads the *scorer's* threshold (a quantile-gated
        # fold carries its own); the stub mimics the contract
        self.threshold = threshold
        self.calls = 0

    def score(self, candidate) -> float:
        self.calls += 1
        return self.p


def test_forward_only_assertion_is_enforced_inside_the_walk_forward():
    day = 86_400 * NS
    from dodgys_dd_quant.backtest.walk_forward import _date_to_ns

    # a malformed fold whose model was trained *after* its own test window
    fold = Fold(asof="2026-06-30", asof_ns=30000 * day, directory=Path("."),
                test_start="2026-02-01", test_end="2026-02-28")
    candidates = [_cand(ts_event=_date_to_ns("2026-02-10"), r=1.0)]   # inside the window,
    with pytest.raises(ForwardOnlyViolation):           # but before the asof
        walk_forward(candidates, n_bars=10, folds=[fold], scorer=_StubScorer())


def test_a_model_below_the_threshold_is_not_traded():
    from dodgys_dd_quant.backtest.walk_forward import _date_to_ns

    fold = Fold(asof="2026-01-31", asof_ns=_date_to_ns("2026-02-01"),
                directory=Path("."), test_start="2026-02-01", test_end="2026-03-01")
    candidates = [_cand(ts_event=_date_to_ns("2026-02-10"), r=1.0, entry_bar=1, exit_bar=2)]
    report = walk_forward(candidates, n_bars=10, folds=[fold], scorer=_StubScorer(0.9))
    assert report.n_candidates == 1
    assert report.n_approved == 1
    assert report.n_trades == 1
    assert report.folds[0].mode == "model"

    # a model that says "no" leaves the candidate in the log but takes no trade
    report = walk_forward(candidates, n_bars=10, folds=[fold], scorer=_StubScorer(0.10))
    assert report.n_candidates == 1
    assert report.n_approved == 0
    assert report.n_trades == 0
    # the candidate is still in the log: nothing is erased (INV4)
    assert len(candidates) == 1


# ---------------------------------------------------------------------------
# The walk-forward index (D3)
# ---------------------------------------------------------------------------


def test_walk_forward_index_is_read_in_order(tmp_path):
    root = tmp_path / "models"
    folder = root / "BTCUSDT" / "asof_20260131"
    folder.mkdir(parents=True)
    (folder / "meta_label_meta.json").write_text(
        json.dumps({"symbol": "BTCUSDT", "asof": "2026-01-31", "n_train": 100,
                    "positives_train": 40, "feature_list": ["x"]})
    )
    (root / "BTCUSDT" / "walk_forward_index.json").write_text(
        json.dumps([
            {"asof": "2026-02-28", "dir": "asof_20260228",
             "test_start": "2026-03-01", "test_end": "2026-03-31"},
            {"asof": "2026-01-31", "dir": "asof_20260131",
             "test_start": "2026-02-01", "test_end": "2026-02-28"},
        ])
    )
    folds = load_walk_forward_index(root, "BTCUSDT")
    assert [f.asof for f in folds] == ["2026-01-31", "2026-02-28"]
    assert folds[0].meta["n_train"] == 100
    assert folds[0].train_start == ""


def test_missing_index_is_not_an_error(tmp_path):
    assert load_walk_forward_index(tmp_path, "BTCUSDT") == []


# ---------------------------------------------------------------------------
# Fold stitching
# ---------------------------------------------------------------------------


def test_fold_stitching_is_contiguous():
    """The folds must tile the timeline without a gap or an overlap."""
    day = 86_400 * NS
    folds = [
        Fold(asof="2026-01-31", asof_ns=10 * day, directory=Path("."),
             test_start="2026-02-01", test_end="2026-03-01"),
        Fold(asof="2026-02-28", asof_ns=40 * day, directory=Path("."),
             test_start="2026-03-01", test_end="2026-04-01"),
        Fold(asof="2026-03-31", asof_ns=70 * day, directory=Path("."),
             test_start="2026-04-01", test_end="2026-05-01"),
    ]
    windows = [f.test_window_ns() for f in folds]
    for (start_a, end_a), (start_b, end_b) in zip(windows, windows[1:]):
        assert end_a is not None and end_b is not None
        assert end_a <= start_b, "folds must not overlap"
        assert end_a == start_b, "folds must be contiguous"

    # every candidate lands in exactly one fold
    # one candidate inside each fold window
    import datetime as _dt

    def ns(text: str) -> int:
        y, m, d = (int(x) for x in text.split("-"))
        return int(_dt.datetime(y, m, d, tzinfo=_dt.timezone.utc).timestamp()) * NS

    candidates = [
        _cand(ts_event=ns("2026-02-10"), r=1.0),
        _cand(ts_event=ns("2026-03-10"), r=-1.0),
        _cand(ts_event=ns("2026-04-10"), r=1.0),
    ]
    report = walk_forward(candidates, n_bars=1000, folds=folds)
    assert sum(f.n_candidates for f in report.folds) == len(candidates)
    assert [f.n_candidates for f in report.folds] == [1, 1, 1]


def test_each_candidate_is_counted_in_exactly_one_fold():
    day = 86_400 * NS
    import datetime as _dt

    def ns(text: str) -> int:
        y, m, d = (int(x) for x in text.split("-"))
        return int(_dt.datetime(y, m, d, tzinfo=_dt.timezone.utc).timestamp()) * NS

    folds = [
        Fold(asof="2026-01-31", asof_ns=10 * day, directory=Path("."),
             test_start="2026-02-01", test_end="2026-03-01"),
        Fold(asof="2026-02-28", asof_ns=40 * day, directory=Path("."),
             test_start="2026-03-01", test_end="2026-04-01"),
    ]
    candidates = [
        _cand(ts_event=ns("2026-02-10"), r=1.0),
        _cand(ts_event=ns("2026-03-10"), r=2.0),
        _cand(ts_event=ns("2026-03-20"), r=-1.0),
    ]
    report = walk_forward(candidates, n_bars=1000, folds=folds)
    assert [f.n_candidates for f in report.folds] == [1, 2]
    assert report.n_approved == 3


# ---------------------------------------------------------------------------
# The portfolio (D4)
# ---------------------------------------------------------------------------


def test_the_portfolio_holds_one_position_at_a_time():
    trades = [
        _cand(ts_event=1, r=2.0, entry_bar=10, exit_bar=20),
        _cand(ts_event=2, r=-1.0, entry_bar=15, exit_bar=25),
        _cand(ts_event=3, r=2.0, entry_bar=21, exit_bar=30),
    ]
    selected = simulate_portfolio(trades, n_bars=100)
    assert len(selected) == 2
    assert [t.entry_bar for t in selected] == [10, 21]


def test_the_statistics_use_the_one_position_portfolio():
    trades = [
        _cand(ts_event=1, r=2.0, entry_bar=10, exit_bar=20),
        _cand(ts_event=2, r=-1.0, entry_bar=15, exit_bar=25),
    ]
    selected = simulate_portfolio(trades, n_bars=100)
    stats = summarise_trades(selected)
    assert stats.n == 1
    assert stats.n_closed == 1
    assert stats.expectancy_r == pytest.approx(2.0)
    assert stats.profit_factor == float("inf")
    # a single observation has no dispersion -> no confidence interval
    assert math.isnan(stats.ci95_lo) and math.isnan(stats.ci95_hi)


def test_expectancy_is_reported_gross_and_net_of_costs():
    trades = [
        _cand(ts_event=1, r=2.0, entry_bar=10, exit_bar=20),
        _cand(ts_event=2, r=-1.0, entry_bar=21, exit_bar=30),
        _cand(ts_event=3, r=2.0, entry_bar=31, exit_bar=40),
    ]
    nq = get_profile("nq")
    stats = summarise_trades(trades, nq, slippage_ticks=1, flat_cost_r=0.05)
    assert stats.expectancy_r == pytest.approx(1.0)
    assert stats.expectancy_net_flat_r == pytest.approx(0.95)
    assert stats.break_even_cost_r == pytest.approx(1.0)
    assert stats.mean_cost_r > 0.0


# ---------------------------------------------------------------------------
# The deflated Sharpe
# ---------------------------------------------------------------------------


def test_deflated_sharpe_is_below_the_raw_sharpe_when_many_trials_were_run():
    rng = np.random.default_rng(5)
    returns = rng.normal(0.05, 1.0, 500)
    sr, dsr, p = deflated_sharpe(returns, trials=32)
    assert 0.0 < dsr <= 1.0
    assert 0.0 <= p <= 1.0
    # with many trials the benchmark is higher, so the DSR cannot exceed 1
    _, dsr_many, _ = deflated_sharpe(returns, trials=1000)
    assert dsr_many <= dsr + 1e-12


def test_deflated_sharpe_of_a_flat_series_is_nan():
    sr, dsr, p = deflated_sharpe(np.zeros(100), trials=32)
    assert math.isnan(sr) and math.isnan(dsr)
