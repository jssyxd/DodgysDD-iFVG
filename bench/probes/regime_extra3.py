"""The regime statistics: the CR1 errors, the contrasts and the permutation.

L3 §C.2 specifies the deliverable exactly: a regression of the realised
multiple on the band dummies with **cluster-robust (CR1) standard errors**
clustered on the session, the pairwise contrasts with their CIs, the
break-even round-trip cost per band, and a **moving-block permutation** test
on the cluster labels.

The CR1 estimator has one property that must hold and that a naive
implementation gets wrong: replicating the observations inside a cluster
must **not** shrink the standard error, because the information is in the
clusters, not in the observations.
"""

from __future__ import annotations

import math

from bench.probes import register

__all__ = []


@register(
    "regime.cr1_errors_are_invariant_to_cluster_replication",
    "regime",
    55,
    "the cluster-robust standard error does not shrink when a cluster is replicated (CR1)",
)
def _cr1_replication() -> tuple[bool, str]:
    """The classic CR1 test.

    The standard error of a mean with cluster-robust errors must depend on
    the *clusters*, not on the number of observations inside them: dividing
    by the observation count instead of using the cluster scores makes the
    interval spuriously tight as a cluster is replicated.
    """
    import numpy as np

    from dodgys_dd_quant.analysis.regime_correlation import _cluster_robust_se

    rng = np.random.default_rng(0)
    values = rng.normal(size=20)
    clusters = np.arange(20)
    once = _cluster_robust_se(values, clusters)

    replicated_values = np.repeat(values, 10)
    replicated_clusters = np.repeat(clusters, 10)
    ten = _cluster_robust_se(replicated_values, replicated_clusters)

    if not math.isfinite(once) or not math.isfinite(ten):
        return False, "the cluster-robust standard error is not finite"
    if ten < 0.9 * once:
        return False, (
            f"replicating every observation ten times shrank the standard error "
            f"from {once:.5f} to {ten:.5f}"
        )
    # with one observation per cluster the estimator must agree with the iid
    # standard error
    iid = float(values.std(ddof=1)) / math.sqrt(values.size)
    if not (0.8 * iid <= once <= 1.25 * iid):
        return False, (
            f"the clustered standard error {once:.5f} does not match the iid "
            f"one {iid:.5f} for one observation per cluster"
        )
    return True, (
        f"the standard error is invariant to replication ({once:.5f} against "
        f"{ten:.5f}) and matches the iid value for one observation per cluster"
    )


@register(
    "regime.correlation_test_reports_cr1_contrasts",
    "regime",
    50,
    "the correlation test reports the band contrasts with their CR1 intervals",
)
def _cr1_contrasts() -> tuple[bool, str]:
    """L3 §C.2's regression deliverable, surfaced.

    The pairwise contrasts between the bands, each with its cluster-robust
    standard error, its 95 % interval and the break-even cost in R.
    """
    from bench import fixtures
    from dodgys_dd_quant.analysis.regime_correlation import regime_correlation_test

    result = regime_correlation_test(fixtures.labelled_frame())
    contrasts = result.get("contrasts")
    if not contrasts:
        return False, "the correlation test reports no contrast"
    for name, contrast in contrasts.items():
        for key in ("contrast_r", "cr1_se", "ci95_lo", "ci95_hi", "break_even_cost_r"):
            if key not in contrast:
                return False, f"the contrast {name!r} carries no {key!r}"
        if not math.isfinite(float(contrast["cr1_se"])):
            return False, f"the contrast {name!r} has no finite standard error"
        lo = float(contrast["ci95_lo"])
        hi = float(contrast["ci95_hi"])
        estimate = float(contrast["contrast_r"])
        if not (lo <= estimate <= hi):
            return False, (
                f"the contrast {name!r} ({estimate:.5f}) is outside its own "
                f"interval [{lo:.5f}, {hi:.5f}]"
            )
        se = float(contrast["cr1_se"])
        if se <= 0.0:
            return False, f"the contrast {name!r} has a non-positive error"
    return True, (
        f"{len(contrasts)} contrast(s) with their cluster-robust intervals"
    )


@register(
    "regime.permutation_is_blocked_and_seeded",
    "regime",
    45,
    "the permutation test moves the labels in blocks and is reproducible from its seed",
)
def _permutation() -> tuple[bool, str]:
    """L3 §C.2's permutation test: moving blocks over the **session** clusters.

    The blocks preserve the regime's own autocorrelation (a volatility
    cluster lasts weeks), which an i.i.d. shuffle would destroy -- and the
    seed makes the p-value reproducible.
    """
    import numpy as np

    from dodgys_dd_quant.analysis.regime_correlation import (
        DEFAULT_BLOCK_CLUSTERS,
        moving_block_permutation,
    )

    rng = np.random.default_rng(1)
    n = 2000
    values = rng.normal(size=n)
    bands = rng.integers(0, 3, size=n)
    cluster = np.arange(n) // 10

    first = moving_block_permutation(values, bands, cluster, seed=7)
    second = moving_block_permutation(values, bands, cluster, seed=7)
    if first.p_value != second.p_value:
        return False, "the permutation test is not reproducible from its seed"
    if first.block_clusters != DEFAULT_BLOCK_CLUSTERS:
        return False, (
            f"the blocks hold {first.block_clusters} clusters, expected "
            f"{DEFAULT_BLOCK_CLUSTERS}"
        )
    if not (0.0 <= first.p_value <= 1.0):
        return False, f"the p-value is {first.p_value}"
    if first.n_replications < 100:
        return False, f"only {first.n_replications} replications"
    return True, (
        f"the permutation moves {first.block_clusters}-cluster blocks, "
        f"{first.n_replications} times, p={first.p_value:.4f} and reproducible"
    )
