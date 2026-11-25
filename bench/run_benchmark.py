"""The benchmark runner.

Prints the primary metric and the secondary metrics in the ``METRIC name=value``
form the harness expects, and exits non-zero when an **invariant** is
violated.

The primary metric is ``capability_score``: the weighted fraction of the
capability probes that pass.  It answers the question the project actually
has open -- *how much of the specified system is implemented and verified?* --
rather than a profit number, which the audits have already shown to be noise
around zero (D4: every 95 % CI includes zero, PF <= 1.051).

Two guards keep the score honest:

1. **Invariants are separate.**  A probe marked ``invariant`` must pass.  A
   violation exits non-zero: optimisation may add capabilities, it may never
   buy them by breaking the system (no look-ahead, no erased signals, the
   frozen D2 schema, one position at a time).
2. **The probes test behaviour, not structure.**  Each probe exercises the
   engine or the pipeline and asserts on the *output*, so a flag that nobody
   reads, or a value that never reaches the decision, earns nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bench.probes import (  # noqa: E402
    AREA_QUESTIONS,
    all_probes,
    area_weights,
    format_failure,
    run_probe,
)
from bench.probes import regime as _regime  # noqa: F401,E402
from bench.probes import regime_extra as _regime_extra  # noqa: F401,E402
from bench.probes import regime_extra2 as _regime_extra2  # noqa: F401,E402
from bench.probes import regime_extra3 as _regime_extra3  # noqa: F401,E402
from bench.probes import regime_extra4 as _regime_extra4  # noqa: F401,E402
from bench.probes import rolling as _rolling  # noqa: F401,E402
from bench.probes import rolling_extra as _rolling_extra  # noqa: F401,E402
from bench.probes import rolling_extra2 as _rolling_extra2  # noqa: F401,E402
from bench.probes import rolling_extra3 as _rolling_extra3  # noqa: F401,E402
from bench.probes import rolling_extra4 as _rolling_extra4  # noqa: F401,E402
from bench.probes import rolling_extra5 as _rolling_extra5  # noqa: F401,E402
from bench.probes import rolling_extra6 as _rolling_extra6  # noqa: F401,E402
from bench.probes import rolling_extra7 as _rolling_extra7  # noqa: F401,E402
from bench.probes import rolling_extra8 as _rolling_extra8  # noqa: F401,E402
from bench.probes import rolling_extra9 as _rolling_extra9  # noqa: F401,E402
from bench.probes import rolling_extra10 as _rolling_extra10  # noqa: F401,E402
from bench.probes import rolling_extra11 as _rolling_extra11  # noqa: F401,E402
from bench.probes import rolling_extra12 as _rolling_extra12  # noqa: F401,E402
from bench.probes import rolling_extra13 as _rolling_extra13  # noqa: F401,E402
from bench.probes import rolling_extra14 as _rolling_extra14  # noqa: F401,E402
from bench.probes import rolling_extra15 as _rolling_extra15  # noqa: F401,E402
from bench.probes import rules as _rules  # noqa: F401,E402
from bench.probes import rules_extra as _rules_extra  # noqa: F401,E402
from bench.probes import rules_extra2 as _rules_extra2  # noqa: F401,E402
from bench.probes import rules_extra3 as _rules_extra3  # noqa: F401,E402
from bench.probes import vision as _vision  # noqa: F401,E402
from bench.probes import vision_extra as _vision_extra  # noqa: F401,E402

__all__ = ["main", "run"]


def _emit(name: str, value: float) -> None:
    print(f"METRIC {name}={value}")


def run(verbose: bool = True) -> dict:
    """Run every probe and return the report dictionary."""
    started = time.time()
    probes = all_probes()
    totals = area_weights()

    area_earned: dict[str, int] = {area: 0 for area in totals}
    area_possible: dict[str, int] = dict(totals)
    failures: list[str] = []
    invariant_failures: list[str] = []
    passed = 0

    for probe in probes:
        ok, detail = run_probe(probe)
        if ok:
            passed += 1
            area_earned[probe.area] = area_earned.get(probe.area, 0) + probe.weight
        else:
            failures.append(format_failure(probe, detail))
            if probe.invariant:
                invariant_failures.append(format_failure(probe, detail))
        if verbose:
            status = "PASS" if ok else "FAIL"
            kind = "invariant" if probe.invariant else "capability"
            print(
                f"  [{status}] {probe.area:<8} {probe.probe_id:<44} "
                f"w={probe.weight:<3} ({kind}) {detail}",
                file=sys.stderr,
            )

    earned = sum(area_earned.values())
    possible = sum(area_possible.values())
    score = earned / possible if possible else 0.0

    if verbose:
        print("", file=sys.stderr)
        for area in sorted(area_possible):
            got = area_earned.get(area, 0)
            print(
                f"  {area:<8} (Q{AREA_QUESTIONS.get(area, '?')}): "
                f"{got}/{area_possible[area]} points",
                file=sys.stderr,
            )
        print("", file=sys.stderr)

    _emit("capability_score", round(score, 6))
    _emit("capability_points", earned)
    _emit("capability_points_total", possible)
    for area in sorted(area_possible):
        got = area_earned.get(area, 0)
        _emit(f"points_{area}", got)
        _emit(f"points_{area}_total", area_possible[area])
    _emit("probes_passed", passed)
    _emit("probes_total", len(probes))
    _emit("invariant_failures", len(invariant_failures))
    _emit("runtime_s", round(time.time() - started, 3))

    return {
        "score": score,
        "points": earned,
        "points_total": possible,
        "area_points": area_earned,
        "area_points_total": area_possible,
        "probes_passed": passed,
        "probes_total": len(probes),
        "failures": failures,
        "invariant_failures": invariant_failures,
        "runtime_s": round(time.time() - started, 3),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m bench.run_benchmark",
        description="Run the capability benchmark and print METRIC lines.",
    )
    parser.add_argument("--json", type=Path, default=None, help="write the report as JSON")
    parser.add_argument("--quiet", action="store_true", help="suppress the per-probe log")
    args = parser.parse_args(argv)

    report = run(verbose=not args.quiet)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    if report["invariant_failures"]:
        print(
            f"INVARIANT VIOLATION: {len(report['invariant_failures'])} invariant(s) failed",
            file=sys.stderr,
        )
        for line in report["invariant_failures"]:
            print(f"  {line}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
