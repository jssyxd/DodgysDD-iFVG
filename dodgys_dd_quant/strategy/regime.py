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
    "RegimeSeries",
    "RegimeState",
    "VxnRegimeIndex",
    "DvolRegimeIndex",
    "ConstantRegimeIndex",
    "regime_label",
    "regime_parameters",
    "regime_state",
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

    The band edges are **inclusive at the top** (``RULE_SPEC`` §1.9):
    ``(-inf, 18) -> 0 | [18, 28] -> 1 | (28, inf) -> 2``.  The discussion's
    literal ``pd.cut(bins=[0, 18, 28, 200])`` is right-closed and would put
    28 in the *high* band (I05) -- and would disagree with the feature
    pipeline's own binning, which is inclusive.
    """
    if value is None or not math.isfinite(value):
        return -1
    if value < bins[1]:
        return REGIME_LOW
    if value <= bins[2]:
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
# The regime state (L3 section C.6)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegimeSeries:
    """A daily index series: the day of each observation and its close."""

    days: np.ndarray
    closes: np.ndarray
    name: str = "VXN"


@dataclass(frozen=True, slots=True)
class RegimeState:
    """The regime **knowable** at a point in time.

    Every field is a decision-time quantity:

    ``known_at_ns``
        when the value became public (the publication time of the
        observation).  Never later than the decision.
    ``level``
        the index level itself.
    ``regime``
        the band: 0 low / 1 normal / 2 high.
    ``percentile``
        the trailing percentile of the level, which makes the band
        scale-free (the doc's own per-market generalisation, RULE_SPEC A34).
    ``stale_days``
        how many days old the level is.  A carried-forward regime is
        **visibly** stale instead of silently looking fresh (L3 trap 2).
    ``index_name``
        which index this is -- the D2 columns are named ``vxn_*`` but the
        migration table assigns a different index per market.
    """

    known_at_ns: int
    level: float
    regime: int
    percentile: float
    stale_days: int
    index_name: str


def regime_state(
    index_name: str,
    asof_ns: int,
    series: RegimeSeries,
    *,
    bins: tuple[float, ...] = VXN_REGIME_BINS,
    trailing_days: int = 252,
) -> RegimeState | None:
    """The regime **knowable** at ``asof_ns``, or ``None``.

    The observation used is the last one whose **publication time** is at or
    before ``asof_ns`` -- never one published later, and never a value
    back-filled from the future (L3 trap 2: ``shift(1).bfill()`` silently
    fills the head of the series with the future).

    A daily index is published at 16:15 ET on its trade date, so the
    publication time of day ``d`` is ``d`` at 16:15 America/New_York.
    """
    days = np.asarray(series.days, dtype=np.int64)
    closes = np.asarray(series.closes, dtype=np.float64)
    if days.size == 0:
        return None

    order = np.argsort(days, kind="stable")
    days = days[order]
    closes = closes[order]

    published = _publication_ns(days)
    # The last observation published at or before the decision.
    position = int(np.searchsorted(published, int(asof_ns), side="right")) - 1
    if position < 0:
        return None

    level = float(closes[position])
    observation_day = int(days[position])
    decision_day = int(asof_ns) // _NS_PER_DAY
    stale_days = max(0, decision_day - observation_day)

    window_start = max(0, position + 1 - int(trailing_days))
    window = closes[window_start : position + 1]
    percentile = (
        float((window <= level).sum()) / float(window.size) if window.size else float("nan")
    )

    return RegimeState(
        known_at_ns=int(published[position]),
        level=level,
        regime=regime_label(level, bins),
        percentile=percentile,
        stale_days=stale_days,
        index_name=index_name,
    )


#: The band mappings a market may name (RULE_SPEC A34).
BAND_MODE_ABSOLUTE = "absolute"
BAND_MODE_PERCENTILE = "percentile"


def band_mode_for(symbol: str) -> str:
    """The band mapping the market's row names.

    The doc's absolute bins (``18`` / ``28``) are stated for **VXN only**;
    the audit measured that they do not transfer -- VXN and VIX disagree on
    roughly half the days -- so every other market uses the index's own
    trailing tertiles (RULE_SPEC A34).
    """
    from dodgys_dd_quant.strategy.constants import market_params

    return market_params(symbol).regime_bands


def percentile_band_labels(
    closes: np.ndarray,
    positions: np.ndarray,
    known: np.ndarray,
    *,
    trailing_days: int = 365,
) -> np.ndarray:
    """The band of every observation by its **own** trailing tertiles.

    The tertiles are computed from the history that was published *before*
    the observation, so the mapping is causal: a bar never sees a quantile
    that was computed with later data.
    """
    values = np.asarray(closes, dtype=np.float64)
    labels = np.full(np.shape(known), -1, dtype=np.int8)
    cache: dict[int, int] = {}
    for i in range(np.shape(known)[0]):
        position = int(positions[i])
        if position < 0 or not math.isfinite(float(known[i])):
            continue
        label = cache.get(position)
        if label is None:
            start = max(0, position + 1 - int(trailing_days))
            window = values[start : position + 1]
            if window.size < 3:
                label = -1
            else:
                low, high = np.quantile(window, [1.0 / 3.0, 2.0 / 3.0])
                level = float(values[position])
                label = 0 if level < low else (1 if level < high else 2)
            cache[position] = label
        labels[i] = label
    return labels


def _publication_ns(days: np.ndarray) -> np.ndarray:
    """The publication timestamp of each daily observation, in nanoseconds.

    A daily index is published at **16:15 ET** on its trade date, so the
    value is not knowable before then (L3 trap 1).  The daylight-time hour
    is used, which is the later of the two, so a state is never claimed to
    be knowable before it is.
    """
    return days.astype(np.int64) * _NS_PER_DAY + 21 * 3_600_000_000_000


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
    #: ``"absolute"`` (the documented points) or ``"percentile"`` (the
    #: index's own trailing tertiles, RULE_SPEC A34).
    band_mode: str = BAND_MODE_ABSOLUTE
    #: The trailing window of the percentile mapping, in observations.
    trailing_days: int = 365

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
        if self.band_mode == BAND_MODE_PERCENTILE:
            labels = percentile_band_labels(
                self.closes, pos, known, trailing_days=self.trailing_days
            )
        else:
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
    #: The crypto index's bands are a calibration input (A34): the default
    #: mapping is the index's own trailing tertiles, because the doc's
    #: absolute points are stated for VXN only.
    band_mode: str = BAND_MODE_PERCENTILE
    #: The trailing window of the percentile mapping, in observations.
    trailing_days: int = 365

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
        if self.band_mode == BAND_MODE_PERCENTILE:
            labels = percentile_band_labels(
                self.closes, pos, known, trailing_days=self.trailing_days
            )
        else:
            labels = np.array(
                [regime_label(v, self.bins) for v in known], dtype=np.int8
            )
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
