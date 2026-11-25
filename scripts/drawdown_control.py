#!/usr/bin/env python3
"""Drawdown-control experiment for the NQ killzone arm.

The meta-labeler has no predictive power (median out-of-sample AUC 0.497), so
the design's remaining use for a learned layer is **risk management**, not
expectation.  This script measures whether a sizing rule can cut the equity
drawdown **without** giving up expectancy.

The comparison is deliberately normalised.  Halving every position trivially
halves the drawdown *and* the profit, so each rule is also reported at
**constant mean exposure**::

    total_R_norm = sum(size_i * r_i) / mean(size)
    max_DD_norm  = max drawdown of the size-weighted curve / mean(size)

A rule is useful only if ``max_DD_norm`` falls while ``total_R_norm`` holds.

Rules tested (all causal — every input is known at the trade's entry):

* ``R0 baseline``      size = 1
* ``R1 vol target``    size = clip(median_atr / atr14, 0.25, 2.5)
* ``R2 regime``        size = 0.5 when the lagged VXN regime is "high"
* ``R3 dd brake``      size = 0.5 while the running drawdown exceeds 5 R
* ``R4 streak brake``  size = 0.5 for three trades after three consecutive losses
* ``R6 vol + regime``  the product of R1 and R2, clipped

Usage:
    .venv-ml/bin/python scripts/drawdown_control.py \
        --candidates logs/NQ_1m_pine_kz.parquet --bars logs/NQ_1m.parquet
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dodgys_dd_quant.backtest.walk_forward import simulate_portfolio  # noqa: E402
from dodgys_dd_quant.ml_pipeline.features import build_features  # noqa: E402
from dodgys_dd_quant.strategy.state_machine import PRESETS  # noqa: E402
from dodgys_dd_quant.strategy.state_machine import run_state_machine  # noqa: E402


def bars_frame(path: str) -> pd.DataFrame:
    """The lake parquet in the frame ``build_features`` expects (close times)."""
    b = pq.read_table(path).to_pandas()
    ts = b["timestamp"].to_numpy("int64")
    if np.abs(ts).max() < 10**13:            # ms -> ns
        ts = ts * 1_000_000
    return pd.DataFrame({
        "ts_event": ts + 60 * 10**9,        # the bar's close time
        "open": b["open"], "high": b["high"], "low": b["low"],
        "close": b["close"], "volume": b["volume"],
    })


def drawdown(curve: np.ndarray) -> tuple[float, int]:
    """The max drawdown of an equity curve and its length in trades."""
    peak = np.maximum.accumulate(curve)
    dd = peak - curve
    i = int(np.argmax(dd))
    if dd[i] <= 0:
        return 0.0, 0
    # the drawdown's start is the last peak before its trough
    start = int(np.flatnonzero(curve[: i + 1] == peak[i])[0])
    return float(dd[i]), i - start


def sortino(r: np.ndarray) -> float:
    """Mean / downside deviation (the design doc's reward family)."""
    down = r[r < 0]
    if len(down) == 0:
        return float("inf")
    dd = float(np.sqrt(np.mean(down ** 2)))
    return float(np.mean(r) / dd) if dd > 0 else float("inf")


def stats(sized: np.ndarray) -> dict:
    curve = np.cumsum(sized)
    mdd, mdd_len = drawdown(curve)
    return {
        "total_R": float(sized.sum()),
        "max_dd": mdd,
        "max_dd_len": mdd_len,
        "sortino": sortino(sized),
        "worst_trade": float(sized.min()),
    }


def simulate_management(
    traded, bars, *, trigger_r: float = 1.0, partial: float = 0.0,
    move_stop_to_be: bool = True, chunk: int = 256, cap: int = 20_000,
) -> np.ndarray:
    """Replay each trade with a break-even / partial-take management rule.

    The design doc's RL layer names three actions: a position multiplier, a
    **break-even trigger** and a **partial take-profit**.  This simulates the
    last two on the raw bars, which changes the *outcome distribution* rather
    than just its scale -- the only kind of lever that can cut drawdown without
    shrinking every position.

    * ``trigger_r``: the R multiple at which the management fires (1.0).
    * ``partial``: the fraction closed at the trigger (0 = pure break-even,
      0.5 = half off at +1R).
    * ``move_stop_to_be``: move the remainder's stop to the entry after the
      trigger (the doc's action), else keep the original stop.

    Returns one R multiple per trade; ``NaN`` for a trade still open at the end.
    """
    low = np.asarray(bars["low"], dtype="float64")
    high = np.asarray(bars["high"], dtype="float64")
    nb = len(low)
    out = np.full(len(traded), np.nan)

    def first_true(k, end, price, sd, above):
        while k < end:
            e = min(end, k + chunk)
            m = (high[k:e] >= price) if above else (low[k:e] <= price)
            if m.any():
                return k + int(m.argmax())
            k = e
        return -1

    for i, c in enumerate(traded):
        j = int(c.entry_bar)
        if j >= nb or not np.isfinite(c.r_multiple):
            continue
        end = min(nb, j + cap)
        sd = int(c.side)
        entry = float(c.entry_price)
        risk = float(c.risk)
        trig = entry + sd * trigger_r * risk
        stop = float(c.stop_price)
        target = float(c.target_price)
        # a long fires the trigger when high >= trig; the stop when low <= stop
        t_trig = first_true(j, end, trig, sd, above=(sd > 0))
        t_stop = first_true(j, end, stop, sd, above=(sd < 0))
        stop_first = t_stop >= 0 and (t_trig < 0 or t_stop <= t_trig)
        if stop_first:
            out[i] = -1.0
            continue
        if t_trig < 0:
            # the trigger never fires: the plain outcome stands
            out[i] = float(c.r_multiple)
            continue
        if partial > 0.0:
            booked = partial * trigger_r
            rest = 1.0 - partial
        else:
            booked, rest = 0.0, 1.0
        rest_stop = entry if move_stop_to_be else stop
        k = t_trig + 1
        if k >= end:
            out[i] = booked + rest * (trigger_r if move_stop_to_be else float("nan"))
            continue
        t_tgt = first_true(k, end, target, sd, above=(sd > 0))
        t_be = first_true(k, end, rest_stop, sd, above=(sd < 0))
        if t_tgt >= 0 and (t_be < 0 or t_tgt < t_be):
            out[i] = booked + rest * 2.0
        elif t_be >= 0:
            out[i] = booked + rest * (0.0 if move_stop_to_be else -1.0)
        else:
            out[i] = booked + rest * (0.0 if move_stop_to_be else 1.0)
    return out


def _verdict(cut: float, kept: float) -> str:
    """Classify a rule on (drawdown reduction, expectancy kept)."""
    if cut >= 0.05 and kept >= 0.95:
        return "**helps**"
    if cut >= 0.02 and kept >= 0.99:
        return "**marginal, both axes improve**"
    if cut >= 0.05:
        return "trade-off"
    return "no help"


def _table(rows: list[tuple[str, dict, float]]) -> list[str]:
    """rows: (name, stats, mean_size)"""
    L = ["| rule | mean size | trades | total R | total R (normalised) | max DD (R) | "
         "max DD (normalised) | DD length | Sortino | win% |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for name, st, ms in rows:
        L.append(f"| {name} | {ms:.3f} | {st['n']} | {st['total_R']:+.1f} | "
                 f"{st['total_R'] / ms:+.1f} | {st['max_dd']:.1f} | "
                 f"{st['max_dd'] / ms:.1f} | {st['max_dd_len']} | {st['sortino']:.3f} | "
                 f"{100 * st['win']:.1f} |")
    return L


def _stats(sized: np.ndarray) -> dict:
    v = sized[np.isfinite(sized)]
    curve = np.cumsum(v)
    mdd, mdd_len = drawdown(curve)
    return {"n": int(len(v)), "total_R": float(v.sum()), "max_dd": mdd,
            "max_dd_len": mdd_len, "sortino": sortino(v),
            "win": float(np.mean(v > 0)) if len(v) else float("nan")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default="logs/NQ_1m_pine_kz.parquet")
    ap.add_argument("--bars", default="logs/NQ_1m.parquet")
    ap.add_argument("--out", default="research/experiments/DRAWDOWN_CONTROL.md")
    ap.add_argument("--dd-threshold", type=float, default=5.0)
    ap.add_argument("--streak", type=int, default=3)
    ap.add_argument("--lo", type=float, default=0.25)
    ap.add_argument("--hi", type=float, default=2.5)
    args = ap.parse_args(argv)

    from dodgys_dd_quant.backtest.runner import load_bars
    raw = load_bars(args.bars, symbol="NQ", timeframe="1m")
    cfg = replace(PRESETS["pine"], symbol="NQ", timeframe="1m",
                  killzone_gate=True).with_doc_window()
    log = run_state_machine(raw, cfg, regime=_regime(args.bars))
    traded = simulate_portfolio(log.candidates, len(raw))
    print(f"candidates {len(log.candidates):,} -> portfolio trades {len(traded):,}")

    feat = build_features(pd.DataFrame(log.to_table()), bars_frame(args.bars),
                          extra_features=True)
    f_by_ts = {int(r["ts_event"]): r for r in feat.to_dict("records")}

    ts = np.array([c.ts_event for c in traded], dtype="int64")
    r = np.array([c.r_multiple for c in traded], dtype="float64")
    atr = np.array([f_by_ts.get(int(t), {}).get("atr14", np.nan) for t in ts], dtype="float64")
    regime = np.array([f_by_ts.get(int(t), {}).get("vxn_regime", -1) for t in ts], dtype=np.int64)
    risk = np.array([c.risk for c in traded], dtype="float64")
    ok = np.isfinite(r) & np.isfinite(atr) & (atr > 0)
    traded_ok = [c for c, k in zip(traded, ok) if k]
    r, atr, regime, risk = r[ok], atr[ok], regime[ok], risk[ok]
    print(f"usable trades {len(r):,}")

    med_atr = float(np.nanmedian(atr))
    vol = np.clip(med_atr / atr, args.lo, args.hi)

    def dd_brake() -> np.ndarray:
        size = np.ones(len(r)); eq = peak = 0.0
        for i in range(len(r)):
            size[i] = 0.5 if (peak - eq) > args.dd_threshold else 1.0
            eq += size[i] * r[i]; peak = max(peak, eq)
        return size

    def streak_brake() -> np.ndarray:
        size = np.ones(len(r)); losses = 0; cooldown = 0
        for i in range(len(r)):
            size[i] = 0.5 if cooldown > 0 else 1.0
            if cooldown > 0: cooldown -= 1
            if r[i] < 0:
                losses += 1
                if losses >= args.streak: cooldown, losses = 3, 0
            else:
                losses = 0
        return size

    sizing = {
        "R0 baseline": np.ones(len(r)),
        "R1 vol target": vol,
        "R2 regime": np.where(regime == 2, 0.5, 1.0),
        "R3 dd brake": dd_brake(),
        "R4 streak brake": streak_brake(),
        "R6 vol + regime": np.clip(vol * np.where(regime == 2, 0.5, 1.0), args.lo, args.hi),
        # the audit's P2 concern: a few very wide stops may dominate the result
        "R5 wide-stop cap (risk > p95)": np.where(risk > np.nanpercentile(risk, 95), 0.5, 1.0),
    }
    hl = {"low": raw.low, "high": raw.high}
    management = {
        "R7 break-even at +1R": simulate_management(traded_ok, hl, trigger_r=1.0,
                                                    partial=0.0, move_stop_to_be=True),
        "R8 50% at +1R, rest to 2R/BE": simulate_management(
            traded_ok, hl, trigger_r=1.0, partial=0.5, move_stop_to_be=True),
        "R9 50% at +1R, stop stays": simulate_management(
            traded_ok, hl, trigger_r=1.0, partial=0.5, move_stop_to_be=False),
    }

    base_s = _stats(r)
    size_rows = [(n, _stats(sz * r), float(np.mean(sz))) for n, sz in sizing.items()]
    mg_rows = [(n, _stats(v), 1.0) for n, v in management.items()]

    L = ["# Drawdown control — the NQ killzone arm\n",
         f"Portfolio: **one position at a time, drop** (the engine's own "
         f"`simulate_portfolio`), **{len(r):,}** trades. Raw expectancy "
         f"**{np.mean(r):+.4f} R**, win rate **{100 * np.mean(r > 0):.2f} %**.\n",
         "Every rule is causal: its inputs (`atr14`, the lagged VXN regime, the running "
         "equity, the loss streak, the price path) are known at the trade's entry.\n",
         "`normalised` divides by the rule's **mean size**, so a rule is not credited "
         "for simply trading smaller.\n",
         "## A. Position sizing (scales each trade)\n"]
    L += _table(size_rows)
    L += ["", f"**Baseline:** total {base_s['total_R']:+.1f} R, max drawdown "
              f"**{base_s['max_dd']:.1f} R**, Sortino {base_s['sortino']:.3f}.", ""]
    L += ["| rule | max DD (normalised) change | total R (normalised) kept | verdict |",
          "|---|---|---|---|"]
    for name, st, ms in size_rows:
        if name == "R0 baseline": continue
        dd_norm = st["max_dd"] / ms
        tot_norm = st["total_R"] / ms
        cut = 1 - dd_norm / base_s["max_dd"] if base_s["max_dd"] else float("nan")
        kept = tot_norm / base_s["total_R"] if base_s["total_R"] else float("nan")
        L.append(f"| {name} | {100 * cut:+.1f} % (positive = smaller DD) | "
                 f"{100 * kept:.1f} % | {_verdict(cut, kept)} |")

    L += ["", "## B. Outcome management (changes the R distribution)\n",
          "The design doc's RL action space names a **break-even trigger** and a "
          "**partial take-profit**. These cannot be tested by reweighting — the trade's "
          "terminal R changes — so they are replayed on the raw bars.\n"]
    L += _table(mg_rows)
    L += ["", "| rule | max DD change vs baseline | total R kept | E[R] | verdict |",
          "|---|---|---|---|---|"]
    for name, st, _ms in mg_rows:
        cut = 1 - st["max_dd"] / base_s["max_dd"] if base_s["max_dd"] else float("nan")
        kept = st["total_R"] / base_s["total_R"] if base_s["total_R"] else float("nan")
        er = st["total_R"] / st["n"] if st["n"] else float("nan")
        L.append(f"| {name} | {100 * cut:+.1f} % | {100 * kept:.1f} % | {er:+.4f} | "
                 f"{_verdict(cut, kept)} |")

    L += ["", "## C. What this measures, and what it does not\n",
          "* A sizing rule only helps if `max DD (normalised)` falls while "
          "`total R (normalised)` holds; cutting both is just smaller trading.\n",
          "* An outcome rule is judged on the same two numbers, but it is allowed to "
          "move `E[R]` — break-even trades a lower expectancy for a shorter tail.\n",
          "* One instrument, one contract, no per-trade dollar cap. The per-trade risk "
          "cap is the same arithmetic in dollar space.\n",
          "* The meta-labeler's `P(Win)` is **not** a sizing input: its median "
          "out-of-sample AUC is 0.497, so a probability-weighted size would be sizing "
          "on noise.\n"]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"[SAVED] {out}")
    print("\n".join(L[6:]))
    return 0


def _regime(bars_path: str):
    from dodgys_dd_quant.strategy.regime import VxnRegimeIndex
    return VxnRegimeIndex.from_parquet()


if __name__ == "__main__":
    raise SystemExit(main())
