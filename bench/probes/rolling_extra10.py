"""The repo's own guards: DST, the regime's bins, the RL's refusals, the costs.

Everything the repository asserts about *itself* should be executable:

* the timezone helper must follow the **tz database**, not a fixed offset --
  the bug that put every "New York" value five hours out;
* the regime's bins must use the **corrected** semantics (RULE_SPEC §1.9),
  not the discussion's right-closed ``pd.cut``;
* the position manager must **refuse** to open or submit -- INV1;
* the cost model must reproduce D9's dollar ladder exactly;
* the label horizon must have **one** representation in bars and in minutes,
  because the embargo is derived from it;
* the credential guard must actually block a staged token.
"""

from __future__ import annotations

import datetime as dt
import math
import subprocess
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

from bench.probes import register

__all__ = []

NY = ZoneInfo("America/New_York")


@register(
    "rules.local_minutes_follow_dst",
    "rules",
    45,
    "the local minutes follow the tz database across the DST switch days",
)
def _local_minutes_dst() -> tuple[bool, str]:
    """The fix for the five-hour bug, locked down.

    ``local_minutes_of_day`` must return the **local** wall-clock minutes:
    the same UTC instant has different local minutes before and after a
    switch day, and a fixed UTC offset would not.
    """
    from dodgys_dd_quant.strategy.structure import local_minutes_of_day

    def _ns(year: int, month: int, day: int, hour: int, minute: int) -> int:
        moment = dt.datetime(year, month, day, hour, minute, tzinfo=NY)
        return int(moment.timestamp() * 1_000_000_000)

    winter = _ns(2024, 1, 3, 9, 30)
    summer = _ns(2024, 7, 3, 9, 30)
    minutes = local_minutes_of_day(
        __import__("numpy").asarray([winter, summer], dtype="int64")
    )
    if int(minutes[0]) != 9 * 60 + 30:
        return False, f"the winter local minutes are {int(minutes[0])}, expected 570"
    if int(minutes[1]) != 9 * 60 + 30:
        return False, f"the summer local minutes are {int(minutes[1])}, expected 570"

    # the same **local** wall-clock time on either side of the switch day
    before = _ns(2024, 3, 9, 14, 30)
    after = _ns(2024, 3, 11, 14, 30)
    import numpy as np

    across = local_minutes_of_day(np.asarray([before, after], dtype="int64"))
    if int(across[0]) != int(across[1]):
        return False, (
            f"the same local time has different minutes across the switch day: "
            f"{int(across[0])} against {int(across[1])}"
        )
    if int(across[0]) != 14 * 60 + 30:
        return False, (
            f"the local minutes are {int(across[0])}, expected "
            f"{14 * 60 + 30}"
        )
    return True, (
        "the local minutes are the same wall-clock time in both seasons and "
        "across the switch day"
    )


@register(
    "regime.binning_matches_the_corrected_semantics",
    "regime",
    40,
    "the regime bins use the corrected semantics, not the discussion's pd.cut",
)
def _regime_bins() -> tuple[bool, str]:
    """RULE_SPEC §1.9 / I05: the bands are ``(-inf,18) 0 | [18,28] 1 | (28,inf) 2``.

    The discussion's literal ``pd.cut(bins=[0,18,28,200])`` is right-closed
    and disagrees with the prose at exactly 18 and 28.
    """
    from dodgys_dd_quant.ml_pipeline.features import vxn_regime_from_level
    from dodgys_dd_quant.strategy.regime import regime_label

    cases = {
        0.0: 0,
        17.99: 0,
        18.0: 1,
        20.0: 1,
        28.0: 1,
        28.01: 2,
        40.0: 2,
    }
    for value, expected in cases.items():
        got = regime_label(value)
        if got != expected:
            return False, (
                f"the level {value} lands in band {got}, expected {expected}"
            )
    import pandas as pd

    frame = vxn_regime_from_level(pd.Series(list(cases)))
    for (value, expected), got in zip(cases.items(), frame.tolist()):
        if not math.isnan(got) and int(got) != expected:
            return False, (
                f"the feature's binning puts {value} in band {got}, expected "
                f"{expected}"
            )
    return True, (
        "the bands follow the corrected semantics at 18 and 28 (and the "
        "feature's binning agrees)"
    )


@register(
    "rl.manager_refuses_to_open_or_submit",
    "rolling",
    45,
    "the position manager has no way to open or submit anything (INV1)",
)
def _manager_refusals() -> tuple[bool, str]:
    """INV1: the agent is handed a manager and nothing else.

    The action space carries no field that could open a position, and the
    manager itself refuses the two obvious attempts.
    """
    from dodgys_dd_quant.rl.position_manager import ManagementError, PositionManager

    manager = PositionManager(
        size=1.0, side=1, entry_price=100.0, stop_price=98.0, target_price=104.0
    )
    for name in ("open_position", "submit_order"):
        method = getattr(manager, name, None)
        if method is None:
            return False, f"the manager has no {name!r} at all"
        try:
            method()
        except ManagementError:
            continue
        except Exception as exc:  # noqa: BLE001 - any refusal is a refusal
            if "not available" not in str(exc).lower():
                return False, f"{name} raised {type(exc).__name__}: {exc}"
            continue
        return False, f"{name} did not refuse"
    return True, "the manager refuses to open a position and to submit an order"


@register(
    "rolling.d9_dollar_ladder_is_exact",
    "rolling",
    45,
    "the cost model reproduces D9's dollar ladder exactly (NQ: $9.50 / $14.50 / $19.50)",
)
def _d9_ladder() -> tuple[bool, str]:
    """D9's numbers: the round trip on NQ is $9.50 at 0 ticks of slippage.

    ``$4.50`` fee plus one crossing tick of ``$5.00``; each further tick of
    slippage adds ``$5.00``.
    """
    from dodgys_dd_quant.backtest.cost_model import get_profile, round_trip_cost

    nq = get_profile("nq")
    price = 20000.0
    ladder = [round_trip_cost(nq, price, ticks) for ticks in (0, 1, 2)]
    expected = [9.50, 14.50, 19.50]
    for got, want in zip(ladder, expected):
        if abs(got - want) > 1e-6:
            return False, f"the ladder is {ladder}, expected {expected}"
    # the slippage is quoted per round trip, not per side
    one_tick = round_trip_cost(nq, price, 1) - round_trip_cost(nq, price, 0)
    if abs(one_tick - nq.tick_value) > 1e-6:
        return False, (
            f"one tick of slippage costs {one_tick}, the tick value is "
            f"{nq.tick_value}"
        )
    return True, f"NQ's round trip is {ladder} at 0/1/2 ticks of slippage"


@register(
    "rolling.label_horizon_has_one_representation",
    "rolling",
    35,
    "the label horizon has one representation in bars and in minutes, and the embargo follows it",
)
def _label_horizon() -> tuple[bool, str]:
    """The embargo is derived from the horizon, so the two must agree."""
    from dodgys_dd_quant.ml_pipeline.labels import label_horizon_bars, max_holding_minutes
    from dodgys_dd_quant.ml_pipeline.splits import make_folds
    from dodgys_dd_quant.strategy.constants import LABEL_HORIZON_BARS

    bars = label_horizon_bars()
    if bars != LABEL_HORIZON_BARS:
        return False, (
            f"the label module says {bars} bars, the constants say "
            f"{LABEL_HORIZON_BARS}"
        )
    for interval in (1, 5, 15):
        minutes = max_holding_minutes(interval)
        if minutes != bars * interval:
            return False, (
                f"at {interval} minutes per bar the horizon is {minutes} "
                f"minutes, expected {bars * interval}"
            )
    return True, (
        f"the horizon is {bars} bars, i.e. {max_holding_minutes(1)} minutes on a "
        f"one-minute series"
    )


@register(
    "data.credential_guard_catches_a_leaked_token",
    "rolling",
    50,
    "the pre-commit credential guard blocks a staged token (the repository's own governance)",
)
def _credential_guard() -> tuple[bool, str]:
    """The guard is the repository's first line of defence.

    The check runs in an isolated temporary repository, so it neither stages
    anything in this one nor needs a real credential: the token-shaped string
    is *built* at run time, so the probe's own source carries no secret.
    """
    script = Path("scripts/pre-commit-secret-scan.sh")
    if not script.exists():
        return False, "the pre-commit guard is missing"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        (root / "clean.txt").write_text("nothing to see here\n", encoding="utf-8")
        subprocess.run(["git", "add", "clean.txt"], cwd=root, check=True)
        clean = subprocess.run(
            ["bash", str(script.resolve())], cwd=root, capture_output=True, text=True
        )
        if clean.returncode != 0:
            return False, (
                "the guard blocked a clean file: "
                f"{clean.stdout.strip()[:200]}"
            )

        # the token is assembled at run time: the probe's source holds no secret
        token = "ghp_" + ("A" * 36)
        (root / "leak.py").write_text(f'TOKEN = "{token}"\n', encoding="utf-8")
        subprocess.run(["git", "add", "leak.py"], cwd=root, check=True)
        dirty = subprocess.run(
            ["bash", str(script.resolve())], cwd=root, capture_output=True, text=True
        )
        if dirty.returncode == 0:
            return False, "the guard let a staged credential through"
        if "BLOCKED" not in dirty.stdout:
            return False, f"the guard failed without saying why: {dirty.stdout[:200]}"
    return True, "the guard blocks a staged credential and passes a clean file"
