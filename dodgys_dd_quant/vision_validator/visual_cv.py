"""The vision/rule alignment contract (D6).

One pure function in, one dataclass out.  No I/O, no engine calls, no clock,
no RNG: ``evaluate_candidate`` is a deterministic function of its arguments,
so it is unit-testable without a backtest and without a GPU.

The geometry
------------
The rendered window is a **chart**, so the price axis is vertical and the bar
axis is horizontal.  Two affine maps carry the geometry:

* ``row_of_price(price) -> float`` -- the pixel row of a price.  Rows grow
  **downwards**, so the mapping is ``y = y0 - k * (price - p0)`` with
  ``k > 0``;
* ``col_of_bar(index) -> float`` -- the pixel column of a bar's centre.

Every rectangle in this module -- the third candle's body, the FVG gap, a
detector's box -- is expressed in that pixel space and compared there.  The
axis is never re-derived from the rendered PNG: a rendered chart is a
*picture of* the data, not the data.

Why the third candle's body and not the gap
-------------------------------------------
The rule engine's object is the FVG **price gap**; the detector's object is
the third candle's **body**.  For a bullish gap the body sits at or above
the gap's upper edge and for a bearish gap at or below its lower edge, so
the two are **disjoint by construction** (D6).  Measuring the two against
each other therefore yields ~0 no matter how good the detection is -- which
is why the discussion's gate was inverted.

What this module measures instead is the only thing that is well-posed: does
the detector's box coincide with the **body of the candle the rule engine
used**?  That is a real question with a real answer in [0, 1].
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Protocol, Sequence

import numpy as np

__all__ = [
    "DEFAULT_STYLE",
    "BodyRect",
    "Detection",
    "Detector",
    "RenderedWindow",
    "VisionStyle",
    "VisionVerdict",
    "body_box_iou",
    "evaluate_candidate",
    "gate_passes",
    "gap_interval_iou",
    "render_window",
]

#: A rectangle in pixel space: ``(x0, y0, x1, y1)`` with ``x0 <= x1`` and
#: ``y0 <= y1``.
BodyRect = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class VisionStyle:
    """The render convention -- a single source of truth.

    ``version`` must change whenever any visual parameter changes, so that a
    style change can never be mistaken for a model change: the version is
    recorded in every verdict and in the side table.

    The defaults are the detector's **training** convention: white
    background, 640x640 (the model card says *"Trained on white background
    TradingView charts only"* and *"Input size: 640x640"*).  The discussion's
    black 224x224 would be out of distribution for these weights.
    """

    version: str = "v1-tv-white-640"
    width: int = 640
    height: int = 640
    #: The number of candles in the rendered window.  The discussion asks for
    #: the last 60 indicator-free candles; L1's contract used 90 to give the
    #: detector more context.  60 is the doc's number and is used here.
    window_bars: int = 60
    background: str = "#FFFFFF"
    grid_color: str = "#FAFAFA"
    up_color: str = "#08987F"
    down_color: str = "#0A0A0A"
    wick_color: str = "#0A0A0A"
    #: The body width as a fraction of the bar pitch.
    body_width_frac: float = 0.68
    #: Symmetric padding around the window's price range, as a fraction of it.
    pad_frac: float = 0.10
    #: The detector's input size.
    imgsz: int = 640
    #: The detector's confidence threshold.
    conf: float = 0.25


DEFAULT_STYLE: VisionStyle = VisionStyle()


@dataclass(frozen=True, slots=True)
class Detection:
    """One detector box, in the rendered window's pixel space."""

    #: ``(x0, y0, x1, y1)``.
    box: BodyRect
    #: The detector's class name, e.g. ``bullish_fvg`` / ``bearish_fvg``.
    class_name: str
    #: The detector's own confidence, in [0, 1].
    confidence: float


class Detector(Protocol):
    """What the vision layer needs from a detector.

    The protocol exists so the alignment logic is testable **without** a
    detector: the unit tests inject a stub that returns a known box.  The
    real detector (``ultralytics``' YOLO on the shipped weights) satisfies
    this protocol; nothing here imports it, so the package stays importable
    on a machine without torch.
    """

    def detect(self, image: np.ndarray) -> Sequence[Detection]:
        """Return the boxes found in ``image`` (an ``(H, W, 3)`` uint8 array)."""
        ...


@dataclass(frozen=True, slots=True)
class RenderedWindow:
    """A rendered window plus the affine maps that place data in it.

    The maps are the point of the class: they make the geometry *exact*.
    A consumer never has to guess where a price ended up in the picture.

    The two maps are affine and therefore invertible:

    * ``row_of_price(p) = row_top_px - (p - price_high) * px_per_price``
    * ``col_of_bar(k) = col_first_px + k * bar_pitch_px``
    """

    #: The rendered chart, ``(H, W, 3)`` uint8.
    image: np.ndarray
    #: The pixel row of a price (scalar or array).
    row_of_price: object
    #: The pixel column of a bar's centre.
    col_of_bar: object
    #: The distance between two consecutive bar centres, in pixels.
    bar_pitch_px: float
    #: The width of a rendered candle body, in pixels.
    body_width_px: float
    #: The timestamp of the window's first bar (ns).
    window_start_ts_ns: int
    #: The timestamp of the window's last bar (ns).
    window_end_ts_ns: int
    #: The style the window was rendered with.
    style: VisionStyle = DEFAULT_STYLE
    #: The number of bars in the window.
    bar_count: int = 0
    #: The price at the top of the plot area.
    price_high: float = 0.0
    #: The price at the bottom of the plot area.
    price_low: float = 0.0
    #: The pixel row of the plot area's top edge.
    row_top_px: float = 0.0
    #: The pixel row of the plot area's bottom edge.
    row_bottom_px: float = 0.0
    #: The open prices of the window's bars, oldest first.
    opens: tuple[float, ...] = ()
    #: The close prices of the window's bars, oldest first.
    closes: tuple[float, ...] = ()

    def body_rect(self, slot: int) -> BodyRect:
        """The **body** rectangle of the bar in ``slot``.

        ``slot`` is the index *within the window* (0 = oldest).  The body is
        the rectangle between the open and the close, which is what the
        detector's annotation convention targets.

        A doji (open == close) has no body at all; the rectangle is then one
        pixel tall, matching what the renderer actually draws.
        """
        if not 0 <= slot < self.bar_count:
            raise IndexError(f"slot {slot} outside the window (0..{self.bar_count - 1})")
        column = float(self.col_of_bar(slot))  # type: ignore[operator]
        half = self.body_width_px / 2.0
        top = float(self.row_of_price(max(self.opens[slot], self.closes[slot])))  # type: ignore[operator]
        bottom = float(self.row_of_price(min(self.opens[slot], self.closes[slot])))  # type: ignore[operator]
        if bottom - top < 1.0:
            bottom = top + 1.0
        return (
            min(column - half, column + half),
            min(top, bottom),
            max(column - half, column + half),
            max(top, bottom),
        )

    def gap_rect(self, slot: int, gap_low: float, gap_high: float) -> BodyRect:
        """The FVG **gap** rectangle of the bar in ``slot``.

        This is the rule engine's object -- the price gap between the first
        and the third candle -- expressed in the same pixel space.  It is
        reported for the descriptive gap IoU and is never a gate.
        """
        column = float(self.col_of_bar(slot))  # type: ignore[operator]
        half = self.body_width_px / 2.0
        top = float(self.row_of_price(max(gap_low, gap_high)))  # type: ignore[operator]
        bottom = float(self.row_of_price(min(gap_low, gap_high)))  # type: ignore[operator]
        return (
            min(column - half, column + half),
            min(top, bottom),
            max(column - half, column + half),
            max(top, bottom),
        )

    def bar_slot_of_column(self, column: float) -> int:
        """The bar slot a pixel column falls on.

        The detector's box is narrower than one bar, so its **centre**
        identifies the bar (D6 §B.5.3).
        """
        if self.bar_pitch_px <= 0.0:
            return -1
        first = float(self.col_of_bar(0))  # type: ignore[operator]
        slot = int(round((column - first) / self.bar_pitch_px))
        if not 0 <= slot < self.bar_count:
            return -1
        return slot


@dataclass(frozen=True, slots=True)
class VisionVerdict:
    """The result of scoring one candidate against the detector.

    Two columns are written into the frozen D2 log -- ``vision_iou`` and
    ``vision_confidence`` -- and everything else goes into a side table, so
    the D2 schema stays byte-identical (D12).
    """

    #: 2-D box IoU between the matched detector box and the third candle's
    #: body rectangle.  NaN when nothing matched.
    vision_iou: float = float("nan")
    #: The detector's confidence for the matched box.  NaN when nothing matched.
    vision_confidence: float = float("nan")
    #: The 1-D vertical IoU between the matched box's rows and the FVG gap's
    #: rows.  **Descriptive only** -- never a gate.  ~0 for a correct match.
    vision_iou_gap: float = float("nan")
    #: ``|box_rows & body_rows| / |box_rows|``.  Measured median 1.000 on the
    #: detector's own ground truth: much sharper than the IoU, because it is
    #: insensitive to the "box is tighter than the body" convention.
    row_containment: float = float("nan")
    #: The bar slot the matched box's centre falls on.
    matched_bar_index: int = -1
    #: ``matched_bar_index - fvg_c3_slot``; must be 0 for the match to count.
    bar_index_delta: int = -1
    #: Whether the detector's class agrees with the gap's direction.
    class_match: bool = False
    #: How many boxes the detector returned.
    n_detections: int = 0
    #: The style version the verdict was produced with.
    style_version: str = DEFAULT_STYLE.version
    #: The SHA-256 of the rendered image, so a verdict can be tied to the
    #: exact picture that produced it.
    image_sha256: str = ""
    #: The gate decision: ``class_match and bar_index_delta == 0 and
    #: vision_iou >= tau``.
    passed: bool = False


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def body_box_iou(a: BodyRect, b: BodyRect) -> float:
    """The 2-D IoU of two pixel-space rectangles.

    Two identical rectangles score 1.0 and two disjoint ones 0.0.  Against
    the discussion's *gap* object this returns ~0 even for a perfect
    detection, because the body and the gap are disjoint by construction --
    which is exactly the defect D6 identified.
    """
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    if union <= 0.0:
        return 0.0
    return inter / union


def gap_interval_iou(a: BodyRect, b: BodyRect) -> float:
    """The 1-D vertical IoU of two rectangles' row spans.

    This is the discussion's literal metric (L279: *"IoU on the vertical
    price axis"*).  It is reported as a **sanity number**: for a correct
    match it must be ~0, and a non-zero value means the renderer and the
    rule engine disagree about the price axis.  It is never a gate.
    """
    a0, a1 = min(a[1], a[3]), max(a[1], a[3])
    b0, b1 = min(b[1], b[3]), max(b[1], b[3])
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    union = (a1 - a0) + (b1 - b0) - inter
    if union <= 0.0:
        return 0.0
    return inter / union


def gate_passes(
    class_match: bool,
    bar_index_delta: int,
    vision_iou: float,
    tau: float,
) -> bool:
    """The three-part gate (D6 / L1 §B.5).

    ``pass <=> class_match AND bar_index_delta == 0 AND vision_iou >= tau``

    The IoU is the **weakest** of the three conditions: the class match is
    categorical and the bar-index delta is an exact integer test, while the
    IoU depends on the detector's annotation convention.  That is why the
    threshold is calibrated (~0.30) instead of inherited (0.75).
    """
    if not class_match:
        return False
    if int(bar_index_delta) != 0:
        return False
    if not math.isfinite(float(vision_iou)):
        return False
    return float(vision_iou) >= float(tau)


def _row_containment(box: BodyRect, body: BodyRect) -> float:
    """``|box_rows & body_rows| / |box_rows|``."""
    b0, b1 = min(box[1], box[3]), max(box[1], box[3])
    y0, y1 = min(body[1], body[3]), max(body[1], body[3])
    height = b1 - b0
    if height <= 0.0:
        return 0.0
    inter = max(0.0, min(b1, y1) - max(b0, y0))
    return inter / height


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _hex_to_rgb(text: str) -> tuple[int, int, int]:
    value = text.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        raise ValueError(f"not a hex colour: {text!r}")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def render_window(
    bars,
    style: VisionStyle = DEFAULT_STYLE,
) -> RenderedWindow:
    """Render the last ``style.window_bars`` bars as a chart.

    ``bars`` is any object exposing ``open``, ``high``, ``low``, ``close``
    (sequences of floats) and ``ts`` (nanosecond timestamps) -- the engine's
    ``Bars`` container qualifies, and so does a plain tuple of sequences.

    The chart is drawn with Pillow rather than a plotting library: the
    detector was trained on plain white TradingView-style charts, and a
    dependency-free renderer keeps the package importable anywhere (it
    imports nothing beyond numpy and Pillow).

    The returned window carries the exact affine maps, so the geometry is
    computed from the data rather than read back out of the picture.
    """
    from PIL import Image, ImageDraw

    opens = np.asarray(bars.open, dtype=np.float64)
    highs = np.asarray(bars.high, dtype=np.float64)
    lows = np.asarray(bars.low, dtype=np.float64)
    closes = np.asarray(bars.close, dtype=np.float64)
    timestamps = np.asarray(bars.ts, dtype=np.int64)

    count = int(min(style.window_bars, opens.shape[0]))
    if count < 2:
        raise ValueError("at least two bars are needed to render a window")
    opens = opens[-count:]
    highs = highs[-count:]
    lows = lows[-count:]
    closes = closes[-count:]
    timestamps = timestamps[-count:]

    width = int(style.width)
    height = int(style.height)
    image = Image.new("RGB", (width, height), _hex_to_rgb(style.background))
    draw = ImageDraw.Draw(image)

    # --- the plot area and the affine maps --------------------------------
    margin_x = int(round(width * style.pad_frac))
    margin_y = int(round(height * style.pad_frac))
    row_top = float(margin_y)
    row_bottom = float(height - margin_y)
    col_first = float(margin_x)
    bar_pitch = (width - 2 * margin_x) / count
    body_width = bar_pitch * style.body_width_frac

    price_high = float(np.max(highs))
    price_low = float(np.min(lows))
    span = price_high - price_low
    if span <= 0.0:
        span = max(abs(price_high), 1.0) * 1e-6
    padded_high = price_high + span * style.pad_frac
    padded_low = price_low - span * style.pad_frac
    padded_span = padded_high - padded_low
    px_per_price = (row_bottom - row_top) / padded_span

    def row_of_price(price):
        # Rows grow downwards, so the *high* price sits at the plot area's top
        # edge and the *low* price at its bottom edge.
        return row_top + (padded_high - np.asarray(price, dtype=np.float64)) * px_per_price

    def col_of_bar(slot):
        return col_first + float(slot) * bar_pitch

    # --- the candles -------------------------------------------------------
    grid = _hex_to_rgb(style.grid_color)
    for i in range(1, 4):
        y = row_top + (row_bottom - row_top) * i / 4.0
        draw.line([(0, y), (width, y)], fill=grid, width=1)

    up = _hex_to_rgb(style.up_color)
    down = _hex_to_rgb(style.down_color)
    wick = _hex_to_rgb(style.wick_color)
    for slot in range(count):
        centre = col_of_bar(slot)
        top = float(row_of_price(highs[slot]))
        bottom = float(row_of_price(lows[slot]))
        draw.line([(centre, top), (centre, bottom)], fill=wick, width=1)
        body_top = float(row_of_price(max(opens[slot], closes[slot])))
        body_bottom = float(row_of_price(min(opens[slot], closes[slot])))
        colour = up if closes[slot] >= opens[slot] else down
        left = centre - body_width / 2.0
        right = centre + body_width / 2.0
        draw.rectangle([left, body_top, right, max(body_bottom, body_top + 1.0)], fill=colour)

    array = np.asarray(image, dtype=np.uint8)
    return RenderedWindow(
        image=array,
        row_of_price=row_of_price,
        col_of_bar=col_of_bar,
        bar_pitch_px=float(bar_pitch),
        body_width_px=float(body_width),
        window_start_ts_ns=int(timestamps[0]),
        window_end_ts_ns=int(timestamps[-1]),
        style=style,
        bar_count=count,
        price_high=padded_high,
        price_low=padded_low,
        row_top_px=row_top,
        row_bottom_px=row_bottom,
        opens=tuple(float(v) for v in opens),
        closes=tuple(float(v) for v in closes),
    )


# ---------------------------------------------------------------------------
# The alignment
# ---------------------------------------------------------------------------

#: The detector's class names, and the gap direction each one stands for.
#: A bullish FVG is a *bullish* gap; the strategy then trades it **short**,
#: because the setup is the failure of that bullish gap (RULE_SPEC A13).
CLASS_DIRECTION: dict[str, int] = {
    "bullish_fvg": 1,
    "bearish_fvg": -1,
}


def evaluate_candidate(
    bars,
    fvg_c1_slot: int,
    fvg_c3_slot: int,
    gap_low: float,
    gap_high: float,
    direction: int,
    detector: Detector,
    style: VisionStyle = DEFAULT_STYLE,
    iou_threshold: float | None = None,
) -> VisionVerdict:
    """Score one candidate against the detector.

    The signature is the one L1 §B.6 proposes for this module.

    Parameters
    ----------
    bars:
        The window to render: the last ``style.window_bars`` bars ending at
        the confirmation bar, oldest first.  Any object with ``open``,
        ``high``, ``low``, ``close`` and ``ts`` sequences qualifies.
    fvg_c1_slot:
        The slot of the FVG's **first** candle within the window.
    fvg_c3_slot:
        The slot of the FVG's **third** candle within the window -- the
        candle whose body the detector should have annotated.
    gap_low, gap_high:
        The FVG's price gap, the rule engine's object.  Reported through the
        descriptive gap IoU; never a gate.
    direction:
        ``+1`` for a bullish gap, ``-1`` for a bearish gap.
    detector:
        The detector.  A stub returning a known box is enough to exercise
        the whole path.
    style, iou_threshold:
        The render convention and the calibrated threshold.  ``None`` uses
        ``constants.VISION_BODY_IOU_THRESHOLD``.

    Returns
    -------
    VisionVerdict
        The two D2 columns (``vision_iou``, ``vision_confidence``) plus the
        diagnostics that belong in the side table.
    """
    if iou_threshold is None:
        from dodgys_dd_quant.strategy.constants import VISION_BODY_IOU_THRESHOLD

        iou_threshold = VISION_BODY_IOU_THRESHOLD

    window = render_window(bars, style)
    digest = hashlib.sha256(window.image.tobytes()).hexdigest()

    # A detector that wants the exact geometry may implement the optional
    # ``detect_window(window)`` hook; the plain protocol (``detect(image)``)
    # is what the shipped model implements.
    if hasattr(detector, "detect_window"):
        detections = list(detector.detect_window(window))
    else:
        detections = list(detector.detect(window.image))
    if not detections:
        return VisionVerdict(
            n_detections=0,
            style_version=style.version,
            image_sha256=digest,
        )

    # The third candle's body is the object both sides must agree on.
    body = window.body_rect(fvg_c3_slot)
    gap = window.gap_rect(fvg_c3_slot, gap_low, gap_high)

    best: Detection | None = None
    best_slot = -1
    # Negative, so that a box on the right bar with *zero* overlap is still
    # recorded as a match (with an IoU of 0.0) rather than being reported as
    # "no detection".  The distinction matters: the former says the detector
    # found the bar but not the body, the latter says it found nothing.
    best_iou = -1.0
    for detection in detections:
        box = detection.box
        centre = (box[0] + box[2]) / 2.0
        slot = window.bar_slot_of_column(centre)
        if slot != fvg_c3_slot:
            # Bar identity is a hard condition: a box on another bar is not
            # a match for this candidate, whatever its overlap.
            continue
        iou = body_box_iou(box, body)
        if iou > best_iou:
            best = detection
            best_slot = slot
            best_iou = iou

    if best is None:
        return VisionVerdict(
            n_detections=len(detections),
            style_version=style.version,
            image_sha256=digest,
        )

    expected_class = "bullish_fvg" if direction > 0 else "bearish_fvg"
    class_match = best.class_name == expected_class
    delta = best_slot - fvg_c3_slot
    containment = _row_containment(best.box, body)
    gap_iou = gap_interval_iou(best.box, gap)

    return VisionVerdict(
        vision_iou=best_iou,
        vision_confidence=float(best.confidence),
        vision_iou_gap=gap_iou,
        row_containment=containment,
        matched_bar_index=best_slot,
        bar_index_delta=delta,
        class_match=class_match,
        n_detections=len(detections),
        style_version=style.version,
        image_sha256=digest,
        passed=gate_passes(class_match, delta, best_iou, iou_threshold),
    )
