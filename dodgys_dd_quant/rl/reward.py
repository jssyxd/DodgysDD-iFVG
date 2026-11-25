"""The RL reward -- Sortino-like, terminal-dominant, with the 1.5R penalty.

The doc's specification (doc L152): the reward is Sortino-like, and it
carries an **extra penalty** for *"reaching 1.5R and then failing to move
the stop"* -- the failure mode the doc singles out.

Two design points matter:

* **Terminal-dominant.**  A Sortino-style per-step reward computed on
  1-minute deltas rewards noise (L4 §D.2).  The episode reward here is
  the **realised R of the position** under the policy, adjusted downward
  by the 1.5R failure penalty and by the realised cost in R, with only an
  optional, small per-step shaping term.
* **Market-agnostic and lagged.**  Every state feature is either R-normalised
  or dimensionless, so a policy trained on one market can be applied to
  another -- the precondition L4 §D.4 sets for any transfer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = [
    "DEFAULT_LAMBDA",
    "RewardConfig",
    "episode_reward",
    "sortino_step_reward",
]

#: The weight of the 1.5R failure penalty (doc L152).  It lives in the
#: constants module with the other thresholds.
DEFAULT_LAMBDA: float = 0.5

#: The gain at which a setup is considered to have "reached 1.5R" (doc L152).
PENALTY_THRESHOLD_R: float = 1.5


@dataclass(frozen=True, slots=True)
class RewardConfig:
    """The reward's parameters."""

    #: The weight of the 1.5R failure penalty.
    penalty_lambda: float = DEFAULT_LAMBDA
    #: The gain at which the penalty applies.
    penalty_threshold_r: float = PENALTY_THRESHOLD_R
    #: The realised round-trip cost of the trade, in R.
    cost_r: float = 0.0
    #: The floor of the downside deviation, so the ratio cannot explode.
    downside_floor: float = 1e-3


def sortino_step_reward(
    step_return_r: float,
    downside_deviation: float,
    *,
    floor: float = 1e-3,
) -> float:
    """The Sortino-like per-step reward.

    ``step_return_r / max(downside_deviation, floor)`` -- the denominator is
    the *downside* deviation only, so upside volatility does not dilute the
    reward.
    """
    return float(step_return_r) / max(float(downside_deviation), float(floor))


def episode_reward(
    realised_r: float,
    peak_r: float,
    *,
    config: RewardConfig = RewardConfig(),
    shaping: float = 0.0,
) -> float:
    """The episode's terminal reward.

    Parameters
    ----------
    realised_r:
        The trade's realised multiple.
    peak_r:
        The largest multiple the trade reached.
    config:
        The reward's parameters.
    shaping:
        An optional small per-step shaping term (zero by default: the
        reward is terminal-dominant).
    """
    reward = float(realised_r) - float(config.cost_r) + float(shaping)
    if (
        float(peak_r) >= config.penalty_threshold_r
        and float(realised_r) < 0.0
    ):
        # The doc's singled-out failure: it reached 1.5R and then let it
        # turn into a loss without moving the stop.
        reward -= config.penalty_lambda
    return float(reward)


def is_penalised(peak_r: float, realised_r: float, config: RewardConfig = RewardConfig()) -> bool:
    """Whether the 1.5R failure penalty applies to this trade."""
    return (
        float(peak_r) >= config.penalty_threshold_r
        and float(realised_r) < 0.0
    )
