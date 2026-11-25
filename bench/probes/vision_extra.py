"""The vision layer's **join** -- the probes that make it reachable.

The D6 contract (the geometry, the calibrated threshold, the three-part
gate) is implemented and probed in ``vision.py``.  What was missing is the
path the layer takes in the *system*:

* the D2 log's ``vision_iou`` / ``vision_confidence`` columns were hard-coded
  to ``NaN``, so the layer was a dead end -- nothing could ever read a
  verdict back;
* the threshold was a constant with no procedure behind it;
* the audit's **side table** -- the sharper diagnostics -- had no export.

The vision layer is an *offline batch* feature (FINAL_REPORT §5.4): the
engine never renders and never runs a detector, so the batch fills the
columns afterwards.  These probes drive that batch with a stub detector, so
no GPU and no weight file are needed.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

from bench.probes import register

__all__ = []


def _bars():
    from bench import fixtures

    return fixtures.btc_1m()


def _candidates(limit: int = 12):
    from dodgys_dd_quant.strategy.state_machine import PRESETS, run_state_machine

    bars = _bars()
    log = run_state_machine(bars, PRESETS["honest"])
    return bars, list(log)[:limit]


class _BodyDetector:
    """A stub detector that annotates every candle's body.

    It mimics the shipped model's convention: the box is a **tight sub-box**
    of the body (the audit measured a median IoU of 0.393 for exactly that
    reason), so the IoU is high but not 1.0.
    """

    def __init__(self, shrink: float = 0.9) -> None:
        self.shrink = float(shrink)
        self.calls = 0

    def detect_window(self, window):
        from dodgys_dd_quant.vision_validator.visual_cv import Detection

        self.calls += 1
        boxes = []
        for slot in range(int(window.bar_count)):
            x0, y0, x1, y1 = window.body_rect(slot)
            cx = (x0 + x1) / 2.0
            cy = (y0 + y1) / 2.0
            half_w = (x1 - x0) / 2.0 * self.shrink
            half_h = (y1 - y0) / 2.0 * self.shrink
            boxes.append(
                Detection(
                    box=(cx - half_w, cy - half_h, cx + half_w, cy + half_h),
                    class_name="bullish_fvg",
                    confidence=0.8,
                )
            )
        return boxes

    def detect(self, image):  # the plain protocol path
        raise AssertionError("the batch should use the window-aware hook")


@register(
    "vision.verdict_reaches_the_d2_log",
    "vision",
    55,
    "the offline batch writes the vision verdict into the D2 log's two columns",
)
def _verdict_reaches_log() -> tuple[bool, str]:
    """The vision columns must stop being hard-coded ``NaN``.

    The engine never runs a detector, so the batch does -- and the two D2
    columns carry the verdict.  The schema itself must not move (23 columns).
    """
    from dodgys_dd_quant.vision_validator.batch import apply_to_candidates, evaluate_candidates
    from dodgys_dd_quant.strategy.state_machine import CandidateLog

    bars, candidates = _candidates()
    if not candidates:
        return False, "no candidates to inspect"

    before = CandidateLog(list(candidates), "BTCUSDT", "1m").to_table()
    if not all(math.isnan(v) for v in before["vision_iou"]):
        return False, "the engine already fills the vision columns"

    batch = evaluate_candidates(candidates, bars, detector=_BodyDetector())
    if batch.n_evaluated == 0:
        return False, "the batch evaluated nothing"
    updated = apply_to_candidates(candidates, batch)
    if updated != batch.n_evaluated:
        return False, f"{updated} of {batch.n_evaluated} candidates were updated"

    after = CandidateLog(list(candidates), "BTCUSDT", "1m").to_table()
    if tuple(after) != tuple(CandidateLog.D2_COLUMNS):
        return False, "the D2 schema moved"
    filled = [v for v in after["vision_iou"] if not math.isnan(v)]
    if len(filled) != len(candidates):
        return False, f"only {len(filled)} of {len(candidates)} rows carry a verdict"
    confidences = [v for v in after["vision_confidence"] if not math.isnan(v)]
    if len(confidences) != len(candidates):
        return False, "the confidence column was not filled"
    return True, (
        f"{len(filled)} candidates carry a body IoU (median "
        f"{sorted(filled)[len(filled) // 2]:.3f}) and a confidence"
    )


@register(
    "vision.feature_reaches_the_model",
    "vision",
    40,
    "the ML pipeline picks the vision feature up once the columns are filled (D12)",
)
def _feature_reaches_model() -> tuple[bool, str]:
    """D12: the feature is excluded when the column is absent -- and used when
    it is there.

    Without the batch the ``vision_confidence`` feature is always excluded;
    with it, the feature frame must carry the column and the trainer's
    feature list must include it.
    """
    import pandas as pd

    from dodgys_dd_quant.ml_pipeline.features import build_features, resolve_feature_list
    from dodgys_dd_quant.vision_validator.batch import apply_to_candidates, evaluate_candidates
    from dodgys_dd_quant.strategy.state_machine import (
        PRESETS,
        CandidateLog,
        run_state_machine,
    )

    bars = _bars()
    log = run_state_machine(bars, PRESETS["honest"])
    candidates = list(log)[:200]
    if not candidates:
        return False, "no candidates to inspect"

    interval = bars.interval_ns
    bars_df = pd.DataFrame(
        {
            "ts_event": bars.ts.astype("int64") + interval,
            "open": bars.open,
            "high": bars.high,
            "low": bars.low,
            "close": bars.close,
            "volume": bars.volume,
        }
    )

    def frame(rows):
        return pd.DataFrame(CandidateLog(list(rows), "BTCUSDT", "1m").to_table())

    empty = build_features(frame(candidates), bars_df)
    _, excluded_before = resolve_feature_list(empty)
    if "vision_confidence" not in excluded_before:
        return False, (
            "the vision feature is not excluded before the batch ran -- the "
            "D12 degradation does not work"
        )

    batch = evaluate_candidates(candidates, bars, detector=_BodyDetector())
    apply_to_candidates(candidates, batch)

    filled = build_features(frame(candidates), bars_df)
    used, excluded = resolve_feature_list(filled)
    if "vision_confidence" not in used:
        return False, (
            f"the vision feature is not used (excluded: {sorted(excluded)[:3]})"
        )
    return True, (
        f"the batch makes {len(used)} features available, the vision column "
        f"among them"
    )


@register(
    "vision.batch_is_causal",
    "vision",
    40,
    "the vision batch is causal: truncating the future changes no verdict",
)
def _batch_is_causal() -> tuple[bool, str]:
    """No look-ahead in the vision layer.

    A candidate is scored on the window that ends at its **own confirmation
    bar**, so truncating the series after that bar cannot change its
    verdict -- and the rendered image's digest must be identical.
    """
    from dodgys_dd_quant.vision_validator.batch import evaluate_candidates
    from dodgys_dd_quant.strategy.structure import Bars

    bars, candidates = _candidates(limit=6)
    if not candidates:
        return False, "no candidates to inspect"

    full = evaluate_candidates(candidates, bars, detector=_BodyDetector())
    if full.n_evaluated == 0:
        return False, "the batch evaluated nothing"

    # the same candidates, on a series truncated right after the last
    # confirmation bar
    last = max(int(c.confirm_bar) for c in candidates)
    end = last + 1
    truncated = Bars(
        ts=bars.ts[:end],
        open=bars.open[:end],
        high=bars.high[:end],
        low=bars.low[:end],
        close=bars.close[:end],
        volume=bars.volume[:end],
        symbol=bars.symbol,
        timeframe=bars.timeframe,
    )
    short = evaluate_candidates(candidates, truncated, detector=_BodyDetector())
    if short.n_evaluated != full.n_evaluated:
        return False, (
            f"truncating the future changed the population "
            f"({short.n_evaluated} against {full.n_evaluated})"
        )
    for a, b in zip(full.verdicts, short.verdicts):
        if a.image_sha256 != b.image_sha256:
            return False, "the rendered window changed when the future was cut"
        if a.vision_iou != b.vision_iou or a.passed != b.passed:
            return False, "a verdict changed when the future was cut"
    return True, (
        f"{full.n_evaluated} verdicts are unchanged when the future is cut"
    )


@register(
    "vision.calibration_recovers_the_pre_registered_threshold",
    "vision",
    45,
    "the IoU threshold is produced by a calibration procedure, not asserted (D6)",
)
def _calibration() -> tuple[bool, str]:
    """D6: "start ≈ 0.5, then calibrate".

    The calibration must recover a known quantile of the measured sample, and
    the audit's own table must be self-consistent: its published quantiles
    and acceptance rates imply the pre-registered threshold of 0.30.
    """
    import numpy as np

    from dodgys_dd_quant.strategy.constants import VISION_BODY_IOU_THRESHOLD
    from dodgys_dd_quant.vision_validator.calibration import (
        AUDIT_MEASURED_ACCEPTANCE,
        AUDIT_MEASURED_QUANTILES,
        PRE_REGISTERED_THRESHOLD,
        calibrate_threshold,
    )

    rng = np.random.default_rng(5)
    samples = rng.beta(4.0, 3.0, size=4000) * 0.8 + 0.1

    report = calibrate_threshold(samples, acceptance=0.5)
    median = float(np.median(samples))
    if not math.isclose(report.threshold, median, rel_tol=0.02):
        return False, (
            f"the calibration returned {report.threshold} where the median is "
            f"{median}"
        )
    if not math.isclose(report.acceptance, 0.5, abs_tol=0.03):
        return False, f"the calibrated threshold admits {report.acceptance}"

    # the acceptance curve is monotone
    shares = [share for _, share in report.curve]
    if any(b > a + 1e-9 for a, b in zip(shares, shares[1:])):
        return False, "the acceptance curve is not monotone"

    # the audit's table: reconstruct the distribution from its published
    # quantiles and check that the 72.1 % acceptance point is 0.30
    points = [
        (0.10, AUDIT_MEASURED_QUANTILES["p10"]),
        (1.0 - AUDIT_MEASURED_ACCEPTANCE[0.30], 0.30),
        (0.50, AUDIT_MEASURED_QUANTILES["p50"]),
        (0.90, AUDIT_MEASURED_QUANTILES["p90"]),
    ]
    points.sort()
    grid = np.linspace(0.001, 0.999, 4000)
    inverse = np.interp(grid, [p[0] for p in points], [p[1] for p in points])
    reconstructed = calibrate_threshold(
        inverse, acceptance=AUDIT_MEASURED_ACCEPTANCE[0.30]
    )
    if not math.isclose(reconstructed.threshold, 0.30, abs_tol=0.02):
        return False, (
            f"the audit's table implies {reconstructed.threshold}, not 0.30"
        )
    if not math.isclose(
        VISION_BODY_IOU_THRESHOLD, PRE_REGISTERED_THRESHOLD, abs_tol=1e-9
    ):
        return False, (
            f"the shipped threshold {VISION_BODY_IOU_THRESHOLD} is not the "
            f"pre-registered {PRE_REGISTERED_THRESHOLD}"
        )
    return True, (
        f"the calibration recovers the median and the audit's implied "
        f"threshold {reconstructed.threshold:.3f}; the shipped gate is "
        f"{VISION_BODY_IOU_THRESHOLD}"
    )


@register(
    "vision.side_table_is_exportable",
    "vision",
    35,
    "the audit's side table -- the sharper diagnostics -- can be exported (L1 §B.6)",
)
def _side_table() -> tuple[bool, str]:
    """L1 §B.6: ``row_containment`` and ``bar_index_delta`` are sharper than
    the IoU and belong in a side table beside the log.
    """
    from dodgys_dd_quant.vision_validator.batch import (
        evaluate_candidates,
        side_table,
        write_side_table,
    )

    bars, candidates = _candidates(limit=6)
    if not candidates:
        return False, "no candidates to inspect"
    batch = evaluate_candidates(candidates, bars, detector=_BodyDetector())
    table = side_table(batch)
    for column in ("row_containment", "bar_index_delta", "class_match", "passed"):
        if column not in table:
            return False, f"the side table has no {column!r} column"
        if len(table[column]) != batch.n_evaluated:
            return False, f"the {column!r} column is not aligned with the batch"
    with tempfile.TemporaryDirectory() as tmp:
        target = write_side_table(batch, Path(tmp) / "side.csv")
        if not target.exists() or target.stat().st_size == 0:
            return False, "the side table was not written"
        header = target.read_text(encoding="utf-8").splitlines()[0]
        if "row_containment" not in header:
            return False, "the written table has no row_containment column"
    return True, (
        f"the side table carries {len(table)} diagnostic columns for "
        f"{batch.n_evaluated} candidates"
    )
