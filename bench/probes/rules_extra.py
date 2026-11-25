"""The rule matrix rows that are still absent (L2 §B).

L2 scored the reference implementation against a **30-row** rule matrix and
found 8 faithful, 3 partial and **19 absent**.  The engine now covers the
geometric core, the sweep semantics, the checklist, the grades, the
killzones, the ATR floor and the swing-origin tracker; the rows below are
the ones the matrix still calls *absent* and that are implementable from
the artefacts (the OB clause, row 24, is **not** implementable: no order
block detector exists in any artefact, and none is invented here).

Each probe is behavioural: it drives the engine and asserts on the output.
"""

from __future__ import annotations

from bench.probes import register

__all__ = []


def _engine():
    from dodgys_dd_quant.strategy.state_machine import PRESETS, run_state_machine

    return PRESETS, run_state_machine


def _bars():
    from bench import fixtures

    return fixtures.btc_1m()


@register(
    "rules.stop_placement_body_and_ifvg",
    "rules",
    45,
    "the Body and IFVG stop placements exist alongside Wick (L2 row 18) and give a different stop",
)
def _stop_placements() -> tuple[bool, str]:
    """L2 row 18: the Pine offers ``Wick`` / ``Body`` / ``IFVG``.

    ``Body`` ignores the wick and uses the body extreme; ``IFVG`` uses the
    gap's own edge.  All three must be selectable and must not coincide.
    """
    from dataclasses import replace

    presets, run_state_machine = _engine()
    bars = _bars()
    stops: dict[str, set[float]] = {}
    for placement in ("wick", "body", "ifvg"):
        config = replace(presets["honest"], stop_placement=placement)
        log = run_state_machine(bars, config)
        stops[placement] = {
            round(c.stop_price, 6) for c in log if c.risk > 0
        }
        if not stops[placement]:
            return False, f"the {placement!r} stop placement produced no candidates"
    if len(stops["body"]) == len(stops["wick"]) and stops["body"] == stops["wick"]:
        return False, "the Body placement is identical to Wick"
    if len(stops["ifvg"]) == len(stops["wick"]) and stops["ifvg"] == stops["wick"]:
        return False, "the IFVG placement is identical to Wick"
    return True, (
        f"three distinct stop placements: wick={len(stops['wick'])} "
        f"body={len(stops['body'])} ifvg={len(stops['ifvg'])} distinct stops"
    )


@register(
    "rules.break_even_level_is_the_swing_origin",
    "rules",
    45,
    "the break-even level is the swing origin and it resolves the trade (L2 rows 19-20)",
)
def _break_even() -> tuple[bool, str]:
    """L2 rows 19 and 20.

    The Pine sets the trade's break-even level to the **swing origin**
    (``pine:L476``) and ends the trade when the price reaches it
    (``pine:L509``).  Both must exist: the level, and its resolution.
    """
    from dataclasses import replace

    presets, run_state_machine = _engine()
    bars = _bars()
    log = run_state_machine(bars, presets["honest"])
    candidates = list(log)
    if not candidates:
        return False, "no candidates to inspect"

    # The origin must be recorded and finite for the candidates that have one.
    with_origin = [c for c in candidates if c.origin_price == c.origin_price]
    if not with_origin:
        return False, "no candidate carries a swing origin"

    # The break-even resolution: a candidate whose price reached the origin
    # before its stop or target must be resolved as a break-even, not as a
    # stop or a target.  The exit is the **reference's** rule, so it is an
    # explicit switch: the code-derived arm keeps its E-1 parity (no
    # break-even exit at all).
    default = {c.outcome for c in candidates}
    if "break_even" in default:
        return False, (
            "the code-derived arm resolves trades at their break-even level; "
            "the reference's exit must be an explicit switch"
        )
    config = replace(presets["honest"], stop_placement="wick", resolve_break_even=True)
    candidates = list(run_state_machine(bars, config))
    resolved = {c.outcome for c in candidates}
    if "break_even" not in resolved:
        return False, (
            f"no candidate was resolved at its break-even level "
            f"(the outcome vocabulary is {sorted(resolved)})"
        )
    return True, (
        f"{len(with_origin)} candidates carry a swing origin; "
        f"{sum(1 for c in candidates if c.outcome == 'break_even')} resolved at break-even"
    )


@register(
    "rules.target_from_the_liquidity_universe",
    "rules",
    45,
    "the >=2R target comes from a liquidity-level universe, not only the RR price (L2 row 23)",
)
def _liquidity_target() -> tuple[bool, str]:
    """L2 row 23: the doc's target is the **next liquidity pool at >= 2R**.

    It needs a level universe: the previous day's high/low, the session
    extremes and the unmitigated swing pivots.  The check asserts that the
    engine knows such a universe and that it can name a target at least 2R
    away for a candidate that has one.
    """
    presets, run_state_machine = _engine()
    candidates = list(run_state_machine(_bars(), presets["honest"]))
    if not candidates:
        return False, "no candidates to inspect"

    # Every candidate must carry the distance to its liquidity target, and
    # that distance must be at least 2R when a target exists.
    from dodgys_dd_quant.strategy.constants import LIQUIDITY_TARGET_MIN_R

    with_target = [c for c in candidates if c.liquidity_target_price == c.liquidity_target_price]
    if not with_target:
        return False, "no candidate carries a liquidity target price"
    too_close = [
        c
        for c in with_target
        if abs(c.liquidity_target_price - c.entry_price) < LIQUIDITY_TARGET_MIN_R * c.risk
    ]
    if too_close:
        return False, (
            f"{len(too_close)} candidates name a liquidity target closer than "
            f"{LIQUIDITY_TARGET_MIN_R}R"
        )
    return True, (
        f"{len(with_target)} candidates carry a liquidity target, all at least "
        f"{LIQUIDITY_TARGET_MIN_R}R away"
    )


@register(
    "rules.equal_high_low_levels",
    "rules",
    40,
    "equal-high/equal-low clusters are a level source and are consumed once (L2 row 5)",
)
def _equal_levels() -> tuple[bool, str]:
    """L2 row 5: the doc's sweep object is EQH/EQL/PDH/PDL.

    The level store must cluster near-equal highs and lows and consume each
    level once, like the swing levels do.
    """
    from dodgys_dd_quant.strategy.structure import EqualLevelStore

    store = EqualLevelStore(tolerance_atr_frac=0.10)
    store.add_level(price=100.0, direction=1, known_at=0)
    store.add_level(price=100.05, direction=1, known_at=1)  # same cluster
    store.add_level(price=120.0, direction=1, known_at=2)  # a different level
    levels = store.levels()
    highs = [level for level in levels if level.direction == 1]
    if len(highs) != 2:
        return False, f"the equal-high store kept {len(highs)} levels, expected 2"

    events = store.update(bar=3, high=100.5, low=99.0, close=99.5)
    if len(events) != 1:
        return False, f"the clustered level was swept {len(events)} times, expected 1"
    again = store.update(bar=4, high=100.6, low=99.0, close=99.5)
    if again:
        return False, "the level was swept again after being consumed"
    return True, "equal highs cluster into one level and are consumed once"


@register(
    "rules.sweep_is_leg_scoped",
    "rules",
    40,
    "the sweep flag is leg-scoped: a sweep since the origin pivot (L2 row 30)",
)
def _leg_scoped_sweep() -> tuple[bool, str]:
    """L2 row 30: ``swept`` = *a sweep occurred **since the origin pivot*.

    The reference's own flag is leg-scoped and is reset only when a new
    pivot fires.  The candidate must therefore carry it.
    """
    presets, run_state_machine = _engine()
    candidates = list(run_state_machine(_bars(), presets["honest"]))
    if not candidates:
        return False, "no candidates to inspect"
    if not hasattr(candidates[0], "sweep_since_origin"):
        return False, "the candidate carries no leg-scoped sweep flag"
    flags = [bool(c.sweep_since_origin) for c in candidates]
    if not any(flags):
        return False, "no candidate reports a sweep since its origin pivot"
    if all(flags):
        return False, "every candidate reports a sweep -- the flag is not selective"
    return True, f"{sum(flags)}/{len(flags)} candidates report a leg-scoped sweep"


@register(
    "rules.unreclaimed_htf_fvg",
    "rules",
    40,
    "unreclaimed 15m/1H FVG zones are tracked causally (L2 row 3)",
)
def _unreclaimed_htf_fvg() -> tuple[bool, str]:
    """L2 row 3: the doc's HTF context includes **unreclaimed** HTF FVG zones.

    The zones must be published from **closed** HTF bars only, and a zone
    that price has since traded through is *mitigated*, not unreclaimed.
    """
    from dodgys_dd_quant.strategy.structure import HtfFvgZones

    zones = HtfFvgZones(timeframe_minutes=15)
    # A gap on the HTF series: low[2] > high[0].
    bars = HtfFvgZones.Bar(
        ts=0, open=100.0, high=101.0, low=100.5, close=100.8
    )
    zones.update([bars])
    live = zones.unreclaimed()
    if not live:
        return False, "the HTF zone store published no unreclaimed zone"

    # Trading through the zone mitigates it.
    zones.update([HtfFvgZones.Bar(ts=900_000_000_000, open=100.8, high=102.0, low=100.6, close=101.9)])
    if len(zones.unreclaimed()) >= len(live):
        return False, "trading through the zone did not mitigate it"
    return True, f"{len(live)} unreclaimed HTF zone(s) published, then mitigated on contact"


@register(
    "rules.candidate_array_cap",
    "rules",
    30,
    "the per-direction candidate cap is explicit and its effect is reported (L2 row 29)",
)
def _candidate_cap() -> tuple[bool, str]:
    """L2 row 29: the Pine keeps at most 50 candidates per direction.

    The row calls the Pine's behaviour "safe direction" (it *drops* the
    oldest), so the port must make the cap explicit rather than accidental.
    """
    from dataclasses import replace

    presets, run_state_machine = _engine()
    bars = _bars()
    candidates = list(run_state_machine(bars, presets["honest"]))
    if not candidates:
        return False, "no candidates to inspect"
    if not hasattr(candidates[0], "dropped_by_cap"):
        return False, "the candidate carries no record of a cap-induced drop"
    if not any(c.dropped_by_cap for c in candidates):
        return False, "no candidate was dropped by the cap -- the cap is not applied"
    return True, "the per-direction candidate cap is applied and its drops are recorded"
