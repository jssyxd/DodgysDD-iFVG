"""The no-FVG control and the abort criteria that need it.

A4 asks whether the FVG contributes anything, and the comparison is against
a **plain ATR-normalised momentum system** on the same bars and the same
costs.  That control did not exist, so the criterion could not be evaluated;
A2's "the only subsets with a positive gross expectancy are the expensive
ones" needed the same kind of helper.
"""

from __future__ import annotations

import math
from pathlib import Path

from bench.probes import register

__all__ = []


@register(
    "rolling.momentum_baseline_is_an_independent_control",
    "rolling",
    50,
    "the no-FVG momentum control trades, with its own one-position accounting",
)
def _momentum_control() -> tuple[bool, str]:
    """The control is a complete system, not a placeholder.

    It produces signals, takes positions one at a time, and reports a finite
    gross expectancy.  It never looks at the FVG: it is the thing the FVG
    has to beat.
    """
    from bench import fixtures
    from dodgys_dd_quant.analysis.momentum_baseline import run_momentum_baseline

    bars = fixtures.btc_1m()
    result = run_momentum_baseline(bars)
    if result.n_signals <= 0:
        return False, "the control produced no signal"
    if result.n_closed <= 0:
        return False, "the control closed no trade"
    if not math.isfinite(result.expectancy_r):
        return False, "the control's expectancy is not finite"
    if result.n_dropped <= 0:
        return False, "the control never dropped a blocked signal"

    # one position at a time: no two trades may overlap
    ordered = sorted(result.trades, key=lambda t: t.entry_bar)
    for previous, trade in zip(ordered, ordered[1:]):
        if trade.entry_bar <= previous.exit_bar:
            return False, (
                f"two control trades overlap: {previous.entry_bar}-"
                f"{previous.exit_bar} and {trade.entry_bar}-{trade.exit_bar}"
            )
    for trade in result.trades:
        if trade.outcome not in ("stop", "target"):
            return False, f"a control trade closed as {trade.outcome!r}"
        if trade.r_multiple <= -1.0 and trade.r_multiple != -1.0:
            return False, "a control trade lost more than its risk"
    return True, (
        f"{result.n_signals} signals, {result.n_closed} closed trades, "
        f"{result.n_dropped} dropped, expectancy {result.expectancy_r:+.4f} R"
    )


@register(
    "rolling.abort_criteria_a4_compares_the_control",
    "rolling",
    45,
    "A4 fires when the FVG does not beat the no-FVG control",
)
def _a4_compares() -> tuple[bool, str]:
    """The criterion needs both arms on the **same** accounting.

    The probe drives it with the control's own expectancy and with a
    deliberately worse result for the FVG, and with a better one.
    """
    from bench import fixtures
    from dodgys_dd_quant.analysis.momentum_baseline import run_momentum_baseline
    from dodgys_dd_quant.backtest.abort import evaluate_abort_criteria

    control = run_momentum_baseline(fixtures.btc_1m())
    if not math.isfinite(control.expectancy_r):
        return False, "the control's expectancy is not finite"

    worse = evaluate_abort_criteria(
        expectancy_r_gross=control.expectancy_r - 0.05,
        momentum_baseline_gross_r=control.expectancy_r,
    )
    if "A4" not in worse.fired:
        return False, f"A4 did not fire when the FVG lost to the control"

    better = evaluate_abort_criteria(
        expectancy_r_gross=control.expectancy_r + 0.05,
        momentum_baseline_gross_r=control.expectancy_r,
    )
    if "A4" in better.fired:
        return False, "A4 fired although the FVG beat the control"
    return True, (
        f"A4 compares the FVG against the control's {control.expectancy_r:+.4f} R "
        f"and fires only when the FVG loses"
    )


@register(
    "rolling.abort_criteria_a2_finds_the_cost_heavy_arms",
    "rolling",
    45,
    "A2 fires when the only profitable arms are the expensive ones",
)
def _a2_cost_heavy() -> tuple[bool, str]:
    """A2: the edge is structurally untradable when only the costly arms win."""
    from dodgys_dd_quant.backtest.abort import cost_heavy_subsets, evaluate_abort_criteria

    cheap_wins = cost_heavy_subsets(
        [("cheap", 0.02, 0.05), ("expensive", 0.01, 0.60)]
    )
    if cheap_wins["only_cost_heavy_positive"]:
        return False, "a cheap profitable arm was counted as cost-heavy"
    heavy_only = cost_heavy_subsets(
        [("cheap", -0.02, 0.05), ("expensive", 0.03, 0.60)]
    )
    if not heavy_only["only_cost_heavy_positive"]:
        return False, "the cost-heavy verdict did not fire when it should"

    fired = evaluate_abort_criteria(
        cost_heavy_subsets_positive=heavy_only["only_cost_heavy_positive"]
    )
    if "A2" not in fired.fired:
        return False, f"A2 did not fire: {fired.fired}"
    quiet = evaluate_abort_criteria(
        cost_heavy_subsets_positive=cheap_wins["only_cost_heavy_positive"]
    )
    if "A2" in quiet.fired:
        return False, "A2 fired although a cheap arm was profitable"
    return True, (
        "A2 identifies the case where only the cost-heavy arms are profitable"
    )


@register(
    "rolling.abort_criteria_a4_is_evaluated_in_a_walk_forward",
    "rolling",
    45,
    "a walk-forward that is given the bars evaluates A4 against the control",
)
def _a4_in_a_walk_forward() -> tuple[bool, str]:
    """The criterion must be checkable in a real run, not only in a unit test.

    Without the bars the control cannot run and A4 is reported as *not
    evaluated*; with them the run compares the FVG's gross expectancy with
    the control's and says which side it is on.
    """
    import pathlib

    from bench import fixtures
    from dodgys_dd_quant.backtest.walk_forward import Fold, walk_forward

    candidates = list(fixtures.candidate_log("BTCUSDT", "honest"))
    if not candidates:
        return False, "no candidates to inspect"
    bars = fixtures.btc_15m()
    folds = [
        Fold(
            asof="2024-03-01",
            asof_ns=1_709_251_200_000_000_000,
            directory=pathlib.Path("."),
            test_start="2024-03-01",
            test_end="2024-03-31",
        )
    ]

    without = walk_forward(candidates, len(bars), folds)
    criteria = without.kill_switch.get("abort_criteria", {})
    if not criteria:
        return False, "the run reports no abort criteria"
    names = {c["name"] for c in criteria.get("criteria", [])}
    if "A4" not in names:
        return False, "the run does not even report A4"

    with_bars = walk_forward(candidates, len(bars), folds, bars=bars)
    payload = with_bars.kill_switch.get("abort_criteria", {})
    evaluated = {
        c["name"]: c for c in payload.get("criteria", []) if c.get("evaluated")
    }
    if "A4" not in evaluated:
        return False, "A4 was not evaluated although the bars were given"
    return True, (
        "the run evaluates A4 against the control "
        f"(fired: {payload.get('fired')})"
    )


@register(
    "rolling.kill_switch_verdict_is_visible_in_the_run_output",
    "rolling",
    40,
    "the runner prints the kill-switch's level and the abort criteria behind it",
)
def _verdict_visible() -> tuple[bool, str]:
    """The safety net has to be readable.

    "Stop and publish the negative result" is a rule nobody reads if the
    run's output does not say what the verdict was.
    """
    import io
    from contextlib import redirect_stdout
    from types import SimpleNamespace

    from bench import fixtures
    from dodgys_dd_quant.backtest.cost_model import get_profile
    from dodgys_dd_quant.backtest.runner import _print_report
    from dodgys_dd_quant.backtest.walk_forward import Fold, walk_forward

    candidates = list(fixtures.candidate_log("BTCUSDT", "honest"))
    if not candidates:
        return False, "no candidates to inspect"
    bars = fixtures.btc_15m()
    folds = [
        Fold(
            asof="2024-03-01",
            asof_ns=1_709_251_200_000_000_000,
            directory=Path("."),
            test_start="2024-03-01",
            test_end="2024-03-31",
        )
    ]
    report = walk_forward(candidates, len(bars), folds, bars=bars)
    args = SimpleNamespace(
        symbol="BTCUSDT",
        timeframe="15m",
        preset="honest",
        inversion_window="code",
        slippage_ticks=1,
    )
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        _print_report(report, get_profile("binance"), args)
    output = buffer.getvalue()
    if "KILL-SWITCH" not in output:
        return False, "the run output does not print the kill-switch's verdict"
    if "ABORT CRITERIA" not in output:
        return False, "the run output does not print the abort criteria"
    level = report.kill_switch.get("level", "none")
    if f"KILL-SWITCH: {level}" not in output:
        return False, f"the output does not carry the level {level!r}"
    return True, f"the run output prints the verdict (level {level})"
