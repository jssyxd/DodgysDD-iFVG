"""The pre-registered regime family, and the census arm's trap.

L3 §C.2 pre-registers a **family of five** regime variables, each tested on
the same sample, with the multiple-testing correction applied **jointly**
across the family -- and names the self-referential control (the realised
volatility) as *not optional*.

D4's trap is the other half: the **census** arm (one position per
candidate) shows a t-statistic that no portfolio can produce, because its
trades overlap.  The probe asserts the trap rather than the number, so the
artefact stays honest whichever arm is quoted.
"""

from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
from pathlib import Path

from bench.probes import register

__all__ = []


@register(
    "regime.pre_registered_family_runs",
    "regime",
    55,
    "the pre-registered regime family runs on a sample, with every member reported",
)
def _family_runs() -> tuple[bool, str]:
    """L3 §C.2: the whole experiment, not just one variable.

    Every member of the family is tested on the same sample; the crypto-only
    members are reported as *not applicable* when the crypto data is absent,
    never silently dropped.
    """
    from bench import fixtures
    from dodgys_dd_quant.analysis.regime_correlation import (
        REGIME_FAMILY,
        run_regime_family,
    )

    days, closes = fixtures.vxn_daily()
    sample = fixtures.frame_from_fixture("btcusdt_1m_2023q1")
    result = run_regime_family(
        sample,
        days=days,
        closes=closes,
        symbol="BTCUSDT",
        timeframe="1m",
    )
    rows = result.get("family")
    if not rows:
        return False, "the family reported no member"
    names = {row.get("variable") for row in rows}
    missing = {member.name for member in REGIME_FAMILY} - names
    if missing:
        return False, f"the family did not report {sorted(missing)}"
    for row in rows:
        if row.get("variable") in {"dvol_tertiles", "funding_sign"}:
            if row.get("status") != "not_applicable":
                return False, (
                    f"the crypto-only member {row['variable']} reported "
                    f"{row.get('status')!r} on a non-crypto sample"
                )
    correction = result.get("correction")
    if not correction:
        return False, "the family reported no joint correction"
    return True, (
        f"{len(rows)} family members reported and corrected jointly"
    )


@register(
    "regime.family_correction_is_joint",
    "regime",
    40,
    "the multiple-testing correction is applied jointly across the family",
)
def _family_correction() -> tuple[bool, str]:
    """Holm-Bonferroni across the family, not per variable.

    The corrected p-values must be monotone in the raw ones and must be at
    least as large as the raw ones.
    """
    from dodgys_dd_quant.analysis.regime_correlation import holm_bonferroni

    raw = [0.01, 0.04, 0.20, 0.50]
    corrected = holm_bonferroni(raw)
    adjusted = corrected.get("p_adjusted")
    if not adjusted or len(adjusted) != len(raw):
        return False, "the correction did not return one value per test"
    if corrected.get("family_size") != len(raw):
        return False, (
            f"the correction's family size is {corrected.get('family_size')}, "
            f"expected {len(raw)}"
        )
    order = sorted(range(len(raw)), key=lambda i: raw[i])
    ordered = [adjusted[i] for i in order]
    if any(b < a - 1e-12 for a, b in zip(ordered, ordered[1:])):
        return False, "the corrected p-values are not monotone in the raw ones"
    for original, value in zip(raw, adjusted):
        if value < original - 1e-12:
            return False, (
                f"the corrected p-value {value} is below the raw {original}"
            )
    # the correction must depend on the family's size: the same p-value in a
    # larger family is penalised more
    single = holm_bonferroni([raw[0]])["p_adjusted"][0]
    if not (adjusted[0] >= single - 1e-12):
        return False, (
            "the joint correction is not penalising the family for its size"
        )
    return True, (
        f"the joint correction lifts the p-values to "
        f"{[round(value, 4) for value in adjusted]}"
    )


@register(
    "rolling.census_arm_is_not_a_result",
    "rolling",
    45,
    "the census arm's significance is an artefact of overlapping trades (D4)",
)
def _census_trap() -> tuple[bool, str]:
    """D4's trap, asserted.

    The census arm (one position per candidate) trades thousands of
    *overlapping* positions, so its t-statistic is manufactured by the
    correlation.  The one-position-at-a-time arm is the only one whose
    significance may be quoted.
    """
    import copy

    from bench import fixtures

    path = Path("research/experiments/e1_rule_falsification.py")
    if not path.exists():
        return False, "the standalone experiment could not be loaded"
    spec = importlib.util.spec_from_file_location("e1_census", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["e1_census"] = module
    spec.loader.exec_module(module)

    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "bars.csv"
        data = fixtures.load_fixture("btcusdt_1m_2023q1")
        import datetime as dt

        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Datetime", "Open", "High", "Low", "Close", "Volume"])
            for ts, o, h, low, c, v in zip(
                data["ts_ms"],
                data["open"],
                data["high"],
                data["low"],
                data["close"],
                data["volume"],
            ):
                stamp = dt.datetime.fromtimestamp(
                    int(ts) / 1000.0, tz=dt.timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S")
                writer.writerow([stamp, o, h, low, c, v])
        bars = module.load_bars(csv_path)
        atr = module.atr_wilder(bars, 14)
        swept = module.sweep_flags(bars)
        gaps = module.find_candidates(bars, atr, 0.0)

        census = module.summarise(
            module.run_arm(
                bars, copy.deepcopy(gaps), swept, (0, 15), "next_open", False,
                max_concurrent=0,
            )
        )
        portfolio = module.summarise(
            module.run_arm(
                bars, copy.deepcopy(gaps), swept, (0, 15), "next_open", False,
                max_concurrent=1,
            )
        )

    census_t = abs(float(census.get("t_stat", float("nan"))))
    portfolio_t = abs(float(portfolio.get("t_stat", float("nan"))))
    if not (census_t > portfolio_t):
        return False, (
            f"the census arm's |t| ({census_t:.2f}) does not exceed the "
            f"one-position arm's ({portfolio_t:.2f}) -- the trap is not "
            f"reproducing"
        )
    if census_t < 5.0:
        return False, (
            f"the census arm's |t| is only {census_t:.2f}; the audit measures "
            f"a much stronger artefact on the full sample"
        )
    return True, (
        f"the census arm's |t| is {census_t:.2f} against the one-position "
        f"arm's {portfolio_t:.2f}"
    )
