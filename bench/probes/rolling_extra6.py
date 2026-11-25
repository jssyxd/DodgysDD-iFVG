"""The E-1 parity: the engine must reproduce the standalone experiment.

`research/experiments/e1_rule_falsification.py` is the repo's foundational
measurement: 32 arms on 2,046,240 real BTCUSDT 1-minute bars, and the
baseline every later deliverable is compared against (D4).  The engine is a
**re-implementation** of that experiment, so the two must agree -- the
census, the trades and the expectancy -- or one of them is lying.

The probes drive the standalone script and the engine over the *same*
fixture and compare them.  They are the parity check F11 asks for: the
README used to call the engine's census "exactly E-1's number" without
anything verifying it.
"""

from __future__ import annotations

import csv
import gzip
import importlib.util
import sys
import tempfile
from pathlib import Path

from bench.probes import register

__all__ = []

#: The E-1's documented arm: ``code[0,15] / code:none / honest:open(k+1) /
#: code:off``, one position at a time.
E1_WINDOW = (0, 15)
E1_ATR_MULT = 0.0
E1_FILL = "next_open"
E1_SWEEP = False


def _e1_module():
    """The standalone falsification experiment, imported as a module."""
    path = Path("research/experiments/e1_rule_falsification.py")
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("e1_falsification", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["e1_falsification"] = module
    spec.loader.exec_module(module)
    return module


def _e1_csv(path: Path) -> Path:
    """The benchmark fixture in the CSV dialect the E-1 script reads."""
    import datetime as dt

    from bench import fixtures

    data = fixtures.load_fixture("btcusdt_1m_2023q1")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Datetime", "Open", "High", "Low", "Close", "Volume"])
        for ts_ms, o, h, l, c, v in zip(
            data["ts_ms"],
            data["open"],
            data["high"],
            data["low"],
            data["close"],
            data["volume"],
        ):
            stamp = dt.datetime.fromtimestamp(
                int(ts_ms) / 1000.0, tz=dt.timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S")
            writer.writerow([stamp, o, h, l, c, v])
    return path


def _e1_arm():
    """Run the standalone experiment's documented arm on the fixture.

    The script's ``run_arm`` **mutates** the candidates it is given, so the
    census arm and the one-at-a-time arm each need their own copies -- the
    script's own grid does exactly that (``copy.deepcopy``).
    """
    import copy

    module = _e1_module()
    if module is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = _e1_csv(Path(tmp) / "bars.csv")
        bars = module.load_bars(csv_path)
        atr = module.atr_wilder(bars, 14)
        swept = module.sweep_flags(bars)
        gaps = module.find_candidates(bars, atr, E1_ATR_MULT)

        # the census arm: every signal that triggers, with no concurrency cap
        census = module.run_arm(
            bars,
            copy.deepcopy(gaps),
            swept,
            E1_WINDOW,
            E1_FILL,
            E1_SWEEP,
            max_concurrent=0,
        )
        n_triggered = sum(1 for c in census if c.confirmed is not None)

        # the one-position-at-a-time arm (the only one D4 allows to be quoted)
        done = module.run_arm(
            bars,
            copy.deepcopy(gaps),
            swept,
            E1_WINDOW,
            E1_FILL,
            E1_SWEEP,
            max_concurrent=1,
        )
        summary = module.summarise(done)
    return {
        "n_bars": len(bars),
        "n_gaps": len(gaps),
        "n_triggered": n_triggered,
        "n_trades": int(summary.get("n", 0)),
        "summary": summary,
    }


def _engine_arm():
    """The engine's equivalent arm on the same fixture."""
    from dodgys_dd_quant.strategy.state_machine import (
        PRESETS,
        run_deferred_portfolio,
        run_state_machine,
    )

    from bench import fixtures

    bars = fixtures.btc_1m()
    log = run_state_machine(bars, PRESETS["e1"])
    deferred = run_deferred_portfolio(bars, PRESETS["e1"])
    closed = [c for c in deferred if c.is_closed]
    expectancy = (
        sum(c.r_multiple for c in closed) / len(closed) if closed else float("nan")
    )
    return {
        "n_bars": len(bars),
        "n_candidates": len(log),
        "n_trades": len(deferred),
        "n_closed": len(closed),
        "expectancy_r": expectancy,
    }


@register(
    "rolling.e1_census_matches_the_standalone_experiment",
    "rolling",
    60,
    "the engine's census is the standalone E-1 experiment's census (F11)",
)
def _census_parity() -> tuple[bool, str]:
    """The census is the population every later number is computed on.

    F11 caught the README claiming the two were "exactly E-1's number"
    without anything checking it; here they are compared.
    """
    e1 = _e1_arm()
    if e1 is None:
        return False, "the standalone experiment could not be loaded"
    engine = _engine_arm()
    if e1["n_bars"] != engine["n_bars"]:
        return False, (
            f"the two ran on {e1['n_bars']} and {engine['n_bars']} bars"
        )
    if e1["n_triggered"] != engine["n_candidates"]:
        return False, (
            f"the engine's census holds {engine['n_candidates']} candidates, "
            f"the standalone experiment triggers {e1['n_triggered']} "
            f"(out of {e1['n_gaps']} gaps)"
        )
    return True, (
        f"both trigger {e1['n_triggered']} setups out of {e1['n_gaps']} gaps "
        f"in {e1['n_bars']} bars"
    )


@register(
    "rolling.e1_expectancy_matches_the_standalone_experiment",
    "rolling",
    55,
    "the engine's one-position-at-a-time expectancy is the standalone experiment's",
)
def _expectancy_parity() -> tuple[bool, str]:
    """The one-position-at-a-time arm is the only arm D4 allows to be quoted."""
    e1 = _e1_arm()
    if e1 is None:
        return False, "the standalone experiment could not be loaded"
    engine = _engine_arm()
    summary = e1["summary"]
    theirs = float(summary.get("expectancy_r", float("nan")))
    ours = float(engine["expectancy_r"])
    # the engine also returns the position that was still open at the end of
    # the sample; the standalone experiment's summary counts the **closed**
    # trades only, so the comparison is made on the same population
    if e1["n_trades"] != engine["n_closed"]:
        return False, (
            f"the engine closed {engine['n_closed']} trades, the standalone "
            f"experiment {e1['n_trades']}"
        )
    if not (abs(ours - theirs) <= 0.02 + 0.02 * abs(theirs)):
        return False, (
            f"the engine's expectancy is {ours:.4f} R, the standalone "
            f"experiment's {theirs:.4f} R"
        )
    return True, (
        f"both arms closed {e1['n_trades']} trades at {ours:.4f} R "
        f"(the standalone: {theirs:.4f} R)"
    )


@register(
    "rolling.e1_rules_are_the_documented_arm",
    "rolling",
    45,
    "the engine's e1 preset is the arm the standalone experiment documents",
)
def _documented_arm() -> tuple[bool, str]:
    """``code[0,15] / code:none / honest:open(k+1) / code:off``.

    The age-0 window is arithmetically impossible (L2 §A.5), so ``[0, 15]``
    and ``[1, 15]`` select the same population -- but the *other* three
    switches are not free.
    """
    from dodgys_dd_quant.strategy.state_machine import PRESETS

    config = PRESETS["e1"]
    if config.min_gap_atr_mult is not None:
        return False, f"the e1 preset has an ATR floor ({config.min_gap_atr_mult})"
    if config.require_sweep:
        return False, "the e1 preset requires a sweep"
    if config.entry_fill != "next_open":
        return False, f"the e1 preset fills at {config.entry_fill!r}"
    if config.portfolio_mode != "defer":
        return False, f"the e1 preset accounts as {config.portfolio_mode!r}"
    if config.inversion_max_bars != 15:
        return False, f"the e1 preset's window ends at {config.inversion_max_bars}"
    if config.inversion_min_bars not in (0, 1):
        return False, f"the e1 preset's window starts at {config.inversion_min_bars}"
    if config.resolve_break_even:
        return False, "the e1 preset resolves trades at their break-even level"
    return True, (
        "the e1 preset is code[0,15] / code:none / honest:open(k+1) / code:off, "
        "deferred, with no break-even exit"
    )
