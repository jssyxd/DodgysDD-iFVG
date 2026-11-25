"""The offline vision batch -- the join that makes the vision layer reachable.

The vision layer is an **offline batch feature**, not a gate (FINAL_REPORT
§5.4): rendering and running the detector over the candidate population is
far too expensive to do inside the engine (29-145 h of CPU inference for the
crypto population), so the engine writes the D2 log with the two vision
columns empty and the batch fills them afterwards.

Without this join the layer is a dead end: ``vision_iou`` and
``vision_confidence`` would never be written into the D2 log, and the ML
pipeline's optional ``vision_confidence`` feature would stay excluded for
ever (D12).

The batch is **causal**: a candidate is scored on the window that ends at its
own confirmation bar, so truncating the future cannot change a verdict.
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from dodgys_dd_quant.vision_validator.visual_cv import (
    DEFAULT_STYLE,
    Detector,
    VisionStyle,
    VisionVerdict,
    evaluate_candidate,
)

__all__ = [
    "VisionBatch",
    "evaluate_candidates",
    "apply_to_candidates",
    "side_table",
    "write_side_table",
]


@dataclass(frozen=True)
class VisionBatch:
    """The outcome of an offline vision pass over a candidate population."""

    #: One verdict per evaluated candidate, in the order they were evaluated.
    verdicts: tuple[VisionVerdict, ...]
    #: The index of the candidate each verdict belongs to.
    candidate_indices: tuple[int, ...]
    #: How long the pass took, in seconds.
    seconds: float = 0.0

    @property
    def n_evaluated(self) -> int:
        return len(self.verdicts)

    @property
    def n_passed(self) -> int:
        return sum(1 for verdict in self.verdicts if verdict.passed)

    @property
    def n_matched(self) -> int:
        return sum(1 for verdict in self.verdicts if verdict.n_detections > 0)

    def columns(self) -> dict[str, np.ndarray]:
        """The two D2 columns, in the batch's own order."""
        return {
            "vision_iou": np.asarray(
                [v.vision_iou for v in self.verdicts], dtype=np.float64
            ),
            "vision_confidence": np.asarray(
                [v.vision_confidence for v in self.verdicts], dtype=np.float64
            ),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_evaluated": self.n_evaluated,
            "n_matched": self.n_matched,
            "n_passed": self.n_passed,
            "seconds": self.seconds,
        }


def _window(bars, confirm_bar: int, window_bars: int):
    """The bars up to and including ``confirm_bar`` (the last ``window_bars``).

    ``None`` when the candidate sits before the first bar.
    """
    from dodgys_dd_quant.strategy.structure import Bars

    end = int(confirm_bar) + 1
    if end <= 0:
        return None
    start = max(0, end - int(window_bars))
    return Bars(
        ts=bars.ts[start:end],
        open=bars.open[start:end],
        high=bars.high[start:end],
        low=bars.low[start:end],
        close=bars.close[start:end],
        volume=bars.volume[start:end],
        symbol=getattr(bars, "symbol", ""),
        timeframe=getattr(bars, "timeframe", "1m"),
    )


def evaluate_candidates(
    candidates: Sequence[Any],
    bars,
    *,
    detector: Detector,
    style: VisionStyle = DEFAULT_STYLE,
    iou_threshold: float | None = None,
    limit: int | None = None,
) -> VisionBatch:
    """Score a candidate population against the detector.

    Parameters
    ----------
    candidates:
        The candidates (or D2 rows) to score.  Each needs ``confirm_bar``,
        ``fvg_oldest``, ``fvg_newest``, ``fvg_low``, ``fvg_high`` and
        ``fvg_type``.
    bars:
        The traded series.
    detector:
        The detector; a stub returning a known box exercises the whole path.
    style, iou_threshold:
        The render convention and the calibrated threshold.
    limit:
        Score at most this many candidates (the batch is expensive).
    """
    verdicts: list[VisionVerdict] = []
    indices: list[int] = []
    started = time.perf_counter()
    for index, cand in enumerate(candidates):
        if limit is not None and len(verdicts) >= int(limit):
            break
        confirm_bar = int(getattr(cand, "confirm_bar", -1))
        window = _window(bars, confirm_bar, style.window_bars)
        if window is None:
            continue
        start = max(0, confirm_bar + 1 - int(style.window_bars))
        c1_slot = int(getattr(cand, "fvg_oldest", -1)) - start
        c3_slot = int(getattr(cand, "fvg_newest", -1)) - start
        count = min(int(style.window_bars), confirm_bar + 1 - start)
        if c1_slot < 0 or c3_slot < 0 or c3_slot >= count:
            continue
        verdict = evaluate_candidate(
            window,
            c1_slot,
            c3_slot,
            float(cand.fvg_low),
            float(cand.fvg_high),
            int(cand.fvg_type),
            detector,
            style=style,
            iou_threshold=iou_threshold,
        )
        verdicts.append(verdict)
        indices.append(index)
    return VisionBatch(
        verdicts=tuple(verdicts),
        candidate_indices=tuple(indices),
        seconds=time.perf_counter() - started,
    )


def apply_to_candidates(candidates: Sequence[Any], batch: VisionBatch) -> int:
    """Write the batch's verdicts back onto the candidates.

    Returns the number of candidates that were updated.
    """
    updated = 0
    for position, index in enumerate(batch.candidate_indices):
        verdict = batch.verdicts[position]
        candidate = candidates[index]
        candidate.vision_iou = float(verdict.vision_iou)
        candidate.vision_confidence = float(verdict.vision_confidence)
        updated += 1
    return updated


def side_table(batch: VisionBatch) -> dict[str, list]:
    """The audit's **side table** (L1 §B.6): the sharper diagnostics.

    ``row_containment`` and ``bar_index_delta`` are more discriminative than
    the IoU, because they are insensitive to the annotation convention; they
    belong beside the log, not inside the frozen D2 schema.
    """
    table: dict[str, list] = {
        "candidate_index": list(batch.candidate_indices),
        "vision_iou": [],
        "vision_confidence": [],
        "vision_iou_gap": [],
        "row_containment": [],
        "bar_index_delta": [],
        "class_match": [],
        "n_detections": [],
        "passed": [],
        "image_sha256": [],
    }
    for verdict in batch.verdicts:
        table["vision_iou"].append(float(verdict.vision_iou))
        table["vision_confidence"].append(float(verdict.vision_confidence))
        table["vision_iou_gap"].append(float(verdict.vision_iou_gap))
        table["row_containment"].append(float(verdict.row_containment))
        table["bar_index_delta"].append(int(verdict.bar_index_delta))
        table["class_match"].append(bool(verdict.class_match))
        table["n_detections"].append(int(verdict.n_detections))
        table["passed"].append(bool(verdict.passed))
        table["image_sha256"].append(verdict.image_sha256)
    return table


def write_side_table(batch: VisionBatch, path: str | Path) -> Path:
    """Write the side table as a CSV file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    table = side_table(batch)
    columns = list(table)
    with target.open("wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in range(len(table[columns[0]])):
            writer.writerow([table[column][row] for column in columns])
    return target
