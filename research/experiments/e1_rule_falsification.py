"""E-1 — rule-engine falsification test (DodgysDD iFVG, code-derived core).

Purpose
-------
Settle ONE question cheaply, before any ML, any vision model or any NQ data:
*does the iFVG rule engine, implemented faithfully from the reference Pine source and
 with no look-ahead, produce a positive-expectancy signal at all?*

This is a **rule-engine test, not an edge test**. It runs on the only real OHLCV series
that physically exists in this repo:
    research/kaggle/gold-xauusd-smc-trading-data/XAUUSD_15M_SMC_Data.csv
(4,502 XAU/USD 15-minute bars, 2026-07-14 -> 2026-09-22.)

It deliberately does NOT use the CSV's own Bullish_FVG / Bearish_FVG columns: those labels
are forward-filled booleans that are NOT reproducible from the CSV's own OHLC
(see research/audit/AUDIT.md section A.5.3 — only 14% / 9% same-direction overlap).
Using them would be circular.

Rule provenance (every predicate is cited to the reference source)
------------------------------------------------------------------
Source of truth: research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine

  FVG geometry        pine:354-355   bullish: low[c] > high[a];  bearish: high[c] < low[a]
                                   (a = oldest of 3 candles, b = displacement, c = newest)
  candidate expiry     pine:499      drop when bar_index - fvgBar1 > graceCandles
  inversion trigger    pine:437      bullish FVG -> close[X-1] < fvgBottom (= high[a]) -> SHORT
                                      bearish FVG -> close[X-1] > fvgTop    (= low[c])  -> LONG
  stop placement       pine:462,466  extreme of the window (min low for long / max high for short)
  RR targets           pine:317,321  entry +/- riskRange * r,  rrInput default "1,2"

Bar indexing convention
-----------------------
All bars are CLOSED. Index i means "bar i has closed". The reference Pine evaluates the
trigger on bar X using close[X-1]; equivalently, in closed-bar terms, a candidate whose
newest candle is c may be confirmed by the close of any bar k > c, and the fill happens at
the open of bar k+1. There is never a same-bar close->open fill.

Arms (pre-registered, cheap, A/B)
---------------------------------
  (a) inversion window : CODE  [0, grace]  vs  DOC  [7, 15]
  (b) ATR floor        : CODE  none        vs  DOC  gap > 0.25 * ATR(14)
  (c) entry fill       : HONEST open(k+1)  vs  CODE  close(k)   (the code's drawing price)
  (d) sweep gate       : OFF (code default) vs ON (doc: sweep is a precondition)

The two A/A+ phase-1 filters the design doc asks for are NOT applied: no artifact in this
repo defines what A+ or A means (research/audit/AUDIT.md section C.1), so filtering on an
invented rubric would make the result a property of the rubric rather than of the rule.

Intrabar convention
-------------------
If a bar touches both the stop and the 2R target, the **stop wins** (conservative). Bars
whose high/low are unusable (first bar of the series) are skipped.

Usage
-----
    PY=/home/da/.local/share/uv/python/cpython-3.11.17-linux-x86_64-gnu/bin/python3.11
    $PY research/experiments/e1_rule_falsification.py
"""

from __future__ import annotations

import copy
import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "kaggle/gold-xauusd-smc-trading-data/XAUUSD_15M_SMC_Data.csv"

# --- arm grid -------------------------------------------------------------------
WINDOWS = {"code[0,15]": (0, 15), "doc[7,15]": (7, 15)}
ATR_FLOORS = {"code:none": 0.0, "doc:0.25xATR": 0.25}
FILLS = {"honest:open(k+1)": "next_open", "code:close(k)": "confirm_close"}
SWEEP_GATES = {"code:off": False, "doc:on": True}
# concurrency: 0 = one position per candidate (signal census, correlated trades,
# t-statistic inflated); 1 = one position at a time (a real portfolio).
CONCURRENCY = {"concurrent": 0, "one-at-a-time": 1}

RR = 2.0  # fixed 1:2 risk-reward, per the phase-1 acceptance criteria


@dataclass
class Bar:
    dt: str
    o: float
    h: float
    l: float
    c: float
    v: float


@dataclass
class Candidate:
    """An iFVG candidate, carried until it triggers or expires."""
    kind: str            # "bullish_fvg" (support) or "bearish_fvg" (resistance)
    a: int              # index of the OLDEST candle of the 3
    c: int              # index of the NEWEST candle of the 3
    gap_top: float
    gap_bottom: float
    trade_dir: int      # +1 long, -1 short
    swept: bool = False
    confirmed: int | None = None   # index of the confirmation bar k
    entry: float = 0.0
    stop: float = 0.0
    target: float = 0.0
    risk: float = 0.0
    outcome: str = ""
    r: float = 0.0
    bars_held: int = 0
    meta: dict = field(default_factory=dict)


def load_bars(path: Path) -> list[Bar]:
    """Load bars from either the Kaggle CSV or a governed lake Parquet.

    The governed lake format (03_governed_lake/v2_parquet_lake) stores
    `timestamp` (int64 ms, left-open), `datetime`, open/high/low/close/volume.
    """
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq
        rows = pq.read_table(path).to_pylist()
        return [Bar(dt=r["datetime"], o=float(r["open"]), h=float(r["high"]),
                    l=float(r["low"]), c=float(r["close"]), v=float(r["volume"]))
                for r in rows]
    bars: list[Bar] = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            bars.append(Bar(
                dt=row["Datetime"],
                o=float(row["Open"]), h=float(row["High"]),
                l=float(row["Low"]), c=float(row["Close"]),
                v=float(row["Volume"]),
            ))
    return bars


def atr_wilder(bars: list[Bar], period: int = 14) -> list[float | None]:
    """Wilder RMA of True Range. None until the series is warm."""
    out: list[float | None] = [None] * len(bars)
    if len(bars) <= period:
        return out
    tr = [0.0] * len(bars)
    tr[0] = bars[0].h - bars[0].l
    for i in range(1, len(bars)):
        tr[i] = max(bars[i].h - bars[i].l,
                    abs(bars[i].h - bars[i - 1].c),
                    abs(bars[i].l - bars[i - 1].c))
    out[period] = sum(tr[1:period + 1]) / period
    for i in range(period + 1, len(bars)):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period  # type: ignore[operator]
    return out


def causal_swings(bars: list[Bar], left: int = 2, right: int = 2) -> tuple[list[float | None], list[float | None]]:
    """Causal fractal swings: a pivot at bar p is only known at bar p+right."""
    n = len(bars)
    highs: list[float | None] = [None] * n
    lows: list[float | None] = [None] * n
    for p in range(left, n - right):
        window = range(p - left, p + right + 1)
        if bars[p].h == max(bars[i].h for i in window):
            highs[p + right] = bars[p].h
        if bars[p].l == min(bars[i].l for i in window):
            lows[p + right] = bars[p].l
    return highs, lows


def sweep_flags(bars: list[Bar]) -> list[bool]:
    """True when bar i wicked through the last known swing level and closed back inside."""
    highs, lows = causal_swings(bars)
    last_h: float | None = None
    last_l: float | None = None
    flags = [False] * len(bars)
    for i, b in enumerate(bars):
        if highs[i] is not None:
            last_h = highs[i]  # type: ignore[assignment]
        if lows[i] is not None:
            last_l = lows[i]  # type: ignore[assignment]
        if last_h is not None and b.h > last_h and b.c < last_h:
            flags[i] = True
        if last_l is not None and b.l < last_l and b.c > last_l:
            flags[i] = True
    return flags


def find_candidates(bars: list[Bar], atr: list[float | None], atr_mult: float) -> list[Candidate]:
    """All 3-candle FVGs that satisfy the ATR floor, formed on closed bars."""
    out: list[Candidate] = []
    for c in range(2, len(bars)):
        a = c - 2
        bull = bars[c].l > bars[a].h
        bear = bars[c].h < bars[a].l
        if not (bull or bear):
            continue
        gap_top, gap_bottom = (bars[c].l, bars[a].h) if bull else (bars[a].l, bars[c].h)
        if atr_mult > 0.0:
            ref = atr[c]
            if ref is None or ref <= 0:
                continue
            if abs(gap_top - gap_bottom) <= atr_mult * ref:
                continue
        kind = "bullish_fvg" if bull else "bearish_fvg"
        out.append(Candidate(kind=kind, a=a, c=c, gap_top=gap_top, gap_bottom=gap_bottom,
                              trade_dir=-1 if bull else +1))
    return out


def run_arm(bars: list[Bar], candidates: list[Candidate], swept: list[bool],
            window: tuple[int, int], fill: str, require_sweep: bool,
            max_concurrent: int = 0) -> list[Candidate]:
    """Walk the series once, confirming and resolving candidates. No look-ahead.

    `max_concurrent`:
      0 -> unlimited concurrent positions (one per candidate). This is a *signal
           census*, useful for measuring how often the pattern fires, but the
           trades are heavily correlated, so its t-statistic is inflated and its
           expectancy is not a portfolio result.
      1 -> at most ONE position open at a time (what a real backtest does).
           Trades are then non-overlapping and the iid t-statistic is meaningful.
    """
    min_age, max_age = window
    n = len(bars)
    pending: list[Candidate] = []
    done: list[Candidate] = []
    open_positions = 0
    by_c: dict[int, list[Candidate]] = {}
    for cand in candidates:
        by_c.setdefault(cand.c, []).append(cand)

    for k in range(n):
        # --- a candidate whose newest candle is k-1 becomes testable on bar k ---
        for cand in by_c.get(k - 1, []):
            cand.meta["testable_from"] = k
            pending.append(cand)

        # --- test EVERY unconfirmed candidate on every bar, using the previous CLOSE ---
        # Pine evaluates the trigger on bar X with close[X-1]; here bar k plays X, so the
        # confirmation candle is k-1 and its age relative to the FVG's newest candle is (k-1) - c.
        for cand in list(pending):
            if cand.confirmed is not None:
                continue
            if cand.kind == "bullish_fvg":
                trig = bars[k - 1].c < cand.gap_bottom
            else:
                trig = bars[k - 1].c > cand.gap_top
            if not trig:
                continue
            age = (k - 1) - cand.c
            if age < min_age or age > max_age:
                continue
            if require_sweep and not swept[k - 1]:
                continue
            if max_concurrent and open_positions >= max_concurrent:
                continue   # a position is already open -> skip this signal

            # entry / stop / target
            if fill == "next_open":
                if k >= n:
                    continue
                entry = bars[k].o
            else:
                entry = bars[k - 1].c
            # stop = extreme of the window [c .. k]  (pine:462/466 scans fvgBar1..bar_index
            # inclusive, default slPlacement "Wick"). pine:293-296 ict_ScanExtreme:
            #   long  -> the MINIMUM low of the window  (stop below)
            #   short -> the MAXIMUM high of the window (stop above)
            seg = bars[cand.c:k + 1]
            if not seg:
                continue
            if cand.trade_dir > 0:
                stop = min(b.l for b in seg)
                risk = entry - stop
                target = entry + RR * risk
            else:
                stop = max(b.h for b in seg)
                risk = stop - entry
                target = entry - RR * risk
            if risk <= 0:
                continue
            cand.confirmed = k
            cand.entry = entry
            cand.stop = stop
            cand.target = target
            cand.risk = risk
            cand.meta["entry_idx"] = k
            cand.meta["age"] = age
            open_positions += 1

        # --- expire candidates that can no longer trigger ---
        still: list[Candidate] = []
        for cand in pending:
            if cand.confirmed is None:
                # age measured from the FVG's newest candle; Pine drops when bar - fvgBar1 > grace
                if (k - 1) - cand.c > max_age:
                    done.append(cand)  # expired without triggering
                else:
                    still.append(cand)
            else:
                # --- resolve open trades on this bar ---
                b = bars[k]
                hit_sl = b.l <= cand.stop if cand.trade_dir > 0 else b.h >= cand.stop
                hit_tp = b.h >= cand.target if cand.trade_dir > 0 else b.l <= cand.target
                if hit_sl:
                    cand.outcome = "stop"
                    cand.r = -1.0
                    done.append(cand)
                    open_positions -= 1
                elif hit_tp:
                    cand.outcome = "target"
                    cand.r = RR
                    done.append(cand)
                    open_positions -= 1
                else:
                    # still open -> keep it open; only the end of the series closes it out
                    cand.bars_held = k - int(cand.meta.get("entry_idx", k))
                    still.append(cand)
        pending = still
    for cand in pending:
        cand.outcome = "expired"
    done.extend(pending)
    return done


def summarise(trades: list[Candidate]) -> dict:
    closed = [t for t in trades if t.outcome in ("stop", "target")]
    n = len(closed)
    base = {
        "n": 0, "win_rate": 0.0, "expectancy_r": 0.0, "pf": 0.0,
        "be_cost_r": float("nan"), "max_consec_losses": 0,
        "expired": sum(1 for t in trades if t.outcome == "expired"),
        "unresolved": sum(1 for t in trades if t.outcome == "open"),
        "t_stat": float("nan"), "ci95_lo": float("nan"), "ci95_hi": float("nan"),
    }
    if n == 0:
        return base
    wins = sum(1 for t in closed if t.outcome == "target")
    losses = n - wins
    gross_win = sum(t.r for t in closed if t.r > 0)
    gross_loss = -sum(t.r for t in closed if t.r < 0)
    exp = sum(t.r for t in closed) / n
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    # break-even round-trip cost per trade, in R: cost c such that expectancy = 0
    # expectancy = (wins*RR - losses*1 - n*c)/n  ->  c = (wins*RR - losses)/n
    be_cost = (wins * RR - losses) / n
    streak = worst = 0
    for t in closed:
        if t.outcome == "stop":
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
    # iid t-statistic on the R series (r is either -1 or +2)
    var = sum((t.r - exp) ** 2 for t in closed) / (n - 1) if n > 1 else 0.0
    sd = math.sqrt(var)
    t_stat = (exp / sd) * math.sqrt(n) if sd > 0 else float("nan")
    ci = 1.96 * sd / math.sqrt(n) if n > 0 else float("nan")
    base.update({
        "n": n, "win_rate": wins / n, "expectancy_r": exp, "pf": pf,
        "be_cost_r": be_cost, "max_consec_losses": worst,
        "t_stat": t_stat, "ci95_lo": exp - ci, "ci95_hi": exp + ci,
    })
    return base


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA),
                    help="CSV or governed-lake Parquet")
    ap.add_argument("--cost-r", type=float, default=0.0,
                    help="round-trip cost per trade expressed in R (0 = cost-free)")
    args = ap.parse_args()

    bars = load_bars(Path(args.data))
    atr = atr_wilder(bars, 14)
    swept = sweep_flags(bars)
    print(f"loaded {len(bars)} bars  {bars[0].dt} -> {bars[-1].dt}")
    print(f"cost model: {args.cost_r:.4f} R per round trip")

    rows = []
    for wname, window in WINDOWS.items():
        for aname, amult in ATR_FLOORS.items():
            base = find_candidates(bars, atr, amult)
            for fname, fill in FILLS.items():
                for sname, req in SWEEP_GATES.items():
                    # fresh copies: run_arm mutates the Candidate objects it is given
                    for cname, conc in CONCURRENCY.items():
                        cands = [copy.deepcopy(c) for c in base]
                        trades = run_arm(bars, cands, swept, window, fill, req,
                                        max_concurrent=conc)
                        s = summarise(trades)
                        s["expectancy_net_r"] = s["expectancy_r"] - args.cost_r
                        s.update(window=wname, atr=aname, fill=fname, sweep=sname,
                                 conc=cname)
                        rows.append(s)

    hdr = (f"{'window':<12}{'atr floor':<14}{'fill':<20}{'sweep':<11}{'conc':>13}"
           f"{'n':>6}{'win%':>7}{'E[R]':>8}{'E_net':>8}{'PF':>7}{'BEcost[R]':>11}"
           f"{'t':>7}{'CI95':>18}{'maxL':>6}")
    print()
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        pf = "inf" if math.isinf(r["pf"]) else f"{r['pf']:.3f}"
        ci = f"[{r['ci95_lo']:+.3f},{r['ci95_hi']:+.3f}]"
        print(f"{r['window']:<12}{r['atr']:<14}{r['fill']:<20}{r['sweep']:<11}"
              f"{r['conc']:>13}{r['n']:>6}{r['win_rate'] * 100:>7.1f}{r['expectancy_r']:>8.3f}"
              f"{r['expectancy_net_r']:>8.3f}{pf:>7}"
              f"{r['be_cost_r']:>11.3f}{r['t_stat']:>7.2f}{ci:>18}"
              f"{r['max_consec_losses']:>6}")

    best = max(rows, key=lambda r: r["expectancy_r"])
    worst = min(rows, key=lambda r: r["expectancy_r"])
    print()
    print(f"best arm  : {best['window']} {best['atr']} {best['fill']} {best['sweep']} "
          f"E[R]={best['expectancy_r']:.3f} PF={best['pf']:.3f}")
    print(f"worst arm : {worst['window']} {worst['atr']} {worst['fill']} {worst['sweep']} "
          f"E[R]={worst['expectancy_r']:.3f}")
    n_pos = sum(1 for r in rows if r["expectancy_r"] > 0)
    print(f"arms with E[R] > 0 : {n_pos}/{len(rows)}")
    signs = {}
    for r in rows:
        signs.setdefault((r["window"], r["atr"]), []).append(r["expectancy_r"])
    print("sign stability across the fill arm:")
    for k, v in sorted(signs.items()):
        print(f"   {k[0]:<12}{k[1]:<14} " + "  ".join(f"{x:+.3f}" for x in v)
              + ("   STABLE" if (max(v) > 0) == (min(v) > 0) else "   FLIPS"))


if __name__ == "__main__":
    main()
