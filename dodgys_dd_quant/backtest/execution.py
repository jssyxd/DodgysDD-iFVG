"""Resolve candidate outcomes on an **execution** series (a finer bar interval).

Why this module exists
----------------------
A 15-minute signal cannot be resolved honestly on 15-minute bars: the bar's
own high/low hides the order in which the stop and the target were touched, so
the conservative "stop first" tie-break decides the result whenever both are
inside the bar's range.  At 1 minute the same ambiguity survives but shrinks;
with tick data it nearly disappears.

So the signal series decides *whether and where* to trade, and the execution
series decides *which barrier was reached first*.  The entry price and the
barriers are taken from the candidate exactly as the rule engine set them --
this module never re-derives the trade geometry (that would silently change
the strategy).

The contract is the engine's own (F6 parity):

* only bars strictly **after** the candidate's ``ts_event`` can resolve it;
* when one bar touches both the stop and the target, the **stop** wins;
* a setup that hits neither inside the horizon is **censored** (``expired``),
  not a loss;
* a ``never_tradable`` candidate stays ``discarded``.

The horizon is given in bars of the **execution** series: the caller converts
its own time horizon, so "8 hours" means 480 one-minute bars or 32 15-minute
bars.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from dodgys_dd_quant.strategy.state_machine import Candidate, _first_hit

__all__ = ["resolve_on_execution", "execution_horizon_bars"]

#: Outcomes that mean "the setup cannot be traded" and are left untouched.
_SKIP = frozenset({"discarded"})


def resolve_on_execution(
    candidates: Sequence[Candidate],
    exec_bars,
    *,
    horizon_bars: int,
    signal_bars=None,
) -> dict:
    """Re-resolve every candidate's outcome on the execution series.

    ``exec_bars`` is a ``Bars`` object (``ts`` in nanoseconds, ``low``/``high``
    aligned).  The function mutates the candidates in place and returns the
    number of rows whose outcome changed -- the number is the caller's
    evidence that the execution series actually decided something.

    The outcome, the realised multiple and the exit *time* come from the
    execution series, but ``exit_bar`` is recorded in **signal-bar space**
    (the bar whose interval contains the exit), because the one-position
    portfolio's book-keeping is keyed on the signal series.  Mixing the two
    index spaces once collapsed the portfolio to four trades.

    A candidate whose ``ts_event`` lies **outside** the execution series is
    left untouched and counted as skipped: resolving it against a different
    era would be a silent look-ahead (the first version of this module did
    exactly that when the signal series started three years before the
    execution series, and manufactured a t-statistic of 35).

    Raises ``ValueError`` when the execution series is not strictly ascending:
    a mis-ordered series would make ``searchsorted`` silently wrong.

    Returns ``{"changed": int, "skipped": int}``.
    """
    n = len(exec_bars)
    if n == 0:
        raise ValueError("the execution series is empty")
    ts = np.asarray(exec_bars.ts, dtype=np.int64)
    if ts.size > 1 and not bool(np.all(np.diff(ts) > 0)):
        raise ValueError("the execution series is not strictly ascending")
    low = np.asarray(exec_bars.low, dtype="float64")
    high = np.asarray(exec_bars.high, dtype="float64")
    signal_ts = (
        np.asarray(signal_bars.ts, dtype=np.int64) if signal_bars is not None else None
    )

    def _signal_bar_at(stamp: int) -> int:
        """The signal bar whose interval contains ``stamp`` (or the last one)."""
        if signal_ts is None or signal_ts.size == 0:
            return -1
        pos = int(np.searchsorted(signal_ts, stamp, side="right")) - 1
        return max(0, min(pos, signal_ts.size - 1))

    changed = 0
    skipped = 0
    for cand in candidates:
        if cand.outcome in _SKIP or cand.never_tradable:
            continue
        stamp = int(cand.ts_event)
        if stamp < int(ts[0]) or stamp > int(ts[-1]):
            skipped += 1
            continue
        # strictly after the decision bar's close (the engine's own rule)
        start = int(np.searchsorted(ts, stamp, side="right"))
        previous = cand.outcome
        if start >= n:
            cand.outcome = "open"
            cand.r_multiple = float("nan")
            cand.exit_bar = -1
            changed += int(previous != cand.outcome)
            continue
        end = min(n, start + int(horizon_bars))
        bar = _first_hit(
            low, high, start, cand.side, cand.stop_price, cand.target_price, end=end
        )
        if bar < 0:
            cand.outcome = "expired"
            cand.r_multiple = float("nan")
            cand.exit_bar = -1
        else:
            hit_stop = (
                low[bar] <= cand.stop_price
                if cand.side > 0
                else high[bar] >= cand.stop_price
            )
            if hit_stop:
                cand.outcome = "stop"
                cand.r_multiple = -1.0
            else:
                cand.outcome = "target"
                cand.r_multiple = (
                    (cand.target_price - cand.entry_price) * cand.side / cand.risk
                )
            cand.exit_bar = _signal_bar_at(int(ts[bar]))
        changed += int(previous != cand.outcome)
    return {"changed": changed, "skipped": skipped}


def execution_horizon_bars(minutes: float, bar_interval_minutes: float) -> int:
    """The horizon in bars of an execution series of the given interval."""
    if bar_interval_minutes <= 0:
        raise ValueError("bar_interval_minutes must be positive")
    return max(1, int(math.ceil(float(minutes) / float(bar_interval_minutes))))
