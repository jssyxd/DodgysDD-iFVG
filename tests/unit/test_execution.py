"""The execution-series resolver: the signal bar's range is not evidence.

The bug this file pins down: a 15-minute signal whose bar spans both the stop
and the target must not be resolved by that bar's own high/low -- the intrabar
order is unknown and the conservative tie-break would call every such trade a
loss.  The 1-minute series knows which barrier came first.
"""

from __future__ import annotations

import numpy as np
import pytest

from dodgys_dd_quant.backtest.execution import (
    execution_horizon_bars,
    resolve_on_execution,
)
from dodgys_dd_quant.strategy.state_machine import Bars, Candidate

NS = 1_000_000_000


def _bars(ts: list[int], low: list[float], high: list[float], close: list[float]) -> Bars:
    n = len(ts)
    arr = lambda values, dtype="float64": np.asarray(values, dtype=dtype)  # noqa: E731
    return Bars(
        ts=arr(ts, "int64"),
        open=arr(close),
        high=arr(high),
        low=arr(low),
        close=arr(close),
        volume=arr([1.0] * n),
    )


def _cand(ts_event: int, side: int = 1) -> Candidate:
    # long: entry 100, stop 95, target 110, risk 5
    return Candidate(
        ts_event=ts_event,
        side=side,
        entry_price=100.0,
        stop_price=95.0 if side > 0 else 105.0,
        target_price=110.0 if side > 0 else 90.0,
        risk=5.0,
        outcome="stop",          # what the coarse (signal) bar would have said
        r_multiple=-1.0,
        exit_bar=0,
    )


def test_the_execution_series_decides_which_barrier_came_first():
    # The signal bar spans [90, 112]: both barriers are inside its range, so
    # the signal series can only guess.  The 1-minute series reaches the
    # target first (bar 2) and the stop never (bar 3 is a different minute).
    ts = [i * 60 * NS for i in range(6)]
    low = [100, 99, 99.5, 96, 100, 100]
    high = [100, 101, 111, 100, 100, 100]
    close = [100, 100, 110, 100, 100, 100]
    bars = _bars(ts, low, high, close)
    cand = _cand(ts_event=0)
    res = resolve_on_execution([cand], bars, horizon_bars=60, signal_bars=bars)
    assert res["changed"] == 1 and res["skipped"] == 0
    assert cand.outcome == "target"
    assert cand.exit_bar == 2
    assert cand.r_multiple == pytest.approx(2.0)


def test_the_stop_wins_when_one_execution_bar_touches_both():
    # one 1-minute bar covers both barriers -> the conservative tie-break
    ts = [i * 60 * NS for i in range(4)]
    low = [100, 90, 100, 100]
    high = [100, 115, 100, 100]
    close = [100, 100, 100, 100]
    cand = _cand(ts_event=0)
    resolve_on_execution([cand], _bars(ts, low, high, close), horizon_bars=60)
    assert cand.outcome == "stop"
    assert cand.r_multiple == -1.0


def test_a_setup_that_never_resolves_is_censored_not_a_loss():
    ts = [i * 60 * NS for i in range(5)]
    low = [100] * 5
    high = [100] * 5
    cand = _cand(ts_event=0)
    resolve_on_execution([cand], _bars(ts, low, high, low), horizon_bars=3)
    assert cand.outcome == "expired"
    assert np.isnan(cand.r_multiple)


def test_only_bars_strictly_after_the_signal_can_resolve_it():
    # the first execution bar is *the* signal bar's own minute: it must not count
    ts = [0, 60 * NS, 120 * NS]
    low = [90.0, 100.0, 100.0]
    high = [115.0, 100.0, 100.0]
    cand = _cand(ts_event=0)
    resolve_on_execution([cand], _bars(ts, low, high, [100.0] * 3), horizon_bars=5)
    assert cand.outcome == "expired"


def test_a_discarded_candidate_is_left_alone():
    ts = [i * 60 * NS for i in range(3)]
    cand = _cand(ts_event=0)
    cand.outcome = "discarded"
    resolve_on_execution([cand], _bars(ts, [100.0] * 3, [100.0] * 3, [100.0] * 3), horizon_bars=5)
    assert cand.outcome == "discarded"


def test_a_candidate_outside_the_execution_series_is_skipped():
    # the signal series starts before the execution series: resolving it would
    # be a silent look-ahead
    ts = [1000 * NS, 1060 * NS]
    bars = _bars(ts, [100.0, 100.0], [100.0, 100.0], [100.0, 100.0])
    cand = _cand(ts_event=0)
    res = resolve_on_execution([cand], bars, horizon_bars=5)
    assert res["skipped"] == 1 and res["changed"] == 0
    assert cand.outcome == "stop"      # the coarse outcome is kept


def test_a_misordered_execution_series_raises():
    ts = [60 * NS, 0, 120 * NS]
    bars = _bars(ts, [100.0] * 3, [100.0] * 3, [100.0] * 3)
    with pytest.raises(ValueError, match="strictly ascending"):
        resolve_on_execution([_cand(0)], bars, horizon_bars=2)


def test_the_horizon_is_converted_between_intervals():
    assert execution_horizon_bars(480, 1) == 480
    assert execution_horizon_bars(480, 15) == 32
    assert execution_horizon_bars(1, 15) == 1
