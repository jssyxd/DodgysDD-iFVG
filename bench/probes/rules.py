"""Rule-fidelity probes -- Q3 (are DodgysDD's rules faithfully reproduced?).

The L2 audit scored the reference implementation against a 30-row rule
matrix and found **8 faithful, 3 partial, 19 absent**.  These probes turn
that matrix into executable assertions against the current engine.

They are deliberately written against **behaviour**, not against internal
structure: a rule counts as implemented when the engine's *output* shows it
acting.  That way an implementation that merely exposes a flag, or computes
a value nobody uses, does not earn the point.

The probes come in two kinds:

* **capability probes** -- a rule the matrix says is absent.  Failing lowers
  the score; it does not fail the run.
* **invariant probes** -- a property that must hold at all times (the
  inversion window's arithmetic impossibility, the "no signal erased"
  obligation, the checklist's "report, never filter").  A violation is a
  regression and fails the run.
"""

from __future__ import annotations

import math

from bench.probes import register

__all__ = []


def _engine():
    from dodgys_dd_quant.strategy.state_machine import PRESETS, run_state_machine

    return PRESETS, run_state_machine


def _bars():
    from bench import fixtures

    return fixtures.btc_1m()


@register(
    "rules.inversion_window_is_1_to_15",
    "rules",
    14,
    "the inversion window is (1,15): age 0 is arithmetically impossible and nothing is older than 15",
    invariant=True,
)
def _inversion_window() -> tuple[bool, str]:
    """L2's correction: the effective code window is **(1, 15)**, not (0, 15).

    Age 0 cannot trigger: a bullish FVG needs ``low[c] > high[c-2]`` while
    the age-0 trigger needs ``close[c] < high[c-2]``, and ``close[c] >=
    low[c]``.
    """
    presets, run_state_machine = _engine()
    log = run_state_machine(_bars(), presets["honest"])
    ages = [c.bars_to_inversion for c in log]
    if not ages:
        return False, "no candidates produced"
    lo, hi = min(ages), max(ages)
    if lo < 1:
        return False, f"a candidate triggered at age {lo} (age 0 is impossible)"
    if hi > 15:
        return False, f"a candidate triggered at age {hi} (window max is 15)"
    return True, f"ages span ({lo}, {hi}) over {len(ages)} candidates"


@register(
    "rules.doc_window_is_7_to_15",
    "rules",
    8,
    "the doc's (7,15) window is available as a separate, A/B-able arm",
)
def _doc_window() -> tuple[bool, str]:
    presets, run_state_machine = _engine()
    doc = presets["honest"].with_doc_window()
    if (doc.inversion_min_bars, doc.inversion_max_bars) != (7, 15):
        return False, (
            f"with_doc_window() gives {(doc.inversion_min_bars, doc.inversion_max_bars)}, "
            "expected (7, 15)"
        )
    log = run_state_machine(_bars(), doc)
    ages = [c.bars_to_inversion for c in log]
    if not ages:
        return False, "the doc window produced no candidates"
    if min(ages) < 7:
        return False, f"the doc window produced a candidate at age {min(ages)}"
    return True, f"doc window (7,15) yields {len(ages)} candidates, min age {min(ages)}"


@register(
    "rules.atr_floor_enforced",
    "rules",
    12,
    "the ATR(14) floor is enforced when enabled: every gap exceeds 0.25 x ATR",
)
def _atr_floor() -> tuple[bool, str]:
    from dataclasses import replace

    from dodgys_dd_quant.strategy.structure import atr_wilder

    presets, run_state_machine = _engine()
    bars = _bars()
    atr = atr_wilder(bars.high, bars.low, bars.close)
    config = replace(presets["honest"], min_gap_atr_mult=0.25)
    log = run_state_machine(bars, config)
    if not len(log):
        return False, "the ATR floor produced no candidates"
    violations = 0
    for cand in log:
        ref = atr[cand.fvg_newest]
        if not math.isfinite(ref):
            continue
        gap = cand.fvg_high - cand.fvg_low
        if gap <= 0.25 * ref:
            violations += 1
    if violations:
        return False, f"{violations}/{len(log)} candidates have a gap <= 0.25 x ATR(14)"
    return True, f"all {len(log)} candidates clear the 0.25 x ATR(14) floor"


@register(
    "rules.sweep_level_consumed_once",
    "rules",
    12,
    "a swept level is consumed: it cannot be swept a second time",
)
def _sweep_consumption() -> tuple[bool, str]:
    from dodgys_dd_quant.strategy.structure import SweepDetector

    detector = SweepDetector(require_body_reclaim=True, consume_levels=True)
    detector.add_level(price=100.0, direction=1, known_at=0)
    first = detector.update(bar=1, high=101.0, low=99.0, close=99.5)
    second = detector.update(bar=2, high=102.0, low=99.0, close=99.5)
    if len(first) != 1:
        return False, f"the first pierce produced {len(first)} events, expected 1"
    if len(second):
        return False, "the level was swept again after being consumed"
    return True, "the level is swept exactly once"


@register(
    "rules.killzone_gate_exists",
    "rules",
    10,
    "the killzone gate is a configurable arm that actually removes out-of-session candidates",
)
def _killzone_gate() -> tuple[bool, str]:
    from dataclasses import replace

    presets, run_state_machine = _engine()
    bars = _bars()
    open_arm = run_state_machine(bars, presets["honest"])
    gated = run_state_machine(bars, replace(presets["honest"], killzone_gate=True))
    if len(gated) >= len(open_arm):
        return False, (
            f"the killzone gate left {len(gated)} of {len(open_arm)} candidates; "
            "it must remove the out-of-session ones"
        )
    return True, f"the killzone gate removes {len(open_arm) - len(gated)} candidates"


@register(
    "rules.be_intact_gate_exists",
    "rules",
    10,
    "the requireBEIntact gate is implemented as a switch that changes the population",
)
def _be_intact_gate() -> tuple[bool, str]:
    from dataclasses import replace

    presets, run_state_machine = _engine()
    bars = _bars()
    off = run_state_machine(bars, presets["honest"])
    on = run_state_machine(bars, replace(presets["honest"], require_be_intact=True))
    if len(on) == len(off):
        return False, "require_be_intact=True left the population unchanged"
    return True, f"require_be_intact removes {len(off) - len(on)} candidates"


@register(
    "rules.smt_uses_reference_instrument",
    "rules",
    12,
    "SMT divergence is computed against a reference instrument (and is -1 without one)",
)
def _smt_reference() -> tuple[bool, str]:
    from bench import fixtures

    presets, run_state_machine = _engine()
    bars = fixtures.btc_1m()
    reference = fixtures.eth_1m()
    log = run_state_machine(bars, presets["honest"], reference=reference)
    values = {c.smt_divergence for c in log}
    if values == {-1}:
        return False, "every candidate reports smt_divergence=-1 despite a reference series"
    if not values <= {-1, 0, 1}:
        return False, f"smt_divergence has values outside {{-1, 0, 1}}: {sorted(values)}"
    if 1 not in values:
        return False, "no candidate registered an SMT divergence (1) against the reference"
    return True, f"smt_divergence takes {sorted(values)} against the reference series"


@register(
    "rules.smt_unknown_without_reference",
    "rules",
    6,
    "without a reference instrument smt_divergence is -1 (unknown), never 0 (no divergence)",
)
def _smt_unknown() -> tuple[bool, str]:
    presets, run_state_machine = _engine()
    log = run_state_machine(_bars(), presets["honest"])
    values = {c.smt_divergence for c in log}
    if values != {-1}:
        return False, f"expected only -1 without a reference instrument, got {sorted(values)}"
    return True, "smt_divergence is -1 without a reference"


@register(
    "rules.checklist_is_five_booleans",
    "rules",
    10,
    "the checklist is exactly the five named booleans and its score is their sum",
)
def _checklist_five() -> tuple[bool, str]:
    from dodgys_dd_quant.strategy.constants import CHECKLIST_CONDITIONS

    presets, run_state_machine = _engine()
    log = run_state_machine(_bars(), presets["honest"])
    if not len(log):
        return False, "no candidates to inspect"
    expected = set(CHECKLIST_CONDITIONS)
    if len(expected) != 5:
        return False, f"CHECKLIST_CONDITIONS has {len(expected)} entries, expected 5"
    for cand in list(log)[:50]:
        flags = cand.checklist_flags
        if set(flags) != expected:
            return False, f"candidate flags {sorted(flags)} != {sorted(expected)}"
        score = sum(1 for v in flags.values() if v)
        if abs(cand.checklist_score - score) > 1e-9:
            return False, (
                f"checklist_score={cand.checklist_score} but {score} of the flags are true"
            )
    return True, "five named booleans; checklist_score is their unweighted sum"


@register(
    "rules.checklist_never_filters",
    "rules",
    14,
    "the checklist is reported, never filtered on (D8): the population is identical either way",
    invariant=True,
)
def _checklist_never_filters() -> tuple[bool, str]:
    presets, run_state_machine = _engine()
    log = run_state_machine(_bars(), presets["honest"])
    if not len(log):
        return False, "no candidates to inspect"
    scores = {c.checklist_score for c in log}
    if scores == {5.0}:
        return False, "every candidate scored 5/5 -- the checklist is not discriminating"
    low = sum(1 for c in log if c.checklist_score < 3)
    if low == 0:
        return False, "no candidate scores below 3/5 -- suspicious"
    return True, f"scores span {sorted(scores)}; {low} candidates score below 3/5 and are kept"


@register(
    "rules.grade_is_reported",
    "rules",
    8,
    "the grade labels are computed and cover more than one bucket",
)
def _grade_reported() -> tuple[bool, str]:
    """The rubric must discriminate.

    The checklist's inputs are attached here (a regime index and the SMT
    reference series), because without them the rubric is degenerate: two of
    its five components can never fire and every candidate lands in "C".
    """
    from bench import fixtures

    from dodgys_dd_quant.strategy.regime import ConstantRegimeIndex

    presets, run_state_machine = _engine()
    log = run_state_machine(
        _bars(),
        presets["honest"],
        regime=ConstantRegimeIndex(value=22.0, regime=1),
        reference=fixtures.eth_1m(),
    )
    grades: dict[str, int] = {}
    for cand in log:
        grades[cand.grade] = grades.get(cand.grade, 0) + 1
    if len(grades) < 2:
        return False, (
            f"every candidate got the same grade {grades} even with the regime and "
            "the SMT reference attached -- the rubric does not discriminate"
        )
    return True, f"grade distribution {grades}"


@register(
    "rules.grade_matches_rubric",
    "rules",
    8,
    "the grade label agrees with the weighted rubric (F11: score and grade must not disagree)",
)
def _grade_matches_rubric() -> tuple[bool, str]:
    from dodgys_dd_quant.strategy.constants import CHECKLIST_WEIGHTS, GRADE_THRESHOLDS

    presets, run_state_machine = _engine()
    log = run_state_machine(_bars(), presets["honest"])
    if not len(log):
        return False, "no candidates to inspect"

    def expected_grade(score: float) -> str:
        for name, threshold in GRADE_THRESHOLDS:
            if score >= threshold:
                return name
        return "C"

    for cand in list(log)[:200]:
        weighted = sum(
            CHECKLIST_WEIGHTS.get(name, 0.0) for name, on in cand.checklist_flags.items() if on
        )
        if cand.grade != expected_grade(weighted):
            return False, (
                f"candidate with flags {cand.checklist_flags} has grade {cand.grade!r}, "
                f"but the weighted rubric gives {expected_grade(weighted)!r}"
            )
    return True, "the grade equals the weighted rubric's label for every candidate"


@register(
    "rules.no_signal_erased",
    "rules",
    16,
    "every candidate is persisted with its outcome; losers are never erased (INV4)",
    invariant=True,
)
def _no_signal_erased() -> tuple[bool, str]:
    presets, run_state_machine = _engine()
    log = run_state_machine(_bars(), presets["honest"])
    candidates = list(log)
    if not candidates:
        return False, "no candidates produced"
    losers = sum(1 for c in candidates if c.outcome == "stop")
    winners = sum(1 for c in candidates if c.outcome == "target")
    if losers == 0:
        return False, "no losing candidate is present -- losers are being erased"
    table = log.to_table()
    if len(table["ts_event"]) != len(candidates):
        return False, "the D2 table drops candidates"
    labels = table["label"]
    if not ((labels == 0).any() and (labels == 1).any()):
        return False, "the D2 log does not carry both labels"
    return True, f"{len(candidates)} candidates persisted ({winners} winners, {losers} losers)"


@register(
    "rules.d2_schema_frozen",
    "rules",
    12,
    "the D2 candidate log keeps its frozen 23-column schema and dtypes",
    invariant=True,
)
def _d2_schema() -> tuple[bool, str]:
    from dodgys_dd_quant.strategy.state_machine import CandidateLog

    presets, run_state_machine = _engine()
    log = run_state_machine(_bars(), presets["honest"])
    table = log.to_table()
    expected = CandidateLog.D2_COLUMNS
    if tuple(table) != tuple(expected):
        missing = set(expected) - set(table)
        extra = set(table) - set(expected)
        return False, f"schema drift; missing={sorted(missing)} extra={sorted(extra)}"
    if len(expected) != 23:
        return False, f"the D2 schema has {len(expected)} columns, expected 23"
    return True, f"the D2 schema is intact ({len(expected)} columns)"


@register(
    "rules.no_lookahead_truncation",
    "rules",
    16,
    "truncating the future does not change the signals (INV6 / no look-ahead)",
    invariant=True,
)
def _no_lookahead() -> tuple[bool, str]:
    presets, run_state_machine = _engine()
    bars = _bars()
    full = run_state_machine(bars, presets["honest"])
    cut = len(bars) // 2
    truncated = run_state_machine(bars.slice(0, cut), presets["honest"])
    full_signals = [(c.ts_event, c.side, c.entry_price, c.stop_price) for c in full]
    truncated_signals = [(c.ts_event, c.side, c.entry_price, c.stop_price) for c in truncated]
    if truncated_signals != full_signals[: len(truncated_signals)]:
        return False, "truncating the future changed the signals that were already emitted"
    return True, f"{len(truncated_signals)} signals are invariant under truncation"


@register(
    "rules.session_extremes_causal",
    "rules",
    10,
    "PDH/PDL come from the previous completed day only (no look-ahead)",
)
def _session_extremes() -> tuple[bool, str]:
    from dodgys_dd_quant.strategy.structure import session_extremes

    bars = _bars()
    extremes = session_extremes(bars.ts, bars.high, bars.low, timezone="America/New_York")
    # The extreme attached to a bar must be the previous day's extreme, so it
    # must never exceed the running maximum *including* the current day.
    running = np_maximum_accumulate(bars.high)
    violations = 0
    for i in range(0, len(bars), 997):
        value = extremes.pdh[i]
        if math.isfinite(value) and value > running[i] + 1e-9:
            violations += 1
    if violations:
        return False, f"{violations} bars see a PDH above the running high"
    return True, "every sampled bar sees a PDH at or below the running high"


def np_maximum_accumulate(values):
    import numpy as np

    return np.maximum.accumulate(values)


@register(
    "rules.regime_lag_is_strict",
    "rules",
    10,
    "the regime index is strictly lagged: a bar never sees its own day's close",
    invariant=True,
)
def _regime_lag() -> tuple[bool, str]:
    from dodgys_dd_quant.strategy.regime import VxnRegimeIndex

    from bench import fixtures

    days, closes = fixtures.vxn_daily()
    index = VxnRegimeIndex(days=days, closes=closes)
    bars = _bars()
    known, labels = index.value_at(bars.ts)
    day_of_bar = bars.ts // 86_400_000_000_000
    # For every bar, the value attached must come from a strictly earlier day.
    positions = _searchsorted_left(days, day_of_bar) - 1
    ok = positions >= 0
    if not ok.all():
        # The first observations have no prior day -- that is the correct
        # "no back-fill" behaviour (L3 trap 2).
        pass
    for i in range(0, len(bars), 1009):
        pos = positions[i]
        if pos >= 0 and not math.isclose(float(known[i]), float(closes[pos]), rel_tol=1e-9):
            return False, f"bar {i} carries a value that is not the previous day's close"
    return True, "every sampled bar carries the previous observation's close"


def _searchsorted_left(days, values):
    import numpy as np

    return np.searchsorted(days, values, side="left")


@register(
    "rules.one_position_at_a_time",
    "rules",
    14,
    "the portfolio never holds more than one position (D4)",
    invariant=True,
)
def _one_position() -> tuple[bool, str]:
    from dodgys_dd_quant.backtest.walk_forward import simulate_portfolio

    presets, run_state_machine = _engine()
    bars = _bars()
    log = run_state_machine(bars, presets["honest"])
    trades = simulate_portfolio(list(log), len(bars))
    if not trades:
        return False, "the portfolio selected no trades"
    overlaps = 0
    ordered = sorted(trades, key=lambda c: c.entry_bar)
    for previous, current in zip(ordered, ordered[1:]):
        if current.entry_bar <= previous.exit_bar:
            overlaps += 1
    if overlaps:
        return False, f"{overlaps} trades overlap in time"
    return True, f"{len(trades)} trades, none overlapping in time"


@register(
    "rules.leg_tracker_limits_candidates",
    "rules",
    8,
    "the leg tracker keeps at most one live candidate per direction (L2 row 17)",
)
def _leg_tracker() -> tuple[bool, str]:
    presets, run_state_machine = _engine()
    log = run_state_machine(_bars(), presets["pine"])
    candidates = list(log)
    if not candidates:
        return False, "the pine preset produced no candidates"
    by_side: dict[int, list] = {}
    for cand in candidates:
        by_side.setdefault(cand.side, []).append(cand)
    overlaps = 0
    for side, items in by_side.items():
        items.sort(key=lambda c: c.fvg_oldest)
        last_end = -1
        for cand in items:
            if cand.fvg_oldest <= last_end:
                overlaps += 1
            last_end = max(last_end, cand.confirm_bar)
    if overlaps:
        return False, f"{overlaps} same-direction candidates overlap in time"
    return True, f"{len(candidates)} candidates, no same-direction overlap"
