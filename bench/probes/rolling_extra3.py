"""The last mile: the RL's management loop and D4's accounting statement.

Two gaps the audits name and no probe covered:

* **The RL's loop was missing.**  The action space, the state vector and the
  position manager (INV1: it cannot open a position) all exist, but nothing
  ever turned a policy's decision into management operations, so the layer
  could not be exercised end to end.
* **D4's accounting statement was missing everywhere but the trainer.**
  R1's F8 caught the trainer's CLI printing an un-caveated census
  expectancy; the walk-forward report, the per-fold rows, the kill-switch
  report, the trial registry's artefact and the runner's terminal output
  had the same defect.  A headline number that does not say which arm it
  came from can be quoted without its accounting.
"""

from __future__ import annotations

import io
import tempfile
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from bench.probes import register

__all__ = []


# ---------------------------------------------------------------------------
# The RL's management loop
# ---------------------------------------------------------------------------


@register(
    "rl.policy_loop_applies_the_action",
    "rolling",
    50,
    "the policy's action is applied to the open position, and the break-even is armed by the position",
)
def _policy_loop() -> tuple[bool, str]:
    """The loop between the policy and the position.

    The break-even trigger is the interesting part: the policy asks for it,
    but the **position** arms it -- the stop moves to the entry only once the
    open profit has actually reached the trigger.
    """
    from dodgys_dd_quant.rl.action_space import PositionAction
    from dodgys_dd_quant.rl.management_loop import manage_step
    from dodgys_dd_quant.rl.position_manager import PositionManager

    position = PositionManager(
        size=1.0,
        side=1,
        entry_price=100.0,
        stop_price=98.0,
        target_price=104.0,
        max_size=1.5,
    )
    action = PositionAction(position_multiplier=1.0, be_trigger_r=1.0, partial_tp_ratio=0.0)

    below = manage_step(position, action, open_pnl_r=0.5)
    if "break_even" in below:
        return False, "the break-even fired before the trigger was reached"
    if position.stop_price != 98.0:
        return False, f"the stop moved to {position.stop_price} without the trigger"

    reached = manage_step(position, action, open_pnl_r=1.5)
    if "break_even" not in reached:
        return False, "the break-even did not fire at the trigger"
    if position.stop_price != 100.0:
        return False, f"the stop is {position.stop_price}, expected the entry"

    scaled = manage_step(
        position,
        PositionAction(position_multiplier=1.5, be_trigger_r=0.0, partial_tp_ratio=0.25),
        open_pnl_r=1.5,
    )
    if "scale" not in scaled or "partial_tp" not in scaled:
        return False, f"the size actions were not applied: {scaled}"
    if not (0.0 < position.size < 1.5):
        return False, f"the size is {position.size}"
    return True, (
        f"the break-even waits for the trigger, the scale and the partial "
        f"take-profit apply: {reached + scaled}"
    )


@register(
    "rl.management_never_exceeds_the_cap",
    "rolling",
    45,
    "a policy cannot push the position past the action space's cap, nor widen the stop",
)
def _management_cap() -> tuple[bool, str]:
    """L4 §D.1 mechanism 3: the cap holds however greedy the policy is."""
    from dodgys_dd_quant.rl.action_space import PositionAction
    from dodgys_dd_quant.rl.management_loop import manage_step
    from dodgys_dd_quant.rl.position_manager import ManagementError, PositionManager

    position = PositionManager(
        size=1.0,
        side=1,
        entry_price=100.0,
        stop_price=98.0,
        target_price=104.0,
        max_size=1.5,
    )
    greedy = PositionAction(position_multiplier=1.5, be_trigger_r=0.0, partial_tp_ratio=0.0)
    for _ in range(20):
        manage_step(position, greedy, open_pnl_r=2.0)
        if position.size > 1.5 + 1e-12:
            return False, f"the size reached {position.size}, past the cap"

    widened = False
    try:
        position.set_stop(97.0)
    except ManagementError:
        widened = True
    if not widened:
        return False, "the stop could be widened"
    return True, (
        f"20 greedy steps leave the size at {position.size} (cap 1.5) and the "
        f"stop cannot be widened"
    )


@register(
    "rl.managed_trade_reports_its_realised_r",
    "rolling",
    40,
    "the managed position reports the realised multiple the reward consumes",
)
def _managed_realised_r() -> tuple[bool, str]:
    """The reward is the realised R under the policy -- so the loop must
    report it, together with the peak the 1.5R penalty looks at.
    """
    from dodgys_dd_quant.rl.action_space import PositionAction
    from dodgys_dd_quant.rl.management_loop import run_managed_position
    from dodgys_dd_quant.rl.position_manager import PositionManager
    from dodgys_dd_quant.rl.reward import episode_reward, is_penalised

    position = PositionManager(
        size=1.0,
        side=1,
        entry_price=100.0,
        stop_price=98.0,
        target_price=104.0,
        max_size=1.5,
    )

    def policy(state):
        return PositionAction(position_multiplier=1.0, be_trigger_r=0.0, partial_tp_ratio=0.0)

    bars = [(100.5, 99.5, 100.0), (101.5, 100.5, 101.0), (103.5, 102.5, 103.0), (105.0, 103.0, 104.5)]
    trade = run_managed_position(position, bars, policy, risk=2.0)
    if trade.reason != "target":
        return False, f"the position closed as {trade.reason!r}, expected the target"
    if abs(trade.realised_r - 2.0) > 1e-9:
        return False, f"the realised multiple is {trade.realised_r}, expected 2.0"
    if trade.peak_r < trade.realised_r:
        return False, "the peak is below the realised multiple"
    if is_penalised(trade.peak_r, trade.realised_r):
        return False, "a profitable trade was flagged as a stall"
    reward = episode_reward(realised_r=trade.realised_r, peak_r=trade.peak_r)
    if not reward > 0:
        return False, f"the reward of the trade is {reward}"
    return True, (
        f"the trade closed at {trade.exit_price} for {trade.realised_r} R "
        f"(peak {trade.peak_r} R), reward {reward:.3f}"
    )


@register(
    "rl.policy_loop_is_auditable",
    "rolling",
    35,
    "every management operation is recorded, so a policy's decisions can be audited",
)
def _policy_audit() -> tuple[bool, str]:
    """The manager keeps an audit trail; the loop must use it."""
    from dodgys_dd_quant.rl.action_space import PositionAction
    from dodgys_dd_quant.rl.management_loop import run_managed_position
    from dodgys_dd_quant.rl.position_manager import PositionManager

    position = PositionManager(
        size=1.0,
        side=1,
        entry_price=100.0,
        stop_price=98.0,
        target_price=104.0,
        max_size=1.5,
    )

    def policy(state):
        return PositionAction(position_multiplier=1.0, be_trigger_r=0.5, partial_tp_ratio=0.0)

    bars = [(100.5, 99.5, 100.0), (101.5, 100.5, 101.0), (102.5, 101.5, 102.0)]
    trade = run_managed_position(position, bars, policy, risk=2.0)
    if not position.operations:
        return False, "the manager recorded no operation"
    if len(trade.operations) != len(position.operations):
        return False, "the trail and the manager disagree"
    if not any(op.startswith("set_stop") for op in position.operations):
        return False, "the break-even was never applied to the stop"
    return True, (
        f"{len(position.operations)} operations recorded: {position.operations}"
    )


# ---------------------------------------------------------------------------
# D4's accounting statement
# ---------------------------------------------------------------------------


@register(
    "rolling.accounting_statement_is_on_every_report",
    "rolling",
    55,
    "every report carries D4's accounting statement, so no headline can be quoted without it",
)
def _accounting_everywhere() -> tuple[bool, str]:
    """The statement must travel with the numbers.

    Checked on the four artefacts that can be quoted on their own: the
    walk-forward report, the per-fold rows, the kill-switch report and the
    trial registry's Parquet.
    """
    import pyarrow.parquet as pq

    from dodgys_dd_quant.backtest.accounting import ACCOUNTING_STATEMENT
    from dodgys_dd_quant.backtest.kill_switch import compute_kill_switch
    from dodgys_dd_quant.backtest.trials import TrialRegistry
    from dodgys_dd_quant.backtest.walk_forward import TradeStats, WalkForwardReport

    surfaces: dict[str, bool] = {}

    report = WalkForwardReport(
        folds=[],
        portfolio=TradeStats(n=3, n_closed=3),
        baseline=TradeStats(n=5, n_closed=5),
        equity_r=[0.1, -0.2, 0.3],
    )
    payload = report.as_dict()
    surfaces["walk_forward_report"] = payload.get("accounting_statement") == ACCOUNTING_STATEMENT

    from dodgys_dd_quant.backtest.fold_report import fold_report_row

    row = fold_report_row(
        fold_index=0,
        windows={},
        asof="2024-01-31",
        n_candidates=10,
        n_candidates_labeled=6,
        n_censored=1,
        n_trades=3,
        n_trades_kept=2,
        win_rate=0.5,
        expectancy_r_gross=0.1,
        expectancy_r_net=-0.2,
        pf=1.2,
        pf_net=0.9,
        max_drawdown_r=-1.0,
        max_consecutive_losses=2,
        auc_test=0.5,
        accuracy_test=0.5,
        brier_score=0.25,
        p_pred_distribution=[0.4, 0.6],
        p_pred_distribution_train=[0.5, 0.5],
        cost_r=0.3,
        n_roll_boundary_bars_excluded=0,
    )
    surfaces["fold_row"] = row.get("accounting_statement") == ACCOUNTING_STATEMENT

    switch = compute_kill_switch(
        p_pred_distribution={"mean": 0.6, "sd": 0.1},
        p_pred_distribution_train={"mean": 0.5, "sd": 0.1},
        realised_top_decile_win_rate=0.4,
        top_importance_churn=0.1,
    )
    surfaces["kill_switch"] = switch.get("accounting_statement") == ACCOUNTING_STATEMENT

    with tempfile.TemporaryDirectory() as tmp:
        registry = TrialRegistry(Path(tmp))
        registry.record(name="arm-1", oos_returns=[0.1, -0.2, 0.3])
        target = registry.to_parquet()
        table = pq.read_table(target)
        column = table.column("accounting_statement").to_pylist()
        surfaces["trial_registry"] = bool(column) and column[0] == ACCOUNTING_STATEMENT

    missing = [name for name, ok in surfaces.items() if not ok]
    if missing:
        return False, f"the statement is missing from: {sorted(missing)}"
    return True, (
        f"the statement travels with {len(surfaces)} reporting surfaces"
    )


@register(
    "rolling.cli_prints_the_accounting_statement",
    "rolling",
    50,
    "the runner's terminal output prints the accounting statement with the headline",
)
def _cli_statement() -> tuple[bool, str]:
    """The CLI is the surface a number is most likely to be copied from."""
    from dodgys_dd_quant.backtest.accounting import ACCOUNTING_STATEMENT
    from dodgys_dd_quant.backtest.cost_model import get_profile
    from dodgys_dd_quant.backtest.runner import _print_report
    from dodgys_dd_quant.backtest.walk_forward import TradeStats, WalkForwardReport

    report = WalkForwardReport(
        folds=[],
        portfolio=TradeStats(n=3, n_closed=3),
        baseline=TradeStats(n=5, n_closed=5),
        equity_r=[0.1, -0.2, 0.3],
    )
    args = SimpleNamespace(
        symbol="BTCUSDT",
        timeframe="1m",
        preset="honest",
        inversion_window="code",
        slippage_ticks=1,
    )
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        _print_report(report, get_profile("binance"), args)
    output = buffer.getvalue()
    if ACCOUNTING_STATEMENT not in output:
        return False, "the CLI output does not carry the accounting statement"
    return True, "the CLI prints the accounting statement above the headline"


@register(
    "rolling.report_carries_the_baseline_next_to_the_gated_arm",
    "rolling",
    45,
    "the gated arm is always reported next to the independent rule-only baseline",
)
def _baseline_next_to() -> tuple[bool, str]:
    """D4: a result must be reported *against* the baseline, on the same data,
    the same costs and the same accounting.
    """
    from dodgys_dd_quant.backtest.walk_forward import TradeStats, WalkForwardReport

    payload = WalkForwardReport(
        folds=[],
        portfolio=TradeStats(n=3, n_closed=3),
        baseline=TradeStats(n=5, n_closed=5),
        equity_r=[0.1, -0.2, 0.3],
    ).as_dict()
    for key in ("portfolio", "baseline"):
        if key not in payload:
            return False, f"the report has no {key!r} arm"
    if payload["portfolio"] is None or payload["baseline"] is None:
        return False, "the report's arms are empty"
    return True, "the gated arm and the rule-only baseline travel together"


@register(
    "rolling.accounting_statement_names_the_census_trap",
    "rolling",
    40,
    "the statement says which arm the t-statistic may be quoted from (D4)",
)
def _statement_names_the_trap() -> tuple[bool, str]:
    """The statement is only useful if it names the trap it closes."""
    from dodgys_dd_quant.backtest.accounting import ACCOUNTING_STATEMENT

    text = ACCOUNTING_STATEMENT.lower()
    for phrase in ("one position at a time", "census", "artefact", "baseline"):
        if phrase not in text:
            return False, f"the statement does not mention {phrase!r}"
    return True, "the statement names the accounting, the census trap and the baseline"
