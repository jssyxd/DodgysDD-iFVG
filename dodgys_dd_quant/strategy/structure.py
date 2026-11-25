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
    "FvgSet",
    "detect_fvg",
    "SweepDetector",
    "SweepEvent",
    "PivotLevels",
    "SessionExtremes",
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

    ts_col = "timestamp" if "timestamp" in cols else None
    if ts_col is None:
        raise ValueError(f"{path}: no 'timestamp' column (found {sorted(cols)})")

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
    # numpy arrays from the start: the short-series branch below skips the
    # vectorised path, and the constructor calls .astype on every argument
    h_idx = np.empty(0, dtype=np.int64)
    h_price = np.empty(0, dtype=np.float64)
    h_known = np.empty(0, dtype=np.int64)
    l_idx = np.empty(0, dtype=np.int64)
    l_price = np.empty(0, dtype=np.float64)
    l_known = np.empty(0, dtype=np.int64)

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
    ``low[c] > high[c-2]`` for a bullish gap, ``high[c] < low[c-2]`` for a
    bearish one.  A zero-width gap is not a gap.

    ``min_gap_atr_mult`` applies the doc's floor ``gap > mult * ATR(14)``,
    anchored at the gap's **newest** bar (RULE_SPEC A02).  ``None`` disables
    the floor, which is what the reference replica does (it has no ATR at all).
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
        ok = np.isfinite(ref) & (ref > 0.0) & (width > min_gap_atr_mult * ref)
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
    """UTC offset (ns) of ``timezone`` at each timestamp (DST-aware)."""
    from datetime import datetime, timedelta, timezone as _tz

    from zoneinfo import ZoneInfo

    tz = ZoneInfo(timezone)
    seconds = ts.astype("datetime64[ns]").astype("datetime64[s]").astype(np.int64)
    # the offset changes at DST transitions, and a transition happens *within* a
    # day -- deriving it per day put the whole transition day on midnight's
    # offset, which was wrong by an hour for the rest of that day.  Per hour is
    # exact outside the ambiguous transition hour itself.
    hours = seconds // 3_600
    uniq, inverse = np.unique(hours, return_inverse=True)
    day_offsets = np.zeros(uniq.shape[0], dtype=np.int64)
    for i, h in enumerate(uniq):
        dt = datetime(1970, 1, 1) + timedelta(seconds=int(h) * 3_600)
        off = dt.replace(tzinfo=_tz.utc).astimezone(tz).utcoffset() or timedelta(0)
        day_offsets[i] = int(off.total_seconds())
    # ``day_offsets`` holds **seconds**; the caller adds it to a nanosecond
    # index.  Casting it straight to ``timedelta64[ns]`` read the number as
    # nanoseconds, so the offset was effectively zero: every ET conversion
    # silently returned UTC, and the killzone gate and PDH/PDL ran on UTC
    # whole-days instead of the New-York session.
    return day_offsets[inverse] * 1_000_000_000
