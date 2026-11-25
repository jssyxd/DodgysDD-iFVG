"""The no-FVG control -- the momentum baseline (L4 §C.6, A4).

A4 asks the question the whole project has to answer about itself:

    *"The result does not beat the no-FVG momentum baseline -> the FVG
    contributes nothing; the project should pivot to a plain ATR-normalised
    momentum system or stop."*

The control was never built, so the criterion could not be evaluated.  This
module is it: a **plain ATR-normalised momentum system** on the same bars,
the same cost model and the same one-position-at-a-time accounting, with no
knowledge of the FVG at all.

The rule is pre-registered and deliberately simple, so that the comparison
measures the *FVG*, not a tuning exercise:

* the signal is the sign of the close-to-close momentum over ``lookback``
  bars, normalised by the ATR(14) so it does not depend on the instrument's
  scale;
* the entry is the **next** bar's open, the stop is one ATR away and the
  target is ``rr`` times that distance;
* a position that has not resolved within ``max_holding_bars`` is
  **censored** (excluded from the expectancy) rather than closed at a price
  the system never saw;
* the accounting is the **drop** accounting: a signal that arrives while a
  position is open is discarded.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from dodgys_dd_quant.strategy.structure import atr_wilder

__all__ = [
    "MomentumConfig",
    "MomentumTrade",
    "MomentumResult",
    "run_momentum_baseline",
]


@dataclass(frozen=True)
class MomentumConfig:
    """The pre-registered parameters of the control."""

    #: The momentum lookback, in bars.
    lookback_bars: int = 20
    #: The ATR window.
    atr_window: int = 14
    #: The stop distance, in ATR.
    atr_stop_mult: float = 1.0
    #: The reward-to-risk of the target.
    rr: float = 2.0
    #: How long a position may be held before it is censored.
    max_holding_bars: int = 240


@dataclass(frozen=True)
class MomentumTrade:
    """One closed position of the control."""

    side: int
    entry_bar: int
    exit_bar: int
    entry_price: float
    exit_price: float
    risk: float
    r_multiple: float
    outcome: str


@dataclass(frozen=True)
class MomentumResult:
    """The outcome of the control."""

    trades: tuple[MomentumTrade, ...] = ()
    #: The gross expectancy per closed trade, in R.
    expectancy_r: float = float("nan")
    #: The number of closed trades.
    n_closed: int = 0
    #: The number of signals the control produced.
    n_signals: int = 0
    #: The number of signals that were dropped because a position was open.
    n_dropped: int = 0
    #: The number of positions that never resolved inside the horizon.
    n_censored: int = 0

    def as_dict(self) -> dict:
        return {
            "n_signals": self.n_signals,
            "n_closed": self.n_closed,
            "n_dropped": self.n_dropped,
            "n_censored": self.n_censored,
            "expectancy_r": self.expectancy_r,
        }


def run_momentum_baseline(bars, *, config: MomentumConfig | None = None) -> MomentumResult:
    """Run the control over ``bars`` and report its expectancy.

    The bars are the engine's ``Bars`` container (or anything with ``open``,
    ``high``, ``low`` and ``close`` sequences).
    """
    config = config or MomentumConfig()
    open_ = np.asarray(bars.open, dtype=np.float64)
    high = np.asarray(bars.high, dtype=np.float64)
    low = np.asarray(bars.low, dtype=np.float64)
    close = np.asarray(bars.close, dtype=np.float64)
    n = close.shape[0]
    if n < config.lookback_bars + config.atr_window + 2:
        return MomentumResult()

    atr = atr_wilder(high, low, close, config.atr_window)

    trades: list[MomentumTrade] = []
    n_signals = 0
    n_dropped = 0
    n_censored = 0
    free_from = -1

    for signal_bar in range(config.lookback_bars, n - 1):
        reference = float(atr[signal_bar])
        if not math.isfinite(reference) or reference <= 0.0:
            continue
        momentum = (float(close[signal_bar]) - float(close[signal_bar - config.lookback_bars])) / reference
        if momentum == 0.0:
            continue
        side = 1 if momentum > 0 else -1
        n_signals += 1
        entry_bar = signal_bar + 1
        if entry_bar < free_from:
            n_dropped += 1
            continue
        entry = float(open_[entry_bar])
        stop = entry - side * config.atr_stop_mult * reference
        risk = abs(entry - stop)
        if risk <= 0.0:
            continue
        target = entry + side * config.rr * risk

        exit_bar = -1
        exit_price = float("nan")
        outcome = "censored"
        horizon = min(n, entry_bar + config.max_holding_bars)
        for bar in range(entry_bar, horizon):
            hit_stop = low[bar] <= stop if side > 0 else high[bar] >= stop
            hit_target = high[bar] >= target if side > 0 else low[bar] <= target
            if hit_stop:
                exit_bar, exit_price, outcome = bar, stop, "stop"
                break
            if hit_target:
                exit_bar, exit_price, outcome = bar, target, "target"
                break
        if exit_bar < 0:
            n_censored += 1
            free_from = horizon
            continue
        r_multiple = (exit_price - entry) * side / risk
        trades.append(
            MomentumTrade(
                side=side,
                entry_bar=entry_bar,
                exit_bar=exit_bar,
                entry_price=entry,
                exit_price=exit_price,
                risk=risk,
                r_multiple=r_multiple,
                outcome=outcome,
            )
        )
        free_from = exit_bar + 1

    closed = [t for t in trades if t.outcome in ("stop", "target")]
    expectancy = (
        sum(t.r_multiple for t in closed) / len(closed) if closed else float("nan")
    )
    return MomentumResult(
        trades=tuple(trades),
        expectancy_r=float(expectancy),
        n_closed=len(closed),
        n_signals=n_signals,
        n_dropped=n_dropped,
        n_censored=n_censored,
    )
