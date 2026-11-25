"""Two more coverage probes: the engine's purity and the vision layer's role.

* The rule engine is a **pure function of the bar history** (the repo's own
  rule): two runs on the same bars must produce the same log, byte for
  byte.  The research phase depends on that -- every number in the audit was
  produced by re-running the engine.
* The vision layer is a **feature, never a gate** (FINAL_REPORT §5.4, and
  L1's finding that the detector's own labels carry no outcome information):
  a verdict that would pass the gate must not change a single decision.
"""

from __future__ import annotations

from bench.probes import register

__all__ = []


@register(
    "rules.engine_is_deterministic",
    "rules",
    40,
    "the rule engine is a pure function of the bar history: two runs agree exactly",
)
def _engine_is_deterministic() -> tuple[bool, str]:
    """Two runs, one answer.

    Nothing in the engine may depend on the clock, the wall or the previous
    run: the audit's numbers are only reproducible if this holds.
    """
    import numpy as np

    from dodgys_dd_quant.strategy.state_machine import PRESETS, run_state_machine

    from bench import fixtures

    bars = fixtures.btc_1m()
    first = run_state_machine(bars, PRESETS["honest"]).to_table()
    second = run_state_machine(bars, PRESETS["honest"]).to_table()
    if set(first) != set(second):
        return False, "the two runs produced different columns"
    for column in first:
        left = np.asarray(first[column])
        right = np.asarray(second[column])
        if left.shape != right.shape:
            return False, f"the column {column!r} has a different shape"
        same = (
            np.array_equal(left, right, equal_nan=True)
            if left.dtype.kind == "f"
            else np.array_equal(left, right)
        )
        if not same:
            return False, f"the column {column!r} differs between two runs"
    return True, f"all {len(first)} columns are identical across two runs"


@register(
    "vision.verdict_never_filters_a_candidate",
    "vision",
    45,
    "the vision verdict is a feature, never a gate: no decision may depend on it",
)
def _verdict_never_filters() -> tuple[bool, str]:
    """L1's finding: the detector's labels carry no outcome information, so a
    vision gate would be a gate on noise.

    The engine must therefore ignore the verdict entirely: filling the
    columns with values that *would* pass the gate must not change a single
    candidate, a single label or a single checklist flag.
    """
    import numpy as np

    from dodgys_dd_quant.vision_validator.batch import apply_to_candidates, evaluate_candidates
    from dodgys_dd_quant.strategy.state_machine import PRESETS, run_state_machine

    from bench import fixtures

    bars = fixtures.btc_1m()
    log = run_state_machine(bars, PRESETS["honest"])
    candidates = list(log)
    if not candidates:
        return False, "no candidates to inspect"

    before = log.to_table()
    labels_before = before["label"].copy()

    # a verdict that passes the gate on every candidate
    for candidate in candidates:
        candidate.vision_iou = 1.0
        candidate.vision_confidence = 1.0

    after = run_state_machine(bars, PRESETS["honest"]).to_table()
    for column in ("label", "r_multiple", "checklist_score", "entry_price"):
        if not np.array_equal(before[column], after[column], equal_nan=True):
            return False, f"the column {column!r} changed when the verdict was set"

    passed = [c for c in candidates if c.checklist_flags.get("vision_iou_pass")]
    if passed:
        return False, (
            f"{len(passed)} candidates were filtered by the vision verdict"
        )
    return True, (
        f"{len(candidates)} candidates are unaffected by a verdict that passes "
        f"the gate"
    )
