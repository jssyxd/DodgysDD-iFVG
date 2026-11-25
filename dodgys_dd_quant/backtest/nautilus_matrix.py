"""The NautilusTrader matrix: same cells as the engine, executed in Nautilus.

For every cell the engine still decides the *candidates* (that is the audited
rule layer); Nautilus executes them with bracket orders and its own position
accounting.  The parity assertion per cell is:

    positions opened in Nautilus  ==  trades selected by the engine's
                                      one-position portfolio

A mismatch is a real finding (order rejection, sizing rounding, a bracket that
cannot be placed), never something to hide.

Cells: the five crypto perps, plus **MNQ / MES** -- the micro CME contracts
that suit the iFVG/ICT intraday windows.  The micros quote the *same* price
series as NQ/ES, so the lane is shared and only the instrument economics
(tick value, multiplier, commission) differ.
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import Sequence

import pandas as pd

from dodgys_dd_quant.backtest.cost_model import profile_for
from dodgys_dd_quant.backtest.matrix import _bars_frame, _MINUTES, lane_path
from dodgys_dd_quant.backtest.nautilus_runner import run_nautilus_backtest
from dodgys_dd_quant.backtest.records import write_parquet
from dodgys_dd_quant.backtest.walk_forward import simulate_portfolio
from dodgys_dd_quant.data_pipeline.catalog_builder import (
    build_crypto_catalog,
    build_futures_catalog,
)
from dodgys_dd_quant.strategy.regime import (
    DEFAULT_DVOL_PATH,
    DEFAULT_VXN_PATH,
    DvolRegimeIndex,
    VxnRegimeIndex,
)
from dodgys_dd_quant.strategy.state_machine import PRESETS, run_state_machine
from dodgys_dd_quant.strategy.structure import load_bars

__all__ = ["cells", "run_cell", "main"]

CRYPTO = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
#: (mini instrument id, mini root, source root, cost profile)
FUTURES = (
    ("MNQ.XCME", "MNQ", "NQ", "mnq"),
    ("MES.XCME", "MES", "ES", "mes"),
)
TIMEFRAMES = ("30m", "1h")
DEFAULT_PRESETS = ("honest", "doc")


def cells(symbols: Sequence[str], timeframes: Sequence[str], presets: Sequence[str]):
    for symbol in symbols:
        for timeframe in timeframes:
            for preset in presets:
                yield ("crypto", symbol, symbol, timeframe, preset)
    for instrument_id, mini, root, profile in FUTURES:
        for timeframe in timeframes:
            for preset in presets:
                yield ("futures", instrument_id, root, timeframe, preset)


def _rows(path: Path) -> int:
    try:
        import pyarrow.parquet as pq

        return int(pq.read_metadata(path).num_rows)
    except Exception:  # noqa: BLE001 - a missing/broken lane is 0 rows
        return 0


def _futures_lane(lake_root: Path, root: str, timeframe: str) -> Path:
    """The first lane of this timeframe that actually holds bars.

    A daily lane resampled from 1m has **zero** complete buckets (the CME
    daily maintenance break makes every 24 h window incomplete), so an empty
    ``*_1d_resampled`` file must fall through to the exchange's own daily bars.
    """
    base = lake_root / "us_futures" / root / timeframe
    for name in (
        f"{root}_{timeframe}_resampled.parquet",
        f"{root}_{timeframe}_consolidated.parquet",
        f"{root}_{timeframe}.parquet",
    ):
        path = base / name
        if path.exists() and _rows(path) > 0:
            return path
    raise FileNotFoundError(f"no non-empty {timeframe} lane for {root} under {base}")


def run_cell(
    kind: str,
    label: str,
    root: str,
    timeframe: str,
    preset: str,
    *,
    lake_root: Path,
    work: Path,
    horizon_minutes: float,
    crypto_regime,
    futures_regime,
    chunk_quarters: bool = False,
    chunk_limit: int | None = None,
) -> dict:
    started = time.time()
    minutes = _MINUTES[timeframe]
    horizon = max(1, int(round(max(float(horizon_minutes), 20.0 * minutes) / minutes)))
    if kind == "crypto":
        lane = lane_path(root, timeframe, lake_root)
        regime = crypto_regime
        reference = None
        cost_name = None
        profile = profile_for(root, None)
        catalog_kind = "crypto"
    else:
        lane = _futures_lane(lake_root, root, timeframe)
        regime = futures_regime
        paired = "ES" if root == "NQ" else "NQ"
        try:
            reference = load_bars(_futures_lane(lake_root, paired, timeframe), symbol=paired, timeframe=timeframe)
        except FileNotFoundError:
            reference = None
        cost_name = "mnq" if root == "NQ" else "mes"
        profile = profile_for(label.split(".")[0], cost_name)
        catalog_kind = "futures"

    bars = load_bars(lane, symbol=root, timeframe=timeframe)
    config = replace(PRESETS[preset], symbol=root, timeframe=timeframe, horizon_bars=horizon)
    log = run_state_machine(bars, config, regime=regime, reference=reference)
    selected = simulate_portfolio(log.candidates, len(bars), config.horizon_bars)

    tag = f"{label}_{timeframe}_{preset}".replace(".", "_")
    if chunk_quarters:
        return _run_chunked(
            kind=kind, label=label, root=root, timeframe=timeframe, preset=preset,
            bars=bars, log=log, selected=selected, work=work, tag=tag,
            horizon=horizon, chunk_limit=chunk_limit, started=started,
        )
    feed = work / f"{tag}_feed.parquet"
    log.write_parquet(feed)
    catalog_path = work / f"{tag}_catalog"
    if catalog_kind == "crypto":
        build_crypto_catalog(catalog_path, (root, lane, timeframe, f"{root}.BINANCE"))
        instrument_id = f"{root}.BINANCE"
    else:
        build_futures_catalog(catalog_path, (label.split(".")[0], lane, timeframe))
        instrument_id = label

    result = run_nautilus_backtest(
        catalog_path=catalog_path,
        candidate_feed=feed,
        out_dir=work / f"{tag}_out",
        instrument_id=instrument_id,
        timeframe=timeframe,
        gate="none",
        # at 1m both bracket legs can fill inside one bar (Nautilus overflow),
        # so the exit is resolved bar by bar instead
        exit_mode="manual" if timeframe == "1m" else "bracket",
        # the engine censors a trade at the horizon; Nautilus must exit then
        # too, or its positions live longer and block later signals
        max_hold_bars=int(horizon),
    )
    # --- the R reconciliation -------------------------------------------
    # The strategy's position objects are not reliably reachable from the
    # callbacks in this runtime, so the mapping is done from the exports: NT
    # fills the entry on the bar *after* the decision, so a position opened at
    # ``ts`` belongs to the candidate whose ``ts_event`` is ``ts - interval``.
    reconciled = _reconcile(
        work / f"{tag}_out" / "positions.parquet",
        log,
        interval_ns=_MINUTES[timeframe] * 60_000_000,
    )

    row = {
        "kind": kind,
        "instrument": label,
        "source_root": root,
        "timeframe": timeframe,
        "preset": preset,
        "bars": len(bars),
        "candidates": len(log),
        "engine_trades": len(selected),
        "nt_candidates": result["candidates"],
        "nt_brackets": result["brackets"],
        "nt_positions": result["positions"],
        "nt_fills": result["fills"],
        "nt_realized_pnl": result["realized_pnl"],
        "recon_n": int(reconciled["n"]),
        "mean_r_engine": reconciled["mean_r_engine"],
        "mean_r_nt": reconciled["mean_r_nt"],
        "mean_abs_dr": reconciled["mean_abs_dr"],
        "r_corr": reconciled["r_corr"],
        # boundary effects (a bracket placed on the last bars, a position still
        # open at the end) leave a 1-3 trade gap; 1 % of the engine's count is
        # the parity tolerance, and the raw difference is recorded too
        "nt_minus_engine": int(result["positions"] - len(selected)),
        "match": int(abs(result["positions"] - len(selected)) <= max(2, 0.01 * len(selected))),
        "cost_profile": profile.name,
        "runtime_s": round(time.time() - started, 2),
    }
    print(
        f"{label:<12} {timeframe:>4} {preset:<7} candidates={row['candidates']:>6} "
        f"engine={row['engine_trades']:>5} nt_positions={row['nt_positions']:>5} "
        f"match={'yes' if row['match'] else 'NO '} pnl={row['nt_realized_pnl']:>12.2f} "
        f"({row['runtime_s']:.1f}s)"
    )
    return row



def _reconcile(positions_path: Path, log, *, interval_ns: int) -> dict:
    """Join NT positions to the engine's candidates and compare R.

    ``r_nt = (avg_px_close - avg_px_open) * side / risk_points`` uses the same
    risk the candidate carries, so it is directly comparable with the engine's
    ``r_multiple``.
    """
    import numpy as np
    import pandas as pd

    empty = {"n": 0, "mean_r_engine": float("nan"), "mean_r_nt": float("nan"),
             "mean_abs_dr": float("nan"), "r_corr": float("nan")}
    if not positions_path.exists():
        return empty
    positions = pd.read_parquet(positions_path)
    # the *order's own* tags carry the candidate's risk and timestamp, which
    # removes the ambiguity of several same-side candidates on one bar
    orders_path = positions_path.with_name("orders.parquet")
    risk_by_order: dict[str, float] = {}
    ts_by_order: dict[str, int] = {}
    if orders_path.exists():
        orders = pd.read_parquet(orders_path)
        if "tags" in orders.columns and "client_order_id" in orders.columns:
            for row in orders.itertuples():
                tags = row.tags
                if isinstance(tags, str):
                    tags = [t.strip("\"'") for t in tags.strip("[]").split(",") if t.strip()]
                if not tags:
                    continue
                tag_map = {}
                for tag in tags:
                    text = str(tag).strip("\"'")
                    if "=" in text:
                        key, value = text.split("=", 1)
                        tag_map[key] = value
                if "risk" in tag_map:
                    risk_by_order[str(row.client_order_id)] = float(tag_map["risk"])
                if "cand_ts" in tag_map:
                    ts_by_order[str(row.client_order_id)] = int(tag_map["cand_ts"])
    if not len(positions) or "ts_opened" not in positions.columns:
        return empty
    feed = pd.DataFrame(log.to_table()).copy()
    feed["ts_event"] = feed["ts_event"].astype("int64")
    feed = feed[np.isfinite(feed["r_multiple"])]
    feed["side_sign"] = np.where(feed["side"] == "BUY", 1, np.where(feed["side"] == "SELL", -1, np.nan))
    # the D2 table stores side as text (BUY/SELL); normalise to +1/-1
    if feed["side_sign"].isna().all():
        feed["side_sign"] = pd.to_numeric(feed["side"], errors="coerce")
    frame = pd.DataFrame({
        "ts_event": feed["ts_event"].to_numpy(),
        "side_sign": feed["side_sign"].to_numpy(),
        "risk": pd.to_numeric(feed["risk"], errors="coerce").to_numpy(),
        "engine_r": pd.to_numeric(feed["r_multiple"], errors="coerce").to_numpy(),
    })
    # NT's bar ``ts_event`` is the bar's CLOSE, and so is the D2 candidate's
    # ``ts_event``: a market order submitted at that instant fills *at* it
    frame["ts_opened"] = frame["ts_event"]
    pos = pd.DataFrame({
        "ts_opened": positions["ts_opened"].astype("int64").to_numpy(),
        "side": positions["entry"].astype(str).to_numpy(),
        "avg_px_open": pd.to_numeric(positions["avg_px_open"], errors="coerce").to_numpy(),
        "avg_px_close": pd.to_numeric(positions["avg_px_close"], errors="coerce").to_numpy(),
        "quantity": pd.to_numeric(positions["peak_qty"], errors="coerce").to_numpy(),
        "opening_order_id": positions["opening_order_id"].astype(str).to_numpy(),
    })
    pos["side_sign"] = np.where(pos["side"] == "BUY", 1, -1)
    pos["tag_risk"] = pos["opening_order_id"].map(risk_by_order)
    pos["tag_ts"] = pos["opening_order_id"].map(ts_by_order)
    if pos["tag_risk"].notna().any():
        # the exact candidate from the order's own stamp: no inferred joins
        exact = pos[pos["tag_risk"].notna()].copy()
        exact["ts_opened"] = exact["tag_ts"].astype("int64")
        exact["risk"] = exact["tag_risk"].astype(float)
        exact = exact.merge(
            frame[["ts_event", "side_sign", "engine_r"]].rename(columns={"ts_event": "ts_opened"}),
            on=["ts_opened", "side_sign"],
            how="left",
        )
        if len(exact):
            r_nt = (exact["avg_px_close"] - exact["avg_px_open"]) * exact["side_sign"] / exact["risk"]
            ok = np.isfinite(r_nt) & np.isfinite(exact["engine_r"])
            if ok.any():
                sub = exact[ok]
                r = r_nt[ok]
                return {
                    "n": int(len(sub)),
                    "mean_r_engine": float(sub["engine_r"].mean()),
                    "mean_r_nt": float(r.mean()),
                    "mean_abs_dr": float((r - sub["engine_r"]).abs().mean()),
                    "r_corr": float(r.corr(sub["engine_r"])) if len(sub) > 2 else float("nan"),
                }
    joined = frame.merge(pos[["ts_opened", "side_sign", "avg_px_open", "avg_px_close"]],
                         on=["ts_opened", "side_sign"], how="inner")
    if joined.empty:
        return empty
    r_nt = (joined["avg_px_close"] - joined["avg_px_open"]) * joined["side_sign"] / joined["risk"]
    ok = np.isfinite(r_nt)
    joined, r_nt = joined[ok], r_nt[ok]
    if joined.empty:
        return empty
    diff = (r_nt - joined["engine_r"]).abs()
    corr = float(r_nt.corr(joined["engine_r"])) if len(joined) > 2 else float("nan")
    return {
        "n": int(len(joined)),
        "mean_r_engine": float(joined["engine_r"].mean()),
        "mean_r_nt": float(r_nt.mean()),
        "mean_abs_dr": float(diff.mean()),
        "r_corr": corr,
    }



def _run_chunked(*, kind, label, root, timeframe, preset, bars, log, selected, work, tag,
                 horizon, chunk_limit, started) -> dict:
    """Run one cell **quarter by quarter**.

    A 2M-bar catalog write is what killed the 1m cell (the panic was fixed by
    the manual exit, but the write alone took the whole budget). A quarter is
    ~130k 1m bars, small enough to catalog and backtest in seconds; the sums
    are the cell's.
    """
    import time

    import numpy as np
    import pandas as pd

    from dodgys_dd_quant.data_pipeline.catalog_builder import build_crypto_catalog

    feed = pd.DataFrame(log.to_table())
    ts = bars.ts.astype("int64")
    quarters = pd.PeriodIndex(pd.to_datetime(ts, unit="ns", utc=True), freq="Q")
    feed_q = pd.PeriodIndex(pd.to_datetime(feed["ts_event"].astype("int64"), unit="ns", utc=True), freq="Q")
    periods = sorted(set(quarters))
    if chunk_limit:
        periods = periods[: int(chunk_limit)]
    pos = cand = fills = 0
    pnl = 0.0
    engine_count = 0
    selected_ts = {int(c.ts_event) for c in selected}
    for period in periods:
        idx = np.flatnonzero(quarters == period)
        if not idx.size:
            continue
        sub = bars.slice(int(idx[0]), int(idx[-1]) + 1)
        lane = work / f"{tag}_{period}.parquet"
        pd.DataFrame({
            "ts_event": sub.ts.astype("int64") // 1_000_000, "open": sub.open, "high": sub.high,
            "low": sub.low, "close": sub.close, "volume": sub.volume,
        }).to_parquet(lane, index=False)
        cat = work / f"{tag}_{period}_catalog"
        if kind == "crypto":
            build_crypto_catalog(cat, (root, lane, timeframe, f"{root}.BINANCE"))
            instrument_id = f"{root}.BINANCE"
        else:
            from dodgys_dd_quant.data_pipeline.catalog_builder import build_futures_catalog

            build_futures_catalog(cat, (label.split(".")[0], lane, timeframe))
            instrument_id = label
        mask = np.asarray(feed_q == period)
        feed_path = work / f"{tag}_{period}_feed.parquet"
        pd.DataFrame({k: v[mask] for k, v in feed.items()}).to_parquet(feed_path, index=False)
        engine_count += sum(1 for t in feed.loc[mask, "ts_event"].astype("int64") if t in selected_ts)
        res = run_nautilus_backtest(
            catalog_path=cat, candidate_feed=feed_path, out_dir=work / f"{tag}_{period}_out",
            instrument_id=instrument_id, timeframe=timeframe, gate="none",
            exit_mode="manual" if timeframe == "1m" else "bracket",
            max_hold_bars=int(horizon),
        )
        pos += int(res["positions"]); cand += int(res["candidates"]); fills += int(res["fills"])
        pnl += float(res["realized_pnl"])
        print(f"  {label} {timeframe} {preset} {period}: nt_positions={res['positions']} "
              f"candidates={res['candidates']}")
    row = {
        "kind": kind, "instrument": label, "source_root": root, "timeframe": timeframe,
        "preset": preset, "bars": len(bars), "candidates": len(log),
        "engine_trades": engine_count, "nt_candidates": cand, "nt_brackets": cand,
        "nt_positions": pos, "nt_fills": fills, "nt_realized_pnl": pnl,
        "nt_minus_engine": pos - engine_count,
        "match": int(abs(pos - engine_count) <= max(2, 0.01 * max(1, engine_count))),
        "cost_profile": "", "runtime_s": round(time.time() - started, 2),
        "recon_n": 0, "mean_r_engine": float("nan"), "mean_r_nt": float("nan"),
        "mean_abs_dr": float("nan"), "r_corr": float("nan"),
        "chunks": len(periods),
    }
    print(f"{label:<12} {timeframe:>4} {preset:<7} chunks={len(periods)} "
          f"engine={engine_count} nt_positions={pos} match={'yes' if row['match'] else 'NO'}")
    return row


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(prog="nautilus_matrix", description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=list(CRYPTO))
    parser.add_argument("--timeframes", nargs="+", default=list(TIMEFRAMES))
    parser.add_argument("--presets", nargs="+", default=list(DEFAULT_PRESETS))
    parser.add_argument("--no-futures", action="store_true")
    parser.add_argument("--only-futures", action="store_true")
    parser.add_argument("--chunk-quarters", action="store_true",
                        help="run each cell quarter by quarter (needed for 1m)")
    parser.add_argument("--chunk-limit", type=int, default=None,
                        help="only the first N quarters (a bounded 1m proof)")
    parser.add_argument("--horizon-minutes", type=float, default=3600.0)
    parser.add_argument(
        "--lake-root",
        default=str(Path("~/iflow_lake/iflow/database/03_governed_lake/v2_parquet_lake").expanduser()),
    )
    parser.add_argument("--out", default="artifacts/nautilus_matrix")
    args = parser.parse_args(argv)

    lake_root = Path(args.lake_root).expanduser()
    work = Path(args.out) / "_work"
    work.mkdir(parents=True, exist_ok=True)
    crypto_regime = DvolRegimeIndex.from_parquet(DEFAULT_DVOL_PATH)
    futures_regime = VxnRegimeIndex.from_parquet(DEFAULT_VXN_PATH)

    rows: list[dict] = []
    for kind, label, root, timeframe, preset in cells(args.symbols, args.timeframes, args.presets):
        if kind == "futures" and args.no_futures:
            continue
        if kind == "crypto" and args.only_futures:
            continue
        try:
            rows.append(
                run_cell(
                    kind, label, root, timeframe, preset,
                    lake_root=lake_root, work=work,
                    horizon_minutes=args.horizon_minutes,
                    crypto_regime=crypto_regime,
                    futures_regime=futures_regime,
                    chunk_quarters=args.chunk_quarters,
                    chunk_limit=args.chunk_limit,
                )
            )
        except Exception as exc:  # noqa: BLE001 - the matrix reports
            print(f"FAILED {label}/{timeframe}/{preset}: {type(exc).__name__}: {exc}")

    frame = pd.DataFrame(rows)
    out = Path(args.out)
    write_parquet(frame, out / "runs.parquet")
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "command": " ".join(["python -m dodgys_dd_quant.backtest.nautilus_matrix", *list(argv or [])]),
                "lake_root": str(lake_root),
                "horizon_minutes": args.horizon_minutes,
                "n_cells": len(frame),
                "parity_cells": int(frame["match"].sum()) if len(frame) else 0,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {out}/runs.parquet ({len(frame)} cells, "
          f"{int(frame['match'].sum()) if len(frame) else 0} parity match)")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
