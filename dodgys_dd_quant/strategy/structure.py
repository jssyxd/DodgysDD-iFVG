"""Causal market structure: swings, FVGs, liquidity sweeps and session levels.

Every function here is **causal**: a value computed from bar ``i`` may only use
bars ``<= i``, and a pivot at bar ``p`` is not *usable* until bar ``p + right``
has closed.  The third-party detector this logic was adapted from
(``xauusd-ml-trader``) uses a **centred** window and therefore peeks; that
defect is fixed here (see ``research/analysis/ML_REUSE.md`` §A).

Conventions
-----------
* Bars are **closed** bars.  Index ``i`` means "bar ``i`` has closed".
* ``ts`` holds the bar **open** time in nanoseconds (the governed lake labels
  bars left-open), so the bar's *close* time is ``ts + interval``.
* The reference Pine evaluates its trigger on bar ``X`` using ``close[X-1]``
  (``pine:L437``).  In closed-bar terms the **confirmation candle** is ``X-1``
  and the signal becomes knowable at the close of ``X``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math

import numpy as np

from dodgys_dd_quant.strategy.constants import (
    MAX_SESSIONS,
    SWING_FRACTAL,
    SWING_RIGHT_BARS,
)

__all__ = [
    "Bars",
    "load_bars",
    "atr_wilder",
    "causal_pivots",
    "EqualLevel",
    "EqualLevelStore",
    "FvgSet",
    "detect_fvg",
    "HtfFvgZone",
    "HtfFvgZones",
    "SweepDetector",
    "SweepEvent",
    "PivotLevels",
    "SessionExtremes",
    "EqualLevel",
    "EqualLevelStore",
    "HtfFvgZone",
    "HtfFvgZones",
    "HtfLevel",
    "HtfSeries",
    "aggregate_htf",
]


# ---------------------------------------------------------------------------
# Bar container
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Bars:
    """A closed-bar OHLCV series stored as parallel numpy arrays."""

    ts: np.ndarray          # int64 ns, bar OPEN time, strictly increasing
    open: np.ndarray        # float64
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    symbol: str = ""
    timeframe: str = "1m"
    _cached_interval: int = field(default=0, compare=False, repr=False)

    def __len__(self) -> int:  # pragma: no cover - trivial
        return int(self.ts.shape[0])

    @property
    def interval_ns(self) -> int:
        """Bar duration in nanoseconds (the modal spacing of the time index)."""
        if self._cached_interval:
            return self._cached_interval
        if self.ts.shape[0] < 2:
            object.__setattr__(self, "_cached_interval", 60_000_000_000)
            return self._cached_interval
        diffs = np.diff(self.ts)
        values, counts = np.unique(diffs, return_counts=True)
        value = int(values[int(np.argmax(counts))])
        object.__setattr__(self, "_cached_interval", value)
        return value

    def close_ts(self) -> np.ndarray:
        """Close timestamp of every bar (the lake labels bars left-open)."""
        return self.ts + self.interval_ns

    def slice(self, start: int, stop: int) -> "Bars":
        return Bars(
            ts=self.ts[start:stop],
            open=self.open[start:stop],
            high=self.high[start:stop],
            low=self.low[start:stop],
            close=self.close[start:stop],
            volume=self.volume[start:stop],
            symbol=self.symbol,
            timeframe=self.timeframe,
        )


def load_bars(path: str | Path, symbol: str = "", timeframe: str = "1m") -> Bars:
    """Load a governed-lake parquet into :class:`Bars`.

    The lake stores ``timestamp`` (int64 **ms**, left-open bar open time),
    ``datetime`` and the OHLCV columns.  Timestamps are converted to ns.
    """
    import pyarrow.parquet as pq

    path = Path(path)
    table = pq.read_table(path)
    cols = set(table.column_names)

    # the lake has two names for the same quantity: older lanes call it
    # ``timestamp``, the canonical contract (AGENTS.md) calls it ``ts_event``
    if "timestamp" in cols:
        ts_col = "timestamp"
    elif "ts_event" in cols:
        ts_col = "ts_event"
    else:
        raise ValueError(
            f"{path}: no 'timestamp' or 'ts_event' column (found {sorted(cols)})"
        )

    ts = table.column(ts_col).to_numpy()
    if np.issubdtype(ts.dtype, np.integer):
        # the lake stores ms; anything below 1e12 cannot be ns for modern dates
        ts = ts.astype(np.int64)
        if np.nanmax(np.abs(ts)) < 10_000_000_000_000:
            ts = ts * 1_000_000
    else:
        ts = ts.astype("datetime64[ns]").astype(np.int64)

    def col(name: str) -> np.ndarray:
        if name not in cols:
            raise ValueError(f"{path}: missing column '{name}'")
        return table.column(name).to_numpy(zero_copy_only=False).astype(np.float64)

    volume = col("volume") if "volume" in cols else np.zeros(len(ts), dtype=np.float64)
    return Bars(
        ts=ts,
        open=col("open"),
        high=col("high"),
        low=col("low"),
        close=col("close"),
        volume=volume,
        symbol=symbol or path.stem.split("_")[0],
        timeframe=timeframe,
    )


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------


def atr_wilder(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Wilder's RMA of True Range.

    ``out[i]`` is ``NaN`` until the series is warm (the first ``period`` values
    of TR are consumed to seed the average), so **no signal may be produced
    before the ATR is warm** (RULE_SPEC A03).  The recursion is the Pine-free
    standard definition and matches ``research/experiments/e1_rule_falsification.py``.
    """
    n = high.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    if n <= period:
        return out

    tr = np.empty(n, dtype=np.float64)
    tr[0] = high[0] - low[0]
    np.maximum(high[1:] - low[1:], np.abs(high[1:] - close[:-1]), out=tr[1:])
    np.maximum(tr[1:], np.abs(low[1:] - close[:-1]), out=tr[1:])

    seed = float(tr[1 : period + 1].sum()) / period
    out[period] = seed
    prev = seed
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


# ---------------------------------------------------------------------------
# Causal swing pivots
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PivotLevels:
    """Causal swing pivots.

    ``high_idx`` / ``low_idx`` are the bar indices of the pivot extremes and
    ``high_known`` / ``low_known`` are the bar indices at which they became
    *knowable* (``pivot + right``).  A pivot may only be used from
    ``known + 1`` onwards, because the swing is published on the close of the
    bar that confirms it.
    """

    high_idx: np.ndarray
    high_price: np.ndarray
    high_known: np.ndarray
    low_idx: np.ndarray
    low_price: np.ndarray
    low_known: np.ndarray

    def highs_known_before(self, bar: int, limit: int = MAX_SESSIONS) -> slice:
        """Slice of the pivot highs that were knowable strictly before ``bar``."""
        end = int(np.searchsorted(self.high_known, bar, side="left"))
        start = max(0, end - limit)
        return slice(start, end)

    def lows_known_before(self, bar: int, limit: int = MAX_SESSIONS) -> slice:
        end = int(np.searchsorted(self.low_known, bar, side="left"))
        start = max(0, end - limit)
        return slice(start, end)


def causal_pivots(
    high: np.ndarray,
    low: np.ndarray,
    left: int = SWING_FRACTAL - 1,
    right: int = SWING_RIGHT_BARS,
) -> PivotLevels:
    """Fractal pivots, published only after the confirming bar has closed.

    A pivot at bar ``p`` is the extreme of the window ``[p-left, p+right]`` and
    becomes knowable at bar ``p + right``.  Ties count as pivots, matching the
    reference's non-strict fractal comparison (``pine:L622``).
    """
    n = high.shape[0]
    h_idx, h_price, h_known, l_idx, l_price, l_known = [], [], [], [], [], []

    if n > left + right:
        # rolling window view -> (n-left-right, 1+left+right)
        hv = np.lib.stride_tricks.sliding_window_view(high, left + right + 1)
        lv = np.lib.stride_tricks.sliding_window_view(low, left + right + 1)
        mid = left
        h_max = hv.max(axis=1)
        l_min = lv.min(axis=1)
        # pivot bar p = left + k ; window rows are ordered p-left .. p+right
        h_hit = hv[:, mid] >= h_max
        l_hit = lv[:, mid] <= l_min
        p_idx = np.arange(left, left + h_hit.shape[0])
        known = p_idx + right
        h_idx = p_idx[h_hit]
        h_price = high[h_idx]
        h_known = known[h_hit]
        l_idx = p_idx[l_hit]
        l_price = low[l_idx]
        l_known = known[l_hit]

    empty_i = np.empty(0, dtype=np.int64)
    empty_f = np.empty(0, dtype=np.float64)
    return PivotLevels(
        high_idx=h_idx.astype(np.int64),
        high_price=h_price.astype(np.float64),
        high_known=h_known.astype(np.int64),
        low_idx=l_idx.astype(np.int64),
        low_price=l_price.astype(np.float64),
        low_known=l_known.astype(np.int64),
    )


# ---------------------------------------------------------------------------
# FVG geometry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FvgSet:
    """A set of three-candle fair-value gaps.

    ``oldest`` / ``newest`` are the bar indices of the gap's first and last
    candle, ``gap_low`` / ``gap_high`` are the gap edges and ``fvg_type`` is
    ``+1`` for a bullish gap (support) and ``-1`` for a bearish gap
    (resistance).  The **trade direction is the opposite** of the gap type.
    """

    oldest: np.ndarray
    newest: np.ndarray
    gap_low: np.ndarray
    gap_high: np.ndarray
    fvg_type: np.ndarray

    def __len__(self) -> int:  # pragma: no cover - trivial
        return int(self.oldest.shape[0])

    @property
    def trade_dir(self) -> np.ndarray:
        """+1 long (inverted bearish gap) / -1 short (inverted bullish gap)."""
        return -self.fvg_type


def detect_fvg(
    bars: Bars,
    atr: np.ndarray | None = None,
    min_gap_atr_mult: float | None = 0.25,
) -> FvgSet:
    """Detect three-candle FVGs on closed bars.

    Geometry is strict and wick-based (``DOC L121``, ``pine:L354-356``):
    ``low[c] > high[c-2]`` for a bullish gap, ``high[c] < low[c-2]`` for
    a bearish one.  A zero-width gap is not a gap.

    ``min_gap_atr_mult`` applies the doc's floor ``gap > mult * ATR(14)``,
    anchored at the gap's **newest** bar (RULE_SPEC A02).  ``None`` disables
    the floor, which is what the reference replica does (it has no ATR at all).

    The floor may also be given **per candle** (an array of the same length
    as ``bars``), which is how the volatility regime tightens or relaxes it
    band by band (L107-109).
    """
    n = len(bars)
    oldest = np.empty(0, dtype=np.int64)
    newest = np.empty(0, dtype=np.int64)
    gap_low = np.empty(0, dtype=np.float64)
    gap_high = np.empty(0, dtype=np.float64)
    fvg_type = np.empty(0, dtype=np.int8)

    if n < 3:
        return FvgSet(oldest, newest, gap_low, gap_high, fvg_type)

    c_idx = np.arange(2, n)
    a_idx = c_idx - 2
    bull = bars.low[c_idx] > bars.high[a_idx]
    bear = bars.high[c_idx] < bars.low[a_idx]
    keep = bull | bear
    if not keep.any():
        return FvgSet(oldest, newest, gap_low, gap_high, fvg_type)

    c_idx = c_idx[keep]
    a_idx = a_idx[keep]
    is_bull = bull[keep]
    low_edge = np.where(is_bull, bars.high[a_idx], bars.high[c_idx])
    high_edge = np.where(is_bull, bars.low[c_idx], bars.low[a_idx])

    if min_gap_atr_mult is not None and atr is not None:
        ref = atr[c_idx]
        width = high_edge - low_edge
        mult = np.asarray(min_gap_atr_mult, dtype=np.float64)
        if mult.ndim == 0:
            floor = float(mult) * ref
        else:
            # A per-candle floor: the regime tightens or relaxes the gap
            # filter band by band (L107-109).
            floor = mult[c_idx] * ref
        ok = np.isfinite(ref) & (ref > 0.0) & (width > floor)
        c_idx, a_idx = c_idx[ok], a_idx[ok]
        low_edge, high_edge = low_edge[ok], high_edge[ok]
        is_bull = is_bull[ok]

    return FvgSet(
        oldest=a_idx.astype(np.int64),
        newest=c_idx.astype(np.int64),
        gap_low=low_edge.astype(np.float64),
        gap_high=high_edge.astype(np.float64),
        fvg_type=np.where(is_bull, 1, -1).astype(np.int8),
    )


# ---------------------------------------------------------------------------
# Liquidity sweeps
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SweepEvent:
    """A liquidity sweep: the wick pierced a known level and the body closed back inside."""

    bar: int          # bar index of the sweep
    direction: int    # +1 = high swept (bearish raid), -1 = low swept
    level: float      # the swept level
    known_at: int     # bar index at which the level became knowable


class SweepDetector:
    """Liquidity-sweep detector with the reference's **one-shot level consumption**.

    The reference removes every swept swing point from its set
    (``pine:L560-575``), so a level can be swept **once, ever**.  A detector that
    merely flags sweeps produces a different signal population (L2 §D.4), so the
    consumption is reproduced here.

    Two level sources are supported: causal swing pivots of the traded series
    and externally supplied levels (EQH/EQL clusters, PDH/PDL).

    The implementation keeps the high and the low levels in separate lists and
    tracks their extremes, so the common case (no level in reach) costs one
    float comparison per bar.
    """

    def __init__(
        self,
        require_body_reclaim: bool = True,
        consume_levels: bool = True,
        max_levels: int = MAX_SESSIONS,
    ) -> None:
        self.require_body_reclaim = require_body_reclaim
        self.consume_levels = consume_levels
        self.max_levels = max_levels
        self._highs: list[tuple[float, int]] = []
        self._lows: list[tuple[float, int]] = []
        self._min_high = math.inf
        self._max_low = -math.inf
        self.events: list[SweepEvent] = []

    def add_level(self, price: float, direction: int, known_at: int) -> None:
        """Register a level: ``direction`` +1 = a swing high, -1 = a swing low."""
        if not math.isfinite(price):
            return
        if direction > 0:
            self._highs.append((float(price), int(known_at)))
            if len(self._highs) > self.max_levels:
                self._highs.pop(0)
            if price < self._min_high:
                self._min_high = float(price)
        else:
            self._lows.append((float(price), int(known_at)))
            if len(self._lows) > self.max_levels:
                self._lows.pop(0)
            if price > self._max_low:
                self._max_low = float(price)

    def update(self, bar: int, high: float, low: float, close: float) -> list[SweepEvent]:
        """Test the active levels against bar ``bar`` and consume the ones pierced.

        A level that became knowable at bar ``k`` may only be swept from bar
        ``k + 1``: it is published at the close of bar ``k`` and the sweep test
        uses the bar's own high/low, which is only complete at the bar's close.
        """
        hits: list[SweepEvent] = []

        if self._highs and high > self._min_high:
            keep: list[tuple[float, int]] = []
            for price, known_at in self._highs:
                if bar <= known_at or not (high > price and (close < price or not self.require_body_reclaim)):
                    keep.append((price, known_at))
                    continue
                hits.append(SweepEvent(bar=bar, direction=1, level=price, known_at=known_at))
                if not self.consume_levels:
                    keep.append((price, known_at))
            self._highs = keep
            self._min_high = min((p for p, _ in keep), default=math.inf)

        if self._lows and low < self._max_low:
            keep = []
            for price, known_at in self._lows:
                if bar <= known_at or not (low < price and (close > price or not self.require_body_reclaim)):
                    keep.append((price, known_at))
                    continue
                hits.append(SweepEvent(bar=bar, direction=-1, level=price, known_at=known_at))
                if not self.consume_levels:
                    keep.append((price, known_at))
            self._lows = keep
            self._max_low = max((p for p, _ in keep), default=-math.inf)

        self.events.extend(hits)
        return hits


def local_minutes_of_day(ts: np.ndarray, timezone: str = "America/New_York") -> np.ndarray:
    """Minutes since local midnight for every timestamp (DST-aware).

    Used for the killzone test (``DOC L115``, evaluated on the bar's **close**
    timestamp) and for ``minutes_from_us_open``.
    """
    if ts.shape[0] == 0:
        return np.empty(0, dtype=np.int64)
    local = ts.astype("int64") + _utc_offsets(ts, timezone)
    return (local // 60_000_000_000) % 1440


# ---------------------------------------------------------------------------
# Session / day extremes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionExtremes:
    """Previous-day and per-session high/low, computed causally.

    ``day_id`` is the integer day index of every bar under the configured
    timezone; ``day_high`` / ``day_low`` carry the extreme of the **previous
    completed day**, so a bar on day ``D`` can never see day ``D``'s extreme.
    """

    day_id: np.ndarray        # int64 day index per bar
    day_high: np.ndarray      # float64, previous completed day's high
    day_low: np.ndarray       # float64, previous completed day's low
    pdh: np.ndarray           # alias of day_high (previous day high)
    pdl: np.ndarray           # alias of day_low (previous day low)


def session_extremes(
    ts: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    timezone: str = "UTC",
) -> SessionExtremes:
    """Compute previous-day high/low (PDH/PDL) from the bar timestamps.

    The **day boundary** is the configured timezone's calendar day.  For CME
    futures the correct boundary is the Globex day (18:00 ET -> 17:00 ET), which
    the doc never defines; the calendar-day default is used and documented as a
    known approximation (L2 §C.3).

    The extremes are shifted by one day: the value attached to a bar is the
    extreme of the *previous* completed day.
    """
    n = ts.shape[0]
    if n == 0:
        empty = np.empty(0, dtype=np.float64)
        return SessionExtremes(
            day_id=np.empty(0, dtype=np.int64),
            day_high=empty,
            day_low=empty,
            pdh=empty,
            pdl=empty,
        )

    local_ns = ts.astype("datetime64[ns]").astype(np.int64) + _utc_offsets(ts, timezone)
    local_days = local_ns // 86_400_000_000_000

    _, inverse = np.unique(local_days, return_inverse=True)
    n_days = int(inverse.max()) + 1
    day_high = np.full(n_days, -np.inf, dtype=np.float64)
    day_low = np.full(n_days, np.inf, dtype=np.float64)
    np.maximum.at(day_high, inverse, high)
    np.minimum.at(day_low, inverse, low)

    prev_high = np.concatenate(([np.nan], day_high[:-1]))
    prev_low = np.concatenate(([np.nan], day_low[:-1]))

    return SessionExtremes(
        day_id=inverse.astype(np.int64),
        day_high=prev_high[inverse],
        day_low=prev_low[inverse],
        pdh=prev_high[inverse],
        pdl=prev_low[inverse],
    )


def _utc_offsets(ts: np.ndarray, timezone: str) -> np.ndarray:
    """UTC offset (ns) of ``timezone`` at each timestamp (DST-aware).

    The offset only changes at a DST transition, so it is derived once per
    **hour**: a transition happens at a whole local hour, and a per-day
    derivation would be wrong for the hours of the transition day itself.
    """
    from datetime import datetime, timedelta, timezone as _tz

    from zoneinfo import ZoneInfo

    tz = ZoneInfo(timezone)
    seconds = ts.astype("datetime64[ns]").astype("datetime64[s]").astype(np.int64)
    hours = seconds // 3600
    uniq, inverse = np.unique(hours, return_inverse=True)
    hour_offsets = np.zeros(uniq.shape[0], dtype=np.int64)
    for i, h in enumerate(uniq):
        dt = datetime(1970, 1, 1) + timedelta(seconds=int(h) * 3600)
        off = dt.replace(tzinfo=_tz.utc).astimezone(tz).utcoffset() or timedelta(0)
        hour_offsets[i] = int(off.total_seconds())
    # the offsets are in **seconds**; the timestamps are in nanoseconds
    return (hour_offsets[inverse] * 1_000_000_000).astype(np.int64)


# ---------------------------------------------------------------------------
# Equal highs / equal lows (L2 row 5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EqualLevel:
    """A cluster of near-equal highs (or lows).

    ``price`` is the cluster's reference price, ``count`` how many observations
    joined it and ``known_at`` the bar at which the cluster became usable.
    """

    price: float
    direction: int
    known_at: int
    count: int = 1

    def as_dict(self) -> dict:
        return {
            "price": self.price,
            "direction": self.direction,
            "known_at": self.known_at,
            "count": self.count,
        }


class EqualLevelStore:
    """The doc's **EQH / EQL** level source (L2 row 5).

    The doc's sweep object is a *cluster* of equal highs (or lows), not a
    single pivot: several touches at the same price are one level of
    liquidity.  The store therefore clusters near-equal observations and,
    like :class:`SweepDetector`, **consumes** a level when it is swept --
    a level is raided once.

    The tolerance is expressed as a fraction of the ATR (the doc's "the same
    price" is a price *band*, and the band's width has to scale with the
    instrument).  When no ATR is supplied the tolerance falls back to the
    same fraction of the level's own price, which keeps the store usable
    without an ATR series.
    """

    def __init__(
        self,
        tolerance_atr_frac: float = 0.10,
        *,
        atr: float | None = None,
        max_levels: int = MAX_SESSIONS,
    ) -> None:
        if tolerance_atr_frac <= 0.0:
            raise ValueError("tolerance_atr_frac must be positive")
        self.tolerance_atr_frac = float(tolerance_atr_frac)
        self.atr = None if atr is None else float(atr)
        self.max_levels = int(max_levels)
        self._levels: list[EqualLevel] = []
        self.events: list[SweepEvent] = []

    # --- construction ----------------------------------------------------

    def _tolerance(self, price: float) -> float:
        scale = self.atr if self.atr is not None else abs(price)
        return self.tolerance_atr_frac * scale

    def add_level(self, price: float, direction: int, known_at: int) -> EqualLevel:
        """Register a level, clustering it with a near-equal one."""
        if not math.isfinite(price):
            raise ValueError("a level price must be finite")
        direction = 1 if direction > 0 else -1
        tolerance = self._tolerance(price)
        for index, level in enumerate(self._levels):
            if level.direction != direction:
                continue
            if abs(level.price - price) <= tolerance:
                merged = EqualLevel(
                    price=(level.price * level.count + price) / (level.count + 1),
                    direction=direction,
                    known_at=min(level.known_at, int(known_at)),
                    count=level.count + 1,
                )
                self._levels[index] = merged
                return merged
        level = EqualLevel(
            price=float(price),
            direction=direction,
            known_at=int(known_at),
        )
        self._levels.append(level)
        if len(self._levels) > self.max_levels:
            self._levels.pop(0)
        return level

    def levels(self) -> list[EqualLevel]:
        """The live levels, oldest first."""
        return list(self._levels)

    # --- consumption ------------------------------------------------------

    def update(self, bar: int, high: float, low: float, close: float) -> list[SweepEvent]:
        """Test the live levels against ``bar`` and consume the ones pierced."""
        hits: list[SweepEvent] = []
        keep: list[EqualLevel] = []
        for level in self._levels:
            if bar <= level.known_at:
                keep.append(level)
                continue
            if level.direction > 0:
                pierced = high > level.price and close < level.price
            else:
                pierced = low < level.price and close > level.price
            if not pierced:
                keep.append(level)
                continue
            hits.append(
                SweepEvent(
                    bar=int(bar),
                    direction=level.direction,
                    level=level.price,
                    known_at=level.known_at,
                )
            )
        self._levels = keep
        self.events.extend(hits)
        return hits


# ---------------------------------------------------------------------------
# Unreclaimed HTF FVG zones (L2 row 3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HtfFvgZone:
    """One unreclaimed zone on the higher timeframe."""

    bottom: float
    top: float
    bullish: bool
    opened_bar: int

    def as_dict(self) -> dict:
        return {
            "bottom": self.bottom,
            "top": self.top,
            "bullish": self.bullish,
            "opened_bar": self.opened_bar,
        }


class HtfFvgZones:
    """The doc's **unreclaimed 15m / 1H FVG zones** (L2 row 3).

    Two kinds of zone are tracked, both published from **closed** HTF bars only
    (the reference publishes its HTF zone one bar late, so a zone may never be
    read from a bar that has not closed):

    * the **three-candle FVG** -- ``low[i] > high[i-2]`` leaves the band
      ``[high[i-2], low[i]]`` unfilled;
    * the **opening band** -- a bar whose open lies outside its own range
      opened discontinuously, so the band between the opening print and the
      extreme is not fully traded.

    A zone stays *unreclaimed* until a later bar trades outside it: price
    above its top (a bullish zone is spent) or below its bottom.
    """

    def __init__(self, timeframe_minutes: int = 15, *, max_zones: int = 3) -> None:
        if timeframe_minutes <= 0:
            raise ValueError("timeframe_minutes must be positive")
        self.timeframe_minutes = int(timeframe_minutes)
        self.max_zones = int(max_zones)
        self._bars: list["HtfFvgZones.Bar"] = []
        self._zones: list[HtfFvgZone] = []

    @dataclass(frozen=True)
    class Bar:
        """One **closed** HTF bar."""

        ts: int
        open: float
        high: float
        low: float
        close: float

    # --- publication ------------------------------------------------------

    def update(self, bars: "list[HtfFvgZones.Bar] | tuple[HtfFvgZones.Bar, ...]") -> list[HtfFvgZone]:
        """Fold newly closed HTF bars in and publish the zones they create."""
        for bar in bars:
            self._bars.append(bar)
            index = len(self._bars) - 1
            zone = self._three_candle_zone(index)
            if zone is None:
                zone = self._opening_band(index)
            if zone is not None:
                self._zones.append(zone)
                self._trim()
            self._mitigate(index)
        return [zone for zone in self._zones if self._live(zone)]

    def _three_candle_zone(self, index: int) -> HtfFvgZone | None:
        if index < 2:
            return None
        first = self._bars[index - 2]
        last = self._bars[index]
        if last.low > first.high:
            return HtfFvgZone(
                bottom=first.high, top=last.low, bullish=True, opened_bar=index
            )
        if last.high < first.low:
            return HtfFvgZone(
                bottom=last.high, top=first.low, bullish=False, opened_bar=index
            )
        return None

    def _opening_band(self, index: int) -> HtfFvgZone | None:
        bar = self._bars[index]
        if bar.open < bar.low:
            return HtfFvgZone(
                bottom=bar.open, top=bar.high, bullish=False, opened_bar=index
            )
        if bar.open > bar.high:
            return HtfFvgZone(
                bottom=bar.low, top=bar.open, bullish=True, opened_bar=index
            )
        return None

    def _mitigate(self, index: int) -> None:
        bar = self._bars[index]
        live: list[HtfFvgZone] = []
        for zone in self._zones:
            if zone.opened_bar >= index:
                live.append(zone)
                continue
            if bar.high > zone.top or bar.low < zone.bottom:
                continue  # spent
            live.append(zone)
        self._zones = live

    def _live(self, zone: HtfFvgZone) -> bool:
        return any(zone is other for other in self._zones)

    def _trim(self) -> None:
        while len(self._zones) > self.max_zones:
            self._zones.pop(0)

    # --- reading ----------------------------------------------------------

    def unreclaimed(self) -> list[HtfFvgZone]:
        """The zones price has not yet spent."""
        return list(self._zones)


# ---------------------------------------------------------------------------
# Higher-timeframe aggregation (L2 rows 3 and 5, audit D-06 / D-08)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HtfLevel:
    """One swing level of the higher timeframe.

    ``known_at`` is the index of the **1-minute** bar at whose close the level
    became knowable: the reference detects the three-bar fractal only when the
    *next* higher-timeframe bucket has closed (``pine:L616-621``), so the level
    is one bucket late by construction and never looks ahead.
    """

    price: float
    direction: int       # +1 = a swing high, -1 = a swing low
    known_at: int


@dataclass(frozen=True)
class HtfSeries:
    """The hand-aggregated higher-timeframe view of a 1-minute series.

    The reference builds its HTF view by hand: the running high/low of the
    current bucket is pushed when the bucket changes (``pine:L567-585``).  The
    same aggregation is reproduced here, together with the two products the
    reference derives from it: the **unreclaimed FVG zones** (row 3) and the
    **three-bar fractal levels** its sweep detector consumes (row 5).
    """

    bucket_of_bar: np.ndarray       # per 1-minute bar: its bucket index
    closed_buckets: np.ndarray      # per 1-minute bar: buckets closed by its close
    bars: tuple[HtfFvgZones.Bar, ...]
    zones: tuple[tuple[HtfFvgZone, ...], ...]   # per closed bucket: the live zones
    levels: tuple[HtfLevel, ...]                # the three-bar fractal levels

    def zones_at(self, bar: int) -> tuple[HtfFvgZone, ...]:
        """The unreclaimed zones knowable at the close of ``bar``."""
        if bar < 0 or bar >= len(self.closed_buckets):
            return ()
        closed = int(self.closed_buckets[bar])
        if closed <= 0:
            return ()
        return self.zones[closed - 1]


def aggregate_htf(bars: Bars, timeframe_minutes: int = 15) -> HtfSeries:
    """Aggregate closed bars into the reference's hand-built HTF view.

    The buckets are UTC-aligned and a bucket is only usable once its **last**
    constituent bar has closed, so nothing in the result is knowable earlier
    than the data allows (``pine:L567-585``).
    """
    if timeframe_minutes <= 0:
        raise ValueError("timeframe_minutes must be positive")
    n = len(bars)
    bucket_ns = int(timeframe_minutes) * 60_000_000_000
    if n == 0:
        return HtfSeries(
            bucket_of_bar=np.zeros(0, dtype=np.int64),
            closed_buckets=np.zeros(0, dtype=np.int64),
            bars=(),
            zones=(),
            levels=(),
        )

    ts = bars.ts
    bucket_ids = (ts // bucket_ns).astype(np.int64)
    # the bucket of every bar, compressed to 0..k-1 (gaps leave no bucket)
    unique_buckets, inverse = np.unique(bucket_ids, return_inverse=True)
    bucket_of_bar = inverse.astype(np.int64)

    # --- the closed HTF bars ----------------------------------------------
    htf_bars: list[HtfFvgZones.Bar] = []
    bucket_last_bar: list[int] = []
    for b in range(len(unique_buckets)):
        members = np.flatnonzero(bucket_of_bar == b)
        first = int(members[0])
        last = int(members[-1])
        htf_bars.append(
            HtfFvgZones.Bar(
                ts=int(ts[first]),
                open=float(bars.open[first]),
                high=float(bars.high[members].max()),
                low=float(bars.low[members].min()),
                close=float(bars.close[last]),
            )
        )
        bucket_last_bar.append(last)

    # --- how many buckets are closed at each 1-minute bar's close ----------
    closed_buckets = np.zeros(n, dtype=np.int64)
    last_index = np.asarray(bucket_last_bar, dtype=np.int64)
    # a bucket closes at the close of its last member bar
    running = 0
    closes = {int(idx): pos + 1 for pos, idx in enumerate(last_index)}
    for j in range(n):
        running = max(running, closes.get(j, 0))
        closed_buckets[j] = running

    # --- the unreclaimed zones over time ----------------------------------
    store = HtfFvgZones(timeframe_minutes=timeframe_minutes)
    zones_per_bucket: list[tuple[HtfFvgZone, ...]] = []
    for pos, bar in enumerate(htf_bars):
        store.update([bar])
        zones_per_bucket.append(tuple(store.unreclaimed()))

    # --- the three-bar fractal levels (the reference's sweep object) ------
    levels: list[HtfLevel] = []
    highs = [b.high for b in htf_bars]
    lows = [b.low for b in htf_bars]
    for pos in range(2, len(htf_bars)):
        # the middle bucket of the triple is the pivot; it becomes knowable
        # when the *next* bucket closes
        known_at = bucket_last_bar[pos]
        if highs[pos - 1] >= highs[pos - 2] and highs[pos - 1] >= highs[pos]:
            levels.append(HtfLevel(price=highs[pos - 1], direction=1, known_at=known_at))
        if lows[pos - 1] <= lows[pos - 2] and lows[pos - 1] <= lows[pos]:
            levels.append(HtfLevel(price=lows[pos - 1], direction=-1, known_at=known_at))

    return HtfSeries(
        bucket_of_bar=bucket_of_bar,
        closed_buckets=closed_buckets,
        bars=tuple(htf_bars),
        zones=tuple(zones_per_bucket),
        levels=tuple(levels),
    )
