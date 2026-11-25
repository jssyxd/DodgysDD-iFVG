"""The RL action space -- position management only (INV1).

The discussion says it plainly: *"严格禁止 RL 自行开仓，仅负责开仓后的仓位管理与离场优化"*
(doc L150) -- the RL is strictly forbidden from opening a position; it only
manages and optimises the exit of a position that is already open.  That is
an invariant, not a convention, so it is enforced **in the type**.

Three independent mechanisms, each sufficient on its own:

1. **Type separation.**  :class:`PositionAction` has exactly three fields --
   the position multiplier, the break-even trigger and the partial
   take-profit ratio.  There is no field that could name a side, a
   quantity or an entry price, so an action *cannot* express "open".
2. **Action-space bounds.**  The multiplier grid is ``{0.5, 1.0, 1.5}``
   (SVG-A), the break-even trigger grid is ``{0.0, 0.5, 1.0, 1.5}`` R
   (A29) and the partial take-profit ratio grid is
   ``{0, 0.25, 0.5, 0.75, 1.0}``.  Every grid is bounded: a multiplier
   can at most scale the position by 1.5x, and a negative break-even
   trigger -- which on a short would be a stop *above* the entry, i.e. a
   de-facto open -- is not in the grid.
3. **Capability restriction.**  The agent is handed a
   :class:`~dodgys_dd_quant.rl.position_manager.PositionManager`, which
   exposes only the four management operations and no order factory.

The grid is 3 x 4 x 5 = **60 discrete actions** (L4 §D.2).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Iterator

__all__ = [
    "BE_TRIGGER_GRID",
    "PARTIAL_TP_GRID",
    "POSITION_MULTIPLIER_GRID",
    "PositionAction",
    "ACTION_SPACE",
    "action_space_size",
]

#: The position multiplier grid (SVG-A).
POSITION_MULTIPLIER_GRID: tuple[float, ...] = (0.5, 1.0, 1.5)

#: The break-even trigger grid, in R (A29).
BE_TRIGGER_GRID: tuple[float, ...] = (0.0, 0.5, 1.0, 1.5)

#: The partial take-profit ratio grid (A29).
PARTIAL_TP_GRID: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)


@dataclass(frozen=True, slots=True)
class PositionAction:
    """One management action.

    There is deliberately **no** field that could open, reverse or close a
    position to zero: the action can only scale the size, move the stop to
    break-even, or take part of the profit.
    """

    #: Scale the position's size by this factor.
    position_multiplier: float
    #: Move the stop to break-even once the position reaches this gain, in R.
    be_trigger_r: float
    #: Take this fraction of the position at the target.
    partial_tp_ratio: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.position_multiplier <= 1.5):
            raise ValueError(
                f"position_multiplier={self.position_multiplier} is outside the grid"
            )
        if self.be_trigger_r < 0.0:
            raise ValueError(
                f"be_trigger_r={self.be_trigger_r} is negative; on a short that is a "
                "stop above the entry, i.e. a de-facto open"
            )
        if not (0.0 <= self.partial_tp_ratio <= 1.0):
            raise ValueError(
                f"partial_tp_ratio={self.partial_tp_ratio} is outside [0, 1]"
            )


def _build_action_space() -> tuple[PositionAction, ...]:
    return tuple(
        PositionAction(multiplier, be_trigger, partial_tp)
        for multiplier, be_trigger, partial_tp in itertools.product(
            POSITION_MULTIPLIER_GRID, BE_TRIGGER_GRID, PARTIAL_TP_GRID
        )
    )


#: Every action the policy may choose.
ACTION_SPACE: tuple[PositionAction, ...] = _build_action_space()


def action_space_size() -> int:
    """The number of discrete actions (60)."""
    return len(ACTION_SPACE)


def iter_actions() -> Iterator[PositionAction]:
    """Iterate the action space."""
    return iter(ACTION_SPACE)
