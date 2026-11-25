"""Build a NautilusTrader ``ParquetDataCatalog`` from the governed crypto lanes.

The lake stores ``ts_event`` (int64 **ms**, left-open) and plain OHLCV; NT wants
``Bar`` objects whose ``ts_event`` is the bar's **close** in nanoseconds, an
instrument with the right precision and fees, and a catalog it can reload.
This module does exactly that and nothing else -- it never re-derives OHLC.
"""

from __future__ import annotations

import math
from decimal import Decimal
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AggressorSide, BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.model.objects import Currency, Price, Quantity
from nautilus_trader.persistence.catalog import ParquetDataCatalog

__all__ = [
    "build_crypto_catalog",
    "build_futures_catalog",
    "crypto_instrument",
    "bar_type_for",
    "INTERVAL_MS",
]

INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}

#: Price precision per symbol family (the lake files carry 2-5 decimals; the
#: instrument must not be *finer* than the exchange's tick or NT will reject
#: the prices when it rounds them).
_PRICE_PRECISION = {"BTCUSDT": 2, "ETHUSDT": 2, "SOLUSDT": 3, "BNBUSDT": 3, "XRPUSDT": 4}


def _bar_spec(timeframe: str):
    from nautilus_trader.model.data import BarSpecification

    if timeframe not in INTERVAL_MS:
        raise ValueError(f"unsupported timeframe {timeframe!r}")
    minutes = INTERVAL_MS[timeframe] // 60_000
    if timeframe == "1d":
        return BarSpecification(1, BarAggregation.DAY, PriceType.LAST)
    if minutes % 60 == 0 and minutes >= 60:
        return BarSpecification(minutes // 60, BarAggregation.HOUR, PriceType.LAST)
    return BarSpecification(minutes, BarAggregation.MINUTE, PriceType.LAST)


def bar_type_for(instrument_id: str, timeframe: str) -> BarType:
    return BarType(InstrumentId.from_str(instrument_id), _bar_spec(timeframe))


def crypto_instrument(
    symbol: str,
    instrument_id: str,
    *,
    price_precision: int | None = None,
    size_precision: int = 3,
    taker_fee: float = 0.0004,
    maker_fee: float = 0.0002,
) -> CryptoPerpetual:
    """A Binance USDT-M linear perpetual (``BASEUSDT`` quoted in USDT)."""
    base = symbol.replace("USDT", "")
    precision = price_precision if price_precision is not None else _PRICE_PRECISION.get(symbol, 4)
    return CryptoPerpetual(
        instrument_id=InstrumentId.from_str(instrument_id),
        raw_symbol=Symbol(symbol),
        base_currency=Currency.from_str(base, 8),
        quote_currency=USDT,
        settlement_currency=USDT,
        is_inverse=False,
        price_precision=precision,
        size_precision=size_precision,
        price_increment=Price(10**-precision, precision),
        size_increment=Quantity(10**-size_precision, size_precision),
        multiplier=Quantity.from_int(1),
        lot_size=None,
        max_quantity=None,
        min_quantity=None,
        max_notional=None,
        min_notional=None,
        max_price=None,
        min_price=None,
        margin_init=Decimal("0.1"),
        margin_maint=Decimal("0.05"),
        maker_fee=Decimal(str(maker_fee)),
        taker_fee=Decimal(str(taker_fee)),
        ts_event=0,
        ts_init=0,
    )


def _load_lane(path: Path, timeframe: str) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    if "ts_event" not in frame.columns and "timestamp" in frame.columns:
        frame = frame.rename(columns={"timestamp": "ts_event"})
    frame["ts_event"] = frame["ts_event"].astype("int64")
    if int(frame["ts_event"].iloc[-1]) > 10**17:  # ns -> ms
        frame["ts_event"] = frame["ts_event"] // 1_000_000
    frame = frame.sort_values("ts_event").reset_index(drop=True)
    if not bool(np.all(np.diff(frame["ts_event"].to_numpy()) > 0)):
        raise ValueError(f"{path}: timestamps are not strictly ascending")
    return frame


def build_crypto_catalog(
    catalog_path: str | Path,
    *datasets: tuple[str, str | Path, str, str],
) -> Path:
    """Write instruments + bars into ``catalog_path`` and verify the round-trip.

    ``dataset`` = ``(symbol, parquet_path, timeframe, instrument_id)``.
    """
    catalog_path = Path(catalog_path)
    catalog = ParquetDataCatalog(str(catalog_path))
    for symbol, path, timeframe, instrument_id in datasets:
        frame = _load_lane(Path(path), timeframe)
        instrument = crypto_instrument(symbol, instrument_id)
        catalog.write_data([instrument])
        interval_ns = INTERVAL_MS[timeframe] * 1_000_000
        # the lake's ts_event is the bar's OPEN in ms; NT's Bar.ts_event is its
        # CLOSE in ns -- the shift is the interval, never a re-derivation
        closes = (frame["ts_event"].to_numpy(dtype=np.int64) * 1_000_000) + interval_ns
        bars = [
            Bar(
                bar_type=bar_type_for(instrument_id, timeframe),
                open=Price(float(o), instrument.price_precision),
                high=Price(float(h), instrument.price_precision),
                low=Price(float(low), instrument.price_precision),
                close=Price(float(c), instrument.price_precision),
                volume=Quantity(float(v), instrument.size_precision),
                ts_event=int(t),
                ts_init=int(t),
            )
            for o, h, low, c, v, t in zip(
                frame["open"], frame["high"], frame["low"], frame["close"],
                frame["volume"], closes,
            )
        ]
        catalog.write_data(bars)
        written = catalog.bars(bar_type_for(instrument_id, timeframe))
        if len(written) != len(bars):
            raise ValueError(
                f"{instrument_id}/{timeframe}: catalog holds {len(written)} bars, wrote {len(bars)}"
            )
        if abs(float(written[-1].close) - float(bars[-1].close)) > 10 ** -instrument.price_precision:
            raise ValueError(f"{instrument_id}/{timeframe}: last close changed in the round-trip")
    return catalog_path


def build_futures_catalog(
    catalog_path: str | Path,
    *datasets: tuple[str, str | Path, str],
) -> Path:
    """Write a CME index-futures catalog from the governed NQ/ES lanes.

    ``dataset`` = ``(root_symbol, parquet_path, timeframe)`` where
    ``root_symbol`` is one of NQ/ES/MNQ/MES.  MNQ and MES quote the **same
    price series** as NQ and ES (the micros are the same underlying); only the
    contract economics differ, so the lane is shared and the instrument is
    not.

    The continuous series is written as **one synthetic contract** spanning the
    data (the repo's "a continuous series is a series of dated contracts"
    decision is not applied here because the lake holds no per-contract data --
    the roll rule is the known gap, and a single spanning contract cannot fake
    a roll *inside* the sample).
    """
    from dodgys_dd_quant.data_pipeline.prepare_parquet import (
        CME_CONTRACT_SPECS,
        cme_contract,
    )

    catalog_path = Path(catalog_path)
    catalog = ParquetDataCatalog(str(catalog_path))
    for root_symbol, path, timeframe in datasets:
        spec = CME_CONTRACT_SPECS[root_symbol]
        frame = _load_lane(Path(path), timeframe)
        interval_ns = INTERVAL_MS[timeframe] * 1_000_000
        first_ns = int(frame["ts_event"].iloc[0]) * 1_000_000
        last_ns = int(frame["ts_event"].iloc[-1]) * 1_000_000 + interval_ns
        instrument = cme_contract(
            spec,
            activation_ns=first_ns,
            expiration_ns=last_ns + 86_400_000_000_000,
        )
        catalog.write_data([instrument])
        closes = (frame["ts_event"].to_numpy(dtype=np.int64) * 1_000_000) + interval_ns
        bars = [
            Bar(
                bar_type=BarType(instrument.id, _bar_spec(timeframe)),
                open=Price(float(o), instrument.price_precision),
                high=Price(float(h), instrument.price_precision),
                low=Price(float(low), instrument.price_precision),
                close=Price(float(c), instrument.price_precision),
                volume=Quantity(float(v), 0),
                ts_event=int(t),
                ts_init=int(t),
            )
            for o, h, low, c, v, t in zip(
                frame["open"], frame["high"], frame["low"], frame["close"],
                frame["volume"], closes,
            )
        ]
        catalog.write_data(bars)
        written = catalog.bars(bar_type=BarType(instrument.id, _bar_spec(timeframe)))
        if len(written) != len(bars):
            raise ValueError(
                f"{instrument.id}/{timeframe}: catalog holds {len(written)} bars, wrote {len(bars)}"
            )
    return catalog_path
