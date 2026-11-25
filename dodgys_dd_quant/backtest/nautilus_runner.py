"""Run the DodgysDD iFVG strategy inside NautilusTrader and export the result.

This is the bridge the design doc's module #5 names: Nautilus is the backtest
and live engine, the rule engine is the decision source, and the report is the
same shape the ML leaf consumes (fills + positions, Parquet).
"""

from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path

import pandas as pd

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.model.currencies import USD, USDT
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import InstrumentId, TraderId, Venue
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from dodgys_dd_quant.data_pipeline.catalog_builder import bar_type_for
from dodgys_dd_quant.strategy.dodgys_strategy import DodgysIFVGConfig, DodgysIFVGStrategy

__all__ = ["run_nautilus_backtest"]


def _write_report(frame, path: Path) -> None:
    """Write a report, flattening the struct/object columns NT leaves in.

    The fills report carries nested ``info`` structs that Parquet refuses to
    write when they have no children; they are serialised to JSON text here
    instead of being dropped (the raw payload is evidence, not decoration).
    """
    if frame is None or len(frame) == 0:
        pd.DataFrame().to_parquet(path, index=False)
        return
    out = frame.copy()
    for column in out.columns:
        series = out[column]
        if series.dtype == object or str(series.dtype).startswith(("void", "struct")):
            out[column] = series.map(
                lambda v: json.dumps(v, default=str) if isinstance(v, (dict, list, tuple)) else v
            ).astype("string")
    out.to_parquet(path, compression="zstd", index=False)


def run_nautilus_backtest(
    *,
    catalog_path: str | Path,
    candidate_feed: str | Path,
    out_dir: str | Path,
    instrument_id: str,
    timeframe: str,
    symbol: str | None = None,
    gate: str = "none",
    threshold: float = 0.58,
    risk_per_trade: float = 0.01,
    starting_balance: float = 100_000.0,
    max_hold_bars: int = 0,
    exit_mode: str = "bracket",
) -> dict:
    """One Nautilus backtest; the exports go to ``out_dir``.

    Returns a dict with the strategy's counters and the realised PnL, so a
    caller can compare it with the engine's one-position portfolio.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(catalog_path))
    # the venue comes from the instrument id: BINANCE for the crypto perps,
    # XCME for the CME micros
    venue = Venue(str(instrument_id).split(".")[-1])
    account_currency = USDT if venue.value == "BINANCE" else USD
    bar_type = bar_type_for(instrument_id, timeframe)
    bars = catalog.bars(bar_type=bar_type)
    if not bars:
        raise ValueError(f"{catalog_path}: no bars for {bar_type}")
    instruments = [i for i in catalog.instruments() if i.id == InstrumentId.from_str(instrument_id)]
    if not instruments:
        raise ValueError(f"{catalog_path}: no instrument {instrument_id}")
    instrument = instruments[0]

    try:
        from nautilus_trader.config import LoggingConfig

        logging = LoggingConfig(log_level="ERROR")
    except Exception:  # noqa: BLE001 - cosmetic only
        logging = None
    engine = BacktestEngine(
        BacktestEngineConfig(
            trader_id=TraderId("BACKTESTER-001"),
            **({"logging": logging} if logging is not None else {}),
        )
    )
    engine.add_venue(
        venue,
        OmsType.NETTING,
        AccountType.MARGIN,
        starting_balances=[Money(starting_balance, account_currency)],
        default_leverage=Decimal(1),
        # the simulated venue rejects a stop order by default; an iFVG trade
        # *is* a stop order, so it must be accepted
        reject_stop_orders=False,
    )
    engine.add_instrument(instrument)
    engine.add_data(bars)
    strategy = DodgysIFVGStrategy(
        DodgysIFVGConfig(
            instrument_id=instrument_id,
            bar_type=str(bar_type),
            candidate_feed=str(candidate_feed),
            symbol=symbol,
            gate=gate,
            threshold=threshold,
            risk_per_trade=risk_per_trade,
            max_hold_bars=max_hold_bars,
            exit_mode=exit_mode,
            log_events=False,
            log_commands=False,
        )
    )
    engine.add_strategy(strategy)
    engine.run()

    fills = engine.trader.generate_order_fills_report()
    positions = engine.trader.generate_positions_report()
    orders = engine.trader.generate_orders_report()
    account = engine.trader.generate_account_report(venue)
    trades = pd.DataFrame(strategy.trades)
    for name, frame in (
        ("fills", fills),
        ("positions", positions),
        ("orders", orders),
        ("account", account),
        ("trades", trades),
    ):
        _write_report(frame, out / f"{name}.parquet")
    engine.dispose()
    realised = 0.0
    if positions is not None and len(positions) and "realized_pnl" in positions.columns:
        # NT renders money as "<amount> <CURRENCY>"; take the amount
        amounts = pd.to_numeric(
            positions["realized_pnl"].astype(str).str.split().str[0], errors="coerce"
        )
        realised = float(amounts.sum())
    return {
        "instrument_id": instrument_id,
        "timeframe": timeframe,
        "bars": len(bars),
        "candidates": int(strategy.n_candidates),
        "brackets": int(strategy.n_brackets),
        "gate_blocked": int(strategy.n_skipped_gate),
        "busy_blocked": int(strategy.n_skipped_busy),
        "fills": int(len(fills)) if fills is not None else 0,
        "positions": int(len(positions)) if positions is not None else 0,
        "realized_pnl": realised,
        "out_dir": str(out),
    }
