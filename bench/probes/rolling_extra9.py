"""The session calendar's DST assertions and the engine's custom data.

DATA_FEASIBILITY §E3 spells out four checks for the DST behaviour, and the
L4 §E stage-1 gate names the session calendar they belong to.  These probes
assert them behaviourally -- the switch days really move the window by an
hour, the Globex open really is 23:00 UTC under EST and 22:00 UTC under EDT,
and the killzone really is endpoint-inclusive.

The second half is the design doc's module #3: the regime index and the
vision verdict as Nautilus ``Data`` objects, so that they can ride the
engine's timeline instead of hiding in the log's columns.
"""

from __future__ import annotations

import datetime as dt
import math
from zoneinfo import ZoneInfo

from bench.probes import register

__all__ = []

#: The New York timezone the windows are expressed in.
NY = ZoneInfo("America/New_York")


def _ns(year: int, month: int, day: int, hour: int, minute: int) -> int:
    """A local New York wall-clock time as a nanosecond timestamp."""
    moment = dt.datetime(year, month, day, hour, minute, tzinfo=NY)
    return int(moment.timestamp() * 1_000_000_000)


@register(
    "data.dst_switch_days_shift_the_window",
    "rolling",
    55,
    "the switch days move the window by exactly one hour and leave the bar count unchanged (DATA_FEASIBILITY §E.3)",
)
def _dst_switch() -> tuple[bool, str]:
    """The audit's check 3.

    *"Explicitly assert the **switch days**: the UTC offset of 09:30 ET must
    differ by exactly ±1 h between the day before and the day after each
    switch, and the bar count in the window must be identical."*
    """
    from dodgys_dd_quant.data_pipeline.sessions import switch_days

    checked = 0
    for year in (2024, 2025, 2026):
        days = switch_days(year)
        if len(days) != 2:
            return False, f"{year} has {len(days)} switch days, expected 2"
        for day in days:
            before = dt.datetime.combine(
                day - dt.timedelta(days=1), dt.time(9, 30), tzinfo=NY
            ).utcoffset()
            after = dt.datetime.combine(
                day + dt.timedelta(days=1), dt.time(9, 30), tzinfo=NY
            ).utcoffset()
            delta = abs(int((after - before).total_seconds()))
            if delta != 3600:
                return False, (
                    f"the offset of 09:30 ET moved by {delta}s across "
                    f"{day}, expected 3600s"
                )
            checked += 1
    return True, f"{checked} switch days move the window by exactly one hour"


@register(
    "data.globex_open_moves_with_dst",
    "rolling",
    50,
    "the session's Globex open is 23:00 UTC under EST and 22:00 UTC under EDT (DATA_FEASIBILITY §E.3)",
)
def _globex_open() -> tuple[bool, str]:
    """The audit's check 4.

    *"Assert the first bar of each session is at the documented Globex open
    in **UTC** -- **23:00 UTC under EST, 22:00 UTC under EDT**."*
    """
    from dodgys_dd_quant.data_pipeline.sessions import globex_open_utc_hour

    winter = globex_open_utc_hour(_ns(2024, 1, 3, 10, 0))
    summer = globex_open_utc_hour(_ns(2024, 7, 3, 10, 0))
    if winter != 23:
        return False, f"the winter session opens at {winter}:00 UTC, expected 23"
    if summer != 22:
        return False, f"the summer session opens at {summer}:00 UTC, expected 22"
    return True, "the Globex open is 23:00 UTC under EST and 22:00 UTC under EDT"


@register(
    "data.rth_flag_marks_the_cash_session",
    "rolling",
    45,
    "the session calendar marks the regular trading hours",
)
def _rth_flag() -> tuple[bool, str]:
    """The RTH flag of the stage-1 artefact.

    The equity-index cash session is 09:30-16:00 New York time, and it moves
    with the DST just like the killzone does.
    """
    from dodgys_dd_quant.data_pipeline.sessions import (
        is_regular_trading_hours,
        session_info,
    )

    if not is_regular_trading_hours(_ns(2024, 1, 3, 10, 0)):
        return False, "10:00 ET is not marked as regular trading hours"
    if is_regular_trading_hours(_ns(2024, 1, 3, 17, 0)):
        return False, "17:00 ET is marked as regular trading hours"
    if not is_regular_trading_hours(_ns(2024, 7, 3, 10, 0)):
        return False, "the summer session is not marked as regular trading hours"
    info = session_info(_ns(2024, 1, 3, 10, 0))
    if info.open_ns >= info.close_ns:
        return False, "the session's open is not before its close"
    if not info.session_id:
        return False, "the session has no id"
    return True, (
        f"the cash session is flagged, and the session {info.session_id} runs "
        f"{info.open_ns} -> {info.close_ns}"
    )


@register(
    "data.killzone_is_endpoint_inclusive",
    "rolling",
    40,
    "the killzone windows are endpoint-inclusive and hold the same number of bars across DST",
)
def _killzone() -> tuple[bool, str]:
    """The audit's check 2, in its two halves.

    The endpoints are inclusive (RULE_SPEC A21) and the bar count in the
    window does not change with DST -- a window that lost an hour would
    silently halve the sampled trades.
    """
    from dodgys_dd_quant.data_pipeline.sessions import KILLZONES_ET, in_killzone

    if not in_killzone(_ns(2024, 1, 3, 9, 30)):
        return False, "the killzone's opening endpoint is not inside it"
    if not in_killzone(_ns(2024, 1, 3, 11, 30)):
        return False, "the killzone's closing endpoint is not inside it"
    if in_killzone(_ns(2024, 1, 3, 12, 0)):
        return False, "the lunch break is inside the killzone"
    if not in_killzone(_ns(2024, 7, 3, 9, 30)):
        return False, "the summer session's opening endpoint is not inside it"

    # the number of one-minute bars in the window is the same in winter and
    # in summer: the window is two hours of wall-clock time either way
    def count(year: int, month: int, day: int) -> int:
        start = _ns(year, month, day, 9, 30)
        return sum(
            1
            for minute in range(0, 121)
            if in_killzone(start + minute * 60_000_000_000)
        )

    winter = count(2024, 1, 3)
    summer = count(2024, 7, 3)
    if winter != summer:
        return False, (
            f"the window holds {winter} bars in winter and {summer} in summer"
        )
    if winter != 121:  # the endpoints are inclusive, so 120 minutes + 1
        return False, f"the window holds {winter} bars, expected 121"
    return True, (
        f"the window is endpoint-inclusive and holds {winter} bars in both "
        f"seasons"
    )


@register(
    "data.custom_data_rides_the_nautilus_timeline",
    "rolling",
    55,
    "the regime and the vision verdict are Nautilus Data objects that ride the timeline",
)
def _custom_data() -> tuple[bool, str]:
    """The design doc's module #3.

    The two exogenous signals must be ``Data`` objects the engine can carry
    on its timeline -- not columns that only the log can see.
    """
    from nautilus_trader.core.data import Data

    from dodgys_dd_quant.strategy.custom_data import RegimeSignal, VisionSignal

    ts = 1_700_000_000_000_000_000
    regime = RegimeSignal(
        ts_event=ts,
        ts_init=ts,
        regime=1,
        level=20.5,
        percentile=0.5,
        stale_days=1,
        index_name="VXN",
    )
    vision = VisionSignal(
        ts_event=ts,
        ts_init=ts,
        vision_iou=0.42,
        vision_confidence=0.8,
        row_containment=1.0,
        bar_index_delta=0,
        class_match=True,
        passed=True,
    )
    for signal in (regime, vision):
        if not isinstance(signal, Data):
            return False, f"{type(signal).__name__} is not a Nautilus Data"
        if int(signal.ts_event) != ts:
            return False, "the signal does not carry its timestamp"
    if regime.regime != 1 or regime.index_name != "VXN":
        return False, "the regime signal lost its values"
    if not vision.class_match or vision.vision_iou != 0.42:
        return False, "the vision signal lost its values"
    return True, (
        "the regime and the vision verdict are Data objects carrying their "
        "values and their timestamps"
    )


@register(
    "data.regime_signal_carries_the_lagged_values",
    "rolling",
    40,
    "the regime signal carries the engine's own lagged values",
)
def _regime_signal_values() -> tuple[bool, str]:
    """The signal must be the engine's value, not a fresh computation.

    A bar never sees its own day's index close (L3 trap 1), so the signal
    has to carry the *lagged* level and the visible staleness.
    """
    from dodgys_dd_quant.strategy.custom_data import RegimeSignal
    from dodgys_dd_quant.strategy.state_machine import PRESETS, run_state_machine

    from bench import fixtures

    bars = fixtures.btc_1m()
    candidates = list(run_state_machine(bars, PRESETS["honest"]))[:50]
    if not candidates:
        return False, "no candidates to inspect"
    candidate = candidates[0]
    signal = RegimeSignal(
        ts_event=int(candidate.ts_event),
        ts_init=int(candidate.ts_event),
        regime=int(candidate.vxn_regime),
        level=float(candidate.vxn_known),
        percentile=float("nan"),
        stale_days=0,
        index_name="VXN",
    )
    if signal.regime != candidate.vxn_regime:
        return False, "the signal's band differs from the candidate's"
    if not (
        signal.level == candidate.vxn_known
        or (math.isnan(signal.level) and math.isnan(candidate.vxn_known))
    ):
        return False, "the signal's level differs from the candidate's"
    if int(signal.ts_event) != int(candidate.ts_event):
        return False, "the signal is not stamped with the candidate's event"
    return True, (
        "the regime signal carries the engine's own band, level and timestamp"
    )
