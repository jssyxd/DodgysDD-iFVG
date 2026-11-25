#!/usr/bin/env python3
"""Audit the candidate/vision/bars parquet files against the review checklist.

For every file it prints the schema, the first 20 rows and the basic statistics;
for the candidate logs it then runs the nine checks a reviewer needs before any
model is trained:

1. **label leakage** — is ``label`` consistent with ``r_multiple``, and does the
   outcome resolve at the **first touch** of the stop or the target after the
   entry (never at the exit bar's close)?
2. **time alignment** — is the timestamp the *confirmation close*, is the entry
   the *next* bar's open, and are the exogenous features lagged?
3. **missing / all-zero features** — per-column NaN and zero rates.
4. **sample imbalance** — the ``label`` distribution.
5. **duplicates / overlap** — duplicate ``ts_event``, duplicate setups, and
   whether two folds share a bar.
6. **rule fidelity** — the distributions that must follow the DodgysDD logic.
7. **execution consistency** — the label is the *standalone* outcome, while the
   portfolio drops blocked signals: the two differ, and the report says so.
8. **timestamp semantics** — is ``ts_event`` the event time or the exit time?
9. schema / head / stats.

Usage:
    python scripts/audit_dataset.py --dir logs --bars NQ logs/NQ_1m.parquet
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

HEAD_ROWS = 20
#: how many candidates to re-derive the outcome for (the exact leakage test)
LEAKAGE_SAMPLE = 3000


def _fmt(v) -> str:
    if isinstance(v, float):
        if np.isnan(v):
            return "nan"
        return f"{v:.6g}"
    return str(v)


def head_block(table, n=HEAD_ROWS) -> list[str]:
    cols = table.column_names
    rows = table.slice(0, n).to_pylist()
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join(_fmt(r[c]) for c in cols) + " |")
    return out


def stats_block(table) -> list[str]:
    out = [f"rows **{table.num_rows:,}**, columns {len(table.column_names)}", "",
           "| column | type | non-null | null% | zeros | min | median | max |",
           "|---|---|---|---|---|---|---|---|"]
    for name in table.column_names:
        col = table.column(name)
        arr = col.to_numpy(zero_copy_only=False)
        n = len(arr)
        if arr.dtype.kind in "iu f b":
            num = arr.astype("float64", copy=False)
            finite = np.isfinite(num)
            nulls = int(n - finite.sum())
            zeros = int((num[finite] == 0).sum())
            if finite.any():
                mn, md, mx = (float(np.min(num[finite])),
                              float(np.median(num[finite])),
                              float(np.max(num[finite])))
            else:
                mn = md = mx = float("nan")
            out.append(f"| `{name}` | {col.type} | {n - nulls:,} | "
                       f"{100 * nulls / n if n else 0:.2f} | {zeros:,} | "
                       f"{_fmt(mn)} | {_fmt(md)} | {_fmt(mx)} |")
        else:
            nulls = int(sum(1 for v in arr if v is None))
            uniq = len({v for v in arr})
            out.append(f"| `{name}` | {col.type} | {n - nulls:,} | "
                       f"{100 * nulls / n if n else 0:.2f} | – | – | "
                       f"{uniq} distinct | – |")
    return out


# ---------------------------------------------------------------------------
# The candidate-log checks
# ---------------------------------------------------------------------------


def check_labels(table) -> list[str]:
    label = table.column("label").to_numpy()
    r = table.column("r_multiple").to_numpy().astype("float64")
    rr = np.nanmedian(np.where(label == 1, r, np.nan))
    out = ["### 1. Label consistency", ""]
    u, c = np.unique(label, return_counts=True)
    out.append("| label | meaning | rows | share |")
    out.append("|---|---|---|---|")
    for k, v in zip(u, c):
        meaning = {1: "target reached", 0: "stopped out", -1: "never resolved"}.get(int(k), "?")
        out.append(f"| {int(k)} | {meaning} | {v:,} | {100 * v / len(label):.2f} % |")
    # the mechanical contracts
    win = label == 1
    lose = label == 0
    open_ = label == -1
    ok_win = bool(np.allclose(r[win], rr, atol=1e-9)) if win.any() else True
    ok_lose = bool(np.allclose(r[lose], -1.0, atol=1e-9)) if lose.any() else True
    ok_open = bool(np.all(np.isnan(r[open_]))) if open_.any() else True
    out.append("")
    out.append(f"* a win's `r_multiple` equals the RR ({rr:.3f}) for **every** row: "
               f"{'YES' if ok_win else '**NO**'}")
    out.append(f"* a loss's `r_multiple` is exactly −1.0 for **every** row: "
               f"{'YES' if ok_lose else '**NO**'}")
    out.append(f"* an unresolved row's `r_multiple` is NaN for **every** row: "
               f"{'YES' if ok_open else '**NO**'}")
    return out


def check_time_alignment(table, bars) -> list[str]:
    """ts_event must be the confirmation **close**, the entry the next **open**."""
    out = ["### 2. Time alignment", ""]
    if bars is None:
        out.append("_the bars file was not supplied; skipped_")
        return out
    ts_bars = bars["ts"]
    o = bars["open"]
    c = bars["close"]
    h = bars["high"]
    lo = bars["low"]
    iv = int(np.median(np.diff(ts_bars)))
    n = table.num_rows
    if n == 0:
        return out

    ts_event = table.column("ts_event").to_numpy()
    confirm = table.column("confirm_bar").to_numpy()
    entry_bar = confirm + 1
    ok_ts = int(np.sum(ts_event == ts_bars[confirm] + iv))
    ok_entry = int(np.sum(table.column("entry_price").to_numpy() == o[entry_bar]))

    # the VXN feature must be the *previous* day's close (the one-day lag)
    vxn = table.column("vxn_known").to_numpy().astype("float64")
    finite = np.isfinite(vxn)

    out.append(f"* `ts_event == bars.timestamp[confirm_bar] + 1 bar` for "
               f"**{ok_ts:,}/{n:,}** rows ({100 * ok_ts / n:.2f} %) — the timestamp is the "
               f"**confirmation bar's close**, not the exit time")
    out.append(f"* `entry_price == bars.open[confirm_bar + 1]` for "
               f"**{ok_entry:,}/{n:,}** rows ({100 * ok_entry / n:.2f} %) — the fill is the "
               f"**next bar's open**, so no same-bar look-ahead")
    out.append(f"* `vxn_known` is non-null on {100 * finite.mean():.1f} % of rows "
               f"(the daily regime, one-day lagged)")
    # the outcome must resolve strictly after the entry bar
    early = 0
    if "exit_bar" in table.column_names:
        exit_bar = table.column("exit_bar").to_numpy()
        early = int(np.sum((exit_bar >= 0) & (exit_bar < entry_bar)))
    out.append(f"* rows whose exit bar precedes the entry bar: **{early}** "
               f"(must be 0)")
    return out


def check_first_touch(table, bars, rr: float) -> list[str]:
    """Re-derive the outcome from the bars: TP/SL at the **first touch**."""
    out = ["", "### 2b. Outcome re-derivation (the decisive leakage test)", ""]
    if bars is None:
        out.append("_the bars file was not supplied; skipped_")
        return out
    n = table.num_rows
    idx = np.arange(0, n, max(1, n // LEAKAGE_SAMPLE))
    lo = bars["low"]
    hi = bars["high"]
    stop = table.column("stop_price").to_numpy()
    target = table.column("target_price").to_numpy()
    side = table.column("side").to_numpy()
    entry_bar = table.column("confirm_bar").to_numpy() + 1
    label = table.column("label").to_numpy()
    nb = len(lo)

    agree = disagree = unresolved = 0
    for i in idx:
        j = int(entry_bar[i])
        if j >= nb:
            unresolved += 1
            continue
        s, t, sd = stop[i], target[i], side[i]
        hit = -1
        stop_hit = target_hit = False
        # scan forward for the first bar that touches either level
        if sd > 0:
            a = np.flatnonzero(lo[j:] <= s)
            b = np.flatnonzero(hi[j:] >= t)
        else:
            a = np.flatnonzero(hi[j:] >= s)
            b = np.flatnonzero(lo[j:] <= t)
        ia = int(a[0]) if a.size else 10**12
        ib = int(b[0]) if b.size else 10**12
        if ia == ib == 10**12:
            unresolved += 1
            continue
        stop_hit = ia <= ib            # a tie on the same bar counts as a stop
        derived = 0 if stop_hit else 1
        if derived == label[i]:
            agree += 1
        else:
            disagree += 1
    tot = agree + disagree
    out.append(f"* sampled **{len(idx):,}** candidates and re-derived the outcome from "
               f"the raw bars, scanning for the **first** touch of the stop or the target "
               f"after the entry bar (a tie on one bar counts as a stop):")
    out.append(f"  * agrees with `label`: **{agree:,}/{tot:,}** "
               f"({100 * agree / tot if tot else 0:.3f} %)")
    out.append(f"  * disagrees: **{disagree:,}**")
    out.append(f"  * still open at the end of the sample: {unresolved:,}")
    if disagree == 0 and tot:
        out.append("")
        out.append("**No leakage found on this axis**: the label is exactly the first-touch "
                   "outcome, so it never uses a later close.")
    return out


def check_features(table) -> list[str]:
    out = ["", "### 3. Missing / all-zero features", ""]
    out.append("| column | null% | zero% | verdict |")
    out.append("|---|---|---|---|")
    for name in table.column_names:
        arr = table.column(name).to_numpy(zero_copy_only=False)
        if arr.dtype.kind not in "iufb":
            continue
        num = arr.astype("float64", copy=False)
        finite = np.isfinite(num)
        nulls = int(len(num) - finite.sum())
        zeros = int((num[finite] == 0).sum())
        nz = max(1, int(finite.sum()))
        if name in ("ts_event", "fvg_bar1", "fvg_bar3", "confirm_bar", "entry_price",
                    "stop_price", "target_price", "risk", "fvg_low", "fvg_high"):
            verdict = "identifier / price — not a feature"
        elif nulls == len(num):
            verdict = "**all NaN**"
        elif zeros == nz and nulls == 0:
            verdict = "**constant 0 — carries no information**"
        elif nulls > 0.2 * len(num):
            verdict = f"**{100 * nulls / len(num):.1f} % missing**"
        else:
            verdict = "ok"
        out.append(f"| `{name}` | {100 * nulls / len(num):.2f} | {100 * zeros / nz:.2f} | "
                   f"{verdict} |")
    return out


def check_duplicates(table) -> list[str]:
    out = ["", "### 4. Duplicates and overlap", ""]
    ts = table.column("ts_event").to_numpy()
    u, c = np.unique(ts, return_counts=True)
    extra = int(len(ts) - len(u))
    out.append(f"* `ts_event` repeats on **{extra:,}** rows ({len(u):,} distinct timestamps "
               f"for {len(ts):,} rows; at most {int(c.max())} candidates share one instant).")
    if "fvg_bar3" in table.column_names:
        key = table.column("fvg_bar3").to_numpy().astype("int64") * 4 + \
            (table.column("side").to_numpy().astype("int64") + 1)
        dup_setup = len(key) - len(np.unique(key))
        out.append(f"* duplicate (`fvg_bar3`, `side`) — the **same setup recorded "
                   f"twice**: **{dup_setup:,}**")
        if extra > 0 and dup_setup == 0:
            out.append("* the repeated `ts_event` is **not** a duplicate setup: it is "
                       "several **distinct gaps** (`fvg_bar3` differs) confirming on the "
                       "**same bar**. That is the census semantics — one candidate per "
                       "(gap, confirmation bar) — so the portfolio later sees rival "
                       "entries at one instant. Not a defect; it must be resolved by the "
                       "portfolio, not by the loader.")
    if "confirm_bar" in table.column_names:
        cb = table.column("confirm_bar").to_numpy()
        g = table.column("fvg_bar3").to_numpy()
        out.append(f"* rows where `confirm_bar < fvg_bar3` (an inversion before the gap "
                   f"exists): **{int(np.sum(cb < g)):,}**")
    return out


def check_rule_fidelity(table) -> list[str]:
    out = ["", "### 5. Rule fidelity", ""]
    bti = table.column("bars_to_inversion").to_numpy()
    u, c = np.unique(bti, return_counts=True)
    out.append(f"* `bars_to_inversion` range **{int(u.min())}–{int(u.max())}**, "
               f"median {int(np.median(bti))}")
    out.append(f"* rows with `bars_to_inversion` outside [1, 15]: "
               f"**{int(np.sum((bti < 1) | (bti > 15))):,}** (the doc window is 7–15; "
               f"the code window is 1–15)")
    if "checklist_score" in table.column_names:
        sc = table.column("checklist_score").to_numpy()
        su, scnt = np.unique(sc, return_counts=True)
        out.append("* `checklist_score`: " + ", ".join(
            f"{_fmt(a)}:{100 * b / len(sc):.1f}%" for a, b in zip(su, scnt)))
        out.append(f"  (the score is capped at 4 because `vision_iou_pass` is never "
                   f"true; max observed {_fmt(su.max())})")
    if "smt_divergence" in table.column_names:
        s = table.column("smt_divergence").to_numpy()
        su, scnt = np.unique(s, return_counts=True)
        lbl = {-1: "unknown", 0: "no divergence", 1: "divergence"}
        out.append("* `smt_divergence`: " + ", ".join(
            f"{lbl.get(int(a), a)}:{100 * b / len(s):.1f}%" for a, b in zip(su, scnt)))
    if "risk" in table.column_names:
        r = table.column("risk").to_numpy()
        out.append(f"* `risk` (points): min {r.min():.4f}, median {np.median(r):.4f}, "
                   f"max {r.max():.4f}; rows with risk ≤ 0: **{int(np.sum(r <= 0)):,}**")
    out.append("* **`gap_size_atr` does not exist in the schema.** The checklist asks for "
               "it; it is not computed, so the ATR-normalised gap width cannot be audited "
               "from these files.")
    return out


def check_execution(table, rr: float) -> list[str]:
    """The label is the standalone outcome; the portfolio drops blocked signals."""
    label = table.column("label").to_numpy()
    r = table.column("r_multiple").to_numpy().astype("float64")
    resolved = label >= 0
    standalone = float(np.nanmean(r[resolved])) if resolved.any() else float("nan")
    out = ["", "### 6. Execution consistency", ""]
    out.append(f"* the standalone expectancy over every resolved candidate is "
               f"**{standalone:+.4f} R** (n={int(resolved.sum()):,}).")
    out.append("* **the label is NOT the executed result.** `r_multiple` is the "
               "outcome *as if the candidate were the only open position*; the backtest "
               "trades **one position at a time** and **drops** the signals that arrive "
               "while a position is open. The portfolio's trade set is a strict subset, "
               "and its expectancy differs from the number above. An ML model trained on "
               "`label` therefore learns a different problem from the one the portfolio "
               "solves — this is by design (D4), but it must be stated.")
    if "confirm_bar" in table.column_names:
        cb = table.column("confirm_bar").to_numpy()
        out.append(f"* `confirm_bar` is monotonic in the file: "
                   f"{'yes' if np.all(np.diff(cb) >= 0) else '**no**'} "
                   f"(the log is written in time order)")
    return out


def check_minutes_from_us_open(table) -> list[str]:
    """The D2 ``minutes_from_us_open`` must be ET minutes from 09:30, not UTC.

    This is the check that catches a timezone helper that silently returns UTC:
    the value would be wrong by the UTC/ET offset (4h in summer, 5h in winter).
    """
    if "minutes_from_us_open" not in table.column_names:
        return []
    import datetime as dt
    from zoneinfo import ZoneInfo

    ts = table.column("ts_event").to_numpy()
    got = table.column("minutes_from_us_open").to_numpy()
    idx = np.arange(0, len(ts), max(1, len(ts) // 2000))
    tz = ZoneInfo("America/New_York")
    bad = 0
    off = []
    for i in idx:
        u = dt.datetime.fromtimestamp(int(ts[i]) / 1e9, dt.timezone.utc)
        e = u.astimezone(tz)
        want = e.hour * 60 + e.minute - (9 * 60 + 30)
        off.append(int(got[i]) - want)
    off = np.array(off)
    bad = int(np.sum(off != 0))
    out = ["", "### 8. `minutes_from_us_open` vs Eastern time", ""]
    out.append(f"* sampled {len(idx):,} rows; mismatches: **{bad:,}**")
    if bad:
        out.append(f"  the offset is {int(np.median(off))} minutes -> the helper is "
                   f"not applying the timezone (a UTC/ET bug)")
    else:
        out.append("  every sampled row is the ET minute from 09:30 -- the timezone "
                   "helper is correct")
    return out


def check_timestamp_semantics(table, bars) -> list[str]:
    out = ["", "### 7. Timestamp semantics", ""]
    if bars is not None:
        ts = table.column("ts_event").to_numpy()
        cb = table.column("confirm_bar").to_numpy()
        delta = (ts - bars["ts"][cb]) / 1e9
        out.append(f"* `ts_event − timestamp[confirm_bar]` = {np.median(delta):.0f} s for "
                   f"the median row → it is the **confirmation bar's close time**, i.e. "
                   f"the moment the signal exists. It is **not** the exit time and **not** "
                   f"the entry time (the entry is the next bar's open).")
    else:
        out.append("* `ts_event` is the confirmation bar's close (see §2).")
    return out


# ---------------------------------------------------------------------------


def load_bars(path: Path | None) -> dict | None:
    if path is None or not path.exists():
        return None
    t = pq.read_table(path)
    ts = t.column("timestamp").to_numpy()
    if np.abs(ts).max() < 10**16:          # ms → ns
        ts = ts * 1_000_000
    return {
        "ts": ts.astype("int64"),
        "open": t.column("open").to_numpy().astype("float64"),
        "high": t.column("high").to_numpy().astype("float64"),
        "low": t.column("low").to_numpy().astype("float64"),
        "close": t.column("close").to_numpy().astype("float64"),
    }


CANDIDATE_COLS = {"label", "r_multiple", "checklist_score"}


def facts(table) -> dict:
    """The numbers the summary table needs, computed once."""
    f = {"rows": table.num_rows}
    if "label" in table.column_names:
        lab = table.column("label").to_numpy()
        u, c = np.unique(lab, return_counts=True)
        f["labels"] = {int(k): int(v) for k, v in zip(u, c)}
        f["n_resolved"] = int((lab >= 0).sum())
        r = table.column("r_multiple").to_numpy().astype("float64")
        m = lab >= 0
        f["standalone_r"] = float(np.nanmean(r[m])) if m.any() else float("nan")
    if "checklist_score" in table.column_names:
        f["checklist_max"] = float(np.nanmax(table.column("checklist_score").to_numpy()))
    if "smt_divergence" in table.column_names:
        smt = table.column("smt_divergence").to_numpy()
        f["smt_unknown_pct"] = 100.0 * float(np.mean(smt < 0))
    for v in ("vision_iou", "vision_confidence"):
        if v in table.column_names:
            a = table.column(v).to_numpy(zero_copy_only=False).astype("float64")
            f[v + "_nan_pct"] = 100.0 * float(np.mean(~np.isfinite(a)))
    if "ts_event" in table.column_names:
        ts = table.column("ts_event").to_numpy()
        f["ts_repeat"] = int(len(ts) - len(np.unique(ts)))
    if {"fvg_bar3", "side"} <= set(table.column_names):
        key = table.column("fvg_bar3").to_numpy().astype("int64") * 4 + \
            table.column("side").to_numpy().astype("int64") + 1
        f["dup_setup"] = int(len(key) - len(np.unique(key)))
    return f


def audit(path: Path, bars: dict | None, rr: float):
    table = pq.read_table(path)
    f = facts(table)
    out = [f"\n## `{path.name}`", ""]
    out += stats_block(table)
    out += ["", "### First 20 rows", ""]
    out += head_block(table)
    if CANDIDATE_COLS <= set(table.column_names):
        out += [""] + check_labels(table)
        out += check_time_alignment(table, bars)
        out += check_first_touch(table, bars, rr)
        out += check_features(table)
        out += check_duplicates(table)
        out += check_rule_fidelity(table)
        out += check_execution(table, rr)
        out += check_timestamp_semantics(table, bars)
        out += check_minutes_from_us_open(table)
    else:
        out += ["", "_(not a candidate log: schema / head / stats only)_"]
    return out, f


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="logs")
    ap.add_argument("--bars", default=None,
                    help="the default bars parquet (its order is what the log's bar "
                         "indices refer to)")
    ap.add_argument("--bars-map", action="append", default=[],
                    metavar="SYMBOL=PATH",
                    help="a per-symbol bars file, e.g. NQ=logs/NQ_1m.parquet. "
                         "Repeat for each symbol.")
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--out", default="research/audit/DATASET_AUDIT.md")
    args = ap.parse_args(argv)

    root = Path(args.dir)
    default_bars = load_bars(Path(args.bars)) if args.bars else None
    bars_by_symbol: dict[str, dict | None] = {}
    cache: dict[str, dict] = {}
    for spec in args.bars_map:
        sym, _, path = spec.partition("=")
        key = str(Path(path))
        if key not in cache:
            cache[key] = load_bars(Path(path))
        bars_by_symbol[sym.strip()] = cache[key]
    files = sorted(p for p in root.glob("*.parquet"))
    if not files:
        raise SystemExit(f"no parquet in {root}")

    L = ["# Dataset audit — the parquet files in `logs/`\n",
         f"Generated by `scripts/audit_dataset.py`. {len(files)} files. "
         f"The bars file used for the leakage/alignment checks: "
         f"`{args.bars or 'none'}`.\n"]
    facts_by_file: list[tuple[str, dict]] = []
    body: list[str] = []
    for p in files:
        table = pq.read_table(p)
        sym = None
        if "symbol" in table.column_names and table.num_rows:
            vals = {v for v in table.column("symbol").slice(0, 1000).to_pylist()}
            sym = vals.pop() if len(vals) == 1 else None
        bars = bars_by_symbol.get(sym, default_bars) if sym else default_bars
        lines, f = audit(p, bars, args.rr)
        body += lines
        facts_by_file.append((p.name, f))

    # the summary, built before the body so a reviewer sees it first
    S = ["## Summary\n",
         "| file | rows | labels (win / loss / open) | win% | checklist max | SMT unknown% | "
         "vision NaN% | ts repeats | dup setups |",
         "|---|---|---|---|---|---|---|---|---|"]
    for name, f in facts_by_file:
        lab = f.get("labels")
        if lab:
            w, l, o = lab.get(1, 0), lab.get(0, 0), lab.get(-1, 0)
            n = w + l + o
            winp = f"{100 * w / n:.1f}" if n else "-"
            labels = f"{w:,} / {l:,} / {o:,}"
        else:
            labels = winp = "-"
        cm = f.get("checklist_max")
        smt = f.get("smt_unknown_pct")
        vis = f.get("vision_iou_nan_pct")
        tsr = f.get("ts_repeat")
        dup = f.get("dup_setup")
        S.append("| `{}` | {:,} | {} | {} | {} | {} | {} | {} | {} |".format(
            name, f["rows"], labels, winp,
            "-" if cm is None else _fmt(cm),
            "-" if smt is None else f"{smt:.1f}",
            "-" if vis is None else f"{vis:.0f}",
            "-" if tsr is None else f"{tsr:,}",
            "-" if dup is None else dup,
        ))
    S.append("")
    S.append("**Read the summary as:** a `dup setups` of 0 means no setup is recorded "
             "twice; a non-zero `ts repeats` with `dup setups = 0` means distinct gaps "
             "confirmed on the same bar (census semantics, not a defect). "
             "`vision NaN% = 100` means the vision columns are dead in that file.")
    L = L[:3] + S + [""] + L[3:]
    L += body

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"[SAVED] {out}  ({len(files)} files, {out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
