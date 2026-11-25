"""The regime correlation test (L3 §C.2).

This is the deliverable the audit says was **never run**: *"No correlation
check implemented: no"* (L3 §A.2).  The question is not "does VXN predict
the market" -- that is established -- but the only claim a trading system
can act on:

    H1: the expectancy of the iFVG rule engine is a function of the
        volatility regime, i.e. ``E[R | G] != const``;
    H0: ``E[R | G] = E[R]`` for every regime variable ``G``.

Why the ordinary test is not enough
-----------------------------------
A parametric t-test on overlapping, autocorrelated trades is not a valid
test here, for two reasons the audit names:

* **Trades overlap.**  The candidates are not independent observations.
* **The regime has its own serial structure.**  Volatility clusters for
  weeks, so a naive shuffle of the labels destroys the regime's
  autocorrelation and makes the test **anti-conservative**.

So the test here is a **moving-block permutation test on the cluster
labels** (L3 §C.2):

1. order the clusters by time;
2. cut the label sequence into contiguous blocks of 20 clusters (~1 trading
   month) -- long enough to preserve the regime's own autocorrelation;
3. randomly re-order the blocks (2,000 replications);
4. recompute the band contrast under each re-assignment;
5. report ``p = (#{replicates with stat >= observed} + 1) / (2000 + 1)``,
   where the statistic is the **band spread**
   ``max_b E[R|b] - min_b E[R|b]``.

This preserves the trade->cluster mapping, the trade weights, the
within-cluster correlation and the regime's serial structure.

The unit of analysis is **one candidate setup** (one row of the D2 log),
not one trade and not one bar: the D2 log carries every candidate,
winners and losers alike, so the estimator is not survivorship-biased.

The outcome scale, and one confound that must not be forgotten
----------------------------------------------------------------
The regime **sets the target distance** (L107-109: RR 1:1.5-1:2 in the low
band, 1:2.5-1:3 in the normal one), so the D2 log's ``r_multiple`` is
``+rr(G)`` for a winner and ``-1`` for a loser.  The raw band means are
therefore **not comparable across bands**: a wider target in one band
inflates that band's ``E[R]`` mechanically, whatever the setups are worth.

So the test reports two things, and the permutation statistic uses the
**comparable** one:

* ``expectancy_r`` -- the raw D2 mean, which embeds the band's own RR. It
  is what the log says and what the position sizing would have earned.
* the **hit scale** ``2*label - 1``: ``+1`` for a setup that reached its
  target, ``-1`` for one that hit its stop, ``NaN`` for an unresolved
  setup.  It is the outcome every band can be compared on, because it does
  not depend on the target distance.

The permutation test is run on the hit scale, so the question it answers is
the honest one: *does the regime band tell you anything about whether a
setup resolves in its favour?*  A band spread that comes only from the
regime's own RR policy does not move it.

One caveat that the numbers alone cannot remove
------------------------------------------------
The regime policy also changes the **population**: the gap filter's ATR
floor is band-dependent, so each band contains a different set of
candidates.  The test therefore measures the conditional expectancy *in the
population the regime policy produces*, not in a fixed population with the
band attached.  A permutation p-value below 0.05 says the band label is
associated with the outcome **beyond what time-ordering alone would
produce**; it does not say the band is a *filter* that would have improved
a fixed candidate set.  Deciding whether the band is worth acting on needs
the out-of-sample, cost-aware test in L4, not this one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

__all__ = [
    "BandExpectancy",
    "FamilyVariable",
    "PermutationResult",
    "REGIME_FAMILY",
    "band_contrasts",
    "band_expectancies",
    "brier_score",
    "cluster_ids",
    "decision_threshold",
    "holm_bonferroni",
    "moving_block_permutation",
    "regime_correlation_test",
    "run_regime_family",
]

#: The number of clusters per permutation block (~1 trading month).
DEFAULT_BLOCK_CLUSTERS = 20

#: The number of permutation replications.
DEFAULT_REPLICATIONS = 2000

#: The seed, so the test is reproducible.
DEFAULT_SEED = 20261123


@dataclass(frozen=True, slots=True)
class BandExpectancy:
    """The expectancy of one regime band."""

    band: int
    n: int
    expectancy_r: float
    ci95_lo: float
    ci95_hi: float
    break_even_cost_r: float

    def as_dict(self) -> dict:
        return {
            "band": self.band,
            "n": self.n,
            "expectancy_r": self.expectancy_r,
            "ci95_lo": self.ci95_lo,
            "ci95_hi": self.ci95_hi,
            "break_even_cost_r": self.break_even_cost_r,
        }


@dataclass(frozen=True, slots=True)
class PermutationResult:
    """The outcome of the moving-block permutation test."""

    statistic: float
    p_value: float
    n_replications: int
    n_clusters: int
    block_clusters: int
    seed: int

    def as_dict(self) -> dict:
        return {
            "statistic": self.statistic,
            "p_value": self.p_value,
            "n_replications": self.n_replications,
            "n_clusters": self.n_clusters,
            "block_clusters": self.block_clusters,
            "seed": self.seed,
        }


def _as_float_array(values) -> np.ndarray:
    return np.asarray(values, dtype=np.float64)


def cluster_ids(
    ts_event,
    *,
    cluster_minutes: int = 1440,
) -> np.ndarray:
    """The cluster a candidate belongs to.

    The cluster is the **publication period** of the regime variable: for a
    daily index, the US trading session whose close was used (L3 §C.2).
    Candidates within one cluster share the same regime value, so they are
    not independent observations -- which is exactly what the cluster-robust
    errors and the block permutation handle.
    """
    ts = np.asarray(ts_event, dtype=np.int64)
    return ts // (int(cluster_minutes) * 60_000_000_000)


def band_expectancies(
    r_multiple,
    bands,
    *,
    cluster: np.ndarray | None = None,
    break_even_cost_r: float = 0.0,
) -> dict[int, BandExpectancy]:
    """``E[R | band]`` per band, with a 95 % CI.

    When ``cluster`` is given the CI is **cluster-robust** (CR1): the
    variance is computed on the cluster means and scaled by the number of
    clusters, so the intracluster correlation cannot flatter the interval.
    """
    r = _as_float_array(r_multiple)
    g = np.asarray(bands, dtype=np.int64)
    if r.shape != g.shape:
        raise ValueError("r_multiple and bands must have the same length")

    keep = np.isfinite(r)
    r = r[keep]
    g = g[keep]
    if cluster is not None:
        cluster = np.asarray(cluster, dtype=np.int64)[keep]

    out: dict[int, BandExpectancy] = {}
    for band in np.unique(g):
        mask = g == band
        values = r[mask]
        n = int(values.shape[0])
        if n == 0:
            continue
        mean = float(values.mean())
        if cluster is None:
            se = float(values.std(ddof=1) / math.sqrt(n)) if n > 1 else float("nan")
        else:
            se = _cluster_robust_se(values, cluster[mask])
        half = 1.96 * se if math.isfinite(se) else float("nan")
        out[int(band)] = BandExpectancy(
            band=int(band),
            n=n,
            expectancy_r=mean,
            ci95_lo=mean - half if math.isfinite(half) else float("nan"),
            ci95_hi=mean + half if math.isfinite(half) else float("nan"),
            break_even_cost_r=break_even_cost_r,
        )
    return out


def _cluster_robust_se(values: np.ndarray, cluster: np.ndarray) -> float:
    """The CR1 cluster-robust standard error of the mean.

    The CR1 estimator is built from the **cluster scores**
    ``u_c = sum_{i in c} (x_i - x_bar)``::

        Var(x_bar) = G/(G-1) * (N-1)/N * sum_c u_c^2 / ((G-1) * N^2)

    The scores are the *sums* inside a cluster, not the cluster means: a
    cluster that holds ten observations carries ten times the information of
    a cluster that holds one.  Dividing by the number of observations
    instead of by the number of clusters would make the standard error
    shrink as a cluster is replicated, which is the classic way to get a
    spuriously tight interval.
    """
    n = int(values.shape[0])
    if n < 2:
        return float("nan")
    unique = np.unique(cluster)
    g = int(unique.shape[0])
    if g < 2:
        return float("nan")
    sums = np.zeros(g, dtype=np.float64)
    counts = np.zeros(g, dtype=np.float64)
    index = {int(c): i for i, c in enumerate(unique)}
    for value, c in zip(values, cluster):
        i = index[int(c)]
        sums[i] += value
        counts[i] += 1.0
    means = sums / counts
    # the cluster scores: the sum of the deviations inside each cluster
    scores = sums - counts * values.mean()
    # the sandwich uses the sum of squares of the scores; the finite-sample
    # correction already carries the (G-1) factor
    variance = float((scores**2).sum())
    correction = (g / (g - 1)) * ((n - 1) / n)
    return math.sqrt(max(0.0, variance * correction) / (n * n))


def band_contrasts(
    r: np.ndarray,
    bands: np.ndarray,
    *,
    cluster: np.ndarray,
    break_even_cost_r: float = 0.0,
) -> dict:
    """The pairwise band contrasts with **cluster-robust (CR1)** errors.

    L3 §C.2 specifies the regression
    ``r_i = alpha + beta_1 1[G=1] + beta_2 1[G=2] + e_i`` with
    cluster-robust (session-clustered) standard errors, the pairwise
    contrasts ``beta_1, beta_2`` with their CIs, and the break-even
    round-trip cost in R per band.

    The reference band is the **lowest** band present, so a contrast reads
    "band b minus band 0".  The standard error of a contrast is the CR1 error
    of the per-cluster differences, which is the same estimator the audit
    used.
    """
    values = np.asarray(r, dtype=np.float64)
    band_index = np.asarray(bands, dtype=np.int64)
    cluster_ids = np.asarray(cluster)
    finite = np.isfinite(values)
    values = values[finite]
    band_index = band_index[finite]
    cluster_ids = cluster_ids[finite]
    if values.size == 0:
        return {}

    present = sorted({int(b) for b in band_index})
    if len(present) < 2:
        return {}
    reference = present[0]

    def _mean(band: int) -> float:
        mask = band_index == band
        return float(values[mask].mean()) if mask.any() else float("nan")

    out: dict[str, dict] = {}
    for band in present[1:]:
        # the per-cluster differences, and the CR1 error of their mean
        diffs: list[float] = []
        ids: list[np.ndarray] = []
        for c in np.unique(cluster_ids):
            rows = cluster_ids == c
            in_band = rows & (band_index == band)
            in_ref = rows & (band_index == reference)
            if not in_band.any() or not in_ref.any():
                continue
            diffs.append(float(values[in_band].mean() - values[in_ref].mean()))
            ids.append(c)
        stacked = np.asarray(diffs, dtype=np.float64)
        paired = int(stacked.size)
        if stacked.size >= 2:
            se = _cluster_robust_se(stacked, np.concatenate(ids))
        else:
            # Too few clusters hold both bands to pair them.  The two bands
            # are then contrasted with the (conservative) sum of their own
            # CR1 errors; the number of paired clusters is reported so the
            # reader can see which estimator was used.
            se_band = _cluster_robust_se(values[band_index == band], cluster_ids[band_index == band])
            se_ref = _cluster_robust_se(
                values[band_index == reference], cluster_ids[band_index == reference]
            )
            if math.isfinite(se_band) and math.isfinite(se_ref):
                se = math.sqrt(se_band**2 + se_ref**2)
            else:
                se = float("nan")
        estimate = _mean(band) - _mean(reference)
        half_width = 1.959963984540054 * se if math.isfinite(se) else float("nan")
        out[f"band_{band}_minus_band_{reference}"] = {
            "band": int(band),
            "reference_band": int(reference),
            "contrast_r": estimate,
            "cr1_se": se,
            "n_paired_clusters": paired,
            "ci95_lo": estimate - half_width if math.isfinite(half_width) else float("nan"),
            "ci95_hi": estimate + half_width if math.isfinite(half_width) else float("nan"),
            "break_even_cost_r": float(break_even_cost_r),
        }
    return out


def _spread_from_labels(
    r: np.ndarray,
    row_cluster_index: np.ndarray,
    row_label: np.ndarray,
    n_clusters: int,
    n_bands: int,
) -> float:
    """``max_b E[R|b] - min_b E[R|b]`` under a per-row label assignment.

    The statistic is two-sided on the family: it is the larger of the two
    absolute band contrasts, so a permutation that only shuffles which band
    is "high" still has to beat it.
    """
    sums = np.zeros(n_bands, dtype=np.float64)
    counts = np.zeros(n_bands, dtype=np.float64)
    np.add.at(sums, row_label, r)
    np.add.at(counts, row_label, 1.0)
    present = counts > 0
    if int(present.sum()) < 2:
        return 0.0
    means = sums[present] / counts[present]
    return float(means.max() - means.min())


def _modal_band_per_cluster(
    bands: np.ndarray,
    cluster_index: np.ndarray,
    n_clusters: int,
    n_bands: int,
) -> np.ndarray:
    """The modal band of each cluster.

    A cluster is the publication period of the regime variable, so every
    candidate in it normally carries the same band.  The modal band is used
    so that a cluster straddling a band boundary is still assigned to one
    band rather than being dropped.
    """
    counts = np.zeros((n_clusters, n_bands), dtype=np.float64)
    np.add.at(counts, (cluster_index, bands), 1.0)
    return np.argmax(counts, axis=1).astype(np.int64)


def moving_block_permutation(
    r_multiple,
    bands,
    cluster: np.ndarray,
    *,
    block_clusters: int = DEFAULT_BLOCK_CLUSTERS,
    replications: int = DEFAULT_REPLICATIONS,
    seed: int = DEFAULT_SEED,
) -> PermutationResult:
    """The moving-block permutation test on the cluster labels.

    The blocks are **contiguous in time** and are re-ordered as units, which
    preserves the regime's serial structure: a volatility cluster stays
    intact, it is only moved to a different point in the sample.
    """
    r = _as_float_array(r_multiple)
    g = np.asarray(bands, dtype=np.int64)
    c = np.asarray(cluster, dtype=np.int64)
    keep = np.isfinite(r)
    r = r[keep]
    g = g[keep]
    c = c[keep]
    if r.size == 0:
        return PermutationResult(0.0, 1.0, 0, 0, block_clusters, seed)

    unique, cluster_index = np.unique(c, return_inverse=True)
    n_clusters = int(unique.shape[0])
    if n_clusters < 2:
        return PermutationResult(0.0, 1.0, 0, n_clusters, block_clusters, seed)

    n_bands = int(g.max()) + 1 if g.size else 1
    cluster_labels = _modal_band_per_cluster(g, cluster_index, n_clusters, n_bands)
    observed = _spread_from_labels(r, cluster_index, g, n_clusters, n_bands)

    # --- the blocks, contiguous in time -----------------------------------
    order = np.argsort(unique)
    ordered_labels = cluster_labels[order]
    n_blocks = max(1, int(math.ceil(n_clusters / block_clusters)))
    blocks = [
        ordered_labels[i * block_clusters : (i + 1) * block_clusters] for i in range(n_blocks)
    ]

    rng = np.random.default_rng(seed)
    exceed = 0
    for _ in range(replications):
        shuffled = list(blocks)
        rng.shuffle(shuffled)
        permuted_labels = np.concatenate(shuffled)
        # Spread the permuted cluster labels back onto the rows: the i-th
        # cluster (in time order) takes the i-th permuted label.
        row_labels = permuted_labels[order][cluster_index]
        statistic = _spread_from_labels(r, cluster_index, row_labels, n_clusters, n_bands)
        if statistic >= observed:
            exceed += 1

    p_value = (exceed + 1) / (replications + 1)
    return PermutationResult(
        statistic=observed,
        p_value=float(p_value),
        n_replications=int(replications),
        n_clusters=n_clusters,
        block_clusters=int(block_clusters),
        seed=int(seed),
    )


def holm_bonferroni(p_values: Sequence[float], alpha: float = 0.05) -> dict:
    """Holm-Bonferroni correction across a pre-registered family.

    The family is *every regime variable tested on the same sample* (L3
    §C.2), so the correction has to be applied jointly -- not per variable.
    """
    values = [float(p) for p in p_values]
    m = len(values)
    order = sorted(range(m), key=lambda i: values[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        candidate = (m - rank) * values[i]
        running = max(running, candidate)
        adjusted[i] = min(1.0, running)
    return {
        "p_values": values,
        "p_adjusted": adjusted,
        "alpha": float(alpha),
        "rejected": [bool(a < alpha) for a in adjusted],
        "family_size": m,
    }


def _hit_scale(candidates, label_column: str) -> np.ndarray | None:
    """The comparable outcome: ``+1`` for a target, ``-1`` for a stop.

    ``None`` when the log carries no label column, in which case the caller
    falls back to the raw multiple.
    """
    if label_column not in candidates.columns:
        return None
    label = np.asarray(candidates[label_column], dtype=np.float64)
    out = np.full(label.shape, np.nan, dtype=np.float64)
    out[label == 1] = 1.0
    out[label == 0] = -1.0
    return out


def regime_correlation_test(
    candidates,
    *,
    regime_column: str = "vxn_regime",
    r_column: str = "r_multiple",
    ts_column: str = "ts_event",
    label_column: str = "label",
    break_even_cost_r: float = 0.0,
    cluster_minutes: int = 1440,
    block_clusters: int = DEFAULT_BLOCK_CLUSTERS,
    replications: int = DEFAULT_REPLICATIONS,
    seed: int = DEFAULT_SEED,
) -> dict:
    """Run the regime correlation test on a candidate log.

    Parameters
    ----------
    candidates:
        The D2 candidate log as a DataFrame.  Every row is one candidate
        setup, winners and losers alike.
    regime_column:
        The column carrying the regime band (``0``/``1``/``2``).
    r_column:
        The realised multiple.
    ts_column:
        The event timestamp, used to build the clusters.
    label_column:
        The D2 label.  When present, the permutation test runs on the
        **hit scale** (``2*label - 1``), which is comparable across bands;
        the raw multiple is still reported.

    Returns
    -------
    dict
        ``bands`` (per-band expectancy with a cluster-robust CI and the
        break-even cost), ``spread``, ``p_value`` (the permutation
        p-value), ``permutation`` and the family correction.
    """
    if regime_column not in candidates.columns:
        raise KeyError(f"the candidate log has no {regime_column!r} column")
    if r_column not in candidates.columns:
        raise KeyError(f"the candidate log has no {r_column!r} column")

    r = _as_float_array(candidates[r_column])
    bands = np.asarray(candidates[regime_column], dtype=np.int64)
    cluster = cluster_ids(candidates[ts_column], cluster_minutes=cluster_minutes)
    hit = _hit_scale(candidates, label_column)

    keep = np.isfinite(r) & (bands >= 0)
    r = r[keep]
    bands = bands[keep]
    cluster = cluster[keep]
    if hit is not None:
        hit = hit[keep]

    band_stats = band_expectancies(
        r, bands, cluster=cluster, break_even_cost_r=break_even_cost_r
    )

    # The comparable scale for the permutation statistic.
    outcome = hit if hit is not None else r
    outcome = np.where(np.isfinite(outcome), outcome, np.nan)
    finite = np.isfinite(outcome)
    permutation = moving_block_permutation(
        outcome[finite],
        bands[finite],
        cluster[finite],
        block_clusters=block_clusters,
        replications=replications,
        seed=seed,
    )
    hit_stats = None
    if hit is not None:
        hit_bands = band_expectancies(
            hit, bands, cluster=cluster, break_even_cost_r=break_even_cost_r
        )
        hit_stats = {band: stats.as_dict() for band, stats in hit_bands.items()}

    means = [stats.expectancy_r for stats in band_stats.values()]
    spread = (max(means) - min(means)) if len(means) >= 2 else 0.0

    correction = holm_bonferroni([permutation.p_value])
    return {
        "bands": {band: stats.as_dict() for band, stats in band_stats.items()},
        "contrasts": band_contrasts(
            r, bands, cluster=cluster, break_even_cost_r=break_even_cost_r
        ),
        "hit_bands": hit_stats,
        "outcome_scale": "hit" if hit is not None else "r_multiple",
        "spread": float(spread),
        "p_value": permutation.p_value,
        "permutation": permutation.as_dict(),
        "family": correction,
        "n_candidates": int(r.shape[0]),
        "n_clusters": int(np.unique(cluster).shape[0]),
    }


# ---------------------------------------------------------------------------
# The pre-registered regime family (L3 section C.2)
# ---------------------------------------------------------------------------
#
# L3 section C.2 pre-registers a **family of five** regime variables, each
# tested on the same sample, with the multiple-testing correction applied
# **jointly** across the family.  The audit records that this had never been
# run; L3 section C.7 nominates **M-E1** -- the equity sample (QQQ 15-minute)
# joined to the governed VXN daily series -- as the one experiment that could
# settle the regime claim on data that already exists.
#
# The fifth member is the **self-referential control**: the traded
# instrument's own realised volatility.  A regime effect that a
# self-referential volatility measure cannot reproduce is not evidence for a
# *market* regime.  It is not optional, and it is not the last one to be
# tried -- it is in the family from the start.
#
# Every variable is lagged the same way: the value used for a candidate is
# the last observation **strictly before** the candidate's day, so no
# candidate can see a value that was published later.

#: The number of trailing observations a scale-free tertile uses.
TRAILING_TERTILE_OBSERVATIONS: int = 252


@dataclass(frozen=True, slots=True)
class FamilyVariable:
    """One member of the pre-registered family."""

    #: The variable's name, as it appears in the report.
    name: str
    #: What the variable answers.
    rationale: str
    #: The kind of band it produces.
    #:
    #: ``"absolute"``
    #:     the doc's fixed bins (VXN: 0 / 18 / 28 / 200);
    #: ``"tertile"``
    #:     the scale-free form -- the value's rank within its own trailing
    #:     distribution;
    #: ``"sign"``
    #:     a two-way split at zero.
    kind: str = "tertile"
    #: Whether the variable only applies to a crypto sample.
    crypto_only: bool = False


#: The pre-registered family.  Its order is the report's order and it is
#: **not** allowed to shrink.
REGIME_FAMILY: tuple[FamilyVariable, ...] = (
    FamilyVariable(
        name="vxn_bands",
        rationale="the doc's primary claim (absolute bands)",
        kind="absolute",
    ),
    FamilyVariable(
        name="vxn_tertiles",
        rationale="the scale-free form of the VXN claim",
    ),
    FamilyVariable(
        name="dvol_tertiles",
        rationale="the doc's crypto regime index",
        crypto_only=True,
    ),
    FamilyVariable(
        name="realised_volatility",
        rationale="the self-referential control -- NOT optional",
    ),
    FamilyVariable(
        name="funding_sign",
        rationale="crypto positioning / crowding",
        kind="sign",
        crypto_only=True,
    ),
)


def brier_score(y_true: Sequence[int], y_prob: Sequence[float]) -> float:
    """The mean squared error of a probability forecast.

    Zero for a perfect forecast, 0.25 for a forecast that always says 0.5.
    """
    truth = np.asarray(y_true, dtype=np.float64)
    probability = np.asarray(y_prob, dtype=np.float64)
    if truth.shape != probability.shape:
        raise ValueError("y_true and y_prob must have the same length")
    if truth.size == 0:
        return float("nan")
    return float(np.mean((probability - truth) ** 2))


def decision_threshold(*, cost_r: float) -> float:
    """The gate: accept iff the **net** expectancy is positive.

    With a 1:2 target and a 1R stop, ``E[R] = 3P - 1``, so
    ``E[R]_net > 0`` iff ``P > (1 + cost_R) / 3``.

    The doc's literal ``P >= 0.58`` would demand a gross expectancy of
    ``+0.74 R``, i.e. a 58 % win rate, which the measured 33 % cannot reach
    -- L4 section C.5 calls it *"the single most expensive mistake available
    in this system"*.  It may still be reported as a secondary, stricter
    filter, but it must not be the production gate.
    """
    return (1.0 + float(cost_r)) / 3.0


def _daily_tertiles(
    days: np.ndarray,
    closes: np.ndarray,
    candidate_days: np.ndarray,
    *,
    trailing: int = TRAILING_TERTILE_OBSERVATIONS,
) -> np.ndarray:
    """The scale-free band of a daily series at each candidate's day.

    The band is the value's rank within **its own trailing distribution**:
    the value is compared to the previous ``trailing`` observations of the
    same series, so the band means "unusually high *for this index*"
    whatever the index's scale.
    """
    days = np.asarray(days, dtype=np.int64)
    closes = np.asarray(closes, dtype=np.float64)
    candidate_days = np.asarray(candidate_days, dtype=np.int64)
    if days.shape != closes.shape:
        raise ValueError("days and closes must have the same length")
    if days.size == 0:
        return np.full(candidate_days.shape, -1, dtype=np.int64)

    order = np.argsort(days, kind="stable")
    days = days[order]
    closes = closes[order]

    # The last observation **strictly before** the candidate's day.
    position = np.searchsorted(days, candidate_days, side="left") - 1
    known = np.full(candidate_days.shape, np.nan, dtype=np.float64)
    ok = position >= 0
    known[ok] = closes[position[ok]]

    bands = np.full(candidate_days.shape, -1, dtype=np.int64)
    finite = np.isfinite(known)
    for index in np.nonzero(finite)[0]:
        pos = int(position[index])
        start = max(0, pos + 1 - int(trailing))
        window = closes[start : pos + 1]
        window = window[np.isfinite(window)]
        if window.size < 20:
            continue
        edges = np.quantile(window, [1.0 / 3.0, 2.0 / 3.0])
        value = float(known[index])
        bands[index] = int(np.searchsorted(edges, value, side="right"))
    return bands


def _absolute_bands(
    days: np.ndarray,
    closes: np.ndarray,
    candidate_days: np.ndarray,
    *,
    bins: tuple[float, ...] = (0.0, 18.0, 28.0, 200.0),
) -> np.ndarray:
    """The doc's absolute bands, lagged the same way as the tertiles."""
    from dodgys_dd_quant.strategy.regime import regime_label

    days = np.asarray(days, dtype=np.int64)
    closes = np.asarray(closes, dtype=np.float64)
    candidate_days = np.asarray(candidate_days, dtype=np.int64)
    if days.size == 0:
        return np.full(candidate_days.shape, -1, dtype=np.int64)

    order = np.argsort(days, kind="stable")
    days = days[order]
    closes = closes[order]

    position = np.searchsorted(days, candidate_days, side="left") - 1
    bands = np.full(candidate_days.shape, -1, dtype=np.int64)
    ok = position >= 0
    for index in np.nonzero(ok)[0]:
        value = float(closes[int(position[index])])
        bands[index] = int(regime_label(value, bins))
    return bands


def _realised_volatility_bands(
    bar_days: np.ndarray,
    closes: np.ndarray,
    candidate_days: np.ndarray,
) -> np.ndarray:
    """The **self-referential control**: the traded instrument's own
    realised volatility, banded by its own trailing distribution.

    A regime effect that this measure cannot reproduce is not evidence for a
    *market* regime.
    """
    bar_days = np.asarray(bar_days, dtype=np.int64)
    closes = np.asarray(closes, dtype=np.float64)
    candidate_days = np.asarray(candidate_days, dtype=np.int64)
    if bar_days.size < 2:
        return np.full(candidate_days.shape, -1, dtype=np.int64)

    order = np.argsort(bar_days, kind="stable")
    bar_days = bar_days[order]
    closes = closes[order]
    # The last close of every day.
    unique_days, inverse = np.unique(bar_days, return_inverse=True)
    daily_close = np.zeros(unique_days.shape[0], dtype=np.float64)
    np.maximum.at(daily_close, inverse, closes)

    log_return = np.zeros(daily_close.shape[0], dtype=np.float64)
    log_return[1:] = np.diff(np.log(daily_close))
    # A 30-day realised volatility, in log-return units.
    window = 30
    realised = np.full(daily_close.shape[0], np.nan, dtype=np.float64)
    if daily_close.shape[0] > window:
        cumulative = np.cumsum(log_return ** 2)
        realised[window:] = (
            cumulative[window:] - cumulative[:-window]
        ) / float(window)

    finite = np.isfinite(realised)
    if int(finite.sum()) < 20:
        return np.full(candidate_days.shape, -1, dtype=np.int64)

    # The last **complete** day before the candidate's day.
    position = np.searchsorted(unique_days, candidate_days, side="left") - 1
    known = np.full(candidate_days.shape, np.nan, dtype=np.float64)
    ok = position >= 0
    known[ok] = realised[position[ok]]

    bands = np.full(candidate_days.shape, -1, dtype=np.int64)
    for index in np.nonzero(np.isfinite(known))[0]:
        pos = int(position[index])
        start = max(0, pos + 1 - TRAILING_TERTILE_OBSERVATIONS)
        window_values = realised[start : pos + 1]
        window_values = window_values[np.isfinite(window_values)]
        if window_values.size < 20:
            continue
        edges = np.quantile(window_values, [1.0 / 3.0, 2.0 / 3.0])
        bands[index] = int(np.searchsorted(edges, float(known[index]), side="right"))
    return bands


def _funding_sign_bands(
    days: np.ndarray,
    rates: np.ndarray,
    candidate_days: np.ndarray,
) -> np.ndarray:
    """The funding-rate sign: crypto positioning and crowding."""
    days = np.asarray(days, dtype=np.int64)
    rates = np.asarray(rates, dtype=np.float64)
    candidate_days = np.asarray(candidate_days, dtype=np.int64)
    if days.size == 0:
        return np.full(candidate_days.shape, -1, dtype=np.int64)

    order = np.argsort(days, kind="stable")
    days = days[order]
    rates = rates[order]

    position = np.searchsorted(days, candidate_days, side="left") - 1
    bands = np.full(candidate_days.shape, -1, dtype=np.int64)
    ok = position >= 0
    for index in np.nonzero(ok)[0]:
        rate = float(rates[int(position[index])])
        if not math.isfinite(rate):
            continue
        bands[index] = 1 if rate > 0.0 else 0
    return bands


def _candidates_from_sample(sample, *, symbol: str = "", timeframe: str = ""):
    """Run the rule engine over a market sample and resolve the outcomes.

    The sample's ``ts_event`` is the bar's **close** time, so the engine's
    bar index (which is the bar's *open* time) is recovered by subtracting
    one bar interval.
    """
    import pandas as pd

    from dodgys_dd_quant.strategy.state_machine import RuleConfig, run_state_machine
    from dodgys_dd_quant.strategy.structure import Bars

    ts = np.asarray(sample["ts_event"], dtype=np.int64)
    if ts.size < 2:
        return pd.DataFrame(columns=["ts_event", "label", "r_multiple"])
    diffs = np.diff(ts)
    unique, counts = np.unique(diffs, return_counts=True)
    interval = int(unique[int(np.argmax(counts))])

    bars = Bars(
        ts=ts - interval,
        open=np.asarray(sample["open"], dtype=np.float64),
        high=np.asarray(sample["high"], dtype=np.float64),
        low=np.asarray(sample["low"], dtype=np.float64),
        close=np.asarray(sample["close"], dtype=np.float64),
        volume=np.asarray(sample["volume"], dtype=np.float64)
        if "volume" in sample.columns
        else np.zeros(ts.shape[0], dtype=np.float64),
        symbol=symbol,
        timeframe=timeframe,
    )
    config = RuleConfig(symbol=symbol or "SAMPLE", timeframe=timeframe or "1m")
    log = run_state_machine(bars, config)
    table = log.to_table()
    return pd.DataFrame({name: table[name] for name in table})


def run_regime_family(
    sample,
    *,
    days: np.ndarray,
    closes: np.ndarray,
    symbol: str = "",
    timeframe: str = "",
    dvol_days: np.ndarray | None = None,
    dvol_closes: np.ndarray | None = None,
    funding_days: np.ndarray | None = None,
    funding_rates: np.ndarray | None = None,
    replications: int = DEFAULT_REPLICATIONS,
    seed: int = DEFAULT_SEED,
    cost_r: float = 0.0,
) -> dict:
    """Run the pre-registered family on a market sample, and correct jointly.

    This is the **whole experiment**, not just the test: the rule engine
    runs over the sample, the outcomes are resolved by the engine, and
    then every member of the family is tested on the resulting candidate
    log.  L3 section C.7 nominates exactly this run -- the equity sample
    (QQQ 15-minute) joined to the governed VXN daily series -- as the one
    experiment that could settle the regime claim on data that already
    exists.

    Parameters
    ----------
    sample:
        The market series as a DataFrame with ``ts_event`` (nanoseconds,
        the bar's **close** time), ``open``, ``high``, ``low``, ``close``
        and ``volume``.
    days, closes:
        The regime index (VXN): the day number and the close of each
        observation.  Every member is lagged the same way -- the value
        used for a candidate is the last observation **strictly before**
        the candidate's day.
    dvol_days, dvol_closes, funding_days, funding_rates:
        The crypto-only members.  When they are absent the member is
        reported as ``not_applicable`` rather than silently dropped.

    Returns
    -------
    dict
        ``family`` -- one row per member; ``correction`` -- the joint
        Holm-Bonferroni correction; ``decision_threshold`` -- the gate.
    """
    candidates = _candidates_from_sample(sample, symbol=symbol, timeframe=timeframe)
    ts = np.asarray(candidates["ts_event"], dtype=np.int64)
    candidate_days = ts // 86_400_000_000_000
    cluster = cluster_ids(ts)

    # The comparable outcome scale: +1 for a target, -1 for a stop.
    label = np.asarray(candidates["label"], dtype=np.float64)
    outcome = np.full(label.shape, np.nan, dtype=np.float64)
    outcome[label == 1] = 1.0
    outcome[label == 0] = -1.0

    bar_days = candidate_days
    bar_closes = None
    if "close" in sample.columns:
        close = np.asarray(sample["close"], dtype=np.float64)
        sample_ts = np.asarray(sample["ts_event"], dtype=np.int64)
        order = np.argsort(sample_ts, kind="stable")
        bar_days = sample_ts[order] // 86_400_000_000_000
        bar_closes = close[order]

    rows: list[dict] = []
    p_values: list[float] = []
    for variable in REGIME_FAMILY:
        if variable.name == "vxn_bands":
            bands = _absolute_bands(days, closes, candidate_days)
        elif variable.name == "vxn_tertiles":
            bands = _daily_tertiles(days, closes, candidate_days)
        elif variable.name == "dvol_tertiles":
            if dvol_days is None or dvol_closes is None:
                rows.append({
                    "variable": variable.name,
                    "status": "not_applicable",
                    "rationale": variable.rationale,
                })
                continue
            bands = _daily_tertiles(dvol_days, dvol_closes, candidate_days)
        elif variable.name == "realised_volatility":
            if bar_closes is None:
                rows.append({
                    "variable": variable.name,
                    "status": "not_applicable",
                    "rationale": variable.rationale,
                })
                continue
            bands = _realised_volatility_bands(bar_days, bar_closes, candidate_days)
        elif variable.name == "funding_sign":
            if funding_days is None or funding_rates is None:
                rows.append({
                    "variable": variable.name,
                    "status": "not_applicable",
                    "rationale": variable.rationale,
                })
                continue
            bands = _funding_sign_bands(funding_days, funding_rates, candidate_days)
        else:  # pragma: no cover - the family is closed
            raise AssertionError(f"unknown family variable {variable.name!r}")

        keep = np.isfinite(outcome) & (bands >= 0)
        n_kept = int(keep.sum())
        present = np.unique(bands[keep]) if n_kept else np.array([], dtype=np.int64)
        if n_kept < 100 or present.size < 2:
            rows.append({
                "variable": variable.name,
                "status": "insufficient_data",
                "rationale": variable.rationale,
                "n_candidates": n_kept,
            })
            continue

        permutation = moving_block_permutation(
            outcome[keep],
            bands[keep],
            cluster[keep],
            replications=replications,
            seed=seed,
        )
        p_values.append(permutation.p_value)
        rows.append({
            "variable": variable.name,
            "status": "tested",
            "rationale": variable.rationale,
            "spread": float(permutation.statistic),
            "p_value": float(permutation.p_value),
            "n_candidates": n_kept,
            "n_clusters": int(permutation.n_clusters),
            "bands": present.tolist(),
        })

    correction = holm_bonferroni(p_values) if p_values else {
        "p_values": [],
        "p_adjusted": [],
        "alpha": 0.05,
        "rejected": [],
        "family_size": 0,
    }
    return {
        "family": rows,
        "correction": correction,
        "decision_threshold": decision_threshold(cost_r=cost_r),
        "cost_r": float(cost_r),
        "n_candidates": int(ts.shape[0]),
    }
