"""The baseline matrix: every symbol x every timeframe x every preset.

Runs the rule engine (no model: this is the **baseline**), the one-position
portfolio, and the rolling statistics, then archives

* ``runs.parquet``      -- one row per cell, with the full statistics;
* ``candidates.parquet``-- one row per candidate, with features, the
  selection flag and the final label ``y``;
* ``folds.parquet``     -- the fold table (empty for a rule-only cell);
* ``SUMMARY.md``        -- the human-readable matrix;
* ``manifest.json``     -- the command, the commit, the lake root.

CLI::

    python -m dodgys_dd_quant.backtest.matrix \
        --symbols BTCUSDT ETHUSDT SOLUSDT BNBUSDT XRPUSDT \
        --timeframes 5m 15m 30m 1h 2h 4h 1d \
        --presets honest doc --horizon-minutes 3600 \
        --out artifacts/matrix_2026-11-24
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from dodgys_dd_quant.backtest.cost_model import profile_for
from dodgys_dd_quant.backtest.records import (
    candidate_frame,
    run_record,
    summary_markdown,
    write_parquet,
)
from dodgys_dd_quant.backtest.walk_forward import simulate_portfolio, walk_forward
from dodgys_dd_quant.ml_pipeline.features import build_features
from dodgys_dd_quant.strategy.regime import DEFAULT_DVOL_PATH, DvolRegimeIndex
from dodgys_dd_quant.strategy.state_machine import PRESETS, run_state_machine
from dodgys_dd_quant.strategy.structure import load_bars

__all__ = ["lane_path", "run_cell", "main"]

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
TIMEFRAMES = ("5m", "15m", "30m", "1h", "2h", "4h", "1d")
DEFAULT_PRESETS = ("honest", "doc")

_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "1d": 1440}


def lane_path(symbol: str, timeframe: str, lake_root: Path) -> Path:
    """The longest lane for ``symbol``/``timeframe``.

    The lake's ``*_consolidated`` lanes are often shorter than the resampled
    ones (several are one-month stubs), so the matrix prefers the resampled
    lane when it exists and is non-trivial.
    """
    folder = lake_root / "crypto" / "futures_um" / symbol / timeframe
    resampled = folder / f"{symbol}_{timeframe}_resampled.parquet"
    consolidated = folder / f"{symbol}_{timeframe}_consolidated.parquet"
    if resampled.exists():
        return resampled
    if consolidated.exists():
        return consolidated
    raise FileNotFoundError(f"no {timeframe} lane for {symbol} under {folder}")


#: The micro CME contracts: (traded symbol, source root, cost profile).  The
#: micros quote the same price series as NQ/ES, so the lane is shared and only
#: the instrument economics differ.
FUTURES = (
    ("MNQ", "NQ", "mnq"),
    ("MES", "ES", "mes"),
)


def _rows(path: Path) -> int:
    try:
        import pyarrow.parquet as pq

        return int(pq.read_metadata(path).num_rows)
    except Exception:  # noqa: BLE001
        return 0


def futures_lane(lake_root: Path, root: str, timeframe: str) -> Path:
    """The first CME lane of this timeframe that actually holds bars."""
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


def _bars_frame(bars) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_event": bars.ts.astype("int64") + bars.interval_ns,
            "open": bars.open,
            "high": bars.high,
            "low": bars.low,
            "close": bars.close,
            "volume": bars.volume,
        }
    )


def run_cell(
    symbol: str,
    timeframe: str,
    preset: str,
    *,
    lake_root: Path,
    horizon_minutes: float,
    slippage_ticks: int,
    regime_name: str,
    regime,
    reference_symbol: str | None,
    lane: Path | None = None,
    reference_lane: Path | None = None,
    profile=None,
    engine_symbol: str | None = None,
    kind: str = "crypto",
) -> tuple[dict, pd.DataFrame]:
    """Run one cell and return ``(run_row, candidates)``.

    ``symbol`` is the **traded** instrument (``MNQ`` for a micro); the engine
    reads ``engine_symbol`` (``NQ``, the same underlying) so its market-parameter
    table still applies.
    """
    engine_symbol = engine_symbol or symbol
    path = lane or lane_path(symbol, timeframe, lake_root)
    bars = load_bars(path, symbol=engine_symbol, timeframe=timeframe)
    minutes = _MINUTES[timeframe]
    # A 60-hour horizon is ~20 bars at 4h and 2.5 bars at 1d; a 2R target
    # cannot resolve in two daily bars and the cell would report NaN.  The
    # horizon stays a *time* but never drops below 20 bars, so every cell has
    # a resolution window the strategy can actually use.
    effective_minutes = max(float(horizon_minutes), 20.0 * minutes)
    config = replace(
        PRESETS[preset],
        symbol=engine_symbol,
        timeframe=timeframe,
        horizon_bars=max(1, int(round(effective_minutes / minutes))),
    )
    reference = None
    if reference_lane is not None:
        reference = load_bars(reference_lane, symbol="ES" if "NQ" in str(reference_lane) else "NQ",
                              timeframe=timeframe)
    elif reference_symbol:
        try:
            reference = load_bars(
                lane_path(reference_symbol, timeframe, lake_root),
                symbol=reference_symbol,
                timeframe=timeframe,
            )
        except FileNotFoundError:
            reference = None

    started = time.time()
    log = run_state_machine(bars, config, regime=regime, reference=reference)
    profile = profile or profile_for(symbol)
    report = walk_forward(
        log.candidates,
        len(bars),
        [],
        profile=profile,
        slippage_ticks=slippage_ticks,
        horizon_bars=config.horizon_bars,
        bars=bars,
    )
    runtime = time.time() - started

    selected = simulate_portfolio(log.candidates, len(bars), config.horizon_bars)
    selected_ids = {id(c) for c in selected}

    # the feature frame, built exactly as the ML leaf builds it
    cand_df = pd.DataFrame(log.to_table())
    features = None
    try:
        # every declared feature, including the causal extras (ATR context,
        # gap/ATR, volume z-score): the archive is the training population
        if len(cand_df):
            features = build_features(cand_df, _bars_frame(bars), extra_features=True)
    except Exception:  # noqa: BLE001 - a cell without features is still archived
        features = None

    run_id = f"{symbol}:{timeframe}:{preset}"
    # keep the kind on the row so the log can filter crypto vs futures
    kind = kind
    row = run_record(
        run_id=run_id,
        symbol=symbol,
        timeframe=timeframe,
        preset=preset,
        data_path=str(path),
        n_bars=len(bars),
        first_ts=int(bars.ts[0]),
        last_ts=int(bars.ts[-1]),
        profile_name=profile.name,
        slippage_ticks=slippage_ticks,
        horizon_minutes=effective_minutes,
        regime=regime_name,
        report=report,
        runtime_s=runtime,
        gate="none (baseline)",
        models_root="",
        n_folds=0,
    )
    frame = candidate_frame(
        log,
        run_id=run_id,
        symbol=symbol,
        timeframe=timeframe,
        preset=preset,
        horizon_minutes=effective_minutes,
        bars=bars,
        selected_ids=selected_ids,
        features=features,
    )
    row["kind"] = kind
    frame["kind"] = kind
    return row, frame


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="matrix", description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=list(SYMBOLS))
    parser.add_argument("--timeframes", nargs="+", default=list(TIMEFRAMES))
    parser.add_argument("--presets", nargs="+", default=list(DEFAULT_PRESETS))
    parser.add_argument("--horizon-minutes", type=float, default=3600.0)
    parser.add_argument("--slippage-ticks", type=int, default=1)
    parser.add_argument("--regime", default="dvol", choices=("none", "dvol", "vxn"))
    parser.add_argument(
        "--lake-root",
        default=str(
            Path("~/iflow_lake/iflow/database/03_governed_lake/v2_parquet_lake").expanduser()
        ),
    )
    parser.add_argument("--out", default="artifacts/matrix")
    parser.add_argument("--futures", dest="futures", action="store_true", default=True,
                        help="also run the MNQ/MES cells (default on)")
    parser.add_argument("--no-futures", dest="futures", action="store_false")
    parser.add_argument("--only-futures", action="store_true")
    args = parser.parse_args(argv)

    lake_root = Path(args.lake_root).expanduser()
    regime = None
    if args.regime == "dvol":
        regime = DvolRegimeIndex.from_parquet(DEFAULT_DVOL_PATH)
    elif args.regime == "vxn":
        from dodgys_dd_quant.strategy.regime import DEFAULT_VXN_PATH, VxnRegimeIndex

        regime = VxnRegimeIndex.from_parquet(DEFAULT_VXN_PATH)

    futures_regime = None
    if args.futures:
        from dodgys_dd_quant.strategy.regime import DEFAULT_VXN_PATH, VxnRegimeIndex

        futures_regime = VxnRegimeIndex.from_parquet(DEFAULT_VXN_PATH)

    runs: list[dict] = []
    frames: list[pd.DataFrame] = []
    for symbol in (() if args.only_futures else args.symbols):
        reference_symbol = "ETHUSDT" if symbol == "BTCUSDT" else "BTCUSDT"
        for timeframe in args.timeframes:
            for preset in args.presets:
                try:
                    row, frame = run_cell(
                        symbol,
                        timeframe,
                        preset,
                        lake_root=lake_root,
                        horizon_minutes=args.horizon_minutes,
                        slippage_ticks=args.slippage_ticks,
                        regime_name=args.regime,
                        regime=regime,
                        reference_symbol=reference_symbol,
                    )
                except Exception as exc:  # noqa: BLE001 - the matrix reports, never hides
                    print(f"FAILED {symbol}/{timeframe}/{preset}: {type(exc).__name__}: {exc}")
                    continue
                runs.append(row)
                frames.append(frame)
                print(
                    f"{row['run_id']:<28} n={row['n_trades']:>6} "
                    f"E[R]={row['expectancy_r']:+.4f} E_net={row['expectancy_net_r']:+.4f} "
                    f"PF={row['profit_factor']:.3f} t={row['t_stat']:+.2f} "
                    f"kill={row['kill_level'] or '-'} "
                    f"({row['runtime_s']:.1f}s, {len(frame):,} candidates)"
                )

    if args.futures:
        for mini, root, profile_name in FUTURES:
            paired = "ES" if root == "NQ" else "NQ"
            for timeframe in args.timeframes:
                for preset in args.presets:
                    try:
                        lane = futures_lane(lake_root, root, timeframe)
                        ref_lane = futures_lane(lake_root, paired, timeframe)
                    except FileNotFoundError as exc:
                        print(f"SKIP {mini}/{timeframe}/{preset}: {exc}")
                        continue
                    try:
                        row, frame = run_cell(
                            mini,
                            timeframe,
                            preset,
                            lake_root=lake_root,
                            horizon_minutes=args.horizon_minutes,
                            slippage_ticks=args.slippage_ticks,
                            regime_name="vxn",
                            regime=futures_regime,
                            reference_symbol=None,
                            lane=lane,
                            reference_lane=ref_lane,
                            profile=profile_for(mini, profile_name),
                            engine_symbol=root,
                            kind="futures",
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(f"FAILED {mini}/{timeframe}/{preset}: {type(exc).__name__}: {exc}")
                        continue
                    runs.append(row)
                    frames.append(frame)
                    print(
                        f"{row['run_id']:<28} n={row['n_trades']:>6} "
                        f"E[R]={row['expectancy_r']:+.4f} E_net={row['expectancy_net_r']:+.4f} "
                        f"PF={row['profit_factor']:.3f} t={row['t_stat']:+.2f} "
                        f"({row['runtime_s']:.1f}s, {len(frame):,} candidates)"
                    )

    out = Path(args.out)
    runs_df = pd.DataFrame(runs).sort_values(["preset", "timeframe", "symbol"]).reset_index(drop=True)
    write_parquet(runs_df, out / "runs.parquet")
    if frames:
        candidates_df = pd.concat(frames, ignore_index=True)
    else:
        candidates_df = pd.DataFrame()
    write_parquet(candidates_df, out / "candidates.parquet")
    write_parquet(
        pd.DataFrame(columns=["run_id", "asof", "train_start", "test_start", "test_end", "mode"]),
        out / "folds.parquet",
    )
    manifest = {
        "command": " ".join(["python -m dodgys_dd_quant.backtest.matrix", *list(argv or [])]),
        "commit": _git_commit(),
        "lake_root": str(lake_root),
        "regime": args.regime,
        "horizon_minutes": args.horizon_minutes,
        "slippage_ticks": args.slippage_ticks,
        "symbols": args.symbols,
        "timeframes": args.timeframes,
        "presets": args.presets,
        "n_runs": len(runs_df),
        "n_candidates": int(len(candidates_df)),
        "note": (
            "rule-only baseline: no model, so p_win is NaN and gate_approved is False "
            "by construction. The NautilusTrader strategy class does not exist yet, so "
            "these candidates are the population such a strategy would consume."
        ),
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    notes = [
        f"{len(runs_df)} cell(s), {len(candidates_df):,} candidate(s), "
        f"regime={args.regime}, horizon={args.horizon_minutes:g} min, "
        f"{args.slippage_ticks} tick slippage, rule-only baseline",
        "E_net uses each symbol's own tick (BTC 0.1, ETH/SOL/BNB 0.01, XRP 0.0001) "
        "and Binance's 0.08 % round trip",
    ]
    (out / "SUMMARY.md").write_text(summary_markdown(runs_df, notes), encoding="utf-8")
    print(f"\nwrote {out}/runs.parquet, candidates.parquet, SUMMARY.md, manifest.json")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
