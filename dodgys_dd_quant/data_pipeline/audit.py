"""The governed lake's own audit (the lake's five invariants).

The repository's context file says it plainly:

    *"Note: the lake's own auditor only tests ``volume < 0``, so it **cannot**
    detect a zero-volume non-flat bar -- verify that rule yourself."*

So this module is that verification.  The lake's contract (``AGENTS.md``,
"Lake governance, briefly") is:

1. the timestamps are **strictly monotonic** UTC;
2. there are **no duplicates**;
3. ``High >= max(Open, Close)`` and ``Low <= min(Open, Close)``;
4. the prices are **strictly positive**;
5. ``Volume >= 0`` -- **plus the flat-bar corollary**: a bar with no volume
   must be a flat bar (``Open == High == Low == Close``), because a
   zero-volume bar that moved is not an observation, it is a gap.

The audit **reports**; it never rewrites.  The caller decides what to do with
a partition that fails (the lake quarantines the offenders).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

__all__ = ["AuditReport", "audit_frame"]


@dataclass(frozen=True)
class AuditReport:
    """The outcome of one partition audit."""

    #: How many bars were audited.
    n_bars: int
    #: The invariant's violations, by name.
    violations: dict[str, int] = field(default_factory=dict)
    #: The first offending bar index per invariant (for the quarantine).
    first_offender: dict[str, int] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.violations

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_bars": self.n_bars,
            "passed": self.passed,
            "violations": dict(self.violations),
            "first_offender": dict(self.first_offender),
        }

    def reason(self) -> str:
        if self.passed:
            return f"{self.n_bars} bars pass every invariant"
        parts = ", ".join(
            f"{name}: {count}" for name, count in sorted(self.violations.items())
        )
        return f"{self.n_bars} bars violate {parts}"


def _column(frame: Any, name: str) -> np.ndarray:
    """A column of a frame (pandas-like or mapping-like)."""
    if hasattr(frame, "columns"):
        values = frame[name]
    else:
        values = frame[name]
    return np.asarray(values)


def audit_frame(frame: Any) -> AuditReport:
    """Audit one partition against the lake's five invariants.

    ``frame`` must carry ``ts`` (or ``timestamp``), ``open``, ``high``,
    ``low``, ``close`` and ``volume``.
    """
    if _has(frame, "ts"):
        ts = _column(frame, "ts")
    elif _has(frame, "ts_event"):
        # the lake's canonical name (int64 ms, per AGENTS.md)
        ts = _column(frame, "ts_event")
    else:
        ts = _column(frame, "timestamp")
    open_ = _column(frame, "open").astype(np.float64)
    high = _column(frame, "high").astype(np.float64)
    low = _column(frame, "low").astype(np.float64)
    close = _column(frame, "close").astype(np.float64)
    volume = _column(frame, "volume").astype(np.float64)

    n = int(ts.shape[0])
    violations: dict[str, int] = {}
    first: dict[str, int] = {}

    def record(name: str, mask: np.ndarray) -> None:
        count = int(mask.sum())
        if count:
            violations[name] = count
            first[name] = int(np.flatnonzero(mask)[0])

    # 1. strictly monotonic timestamps
    if n > 1:
        record("non_monotonic_ts", np.diff(ts.astype(np.int64)) <= 0)
    # 2. no duplicates (a non-monotonic series may also carry duplicates)
    if n > 1:
        _, counts = np.unique(ts.astype(np.int64), return_counts=True)
        duplicated = int((counts[counts > 1]).sum())
        if duplicated:
            violations["duplicate_ts"] = duplicated
    # 3. the high/low envelope
    record("high_below_body", high < np.maximum(open_, close))
    record("low_above_body", low > np.minimum(open_, close))
    # 4. strictly positive prices
    record("non_positive_price", ~(open_ > 0) | ~(high > 0) | ~(low > 0) | ~(close > 0))
    # 5. the volume and its flat-bar corollary
    record("negative_volume", volume < 0)
    flat = (open_ == high) & (high == low) & (low == close)
    record("zero_volume_non_flat_bar", (volume == 0) & ~flat)

    return AuditReport(
        n_bars=n,
        violations=violations,
        first_offender=first,
    )


def _has(frame: Any, name: str) -> bool:
    if hasattr(frame, "columns"):
        return name in list(frame.columns)
    try:
        return name in frame
    except TypeError:  # pragma: no cover - defensive
        return False
