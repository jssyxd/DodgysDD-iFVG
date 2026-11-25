"""The vision layer: an offline batch feature extractor for the D2 log.

D12 fixes the role: the vision layer is **not** a gate and **not** on the
critical path.  It is a batch extractor that fills two columns of the frozen
D2 candidate log -- ``vision_iou`` and ``vision_confidence`` -- so that the
meta-labeler can *see* the vision signal if one wants it to, and so that the
alignment between the rule engine and the detector is measurable rather than
asserted.

What this package is **not**
---------------------------
It is not a trading signal, and it never changes a direction or a price
(INV2/INV3).  It measures one thing: *does an independent visual detector
localise the same bar the rule engine used?*  (D6's wording.)

The alignment contract (D6)
---------------------------
The audit established that the discussion's own metric is **inverted**: the
rule engine measures the FVG *price gap*, the shipped detector annotates the
*third candle's body*, and those two objects are **disjoint by construction**.
Under the discussion's literal metric a *perfect* detection therefore scores
**IoU = 0.00** (measured on the detector's own labels: median 0.0000, 87.9 %
exactly zero, 0.65 % above 0.75).

So the metric here is the **2-D box IoU against the third candle's body
rectangle**, where a perfect match scores 1.0, and the gate is three-part::

    pass  <=>  class_match AND bar_index_delta == 0 AND vision_iou >= tau

with ``tau`` **calibrated** rather than inherited: 0.75 would reject 98 % of
the detector's own correct labels, and 0.50 still rejects two thirds of them.
The band that admits most correct detections is ~0.30-0.35.

The 1-D vertical gap IoU is still computed and reported -- it is a useful
*sanity* number, because it should be ~0 for a correct match and a non-zero
value means the renderer and the rule engine disagree about the price axis --
but it is **never a gate**.
"""

from __future__ import annotations

from dodgys_dd_quant.vision_validator.visual_cv import (
    DEFAULT_STYLE,
    Detection,
    Detector,
    RenderedWindow,
    VisionStyle,
    VisionVerdict,
    body_box_iou,
    evaluate_candidate,
    gate_passes,
    gap_interval_iou,
    render_window,
)

__all__ = [
    "DEFAULT_STYLE",
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
