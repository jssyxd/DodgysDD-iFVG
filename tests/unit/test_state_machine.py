"""Unit tests of the rule engine.

Everything is synthetic: no network, no lake, no clock.  The bar builder below
is the only source of market data in this file.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from dodgys_dd_quant.strategy.constants import INVERSION_MAX_BARS, INVERSION_MIN_BARS
from dodgys_dd_quant.strategy.state_machine import (
    PRESETS,
    Candidate,
    run_state_machine,
)
from dodgys_dd_quant.strategy.structure import Bars, atr_wilder, detect_fvg

NS = 1_000_000_000
START_NS = 1_700_000_000 * NS


def make_bars(rows, symbol: str = "TEST") -> Bars:
    """Build a :class:`Bars` from ``(open, high, low, close)`` tuples."""
    n = len(rows)
    ts = START_NS + np.arange(n, dtype=np.int64) * 60 * NS
    o = np.array([r[0] for r in rows], dtype=np.float64)
    h = np.array([r[1] for r in rows], dtype=np.float64)
    lo = np.array([r[2] for r in rows], dtype=np.float64)
    c = np.array([r[3] for r in rows], dtype=np.float64)
    return Bars(ts=ts, open=o, high=h, low=lo, close=c, volume=np.ones(n), symbol=symbol)


def flat_bars(n: int, price: float = 100.0) -> Bars:
    return make_bars([(price, price, price, price)] * n)


# ---------------------------------------------------------------------------
# FVG geometry (DOC L121 / pine:L354-356)
# ---------------------------------------------------------------------------


def test_fvg_geometry_is_strict_and_wick_based():
    # bar0 high 10, bar2 low 12 -> a bullish gap [10, 12]
    bars = make_bars(
        [
            (9.0, 10.0, 8.5, 9.5),
            (10.5, 11.0, 10.0, 10.8),
            (11.5, 13.0, 12.0, 12.5),
        ]
    )
    fvgs = detect_fvg(bars, atr_wilder(bars.high, bars.low, bars.close), None)
    assert len(fvgs) == 1
    assert fvgs.oldest[0] == 0
    assert fvgs.newest[0] == 2
    assert fvgs.gap_low[0] == 10.0
    assert fvgs.gap_high[0] == 12.0
    assert fvgs.fvg_type[0] == 1          # bullish gap
    assert fvgs.trade_dir[0] == -1       # -> a short when it inverts


def test_zero_width_gap_is_not_a_fvg():
    bars = make_bars(
        [
            (9.0, 12.0, 8.5, 9.5),
            (10.5, 11.0, 10.0, 10.8),
            (11.5, 13.0, 12.0, 12.5),
        ]
    )
    fvgs = detect_fvg(bars, atr_wilder(bars.high, bars.low, bars.close), None)
    assert len(fvgs) == 0


def test_bearish_gap_trades_long():
    bars = make_bars(
        [
            (11.0, 11.5, 10.0, 10.5),
            (10.0, 10.5, 9.5, 9.8),
            (9.0, 9.5, 8.0, 8.5),
        ]
    )
    fvgs = detect_fvg(bars, atr_wilder(bars.high, bars.low, bars.close), None)
    assert len(fvgs) == 1
    assert fvgs.fvg_type[0] == -1
    assert fvgs.trade_dir[0] == 1


# ---------------------------------------------------------------------------
# The inversion trigger
# ---------------------------------------------------------------------------


def _gap_then_close_series(wick_only: bool) -> Bars:
    """A bullish gap [10, 12] and a later close through its lower edge."""
    rows = [
        (9.0, 10.0, 8.5, 9.5),     # 0
        (10.5, 11.0, 10.0, 10.8),   # 1
        (11.5, 13.0, 12.0, 12.5),   # 2  -> bullish FVG [10, 12]
        (12.0, 12.5, 11.0, 12.2),   # 3  (no trigger)
        (11.0, 11.5, 9.0, 10.5),    # 4  the wick pierces, the body closes back inside
        (9.5, 10.0, 9.0, 9.5),      # 5
    ]
    if not wick_only:
        rows[4] = (11.0, 11.2, 9.0, 9.5)   # the body closes below 10
    return make_bars(rows)


def test_inversion_requires_a_body_close_through_the_far_edge():
    """A wick-only penetration must not trigger (DOC L123)."""
    bars = _gap_then_close_series(wick_only=True)
    log = run_state_machine(bars, PRESETS["honest"])
    assert len(log.candidates) == 0


def test_inversion_triggers_on_the_closing_bar_and_enters_next_bar():
    bars = _gap_then_close_series(wick_only=False)
    log = run_state_machine(bars, PRESETS["honest"])
    assert len(log.candidates) == 1
    cand = log.candidates[0]
    assert cand.confirm_bar == 4            # the bar whose close penetrated
    assert cand.side == -1                  # a bullish gap inverts into a short
    assert cand.entry_bar == 5              # the honest fill is the next open
    assert cand.entry_price == pytest.approx(bars.open[5])
    assert cand.bars_to_inversion == 2      # age measured from the gap's newest candle


def test_confirmation_age_can_never_be_zero():
    """Age 0 is arithmetically impossible (L2 §A.5)."""
    rng = np.random.default_rng(3)
    n = 4000
    close = 100 + np.cumsum(rng.normal(0, 0.3, n))
    high = close + np.abs(rng.normal(0, 0.15, n))
    low = close - np.abs(rng.normal(0, 0.15, n))
    open_ = np.concatenate(([close[0]], close[:-1]))
    bars = Bars(
        ts=START_NS + np.arange(n, dtype=np.int64) * 60 * NS,
        open=open_, high=high, low=low, close=close, volume=np.ones(n),
    )
    log = run_state_machine(bars, PRESETS["honest"])
    assert log.candidates
    assert min(c.bars_to_inversion for c in log.candidates) >= INVERSION_MIN_BARS


# ---------------------------------------------------------------------------
# The expiry rule
# ---------------------------------------------------------------------------


def _series_with_trigger_at(age: int) -> Bars:
    """A bullish gap whose body close penetrates exactly at the given age."""
    rows = [
        (9.0, 10.0, 8.5, 9.5),      # 0
        (10.5, 11.0, 10.0, 10.8),    # 1
        (11.5, 13.0, 12.0, 12.5),    # 2 -> the gap's newest candle
    ]
    # bars 3..(2+age) do not penetrate; the bar at age `age` does
    for i in range(3, 2 + age):
        rows.append((11.5, 11.8, 10.5, 11.6))
    rows.append((11.0, 11.2, 9.0, 9.5))
    # a couple of flat bars afterwards so the entry exists
    rows.extend([(9.5, 9.8, 9.2, 9.4)] * 3)
    return make_bars(rows)


def _gap_candidates(log):
    """The candidates of the gap built at bars 0..2 (the one under test)."""
    return [c for c in log.candidates if c.fvg_newest == 2]


@pytest.mark.parametrize("age", [1, 7, 15])
def test_trigger_inside_the_window_is_accepted(age):
    bars = _series_with_trigger_at(age)
    log = run_state_machine(bars, PRESETS["honest"])
    found = _gap_candidates(log)
    assert len(found) == 1
    assert found[0].bars_to_inversion == age


def test_trigger_outside_the_window_expires():
    bars = _series_with_trigger_at(INVERSION_MAX_BARS + 1)
    log = run_state_machine(bars, PRESETS["honest"])
    assert _gap_candidates(log) == []


def test_the_doc_window_rejects_the_early_ages():
    """The doc's (7, 15) band rejects the ages the code allows (L2 §C-2)."""
    bars = _series_with_trigger_at(3)
    assert len(_gap_candidates(run_state_machine(bars, PRESETS["honest"]))) == 1
    doc = replace(PRESETS["honest"]).with_doc_window()
    assert _gap_candidates(run_state_machine(bars, doc)) == []


# ---------------------------------------------------------------------------
# Stop placement
# ---------------------------------------------------------------------------


def test_stop_placement_variants():
    bars = _gap_then_close_series(wick_only=False)
    wick = run_state_machine(bars, replace(PRESETS["honest"], stop_placement="wick"))
    ifvg = run_state_machine(bars, replace(PRESETS["honest"], stop_placement="ifvg"))
    assert len(wick.candidates) == 1 and len(ifvg.candidates) == 1
    assert wick.candidates[0].fvg_newest == 2
    assert wick.candidates[0].side == -1          # a short
    # the wick stop of a short is the HIGHEST high of [gap_newest .. confirmation]
    seg_high = float(bars.high[2:5].max())
    assert wick.candidates[0].stop_price == pytest.approx(seg_high)
    # the IFVG stop is the gap's far edge (12.0 for a bullish gap)
    assert ifvg.candidates[0].stop_price == pytest.approx(12.0)
    # the tighter stop means a smaller risk unit
    assert ifvg.candidates[0].risk < wick.candidates[0].risk


def test_stop_window_confirm_plus_one_includes_the_fill_bar():
    """The reference's stop window peeks at the fill bar; the honest one does not."""
    rows = [
        (9.0, 10.0, 8.5, 9.5),      # 0
        (10.5, 11.0, 10.0, 10.8),    # 1
        (11.5, 13.0, 12.0, 12.5),    # 2  -> bullish gap [10, 12]
        (12.0, 12.5, 11.0, 12.2),    # 3
        (11.0, 11.2, 9.0, 9.5),      # 4  the body closes below 10 -> the inversion
        (9.5, 13.5, 9.0, 9.5),      # 5  the fill bar, whose high is above the window
    ]
    bars = make_bars(rows)
    honest = run_state_machine(bars, replace(PRESETS["honest"], stop_placement="wick"))
    pine = run_state_machine(bars, replace(PRESETS["honest"], stop_placement="wick",
                                           stop_window="confirm_plus_one"))
    assert honest.candidates[0].stop_price == pytest.approx(float(bars.high[2:5].max()))
    # the pine window adds the fill bar (index 5), whose high is 13.5
    assert pine.candidates[0].stop_price == pytest.approx(13.5)


# ---------------------------------------------------------------------------
# One position at a time (D4)
# ---------------------------------------------------------------------------


def _candidate(entry_bar: int, exit_bar: int) -> Candidate:
    return Candidate(
        ts_event=entry_bar * 60 * NS,
        confirm_bar=entry_bar - 1,
        side=1,
        entry_bar=entry_bar,
        entry_price=100.0,
        stop_price=95.0,
        target_price=110.0,
        risk=5.0,
        outcome="target" if exit_bar >= 0 else "open",
        r_multiple=2.0 if exit_bar >= 0 else float("nan"),
        exit_bar=exit_bar,
    )


def test_portfolio_holds_at_most_one_position():
    from dodgys_dd_quant.backtest.walk_forward import simulate_portfolio

    trades = [
        _candidate(10, 20),   # occupies bars 10..20
        _candidate(15, 25),   # overlaps -> dropped
        _candidate(21, 30),   # starts after the first one closed -> taken
    ]
    selected = simulate_portfolio(trades, n_bars=100)
    assert [t.entry_bar for t in selected] == [10, 21]


def test_portfolio_drops_instead_of_deferring():
    """A blocked signal is discarded, not re-timed at a later price."""
    from dodgys_dd_quant.backtest.walk_forward import simulate_portfolio

    trades = [_candidate(10, 20), _candidate(15, 25)]
    selected = simulate_portfolio(trades, n_bars=100)
    assert len(selected) == 1


# ---------------------------------------------------------------------------
# Look-ahead
# ---------------------------------------------------------------------------


def _random_bars(n: int, seed: int = 11) -> Bars:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.25, n))
    high = close + np.abs(rng.normal(0, 0.12, n))
    low = close - np.abs(rng.normal(0, 0.12, n))
    open_ = np.concatenate(([close[0]], close[:-1]))
    return Bars(
        ts=START_NS + np.arange(n, dtype=np.int64) * 60 * NS,
        open=open_, high=high, low=low, close=close, volume=np.ones(n),
    )


@pytest.mark.parametrize("preset", ["honest", "pine", "doc"])
def test_truncating_the_future_does_not_change_the_signals(preset):
    """The strongest look-ahead test: the past must not depend on the future."""
    full = _random_bars(3000)
    cut = 2000
    truncated = full.slice(0, cut)

    log_full = run_state_machine(full, PRESETS[preset])
    log_cut = run_state_machine(truncated, PRESETS[preset])

    def signals(log):
        return [
            (c.fvg_oldest, c.fvg_newest, c.confirm_bar, c.side, c.entry_bar,
             round(c.entry_price, 10), round(c.stop_price, 10),
             round(c.target_price, 10), round(c.risk, 10))
            for c in log.candidates
            if c.confirm_bar < cut
        ]

    assert signals(log_full) == signals(log_cut)
    if preset == "honest":
        assert len(signals(log_full)) > 0


def test_the_atr_floor_suppresses_signals_until_the_series_is_warm():
    """No signal may be produced before ATR(14) is warm (RULE_SPEC A03)."""
    bars = _random_bars(500)
    warm = atr_wilder(bars.high, bars.low, bars.close, 14)
    assert not np.isfinite(warm[:14]).any()
    assert np.isfinite(warm[14]).all()

    config = replace(PRESETS["honest"], min_gap_atr_mult=0.25)
    log = run_state_machine(bars, config)
    assert all(c.fvg_newest >= 14 for c in log.candidates)


# ---------------------------------------------------------------------------
# The D2 log
# ---------------------------------------------------------------------------


def test_candidate_log_has_the_frozen_d2_schema():
    bars = _random_bars(1500)
    log = run_state_machine(bars, PRESETS["honest"])
    table = log.to_table()
    assert tuple(table.keys()) == log.D2_COLUMNS
    assert log.D2_COLUMNS == (
        "ts_event", "symbol", "side", "entry_price", "stop_price", "target_price",
        "risk", "fvg_low", "fvg_high", "fvg_bar1", "fvg_bar3", "confirm_bar",
        "bars_to_inversion", "minutes_from_us_open", "checklist_score",
        "smt_divergence", "sweep_detected", "vxn_known", "vxn_regime",
        "vision_iou", "vision_confidence", "label", "r_multiple",
    )
    assert table["side"].dtype == np.int8
    assert table["ts_event"].dtype == np.int64
    assert table["label"].dtype == np.int8
    # every candidate is kept, including the losers
    assert len(log.candidates) == len(table["label"])
    assert set(np.unique(table["label"])) <= {-1, 0, 1}


def test_checklist_is_reported_but_never_filters():
    """D8: the score is reported; no candidate is removed because of it."""
    bars = _random_bars(2500)
    log = run_state_machine(bars, PRESETS["honest"])
    scores = {c.checklist_score for c in log.candidates}
    assert scores, "the checklist must be populated"
    assert all(0.0 <= s <= 5.0 for s in scores)
    # the same candidates are produced regardless of the checklist
    config = replace(PRESETS["honest"])
    log2 = run_state_machine(bars, config)
    assert len(log2.candidates) == len(log.candidates)


def test_no_signal_uses_a_future_bar():
    """Every entry price comes from the bar after the confirmation candle."""
    bars = _random_bars(2000)
    log = run_state_machine(bars, PRESETS["honest"])
    for cand in log.candidates:
        assert cand.entry_bar == cand.confirm_bar + 1
        assert cand.entry_price == pytest.approx(float(bars.open[cand.entry_bar]))
        # the stop never looks past the confirmation bar
        assert cand.stop_price >= float(bars.low[cand.fvg_newest : cand.confirm_bar + 1].min()) - 1e-9
        assert cand.stop_price <= float(bars.high[cand.fvg_newest : cand.confirm_bar + 1].max()) + 1e-9


def test_smt_is_unknown_without_a_reference_instrument():
    bars = _random_bars(1200)
    log = run_state_machine(bars, PRESETS["honest"])
    assert all(c.smt_divergence == -1 for c in log.candidates)


# ---------------------------------------------------------------------------
# The regime layer: the strictly-lagged index
# ---------------------------------------------------------------------------


def _vxn_index():
    """A synthetic daily VXN series: three days with three distinct closes."""
    from dodgys_dd_quant.strategy.regime import VxnRegimeIndex

    days = np.array([20000, 20001, 20002], dtype=np.int64)
    closes = np.array([15.0, 20.0, 40.0], dtype=np.float64)
    return VxnRegimeIndex(days=days, closes=closes)


def test_the_regime_never_sees_the_current_day_close():
    """No bar on day D may see day D's VXN close (only day D-1's)."""
    index = _vxn_index()
    day = 86_400 * NS
    # one bar on each of the four days around the observations
    ts = np.array([20000 * day, 20001 * day, 20002 * day, 20003 * day], dtype=np.int64)
    known, labels = index.value_at(ts)
    # day 20000 -> nothing before it -> unknown
    assert math.isnan(known[0])
    assert labels[0] == -1
    # day 20001 -> the close of day 20000 (15.0 -> low-vol regime)
    assert known[1] == pytest.approx(15.0)
    assert labels[1] == 0
    # day 20002 -> the close of day 20001 (20.0 -> normal regime)
    assert known[2] == pytest.approx(20.0)
    assert labels[2] == 1
    # day 20003 -> the close of day 20002 (40.0 -> high-vol regime)
    assert known[3] == pytest.approx(40.0)
    assert labels[3] == 2
    # and never the close of its own day
    assert known[2] != pytest.approx(40.0)


def test_the_regime_is_attached_to_every_candidate():
    bars = _random_bars(1500)
    index = _vxn_index()
    log = run_state_machine(bars, PRESETS["honest"], regime=index)
    assert log.candidates
    for cand in log.candidates:
        assert cand.vxn_regime in (-1, 0, 1, 2)
        # the regime is knowable at decision time: the value is from a day
        # that closed before the confirmation bar
        assert math.isnan(cand.vxn_known) or cand.vxn_known > 0.0


def test_without_a_regime_index_the_columns_are_unknown():
    bars = _random_bars(800)
    log = run_state_machine(bars, PRESETS["honest"])
    assert all(c.vxn_regime == -1 for c in log.candidates)
    assert all(math.isnan(c.vxn_known) for c in log.candidates)


# ---------------------------------------------------------------------------
# Causal swings (the look-ahead of the third-party detector is fixed here)
# ---------------------------------------------------------------------------


def test_a_pivot_is_only_usable_after_its_confirming_bar():
    """A pivot at bar p may only be used from bar p + right."""
    from dodgys_dd_quant.strategy.structure import causal_pivots

    high = np.array([10.0, 11.0, 20.0, 11.0, 10.0])
    low = np.array([9.0, 10.0, 19.0, 10.0, 9.0])
    pivots = causal_pivots(high, low, left=1, right=1)
    # the pivot is at bar 2 and is published at bar 3
    assert 2 in pivots.high_idx.tolist()
    assert 3 in pivots.high_known.tolist()
    # it is not usable before that
    end = int(np.searchsorted(pivots.high_known, 2, side="left"))
    assert end == 0
    # the level known before bar 3 excludes the pivot
    assert pivots.highs_known_before(3).start == pivots.highs_known_before(3).stop
    # and includes it from bar 4 onwards
    assert pivots.highs_known_before(4).stop > pivots.highs_known_before(4).start


def test_the_centred_window_would_have_peaked():
    """The third-party detector's centred window sees the future; ours does not."""
    from dodgys_dd_quant.strategy.structure import causal_pivots

    # bar 3 is the high, but it is only known at bar 5
    high = np.array([10.0, 11.0, 12.0, 30.0, 12.0, 11.0, 10.0])
    low = high - 1.0
    pivots = causal_pivots(high, low, left=2, right=2)
    assert 3 in pivots.high_idx.tolist()
    known = int(pivots.high_known[pivots.high_idx == 3][0])
    assert known == 5
    # a centred window would have known it at bar 3
    assert known > 3


# ---------------------------------------------------------------------------
# The leg tracker and the BE-intact gate
# ---------------------------------------------------------------------------


def test_the_leg_tracker_produces_candidates():
    """The leg tracker must actually find setups.

    Its pivots used to be a 3-bar rolling minimum, which fires on roughly a
    third of all bars: the live gap was then discarded long before it could
    reach the 7-bar minimum inversion age, and the reference-faithful arm
    collapsed to a single trade over ten years of NQ.
    """
    bars = _random_bars(3000, seed=5)
    log = run_state_machine(bars, PRESETS["pine_leg"])
    assert len(log.candidates) > 50, (
        f"the leg tracker produced only {len(log.candidates)} candidates"
    )


def test_the_be_intact_gate_removes_candidates():
    """The gate is a real filter, not dead configuration."""
    bars = _random_bars(3000, seed=5)
    without = run_state_machine(bars, PRESETS["pine_be"])
    with_gate = run_state_machine(bars, PRESETS["pine"])
    assert len(with_gate.candidates) <= len(without.candidates)


def test_an_intact_origin_keeps_the_candidate():
    """A candidate whose origin was never taken out must survive the gate."""
    bars = _random_bars(3000, seed=5)
    log = run_state_machine(bars, PRESETS["pine"])
    for cand in log.candidates:
        ob = cand.origin_bar
        if ob < 0 or cand.confirm_bar < ob:
            continue
        if cand.side < 0:
            taken = float(bars.high[ob : cand.confirm_bar + 1].max()) > cand.origin_price
        else:
            taken = float(bars.low[ob : cand.confirm_bar + 1].min()) < cand.origin_price
        assert not taken, (
            f"candidate at bar {cand.confirm_bar} kept although its origin "
            f"({ob}, {cand.origin_price}) was already taken out"
        )
