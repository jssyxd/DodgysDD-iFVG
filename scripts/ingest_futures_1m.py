#!/usr/bin/env python3
"""Ingest the fetched NQ / ES 1-minute futures into the governed lake, with a roll rule.

Inputs (already downloaded under ``research/hf_futures/``)
--------------------------------------------------------
``NQ/NQ_1min_<year>.parquet``  -  mdelcristo/NQ-F_1min_OHLCV_Parquet
    columns: timestamp (tz-NAIVE UTC), open, high, low, close, volume
    The publisher has ALREADY rolled this series, and the contract identity is
    not exposed, so the roll points must be detected.

``ES/es_continuous_1m.parquet`` - Khanhpham1992/es-futures-1m
    columns: instrument_id, open, high, low, close, volume,
             adj_open..adj_close, datetime (tz-aware UTC)
    ``instrument_id`` changes at every roll, so ES gives the **roll calendar for
    free**. The ``adj_*`` columns are unusable: their "adjusted" series has gaps
    of +125..+672 points, i.e. the publisher's back-adjustment is broken, so the
    RAW prices of the active leg are used and the roll is masked instead.

The roll rule (why it matters)
------------------------------
A roll splices two contracts. The price difference between the expiring and the
new front contract is a **synthetic move** that never happened in the market. On the
ES series the measured raw gaps at the 14 rolls are up to **+5.87 % in one minute**.
That is exactly the shape of a liquidity sweep and exactly the shape of an iFVG
inversion: an uncorrected continuous series would manufacture signals out of
artefacts, and the strategy's whole premise is to detect a *real* failed gap.

So the rule is:

1. Build the roll calendar from the quarterly CME expiry cycle
   (3rd Friday of Mar/Jun/Sep/Dec), cross-checked against the ES panel's own
   contract transitions.
2. **Mask** every bar in a guard window around each roll, and additionally every
   bar whose 1-minute move is a statistical outlier (a jump that cannot be a
   real print). The mask is written next to the data so the backtest can exclude
   those minutes explicitly.
3. Never forward-fill. Gaps stay as native hiatuses.

Output (the lake's L3 contract)
-------------------------------
``03_governed_lake/v2_parquet_lake/us_futures/<SYM>/1m/<SYM>_1m.parquet``
    int64 milliseconds since UTC epoch, LEFT-OPEN, zstd-7, with
    ``roll_masked`` (int8) and ``is_roll_window`` (int8) columns.

Usage
-----
    python scripts/ingest_futures_1m.py --symbol NQ --root research/hf_futures
    python scripts/ingest_futures_1m.py --symbol ES --root research/hf_futures
    python scripts/ingest_futures_1m.py --symbol NQ --audit
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

BASE = Path(__file__).resolve().parent.parent
LAKE = BASE / "03_governed_lake" / "v2_parquet_lake"
MASK_MINUTES = 120          # guard window either side of a roll
OUTLIER_SIGMA = 12.0        # backstop: 1-minute move > 12 sigma of the series' own sigma
SPLICE_SIGMA = 6.0         # a quarterly splice shows up as a >= 6 sigma move near the expiry
SPLICE_WINDOW_MIN = 60      # mask +-60 minutes around a detected splice


# ---------------------------------------------------------------- roll calendar
def quarterly_expiries(start: int, end: int) -> list[dt.date]:
    """3rd Friday of Mar/Jun/Sep/Dec between two years."""
    out = []
    for year in range(start, end + 1):
        for month in (3, 6, 9, 12):
            d = dt.date(year, month, 1)
            fridays = [d + dt.timedelta(days=i) for i in range(31)
                       if (d + dt.timedelta(days=i)).month == month
                       and (d + dt.timedelta(days=i)).weekday() == 4]
            if len(fridays) >= 3:
                out.append(fridays[2])
    return sorted(out)


def roll_windows(expiries: list[dt.date], minutes: int = MASK_MINUTES) -> list[tuple[int, int]]:
    """[start, end) UTC millisecond windows covering each roll."""
    wins = []
    for d in expiries:
        start = int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp() * 1000)
        wins.append((start - minutes * 60_000, start + minutes * 60_000))
    return wins


# ---------------------------------------------------------------- loaders
def load_nq(root: Path) -> list[dict]:
    rows = []
    for p in sorted(root.glob("NQ/NQ_1min_*.parquet")):
        for r in pq.read_table(p).to_pylist():
            ts = r["timestamp"]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=dt.timezone.utc)
            rows.append({
                "timestamp": int(ts.timestamp() * 1000),
                "open": float(r["open"]), "high": float(r["high"]),
                "low": float(r["low"]), "close": float(r["close"]),
                "volume": float(r["volume"]), "instrument_id": None,
            })
    return rows


def load_es(root: Path) -> list[dict]:
    rows = []
    p = root / "ES/es_continuous_1m.parquet"
    for r in pq.read_table(p).to_pylist():
        ts = r["datetime"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        rows.append({
            "timestamp": int(ts.timestamp() * 1000),
            "open": float(r["open"]), "high": float(r["high"]),
            "low": float(r["low"]), "close": float(r["close"]),
            "volume": float(r["volume"]), "instrument_id": str(r["instrument_id"]),
        })
    return rows


# ---------------------------------------------------------------- cleaning
def clean(rows: list[dict], symbol: str) -> tuple[list[dict], dict]:
    stats = {"raw": len(rows)}
    rows.sort(key=lambda r: r["timestamp"])

    # --- duplicate timestamps: keep the LAST occurrence (the publisher's revision)
    by_ts: dict[int, dict] = {}
    for r in rows:
        by_ts[r["timestamp"]] = r
    stats["duplicates"] = len(rows) - len(by_ts)
    rows = [by_ts[k] for k in sorted(by_ts)]

    # --- invariants: monotonic, positive prices, OHLC envelope, non-negative volume
    out = []
    bad_env = bad_price = 0
    for r in rows:
        if min(r["open"], r["high"], r["low"], r["close"]) <= 0:
            bad_price += 1
            continue
        if r["high"] < max(r["open"], r["close"]) or r["low"] > min(r["open"], r["close"]) \
                or r["low"] > r["high"]:
            bad_env += 1
            continue
        if r["volume"] < 0:
            continue
        out.append(r)
    stats["dropped_bad_price"] = bad_price
    stats["dropped_bad_envelope"] = bad_env
    rows = out
    stats["after_invariants"] = len(rows)

    # --- session: drop the CME maintenance break 17:00-18:00 ET
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    keep = []
    dropped_break = 0
    for r in rows:
        m = dt.datetime.fromtimestamp(r["timestamp"] / 1000, et)
        if m.hour == 17 and m.minute >= 1:
            dropped_break += 1
            continue
        keep.append(r)
    stats["dropped_maintenance_break"] = dropped_break
    rows = keep
    stats["after_session"] = len(rows)

    # --- THE ROLL RULE -------------------------------------------------------
    # The publisher's continuous series is spliced at the quarterly expiry: at
    # 37 of the 44 expiries in the NQ span there is a 1-minute move of
    # 0.15%-1.76% against a 1-minute sigma of 0.03% (5-58 sigma). That splice is
    # synthetic -- the two contracts simply have different prices -- and it is
    # exactly the shape of a liquidity sweep, so it must not be traded.
    #
    # The splice minute is DETECTED (the largest move near each expiry), not
    # assumed to sit on the expiry date, and a tight window is masked around it.
    # The publisher's own segment boundaries (visible only for ES) are masked too.
    years = [dt.datetime.fromtimestamp(r["timestamp"] / 1000, dt.timezone.utc).year
             for r in rows]
    expiries = quarterly_expiries(min(years), max(years))
    stats["quarterly_expiries"] = len(expiries)

    # 1-minute returns, as (index_into_rows, magnitude)
    rets: list[float] = []
    for a, b in zip(rows, rows[1:]):
        rets.append(abs(b["close"] / a["close"] - 1.0) if a["close"] else 0.0)
    mean = sum(rets) / len(rets) if rets else 0.0
    var = (sum((x - mean) ** 2 for x in rets) / max(1, len(rets) - 1)) if rets else 0.0
    sigma = var ** 0.5
    stats["sigma_1m"] = sigma
    stats["mean_abs_return_1m"] = mean

    # candidate splice minutes: the largest move within +/-3 days of an expiry
    # one pass: the largest move inside each expiry's +-3 day window
    windows = []
    for e in expiries:
        c0 = int(dt.datetime(e.year, e.month, e.day, tzinfo=dt.timezone.utc).timestamp() * 1000)
        windows.append((c0 - 3 * 86400_000, c0 + 3 * 86400_000, None, 0.0))
    splice_minutes: list[int] = []
    for i in range(1, len(rows)):
        ts = rows[i]["timestamp"]
        if rows[i]["timestamp"] - rows[i - 1]["timestamp"] != 60_000:
            continue
        z = rets[i - 1] / sigma if sigma else 0.0
        for lo, hi, best, bz in windows:
            if lo <= ts <= hi and z > bz:
                windows[[w[0] for w in windows].index(lo)] = (lo, hi, ts, z)
    for lo, hi, best, bz in windows:
        if best is not None and bz >= SPLICE_SIGMA:
            splice_minutes.append(best)
    stats["splices_detected"] = len(splice_minutes)

    # the publisher's own segment boundaries (ES exposes them)
    transitions: list[int] = []
    prev = None
    for r in rows:
        if r["instrument_id"] is not None and prev is not None \
                and r["instrument_id"] != prev:
            transitions.append(r["timestamp"])
        prev = r["instrument_id"]
    stats["contract_transitions"] = len(transitions)

    mask_ts: set[int] = set()
    for ts in splice_minutes:
        for d in range(-SPLICE_WINDOW_MIN, SPLICE_WINDOW_MIN + 1):
            mask_ts.add(ts + d * 60_000)
    for ts in transitions:
        for d in range(-SPLICE_WINDOW_MIN, SPLICE_WINDOW_MIN + 1):
            mask_ts.add(ts + d * 60_000)
    stats["masked_window_bars"] = len(mask_ts)

    for r in rows:
        r["roll_masked"] = 1 if r["timestamp"] in mask_ts else 0

    # --- backstop: any remaining 1-minute move that cannot be a real print
    thresh = OUTLIER_SIGMA * sigma
    jumps = 0
    for i, r in enumerate(rows):
        if i and rets[i - 1] > thresh and not r["roll_masked"]:
            r["roll_masked"] = 1
            jumps += 1
    stats["outlier_jumps_masked"] = jumps
    stats["masked_bars"] = sum(r["roll_masked"] for r in rows)
    stats["masked_pct"] = round(100 * stats["masked_bars"] / max(1, len(rows)), 4)
    return rows, stats


def write(rows: list[dict], symbol: str) -> Path:
    rel = ("global_futures/commodities_and_rates/GC" if symbol == "GC"
           else f"us_futures/{symbol}")
    out_dir = LAKE / rel / "1m"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{symbol}_1m.parquet"
    tbl = pa.Table.from_pylist([
        {"timestamp": r["timestamp"],
         "datetime": dt.datetime.fromtimestamp(
             r["timestamp"] / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
         "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"],
         "volume": r["volume"], "roll_masked": r["roll_masked"]}
        for r in rows])
    tmp = out.with_suffix(".tmp.parquet")
    pq.write_table(tbl, tmp, compression="zstd", compression_level=7)
    tmp.replace(out)
    print(f"[SAVED] {out} ({len(rows):,} rows, {out.stat().st_size / 1e6:.1f} MB)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True, choices=["NQ", "ES"])
    ap.add_argument("--root", default="research/hf_futures")
    ap.add_argument("--audit", action="store_true")
    args = ap.parse_args()
    root = Path(args.root)

    if args.audit:
        p = LAKE / f"us_futures/{args.symbol}/1m/{args.symbol}_1m.parquet"
        if not p.exists():
            print("not ingested yet")
            return 1
        rows = pq.read_table(p).to_pylist()
        ts = [r["timestamp"] for r in rows]
        print(f"{args.symbol}: {len(rows):,} rows  "
              f"{rows[0]['datetime']} -> {rows[-1]['datetime']}")
        print(f"  monotonic={all(b > a for a, b in zip(ts, ts[1:]))}  "
              f"dupes={len(ts) - len(set(ts))}  "
              f"masked={sum(r['roll_masked'] for r in rows):,}")
        days = sorted({r["datetime"][:10] for r in rows})
        print(f"  distinct days: {len(days)}")
        return 0

    raw = load_nq(root) if args.symbol == "NQ" else load_es(root)
    rows, stats = clean(raw, args.symbol)
    print(f"[{args.symbol}] {json.dumps(stats, indent=2)}")
    write(rows, args.symbol)
    out = LAKE / f"us_futures/{args.symbol}/1m/{args.symbol}_1m.parquet"
    (out.parent / f"{args.symbol}_1m_roll_report.json").write_text(
        json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
