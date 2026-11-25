"""The rule-matrix rows that the audits still call *absent* (L2 §B, D-series).

Rows 8, 15, 26, 28 and the D-06 sweep object are the last implementable
gaps of the 30-row matrix: every other absent row needs a detector that no
artefact contains (row 24's order block) or is a reporting concern.

Each probe is behavioural: it drives the engine and asserts on the output.
"""

from __future__ import annotations

import math
from dataclasses import replace

from bench.probes import register

__all__ = []


def _engine():
    from dodgys_dd_quant.strategy.state_machine import PRESETS, run_state_machine

    return PRESETS, run_state_machine


def _bars():
    from bench import fixtures

    return fixtures.btc_1m()


@register(
    "rules.htf_confluence_gate",
    "rules",
    50,
    "the HTF-FVG confluence gate exists as a switch and reads the unreclaimed HTF zones (L2 row 8 / D-08)",
)
def _htf_confluence() -> tuple[bool, str]:
    """L2 row 8: ``onlyShowHtfAlignedIFVG``.

    The reference can require the setup to overlap an unreclaimed HTF FVG
    zone.  The gate is **off** at the reference's defaults, so the port must
    offer it as a switch that (a) changes the population and (b) is decided by
    the zones themselves -- recomputed here from the aggregated HTF series.
    """
    from dodgys_dd_quant.strategy.structure import aggregate_htf

    presets, run_state_machine = _engine()
    bars = _bars()
    off = list(run_state_machine(bars, presets["honest"]))
    if not off:
        return False, "no candidates to inspect"

    on = list(
        run_state_machine(
            bars, replace(presets["honest"], require_htf_alignment=True)
        )
    )
    if not on:
        return False, "the HTF confluence gate removed every candidate"
    if len(on) == len(off):
        return False, "the HTF confluence gate left the population unchanged"

    # The decision must come from the zones: recompute the overlap here.
    htf = aggregate_htf(bars, presets["honest"].htf_timeframe_minutes)
    wrong = 0
    aligned = 0
    for cand in on:
        zones = htf.zones_at(cand.confirm_bar)
        hit = any(
            zone.bottom <= cand.fvg_high and zone.top >= cand.fvg_low
            for zone in zones
        )
        aligned += int(hit)
        wrong += int(not hit)
    if wrong:
        return False, f"{wrong} gated candidates do not overlap a live HTF zone"
    if aligned != len(on):
        return False, f"only {aligned}/{len(on)} gated candidates overlap a zone"
    return True, (
        f"the gate keeps {len(on)}/{len(off)} candidates, all overlapping an "
        f"unreclaimed HTF zone"
    )


@register(
    "rules.setup_history_cap",
    "rules",
    50,
    "the setup-history cap stops managing an evicted unresolved setup (L2 row 28 / D-11)",
)
def _setup_history() -> tuple[bool, str]:
    """L2 row 28: the reference keeps only the last ``setupHistory`` setups.

    When a new setup is pushed, the oldest is shifted out of the history and
    removed from the live-trade array, so an unresolved setup **stops being
    managed** and never resolves.  The port must reproduce that side effect
    and keep the default (everything is managed).
    """
    presets, run_state_machine = _engine()
    bars = _bars()
    managed = list(run_state_machine(bars, presets["honest"]))
    if not managed:
        return False, "no candidates to inspect"
    if any(c.outcome == "unmanaged" for c in managed):
        return False, "the default arm leaves setups unmanaged"

    capped = list(
        run_state_machine(bars, replace(presets["honest"], setup_history_cap=2))
    )
    unmanaged = [c for c in capped if c.outcome == "unmanaged"]
    if not unmanaged:
        return False, "the setup-history cap left every setup managed"
    resolved_off = sum(1 for c in managed if c.outcome in ("stop", "target"))
    resolved_on = sum(1 for c in capped if c.outcome in ("stop", "target"))
    if resolved_on >= resolved_off:
        return False, (
            f"the cap did not reduce the managed population ({resolved_on} vs "
            f"{resolved_off})"
        )
    if len(capped) != len(managed):
        return False, "the cap erased setups instead of unmanaging them"
    return True, (
        f"a cap of 2 leaves {len(unmanaged)} setups unmanaged and resolves "
        f"{resolved_on} instead of {resolved_off}"
    )


@register(
    "rules.origin_bar_variants",
    "rules",
    40,
    "both readings of the reference's origin bar are implemented and reconciled (L2 row 15)",
)
def _origin_variants() -> tuple[bool, str]:
    """L2 row 15: the reference's origin sits one bar before the extreme.

    The audit asks for **both** variants to be ported and reconciled.  The
    price is the extreme either way; only the *published bar* differs, and it
    decides the window in which a sweep counts as leg-scoped.
    """
    presets, run_state_machine = _engine()
    bars = _bars()
    default = list(run_state_machine(bars, presets["honest"]))
    literal = list(
        run_state_machine(bars, replace(presets["honest"], origin_bar_offset=-1))
    )
    if not default or len(default) != len(literal):
        return False, "the two origin readings do not share a population"

    shifted = 0
    price_kept = 0
    checked = 0
    for a, b in zip(default, literal):
        if not math.isfinite(a.origin_price):
            continue
        checked += 1
        if a.origin_bar != b.origin_bar:
            shifted += 1
            if a.origin_bar - 1 != b.origin_bar:
                return False, (
                    f"the literal reading shifted the origin by "
                    f"{b.origin_bar - a.origin_bar} bars, expected -1"
                )
        if a.origin_price == b.origin_price:
            price_kept += 1
    if checked == 0:
        return False, "no candidate carries an origin to compare"
    if shifted == 0:
        return False, "the literal origin reading changed nothing"
    if price_kept != checked:
        return False, "the two readings disagree about the origin's price"
    return True, (
        f"{shifted}/{checked} origins move one bar back while keeping their level"
    )


@register(
    "rules.bias_filter_partitions",
    "rules",
    35,
    "the direction filter is unambiguous and partitions the neutral population (L2 row 26)",
)
def _bias_filter() -> tuple[bool, str]:
    """L2 row 26: the reference's bias switch.

    The reference's naming is inverted (``enableBearOutput`` gates the
    *bullish* tracker, which produces shorts), so the port names the switch
    after the **trade** direction.  The two arms must partition the neutral
    population exactly.
    """
    presets, run_state_machine = _engine()
    bars = _bars()
    neutral = list(run_state_machine(bars, presets["honest"]))
    if not neutral:
        return False, "no candidates to inspect"
    longs = list(run_state_machine(bars, replace(presets["honest"], bias="bullish")))
    shorts = list(run_state_machine(bars, replace(presets["honest"], bias="bearish")))
    if not longs or not shorts:
        return False, "a direction arm produced no candidates"
    if any(c.side != 1 for c in longs):
        return False, "the bullish arm kept a short"
    if any(c.side != -1 for c in shorts):
        return False, "the bearish arm kept a long"
    if len(longs) + len(shorts) != len(neutral):
        return False, (
            f"the arms hold {len(longs) + len(shorts)} candidates, the neutral "
            f"population is {len(neutral)}"
        )
    return True, (
        f"the direction arms partition the population: {len(longs)} long, "
        f"{len(shorts)} short"
    )


@register(
    "rules.sweep_object_is_htf_fractal",
    "rules",
    50,
    "the reference's sweep object is the HTF three-bar fractal with a strict pierce (audit D-06)",
)
def _htf_sweep_object() -> tuple[bool, str]:
    """Audit D-06: the two sweep detectors are different objects.

    The reference's levels are the **three-bar fractals of the hand-aggregated
    HTF series**, the pierce is **strict** (no body reclaim) and every pierced
    level is **consumed**.  The code-derived detector uses the same timeframe,
    a five-bar fractal and an added body-reclaim condition -- so the two arms
    must differ.
    """
    from dodgys_dd_quant.strategy.structure import aggregate_htf

    presets, run_state_machine = _engine()
    bars = _bars()
    htf_arm = list(
        run_state_machine(
            bars,
            replace(presets["honest"], sweep_source="htf_fractal", require_sweep=True),
        )
    )
    swing_arm = list(
        run_state_machine(
            bars, replace(presets["honest"], sweep_source="swings", require_sweep=True)
        )
    )
    if not htf_arm:
        return False, "the HTF-fractal sweep arm produced no candidates"
    if not swing_arm:
        return False, "the same-timeframe sweep arm produced no candidates"
    if len(htf_arm) == len(swing_arm):
        return False, "the two sweep objects select the same population"

    # The levels the HTF arm uses must be the HTF series' own fractals.
    htf = aggregate_htf(bars, presets["honest"].htf_timeframe_minutes)
    levels = {(round(float(l.price), 8), int(l.direction)) for l in htf.levels}
    if not levels:
        return False, "the aggregated HTF series published no fractal levels"

    htf_conf = {c.confirm_bar for c in htf_arm}
    swing_conf = {c.confirm_bar for c in swing_arm}
    if htf_conf == swing_conf:
        return False, "the two sweep objects select the same confirmations"

    # A strict pierce: some sweep closes beyond the level it pierced.
    from dodgys_dd_quant.strategy.state_machine import _sweep_events

    events = _sweep_events(
        bars,
        __import__(
            "dodgys_dd_quant.strategy.structure", fromlist=["causal_pivots"]
        ).causal_pivots(bars.high, bars.low, left=2, right=2),
        replace(presets["honest"], sweep_source="htf_fractal"),
        htf,
    )
    if not events:
        return False, "the HTF sweep detector produced no events"
    strict = 0
    for ev in events:
        close = float(bars.close[ev.bar])
        if ev.direction > 0 and close > ev.level:
            strict += 1
        elif ev.direction < 0 and close < ev.level:
            strict += 1
    if strict == 0:
        return False, "no sweep pierced its level without reclaiming it"
    unknown = [
        ev
        for ev in events
        if (round(float(ev.level), 8), int(ev.direction)) not in levels
    ]
    if unknown:
        return False, f"{len(unknown)} sweeps used a level that is not an HTF fractal"
    return True, (
        f"the HTF-fractal object selects {len(htf_arm)} candidates against "
        f"{len(swing_arm)} for the same-timeframe levels, {strict} strict pierces"
    )
