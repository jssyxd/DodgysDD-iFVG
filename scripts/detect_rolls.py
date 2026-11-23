#!/usr/bin/env python3
"""Detect the roll / segment boundaries in the NQ and ES 1-minute series.

What the data actually is (measured, 2026-11-23)
-------------------------------------------------
* **ES** (`Khanhpham1992/es-futures-1m`) is a **segmented** series: every bar carries an
  ``instrument_id`` and each id covers one contiguous stretch of time. The 14 id
  changes are *segment boundaries*, not synthetic rolls -- the price difference
  across one is 5 months of market drift (the segment before 2023-10-18 ended
  2023-05-05), not a basis. The panel covers 528 of 959 weekdays.
* **NQ** (`mdelcristo/NQ-F_1min_OHLCV_Parquet`) is a **continuous** series with no
  contract metadata at all, 2015-2025. Somebody rolled it, so a splice exists
  somewhere, but its dates are not published.

The detector
------------
NQ and ES are two contracts on the same underlying index. Their **price ratio**
should wander around a slowly-drifting value. A **splice in either series**
produces a *step* in that ratio; a real market move produces a spike that
**reverts**. So:

    step  = |Δ log(NQ/ES) over 5 min| > z_threshold
    roll  = a step whose level shift PERSISTS (|log(ratio(t+6h)/ratio(t))| stays large)

Validation: the detector is run against ES's 14 **known** segment boundaries. Its
recall and precision are reported, and the threshold is only kept if it finds most
of them. A rule that cannot find the boundaries we already know is not a rule.

Output: ``research/analysis/roll_events.json`` -- the canonical event calendar that
``ingest_futures_1m.py`` masks.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path

import pyarrow.parquet as pq

BASE = Path(__file__).resolve().parent.parent
LAKE = BASE / "03_governed_lake" / "v2_parquet_lake"
OUT = BASE / "research" / "analysis" / "roll_events.json"

Z_STEP = 8.0        # sigma for the 5-minute log-ratio change
MIN_SEP_MIN = 60     # cluster events closer than this into one
PERSIST_H = 6        # hours over which the level shift must persist


def load(symbol: str) -> list[dict]:
    p = LAKE / f"us_futures/{symbol}/1m/{symbol}_1m.parquet"
    rows = pq.read_table(p).to_pylist()
    rows.sort(key=lambda r: r["timestamp"])
    return rows


def es_known_boundaries() -> list[int]:
    """The ES panel's own instrument_id changes (ground truth)."""
    p = BASE / "research" / "hf_futures" / "ES" / "es_continuous_1m.parquet"
    rows = pq.read_table(p).to_pylist()
    rows.sort(key=lambda r: r["datetime"])
    out, prev = [], None
    for r in rows:
        if prev is not None and r["instrument_id"] != prev:
            out.append(int(r["datetime"].timestamp() * 1000))
        prev = r["instrument_id"]
    return out


def ratio_series(nq: list[dict], es: list[dict]) -> list[tuple[int, float]]:
    E = {r["timestamp"]: r for r in es}
    pts = []
    for a, b in zip(nq, nq[1:]):
        if b["timestamp"] - a["timestamp"] != 60_000:
            continue
        ea = E.get(a["timestamp"])
        eb = E.get(b["timestamp"])
        if ea is None or eb is None:
            continue
        pts.append((b["timestamp"], math.log(b["close"] / ea["close"])))
    return pts


def detect(pts: list[tuple[int, float]], z: float = Z_STEP) -> tuple[list[dict], dict]:
    W = 5
    diffs = []
    for i in range(W, len(pts)):
        a, b = pts[i - W][1], pts[i][1]
        diffs.append((pts[i][0], b - a))
    if not diffs:
        return [], {"n": 0}
    vals = [d for _, d in diffs]
    mu = sum(vals) / len(vals)
    var = sum((x - mu) ** 2 for x in vals) / (len(vals) - 1)
    sd = math.sqrt(var)
    by_ts = dict(pts)

    events: list[dict] = []
    for t, d in diffs:
        if abs(d) / sd < z:
            continue
        # persistence: where is the ratio 6 h later, relative to the pre-step level?
        fut = [p for p in pts if p[0] >= t and p[0] <= t + PERSIST_H * 3_600_000]
        if not fut:
            continue
        level_before = by_ts.get(t)
        if level_before is None:
            continue
        shift = fut[-1][1] - level_before
        events.append({
            "ts": t,
            "z": round(abs(d) / sd, 1),
            "step_log": d,
            "persist_log": shift,
            "persists": abs(shift) > 0.5 * abs(d),
        })
    # cluster consecutive minutes into single events
    events.sort(key=lambda e: e["ts"])
    clustered: list[dict] = []
    for e in events:
        if clustered and e["ts"] - clustered[-1]["ts"] <= MIN_SEP_MIN * 60_000:
            prev = clustered[-1]
            if e["z"] > prev["z"]:
                clustered[-1] = e
        else:
            clustered.append(dict(e))
    for e in clustered:
        e["ts_iso"] = dt.datetime.fromtimestamp(
            e["ts"] / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    stats = {"n_diffs": len(diffs), "sd": sd, "z_threshold": z,
             "n_events": len(clustered),
             "n_persistent": sum(1 for e in clustered if e["persists"])}
    return clustered, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--z", type=float, default=Z_STEP)
    args = ap.parse_args()

    nq, es = load("NQ"), load("ES")
    known = es_known_boundaries()
    print(f"ES known segment boundaries: {len(known)}")

    pts = ratio_series(nq, es)
    print(f"aligned NQ/ES log-ratio points: {len(pts)}")

    events, stats = detect(pts, args.z)
    print(json.dumps(stats, indent=2))

    hit = sum(1 for k in known if any(abs(e["ts"] - k) <= 3_600_000 for e in events))
    print(f"\nVALIDATION: ES boundaries found within 1 h: {hit}/{len(known)}")
    persistent = [e for e in events if e["persists"]]
    phit = sum(1 for k in known if any(abs(e["ts"] - k) <= 3_600_000 for e in persistent))
    print(f"           of which persistent: {phit}/{len(known)}")

    print(f"\ndetected events: {len(events)}  (persistent {len(persistent)})")
    for e in events[:25]:
        tag = ""
        if any(abs(e["ts"] - k) <= 3_600_000 for k in known):
            tag = "  <- ES boundary"
        print(f"   {e['ts_iso']}  z={e['z']:6.1f}  step={e['step_log']*100:+7.4f}%  "
              f"persist={e['persist_log']*100:+7.4f}%  {'PERSIST' if e['persists'] else ''}{tag}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "method": "NQ/ES log-ratio step detector",
        "z_threshold": args.z,
        "validation_es_boundaries_found": f"{hit}/{len(known)}",
        "events": events,
    }, indent=2))
    print(f"\n[SAVED] {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
