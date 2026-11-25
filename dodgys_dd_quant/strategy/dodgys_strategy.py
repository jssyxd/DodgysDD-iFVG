"""The NautilusTrader strategy of the DodgysDD iFVG system (doc module #5).

Design (frozen in ``.herd-swarm/decisions.md``, D1): the *rules* are the
engine's -- a pure function of the bar history, validated by the benchmark --
and they arrive here as a **precomputed candidate feed** (the D2 log or the
archive).  Nautilus owns everything the engine cannot: order placement, fills,
position accounting and the export.  The alternative -- calling the engine per
bar -- is quadratic in the history and would make a backtest useless.

Pine -> Nautilus mapping: ``research/nautilus/PINE_TO_NAUTILUS.md``.
The replica's ``hideLosing`` has **no** counterpart on purpose (INV4: a signal
is never erased), and the killzones gate *alerts*, not setups.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, OrderType, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import Strategy

__all__ = ["DodgysIFVGConfig", "DodgysIFVGStrategy", "load_candidate_feed"]


def load_candidate_feed(path: str | Path, symbol: str | None = None) -> pd.DataFrame:
    """The candidate feed of one symbol, sorted by the decision timestamp.

    Accepts both the D2 log and the archive.  ``ts_event`` is normalised to
    **nanoseconds** (the archive also carries ``ts_event_ms``).
    """
    frame = pd.read_parquet(path)
    if "ts_event" not in frame.columns and "timestamp" in frame.columns:
        frame = frame.rename(columns={"timestamp": "ts_event"})
    if symbol is not None and "symbol" in frame.columns:
        frame = frame[frame["symbol"] == symbol]
    if frame.empty:
        # the ATR floor can filter *every* setup on a timeframe (measured on
        # 4h/1d); an empty feed is a zero-candidate cell, not an error
        for column, default in (
            ("ts_event", pd.Series(dtype="int64")),
            ("side", pd.Series(dtype="int64")),
            ("entry_price", pd.Series(dtype="float64")),
            ("stop_price", pd.Series(dtype="float64")),
            ("target_price", pd.Series(dtype="float64")),
            ("risk", pd.Series(dtype="float64")),
            ("r_multiple", pd.Series(dtype="float64")),
            ("p_win", pd.Series(dtype="float64")),
        ):
            frame[column] = default
        return frame.reset_index(drop=True)
    frame = frame.copy()
    frame["ts_event"] = frame["ts_event"].astype("int64")
    if int(frame["ts_event"].max()) < 10**17:  # ms -> ns
        frame["ts_event"] = frame["ts_event"] * 1_000_000
    for column, default in (
        ("be_price", float("nan")),
        ("p_win", float("nan")),
        ("bars_to_inversion", -1),
        ("checklist_score", float("nan")),
        ("smt_divergence", -1),
        ("vxn_known", float("nan")),
        ("vxn_regime", -1),
    ):
        if column not in frame.columns:
            frame[column] = default
    frame = frame.sort_values("ts_event", kind="mergesort").reset_index(drop=True)
    if not bool(np.all(np.diff(frame["ts_event"].to_numpy()) >= 0)):
        raise ValueError(f"{path}: the feed is not ordered")
    return frame


class DodgysIFVGConfig(StrategyConfig, frozen=True):
    """Execution switches only -- the rules live in the engine."""

    instrument_id: str
    bar_type: str
    candidate_feed: str
    symbol: str | None = None
    #: ``none`` (take every candidate), ``absolute`` (p_win >= threshold) or
    #: ``quantile`` (the feed already carries the per-fold threshold decision;
    #: here it is treated as absolute, which is what the archive stores).
    gate: str = "none"
    threshold: float = 0.58
    risk_per_trade: float = 0.01
    #: The equity used to size each trade.  A fixed number keeps the backtest
    #: deterministic and avoids compounding drift between Nautilus and the
    #: engine's R-space accounting (which is per-trade, not per-equity).
    equity: float = 100_000.0
    max_hold_bars: int = 0  # 0 disables the time exit
    #: ``bracket`` (entry + resting TP/SL) or ``manual`` (a plain entry and a
    #: bar-by-bar exit).  At 1-minute resolution both bracket legs can trigger
    #: inside one bar and Nautilus's netting position underflows (measured:
    #: ``Quantity::from_raw raw=3.4e38``), so 1m runs use ``manual``.
    exit_mode: str = "bracket"
    log_feed: bool = False


class DodgysIFVGStrategy(Strategy):
    """One position at a time; a blocked signal is dropped (D4, ``drop``)."""

    def __init__(self, config: DodgysIFVGConfig) -> None:
        super().__init__(config)
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type = BarType.from_str(config.bar_type)
        self.feed = load_candidate_feed(config.candidate_feed, config.symbol)
        self._by_ts: dict[int, list[dict]] = {}
        for row in self.feed.to_dict("records"):
            self._by_ts.setdefault(int(row["ts_event"]), []).append(row)
        self.instrument = None
        self.n_candidates = 0
        self.n_skipped_gate = 0
        self.n_skipped_busy = 0
        self.n_brackets = 0
        self._hold_bars = 0
        self._open_tags: set[str] = set()
        #: entry order id -> the candidate that opened it
        self._by_order: dict[str, dict] = {}
        #: the candidate behind the single open position (manual exit mode)
        self._open_cand: dict | None = None
        #: position_id -> the candidate that opened it (for the R reconciliation)
        self._by_position: dict[str, dict] = {}
        #: one row per closed position, in **R** (comparable with the engine)
        self.trades: list[dict] = []

    # --- lifecycle --------------------------------------------------------
    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            raise RuntimeError(f"no instrument {self.instrument_id} in the cache")
        self.subscribe_bars(self.bar_type)
        self.log.info(
            f"iFVG feed: {len(self.feed)} candidate(s), gate={self.config.gate}"
        )

    # --- decisions --------------------------------------------------------
    def on_bar(self, bar: Bar) -> None:
        if self.config.exit_mode == "manual":
            self._check_manual_exit(bar)
        if self.config.max_hold_bars and not self.portfolio.is_flat(self.instrument_id):
            self._hold_bars += 1
            if self._hold_bars >= self.config.max_hold_bars:
                self._close_all(bar)
        for cand in self._by_ts.get(int(bar.ts_event), ()):
            self._try_enter(cand, bar)

    def _gate_passes(self, cand: dict) -> bool:
        gate = str(self.config.gate).lower()
        if gate == "none":
            return True
        p = float(cand.get("p_win", float("nan")))
        return bool(np.isfinite(p) and p >= float(self.config.threshold))

    def _try_enter(self, cand: dict, bar: Bar) -> None:
        self.n_candidates += 1
        if not self._gate_passes(cand):
            self.n_skipped_gate += 1
            return
        if not self.portfolio.is_flat(self.instrument_id):
            self.n_skipped_busy += 1
            return
        side = int(cand["side"])
        risk = float(cand["risk"])
        entry = float(cand["entry_price"])
        stop = float(cand["stop_price"])
        target = float(cand["target_price"])
        if not (np.isfinite(risk) and risk > 0 and entry > 0 and target > 0 and stop > 0):
            return
        equity = float(self.config.equity)
        # the currency risk of one unit is ``risk_points * multiplier``; omitting
        # the multiplier oversized MNQ/MES by 2x/5x (measured against R space)
        multiplier = float(getattr(self.instrument, "multiplier", 1.0) or 1.0)
        qty_raw = (equity * float(self.config.risk_per_trade)) / (risk * multiplier)
        precision = self.instrument.size_precision
        qty = Quantity(round(qty_raw, precision), precision)
        if float(qty) <= 0:
            return
        order_side = OrderSide.BUY if side > 0 else OrderSide.SELL
        if self.config.exit_mode == "manual":
            order = self.order_factory.market(
                instrument_id=self.instrument_id,
                order_side=order_side,
                quantity=qty,
                tags=["ifvg", f"cand_ts={int(cand.get('ts_event', 0))}",
                      f"risk={risk:.10g}", f"side={side}"],
            )
            self._by_order[str(order.client_order_id)] = cand
            self.submit_order(order)
            self._open_cand = cand
            self.n_brackets += 1
            self._hold_bars = 0
            return
        bracket = self.order_factory.bracket(
            instrument_id=self.instrument_id,
            order_side=order_side,
            quantity=qty,
            entry_order_type=OrderType.MARKET,
            tp_price=Price(target, self.instrument.price_precision),
            sl_trigger_price=Price(stop, self.instrument.price_precision),
            tp_post_only=False,
            entry_tags=[
                "ifvg",
                f"cand_ts={int(cand.get('ts_event', 0))}",
                f"risk={risk:.10g}",
                f"side={side}",
            ],
            time_in_force=TimeInForce.GTC,
        )
        # bind the candidate to the entry order: ``on_position_opened`` can
        # then recover exactly which candidate the position belongs to
        entry_order = bracket.orders[0] if hasattr(bracket, "orders") else bracket[0]
        self._by_order[str(entry_order.client_order_id)] = cand
        self.submit_order_list(bracket)
        self.n_brackets += 1
        self._hold_bars = 0
        if self.config.log_feed:
            self.log.info(
                f"candidate {cand.get('ts_event')} side={side} entry={entry} "
                f"stop={stop} target={target} qty={qty}"
            )

    # --- position bookkeeping (the R reconciliation) ----------------------
    def on_event(self, event) -> None:
        """Bind candidates to positions and record closed ones, in R.

        The ``on_position_*`` callbacks are not delivered for a netting
        position in this runtime (measured: zero calls on 1,130 closes), but
        the ``PositionOpened``/``PositionClosed`` *events* are, so the
        bookkeeping hangs off them.
        """
        from nautilus_trader.model.events import PositionClosed, PositionOpened

        try:
            if isinstance(event, PositionOpened):
                cand = self._by_order.pop(str(event.opening_order_id), None)
                if cand is not None:
                    self._by_position[str(event.position_id)] = cand
            elif isinstance(event, PositionClosed):
                # ``event.id`` is the event's UUID; the position is ``position_id``
                position = self.cache.position(event.position_id)
                if position is not None:
                    self._record_trade(position)
        except Exception as exc:  # noqa: BLE001 - never let bookkeeping kill the run
            self.log.error(f"position event handling failed: {exc!r}")

    def on_position_opened(self, position) -> None:
        cand = self._by_order.pop(str(position.opening_order_id), None)
        if cand is not None:
            self._by_position[str(position.id)] = cand

    def on_position_closed(self, position) -> None:
        self._record_trade(position)

    def _record_trade(self, position) -> None:
        """One closed position -> one R-space row (never double counted)."""
        try:
            cand = self._by_position.pop(str(position.id), None)
            if cand is None:
                cand = self._by_order.pop(str(position.opening_order_id), None)
            if cand is None:
                return
            risk = float(cand.get("risk", float("nan")))
            side = int(cand.get("side", 0))
            entry = float(position.avg_px_open)
            exit_ = float(position.avg_px_close)
            r = (exit_ - entry) * side / risk if risk and risk > 0 else float("nan")
            try:
                commission = float(position.commissions())
            except Exception:  # noqa: BLE001 - the accessor differs across versions
                commission = 0.0
            self.trades.append(
                {
                    "ts_event": int(cand.get("ts_event", 0)),
                    "side": side,
                    "entry_px": entry,
                    "exit_px": exit_,
                    "risk_points": risk,
                    "quantity": float(position.quantity),
                    "r_multiple": r,
                    "engine_r": float(cand.get("r_multiple", float("nan"))),
                    "pnl": float(position.realized_pnl),
                    "commission": commission,
                    "ts_opened": int(position.ts_opened),
                    "ts_closed": int(position.ts_closed),
                }
            )
        except Exception as exc:  # noqa: BLE001 - never let the export kill the run
            self.log.error(f"trade record failed: {exc!r}")

    def _check_manual_exit(self, bar: Bar) -> None:
        """Resolve the open position against this bar: stop first, then target."""
        cand = self._open_cand
        if cand is None:
            return
        side = int(cand.get("side", 0))
        stop = float(cand.get("stop_price", float("nan")))
        target = float(cand.get("target_price", float("nan")))
        low, high = float(bar.low), float(bar.high)
        hit_stop = low <= stop if side > 0 else high >= stop
        hit_target = high >= target if side > 0 else low <= target
        if not (hit_stop or hit_target):
            return
        for position in self.cache.positions_open(instrument_id=self.instrument_id):
            self.close_position(position)
        self._open_cand = None

    def _close_all(self, bar: Bar) -> None:
        for position in self.cache.positions_open(instrument_id=self.instrument_id):
            self.close_position(position)
        for order in self.cache.orders_open(instrument_id=self.instrument_id):
            self.cancel_order(order)
        self._hold_bars = 0

    # --- reporting --------------------------------------------------------
    def on_stop(self) -> None:
        self.log.info(
            f"iFVG summary: candidates={self.n_candidates} "
            f"brackets={self.n_brackets} gate_blocked={self.n_skipped_gate} "
            f"busy_blocked={self.n_skipped_busy}"
        )
