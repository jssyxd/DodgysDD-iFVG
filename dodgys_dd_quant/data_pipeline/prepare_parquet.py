"""The data ingest: the governed parquet -> the Nautilus catalog (doc module #1).

The design discussion's ``prepare_parquet.py`` sample was flagged as "written
against an older API".  The audit's correction (``NAUTILUS_API.md`` §0) is
that the flag was **partly wrong**: the bar construction is fine, and the
real defects are

1. **no CME instrument definition** -- ``InstrumentId.from_str("NQ.XCME")``
   is an identifier, not a tradable instrument, so the backtest has nothing
   to fill against;
2. the **hard-coded two-decimal price** -- the precision has to follow the
   instrument, or the engine rejects the price;
3. **no ``ts_event``/``ts_init`` type discipline** -- both are ``uint64``
   nanoseconds;
4. the VXN daily/intraday mismatch, which belongs to the ML feature list
   and is *dropped* rather than fabricated (RULE_SPEC A18).

This module implements 1-3.  It is the data lane, not the live path: the
engine itself never imports Nautilus (the rule engine stays a pure function
of the bar history).

**The continuous-contract decision.**  A continuous series has no single
expiry, and ``FuturesContract`` demands ``activation_ns`` and
``expiration_ns``.  The port resolves it the way the data lane already
implies: a continuous series is a **series of dated contracts**, one per roll
segment (``data_pipeline.roll``), so the roll rule and the instrument
definitions cannot disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

__all__ = [
    "CmeContractSpec",
    "CME_CONTRACT_SPECS",
    "cme_contract",
    "contracts_for_segments",
    "write_catalog",
    "catalog_bars",
]


@dataclass(frozen=True)
class CmeContractSpec:
    """One CME contract family.

    The tick size and the multiplier come from the **cost model** (one source
    of truth: D9's ladder is built from the same numbers), and the price
    precision is the instrument's own.
    """

    symbol: str            # the root symbol, e.g. "NQ"
    raw_symbol: str
    venue: str
    tick_size: float
    multiplier: float
    price_precision: int
    asset_class: str = "INDEX"
    currency: str = "USD"
    underlying: str = ""
    #: The number of decimal places a price is quoted with.
    quote_precision: int = 2

    @property
    def instrument_id(self) -> str:
        return f"{self.symbol}.{self.venue}"

    @property
    def tick_value(self) -> float:
        """The currency value of one tick (D9's ladder)."""
        return float(self.tick_size) * float(self.multiplier)


#: The CME contract families the design doc names.  The tick size and the
#: multiplier are the cost model's numbers: NQ 0.25 pt = $5.00 on $20, ES
#: 0.25 pt = $12.50 on $50 (D9).
CME_CONTRACT_SPECS: dict[str, CmeContractSpec] = {
    "NQ": CmeContractSpec(
        symbol="NQ",
        raw_symbol="NQ",
        venue="XCME",
        tick_size=0.25,
        multiplier=20.0,
        price_precision=2,
        asset_class="INDEX",
        underlying="NQ",
    ),
    "MNQ": CmeContractSpec(
        symbol="MNQ",
        raw_symbol="MNQ",
        venue="XCME",
        tick_size=0.25,
        multiplier=2.0,
        price_precision=2,
        asset_class="INDEX",
        underlying="NQ",
    ),
    "ES": CmeContractSpec(
        symbol="ES",
        raw_symbol="ES",
        venue="XCME",
        tick_size=0.25,
        multiplier=50.0,
        price_precision=2,
        asset_class="INDEX",
        underlying="ES",
    ),
    "MES": CmeContractSpec(
        symbol="MES",
        raw_symbol="MES",
        venue="XCME",
        tick_size=0.25,
        multiplier=5.0,
        price_precision=2,
        asset_class="INDEX",
        underlying="ES",
    ),
}


def cme_contract(
    spec: CmeContractSpec,
    *,
    activation_ns: int = 0,
    expiration_ns: int = 0,
    ts_event: int = 0,
    ts_init: int = 0,
):
    """The **tradable** instrument definition for one CME contract family.

    This is the doc's missing piece: without it the backtest has no
    venue-side instrument to fill against, because an ``InstrumentId`` is an
    identifier only.
    """
    from nautilus_trader.model.enums import AssetClass
    from nautilus_trader.model.identifiers import InstrumentId, Symbol
    from nautilus_trader.model.instruments import FuturesContract
    from nautilus_trader.model.objects import Currency, Price, Quantity

    return FuturesContract(
        instrument_id=InstrumentId.from_str(spec.instrument_id),
        raw_symbol=Symbol(spec.raw_symbol),
        asset_class=AssetClass[spec.asset_class],
        currency=Currency.from_str(spec.currency),
        price_precision=spec.price_precision,
        price_increment=Price(spec.tick_size, spec.quote_precision),
        multiplier=Quantity(int(spec.multiplier), 1),
        lot_size=Quantity(1, 1),
        underlying=spec.underlying or spec.symbol,
        activation_ns=int(activation_ns),
        expiration_ns=int(expiration_ns),
        ts_event=int(ts_event),
        ts_init=int(ts_init),
        exchange=spec.venue,
    )


def contracts_for_segments(
    spec: CmeContractSpec,
    segments: Sequence[tuple[int, int]],
) -> list[Any]:
    """A continuous series as a **series of dated contracts**.

    ``segments`` are the roll segments' ``(activation_ns, expiration_ns)``
    bounds; each becomes one dated ``FuturesContract``.  This is the design
    decision the documents left open, and it makes the instrument definitions
    and the roll rule agree by construction.
    """
    out = []
    for activation_ns, expiration_ns in segments:
        out.append(
            cme_contract(
                spec,
                activation_ns=int(activation_ns),
                expiration_ns=int(expiration_ns),
                ts_event=int(activation_ns),
                ts_init=int(activation_ns),
            )
        )
    return out


def _price(value: float, precision: int):
    from nautilus_trader.model.objects import Price

    return Price(float(value), int(precision))


def write_catalog(
    bars: Any,
    *,
    instrument: Any,
    catalog_path: str | Path,
    bar_specification: Any | None = None,
) -> Path:
    """Write the bars into a ``ParquetDataCatalog``.

    Two disciplines the doc's sample lacked:

    * the **price precision** comes from the instrument (a price with the
      wrong precision is rejected by the engine);
    * the **timestamps** are asserted to be ``uint64`` nanoseconds before
      anything is written.
    """
    from nautilus_trader.model.data import Bar, BarSpecification, BarType
    from nautilus_trader.model.enums import BarAggregation, PriceType
    from nautilus_trader.model.objects import Quantity
    from nautilus_trader.persistence.catalog import ParquetDataCatalog

    if bar_specification is None:
        bar_specification = BarSpecification(
            1, BarAggregation.MINUTE, PriceType.LAST
        )
    bar_type = BarType(instrument.id, bar_specification)
    precision = int(instrument.price_precision)

    native_bars = []
    for index in range(len(bars)):
        ts_event = int(bars.ts[index])
        ts_init = int(bars.ts[index])
        if ts_event < 0 or ts_init < 0:
            raise ValueError(
                f"bar {index}: ts_event/ts_init must be unsigned nanoseconds"
            )
        native_bars.append(
            Bar(
                bar_type=bar_type,
                open=_price(bars.open[index], precision),
                high=_price(bars.high[index], precision),
                low=_price(bars.low[index], precision),
                close=_price(bars.close[index], precision),
                volume=Quantity(float(bars.volume[index]), 0),
                ts_event=ts_event,
                ts_init=ts_init,
            )
        )

    target = Path(catalog_path)
    target.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(target)
    catalog.write_data(native_bars)
    return target


def catalog_bars(catalog_path: str | Path) -> list[Any]:
    """Read the bars back out of a catalog (the round-trip check)."""
    from nautilus_trader.model.data import Bar
    from nautilus_trader.persistence.catalog import ParquetDataCatalog

    catalog = ParquetDataCatalog(Path(catalog_path))
    return list(catalog.query(Bar))
