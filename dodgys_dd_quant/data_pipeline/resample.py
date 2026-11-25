"""Build the higher-timeframe partitions from the 1-minute lane.

Why resample instead of downloading every interval
--------------------------------------------------
The exchange's own klines *are* its aggregation of 1m bars.  Pulling 5m, 15m,
30m, 1h, 2h, 4h and 1d separately multiplies the transfer by seven and can
introduce disagreement between intervals that should nest.  One 1m lane plus a
strict aggregation gives every interval from the same source, and a few
exchange-pulled intervals (:mod:`pull_exchange`) verify it.

"Strict" means **complete buckets only**
----------------------------------------
A bucket is emitted when it holds *every* expected 1m bar (or whatever the base
interval is).  A bucket with a missing bar is dropped and counted -- never
forward-filled, never partially assembled (the lake's contract forbids
synthetic bars, and a partial 30m candle is exactly that).  The drop count is
reported so a gappy source cannot masquerade as a clean higher timeframe.

CLI::

    python -m dodgys_dd_quant.data_pipeline.resample \
        --symbols BTCUSDT ETHUSDT SOLUSDT BNBUSDT XRPUSDT \
        --timeframes 5m 15m 30m 1h 2h 4h 1d --base 1m
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from dodgys_dd_quant.data_pipeline.audit import audit_frame
from dodgys_dd_quant.data_pipeline.pull_exchange import (
    DEFAULT_LAKE_ROOT,
    write_governed,
)

__all__ = ["interval_minutes", "resample_ohlcv", "build_timeframes"]

_INTERVAL_MINUTES: dict[str, int] = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "6h": 360,
    "8h": 480,
    "12h": 720,
    "1d": 1440,
}


def interval_minutes(interval: str) -> int:
    """``5m`` -> 5, ``1h`` -> 60, ``1d`` -> 1440."""
    text = str(interval).strip().lower()
    if text not in _INTERVAL_MINUTES:
        raise ValueError(
            f"unknown interval {interval!r}; expected one of "
            f"{sorted(_INTERVAL_MINUTES)}"
        )
    return _INTERVAL_MINUTES[text]


def resample_ohlcv(
    frame: pd.DataFrame,
    minutes: int,
    *,
    base_minutes: int = 1,
    strict: bool = True,
) -> tuple[pd.DataFrame, int]:
    """Aggregate ``frame`` into ``minutes`` buckets.

    Returns ``(bars, n_incomplete)``.  With ``strict`` (the default) only
    buckets holding every expected base bar are emitted; the rest are counted
    in ``n_incomplete`` and dropped.
    """
    if minutes % base_minutes:
        raise ValueError(f"{minutes}m is not a multiple of {base_minutes}m")
    expected = minutes // base_minutes
    ts = np.asarray(frame["ts_event"], dtype=np.int64)
    if ts.size and not bool(np.all(np.diff(ts) > 0)):
        raise ValueError("the base series is not strictly ascending")
    bucket = (ts // (minutes * 60_000)) * (minutes * 60_000)
    order = np.argsort(bucket, kind="stable")
    bucket = bucket[order]
    sub = frame.iloc[order]
    starts = np.flatnonzero(np.r_[True, bucket[1:] != bucket[:-1]])
    counts = np.diff(np.r_[starts, bucket.size])
    complete = counts == expected
    n_incomplete = int((~complete).sum())
    if strict:
        keep = np.repeat(complete, counts)
        sub = sub.iloc[np.flatnonzero(keep)]
    keep_columns = ["ts_event", "open", "high", "low", "close", "volume"] + [
        c
        for c in ("quote_volume", "trades", "taker_buy_base", "taker_buy_quote")
        if c in sub.columns
    ]
    sub = sub[keep_columns]
    grouped = sub.assign(_bucket=bucket[np.repeat(complete, counts)] if strict else bucket)
    bars = grouped.groupby("_bucket", sort=True).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).reset_index().rename(columns={"_bucket": "ts_event"})
    # the optional exchange columns are summed where they exist
    for column in ("quote_volume", "trades", "taker_buy_base", "taker_buy_quote"):
        if column in grouped.columns:
            bars[column] = grouped.groupby("_bucket", sort=True)[column].sum().to_numpy()
    bars["ts_event"] = bars["ts_event"].astype("int64")
    return bars, n_incomplete


def build_timeframes(
    symbol: str,
    timeframes: Sequence[str],
    *,
    base: str = "1m",
    lake_root: Path = DEFAULT_LAKE_ROOT,
    strict: bool = True,
) -> list[dict]:
    """Write one governed partition per timeframe for ``symbol``."""
    base_path = (
        lake_root
        / "crypto"
        / "futures_um"
        / symbol
        / base
        / f"{symbol}_{base}_consolidated.parquet"
    )
    if not base_path.exists():
        raise FileNotFoundError(f"{symbol}: no {base} lane at {base_path}")
    source = pd.read_parquet(base_path)
    # the lake's older lanes call the column ``timestamp`` and some carry
    # nanoseconds; the resampler speaks int64 milliseconds and ``ts_event``
    if "ts_event" not in source.columns and "timestamp" in source.columns:
        source = source.rename(columns={"timestamp": "ts_event"})
    source["ts_event"] = source["ts_event"].astype("int64")
    if int(source["ts_event"].iloc[-1]) > 10**17:
        source["ts_event"] = source["ts_event"] // 1_000_000
    source = source.sort_values("ts_event").reset_index(drop=True)
    out: list[dict] = []
    for timeframe in timeframes:
        minutes = interval_minutes(timeframe)
        if minutes == interval_minutes(base):
            bars = source.copy()
            incomplete = 0
        else:
            bars, incomplete = resample_ohlcv(
                source, minutes, base_minutes=interval_minutes(base), strict=strict
            )
        report = audit_frame(bars)
        if not report.passed:
            raise ValueError(
                f"{symbol}/{timeframe}: resampled partition fails the audit: "
                f"{report.violations}"
            )
        folder = lake_root / "crypto" / "futures_um" / symbol / timeframe
        path = folder / f"{symbol}_{timeframe}_consolidated.parquet"
        status = "written"
        max_diff = 0.0
        if path.exists():
            # An existing lane is the exchange's own aggregation: it is the
            # independent check of this resample, so it is never replaced.
            old = pd.read_parquet(path)
            if "ts_event" not in old.columns and "timestamp" in old.columns:
                old = old.rename(columns={"timestamp": "ts_event"})
            old["ts_event"] = old["ts_event"].astype("int64")
            if int(old["ts_event"].iloc[-1]) > 10**17:
                old["ts_event"] = old["ts_event"] // 1_000_000
            common = old[["ts_event", "open", "high", "low", "close", "volume"]].merge(
                bars[["ts_event", "open", "high", "low", "close", "volume"]],
                on="ts_event",
                suffixes=("_old", "_new"),
            )
            if len(common):
                for column in ("open", "high", "low", "close", "volume"):
                    delta = (
                        common[f"{column}_old"].to_numpy(dtype=float)
                        - common[f"{column}_new"].to_numpy(dtype=float)
                    )
                    if delta.size and not np.all(np.isnan(delta)):
                        max_diff = max(max_diff, float(np.nanmax(np.abs(delta))))
            if max_diff == 0.0:
                status = "identical to the existing lane"
            else:
                path = folder / f"{symbol}_{timeframe}_resampled.parquet"
                status = (
                    f"MISMATCH vs the existing lane (max |delta| = {max_diff:.6g}); "
                    "written beside it"
                )
                write_governed(bars, path)
        else:
            write_governed(bars, path)
        out.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "rows": len(bars),
                "incomplete_buckets_dropped": incomplete,
                "path": str(path),
                "status": status,
                "source": str(base_path),
            }
        )
        print(
            f"{symbol:>10} {timeframe:>4} {len(bars):>9,} bars "
            f"({incomplete:,} incomplete) {status}"
        )
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="resample", description=__doc__)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--timeframes", nargs="+", required=True)
    parser.add_argument("--base", default="1m")
    parser.add_argument("--lake-root", default=str(DEFAULT_LAKE_ROOT))
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="emit partial buckets too (NOT the lake's contract; for diagnosis only)",
    )
    args = parser.parse_args(argv)
    lake_root = Path(args.lake_root).expanduser()
    failures = 0
    for symbol in args.symbols:
        try:
            build_timeframes(
                symbol,
                args.timeframes,
                base=args.base,
                lake_root=lake_root,
                strict=not args.allow_incomplete,
            )
        except Exception as exc:  # noqa: BLE001 - the CLI reports
            failures += 1
            print(f"FAILED {symbol}: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
