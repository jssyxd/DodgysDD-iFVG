"""The abort criteria -- the repository's own "kill the project" rules.

L4 §C.6 pre-registers five criteria so that stopping is *cheap to observe*
and not a judgement call.  They were specified and never evaluated: the
kill-switch took a boolean somebody had to remember to set.

These probes assert the criteria fire on the data they describe, stay quiet
on a healthy result, report the ones they could not evaluate, and reach the
kill-switch's K3 level.
"""

from __future__ import annotations

import math

from bench.probes import register

__all__ = []


@register(
    "rolling.abort_criteria_are_evaluated",
    "rolling",
    55,
    "L4 §C.6's five abort criteria fire on the data they describe",
)
def _abort_criteria() -> tuple[bool, str]:
    """Each criterion, on the data that triggers it.

    A1 the net expectancy is not positive and the CI includes zero; A2 only
    the cost-heavy subsets are profitable; A3 a high-AUC model with no lift
    that has learned the cost; A4 the FVG does not beat the momentum
    baseline; A5 the net expectancy is positive but inconclusive.
    """
    from dodgys_dd_quant.backtest.abort import ABORT_CRITERIA, evaluate_abort_criteria

    if ABORT_CRITERIA != ("A1", "A2", "A3", "A4", "A5"):
        return False, f"the criteria are {ABORT_CRITERIA}"

    a1 = evaluate_abort_criteria(
        expectancy_net_r=-0.02, ci95_lo=-0.06, ci95_hi=0.01
    )
    if "A1" not in a1.fired:
        return False, f"A1 did not fire on a negative, inconclusive result: {a1.fired}"

    a2 = evaluate_abort_criteria(cost_heavy_subsets_positive=True)
    if "A2" not in a2.fired:
        return False, f"A2 did not fire when only the cost-heavy subsets win"

    a3 = evaluate_abort_criteria(
        auc_test=0.72,
        expectancy_lift_r=-0.01,
        top_features=["cost_R", "risk_in_atr"],
    )
    if "A3" not in a3.fired:
        return False, f"A3 did not fire on a cost-learning model: {a3.fired}"

    a4 = evaluate_abort_criteria(
        expectancy_r_gross=0.01, momentum_baseline_gross_r=0.05
    )
    if "A4" not in a4.fired:
        return False, f"A4 did not fire when the momentum baseline wins"

    a5 = evaluate_abort_criteria(
        expectancy_net_r=0.02, ci95_lo=-0.01, ci95_hi=0.05
    )
    if "A5" not in a5.fired:
        return False, f"A5 did not fire on an inconclusive positive result"

    healthy = evaluate_abort_criteria(
        expectancy_net_r=0.30,
        ci95_lo=0.10,
        ci95_hi=0.50,
        expectancy_r_gross=0.40,
        momentum_baseline_gross_r=0.05,
        cost_heavy_subsets_positive=False,
        auc_test=0.65,
        expectancy_lift_r=0.20,
        top_features=["checklist_score", "sweep_detected"],
    )
    if healthy.triggered:
        return False, f"a healthy result tripped {healthy.fired}"
    if healthy.not_evaluated:
        return False, (
            f"the healthy result left {healthy.not_evaluated} unevaluated"
        )
    return True, (
        "each criterion fires on its own data and a healthy result trips none"
    )


@register(
    "rolling.abort_criteria_report_what_they_could_not_check",
    "rolling",
    40,
    "a criterion whose inputs are missing is reported as not evaluated, never silently passed",
)
def _abort_not_evaluated() -> tuple[bool, str]:
    """Silence is not a pass.

    The walk-forward can check A1 and A5 on its own; A2, A3 and A4 need the
    cost-heavy subsets, the feature importances and the momentum control.
    """
    from dodgys_dd_quant.backtest.abort import evaluate_abort_criteria

    report = evaluate_abort_criteria(
        expectancy_net_r=-0.01, ci95_lo=-0.05, ci95_hi=0.02
    )
    not_evaluated = set(report.not_evaluated)
    if "A2" not in not_evaluated or "A3" not in not_evaluated:
        return False, f"the missing inputs were not reported: {sorted(not_evaluated)}"
    if "A1" in not_evaluated:
        return False, "A1 was not evaluated although its inputs were given"
    # A1 can fire on its own evidence; the unknown criteria must not.
    for name in not_evaluated:
        if name in report.fired:
            return False, f"{name} fired although it was not evaluated"
    payload = report.as_dict()
    if not payload["criteria"]:
        return False, "the report serialises to nothing"
    for criterion in payload["criteria"]:
        if not criterion.get("action"):
            return False, f"the criterion {criterion.get('name')} states no action"
    return True, (
        f"{len(not_evaluated)} criteria are reported as not evaluated and the "
        f"rest are evaluated"
    )


@register(
    "rolling.abort_criteria_reach_the_kill_switch",
    "rolling",
    45,
    "the abort criteria are the kill-switch's K3 trigger, not a manual flag",
)
def _abort_reaches_kill_switch() -> tuple[bool, str]:
    """K3 -- kill the project -- comes from the criteria's verdict."""
    from dodgys_dd_quant.backtest.abort import evaluate_abort_criteria
    from dodgys_dd_quant.backtest.kill_switch import compute_kill_switch

    triggered = evaluate_abort_criteria(
        expectancy_net_r=-0.02, ci95_lo=-0.06, ci95_hi=0.01
    )
    switch = compute_kill_switch(abort_report=triggered)
    if switch["level"] != "K3":
        return False, f"the criteria triggered but the switch says {switch['level']}"
    if not switch.get("abort_criteria"):
        return False, "the switch does not carry the criteria's verdict"

    healthy = evaluate_abort_criteria(
        expectancy_net_r=0.30,
        ci95_lo=0.10,
        ci95_hi=0.50,
        momentum_baseline_gross_r=0.05,
        cost_heavy_subsets_positive=False,
        auc_test=0.65,
        expectancy_lift_r=0.20,
        top_features=["checklist_score"],
    )
    quiet = compute_kill_switch(abort_report=healthy)
    if quiet["level"] == "K3":
        return False, "a healthy result killed the project"
    return True, (
        "the criteria's verdict is the kill-switch's K3 trigger and a healthy "
        "result does not trip it"
    )
