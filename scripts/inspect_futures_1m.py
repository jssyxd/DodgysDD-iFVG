#!/usr/bin/env python3
"""Inspect the fetched NQ/ES 1-minute futures series and report what they are.

The questions this answers, because the design doc needs a **roll rule** and we
must not guess:

1. What are the columns, the timestamp unit and the timezone?
2. Is the series **continuous** (already rolled by the publisher) or per-contract /
   a naive front-month splice? A continuous series has synthetic price gaps at the
   roll, and a roll gap prints exactly like a liquidity sweep — so it must be
   detected and masked before any iFVG logic runs.
3. Where are the roll boundaries, and how big are the gaps?
4. Is there a session break (the 17:00-18:00 ET maintenance window) that would
   otherwise look like a continuous series?

Usage
-----
    python scripts/inspect_futures_1m.py --root research/hf_futures
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pyarrow.parquet as pq


def describe(path: Path, label: str) -> None:
    print(f"\n===== {label}: {path.name} =====")
    t = pq.read_table(path)
    print(f"rows={t.num_rows:,}  cols={t.column_names}")
    d = t.to_pylist()
    if not d:
        print("EMPTY")
        return
    for k, v in d[0].items():
        print(f"   {k:24} {type(v).__name__:10} {str(v)[:44]}")
    print("   first:", {k: str(v)[:26] for k, v in d[0].items()})
    print("   last :", {k: str(v)[:26] for k, v in d[-1].items()})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="research/hf_futures")
    args = ap.parse_args()
    root = Path(args.root)

    for p in sorted(root.glob("NQ/*.parquet"))[:2] + sorted(root.glob("NQ/*.parquet"))[-1:]:
        describe(p, "NQ")
    for p in sorted(root.glob("ES/*.parquet"))[:1]:
        describe(p, "ES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
