"""CSCV and the Probability of Backtest Overfitting (L4 §F.5, item 5).

The audit's multiple-testing proposal has two halves: the **Deflated Sharpe
Ratio** for the headline statistic (already implemented in
``backtest.walk_forward.deflated_sharpe``) and the **Probability of
Backtest Overfitting** for the *selection procedure*.  The second half needs
non-overlapping out-of-sample segments -- the monthly folds provide them --
and it was never built.

The estimator is the Combinatorially Symmetric Cross-Validation of Bailey &
Lopez de Prado:

1. split the ``S`` out-of-sample segments into every possible pair of halves
   (``C(S, S/2)`` combinations, each counted once);
2. in each split, **select** the configuration with the best in-sample
   performance;
3. rank that configuration by its out-of-sample performance among all of them
   and turn the rank into a logit ``lambda = log(w / (1 - w))``;
4. the PBO is the fraction of splits whose logit is negative -- the selected
   configuration landed *below* the median out of sample.

A PBO near 0.5 means the selection procedure is indistinguishable from luck;
a PBO near 0 means the selection generalises.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Sequence

import numpy as np

__all__ = ["PboResult", "cscv_pbo", "pbo_from_trials"]


@dataclass(frozen=True)
class PboResult:
    """The outcome of one CSCV run."""

    #: The probability of backtest overfitting: the share of splits in which
    #: the selected configuration underperformed out of sample.
    pbo: float
    #: The number of splits examined (``C(S, S/2)``).
    n_splits: int
    #: The number of configurations the selection chose between.
    n_configurations: int
    #: The number of out-of-sample segments.
    n_segments: int
    #: The splits whose logit was negative.
    overfit_splits: int
    #: The median logit over the splits.
    median_logit: float

    def as_dict(self) -> dict:
        return {
            "pbo": self.pbo,
            "n_splits": self.n_splits,
            "n_configurations": self.n_configurations,
            "n_segments": self.n_segments,
            "overfit_splits": self.overfit_splits,
            "median_logit": self.median_logit,
        }


def _logit(better: int, n: int) -> float:
    """``log(w / (1 - w))`` for the relative rank ``w`` of the selection.

    ``better`` is the number of configurations whose out-of-sample
    performance exceeds the selected one's, so the **goodness** rank is
    ``w = 1 - better / n``: ``1.0`` when the selection was also the best out
    of sample, ``0.5`` when it landed in the middle, ``0.0`` when it was the
    worst.  The logit is therefore positive for a selection that generalised
    and negative for one that did not, and the PBO is the share of negative
    logits.

    The rank is clipped away from 0 and 1 so the logit stays finite; the
    clipping is symmetric and cannot move a split from one side of zero to
    the other.
    """
    eps = 0.5 / max(n, 1)
    w = min(1.0 - eps, max(eps, 1.0 - better / n))
    return math.log(w / (1.0 - w))


def cscv_pbo(returns: np.ndarray) -> PboResult:
    """The PBO of the selection procedure behind ``returns``.

    Parameters
    ----------
    returns:
        A ``(n_segments, n_configurations)`` matrix: one row per
        out-of-sample segment (a monthly fold, say), one column per
        configuration the procedure chooses between (the registered trials).
        A segment with no trades must be encoded as ``NaN`` and is dropped.
    """
    matrix = np.asarray(returns, dtype=np.float64)
    if matrix.ndim != 2:
        raise ValueError("returns must be a two-dimensional matrix")
    n_segments, n_configurations = matrix.shape
    if n_segments < 4:
        raise ValueError("CSCV needs at least four out-of-sample segments")
    if n_configurations < 2:
        raise ValueError("CSCV needs at least two configurations to choose between")

    half = n_segments // 2
    logits: list[float] = []
    overfit = 0
    for combo in combinations(range(n_segments), half):
        inside = list(combo)
        outside = [i for i in range(n_segments) if i not in combo]
        in_sample = np.nanmean(matrix[inside], axis=0)
        out_sample = np.nanmean(matrix[outside], axis=0)
        if not np.isfinite(in_sample).any() or not np.isfinite(out_sample).any():
            continue
        # the selection: the best in-sample configuration
        selected = int(np.nanargmax(in_sample))
        # how many configurations beat it out of sample
        better = int(np.sum(out_sample > out_sample[selected]))
        logit = _logit(better, n_configurations)
        logits.append(logit)
        if logit <= 0.0:
            # the selection landed in the bottom half out of sample
            overfit += 1

    if not logits:
        return PboResult(
            pbo=float("nan"),
            n_splits=0,
            n_configurations=n_configurations,
            n_segments=n_segments,
            overfit_splits=0,
            median_logit=float("nan"),
        )
    return PboResult(
        pbo=overfit / len(logits),
        n_splits=len(logits),
        n_configurations=n_configurations,
        n_segments=n_segments,
        overfit_splits=overfit,
        median_logit=float(np.median(logits)),
    )


def pbo_from_trials(trials: Sequence, n_segments: int) -> PboResult:
    """The PBO of a selection over registered trials.

    Each trial's out-of-sample return series is cut into ``n_segments``
    contiguous blocks (the monthly folds); a trial with fewer returns than
    segments is padded with ``NaN`` and the empty segments are dropped by
    :func:`cscv_pbo`.
    """
    if n_segments < 4:
        raise ValueError("CSCV needs at least four out-of-sample segments")
    rows: list[list[float]] = []
    for trial in trials:
        series = np.asarray(getattr(trial, "oos_returns", []), dtype=np.float64)
        if series.size == 0:
            continue
        blocks = np.array_split(series, n_segments)
        row = []
        for block in blocks:
            row.append(float(block.mean()) if block.size else float("nan"))
        rows.append(row)
    if not rows:
        raise ValueError("no trial carries an out-of-sample return series")
    matrix = np.asarray(rows, dtype=np.float64).T  # (segments, configurations)
    return cscv_pbo(matrix)
