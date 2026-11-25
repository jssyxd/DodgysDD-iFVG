"""Analyses over the frozen D2 candidate log.

These are **measurements**, not trading logic: they read the candidate log
and report what it says.  Nothing here may open a position or change a
price (INV2/INV3).

The module that lives here today is the regime correlation test (L3 §C.2) --
the deliverable the audit records as *"no correlation check implemented: no"*.
"""

from __future__ import annotations

from dodgys_dd_quant.analysis.regime_correlation import (
    BandExpectancy,
    PermutationResult,
    band_expectancies,
    cluster_ids,
    holm_bonferroni,
    moving_block_permutation,
    regime_correlation_test,
)

__all__ = [
    "BandExpectancy",
    "PermutationResult",
    "band_expectancies",
    "cluster_ids",
    "holm_bonferroni",
    "moving_block_permutation",
    "regime_correlation_test",
]
