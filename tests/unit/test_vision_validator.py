"""Tests for the vision/rule alignment contract (D6).

The geometry is checked against **hand-computed** values, not against the
module's own output, so a broken implementation cannot agree with itself.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from dodgys_dd_quant.strategy import constants
from dodgys_dd_quant.vision_validator import visual_cv


class _Bars:
    """A minimal bar container: open/high/low/close/ts sequences."""

    def __init__(self, opens, highs, lows, closes, ts):
        self.open = np.asarray(opens, dtype=float)
        self.high = np.asarray(highs, dtype=float)
        self.low = np.asarray(lows, dtype=float)
        self.close = np.asarray(closes, dtype=float)
        self.ts = np.asarray(ts, dtype=np.int64)


def _flat_bars(n: int = 60, base: float = 100.0) -> _Bars:
    ts = np.arange(n, dtype=np.int64) * 60_000_000_000
    opens = np.full(n, base)
    closes = np.full(n, base)
    highs = np.full(n, base + 1.0)
    lows = np.full(n, base - 1.0)
    return _Bars(opens, highs, lows, closes, ts)


class _StubDetector:
    """Returns a fixed box, or nothing."""

    def __init__(self, boxes=()):
        self.boxes = list(boxes)
        self.calls = 0

    def detect(self, image):
        self.calls += 1
        return self.boxes


# ---------------------------------------------------------------------------
# The IoU metric
# ---------------------------------------------------------------------------


def test_identical_rectangles_score_one():
    rect = (10.0, 20.0, 30.0, 40.0)
    assert visual_cv.body_box_iou(rect, rect) == pytest.approx(1.0)


def test_disjoint_rectangles_score_zero():
    a = (0.0, 0.0, 10.0, 10.0)
    b = (100.0, 100.0, 110.0, 110.0)
    assert visual_cv.body_box_iou(a, b) == 0.0


def test_half_overlap_scores_one_third():
    a = (0.0, 0.0, 10.0, 10.0)
    b = (5.0, 0.0, 15.0, 10.0)
    # intersection 5*10 = 50, union 100 + 100 - 50 = 150
    assert visual_cv.body_box_iou(a, b) == pytest.approx(50.0 / 150.0)


def test_body_and_gap_are_disjoint_by_construction():
    """The defect D6 identified: the two objects never overlap.

    A bullish gap sits *below* the third candle's body, so the body's rows
    and the gap's rows do not intersect at all -- which is why the
    discussion's vertical-gap IoU scores a *perfect* detection 0.00.
    """
    body = (100.0, 200.0, 110.0, 210.0)
    gap = (100.0, 220.0, 110.0, 230.0)
    assert visual_cv.body_box_iou(body, gap) == 0.0
    assert visual_cv.gap_interval_iou(body, gap) == 0.0


def test_gap_interval_iou_is_one_for_identical_spans():
    assert visual_cv.gap_interval_iou((0.0, 10.0, 5.0, 20.0), (0.0, 10.0, 5.0, 20.0)) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def test_gate_requires_all_three_conditions():
    assert visual_cv.gate_passes(True, 0, 0.60, 0.30) is True
    assert visual_cv.gate_passes(False, 0, 0.60, 0.30) is False
    assert visual_cv.gate_passes(True, 2, 0.60, 0.30) is False
    assert visual_cv.gate_passes(True, 0, 0.10, 0.30) is False


def test_gate_rejects_a_non_finite_iou():
    assert visual_cv.gate_passes(True, 0, float("nan"), 0.30) is False


# ---------------------------------------------------------------------------
# The threshold
# ---------------------------------------------------------------------------


def test_the_threshold_is_calibrated_not_inherited():
    assert 0.20 <= constants.VISION_BODY_IOU_THRESHOLD <= 0.50


def test_the_inherited_075_gate_is_gone():
    assert not hasattr(constants, "VISION_IOU_THRESHOLD")


# ---------------------------------------------------------------------------
# The renderer
# ---------------------------------------------------------------------------


def test_render_is_640_square_and_white():
    window = visual_cv.render_window(_flat_bars())
    assert window.image.shape == (640, 640, 3)
    assert window.image.dtype == np.uint8
    # The corners are the untouched background.
    assert tuple(window.image[0, 0]) == (255, 255, 255)


def test_render_uses_the_detectors_training_convention():
    style = visual_cv.DEFAULT_STYLE
    assert (style.width, style.height) == (640, 640)
    assert style.background.upper() == "#FFFFFF"
    assert style.window_bars >= 60


def test_the_price_map_is_exact_and_invertible():
    window = visual_cv.render_window(_flat_bars())
    price = 100.0
    row = float(window.row_of_price(price))
    scale = (window.row_bottom_px - window.row_top_px) / (window.price_high - window.price_low)
    back = window.price_high - (row - window.row_top_px) / scale
    assert back == pytest.approx(price, abs=1e-9)


def test_the_bar_map_places_the_body_inside_the_plot_area():
    window = visual_cv.render_window(_flat_bars())
    body = window.body_rect(0)
    assert window.row_top_px <= body[1] <= body[3] <= window.row_bottom_px
    assert 0.0 <= body[0] <= body[2] <= 640.0


def test_a_bar_slot_is_identified_by_its_column():
    window = visual_cv.render_window(_flat_bars())
    for slot in (0, 17, 59):
        assert window.bar_slot_of_column(float(window.col_of_bar(slot))) == slot


def test_a_column_outside_the_window_has_no_slot():
    window = visual_cv.render_window(_flat_bars())
    assert window.bar_slot_of_column(-500.0) == -1
    assert window.bar_slot_of_column(10_000.0) == -1


# ---------------------------------------------------------------------------
# evaluate_candidate
# ---------------------------------------------------------------------------


def test_evaluate_reports_no_match_when_the_detector_finds_nothing():
    bars = _flat_bars()
    window = visual_cv.render_window(bars)
    detector = _StubDetector()
    verdict = visual_cv.evaluate_candidate(bars, 0, 0, 99.0, 101.0, 1, detector)
    assert verdict.n_detections == 0
    assert verdict.passed is False
    assert math.isnan(verdict.vision_iou)
    assert detector.calls == 1


def test_a_perfect_body_detection_scores_one_and_passes():
    bars = _flat_bars()
    window = visual_cv.render_window(bars)
    body = window.body_rect(0)
    detector = _StubDetector([visual_cv.Detection(body, "bullish_fvg", 0.9)])
    verdict = visual_cv.evaluate_candidate(bars, 0, 0, 99.0, 101.0, 1, detector)
    assert verdict.vision_iou == pytest.approx(1.0)
    assert verdict.class_match is True
    assert verdict.bar_index_delta == 0
    assert verdict.passed is True
    assert verdict.vision_confidence == pytest.approx(0.9)


def test_a_wrong_class_does_not_pass():
    bars = _flat_bars()
    window = visual_cv.render_window(bars)
    body = window.body_rect(0)
    detector = _StubDetector([visual_cv.Detection(body, "bearish_fvg", 0.9)])
    verdict = visual_cv.evaluate_candidate(bars, 0, 0, 99.0, 101.0, 1, detector)
    assert verdict.class_match is False
    assert verdict.passed is False


def test_a_box_on_another_bar_is_not_a_match():
    bars = _flat_bars()
    window = visual_cv.render_window(bars)
    body = window.body_rect(10)
    detector = _StubDetector([visual_cv.Detection(body, "bullish_fvg", 0.9)])
    verdict = visual_cv.evaluate_candidate(bars, 0, 0, 99.0, 101.0, 1, detector)
    assert verdict.n_detections == 1
    assert verdict.vision_iou != verdict.vision_iou  # NaN: nothing matched
    assert verdict.passed is False


def test_the_verdict_records_the_gap_iou_as_a_description():
    bars = _flat_bars()
    window = visual_cv.render_window(bars)
    body = window.body_rect(0)
    detector = _StubDetector([visual_cv.Detection(body, "bullish_fvg", 0.9)])
    # A bullish gap sits *below* the third candle's body, so the two row
    # spans do not intersect.
    verdict = visual_cv.evaluate_candidate(bars, 0, 0, 99.0, 99.9, 1, detector)
    # The descriptive gap IoU is ~0 even though the body IoU is 1.0.  This
    # is the alignment D6 fixed.
    assert verdict.vision_iou_gap == pytest.approx(0.0, abs=1e-9)
    assert verdict.vision_iou == pytest.approx(1.0)
    assert verdict.row_containment == pytest.approx(1.0)


def test_the_image_digest_is_recorded():
    bars = _flat_bars()
    detector = _StubDetector()
    verdict = visual_cv.evaluate_candidate(bars, 0, 0, 99.0, 101.0, 1, detector)
    assert len(verdict.image_sha256) == 64
    assert verdict.style_version == visual_cv.DEFAULT_STYLE.version
