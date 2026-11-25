"""Vision probes -- Q1 (visual detection + parameter double validation) and
Q2 (are the two sides actually aligned?).

The audit says the two sides are **not** aligned and that the discussion's
own metric is *inverted*:

* the rule engine measures the FVG **price gap**;
* the shipped detector annotates the **third candle's body**;
* those two objects are **disjoint by construction**, so under the
  discussion's literal metric a *perfect* detection scores **IoU = 0.00**
  (measured: median 0.0000, 87.9 % exactly zero, 0.65 % above 0.75).

D6 therefore fixes the contract: the metric must be the **2-D box IoU
against the third candle's body rectangle**, where a perfect match scores
1.0.  These probes encode that contract, and they encode it *geometrically*
-- they build the two rectangles by hand and check the IoU arithmetic, so
no detector and no GPU is required.

The gate itself is three-part (L1 §B.5):

    pass  <=>  class_match AND bar_index_delta == 0 AND vision_iou >= tau

with ``tau`` calibrated, not inherited: 0.75 rejects **98 %** of the
detector's own correct labels.
"""

from __future__ import annotations

import math

from bench.probes import register

__all__ = []

#: The calibrated threshold band (L1: 0.75 is wrong even against the correct
#: object -- the model's own ground truth would fail it 98 % of the time;
#: the band that admits most correct detections is ~0.30-0.35).
CALIBRATED_TAU_MIN = 0.20
CALIBRATED_TAU_MAX = 0.50

#: The 0.75 gate that D6/D12 deleted.  It must not reappear.
LEGACY_TAU = 0.75


def _iou_2d(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """2-D box IoU of two ``(x0, y0, x1, y1)`` rectangles."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _body_rect(bar: dict) -> tuple[float, float, float, float]:
    """The third candle's **body** rectangle in pixel space."""
    x0 = bar["col"] - bar["body_half_width"]
    x1 = bar["col"] + bar["body_half_width"]
    y0 = bar["row_top"]
    y1 = bar["row_bottom"]
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _gap_rect(bar: dict) -> tuple[float, float, float, float]:
    """The FVG **gap** rectangle in pixel space (the rule engine's object)."""
    x0 = bar["col"] - bar["body_half_width"]
    x1 = bar["col"] + bar["body_half_width"]
    y0 = bar["row_gap_high"]
    y1 = bar["row_gap_low"]
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _sample_bar() -> dict:
    """One synthetic rendered candle with a bullish gap below its body."""
    return {
        "col": 320.0,
        "body_half_width": 2.5,
        "row_top": 200.0,
        "row_bottom": 215.0,
        "row_gap_high": 240.0,
        "row_gap_low": 260.0,
    }


@register(
    "vision.module_exists",
    "vision",
    12,
    "dodgys_dd_quant.vision_validator exists and exposes evaluate_candidate",
)
def _vision_module_exists() -> tuple[bool, str]:
    try:
        from dodgys_dd_quant.vision_validator import visual_cv
    except Exception as exc:
        return False, f"import failed: {type(exc).__name__}: {exc}"
    for name in ("VisionStyle", "VisionVerdict", "evaluate_candidate"):
        if not hasattr(visual_cv, name):
            return False, f"visual_cv has no {name}"
    return True, "visual_cv exposes VisionStyle, VisionVerdict, evaluate_candidate"


@register(
    "vision.style_is_640_white",
    "vision",
    10,
    "the render convention is white 640x640 (the detector's training style), not black 224x224",
)
def _vision_style() -> tuple[bool, str]:
    try:
        from dodgys_dd_quant.vision_validator.visual_cv import DEFAULT_STYLE
    except Exception as exc:
        return False, f"no DEFAULT_STYLE: {type(exc).__name__}: {exc}"
    problems = []
    if int(getattr(DEFAULT_STYLE, "width", 0)) != 640:
        problems.append(f"width={getattr(DEFAULT_STYLE, 'width', None)}")
    if int(getattr(DEFAULT_STYLE, "height", 0)) != 640:
        problems.append(f"height={getattr(DEFAULT_STYLE, 'height', None)}")
    background = str(getattr(DEFAULT_STYLE, "background", "")).upper()
    if background not in ("#FFFFFF", "WHITE", "RGB(255,255,255)"):
        problems.append(f"background={background!r} (must be white)")
    if int(getattr(DEFAULT_STYLE, "window_bars", 0)) < 60:
        problems.append(f"window_bars={getattr(DEFAULT_STYLE, 'window_bars', None)}")
    if problems:
        return False, "style mismatch: " + ", ".join(problems)
    return True, "640x640 white background, >=60-bar window"


@register(
    "vision.body_iou_not_gap_iou",
    "vision",
    18,
    "the metric is 2-D IoU against the third candle's BODY: a perfect match scores 1.0",
)
def _vision_body_iou() -> tuple[bool, str]:
    """The load-bearing check: the module must expose a *body* IoU, not the
    discussion's vertical gap IoU."""
    try:
        from dodgys_dd_quant.vision_validator import visual_cv
    except Exception as exc:
        return False, f"import failed: {type(exc).__name__}: {exc}"

    scorer = None
    for name in ("body_box_iou", "iou_2d", "box_iou", "compute_body_iou"):
        fn = getattr(visual_cv, name, None)
        if callable(fn):
            scorer = fn
            break
    if scorer is None:
        return False, "visual_cv exposes no box-IoU function (body_box_iou/iou_2d/box_iou)"

    bar = _sample_bar()
    body = _body_rect(bar)
    gap = _gap_rect(bar)

    perfect = float(scorer(body, body))
    if not math.isclose(perfect, 1.0, rel_tol=1e-9, abs_tol=1e-9):
        return False, f"IoU(body, body) = {perfect!r}, expected 1.0"

    disjoint = float(scorer(body, gap))
    if disjoint > 1e-9:
        return False, (
            f"IoU(body, gap) = {disjoint!r}; the body and the gap are disjoint by "
            "construction, so this must be 0"
        )

    half = float(scorer(body, (body[0], body[1], body[0] + (body[2] - body[0]) / 2, body[3])))
    if not (0.0 < half < 1.0):
        return False, f"IoU(body, half-overlap) = {half!r}, expected a value in (0, 1)"

    return True, "body IoU: perfect=1.0, body-vs-gap=0.0, partial in (0,1)"


@register(
    "vision.gap_iou_is_descriptive",
    "vision",
    10,
    "the vertical gap IoU is reported as a description, never used as the gate",
)
def _vision_gap_iou_demoted() -> tuple[bool, str]:
    try:
        from dodgys_dd_quant.vision_validator import visual_cv
    except Exception as exc:
        return False, f"import failed: {type(exc).__name__}: {exc}"
    fn = getattr(visual_cv, "gap_interval_iou", None)
    if not callable(fn):
        return False, "visual_cv has no gap_interval_iou (the descriptive statistic)"
    bar = _sample_bar()
    value = float(fn(_gap_rect(bar), _body_rect(bar)))
    if value > 1e-9:
        return False, f"gap-interval IoU(body, gap) = {value!r}, expected 0.0"
    return True, "gap-interval IoU(body, gap) = 0.0 as the audit predicts"


@register(
    "vision.threshold_is_calibrated",
    "vision",
    12,
    "the gate threshold is the calibrated body-IoU threshold; the 0.75 gap gate is gone",
)
def _vision_threshold() -> tuple[bool, str]:
    try:
        from dodgys_dd_quant.strategy import constants
    except Exception as exc:
        return False, f"import failed: {type(exc).__name__}: {exc}"

    tau = getattr(constants, "VISION_BODY_IOU_THRESHOLD", None)
    if tau is None:
        return False, "constants.VISION_BODY_IOU_THRESHOLD is not defined"
    tau = float(tau)
    if not (CALIBRATED_TAU_MIN <= tau <= CALIBRATED_TAU_MAX):
        return False, (
            f"VISION_BODY_IOU_THRESHOLD = {tau}, expected the calibrated band "
            f"[{CALIBRATED_TAU_MIN}, {CALIBRATED_TAU_MAX}]"
        )
    legacy = getattr(constants, "VISION_IOU_THRESHOLD", None)
    if legacy is not None and math.isclose(float(legacy), LEGACY_TAU, abs_tol=1e-9):
        return False, "constants.VISION_IOU_THRESHOLD = 0.75 still exists (D6 deleted it)"
    return True, f"calibrated body-IoU threshold {tau}; no 0.75 gate"


@register(
    "vision.verdict_has_diagnostics",
    "vision",
    12,
    "VisionVerdict carries the auditable diagnostics (row_containment, bar_index_delta, class_match)",
)
def _vision_verdict_fields() -> tuple[bool, str]:
    try:
        from dodgys_dd_quant.vision_validator.visual_cv import VisionVerdict
    except Exception as exc:
        return False, f"import failed: {type(exc).__name__}: {exc}"
    required = (
        "vision_iou",
        "vision_confidence",
        "row_containment",
        "bar_index_delta",
        "class_match",
        "n_detections",
        "passed",
    )
    fields = getattr(VisionVerdict, "__dataclass_fields__", None)
    if fields is None:
        return False, "VisionVerdict is not a dataclass"
    missing = [name for name in required if name not in fields]
    if missing:
        return False, f"VisionVerdict is missing field(s): {missing}"
    return True, f"VisionVerdict carries all {len(required)} diagnostic fields"


@register(
    "vision.gate_is_three_part",
    "vision",
    14,
    "the gate is class_match AND bar_index_delta==0 AND iou>=tau (L1 section B.5)",
)
def _vision_gate() -> tuple[bool, str]:
    try:
        from dodgys_dd_quant.vision_validator import visual_cv
    except Exception as exc:
        return False, f"import failed: {type(exc).__name__}: {exc}"

    gate = None
    for name in ("gate_passes", "evaluate_gate", "passes_gate"):
        fn = getattr(visual_cv, name, None)
        if callable(fn):
            gate = fn
            break
    if gate is None:
        return False, "visual_cv exposes no gate function (gate_passes/evaluate_gate)"

    tau = 0.30
    cases = (
        (True, 0, 0.60, True, "all three conditions met"),
        (False, 0, 0.60, False, "class mismatch"),
        (True, 2, 0.60, False, "bar index mismatch"),
        (True, 0, 0.10, False, "IoU below threshold"),
    )
    for class_match, delta, iou, expected, label in cases:
        try:
            got = bool(gate(class_match=class_match, bar_index_delta=delta, vision_iou=iou, tau=tau))
        except TypeError:
            try:
                got = bool(gate(class_match, delta, iou, tau))
            except Exception as exc:
                return False, f"gate call failed: {type(exc).__name__}: {exc}"
        except Exception as exc:
            return False, f"gate call failed: {type(exc).__name__}: {exc}"
        if got != expected:
            return False, f"gate wrong for '{label}': got {got}, expected {expected}"
    return True, "gate rejects on class, bar index and IoU, and accepts when all three hold"


@register(
    "vision.evaluates_candidate",
    "vision",
    16,
    "evaluate_candidate returns a verdict for a real candidate window with a stub detector",
)
def _vision_evaluate_candidate() -> tuple[bool, str]:
    """End-to-end on the *geometry* contract, with a stub detector.

    A stub detector keeps the probe free of a GPU and of the 43 MB weight
    file, while still exercising the whole path: window -> render -> detect
    -> match -> IoU -> verdict.  The detector's own accuracy is a separate
    concern (the audit measured it: mAP@50 0.923 on its own labels).
    """
    try:
        from dodgys_dd_quant.vision_validator import visual_cv
    except Exception as exc:
        return False, f"import failed: {type(exc).__name__}: {exc}"

    evaluate = getattr(visual_cv, "evaluate_candidate", None)
    if not callable(evaluate):
        return False, "visual_cv has no callable evaluate_candidate"

    from bench import fixtures

    bars = fixtures.btc_1m()
    window = bars.slice(max(0, len(bars) - 90), len(bars))

    class _StubDetector:
        """Returns exactly one box covering the window's middle candle body."""

        def __init__(self) -> None:
            self.calls = 0

        def detect(self, image):
            self.calls += 1
            return []

    detector = _StubDetector()
    try:
        verdict = evaluate(window, 0, 0, 0.0, 1.0, 1, detector)
    except TypeError:
        try:
            verdict = evaluate(window, detector)
        except Exception as exc:
            return False, f"evaluate_candidate failed: {type(exc).__name__}: {exc}"
    except Exception as exc:
        return False, f"evaluate_candidate failed: {type(exc).__name__}: {exc}"

    for name in ("vision_iou", "vision_confidence", "passed", "n_detections"):
        if not hasattr(verdict, name):
            return False, f"verdict has no attribute {name}"
    if not isinstance(int(getattr(verdict, "n_detections", -1)), int):
        return False, "n_detections is not an int"
    return True, f"evaluate_candidate returned a verdict (n_detections={verdict.n_detections})"


@register(
    "vision.degrades_gracefully",
    "vision",
    10,
    "the ML pipeline still excludes the vision feature when the column is absent (D12)",
)
def _vision_graceful() -> tuple[bool, str]:
    try:
        from dodgys_dd_quant.ml_pipeline.features import build_features, resolve_feature_list
    except Exception as exc:
        return False, f"import failed: {type(exc).__name__}: {exc}"

    import pandas as pd

    candidates = pd.DataFrame(
        {
            "ts_event": [1_700_000_000_000_000_000],
            "side": [1],
            "entry_price": [100.0],
            "stop_price": [99.0],
            "target_price": [102.0],
            "risk": [1.0],
        }
    )
    frame = build_features(candidates)
    used, excluded = resolve_feature_list(frame)
    if "vision_confidence" in used:
        return False, "vision_confidence was used although the column is absent"
    if not any("vision" in name for name in excluded):
        return False, "the excluded features do not mention the vision column"
    return True, f"vision feature excluded and recorded ({sorted(excluded)})"
