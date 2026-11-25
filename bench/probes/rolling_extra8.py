"""The data lane's own contracts: the Nautilus catalog and the CME instruments.

Q5's answer is that the data is sufficient and how to roll it -- and the
design doc's module #1 (``prepare_parquet.py``) is where that lands.  The
audit's correction of that module (``NAUTILUS_API.md`` §0) found three real
defects, and these probes assert that they are gone:

* the **CME instrument definition** exists and is tradable (an
  ``InstrumentId`` alone is an identifier, not an instrument);
* the **price precision** follows the instrument instead of being hard-coded
  to two decimals;
* the **timestamps** are asserted to be unsigned nanoseconds.

The fourth defect -- the daily VXN against the intraday feature -- belongs to
the ML feature list and is *dropped* rather than fabricated (RULE_SPEC A18).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from bench.probes import register

__all__ = []


@register(
    "data.cme_instruments_are_defined",
    "rolling",
    55,
    "the CME contracts are defined as tradable instruments with the right tick and multiplier",
)
def _cme_instruments() -> tuple[bool, str]:
    """The doc's missing piece: a tradable instrument to fill against.

    The tick value must agree with D9's cost ladder -- NQ 0.25 pt = $5.00 on
    $20, ES 0.25 pt = $12.50 on $50 -- because that ladder is what the
    backtest charges.
    """
    from dodgys_dd_quant.backtest.cost_model import get_profile
    from dodgys_dd_quant.data_pipeline.prepare_parquet import (
        CME_CONTRACT_SPECS,
        cme_contract,
    )

    for symbol, profile_name in (("NQ", "nq"), ("ES", "es"), ("MES", "mes")):
        spec = CME_CONTRACT_SPECS[symbol]
        instrument = cme_contract(spec)
        profile = get_profile(profile_name)
        if str(instrument.id) != f"{symbol}.XCME":
            return False, f"the instrument is {instrument.id}"
        if float(instrument.price_increment) != float(profile.tick_size):
            return False, (
                f"{symbol}'s tick is {instrument.price_increment}, the cost "
                f"model charges {profile.tick_size}"
            )
        if float(instrument.multiplier) != float(profile.multiplier):
            return False, (
                f"{symbol}'s multiplier is {instrument.multiplier}, the cost "
                f"model charges {profile.multiplier}"
            )
        if spec.tick_value != float(profile.tick_value):
            return False, (
                f"{symbol}'s tick value is ${spec.tick_value}, the cost model "
                f"charges ${profile.tick_value}"
            )
        if int(instrument.price_precision) != spec.price_precision:
            return False, f"{symbol}'s price precision is wrong"
    return True, (
        "NQ, ES and MES are defined with the cost model's tick, multiplier "
        "and tick value"
    )


@register(
    "data.catalog_round_trips_the_bars",
    "rolling",
    50,
    "the bars survive the Nautilus catalog round trip",
)
def _catalog_round_trip() -> tuple[bool, str]:
    """The AGENTS.md's planned integration test: the catalog round trip.

    The bars go into a ``ParquetDataCatalog`` and come back with their
    prices, their volumes and their nanosecond timestamps intact.
    """
    from dodgys_dd_quant.data_pipeline.prepare_parquet import (
        CME_CONTRACT_SPECS,
        catalog_bars,
        cme_contract,
        write_catalog,
    )

    from bench import fixtures

    bars = fixtures.btc_1m()
    instrument = cme_contract(CME_CONTRACT_SPECS["NQ"])
    with tempfile.TemporaryDirectory() as tmp:
        target = write_catalog(
            bars, instrument=instrument, catalog_path=Path(tmp) / "catalog"
        )
        back = catalog_bars(target)
    if len(back) != len(bars):
        return False, f"the catalog holds {len(back)} bars, the series {len(bars)}"
    first = back[0]
    if float(first.close) != float(bars.close[0]):
        return False, (
            f"the first close came back as {first.close}, the series has "
            f"{bars.close[0]}"
        )
    if int(first.ts_event) != int(bars.ts[0]):
        return False, "the first timestamp changed"
    if float(first.volume) != float(bars.volume[0]):
        return False, "the first volume changed"
    return True, f"{len(back)} bars round-trip through the catalog"


@register(
    "data.prices_use_the_instrument_precision",
    "rolling",
    40,
    "the written prices carry the instrument's precision, not a hard-coded one",
)
def _price_precision() -> tuple[bool, str]:
    """The doc's second defect: ``Price.from_str(f\"{v:.2f}\")``.

    A price whose precision does not match the instrument's is rejected by
    the engine, so the precision has to travel with the instrument.
    """
    from dodgys_dd_quant.data_pipeline.prepare_parquet import (
        CME_CONTRACT_SPECS,
        catalog_bars,
        cme_contract,
        write_catalog,
    )

    from bench import fixtures

    bars = fixtures.btc_1m()
    instrument = cme_contract(CME_CONTRACT_SPECS["NQ"])
    with tempfile.TemporaryDirectory() as tmp:
        target = write_catalog(
            bars, instrument=instrument, catalog_path=Path(tmp) / "catalog"
        )
        back = catalog_bars(target)
    if not back:
        return False, "nothing was written"
    precision = int(back[0].close.precision)
    if precision != int(instrument.price_precision):
        return False, (
            f"the written prices carry {precision} decimals, the instrument "
            f"declares {instrument.price_precision}"
        )
    if precision == 2 and instrument.price_precision != 2:
        return False, "the precision is hard-coded to two decimals"
    return True, (
        f"the written prices carry the instrument's {precision}-decimal precision"
    )


@register(
    "data.continuous_series_is_dated_contracts",
    "rolling",
    45,
    "a continuous series is a series of dated contracts, one per roll segment",
)
def _dated_contracts() -> tuple[bool, str]:
    """The design decision the documents left open.

    A continuous "NQ" series has no single expiry and ``FuturesContract``
    demands ``activation_ns`` and ``expiration_ns``; the roll rule already
    knows where the contracts change, so the port models the series as one
    dated contract per roll segment -- the instrument definitions and the
    roll rule cannot then disagree.
    """
    from dodgys_dd_quant.data_pipeline.prepare_parquet import (
        CME_CONTRACT_SPECS,
        contracts_for_segments,
    )
    from dodgys_dd_quant.data_pipeline.roll import RollFilter

    # a synthetic roll: two price jumps
    bars = [
        {"ts": 0, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0},
        {"ts": 1_000_000_000, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0},
        {"ts": 2_000_000_000, "open": 110.0, "high": 110.5, "low": 109.5, "close": 110.0},
        {"ts": 3_000_000_000, "open": 110.0, "high": 110.5, "low": 109.5, "close": 110.0},
    ]
    boundaries = RollFilter(price_gap_frac=0.05).boundaries(bars)
    if len(boundaries) < 1:
        return False, "the roll filter found no boundary"

    segments = []
    start = int(bars[0]["ts"])
    for boundary in boundaries:
        segments.append((start, int(boundary.ts)))
        start = int(boundary.ts)
    segments.append((start, int(bars[-1]["ts"]) + 1))

    contracts = contracts_for_segments(CME_CONTRACT_SPECS["NQ"], segments)
    if len(contracts) != len(segments):
        return False, "the contract count does not match the segment count"
    for contract, (activation_ns, expiration_ns) in zip(contracts, segments):
        if int(contract.activation_ns) != int(activation_ns):
            return False, "a contract's activation does not match its segment"
        if int(contract.expiration_ns) != int(expiration_ns):
            return False, "a contract's expiry does not match its segment"
    return True, (
        f"the roll's {len(segments)} segments became {len(contracts)} dated "
        f"contracts"
    )


@register(
    "data.lake_audit_catches_every_invariant",
    "rolling",
    45,
    "the lake's five invariants are audited, and each violation is reported",
)
def _lake_audit() -> tuple[bool, str]:
    """The lake's contract, checked by the repo's own auditor.

    The lake's own auditor only tests ``volume < 0``; this one checks all
    five invariants and reports where each is broken.
    """
    import numpy as np
    import pandas as pd

    from dodgys_dd_quant.data_pipeline.audit import audit_frame

    # a zero-volume bar must be a **flat** bar: open == high == low == close
    clean = pd.DataFrame(
        {
            "ts": np.arange(5, dtype=np.int64) * 60_000_000_000,
            "open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "high": [101.0, 101.0, 103.0, 103.0, 105.0],
            "low": [99.0, 101.0, 101.0, 103.0, 103.0],
            "close": [100.5, 101.0, 102.5, 103.0, 104.5],
            "volume": [10.0, 0.0, 10.0, 0.0, 10.0],
        }
    )
    report = audit_frame(clean)
    if not report.passed:
        return False, f"a clean partition failed the audit: {report.reason()}"
    if report.n_bars != 5:
        return False, f"the audit counted {report.n_bars} bars"

    cases = {
        "non_monotonic_ts": {"ts": [0, 0, 2]},
        "duplicate_ts": {"ts": [0, 1, 1]},
        "high_below_body": {"high": [99.0, 100.0, 100.0]},
        "low_above_body": {"low": [200.0, 100.0, 100.0]},
        "non_positive_price": {"close": [100.0, 0.0, 100.0]},
        "negative_volume": {"volume": [1.0, -1.0, 1.0]},
        "zero_volume_non_flat_bar": {"volume": [1.0, 0.0, 1.0]},
    }
    base = {
        "ts": [0, 1, 2],
        "open": [100.0, 100.0, 100.0],
        "high": [101.0, 101.0, 101.0],
        "low": [99.0, 99.0, 99.0],
        "close": [100.0, 100.0, 100.0],
        "volume": [1.0, 1.0, 1.0],
    }
    missed = []
    for name, patch in cases.items():
        rows = dict(base)
        rows.update(patch)
        broken = audit_frame(pd.DataFrame(rows))
        if name not in broken.violations:
            missed.append(name)
    if missed:
        return False, f"the audit did not catch: {missed}"
    return True, f"the audit catches all {len(cases)} kinds of violation"


@register(
    "data.lake_audit_catches_the_flat_bar_corollary",
    "rolling",
    45,
    "a zero-volume bar that moved is caught: the lake's own auditor cannot see it",
)
def _flat_bar_corollary() -> tuple[bool, str]:
    """The corollary the repository's context file singles out.

    *"the lake's own auditor only tests ``volume < 0``, so it **cannot**
    detect a zero-volume non-flat bar -- verify that rule yourself."*
    """
    import pandas as pd

    from dodgys_dd_quant.data_pipeline.audit import audit_frame

    rows = {
        "ts": [0, 1, 2, 3],
        "open": [100.0, 100.0, 100.0, 100.0],
        "high": [101.0, 100.0, 101.0, 101.0],
        "low": [99.0, 100.0, 99.0, 99.0],
        "close": [100.0, 100.0, 100.0, 100.0],
        "volume": [5.0, 0.0, 0.0, 5.0],
    }
    frame = pd.DataFrame(rows)
    # bar 1 is a flat bar with no volume: allowed
    # bar 2 is a zero-volume bar that moved: not an observation
    frame.loc[2, "close"] = 100.5
    report = audit_frame(frame)
    if "zero_volume_non_flat_bar" not in report.violations:
        return False, "the zero-volume non-flat bar was not caught"
    if report.violations["zero_volume_non_flat_bar"] != 1:
        return False, (
            f"the audit reported {report.violations['zero_volume_non_flat_bar']} "
            f"offenders, expected 1"
        )
    if report.first_offender.get("zero_volume_non_flat_bar") != 2:
        return False, "the audit does not point at the offending bar"
    return True, (
        "the flat-bar corollary is enforced: the zero-volume bar that moved is "
        "reported with its index"
    )
