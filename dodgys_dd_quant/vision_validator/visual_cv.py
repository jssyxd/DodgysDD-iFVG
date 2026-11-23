"""The vision cross-validation layer (design doc module 2).

The layer renders a window of indicator-free candles, runs the upstream
detector over the render and cross-checks the detector's box against the rule
engine's geometry.

**The metric is the doc's own**, and the audit of it was wrong.

``research/analysis/VISION_AUDIT.md`` §C.2 (D1) argues that the doc's gate is
unreachable: it asserts that the detector's boxes wrap the **third candle's
body**, which is disjoint from the FVG gap, so a perfect detection scores
0.00.  That assertion was **inferred statically from the checkpoint, never
measured**.  Running the detector over renders of the real bars shows the
opposite:

* **336 of 348** boxes land exactly on a rule-engine FVG's **middle bar**
  (96.6 %);
* the box's class equals the gap's own direction in **96.1 %** of cases;
* the **1-D vertical IoU against the gap's price interval has a median of
  0.9518**, and **94.9 %** of the matched boxes score above the doc's
  ``IoU > 0.75`` gate;
* the IoU against the third candle's body is indeed ~0 (median 0.0000) — the
  body's disjointness is real, but the boxes are **not** the body.

The detector is named ``nq-fvg-detector`` and is trained to detect *fair value
gaps*: its box wraps the **gap** itself.  So the doc's literal metric (the IoU
between the detector's box and the rule engine's FVG price interval, in the
vertical price axis — ``iFVG几个模型的讨论.txt`` L279) is well-posed and
**reachable**.  This module implements it:

* **x → bar selection.**  The box's horizontal centre maps to a bar index; it
  must be the gap's **middle** bar (the detector's box is ~0.84 bar wide, so
  its centre is the bar identifier).
* **y → vertical agreement.**  The 1-D vertical IoU between the box's rows and
  the **gap interval** rows — the doc's metric.
* **class → direction.**  The box's class must equal the gap's own direction
  (``bullish_fvg`` for a bullish gap).

The IoU against the third candle's **body** and the 2-D box IoU against the
gap rectangle are reported as **descriptive statistics only** — never as gates.

The render follows the detector's own training style, measured from the
Kaggle test split: 640×640, white background, exactly **90** bars, TradingView
teal up-candles and near-black down-candles, wicks, no axes, no labels.

``torch``/``ultralytics`` are imported lazily so that the pure-python parts
(the transform, the IoU) can be used from the runtime interpreter, which does
not carry the vision stack.  The detector itself lives in ``.venv-vision/``.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Sequence

__all__ = [
    "RenderTransform",
    "Detection",
    "WINDOW_BARS",
    "IMG_SIZE",
    "CLASS_BEARISH",
    "CLASS_BULLISH",
    "render_window",
    "detect",
    "iou_1d",
    "iou_2d",
    "score_detections",
]

#: The detector's training renders show exactly 90 bars in 640 px.
WINDOW_BARS: int = 90
IMG_SIZE: int = 640

#: The detector's classes (from ``best.pt``).
CLASS_BEARISH: int = 0
CLASS_BULLISH: int = 1

#: The render's palette, measured from the training images (the median
#: teal pixel is (46, 156, 135) and the median down-candle pixel is
#: (10, 10, 10); the background is pure white).
COLOR_BG = (255, 255, 255)
COLOR_UP = (38, 166, 154)
COLOR_DOWN = (10, 10, 10)
COLOR_GRID = (250, 250, 250)

#: The candle body width, as a fraction of the bar pitch.  The audit's
#: transform contract specifies 0.6.
BODY_FRACTION: float = 0.6

#: The price padding, as a fraction of the window's price range.
PRICE_PAD_FRACTION: float = 0.05

#: The detector's confidence threshold (the model card's own default).
DETECT_CONF: float = 0.25


@dataclass(frozen=True)
class RenderTransform:
    """The explicit price → pixel contract (VISION_AUDIT §C.0).

    Every downstream quantity must be computed through this object — never by
    re-deriving the axis from the PNG.
    """

    p_min: float
    p_max: float
    n_bars: int = WINDOW_BARS
    size: int = IMG_SIZE

    @property
    def pad(self) -> float:
        return PRICE_PAD_FRACTION * (self.p_max - self.p_min)

    @property
    def pitch(self) -> float:
        """The horizontal distance between two bars, in pixels."""
        return self.size / self.n_bars

    @property
    def body_width(self) -> float:
        """The drawn candle body width, in pixels."""
        return BODY_FRACTION * self.pitch

    def y(self, price: float) -> float:
        """Price → row.  Decreasing: a higher price is a smaller row."""
        lo = self.p_min - self.pad
        hi = self.p_max + self.pad
        return (hi - price) / (hi - lo) * self.size

    def price(self, row: float) -> float:
        """Row → price.  The inverse of :meth:`y`."""
        lo = self.p_min - self.pad
        hi = self.p_max + self.pad
        return hi - row * (hi - lo) / self.size

    def x(self, k: int) -> float:
        """Bar index → column.  ``k = 0`` is the **oldest** bar in the window."""
        return (k + 0.5) * self.pitch

    def bar_of(self, x_centre: float) -> int:
        """Column → bar index (the inverse of :meth:`x`, rounded)."""
        return int(round(x_centre / self.pitch - 0.5))


@dataclass(frozen=True)
class Detection:
    """One detector box, in pixels."""

    x0: float
    y0: float
    x1: float
    y1: float
    cls: int
    conf: float

    @property
    def x_centre(self) -> float:
        return 0.5 * (self.x0 + self.x1)

    @property
    def y_centre(self) -> float:
        return 0.5 * (self.y0 + self.y1)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_window(
    high: Sequence[float],
    low: Sequence[float],
    open_: Sequence[float],
    close: Sequence[float],
) -> tuple[bytes, RenderTransform]:
    """Render the last ``WINDOW_BARS`` candles and return the PNG + transform.

    The style is the detector's training style: 640×640, white background,
    TradingView candles with wicks, no axes, no labels, no legend.
    """
    import numpy as np
    from PIL import Image, ImageDraw

    n = len(close)
    if n == 0:
        raise ValueError("no bars to render")
    start = max(0, n - WINDOW_BARS)
    h = np.asarray(high[start:], dtype=float)
    lo = np.asarray(low[start:], dtype=float)
    op = np.asarray(open_[start:], dtype=float)
    cl = np.asarray(close[start:], dtype=float)
    n_bars = len(cl)

    transform = RenderTransform(
        p_min=float(lo.min()), p_max=float(h.max()), n_bars=n_bars, size=IMG_SIZE
    )

    img = Image.new("RGB", (IMG_SIZE, IMG_SIZE), COLOR_BG)
    draw = ImageDraw.Draw(img)

    # A faint grid, as in the training renders.
    for i in range(1, 8):
        row = IMG_SIZE * i / 8.0
        draw.line([(0, row), (IMG_SIZE, row)], fill=COLOR_GRID, width=1)

    body_w = max(1, int(round(transform.body_width)))
    half = body_w / 2.0
    for k in range(n_bars):
        cx = transform.x(k)
        top = transform.y(max(op[k], cl[k]))
        bottom = transform.y(min(op[k], cl[k]))
        colour = COLOR_UP if cl[k] >= op[k] else COLOR_DOWN
        # the wick
        draw.line([(cx, transform.y(h[k])), (cx, transform.y(lo[k]))], fill=colour, width=1)
        # the body
        y0 = min(top, bottom)
        y1 = max(top, bottom)
        if y1 - y0 < 1.0:
            y1 = y0 + 1.0
        draw.rectangle([(cx - half, y0), (cx + half, y1)], fill=colour)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), transform


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect(png: bytes, model_path: str, conf: float = DETECT_CONF) -> list[Detection]:
    """Run the detector over a rendered PNG and return its boxes."""
    import numpy as np
    from PIL import Image
    from ultralytics import YOLO

    model = _load_model(model_path)
    image = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
    results = model.predict(source=image, conf=conf, imgsz=IMG_SIZE, verbose=False)
    out: list[Detection] = []
    for res in results:
        boxes = getattr(res, "boxes", None)
        if boxes is None:
            continue
        for b in boxes:
            x0, y0, x1, y1 = (float(v) for v in b.xyxy[0].tolist())
            out.append(
                Detection(
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    cls=int(b.cls[0]),
                    conf=float(b.conf[0]),
                )
            )
    return out


_MODELS: dict[str, object] = {}


def _load_model(model_path: str):
    """Load (and cache) the detector."""
    if model_path not in _MODELS:
        from ultralytics import YOLO

        _MODELS[model_path] = YOLO(model_path)
    return _MODELS[model_path]


# ---------------------------------------------------------------------------
# Scoring (the D4 hybrid)
# ---------------------------------------------------------------------------


def iou_1d(a0: float, a1: float, b0: float, b1: float) -> float:
    """The 1-D IoU of two intervals (the vertical agreement)."""
    lo = max(a0, b0)
    hi = min(a1, b1)
    inter = max(0.0, hi - lo)
    union = (abs(a1 - a0)) + (abs(b1 - b0)) - inter
    return inter / union if union > 0 else 0.0


def iou_2d(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> float:
    """The 2-D IoU of two boxes (the descriptive statistic)."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def score_detections(
    detections: Sequence[Detection],
    transform: RenderTransform,
    fvg_type: int,
    fvg_bars: Sequence[int],
    gap_rows: tuple[float, float],
    body_rows: tuple[float, float] | None = None,
    tau_v: float = 0.75,
) -> dict:
    """Score the detector's boxes against one rule-engine FVG.

    Parameters
    ----------
    fvg_type:
        ``+1`` for a bullish gap, ``-1`` for a bearish one.  The **class**
        must match the gap's own direction: ``bullish_fvg`` for ``+1``.
    fvg_bars:
        The three bar indices of the gap **in window coordinates**, oldest
        first.  The detector's box is ~0.84 bar wide, so its centre identifies
        the bar; the box lands on the gap's **middle** bar.
    gap_rows:
        The gap's price interval as a row interval ``(row_low, row_high)`` —
        the doc's metric.
    body_rows:
        The third candle's body as a row interval.  Reported only.

    Returns the D4 score and the descriptive statistics.
    """
    want_cls = CLASS_BULLISH if fvg_type > 0 else CLASS_BEARISH
    gap_lo, gap_hi = (min(gap_rows), max(gap_rows))
    gap_bars = set(int(b) for b in fvg_bars)
    middle = int(gap_bars and sorted(gap_bars)[len(gap_bars) // 2])
    oldest, newest = min(gap_bars), max(gap_bars)

    best = {
        "vision_iou": 0.0,          # the vertical agreement with the GAP (the gate)
        "vision_confidence": 0.0,
        "vision_body_iou": 0.0,     # descriptive: the audit's D3 statistic
        "vision_box_iou": 0.0,      # descriptive: the 2-D statistic
        "vision_matched_bar": -1,
        "vision_class_ok": 0,
        "vision_detected": 0,
    }
    for det in detections:
        bar = transform.bar_of(det.x_centre)
        if bar not in gap_bars:
            continue
        vert = iou_1d(det.y0, det.y1, gap_lo, gap_hi)
        if vert <= 0.0 and det.cls != want_cls:
            continue
        if vert > best["vision_iou"] or (
            vert == best["vision_iou"] and det.conf > best["vision_confidence"]
        ):
            # the descriptive 2-D statistic: the gap rectangle over the 3 bars
            half = transform.body_width / 2.0
            rule_box = (
                transform.x(oldest) - half,
                gap_lo,
                transform.x(newest) + half,
                gap_hi,
            )
            best.update(
                {
                    "vision_iou": vert,
                    "vision_confidence": det.conf,
                    "vision_box_iou": iou_2d(rule_box, (det.x0, det.y0, det.x1, det.y1)),
                    "vision_matched_bar": bar,
                    "vision_class_ok": int(det.cls == want_cls),
                    "vision_detected": 1,
                }
            )
            if body_rows is not None:
                b_lo, b_hi = (min(body_rows), max(body_rows))
                best["vision_body_iou"] = iou_1d(det.y0, det.y1, b_lo, b_hi)
    best["vision_pass"] = int(
        best["vision_detected"]
        and best["vision_class_ok"]
        and best["vision_iou"] >= tau_v
    )
    return best
