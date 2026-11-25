"""The position manager -- the RL's entire capability surface (INV1).

The agent is given this object and nothing else.  It exposes exactly four
management operations:

* ``set_stop(price)`` -- move the stop (to break-even, typically);
* ``set_take_profit(price)`` -- move the target;
* ``reduce_size(fraction)`` -- take profit on part of the position;
* ``scale_in(factor, cap)`` -- add to the position, **capped** at the
  action-space maximum.

There is no ``submit_order``, no ``open`` and no access to an order
factory, so the RL *cannot* open a position even if it wanted to: the
entry path and the management path are separate objects with separate
capabilities (L4 §D.1 mechanism 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["PositionManager", "ManagementError"]


class ManagementError(RuntimeError):
    """Raised when a management request cannot be honoured."""


@dataclass
class PositionManager:
    """The only object the RL policy is given.

    It manages a position that is **already open**.  Every method is a
    management operation; none of them opens a position.
    """

    #: The position's current size (always positive; the direction is not
    #: the policy's to choose).
    size: float = 0.0
    #: The direction of the open position: ``+1`` long, ``-1`` short.  It is
    #: given to the policy, not chosen by it.
    side: int = 1
    entry_price: float = 0.0
    stop_price: float = 0.0
    target_price: float = 0.0
    #: The cap on the position size.  The action grid's multiplier may not
    #: exceed it (mechanism 1 of L4 §D.1).
    max_size: float = 0.0
    #: Every management operation that was performed, for the audit trail.
    operations: list[str] = field(default_factory=list)

    # -- the management operations -----------------------------------------

    def set_stop(self, price: float) -> None:
        """Move the stop to ``price``.

        A stop that would be *worse* than the current one is refused: the
        policy may tighten the risk, never widen it.
        """
        if self.size <= 0.0:
            raise ManagementError("no position is open")
        if self.side > 0 and price < self.stop_price:
            raise ManagementError("the stop may not be widened")
        if self.side < 0 and price > self.stop_price:
            raise ManagementError("the stop may not be widened")
        self.stop_price = float(price)
        self.operations.append(f"set_stop({price})")

    def set_take_profit(self, price: float) -> None:
        """Move the target to ``price``."""
        if self.size <= 0.0:
            raise ManagementError("no position is open")
        self.target_price = float(price)
        self.operations.append(f"set_take_profit({price})")

    def reduce_size(self, fraction: float) -> None:
        """Close ``fraction`` of the position (a partial take-profit)."""
        if self.size <= 0.0:
            raise ManagementError("no position is open")
        if not (0.0 <= fraction <= 1.0):
            raise ManagementError(f"fraction={fraction} is outside [0, 1]")
        self.size *= 1.0 - float(fraction)
        self.operations.append(f"reduce_size({fraction})")

    def scale_in(self, factor: float, cap: float | None = None) -> None:
        """Scale the position by ``factor``, never above the cap.

        The cap is the **action space's** maximum multiplier applied to the
        original size, so a policy that always asks for the maximum can at
        most reach 1.5x -- the invariant L4 §D.1 mechanism 3 asserts.
        """
        if self.size <= 0.0:
            raise ManagementError("no position is open")
        limit = self.max_size if cap is None else min(self.max_size, float(cap))
        target = self.size * float(factor)
        if target > limit:
            target = limit
        self.size = target
        self.operations.append(f"scale_in({factor})")

    # -- what the policy may not do ----------------------------------------

    def open_position(self, *args, **kwargs):
        """**Not available.**  The RL may never open a position (INV1)."""
        raise ManagementError(
            "the RL may not open a position: the entry path is the rule engine's alone"
        )

    def submit_order(self, *args, **kwargs):
        """**Not available.**  The RL has no order factory (INV1)."""
        raise ManagementError("the RL has no order factory: it may only manage an open position")
