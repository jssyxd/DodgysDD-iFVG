#!/usr/bin/env python3
"""Run the vision cross-validation over the D2 candidate log.

For every candidate the window of ``WINDOW_BARS`` candles **ending at the
gap's third bar** is rendered in the detector's training style, the detector
is run over it, and its box is scored against the rule engine's third candle
(D4 hybrid — see ``research/analysis/VISION_AUDIT.md`` §C.2).

The output is a parquet of one row per candidate:
``ts_event, vision_iou, vision_confidence, vision_box_iou, vision_gap_iou,
vision_matched_bar, vision_detected, vision_pass``.

This script needs the vision stack (``torch``, ``ultralytics``, ``PIL``); run
it with ``.venv-vision/bin/python``, not with the runtime interpreter.

Usage:
    .venv-vision/bin/python scripts/vision_signals.py \
        --candidates data/candidates/NQ_1m_pine.parquet \
        --bars ~/iflow_lake/.../NQ/1m/NQ_1m.parquet \
        --out data/candidates/NQ_1m_vision.parquet --limit 500
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dodgys_dd_quant.vision_validator.visual_cv import (  # noqa: E402
    WINDOW_BARS,
    detect,
    render_window,
    score_detections,
)

DEFAULT_MODEL = "research/huggingface/nq-fvg-detector/best.pt"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--bars", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--stride", type=int, default=1,
                    help="sample every Nth candidate, so a run spans the whole sample")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--tau-v", type=float, default=0.75,
                    help="the doc's vertical IoU gate (iFVG几个模型的讨论.txt L279)")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--skip-existing", default=None,
                    help="an earlier signal parquet; rows whose (fvg_bar3, confirm_bar) "
                         "is already scored there are skipped. The vision score depends "
                         "only on that key and the bars, so a cached value stays valid "
                         "even when the candidate set changes.")
    args = ap.parse_args(argv)

    cand = pq.read_table(args.candidates)
    bars_tbl = pq.read_table(args.bars)
    bars_ts = bars_tbl.column("timestamp").to_numpy()
    o = bars_tbl.column("open").to_numpy()
    h = bars_tbl.column("high").to_numpy()
    lo = bars_tbl.column("low").to_numpy()
    c = bars_tbl.column("close").to_numpy()

    ts_event = cand.column("ts_event").to_numpy()
    fvg_bar1 = cand.column("fvg_bar1").to_numpy()
    fvg_bar3 = cand.column("fvg_bar3").to_numpy()
    fvg_low = cand.column("fvg_low").to_numpy()
    fvg_high = cand.column("fvg_high").to_numpy()
    fvg_type = cand.column("side").to_numpy()      # the trade side = -gap direction
    confirm = cand.column("confirm_bar").to_numpy()

    done: set = set()
    if args.skip_existing:
        prev = pq.read_table(args.skip_existing)
        done = {(int(g), int(c)) for g, c in zip(prev.column("fvg_bar3").to_numpy(),
                                                 prev.column("confirm_bar").to_numpy())}
        print(f"skip-existing: {len(done):,} keys already scored")

    n = len(ts_event)
    order = np.arange(args.offset, min(n, args.offset + args.limit) if args.limit else n,
                     step=args.stride)

    rows = []
    t0 = time.time()
    skipped = 0
    for i in order:
        i3 = int(fvg_bar3[i])
        if done and (i3, int(confirm[i])) in done:
            skipped += 1
            continue
        i1 = int(fvg_bar1[i])
        start = i3 - WINDOW_BARS + 1
        if start < 0:
            continue
        # the window must be contiguous in time and land on the lake's bars
        if int(bars_ts[i3]) - int(bars_ts[start]) != (WINDOW_BARS - 1) * 60_000:
            continue
        png, transform = render_window(h[start : i3 + 1], lo[start : i3 + 1],
                                       o[start : i3 + 1], c[start : i3 + 1])
        dets = detect(png, args.model, conf=args.conf)
        # the gap's price interval (the doc's metric) and the third candle's body
        gl, gh = float(fvg_low[i]), float(fvg_high[i])
        gap_rows = (transform.y(gh), transform.y(gl))
        body_rows = (transform.y(max(o[i3], c[i3])), transform.y(min(o[i3], c[i3])))
        score = score_detections(
            dets,
            transform,
            fvg_type=-int(fvg_type[i]),          # the gap's own direction
            fvg_bars=(i1 - start, i1 + 1 - start, i3 - start),
            gap_rows=gap_rows,
            body_rows=body_rows,
            tau_v=args.tau_v,
        )
        rows.append(
            {
                "ts_event": int(ts_event[i]),
                "fvg_bar3": i3,
                "confirm_bar": int(confirm[i]),
                "n_detections": len(dets),
                **score,
            }
        )
        if len(rows) % 25 == 0:
            rate = (time.time() - t0) / len(rows)
            print(f"  {len(rows)} scored  {rate:.2f} s/candidate  "
                  f"eta {(len(order) - len(rows)) * rate / 60:.1f} min", flush=True)

    if not rows:
        print("no candidate could be rendered")
        return 1

    table = pa.Table.from_pylist(rows)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out, compression="zstd", compression_level=7)

    det_rate = float(np.mean([r["vision_detected"] for r in rows]))
    pass_rate = float(np.mean([r["vision_pass"] for r in rows]))
    ious = [r["vision_iou"] for r in rows if r["vision_detected"]]
    print(f"[SAVED] {out} ({len(rows)} rows, {skipped:,} skipped as already scored)")
    print(f"  a box landed on the gap's bars         : {det_rate:.1%}")
    print(f"  class == the gap's direction           : "
          f"{float(np.mean([r['vision_class_ok'] for r in rows if r['vision_detected']])):.1%}"
          if det_rate else "n/a")
    print(f"  vertical IoU >= {args.tau_v} (the doc's gate): {pass_rate:.1%}")
    if ious:
        print(f"  vertical IoU (when detected) median    : {np.median(ious):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
