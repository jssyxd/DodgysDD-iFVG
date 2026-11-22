"""The backtest entry point.

    python -m dodgys_dd_quant.backtest.runner \
        --symbol BTCUSDT --timeframe 1m \
        --from 2023-01-01 --to 2026-11-21 \
        --cost-profile binance --slippage-ticks 1

It loads the governed parquet from the **NFS lake** (read-only), builds the
D2 candidate log, runs the walk-forward and prints the report.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

from dodgys_dd_quant.backtest.cost_model import COST_PROFILES, get_profile
from dodgys_dd_quant.backtest.walk_forward import (
    ModelScorer,
    load_walk_forward_index,
    walk_forward,
)
from dodgys_dd_quant.strategy.constants import (
    DECISION_THRESHOLD,
    INVERSION_WINDOW,
    DOC_INVERSION_WINDOW,
    market_params,
)
from dodgys_dd_quant.strategy.regime import (
    DEFAULT_DVOL_PATH,
    DEFAULT_VXN_PATH,
    DvolRegimeIndex,
    VxnRegimeIndex,
)
from dodgys_dd_quant.strategy.state_machine import (
    PRESETS,
    RuleConfig,
    run_deferred_portfolio,
    run_state_machine,
)
from dodgys_dd_quant.strategy.structure import load_bars

__all__ = ["main", "resolve_lake_path"]

#: Roots of the governed lake, most authoritative first (D5, D10).  The NFS
#: mount is authoritative; the local checkout is a working copy.
LAKE_ROOTS = tuple(
    Path(p).expanduser()
    for p in (
        "~/iflow_lake/iflow/database/03_governed_lake/v2_parquet_lake",
        "~/iflow_lake/iflow/database",
        "/home/da/桌面/database/03_governed_lake/v2_parquet_lake",
        "/home/da/桌面/database",
    )
)

#: Candidate directory layouts inside the lake, per asset family.
LAYOUTS = (
    "crypto/futures_um/{symbol}/{tf}",
    "crypto/futures_um/{symbol}",
    "us_futures/{symbol}/{tf}",
    "us_equities/{symbol}/{tf}",
    "global_futures/{symbol}/{tf}",
)


def resolve_lake_path(symbol: str, timeframe: str = "1m") -> Path:
    """Find the governed parquet for ``symbol``/``timeframe`` in the lake.

    The lake is **read** from here and never written to: it is shared by every
    leaf (D10).
    """
    tried: list[str] = []
    for root in LAKE_ROOTS:
        for layout in LAYOUTS:
            folder = root / layout.format(symbol=symbol, tf=timeframe)
            if not folder.is_dir():
                continue
            candidates = sorted(folder.glob("*.parquet"))
            exact = [p for p in candidates if f"{symbol}_{timeframe}_consolidated" in p.name]
            if exact:
                return exact[0]
            if candidates:
                return candidates[0]
        tried.append(str(root))
    raise FileNotFoundError(
        f"no governed parquet for {symbol}/{timeframe}; searched: {tried}"
    )


def _slice_bars(bars, start: str | None, end: str | None):
    if not start and not end:
        return bars
    ts = bars.ts
    lo = 0
    hi = ts.shape[0]
    if start:
        lo = int(np.searchsorted(ts, _date_ns(start), side="left"))
    if end:
        hi = int(np.searchsorted(ts, _date_ns(end), side="right"))
    return bars.slice(lo, hi)


def _date_ns(text: str) -> int:
    from dodgys_dd_quant.backtest.walk_forward import _date_to_ns

    return _date_to_ns(text)


def _fmt(value: float, digits: int = 4) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "n/a"
    return f"{value:.{digits}f}"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m dodgys_dd_quant.backtest.runner",
        description="DodgysDD iFVG end-to-end rolling backtest",
    )
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--timeframe", default="1m")
    p.add_argument("--from", dest="start", default=None, help="inclusive start date (YYYY-MM-DD)")
    p.add_argument("--to", dest="end", default=None, help="inclusive end date (YYYY-MM-DD)")
    p.add_argument("--data", default=None, help="explicit parquet path (overrides the lake)")
    p.add_argument("--cost-profile", default=None, choices=sorted(COST_PROFILES))
    p.add_argument("--slippage-ticks", type=int, default=1, choices=(0, 1, 2))
    p.add_argument("--preset", default="honest", choices=sorted(PRESETS), help="rule set")
    p.add_argument("--inversion-window", default="code", choices=("code", "doc"))
    p.add_argument("--models-root", default="artifacts/models")
    p.add_argument("--candidates-out", default=None, help="path of the D2 candidate log")
    p.add_argument("--reference-symbol", default=None, help="SMT reference instrument")
    p.add_argument("--regime", default="none", choices=("none", "vxn", "dvol"))
    p.add_argument("--threshold", type=float, default=DECISION_THRESHOLD)
    p.add_argument("--trials", type=int, default=32, help="independent trials for the DSR")
    p.add_argument("--limit", type=int, default=0, help="use only the first N bars (smoke test)")
    p.add_argument("--no-write-candidates", action="store_true")
    p.add_argument(
        "--portfolio",
        default="drop",
        choices=("drop", "defer"),
        help="accounting of a blocked signal: drop it (a real portfolio) or "
             "defer it (the experiment harness's queue)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # --- data -------------------------------------------------------------
    path = Path(args.data) if args.data else resolve_lake_path(args.symbol, args.timeframe)
    print(f"data: {path}")
    bars = load_bars(path, symbol=args.symbol, timeframe=args.timeframe)
    if args.start or args.end:
        bars = _slice_bars(bars, args.start, args.end)
    if args.limit:
        bars = bars.slice(0, min(args.limit, len(bars)))
    print(f"bars: {len(bars)}  {bars.ts[0]} -> {bars.ts[-1]}")

    # --- configuration ----------------------------------------------------
    config: RuleConfig = PRESETS[args.preset]
    config = replace(config, symbol=args.symbol, timeframe=args.timeframe)
    if args.inversion_window == "doc":
        config = config.with_doc_window()
    if config.min_gap_atr_mult is None:
        mp = market_params(args.symbol)
        if args.preset == "doc":
            config = replace(config, min_gap_atr_mult=mp.atr_coefficient)

    # --- regime -----------------------------------------------------------
    regime = None
    if args.regime == "vxn":
        regime = VxnRegimeIndex.from_parquet(DEFAULT_VXN_PATH)
    elif args.regime == "dvol":
        regime = DvolRegimeIndex.from_parquet(DEFAULT_DVOL_PATH)

    # --- reference instrument --------------------------------------------
    reference = None
    if args.reference_symbol:
        try:
            reference = load_bars(
                resolve_lake_path(args.reference_symbol, args.timeframe),
                symbol=args.reference_symbol,
                timeframe=args.timeframe,
            )
        except FileNotFoundError as exc:
            print(f"warning: no reference instrument ({exc})")

    # --- rule engine ------------------------------------------------------
    log = run_state_machine(bars, config, regime=regime, reference=reference)
    print(f"candidates: {len(log)}")

    out_path = args.candidates_out
    if out_path is None:
        out_path = Path("data/candidates") / f"{args.symbol}_{args.timeframe}.parquet"
    if not args.no_write_candidates:
        written = log.write_parquet(out_path)
        print(f"candidate log (D2): {written}")

    # --- costs ------------------------------------------------------------
    profile = get_profile(args.cost_profile or ("binance" if args.symbol.isupper() and "USDT" in args.symbol else "nq"))

    # --- walk forward -----------------------------------------------------
    folds = load_walk_forward_index(args.models_root, args.symbol, args.timeframe)
    scorer = None
    feature_fn = None
    if folds:
        scorer = ModelScorer(folds[-1], threshold=args.threshold)
        if not scorer.available:
            print(f"warning: model unavailable ({scorer.error}); running rule-only")
        # The model scores a *feature vector*, so the candidate must be joined to
        # the feature frame the ML leaf builds (ml_pipeline.features.build_features).
        # Without this the scorer would receive a Candidate instead of a dict.
        try:
            import pandas as pd

            from dodgys_dd_quant.ml_pipeline.features import build_features

            cand_df = pd.DataFrame([
                # `symbol` is a run-level fact, not a per-candidate field
                {name: getattr(c, name, args.symbol) for name in log.D2_COLUMNS}
                for c in log.candidates
            ])
            # The market series, in the shape ml_pipeline.features expects.
            # `Bars.ts` is the bar **open** time; the feature builder merges
            # backwards on "the last bar that closed at or before ts_event", so
            # the frame must carry the bar **close** time.
            if isinstance(bars, pd.DataFrame):
                bars_df = bars
            else:
                iv = bars.interval_ns          # a property, not a method
                bars_df = pd.DataFrame({
                    "ts_event": bars.ts.astype("int64") + iv,
                    "open": bars.open, "high": bars.high,
                    "low": bars.low, "close": bars.close,
                    "volume": bars.volume,
                })
            feat_df = build_features(cand_df, bars_df)
            feat_by_ts = {
                int(r["ts_event"]): {k: r[k] for k in feat_df.columns if k != "ts_event"}
                for r in feat_df.to_dict("records")
            }

            def _feature_fn(cand, _m=feat_by_ts):
                row = _m.get(int(cand.ts_event))
                if row is None:
                    raise KeyError(
                        f"no features for candidate ts_event={cand.ts_event}")
                return row

            feature_fn = _feature_fn
            print(f"feature frame: {len(feat_df)} rows, "
                  f"{len(feat_df.columns) - 1} features")
        except Exception as exc:
            print(f"warning: could not build the feature frame ({exc}); "
                  f"the model path will not be used")
            feature_fn = None
    else:
        print("no walk-forward index found -> rule-only baseline over the whole sample")

    portfolio_trades = None
    if args.portfolio == "defer":
        # the experiment harness's accounting: a blocked signal stays pending
        # and may still trigger later, at a different price
        portfolio_trades = run_deferred_portfolio(bars, config)

    report = walk_forward(
        log.candidates,
        len(bars),
        folds,
        profile=profile,
        slippage_ticks=args.slippage_ticks,
        threshold=args.threshold,
        scorer=scorer,
        feature_fn=feature_fn,
        trials=args.trials,
        portfolio_trades=portfolio_trades,
    )

    _print_report(report, profile, args)
    return 0


def _print_report(report, profile, args) -> None:
    print()
    print("=" * 100)
    print(f"WALK-FORWARD REPORT  {args.symbol} {args.timeframe}  preset={args.preset}  "
          f"window={INVERSION_WINDOW if args.inversion_window == 'code' else DOC_INVERSION_WINDOW}")
    print(f"cost profile: {profile.name}  slippage: {args.slippage_ticks} tick(s)")
    print("=" * 100)
    hdr = (f"{'fold':<12}{'mode':<11}{'cands':>7}{'appr':>7}{'trades':>8}"
           f"{'win%':>7}{'E[R]':>9}{'E_net':>9}{'PF':>7}{'t':>7}{'CI95':>20}")
    print(hdr)
    print("-" * len(hdr))
    for f in report.folds:
        s = f.stats
        ci = f"[{_fmt(s.ci95_lo, 3)},{_fmt(s.ci95_hi, 3)}]"
        pf = "inf" if math.isinf(s.profit_factor) else _fmt(s.profit_factor, 3)
        print(f"{f.label:<12}{f.mode:<11}{f.n_candidates:>7}{f.n_approved:>7}{f.n_trades:>8}"
              f"{s.win_rate * 100:>7.1f}{_fmt(s.expectancy_r):>9}{_fmt(s.expectancy_net_r):>9}"
              f"{pf:>7}{_fmt(s.t_stat, 2):>7}{ci:>20}")
    print("-" * len(hdr))
    accounting = report.folds[0].accounting if report.folds else "drop"
    for name, stats in ((f"PORTFOLIO (1 at a time, {accounting})", report.portfolio),
                        (f"BASELINE  (rule-only, {accounting})", report.baseline)):
        ci = f"[{_fmt(stats.ci95_lo, 3)},{_fmt(stats.ci95_hi, 3)}]"
        pf = "inf" if math.isinf(stats.profit_factor) else _fmt(stats.profit_factor, 3)
        print(f"{name:<32} n={stats.n_closed:<7} win%={stats.win_rate * 100:>5.1f}  "
              f"E[R]={_fmt(stats.expectancy_r):>8}  E_net={_fmt(stats.expectancy_net_r):>8}  "
              f"PF={pf:>6}  t={_fmt(stats.t_stat, 2):>6}  CI95={ci}")
        pf_net = "inf" if math.isinf(stats.profit_factor_net) else _fmt(stats.profit_factor_net, 3)
        print(f"{'':32} mean cost={_fmt(stats.mean_cost_r)} R   "
              f"break-even cost={_fmt(stats.break_even_cost_r)} R   "
              f"PF_net={pf_net}   total R={_fmt(stats.total_r, 2)}   "
              f"max consec losses={stats.max_consecutive_losses}")
    print()
    print(f"candidates={report.n_candidates}  approved={report.n_approved}  trades={report.n_trades}")
    print(f"Sharpe (per trade) = {_fmt(report.sharpe)}   "
          f"deflated Sharpe = {_fmt(report.deflated_sharpe)}   "
          f"DSR p-value = {_fmt(report.dsr_p_value)}   trials = {report.trials}")
    print()


if __name__ == "__main__":
    sys.exit(main())
