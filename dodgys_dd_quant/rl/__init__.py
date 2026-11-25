"""The RL layer -- position management only (INV1, L4 §D).

The rule engine opens positions; this layer may only **manage** an open
one.  That is an invariant, enforced in the type system:

* the action space carries no field that could open a position
  (:mod:`dodgys_dd_quant.rl.action_space`);
* the policy is given a capability-restricted
  :class:`~dodgys_dd_quant.rl.position_manager.PositionManager` with no
  order factory;
* the reward is terminal-dominant and carries the doc's 1.5R failure
  penalty (:mod:`dodgys_dd_quant.rl.reward`);
* the state is market-agnostic and lagged
  (:mod:`dodgys_dd_quant.rl.state_builder`).

No PPO learner is included: L4 §D.5 is explicit that the RL is the **last**
thing to build and only once there is an edge to manage -- and the audits
measured the edge at zero (D4).  What is here is the contract the learner
will have to satisfy, so that it cannot be built wrong.
"""

from __future__ import annotations

from dodgys_dd_quant.rl.action_space import (
    ACTION_SPACE,
    BE_TRIGGER_GRID,
    PARTIAL_TP_GRID,
    POSITION_MULTIPLIER_GRID,
    PositionAction,
    action_space_size,
)
from dodgys_dd_quant.rl.position_manager import ManagementError, PositionManager
from dodgys_dd_quant.rl.reward import (
    DEFAULT_LAMBDA,
    RewardConfig,
    episode_reward,
    sortino_step_reward,
)
from dodgys_dd_quant.rl.state_builder import RLState, build_state, close_location_value

__all__ = [
    "ACTION_SPACE",
    "BE_TRIGGER_GRID",
    "DEFAULT_LAMBDA",
    "ManagementError",
    "PARTIAL_TP_GRID",
    "POSITION_MULTIPLIER_GRID",
    "PositionAction",
    "PositionManager",
    "RLState",
    "RewardConfig",
    "action_space_size",
    "build_state",
    "close_location_value",
    "episode_reward",
    "sortino_step_reward",
]
