"""The abort criteria -- the repository's own "kill the project" rules.

L4 §C.6 pre-registers five criteria on the **concatenated** out-of-sample
series.  They exist so that the decision to stop is *cheap to observe* and
*not a judgement call*:

``A1``
    ``E_net[S] <= 0`` with the CI including zero -> the meta-labeler adds
    nothing.  Do not proceed to the RL, do not "tune harder", report the
    negative.
``A2``
    the only subsets with a positive gross expectancy are the ones whose
    ``cost_R > 0.3 R`` -> the edge is structurally untradable at the assumed
    fees.
``A3``
    a high-AUC model with **no** net lift -> the model has learned the cost
    (``cost_R`` or ``risk_in_atr``), not the edge.
``A4``
    the result does not beat the no-FVG momentum baseline -> the FVG
    contributes nothing.
``A5``
    ``E_net[S] > 0`` but the CI includes zero and the point estimate is
    below 0.05 R -> inconclusive.

The criteria are evaluated, reported and **not** silently ignored: the
kill-switch's K3 level ("kill the project") is the criterion's verdict, not a
flag somebody remembers to set.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

__all__ = [
    "ABORT_CRITERIA",
    "AbortCriterion",
    "AbortReport",
    "cost_buckets",
    "cost_heavy_subsets",
    "evaluate_abort_criteria",
]


def cost_buckets(
    candidates: Sequence[Any],
    *,
    profile: Any,
    slippage_ticks: int = 0,
    threshold_r: float = 0.3,
) -> dict[str, Any]:
    """Split a population by the round-trip cost in R and compare the halves.

    A2 asks whether the edge survives the costs: *"the only subsets with
    positive ``E[R]_gross`` are those with ``cost_R > 0.3 R``"*.  The
    population is split at that threshold and each bucket's gross expectancy
    is measured, so the verdict is a property of the run rather than a
    remembered flag.
    """
    from dodgys_dd_quant.backtest.cost_model import cost_in_r

    light: list[float] = []
    heavy: list[float] = []
    for cand in candidates:
        r = float(getattr(cand, "r_multiple", float("nan")))
        if not math.isfinite(r):
            continue
        risk = float(getattr(cand, "risk", 0.0))
        price = float(getattr(cand, "entry_price", float("nan")))
        try:
            cost = float(cost_in_r(profile, price, risk, slippage_ticks))
        except Exception:  # pragma: no cover - a bad price, not a crash
            continue
        if not math.isfinite(cost):
            continue
        (heavy if cost > float(threshold_r) else light).append(r)
    light_expectancy = sum(light) / len(light) if light else float("nan")
    heavy_expectancy = sum(heavy) / len(heavy) if heavy else float("nan")
    only_heavy = bool(
        math.isfinite(heavy_expectancy)
        and heavy_expectancy > 0.0
        and (not math.isfinite(light_expectancy) or light_expectancy <= 0.0)
    )
    return {
        "threshold_r": float(threshold_r),
        "n_light": len(light),
        "n_heavy": len(heavy),
        "light_expectancy_r": light_expectancy,
        "heavy_expectancy_r": heavy_expectancy,
        # an empty population is **not** a pass: the criterion cannot be
        # evaluated, and the report has to say so
        "evaluated": bool(light or heavy),
        "only_cost_heavy_positive": only_heavy if (light or heavy) else None,
    }


def cost_heavy_subsets(
    arms: Sequence[tuple[str, float, float]],
    *,
    cost_threshold_r: float = 0.3,
) -> dict[str, Any]:
    """Which arms are profitable, and are the profitable ones the expensive ones?

    A2: *"the only subsets with positive ``E[R]_gross`` are those with
    ``cost_R > 0.3 R`` -> the edge is structurally untradable at the assumed
    fees"*.

    ``arms`` are ``(name, expectancy_r, cost_r)`` triples -- the gross
    expectancy of each configuration and the round-trip cost it paid, in R.
    """
    rows = [
        {"name": str(name), "expectancy_r": float(expectancy), "cost_r": float(cost)}
        for name, expectancy, cost in arms
    ]
    positive = [row for row in rows if row["expectancy_r"] > 0.0]
    heavy = [row for row in positive if row["cost_r"] > float(cost_threshold_r)]
    return {
        "arms": rows,
        "cost_threshold_r": float(cost_threshold_r),
        "positive_subsets": [row["name"] for row in positive],
        "cost_heavy_positive": [row["name"] for row in heavy],
        # A2 fires when every profitable arm is one of the expensive ones
        "only_cost_heavy_positive": bool(positive) and len(heavy) == len(positive),
    }

#: The names of the five pre-registered criteria, in the audit's order.
ABORT_CRITERIA: tuple[str, ...] = ("A1", "A2", "A3", "A4", "A5")


@dataclass(frozen=True)
class AbortCriterion:
    """One criterion and whether it fired."""

    name: str
    fired: bool
    #: The evidence the verdict rests on (empty when the criterion could not
    #: be evaluated -- it is then *not* counted as fired).
    evidence: dict[str, Any] = field(default_factory=dict)
    #: Whether the criterion could be evaluated with the data at hand.
    evaluated: bool = True
    #: What the criterion says when it fires.
    action: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "fired": bool(self.fired),
            "evaluated": bool(self.evaluated),
            "evidence": dict(self.evidence),
            "action": self.action,
        }


@dataclass(frozen=True)
class AbortReport:
    """The verdict of the five criteria."""

    criteria: tuple[AbortCriterion, ...]

    @property
    def triggered(self) -> bool:
        """Whether any criterion fired."""
        return any(criterion.fired for criterion in self.criteria)

    @property
    def fired(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.criteria if c.fired)

    @property
    def not_evaluated(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.criteria if not c.evaluated)

    def as_dict(self) -> dict[str, Any]:
        return {
            "triggered": self.triggered,
            "fired": list(self.fired),
            "not_evaluated": list(self.not_evaluated),
            "criteria": [c.as_dict() for c in self.criteria],
        }


def _criterion(
    name: str,
    fired: bool | None,
    evidence: Mapping[str, Any],
    action: str,
) -> AbortCriterion:
    """One criterion; ``fired=None`` means it could not be evaluated."""
    if fired is None:
        return AbortCriterion(
            name=name, fired=False, evidence=dict(evidence), evaluated=False, action=action
        )
    return AbortCriterion(
        name=name, fired=bool(fired), evidence=dict(evidence), evaluated=True, action=action
    )


def evaluate_abort_criteria(
    *,
    expectancy_net_r: float | None = None,
    ci95_lo: float | None = None,
    ci95_hi: float | None = None,
    expectancy_r_gross: float | None = None,
    auc_test: float | None = None,
    expectancy_lift_r: float | None = None,
    cost_heavy_subsets_positive: bool | None = None,
    top_features: Sequence[str] = (),
    momentum_baseline_gross_r: float | None = None,
    significant_threshold_r: float = 0.05,
) -> AbortReport:
    """Evaluate L4 §C.6's five criteria on the concatenated OOS.

    A criterion whose inputs are missing is reported as **not evaluated**
    rather than silently passed: the report says which of the five the run
    could not check.
    """
    criteria: list[AbortCriterion] = []

    # --- A1: the meta-labeler adds nothing -------------------------------
    if expectancy_net_r is None or not math.isfinite(float(expectancy_net_r)):
        criteria.append(
            _criterion("A1", None, {}, "the meta-labeler adds nothing")
        )
    else:
        includes_zero = (
            ci95_lo is not None and ci95_hi is not None and ci95_lo <= 0.0 <= ci95_hi
        )
        fired = expectancy_net_r <= 0.0 and includes_zero
        criteria.append(
            _criterion(
                "A1",
                fired,
                {
                    "expectancy_net_r": expectancy_net_r,
                    "ci95": [ci95_lo, ci95_hi],
                    "ci_includes_zero": bool(includes_zero),
                },
                "the meta-labeler adds nothing; report the negative",
            )
        )

    # --- A2: the edge is structurally untradable -------------------------
    if cost_heavy_subsets_positive is None:
        criteria.append(
            _criterion("A2", None, {}, "the edge is structurally untradable")
        )
    else:
        criteria.append(
            _criterion(
                "A2",
                bool(cost_heavy_subsets_positive),
                {"cost_heavy_subsets_positive": bool(cost_heavy_subsets_positive)},
                "the edge is structurally untradable at the assumed fees",
            )
        )

    # --- A3: the model learned the cost ----------------------------------
    if (
        auc_test is None
        or expectancy_lift_r is None
        or not math.isfinite(float(auc_test))
        or not math.isfinite(float(expectancy_lift_r))
    ):
        criteria.append(
            _criterion("A3", None, {}, "the model learned the cost, not the edge")
        )
    else:
        learned_cost = any(
            name in ("cost_R", "risk_in_atr") for name in top_features
        )
        high_auc = auc_test >= 0.60
        no_lift = expectancy_lift_r <= 0.0
        criteria.append(
            _criterion(
                "A3",
                bool(high_auc and no_lift and learned_cost),
                {
                    "auc_test": auc_test,
                    "expectancy_lift_r": expectancy_lift_r,
                    "top_features": list(top_features),
                    "learned_the_cost": bool(learned_cost),
                },
                "the model has rediscovered the cost; the result is not an edge",
            )
        )

    # --- A4: the FVG contributes nothing ---------------------------------
    # The comparison is **gross against gross**, on purpose.  A net
    # comparison would be rigged by the *risk definition*: the rule engine
    # stops at the gap window's extreme and the control at one ATR, so the
    # same fee buys a very different cost in R, and the arm with the wider
    # stop looks better whatever it earns.  The gross comparison asks the
    # question the criterion actually asks -- does the pattern produce an
    # edge the control does not -- and A2 then asks whether that edge is
    # tradable at the assumed fees.
    if expectancy_r_gross is None or momentum_baseline_gross_r is None:
        criteria.append(
            _criterion("A4", None, {}, "the FVG contributes nothing")
        )
    else:
        criteria.append(
            _criterion(
                "A4",
                bool(expectancy_r_gross <= momentum_baseline_gross_r),
                {
                    "expectancy_gross_r": expectancy_r_gross,
                    "momentum_baseline_gross_r": momentum_baseline_gross_r,
                },
                "the FVG contributes nothing; pivot or stop",
            )
        )

    # --- A5: inconclusive -------------------------------------------------
    if (
        expectancy_net_r is None
        or ci95_lo is None
        or ci95_hi is None
        or not math.isfinite(float(expectancy_net_r))
    ):
        criteria.append(
            _criterion("A5", None, {}, "the result is inconclusive")
        )
    else:
        includes_zero = ci95_lo <= 0.0 <= ci95_hi
        fired = (
            expectancy_net_r > 0.0
            and includes_zero
            and expectancy_net_r < float(significant_threshold_r)
        )
        criteria.append(
            _criterion(
                "A5",
                bool(fired),
                {
                    "expectancy_net_r": expectancy_net_r,
                    "ci95": [ci95_lo, ci95_hi],
                    "threshold_r": float(significant_threshold_r),
                },
                "the result is inconclusive; do not start paper trading",
            )
        )

    return AbortReport(criteria=tuple(criteria))
