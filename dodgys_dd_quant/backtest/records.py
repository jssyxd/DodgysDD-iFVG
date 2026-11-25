"""A durable archive of backtest runs and of **every** candidate iFVG.

Two tables, both Parquet (Zstd-7, atomic rename):

``runs.parquet``
    one row per backtest: the configuration (symbol, timeframe, preset, cost
    profile, slippage, horizon, regime), the sample (bars, date range), the
    statistics (``TradeStats``: n, win rate, E[R], E_net, PF, t, CI, cost),
    the rolling statistics (Sharpe, deflated Sharpe, DSR p), and the verdict
    (kill-switch level, abort criteria fired / evaluated).

``candidates.parquet``
    one row per **candidate setup**, taken or not: every geometry field the
    engine produced, the checklist and regime context, the model's score and
    gate decision when a model ran, the one-position portfolio's selection
    flag, the fold that decided it, the outcome and the final label ``y``.

Why a second table and not the D2 log
-------------------------------------
The D2 candidate log is a **frozen schema** (the benchmark asserts it, and
`INV4` forbids erasing a signal).  The archive is additive: it keeps the D2
columns *plus* the bar indices, the outcome string, the features and the
selection/gate decisions, so a later model can be trained on the exact
population a backtest saw -- including the candidates that were blocked by an
open position.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

__all__ = [
    "candidate_frame",
    "run_record",
    "summary_markdown",
    "write_parquet",
]

#: The Candidate dataclass fields that are not a plain scalar.
_NON_SCALAR = frozenset({"checklist_flags"})


def _scalar_fields(candidate) -> dict:
    out: dict = {}
    for key, value in asdict(candidate).items():
        if key in _NON_SCALAR:
            out["checklist_flags_json"] = json.dumps(value, sort_keys=True)
            continue
        out[key] = value
    return out


def _label(outcome: str) -> int:
    if outcome == "target":
        return 1
    if outcome == "stop":
        return 0
    return -1


def candidate_frame(
    log,
    *,
    run_id: str,
    symbol: str,
    timeframe: str,
    preset: str,
    horizon_minutes: float,
    bars,
    selected_ids: set[int],
    gate_approved_ids: set[int] | None = None,
    folds: Sequence = (),
    features: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """One row per candidate, with features, decisions and the final label.

    ``selected_ids`` / ``gate_approved_ids`` are ``id()`` sets of the objects
    the caller marked -- the same objects that live in ``log.candidates``.
    """
    gate_approved_ids = gate_approved_ids or set()
    if not log.candidates:
        # an empty population is a legitimate outcome (the ATR floor can
        # filter every setup); the archive keeps a typed, zero-row table
        columns = list(getattr(log, "D2_COLUMNS", ())) + [
            "run_id", "symbol", "timeframe", "preset", "horizon_minutes",
            "ts_utc", "ts_event_ms", "y", "selected", "gate_approved", "fold_asof",
        ]
        # ``symbol`` is already a D2 column; a duplicate label makes
        # ``pd.concat`` raise "Reindexing only valid with uniquely valued Index"
        columns = list(dict.fromkeys(columns))
        if features is not None:
            columns += [c for c in features.columns if c not in columns]
        return pd.DataFrame(columns=columns)
    rows = []
    for cand in log.candidates:
        row = _scalar_fields(cand)
        row.update(
            {
                "run_id": run_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "preset": preset,
                "horizon_minutes": float(horizon_minutes),
                "ts_utc": pd.to_datetime(int(cand.ts_event), unit="ns", utc=True).isoformat(),
                "y": _label(cand.outcome),
                "selected": id(cand) in selected_ids,
                "gate_approved": bool(gate_approved_ids) and id(cand) in gate_approved_ids,
                "fold_asof": "",
            }
        )
        rows.append(row)
    frame = pd.DataFrame(rows)

    # the fold whose test window contains the candidate (a model run only)
    if folds:
        stamps = frame["ts_event"].to_numpy(dtype=np.int64)
        asof = np.full(len(frame), "", dtype=object)
        for fold in folds:
            start, end = _window_ns(fold)
            mask = stamps >= start
            if end is not None:
                mask &= stamps < end
            asof[mask] = fold.asof
        frame["fold_asof"] = asof

    # keep the nanosecond timestamp exact: a float64 round-trip through pandas
    # would quantise ~1.7e18 ns to ~200 ns steps
    frame["ts_event"] = frame["ts_event"].astype("int64")
    frame["ts_event_ms"] = frame["ts_event"] // 1_000_000

    # the feature frame is built from the same rows, in the same order
    if features is not None:
        for column in features.columns:
            if column in ("ts_event", "side") or column in frame.columns:
                continue
            frame[column] = features[column].to_numpy()
    return frame


def _window_ns(fold) -> tuple[int, int | None]:
    from dodgys_dd_quant.backtest.walk_forward import _date_to_ns

    start = _date_to_ns(fold.test_start) if fold.test_start else fold.asof_ns
    end = _date_to_ns(fold.test_end) if fold.test_end else None
    return int(start), (int(end) if end is not None else None)


def run_record(
    *,
    run_id: str,
    symbol: str,
    timeframe: str,
    preset: str,
    data_path: str,
    n_bars: int,
    first_ts: int,
    last_ts: int,
    profile_name: str,
    slippage_ticks: int,
    horizon_minutes: float,
    regime: str,
    report,
    runtime_s: float,
    gate: str,
    models_root: str,
    n_folds: int,
) -> dict:
    """The ``runs.parquet`` row of one backtest."""
    stats = report.portfolio
    abort = (report.kill_switch or {}).get("abort_criteria") or {}
    fired = [c["name"] for c in abort.get("criteria", []) if c.get("fired")]
    evaluated = [c["name"] for c in abort.get("criteria", []) if c.get("evaluated")]
    return {
        "run_id": run_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "preset": preset,
        "data_path": data_path,
        "n_bars": int(n_bars),
        "first_ts": int(first_ts),
        "last_ts": int(last_ts),
        "first_utc": pd.to_datetime(int(first_ts), unit="ns", utc=True).isoformat(),
        "last_utc": pd.to_datetime(int(last_ts), unit="ns", utc=True).isoformat(),
        "cost_profile": profile_name,
        "slippage_ticks": int(slippage_ticks),
        "horizon_minutes": float(horizon_minutes),
        "regime": regime,
        "gate": gate,
        "models_root": models_root,
        "n_folds": int(n_folds),
        "n_candidates": int(report.n_candidates),
        "n_approved": int(report.n_approved),
        "n_trades": int(report.n_trades),
        "win_rate": float(stats.win_rate),
        "expectancy_r": float(stats.expectancy_r),
        "expectancy_net_r": float(stats.expectancy_net_r),
        "profit_factor": float(stats.profit_factor),
        "profit_factor_net": float(stats.profit_factor_net),
        "t_stat": float(stats.t_stat),
        "ci95_lo": float(stats.ci95_lo),
        "ci95_hi": float(stats.ci95_hi),
        "total_r": float(stats.total_r),
        "max_consecutive_losses": int(stats.max_consecutive_losses),
        "mean_cost_r": float(stats.mean_cost_r),
        "break_even_cost_r": float(stats.break_even_cost_r),
        "sharpe": float(report.sharpe),
        "deflated_sharpe": float(report.deflated_sharpe),
        "dsr_p_value": float(report.dsr_p_value),
        "trials": int(report.trials),
        "kill_level": str((report.kill_switch or {}).get("level", "")),
        "abort_fired": ",".join(fired),
        "abort_evaluated": ",".join(evaluated),
        "runtime_s": float(runtime_s),
    }


def write_parquet(frame: pd.DataFrame, path: Path) -> Path:
    """Zstd-7, atomic rename (the lake's write contract)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, compression="zstd", compression_level=7, index=False)
    tmp.replace(path)
    return path


def summary_markdown(runs: pd.DataFrame, notes: Iterable[str] = ()) -> str:
    """The human-readable roll-up of the matrix."""
    lines = ["# Backtest matrix", ""]
    for note in notes:
        lines.append(f"* {note}")
    if notes:
        lines.append("")

    def table(frame: pd.DataFrame, title: str) -> None:
        lines.extend([f"## {title}", ""])
        if frame.empty:
            lines.extend(["_(empty)_", ""])
            return
        header = "| symbol | tf | preset | n | win % | E[R] | E_net | PF | t | kill | abort |"
        lines.extend([header, "|---|---|---|---|---|---|---|---|---|---|---|"])
        for row in frame.itertuples():
            lines.append(
                f"| {row.symbol} | {row.timeframe} | {row.preset} | {row.n_trades} "
                f"| {100 * row.win_rate:.1f} | {row.expectancy_r:+.4f} "
                f"| {row.expectancy_net_r:+.4f} | {row.profit_factor:.3f} "
                f"| {row.t_stat:+.2f} | {row.kill_level} | {row.abort_fired or '-'} |"
            )
        lines.append("")

    for preset in sorted(runs["preset"].unique()):
        table(runs[runs["preset"] == preset], f"preset `{preset}`")
    return "\n".join(lines) + "\n"
