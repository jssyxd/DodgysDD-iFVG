"""The management loop -- the piece between the policy and the position.

The action space (60 discrete actions), the state vector and the position
manager all exist, and the manager refuses to open anything (INV1).  What
was missing is the **loop**: nothing ever turned a policy's decision into
management operations, so the RL layer could not be exercised end to end
without torch.

This module is that loop, and it is deliberately small:

* the break-even trigger moves the stop to the entry, but **only once the
  position has actually reached the trigger** -- a policy that asks for the
  break-even at 0.5 R before the trade is 0.5 R in profit gets nothing;
* the partial take-profit reduces the size by the requested share;
* the position multiplier scales the size, and the action space's cap holds
  the result (L4 §D.1 mechanism 3).

The loop never opens anything: it is given an open position and it manages
it.  The reward consumes the realised multiple the loop reports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence

from dodgys_dd_quant.rl.action_space import PositionAction
from dodgys_dd_quant.rl.position_manager import PositionManager
from dodgys_dd_quant.rl.state_builder import RLState, build_state

__all__ = [
    "ManagedTrade",
    "Policy",
    "manage_step",
    "realised_r",
    "run_managed_position",
]


class Policy(Protocol):
    """What the loop expects from a policy: state in, action out."""

    def __call__(self, state: RLState) -> PositionAction:  # pragma: no cover
        ...


@dataclass(frozen=True)
class ManagedTrade:
    """The outcome of a managed position."""

    #: The realised multiple, in R.
    realised_r: float
    #: The largest multiple the position reached, in R.
    peak_r: float
    #: The price the position was closed at.
    exit_price: float
    #: Why it closed: ``"stop"``, ``"target"`` or ``"horizon"``.
    reason: str
    #: How many bars the position was held.
    bars_held: int
    #: Every management operation that was performed, in order.
    operations: tuple[str, ...] = ()


def realised_r(side: int, entry_price: float, exit_price: float, risk: float) -> float:
    """The realised multiple of a closed position, in R."""
    unit = float(risk) if risk > 0.0 else float("nan")
    if not math.isfinite(unit) or unit == 0.0:
        return float("nan")
    return (float(exit_price) - float(entry_price)) * int(side) / unit


def manage_step(
    position: PositionManager,
    action: PositionAction,
    *,
    open_pnl_r: float,
) -> tuple[str, ...]:
    """Apply one policy action to the open position.

    Returns the operations that were performed, in order.  The break-even is
    **armed by the position, not by the policy**: the stop moves to the entry
    only when the open profit has reached the action's trigger.
    """
    applied: list[str] = []

    multiplier = float(action.position_multiplier)
    if abs(multiplier - 1.0) > 1e-12:
        position.scale_in(multiplier)
        applied.append("scale")

    trigger = float(action.be_trigger_r)
    entry = float(position.entry_price)
    if trigger > 0.0 and math.isfinite(open_pnl_r) and open_pnl_r >= trigger:
        tighter = (
            (position.side > 0 and position.stop_price < entry)
            or (position.side < 0 and position.stop_price > entry)
        )
        if tighter:
            position.set_stop(entry)
            applied.append("break_even")

    fraction = float(action.partial_tp_ratio)
    if fraction > 0.0:
        position.reduce_size(fraction)
        applied.append("partial_tp")

    return tuple(applied)


def run_managed_position(
    position: PositionManager,
    bars: Sequence[tuple[float, float, float]],
    policy: Policy,
    *,
    risk: float,
    max_holding_bars: int = 240,
    regime: int = -1,
    operations: list[str] | None = None,
) -> ManagedTrade:
    """Walk the bars, ask the policy for an action, apply it.

    ``bars`` are ``(high, low, close)`` triples of the position's own
    timeframe.  The position closes when its stop or its target is hit, or
    when the horizon expires.  The realised multiple it reports is what the
    reward consumes (``rl.reward.episode_reward``).
    """
    trail: list[str] = [] if operations is None else operations
    entry = float(position.entry_price)
    peak_price = entry
    exit_price = float("nan")
    reason = "horizon"
    bars_held = 0

    for index, (high, low, close) in enumerate(bars):
        bars_held = index + 1
        if position.side > 0:
            peak_price = max(peak_price, float(high))
        else:
            peak_price = min(peak_price, float(high))

        hit_stop = (
            low <= position.stop_price
            if position.side > 0
            else high >= position.stop_price
        )
        hit_target = (
            high >= position.target_price
            if position.side > 0
            else low <= position.target_price
        )
        if hit_stop:
            exit_price = float(position.stop_price)
            reason = "stop"
            break
        if hit_target:
            exit_price = float(position.target_price)
            reason = "target"
            break

        state = build_state(
            entry_price=entry,
            current_price=float(close),
            risk=float(risk),
            peak_price=peak_price,
            regime=int(regime),
            holding_bars=index,
            max_holding_bars=int(max_holding_bars),
            high=float(high),
            low=float(low),
            close=float(close),
        )
        action = policy(state)
        applied = manage_step(position, action, open_pnl_r=state.open_pnl_r)
        trail.extend(applied)
        if index + 1 >= int(max_holding_bars):
            exit_price = float(close)
            reason = "horizon"
            break

    if not math.isfinite(exit_price):
        exit_price = float(peak_price) if math.isfinite(peak_price) else entry

    peak_multiple = (
        (peak_price - entry) * position.side / float(risk)
        if float(risk) > 0.0
        else float("nan")
    )
    return ManagedTrade(
        realised_r=realised_r(position.side, entry, exit_price, risk),
        peak_r=float(peak_multiple),
        exit_price=float(exit_price),
        reason=reason,
        bars_held=int(bars_held),
        operations=tuple(trail),
    )
