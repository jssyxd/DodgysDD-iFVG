"""Tests for the RL layer's INV1 invariant.

INV1: *"The RL agent must never open a position."*  The audit calls it a
hard invariant that must be asserted in tests (RULE_SPEC §2.2), and L4
§D.1 gives four independent mechanisms.  Three of them are testable
without a learner, which is what these tests check.
"""

from __future__ import annotations

import pytest

from dodgys_dd_quant.rl import (
    ACTION_SPACE,
    BE_TRIGGER_GRID,
    PARTIAL_TP_GRID,
    POSITION_MULTIPLIER_GRID,
    ManagementError,
    PositionAction,
    PositionManager,
    RewardConfig,
    action_space_size,
    build_state,
    close_location_value,
    episode_reward,
    sortino_step_reward,
)


# ---------------------------------------------------------------------------
# Mechanism 1: type separation
# ---------------------------------------------------------------------------


def test_the_action_carries_no_field_that_could_open_a_position():
    fields = set(PositionAction.__dataclass_fields__)
    for forbidden in ("side", "quantity", "direction", "open", "entry"):
        assert forbidden not in fields


def test_the_action_space_is_the_specified_grid():
    assert POSITION_MULTIPLIER_GRID == (0.5, 1.0, 1.5)
    assert BE_TRIGGER_GRID == (0.0, 0.5, 1.0, 1.5)
    assert PARTIAL_TP_GRID == (0.0, 0.25, 0.5, 0.75, 1.0)
    assert action_space_size() == 60
    assert len(ACTION_SPACE) == 60


def test_every_action_is_bounded():
    for action in ACTION_SPACE:
        assert 0.0 <= action.position_multiplier <= 1.5
        assert action.be_trigger_r >= 0.0
        assert 0.0 <= action.partial_tp_ratio <= 1.0


def test_a_negative_break_even_trigger_is_rejected():
    """On a short, a negative trigger is a stop *above* the entry."""
    with pytest.raises(ValueError, match="negative"):
        PositionAction(1.0, -0.5, 0.0)


def test_an_out_of_grid_multiplier_is_rejected():
    with pytest.raises(ValueError, match="outside the grid"):
        PositionAction(2.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Mechanism 2: capability restriction
# ---------------------------------------------------------------------------


def test_the_manager_cannot_open_a_position():
    manager = PositionManager(size=1.0, side=1, entry_price=100.0)
    with pytest.raises(ManagementError, match="may not open"):
        manager.open_position()


def test_the_manager_has_no_order_factory():
    manager = PositionManager(size=1.0, side=1, entry_price=100.0)
    with pytest.raises(ManagementError, match="no order factory"):
        manager.submit_order()


def test_the_manager_only_manages_an_open_position():
    manager = PositionManager(size=0.0)
    with pytest.raises(ManagementError, match="no position is open"):
        manager.set_stop(99.0)
    with pytest.raises(ManagementError, match="no position is open"):
        manager.reduce_size(0.5)
    with pytest.raises(ManagementError, match="no position is open"):
        manager.scale_in(1.5)


def test_the_manager_can_manage_an_open_position():
    manager = PositionManager(
        size=2.0, side=1, entry_price=100.0, stop_price=95.0, target_price=110.0, max_size=3.0
    )
    manager.set_stop(100.0)
    manager.set_take_profit(115.0)
    manager.reduce_size(0.5)
    assert manager.size == pytest.approx(1.0)
    manager.scale_in(1.5)
    assert manager.size == pytest.approx(1.5)
    assert len(manager.operations) == 4


def test_the_manager_never_scales_past_the_cap():
    """The "malicious policy" of L4 §D.1 mechanism 3."""
    manager = PositionManager(size=1.0, side=1, entry_price=100.0, max_size=1.5)
    for _ in range(10):
        manager.scale_in(1.5)
    assert manager.size <= 1.5 + 1e-12


def test_the_stop_may_not_be_widened():
    manager = PositionManager(size=1.0, side=1, entry_price=100.0, stop_price=95.0)
    manager.set_stop(98.0)
    with pytest.raises(ManagementError, match="widened"):
        manager.set_stop(90.0)


# ---------------------------------------------------------------------------
# The reward
# ---------------------------------------------------------------------------


def test_the_reward_penalises_reaching_1_5r_and_then_losing():
    config = RewardConfig(penalty_lambda=0.5)
    # Reached 1.5R and ended negative -> penalised.
    assert episode_reward(-1.0, 1.5, config=config) < -1.0
    # Reached 1.5R and ended positive -> not penalised.
    assert episode_reward(2.0, 1.5, config=config) == pytest.approx(2.0)
    # Never reached 1.5R -> not penalised.
    assert episode_reward(-1.0, 0.5, config=config) == pytest.approx(-1.0)


def test_the_reward_is_terminal_dominant():
    """The episode reward is the realised R, not a sum of per-step noise."""
    config = RewardConfig(cost_r=0.05)
    assert episode_reward(2.0, 2.0, config=config) == pytest.approx(1.95)


def test_the_sortino_step_reward_uses_the_downside_deviation():
    assert sortino_step_reward(1.0, 0.5) == pytest.approx(2.0)
    assert sortino_step_reward(1.0, 0.0) > 0.0  # the floor keeps it finite


# ---------------------------------------------------------------------------
# The state
# ---------------------------------------------------------------------------


def test_the_state_is_r_normalised_and_dimensionless():
    state = build_state(
        entry_price=100.0,
        current_price=110.0,
        risk=10.0,
        peak_price=120.0,
        regime=1,
        holding_bars=5,
        max_holding_bars=10,
        high=111.0,
        low=109.0,
        close=110.0,
    )
    assert state.open_pnl_r == pytest.approx(1.0)
    assert state.peak_pnl_r == pytest.approx(2.0)
    assert state.holding_time_bars == pytest.approx(0.5)
    assert state.vxn_regime == 1
    vector = state.as_vector()
    assert vector.shape == (5,)
    assert vector.dtype.kind == "f"


def test_the_imbalance_proxy_is_bounded():
    assert close_location_value(110.0, 100.0, 105.0) == pytest.approx(0.5)
    assert close_location_value(110.0, 100.0, 100.0) == pytest.approx(0.0)
    assert close_location_value(110.0, 100.0, 110.0) == pytest.approx(1.0)
    assert close_location_value(100.0, 100.0, 100.0) == 0.0  # a flat bar
