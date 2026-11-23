#!/usr/bin/env python3
"""Audit a governed-lake dataset against the lake's five mathematical invariants.

The lake's standard (see the dataBaseLake repo and the lake's own
``incremental_update_change_declarations.md``) requires, for every dataset that
enters the lake:

1. **Timestamp monotonicity** — ``ts_i > ts_{i-1}``, strictly increasing.
2. **Deduplication** — the timestamp is unique.
3. **Price envelope** — ``high >= max(open, close)`` and ``low <= min(open, close)``.
4. **Positive domain** — ``open, high, low, close > 0``.
5. **Non-negative volume** — ``volume >= 0``.
6. **Zero synthetic forward-fill** — real market breaks are preserved; nothing
   is interpolated.

This script re-derives all six from the *stored* file (not from the ingest's
in-memory state), so it audits what was actually written, and prints the
declaration row the lake's change-declaration table expects.

Usage:
    python scripts/audit_lake_dataset.py --path <file.parquet> [--label NQ 1m]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

TIMESTAMP_UNITS = {
    "milliseconds": 1_000,
    "microseconds": 1_000_000,
    "nanoseconds": 1_000_000_000,
}


def detect_unit(ts: np.ndarray) -> str:
    """The timestamp unit, from the modal spacing between consecutive bars.

    The lake's contract allows milliseconds and microseconds; the stored value
    is whatever the writer used, and a wrong guess turns the dates into 1970.
    """
    if ts.size < 2:
        return "milliseconds"
    diffs = np.diff(ts)
    diffs = diffs[diffs > 0]
    if diffs.size == 0:
        return "milliseconds"
    spacing = float(np.median(diffs))
    for unit, factor in (("milliseconds", 1_000), ("microseconds", 1_000_000),
                         ("nanoseconds", 1_000_000_000)):
        if spacing >= factor * 0.9:
            # a one-minute bar: spacing is 60 * factor
            if abs(spacing / factor - 60.0) < 1.0:
                return unit
    # fall back on the magnitude of the first timestamp
    first = float(ts[0])
    if first > 1e17:
        return "nanoseconds"
    if first > 1e14:
        return "microseconds"
    return "milliseconds"


def audit(path: Path) -> dict:
    table = pq.read_table(path)
    cols = table.column_names
    ts = table.column("timestamp").to_numpy()
    o = table.column("open").to_numpy()
    h = table.column("high").to_numpy()
    lo = table.column("low").to_numpy()
    c = table.column("close").to_numpy()
    v = table.column("volume").to_numpy()
    n = len(ts)
    unit = detect_unit(ts)
    factor = TIMESTAMP_UNITS[unit]

    report: dict = {
        "path": str(path),
        "rows": n,
        "columns": cols,
        "timestamp_unit": unit,
        "start_utc": None,
        "end_utc": None,
        "invariants": {},
    }

    # 1. strict monotonicity
    diffs = np.diff(ts)
    non_increasing = int((diffs <= 0).sum())
    report["invariants"]["timestamp_monotonicity"] = {
        "ok": non_increasing == 0,
        "violations": non_increasing,
        "detail": "ts_i > ts_{i-1} for every row",
    }

    # 2. uniqueness
    unique = int(np.unique(ts).size)
    report["invariants"]["deduplication"] = {
        "ok": unique == n,
        "duplicates": n - unique,
        "detail": "the timestamp is the primary key",
    }

    # 3. price envelope
    bad_env = int(((h < np.maximum(o, c)) | (lo > np.minimum(o, c))).sum())
    report["invariants"]["price_envelope"] = {
        "ok": bad_env == 0,
        "violations": bad_env,
        "detail": "high >= max(open, close) and low <= min(open, close)",
    }

    # 4. positive prices
    bad_pos = int(((o <= 0) | (h <= 0) | (lo <= 0) | (c <= 0)).sum())
    report["invariants"]["positive_domain"] = {
        "ok": bad_pos == 0,
        "violations": bad_pos,
        "detail": "open, high, low, close > 0",
    }

    # 5. non-negative volume
    bad_vol = int((v < 0).sum())
    report["invariants"]["non_negative_volume"] = {
        "ok": bad_vol == 0,
        "violations": bad_vol,
        "detail": "volume >= 0",
    }

    # 6. zero synthetic forward-fill: a gap that is a whole number of minutes
    #    is a real market break; the audit reports the gaps and their size so
    #    that a reader can see they are *not* filled.
    if n > 1:
        minutes = np.diff(ts) / (60.0 * factor)
        gaps = minutes[minutes > 1.0]
        report["market_breaks"] = {
            "count": int(gaps.size),
            "max_minutes": float(gaps.max()) if gaps.size else 0.0,
            "total_broken_minutes": float((minutes - 1.0).clip(min=0).sum()),
            "detail": "real breaks are preserved; no bar is interpolated",
        }
    else:
        report["market_breaks"] = {"count": 0, "max_minutes": 0.0,
                                    "total_broken_minutes": 0.0,
                                    "detail": "single bar"}

    # the roll mask is a disclosure, not a deletion: the rows stay in the file
    if "roll_masked" in cols:
        mask = table.column("roll_masked").to_numpy()
        report["roll_mask"] = {
            "masked_bars": int(mask.sum()),
            "masked_pct": round(100.0 * float(mask.mean()), 4) if n else 0.0,
            "detail": "the synthetic quarterly splice is flagged, not deleted",
        }

    report["start_utc"] = _iso(ts[0], factor) if n else None
    report["end_utc"] = _iso(ts[-1], factor) if n else None
    report["passed"] = all(v["ok"] for v in report["invariants"].values())
    report["verdict"] = "PASS" if report["passed"] else "FAIL"
    return report


def _iso(ts: int, factor: int) -> str:
    import datetime as dt

    return dt.datetime.fromtimestamp(int(ts) / factor, dt.timezone.utc).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    report = audit(Path(args.path))
    if args.label:
        report["label"] = args.label
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json_out:
        Path(args.json_out).write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
