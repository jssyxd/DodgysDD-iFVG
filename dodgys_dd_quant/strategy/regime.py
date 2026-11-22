"""The regime layer: a strictly-lagged volatility index.

The D2 candidate log carries two regime columns:

``vxn_known``
    the volatility index value that was **knowable at decision time**.
``vxn_regime``
    the regime label derived from it (``0`` low-vol, ``1`` normal, ``2``
    high-vol).

Why "strictly lagged"
---------------------
A daily close of a volatility index is published **after** the cash close.  For
an intraday trade on day ``D`` the only safe value is **day ``D-1``'s close**.
This module implements exactly that and the test suite proves it: *no bar on
day D may see day D's index close*.

Plugability
-----------
The index is an interface, not a hard-coded series.  ``VXN`` (CBOE) is what the
lake actually contains and is therefore the default for NQ/MNQ/QQQ.  The doc's
migration table assigns **VIX** to MES and **GVZ** to GC — **neither is
ingested** (D5) — and those markets therefore still need a data source before
the regime layer can be used on them.  Crypto is assigned **DVOL**, which does
exist in the lake (``macro/dvol/BTCDVOL_1h_consolidated.parquet``); its bands
are not specified by the doc and are therefore **calibration inputs, not
facts**.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from dodgys_dd_quant.strategy.constants import (
    REGIME_HIGH,
    REGIME_LOW,
    REGIME_NORMAL,
    REGIME_PARAMETERS,
    VXN_REGIME_BINS,
    RegimeParameters,
)

__all__ = [
    "RegimeIndex",
    "VxnRegimeIndex",
    "DvolRegimeIndex",
    "ConstantRegimeIndex",
    "regime_label",
    "regime_parameters",
    "load_vxn_parquet",
    "DEFAULT_VXN_PATH",
]

#: Canonical location of the governed VXN partition on the NFS lake (D5, D10).
DEFAULT_VXN_PATH = Path(
    "~/iflow_lake/iflow/database/03_governed_lake/v2_parquet_lake/macro/vxn/VXN_1d_consolidated.parquet"
)

#: Canonical location of the governed crypto DVOL partition.
DEFAULT_DVOL_PATH = Path(
    "~/iflow_lake/iflow/database/03_governed_lake/v2_parquet_lake/macro/dvol/BTCDVOL_1h_consolidated.parquet"
)

_NS_PER_DAY = 86_400_000_000_000


def regime_label(value: float, bins: tuple[float, ...] = VXN_REGIME_BINS) -> int:
    """Map an index value to a regime label.

    ``VXN_REGIME_BINS = (0, 18, 28, 200)`` (DOC L265-266) with three labels:
    ``0`` low-vol range, ``1`` normal trend, ``2`` high-vol panic.  The fourth
    edge (200) does not create a fourth label; it marks the *extreme* end of
    the high-vol band (reported by :func:`is_extreme`).
    """
    if value is None or not math.isfinite(value):
        return -1
    if value < bins[1]:
        return REGIME_LOW
    if value < bins[2]:
        return REGIME_NORMAL
    return REGIME_HIGH


def is_extreme(value: float, bins: tuple[float, ...] = VXN_REGIME_BINS) -> bool:
    """Whether the value is in the extreme tail of the high-vol band."""
    return math.isfinite(value) and value >= bins[3]


def regime_parameters(regime: int) -> RegimeParameters:
    """The regime-driven trade parameters (DOC L107-109).

    The doc's "tighten to A+ only" for low volatility is **not implementable**
    (D8: no artefact defines A+); it is replaced by "tighten the ATR floor and
    the risk/reward", which is what this table does.
    """
    return REGIME_PARAMETERS.get(regime, REGIME_PARAMETERS[REGIME_NORMAL])


# ---------------------------------------------------------------------------
# The index interface
# ---------------------------------------------------------------------------


class RegimeIndex:
    """Interface of a regime index.

    ``value_at(ts)`` returns ``(known_value, regime_label)`` arrays aligned with
    ``ts``.  The implementation **must** be strictly lagged: the value attached
    to a bar must have been published before that bar's close.
    """

    name: str = "none"

    def value_at(self, ts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:  # pragma: no cover
        raise NotImplementedError


@dataclass
class ConstantRegimeIndex(RegimeIndex):
    """A fixed regime — used when no index is available for a market."""

    value: float = float("nan")
    regime: int = -1
    name: str = "constant"

    def value_at(self, ts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        n = ts.shape[0]
        return (
            np.full(n, self.value, dtype=np.float64),
            np.full(n, self.regime, dtype=np.int8),
        )


@dataclass
class VxnRegimeIndex(RegimeIndex):
    """The CBOE VXN daily close, strictly lagged by one day.

    Parameters
    ----------
    days:
        int64 array of UTC day numbers of the index observations.
    closes:
        the index close of each observation.
    bins:
        the regime bin edges (``VXN_REGIME_BINS``).
    """

    days: np.ndarray
    closes: np.ndarray
    bins: tuple[float, ...] = VXN_REGIME_BINS
    name: str = "VXN"

    @classmethod
    def from_parquet(
        cls,
        path: str | Path = DEFAULT_VXN_PATH,
        bins: tuple[float, ...] = VXN_REGIME_BINS,
    ) -> "VxnRegimeIndex":
        """Load the governed VXN partition."""
        days, closes = load_vxn_parquet(path)
        return cls(days=days, closes=closes, bins=bins)

    def value_at(self, ts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        bar_days = ts.astype("int64") // _NS_PER_DAY
        # the last observation **strictly before** the bar's day: a bar on day
        # D can never see day D's close
        pos = np.searchsorted(self.days, bar_days, side="left") - 1
        known = np.full(bar_days.shape[0], np.nan, dtype=np.float64)
        ok = pos >= 0
        known[ok] = self.closes[pos[ok]]
        labels = np.array(
            [regime_label(v, self.bins) for v in known], dtype=np.int8
        )
        return known, labels


@dataclass
class DvolRegimeIndex(RegimeIndex):
    """Crypto DVOL, resampled to a daily close and lagged the same way.

    The doc names DVOL as the crypto regime index but specifies **no bands**,
    so the band edges are a *calibration input*: they default to the VXN edges
    and must be re-calibrated for the DVOL scale before any claim is made about
    the crypto regimes.
    """

    days: np.ndarray
    closes: np.ndarray
    bins: tuple[float, ...] = VXN_REGIME_BINS
    name: str = "DVOL"

    @classmethod
    def from_parquet(
        cls,
        path: str | Path = DEFAULT_DVOL_PATH,
        bins: tuple[float, ...] = VXN_REGIME_BINS,
    ) -> "DvolRegimeIndex":
        import pyarrow.parquet as pq

        table = pq.read_table(Path(path))
        ts = table.column("timestamp").to_numpy().astype("int64")
        # the lake stores ms; normalise to ns when needed
        if np.nanmax(np.abs(ts)) < 10_000_000_000_000:
            ts = ts * 1_000_000
        close = table.column("close").to_numpy(zero_copy_only=False).astype(np.float64)
        day = ts // _NS_PER_DAY
        order = np.argsort(day, kind="stable")
        day = day[order]
        close = close[order]
        uniq, inverse = np.unique(day, return_inverse=True)
        last = np.zeros(uniq.shape[0], dtype=np.float64)
        np.maximum.at(last, inverse, close)      # the day's last observation
        return cls(days=uniq, closes=last, bins=bins)

    def value_at(self, ts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        bar_days = ts.astype("int64") // _NS_PER_DAY
        pos = np.searchsorted(self.days, bar_days, side="left") - 1
        known = np.full(bar_days.shape[0], np.nan, dtype=np.float64)
        ok = pos >= 0
        known[ok] = self.closes[pos[ok]]
        labels = np.array([regime_label(v, self.bins) for v in known], dtype=np.int8)
        return known, labels


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_vxn_parquet(path: str | Path = DEFAULT_VXN_PATH) -> tuple[np.ndarray, np.ndarray]:
    """Read the governed VXN partition into ``(days, closes)``.

    The lake's invariant is a strictly monotonic int64 **ms** time index; the
    day number is derived from it.
    """
    import pyarrow.parquet as pq

    table = pq.read_table(Path(path))
    ts = table.column("timestamp").to_numpy().astype("int64")
    if np.nanmax(np.abs(ts)) < 10_000_000_000_000:
        ts = ts * 1_000_000
    close = table.column("close").to_numpy(zero_copy_only=False).astype(np.float64)
    days = ts // _NS_PER_DAY
    order = np.argsort(days, kind="stable")
    return days[order], close[order]
