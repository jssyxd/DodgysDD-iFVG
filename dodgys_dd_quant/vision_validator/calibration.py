"""Calibrating the vision gate's threshold (D6, L1 §C.4).

D6 says the body-IoU threshold must be *calibrated*, not inherited: the
discussion's ``0.75`` was written against a different object and is wrong
even against the correct one -- the detector's own ground truth scores a
median IoU of **0.393** against the true body rectangle, so ``0.75`` would
reject **98 %** of the model's own correct labels.

The audit measured the achievable distribution on the Kaggle test split
(524 boxes over 75 images):

| statistic | 2-D IoU(annotation box, true body rect) |
|---|---|
| median | 0.393 |
| p10 / p90 | 0.200 / 0.652 |
| fraction >= 0.30 | 72.1 % |
| fraction >= 0.40 | 49.2 % |
| fraction >= 0.50 | 33.0 % |
| fraction >= 0.75 | 2.1 % |

The pre-registered default is therefore **tau = 0.30** (the band that admits
most correct detections), and this module provides the *procedure* that
produced it: given a sample of body IoUs, report the threshold that admits a
given share of them, together with the acceptance curve.

The threshold is a **calibration input**, not a constant of nature: running
``calibrate_threshold`` on the real Kaggle test split is what would replace
the pre-registered default with a measured one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

__all__ = [
    "CalibrationReport",
    "calibrate_threshold",
    "acceptance_curve",
    "AUDIT_MEASURED_QUANTILES",
    "AUDIT_MEASURED_ACCEPTANCE",
]

#: The audit's measured quantiles of the body IoU (L1 §C.4).
AUDIT_MEASURED_QUANTILES: dict[str, float] = {
    "p10": 0.200,
    "p50": 0.393,
    "p90": 0.652,
}

#: The audit's measured acceptance of a threshold: the share of the model's
#: own correct labels that a detector at that IoU would pass.
AUDIT_MEASURED_ACCEPTANCE: dict[float, float] = {
    0.30: 0.721,
    0.40: 0.492,
    0.50: 0.330,
    0.75: 0.021,
}

#: The pre-registered default: the band that admits most correct detections.
PRE_REGISTERED_THRESHOLD: float = 0.30


@dataclass(frozen=True)
class CalibrationReport:
    """The outcome of one calibration."""

    #: The threshold that admits ``acceptance`` of the sample.
    threshold: float
    #: The share of the sample the threshold admits.
    acceptance: float
    #: The number of samples the calibration was run on.
    n_samples: int
    #: The sample's quantiles (p10, p50, p90).
    quantiles: dict[str, float]
    #: The acceptance curve: ``(threshold, fraction admitted)`` pairs, sorted
    #: by the threshold.
    curve: tuple[tuple[float, float], ...]

    def as_dict(self) -> dict:
        return {
            "threshold": self.threshold,
            "acceptance": self.acceptance,
            "n_samples": self.n_samples,
            "quantiles": dict(self.quantiles),
            "curve": [list(pair) for pair in self.curve],
        }


def _clean(samples: Iterable[float]) -> np.ndarray:
    values = np.asarray(list(samples), dtype=np.float64)
    return values[np.isfinite(values)]


def acceptance_curve(
    samples: Iterable[float],
    thresholds: Sequence[float],
) -> tuple[tuple[float, float], ...]:
    """The share of ``samples`` at or above each threshold.

    The curve is monotone non-increasing in the threshold by construction:
    a stricter threshold can only admit fewer samples.
    """
    values = _clean(samples)
    if values.size == 0:
        return tuple((float(t), float("nan")) for t in thresholds)
    ordered = sorted({float(t) for t in thresholds})
    out = []
    for threshold in ordered:
        admitted = float((values >= threshold).sum()) / float(values.size)
        out.append((threshold, admitted))
    return tuple(out)


def calibrate_threshold(
    samples: Iterable[float],
    *,
    acceptance: float = 0.721,
    curve_thresholds: Sequence[float] | None = None,
) -> CalibrationReport:
    """The threshold that admits ``acceptance`` of the measured IoUs.

    The threshold is the sample's ``1 - acceptance`` quantile: the share of
    the sample at or above it is the requested acceptance.  ``acceptance=1.0``
    returns the sample's minimum and ``acceptance=0.0`` its maximum.
    """
    if not 0.0 < float(acceptance) <= 1.0:
        raise ValueError("acceptance must be in (0, 1]")
    values = _clean(samples)
    if values.size == 0:
        raise ValueError("no finite samples to calibrate on")
    quantile = 1.0 - float(acceptance)
    threshold = float(np.quantile(values, quantile, method="linear"))
    admitted = float((values >= threshold).sum()) / float(values.size)
    if curve_thresholds is None:
        curve_thresholds = (0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.75)
    quantiles = {
        "p10": float(np.quantile(values, 0.10, method="linear")),
        "p50": float(np.quantile(values, 0.50, method="linear")),
        "p90": float(np.quantile(values, 0.90, method="linear")),
    }
    return CalibrationReport(
        threshold=threshold,
        acceptance=admitted,
        n_samples=int(values.size),
        quantiles=quantiles,
        curve=acceptance_curve(values, curve_thresholds),
    )
