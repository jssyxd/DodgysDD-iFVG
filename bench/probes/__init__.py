"""Probe registry for the benchmark.

A *probe* is one executable, objective assertion about the repository's
behaviour.  Probes are grouped into **areas**; each area maps to one of the
five questions the project must answer:

============  ==========================================================
area          question
============  ==========================================================
``vision``    Q1/Q2 -- visual detection and the rule/vision alignment
``rules``     Q3    -- faithful reproduction of DodgysDD's rule set
``regime``    Q4    -- the volatility regime is correlated and wired in
``rolling``   Q5    -- data sufficiency and the rolling ML/RL/e2e stack
============  ==========================================================

Two kinds of probe exist, and the difference is load-bearing:

**capability probes**
    A feature that is *not implemented yet*.  Failing lowers the score;
    it does not fail the run.  These are the levers the optimisation loop
    pulls.

**invariant probes**
    A property that must hold *at all times* -- no-look-ahead, no signal
    erasure, one-position-at-a-time, the frozen D2 schema.  A violated
    invariant is a regression, and it makes the benchmark **exit
    non-zero**.  Optimisation must never be able to buy points by
    breaking the system.

The registry is deliberately tiny: a probe is a callable that returns
``(ok, detail)`` and raises nothing (exceptions are caught and reported
as failures with the exception text).
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Callable

__all__ = [
    "Probe",
    "AREA_QUESTIONS",
    "register",
    "all_probes",
    "probe_by_id",
    "area_weights",
]

#: The five questions each area answers.  Kept as data so the report can
#: print the mapping instead of leaving it in prose.
AREA_QUESTIONS: dict[str, str] = {
    "vision": "Q1+Q2",
    "rules": "Q3",
    "regime": "Q4",
    "rolling": "Q5",
}

ProbeFn = Callable[[], tuple[bool, str]]


@dataclass(frozen=True)
class Probe:
    """One executable assertion."""

    probe_id: str
    area: str
    weight: int
    description: str
    fn: ProbeFn
    invariant: bool = False


_REGISTRY: dict[str, Probe] = {}


def register(
    probe_id: str,
    area: str,
    weight: int,
    description: str,
    *,
    invariant: bool = False,
) -> Callable[[ProbeFn], ProbeFn]:
    """Register a probe.  Usable as a decorator."""

    def decorate(fn: ProbeFn) -> ProbeFn:
        if probe_id in _REGISTRY:
            raise ValueError(f"duplicate probe id: {probe_id}")
        _REGISTRY[probe_id] = Probe(
            probe_id=probe_id,
            area=area,
            weight=weight,
            description=description,
            fn=fn,
            invariant=invariant,
        )
        return fn

    return decorate


def all_probes() -> list[Probe]:
    """Every registered probe, in a stable order."""
    return sorted(_REGISTRY.values(), key=lambda p: (p.area, p.probe_id))


def probe_by_id(probe_id: str) -> Probe | None:
    return _REGISTRY.get(probe_id)


def area_weights() -> dict[str, int]:
    """Total weight per area."""
    totals: dict[str, int] = {}
    for probe in _REGISTRY.values():
        totals[probe.area] = totals.get(probe.area, 0) + probe.weight
    return totals


def run_probe(probe: Probe) -> tuple[bool, str]:
    """Execute a probe, converting any exception into a failure."""
    try:
        ok, detail = probe.fn()
    except Exception as exc:  # noqa: BLE001 -- a broken feature is a failure
        return False, f"raised {type(exc).__name__}: {exc}"
    return bool(ok), str(detail)


def format_failure(probe: Probe, detail: str) -> str:
    """A one-line, human-readable failure record."""
    return f"FAIL {probe.area}/{probe.probe_id} (w{probe.weight}): {detail}"


__all__ += ["run_probe", "format_failure", "traceback"]
