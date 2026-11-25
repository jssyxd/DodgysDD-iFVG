"""The regime family and the pre-registered experiment (L3 §C.2, §C.7).

L3 §C.2 pre-registers a **family of five** regime variables, each tested
on the same sample, with the correction applied **jointly** across the
family.  The audit's verdict was that this had never been run.

The probes here check that the family exists, that the correction is
applied across the family (not per variable), and that the real
experiment the audit nominates -- M-E1, the equity sample -- can be run.
"""

from __future__ import annotations

import math

from bench.probes import register

__all__ = []


@register(
    "regime.family_is_pre_registered",
    "regime",
    50,
    "the five-variable regime family is pre-registered and testable together (L3 section C.2)",
)
def _family_registered() -> tuple[bool, str]:
    """L3 §C.2 lists five variables; the family must be a fixed, named list.

    The fourth -- realised volatility -- is the *self-referential control*:
    a regime effect that a self-referential volatility measure cannot
    reproduce is not evidence for a market regime.  It is not optional.
    """
    from dodgys_dd_quant.analysis.regime_correlation import REGIME_FAMILY

    names = [entry.name for entry in REGIME_FAMILY]
    if len(names) < 5:
        return False, f"the family has {len(names)} variables, expected at least 5"
    if "realised_volatility" not in names:
        return False, "the family has no realised-volatility control"
    return True, f"the pre-registered family: {names}"


@register(
    "regime.correction_is_joint_across_the_family",
    "regime",
    50,
    "the multiple-testing correction is applied jointly across the family (L3 section C.2)",
)
def _correction_joint() -> tuple[bool, str]:
    """Holm-Bonferroni must be applied to the family **as a whole**.

    Applying it per variable would let a family of five arms make five
    uncorrected claims.
    """
    from dodgys_dd_quant.analysis.regime_correlation import REGIME_FAMILY, holm_bonferroni

    p_values = [0.001 * (i + 1) for i in range(len(REGIME_FAMILY))]
    result = holm_bonferroni(p_values)
    if result["family_size"] != len(REGIME_FAMILY):
        return False, "the correction did not run over the whole family"
    # The smallest p-value is multiplied by the family size, not by one.
    expected = p_values[0] * len(REGIME_FAMILY)
    if not math.isclose(result["p_adjusted"][0], expected, rel_tol=1e-9):
        return False, (
            f"the smallest p-value was adjusted to {result['p_adjusted'][0]}, "
            f"expected {expected}"
        )
    return True, f"the correction spans {result['family_size']} variables"


@register(
    "regime.equity_experiment_runs",
    "regime",
    50,
    "the pre-registered equity experiment (M-E1) runs on the QQQ sample with VXN",
)
def _equity_experiment() -> tuple[bool, str]:
    """L3 §C.7 nominates M-E1 as the one experiment that could settle the
    regime claim on the data that already exists: QQQ 15-minute joined to
    the governed VXN daily series.

    The probe runs it and requires a real answer -- per-band expectancies
    and a p-value -- not a stub.
    """
    from dodgys_dd_quant.analysis.regime_correlation import run_regime_family

    from bench import fixtures

    qqq = fixtures.frame_from_fixture("qqq_15m")
    days, closes = fixtures.vxn_daily()
    result = run_regime_family(qqq, days=days, closes=closes, replications=200)
    if not result:
        return False, "the regime family produced no result"
    rows = result.get("family", [])
    if len(rows) < 2:
        return False, f"the family produced {len(rows)} result(s), expected the whole family"
    vxn = next((r for r in rows if r.get("variable") == "vxn_bands"), None)
    if vxn is None:
        return False, "the family's VXN band result is missing"
    if vxn.get("p_value") is None:
        return False, "the VXN band result carries no p-value"
    return True, (
        f"{len(rows)} variables tested on QQQ 15m; the VXN band spread is "
        f"{vxn.get('spread'):.4f} with p={vxn.get('p_value'):.4f}"
    )


@register(
    "regime.decision_rule_is_e_r_based",
    "regime",
    45,
    "the gate is E[R]_net > 0, not the doc's literal P >= 0.58 (L4 section C.5)",
)
def _decision_rule() -> tuple[bool, str]:
    """L4 §C.5: the doc's 0.58 is "the single most expensive mistake
    available in this system".

    The correct rule is ``accept iff E[R]_net > 0``, i.e.
    ``P > (1 + cost_R) / 3`` -- a **conditional** threshold, because the
    cost enters it.  The doc's 0.58 may be reported as a secondary,
    stricter filter, but it must not be the production gate.
    """
    from dodgys_dd_quant.analysis.regime_correlation import decision_threshold

    for cost in (0.0, 0.05, 0.091):
        threshold = decision_threshold(cost_r=cost)
        expected = (1.0 + cost) / 3.0
        if not math.isclose(threshold, expected, rel_tol=1e-9):
            return False, (
                f"the threshold for a cost of {cost} R is {threshold}, expected {expected}"
            )
    if decision_threshold(cost_r=0.0) >= 0.58:
        return False, "the decision threshold is at or above the doc's 0.58"
    return True, (
        f"the gate is cost-aware: "
        f"{decision_threshold(cost_r=0.0):.4f} at zero cost, "
        f"{decision_threshold(cost_r=0.091):.4f} at the NQ round trip"
    )


@register(
    "regime.brier_score_is_reported",
    "regime",
    35,
    "the family's probability quality is reported with a Brier score (L4 section F.2)",
)
def _brier() -> tuple[bool, str]:
    """L4 §F.2 lists ``brier_score`` among the per-fold model-quality fields."""
    from dodgys_dd_quant.analysis.regime_correlation import brier_score

    score = brier_score([1, 0, 1, 0], [0.9, 0.1, 0.8, 0.2])
    if not math.isclose(score, 0.025, rel_tol=1e-6):
        return False, f"the Brier score of a perfect forecast is {score}, expected 0.025"
    worst = brier_score([1, 0], [0.0, 1.0])
    if worst <= score:
        return False, "a maximally wrong forecast did not score worse than a perfect one"
    return True, f"the Brier score is {score:.4f} for a perfect forecast"
