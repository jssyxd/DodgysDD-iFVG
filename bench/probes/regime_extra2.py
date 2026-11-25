"""The regime's band mapping -- the per-index question L3 §C.2 measured.

The doc's band edges (``18`` / ``28``) are stated for **VXN only** (RULE_SPEC
A34), and the audit measured that they do **not** transfer: applied to VIX
as well, the two indices disagree on roughly half the days (the crosstab in
L3 §C.2 counts 202 of 391 days in the "VXN normal / VIX low" cell).

So the band mapping has to be **per market**: VXN keeps its documented
points, and every other index (VIX for MES, GVZ for GC, DVOL for the crypto
pair) uses its own trailing tertiles -- the scale-free mapping the doc itself
proposes.

These probes drive the engine's regime indices with a synthetic series, so no
lake mount is needed.
"""

from __future__ import annotations

import math

from bench.probes import register

__all__ = []

#: The index's own trailing window for the percentile mapping.
TRAILING_DAYS = 365


def _synthetic_index(seed: int = 3, days: int = 400):
    """A synthetic daily index: a slow cycle with noise."""
    import numpy as np

    rng = np.random.default_rng(seed)
    day_numbers = np.arange(1000, 1000 + days, dtype=np.int64)
    closes = (
        20.0
        + 8.0 * np.sin(np.arange(days) / 40.0)
        + rng.normal(scale=0.5, size=days)
    )
    # the bars of the following days, so the index is lagged by one day
    ts = (day_numbers + 1) * 86_400_000_000_000
    return day_numbers, closes, ts


@register(
    "regime.bands_are_per_market",
    "regime",
    50,
    "the absolute VXN bands do not transfer: the mapping is per index (A34)",
)
def _bands_are_per_market() -> tuple[bool, str]:
    """The same level must not mean the same band in two indices.

    The audit's measurement is the reference: the absolute bands and the
    percentile mapping agree on roughly half the days, so a port that applies
    VXN's points everywhere is wrong.
    """
    from dodgys_dd_quant.strategy.regime import (
        BAND_MODE_ABSOLUTE,
        BAND_MODE_PERCENTILE,
        VxnRegimeIndex,
    )

    days, closes, ts = _synthetic_index()
    absolute = VxnRegimeIndex(
        days=days, closes=closes, band_mode=BAND_MODE_ABSOLUTE
    )
    percentile = VxnRegimeIndex(
        days=days, closes=closes, band_mode=BAND_MODE_PERCENTILE
    )
    _, absolute_labels = absolute.value_at(ts)
    _, percentile_labels = percentile.value_at(ts)

    known = absolute_labels >= 0
    if not known.any():
        return False, "the synthetic index produced no bands"
    agreement = float((absolute_labels[known] == percentile_labels[known]).mean())
    if agreement > 0.75:
        return False, (
            f"the two mappings agree on {agreement:.0%} of the bars -- the "
            f"absolute bands must not be reused across indices"
        )
    if not ((percentile_labels == 0).any() and (percentile_labels == 2).any()):
        return False, "the percentile mapping never reaches the extreme bands"
    return True, (
        f"the absolute and the percentile mapping agree on only "
        f"{agreement:.0%} of the bars"
    )


@register(
    "regime.percentile_mapping_is_causal",
    "regime",
    45,
    "the percentile mapping uses only the history published before the observation",
)
def _percentile_is_causal() -> tuple[bool, str]:
    """No look-ahead in the band mapping.

    The tertiles are computed from the trailing window of the index's own
    history, so truncating the series cannot change an earlier band.
    """
    import numpy as np

    from dodgys_dd_quant.strategy.regime import (
        BAND_MODE_PERCENTILE,
        VxnRegimeIndex,
    )

    days, closes, ts = _synthetic_index()
    index = VxnRegimeIndex(days=days, closes=closes, band_mode=BAND_MODE_PERCENTILE)
    _, labels = index.value_at(ts)

    # the same index, but with the future removed
    cut = 250
    short = VxnRegimeIndex(
        days=days[:cut], closes=closes[:cut], band_mode=BAND_MODE_PERCENTILE
    )
    _, short_labels = short.value_at(ts[:cut])
    if not np.array_equal(short_labels, labels[:cut]):
        return False, "truncating the future changed the earlier bands"
    return True, f"{cut} bars keep their band when the future is cut"


@register(
    "regime.market_row_names_the_index_and_the_mapping",
    "regime",
    45,
    "each market's row names its regime index and its band mapping",
)
def _market_rows() -> tuple[bool, str]:
    """The migration table is the config: the index and the mapping.

    ``MES`` uses **VIX**, ``GC`` uses **GVZ**, the crypto pair uses **DVOL**
    -- and none of those may borrow VXN's absolute points.
    """
    from dodgys_dd_quant.strategy.constants import market_params
    from dodgys_dd_quant.strategy.regime import (
        BAND_MODE_ABSOLUTE,
        BAND_MODE_PERCENTILE,
        DvolRegimeIndex,
        band_mode_for,
    )

    expected = {
        "NQ": ("VXN", BAND_MODE_ABSOLUTE),
        "MES": ("VIX", BAND_MODE_PERCENTILE),
        "GC": ("GVZ", BAND_MODE_PERCENTILE),
        "BTCUSDT": ("DVOL", BAND_MODE_PERCENTILE),
    }
    for symbol, (index_name, mapping) in expected.items():
        params = market_params(symbol)
        if params.regime_index != index_name:
            return False, (
                f"{symbol} is wired to {params.regime_index}, expected {index_name}"
            )
        if band_mode_for(symbol) != mapping:
            return False, (
                f"{symbol} uses the {band_mode_for(symbol)} bands, expected {mapping}"
            )

    # the crypto index defaults to the scale-free mapping, because the doc's
    # absolute points are stated for VXN only
    days, closes, _ = _synthetic_index()
    dvol = DvolRegimeIndex(days=days, closes=closes)
    if dvol.band_mode != BAND_MODE_PERCENTILE:
        return False, "the DVOL index still defaults to the absolute bands"
    return True, (
        "NQ keeps VXN's absolute bands; MES, GC and the crypto pair use the "
        "percentile mapping"
    )


@register(
    "regime.percentile_bands_reach_the_order",
    "regime",
    45,
    "a percentile-banded index still changes the order's target distance",
)
def _percentile_reaches_the_order() -> tuple[bool, str]:
    """The band must reach the decision, whatever mapping produced it.

    The doc's per-band policy (L107-109) sets the target distance, so a
    percentile-banded index must change the trade's shape exactly like the
    absolute one.
    """
    import numpy as np

    from dodgys_dd_quant.strategy.regime import (
        BAND_MODE_PERCENTILE,
        VxnRegimeIndex,
        regime_parameters,
    )

    days, closes, ts = _synthetic_index()
    index = VxnRegimeIndex(days=days, closes=closes, band_mode=BAND_MODE_PERCENTILE)
    _, labels = index.value_at(ts)
    bands = {int(label) for label in np.unique(labels) if label >= 0}
    if len(bands) < 2:
        return False, f"the synthetic index only reached the bands {sorted(bands)}"

    distances = {
        band: regime_parameters(band).rr for band in sorted(bands)
    }
    if len(set(distances.values())) < 2:
        return False, "the bands do not change the target distance"
    if regime_parameters(2).risk_multiplier >= regime_parameters(1).risk_multiplier:
        return False, "the high-volatility band does not reduce the risk"
    if regime_parameters(2).atr_floor_mult <= regime_parameters(1).atr_floor_mult:
        return False, "the high-volatility band does not raise the ATR floor"
    return True, (
        f"the bands {sorted(bands)} carry the target distances "
        f"{[distances[b] for b in sorted(bands)]}"
    )
