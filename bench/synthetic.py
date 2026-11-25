"""Deterministic synthetic market series for the benchmark.

Why synthetic and not the lake
------------------------------
The benchmark must produce **the same numbers on every machine, every run**,
with no network and no mount of the governed NFS lake.  A committed,
seeded generator gives that: the price path is a pure function of
``(seed, n_bars, interval)`` and of nothing else -- no clock, no RNG state
carried between calls, no file system.

The series is *not* random noise.  It is a regime-switching geometric
Brownian motion with

* **volatility regimes** -- three volatility levels with a per-bar
  volatility multiplier drawn from a fixed distribution.  FVGs only form
  when the market is not degenerate, so the regime switch is what makes the
  FVG population non-trivial;
* **intraday seasonality** -- a UTC-hour volatility profile, so the session
  boundaries (the killzones, the previous-day extremes) carry real structure;
* **occasional jumps** -- a small number of large moves, so the series has
  the occasional impulse leg the strategy reacts to.

Everything is expressed in integer nanoseconds / float64 so the same bytes
feed the rule engine and the ML pipeline.
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "NS_PER_MINUTE",
    "synth_bars",
    "synth_pair",
    "aggregate",
]

NS_PER_MINUTE = 60_000_000_000
NS_PER_HOUR = 60 * NS_PER_MINUTE
NS_PER_DAY = 24 * NS_PER_HOUR

#: Start of the synthetic sample: 2023-01-01T00:00:00Z.
EPOCH_START_NS = 1_672_531_200_000_000_000

#: The three volatility regimes and their sampling weights.
_REGIME_VOL = np.array([0.6, 2.4, 0.35], dtype=np.float64)
_REGIME_P = np.array([0.55, 0.25, 0.20], dtype=np.float64)

#: Intraday volatility profile by UTC hour (crypto: a mild, stable diurnal
#: shape).  Normalised to mean 1.0 below.
_HOUR_PROFILE = np.array(
    [
        0.85, 0.78, 0.72, 0.70, 0.75, 0.88, 1.00, 1.10,
        1.18, 1.22, 1.20, 1.15, 1.12, 1.14, 1.16, 1.12,
        1.05, 1.00, 0.98, 1.02, 1.10, 1.14, 1.06, 0.94,
    ],
    dtype=np.float64,
)


def _regime_path(rng: np.random.Generator, n: int) -> np.ndarray:
    """A block-constant volatility multiplier path."""
    blocks = rng.integers(200, 3_000, size=n // 500 + 2)
    mult = rng.choice(_REGIME_VOL, size=blocks.shape[0], p=_REGIME_P)
    path = np.repeat(mult, blocks)
    return path[:n]


def synth_bars(
    n_bars: int,
    *,
    seed: int,
    interval_ns: int = NS_PER_MINUTE,
    start_ns: int = EPOCH_START_NS,
    symbol: str = "SYNTHUSD",
    price0: float = 20_000.0,
    cross_symbol: str | None = None,
    cross_seed: int | None = None,
    cross_corr: float = 0.55,
) -> "SynthBars":
    """Generate one deterministic OHLCV series.

    Parameters
    ----------
    n_bars:
        Number of bars.
    seed:
        Master seed.  Two calls with the same seed give byte-identical
        output.
    interval_ns:
        Bar spacing in nanoseconds.
    start_ns:
        Timestamp of the first bar's **open** (left-open convention, the
        lake's convention).
    cross_symbol, cross_seed, cross_corr:
        When given, a second series is generated with a shared market
        factor of correlation ``cross_corr``.  Used to exercise the SMT
        cross-check, which needs a *reference instrument* that does not
        always make a new extreme when the traded series does.
    """
    if n_bars < 100:
        raise ValueError("n_bars must be >= 100")
    rng = np.random.default_rng(seed)

    ts = start_ns + np.arange(n_bars, dtype=np.int64) * int(interval_ns)

    # Shared market factor (so a pair of instruments is genuinely correlated).
    if cross_symbol is not None:
        factor = rng.normal(0.0, 1.0, n_bars)
    else:
        factor = None

    hourly = _HOUR_PROFILE[(ts // NS_PER_HOUR) % 24]
    vol = _regime_path(rng, n_bars) * hourly

    if factor is None:
        shocks = rng.normal(0.0, 1.0, n_bars)
    else:
        rng2 = np.random.default_rng((cross_seed if cross_seed is not None else seed) + 977)
        idio = rng2.normal(0.0, 1.0, n_bars)
        shocks = np.sqrt(cross_corr) * factor + np.sqrt(1.0 - cross_corr) * idio

    # Per-bar log return in price units: 4 bp per unit of volatility.
    step = 0.0004 * vol * shocks

    # A handful of impulse jumps: the strategy's whole premise is a violent
    # leg followed by a failed retest.
    n_jumps = max(1, n_bars // 40_000)
    jump_idx = rng.choice(n_bars, size=n_jumps, replace=False)
    jump_sign = rng.choice([-1.0, 1.0], size=n_jumps)
    jump_size = rng.uniform(0.004, 0.016, size=n_jumps) * jump_sign
    step[jump_idx] += jump_size

    close = price0 * np.exp(np.cumsum(step))

    # The bar *before* the close is the open; the last bar closes where it is.
    open_ = np.empty_like(close)
    open_[0] = price0
    open_[1:] = close[:-1]

    # Wicks: half the bar's realised range each way, with a little noise.
    span = np.abs(close - open_) + close * 0.00012 * np.abs(shocks)
    high = np.maximum(open_, close) + span * rng.uniform(0.15, 0.85, n_bars)
    low = np.minimum(open_, close) - span * rng.uniform(0.15, 0.85, n_bars)
    low = np.maximum(low, 1e-6)

    volume = rng.lognormal(4.0, 0.55, n_bars) * (1.0 + 6.0 * vol)

    return SynthBars(
        symbol=symbol,
        timeframe=_timeframe_of(interval_ns),
        ts=ts,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _timeframe_of(interval_ns: int) -> str:
    minutes = int(interval_ns) // NS_PER_MINUTE
    return f"{minutes}m" if minutes < 60 else f"{minutes // 60}h"


class SynthBars:
    """A plain OHLCV container with the same field names as ``Bars``.

    Kept separate from ``dodgys_dd_quant.strategy.structure.Bars`` so the
    benchmark can build a series without importing the package under test
    (a broken package must still let the harness *run* and report a low
    score, not crash the whole benchmark).
    """

    __slots__ = ("symbol", "timeframe", "ts", "open", "high", "low", "close", "volume")

    def __init__(self, symbol, timeframe, ts, open, high, low, close, volume):
        self.symbol = symbol
        self.timeframe = timeframe
        self.ts = ts
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume

    def __len__(self) -> int:
        return int(self.ts.shape[0])

    @property
    def interval_ns(self) -> int:
        if len(self.ts) < 2:
            return NS_PER_MINUTE
        diffs = np.diff(self.ts)
        return int(np.unique(diffs)[0]) if diffs.size else NS_PER_MINUTE


def synth_pair(
    n_bars: int,
    *,
    seed: int,
    interval_ns: int = NS_PER_MINUTE,
    start_ns: int = EPOCH_START_NS,
    cross_corr: float = 0.55,
) -> tuple[SynthBars, SynthBars]:
    """A traded series plus a correlated reference series (for SMT)."""
    traded = synth_bars(
        n_bars,
        seed=seed,
        interval_ns=interval_ns,
        start_ns=start_ns,
        symbol="SYNTHUSD",
        cross_symbol="SYNTHREF",
        cross_seed=seed + 1,
        cross_corr=cross_corr,
    )
    reference = synth_bars(
        n_bars,
        seed=seed + 1,
        interval_ns=interval_ns,
        start_ns=start_ns,
        symbol="SYNTHREF",
        price0=4_000.0,
    )
    return traded, reference


def aggregate(bars: SynthBars, factor: int) -> SynthBars:
    """Aggregate a series ``factor`` times (1m -> 15m and friends)."""
    n = len(bars) // factor * factor
    if n == 0:
        raise ValueError("series too short to aggregate")
    ts = bars.ts[:n].reshape(-1, factor)
    o = bars.open[:n].reshape(-1, factor)[:, 0]
    c = bars.close[:n].reshape(-1, factor)[:, -1]
    h = bars.high[:n].reshape(-1, factor).max(axis=1)
    l = bars.low[:n].reshape(-1, factor).min(axis=1)
    v = bars.volume[:n].reshape(-1, factor).sum(axis=1)
    return SynthBars(
        symbol=bars.symbol,
        timeframe=_timeframe_of(bars.interval_ns * factor),
        ts=ts[:, 0],
        open=o,
        high=h,
        low=l,
        close=c,
        volume=v,
    )
