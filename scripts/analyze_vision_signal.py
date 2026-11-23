#!/usr/bin/env python3
"""Does the vision signal carry information about the outcome?

Joins the vision signals (from ``scripts/vision_signals.py``) with the D2
candidate log and asks the only question that matters for the layer: does a
candidate that the **detector confirms** have a different outcome from one it
does not?

Reported:
* the win rate and the mean R of the confirmed vs the unconfirmed;
* the two-proportion z-test of the win-rate difference;
* the point-biserial correlation between the IoU and the outcome;
* the same split by the detector's confidence.

Usage:
    .venv-vision/bin/python scripts/analyze_vision_signal.py \
        --candidates data/candidates/NQ_1m_pine.parquet \
        --vision data/candidates/NQ_1m_vision.parquet
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq


def two_proportion_z(x1: int, n1: int, x2: int, n2: int) -> float:
    """The z-statistic of the difference of two proportions."""
    if n1 == 0 or n2 == 0:
        return float("nan")
    p1, p2 = x1 / n1, x2 / n2
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    return (p1 - p2) / se if se > 0 else float("nan")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--vision", required=True)
    ap.add_argument("--tau-v", type=float, default=0.75)
    args = ap.parse_args(argv)

    cand = pq.read_table(args.candidates)
    vis = pq.read_table(args.vision)

    ts_c = cand.column("ts_event").to_numpy()
    label = cand.column("label").to_numpy()          # 1 = target, 0 = stop, -1 = unresolved
    r_mult = cand.column("r_multiple").to_numpy()
    order = {int(t): i for i, t in enumerate(ts_c)}

    ts_v = vis.column("ts_event").to_numpy()
    iou = vis.column("vision_iou").to_numpy()
    conf = vis.column("vision_confidence").to_numpy()
    det = vis.column("vision_detected").to_numpy()
    cls_ok = vis.column("vision_class_ok").to_numpy()

    keep = [(int(t), float(i), float(c), int(d), int(k))
            for t, i, c, d, k in zip(ts_v, iou, conf, det, cls_ok) if int(t) in order]
    if not keep:
        print("no overlap between the vision signals and the candidate log")
        return 1

    rows = []
    for t, i, c, d, k in keep:
        j = order[t]
        rows.append((i, c, d, k, int(label[j]), float(r_mult[j])))
    arr = np.array(rows, dtype=float)
    iou_a, conf_a, det_a, cls_a, label_a, r_a = arr.T

    resolved = label_a >= 0
    print(f"scored candidates joined to the log : {len(rows)}")
    print(f"  with a resolved outcome           : {int(resolved.sum())}")

    def report(name: str, mask: np.ndarray) -> None:
        m = mask & resolved
        n = int(m.sum())
        if n == 0:
            print(f"{name}: no resolved candidates")
            return
        lab = label_a[m]
        r = r_a[m]
        wins = int((lab == 1).sum())
        print(f"  {name:<34} n={n:6d}  win%={100 * wins / n:5.2f}  "
              f"E[R]={np.nanmean(r):+.4f}")

    print("\n-- by the doc's vertical-IoU gate (tau_v = "
          f"{args.tau_v}) --")
    report(f"confirmed (IoU >= {args.tau_v})", (iou_a >= args.tau_v) & (cls_a > 0))
    report("not confirmed", ~((iou_a >= args.tau_v) & (cls_a > 0)))

    confirmed = (iou_a >= args.tau_v) & (cls_a > 0) & resolved
    unconfirmed = (~((iou_a >= args.tau_v) & (cls_a > 0))) & resolved
    n1, n2 = int(confirmed.sum()), int(unconfirmed.sum())
    if n1 and n2:
        x1 = int((label_a[confirmed] == 1).sum())
        x2 = int((label_a[unconfirmed] == 1).sum())
        z = two_proportion_z(x1, n1, x2, n2)
        print(f"\n  win rate   confirmed {100 * x1 / n1:.2f}%  vs  "
              f"unconfirmed {100 * x2 / n2:.2f}%")
        print(f"  two-proportion z = {z:+.2f}   "
              f"(|z| > 1.96 is significant at 5%)")
        print(f"  E[R]       confirmed {np.nanmean(r_a[confirmed]):+.4f}  vs  "
              f"unconfirmed {np.nanmean(r_a[unconfirmed]):+.4f}")

    print("\n-- by the detector's confidence (detected boxes only) --")
    for lo, hi in ((0.0, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)):
        report(f"conf in [{lo:.1f}, {hi:.1f})", (conf_a >= lo) & (conf_a < hi) & (det_a > 0))

    # the point-biserial correlation between the IoU and the outcome
    m = resolved & (det_a > 0)
    if m.sum() > 2:
        x = iou_a[m]
        y = label_a[m]
        r_pb = float(np.corrcoef(x, y)[0, 1])
        print(f"\n  point-biserial corr(IoU, outcome) = {r_pb:+.4f}  (n={int(m.sum())})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
