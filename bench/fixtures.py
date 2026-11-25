"""Loading of the committed benchmark fixtures.

The benchmark must run **offline and deterministically**, so every dataset it
needs is committed to the repository as a gzip-compressed CSV under
``bench/fixtures/``.  The files are slices of the governed lake (read-only,
never written back); ``bench/fixtures/MANIFEST.md`` records their provenance.

The CSV format is deliberately dull::

    ts_ms,o,h,l,c,v

* ``ts_ms`` -- the bar's **open** time in milliseconds since the epoch (the
  lake's left-open convention);
* ``o,h,l,c`` -- the prices in **integer cents**, so the file round-trips
  exactly and the text compresses well;
* ``v`` -- the volume, rounded to an integer.

Everything else -- the nanosecond time index, the float prices -- is
reconstructed on load.
"""

from __future__ import annotations

import csv
import gzip
import math
from functools import lru_cache
from pathlib import Path

import numpy as np

__all__ = [
    "FIXTURE_DIR",
    "load_fixture",
    "bars_from_fixture",
    "frame_from_fixture",
    "btc_1m",
    "eth_1m",
    "btc_15m",
    "qqq_15m",
    "vxn_daily",
    "candidate_log",
    "labelled_frame",
    "rolling_frame",
]

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

_NS_PER_MS = 1_000_000
_NS_PER_MINUTE = 60_000_000_000
_NS_PER_HOUR = 60 * _NS_PER_MINUTE
_NS_PER_DAY = 24 * _NS_PER_HOUR


@lru_cache(maxsize=None)
def load_fixture(name: str) -> dict[str, np.ndarray]:
    """Read one fixture into numpy arrays (cents -> float prices)."""
    path = FIXTURE_DIR / f"{name}.csv.gz"
    if not path.exists():
        raise FileNotFoundError(f"benchmark fixture missing: {path}")
    ts: list[int] = []
    o: list[int] = []
    h: list[int] = []
    low: list[int] = []
    c: list[int] = []
    v: list[int] = []
    with gzip.open(path, "rt", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        if header != ["ts_ms", "o", "h", "l", "c", "v"]:
            raise ValueError(f"{path}: unexpected header {header}")
        for row in reader:
            ts.append(int(row[0]))
            o.append(int(row[1]))
            h.append(int(row[2]))
            low.append(int(row[3]))
            c.append(int(row[4]))
            v.append(int(row[5]))
    return {
        "ts_ms": np.asarray(ts, dtype=np.int64),
        "open": np.asarray(o, dtype=np.float64) / 100.0,
        "high": np.asarray(h, dtype=np.float64) / 100.0,
        "low": np.asarray(low, dtype=np.float64) / 100.0,
        "close": np.asarray(c, dtype=np.float64) / 100.0,
        "volume": np.asarray(v, dtype=np.float64),
    }


def bars_from_fixture(name: str, symbol: str, timeframe: str):
    """Build the engine's ``Bars`` container from a fixture."""
    from dodgys_dd_quant.strategy.structure import Bars

    data = load_fixture(name)
    return Bars(
        ts=data["ts_ms"] * _NS_PER_MS,
        open=data["open"],
        high=data["high"],
        low=data["low"],
        close=data["close"],
        volume=data["volume"],
        symbol=symbol,
        timeframe=timeframe,
    )


def frame_from_fixture(name: str):
    """Build the ML pipeline's bar frame (``ts_event`` in nanoseconds).

    ``ts_event`` is the bar's **close** time, the same convention the D2
    candidate log and the rule engine use (``ts_event`` = the close of the
    confirmation bar).  The lake stamps its bars at the open, so the fixture
    adds one bar interval.
    """
    import pandas as pd

    data = load_fixture(name)
    ts = data["ts_ms"] * _NS_PER_MS
    interval = _interval_ns(ts)
    return pd.DataFrame(
        {
            "ts_event": ts + interval,
            "open": data["open"],
            "high": data["high"],
            "low": data["low"],
            "close": data["close"],
            "volume": data["volume"],
        }
    )


def _interval_ns(ts: np.ndarray) -> int:
    """The modal bar spacing of a regular series, in nanoseconds."""
    if ts.size < 2:
        return _NS_PER_MINUTE
    diffs = np.diff(ts)
    values, counts = np.unique(diffs, return_counts=True)
    return int(values[int(np.argmax(counts))])


def btc_1m():
    return bars_from_fixture("btcusdt_1m_2023q1", "BTCUSDT", "1m")


def eth_1m():
    return bars_from_fixture("ethusdt_1m_2023q1", "ETHUSDT", "1m")


def btc_15m():
    return bars_from_fixture("btcusdt_15m_2024_2026", "BTCUSDT", "15m")


def qqq_15m():
    return bars_from_fixture("qqq_15m", "QQQ", "15m")


def vxn_daily():
    """The CBOE VXN daily close, as ``(day_number, close)``."""
    data = load_fixture("vxn_1d")
    days = data["ts_ms"] // 86_400_000
    return days.astype(np.int64), data["close"]


def load_series(name: str) -> tuple[np.ndarray, np.ndarray]:
    """Read a daily *index* fixture (``day,value``), as ``(days, values)``."""
    path = FIXTURE_DIR / f"{name}.csv.gz"
    if not path.exists():
        raise FileNotFoundError(f"benchmark fixture missing: {path}")
    days: list[int] = []
    values: list[float] = []
    with gzip.open(path, "rt", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        if header != ["day", "value"]:
            raise ValueError(f"{path}: unexpected header {header}")
        for row in reader:
            days.append(int(row[0]))
            values.append(float(row[1]))
    return np.asarray(days, dtype=np.int64), np.asarray(values, dtype=np.float64)


def dvol_daily():
    """The crypto DVOL daily close, as ``(day_number, close)``."""
    return load_series("dvol_1d")


def funding_daily():
    """The BTCUSDT daily mean funding rate, as ``(day_number, rate)``."""
    return load_series("btc_funding_1d")


@lru_cache(maxsize=None)
def candidate_log(symbol: str = "BTCUSDT", preset: str = "honest"):
    """Run the rule engine over the BTC 1-minute fixture (cached).

    The **VXN regime is attached**, as the production runner does with
    ``--regime vxn``: the D2 log carries ``vxn_known`` and ``vxn_regime``, and
    the regime-conditioned analyses need them.  The index is the committed
    daily VXN fixture, lagged by a day.
    """
    from dodgys_dd_quant.strategy.regime import VxnRegimeIndex
    from dodgys_dd_quant.strategy.state_machine import PRESETS, run_state_machine

    days, closes = vxn_daily()
    index = VxnRegimeIndex(days=days, closes=closes)
    bars = btc_1m()
    return run_state_machine(bars, PRESETS[preset], regime=index)


@lru_cache(maxsize=None)
def labelled_frame(symbol: str = "BTCUSDT", preset: str = "honest"):
    """The candidate log joined with labels and features, as a DataFrame."""
    import pandas as pd

    from dodgys_dd_quant.ml_pipeline.features import build_features
    from dodgys_dd_quant.ml_pipeline.labels import build_labels

    log = candidate_log(symbol, preset)
    columns = [
        "ts_event", "side", "entry_price", "stop_price", "target_price", "risk",
        "fvg_low", "fvg_high", "fvg_bar1", "fvg_bar3", "confirm_bar",
        "bars_to_inversion", "checklist_score", "smt_divergence", "sweep_detected",
        "vxn_known", "vxn_regime", "label", "r_multiple",
    ]
    table = log.to_table()
    frame = pd.DataFrame({name: table[name] for name in columns})
    bars = frame_from_fixture("btcusdt_1m_2023q1")
    labelled = build_labels(frame, bars)
    return build_features(labelled, bars)


@lru_cache(maxsize=None)
def rolling_frame(symbol: str = "BTCUSDT", preset: str = "honest"):
    """A labelled 15-minute frame long enough for the 6/1/1 fold geometry.

    The 6-month train / 1-month validate / 1-month test windows need more than
    a quarter of history, so the rolling lane uses the 2024-2026 15-minute
    series rather than the 2023-Q1 1-minute one.

    The **VXN regime is attached**, because the regime is part of the D2 log
    (``vxn_known`` / ``vxn_regime``) and the regime-conditioned analyses need
    it.  The VXN series is the committed daily fixture, lagged by a day.
    """
    import pandas as pd

    from dodgys_dd_quant.ml_pipeline.features import build_features
    from dodgys_dd_quant.ml_pipeline.labels import build_labels
    from dodgys_dd_quant.strategy.regime import VxnRegimeIndex
    from dodgys_dd_quant.strategy.state_machine import PRESETS, run_state_machine

    days, closes = vxn_daily()
    index = VxnRegimeIndex(days=days, closes=closes)

    bars = btc_15m()
    log = run_state_machine(bars, PRESETS[preset], regime=index)
    columns = [
        "ts_event", "side", "entry_price", "stop_price", "target_price", "risk",
        "fvg_low", "fvg_high", "fvg_bar1", "fvg_bar3", "confirm_bar",
        "bars_to_inversion", "checklist_score", "smt_divergence", "sweep_detected",
        "vxn_known", "vxn_regime", "label", "r_multiple",
    ]
    table = log.to_table()
    frame = pd.DataFrame({name: table[name] for name in columns})
    bar_frame = frame_from_fixture("btcusdt_15m_2024_2026")
    labelled = build_labels(frame, bar_frame)
    return build_features(labelled, bar_frame), bar_frame


def finite_or_nan(value: float) -> float:
    """``value`` if it is a finite float, else NaN."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return out if math.isfinite(out) else float("nan")
