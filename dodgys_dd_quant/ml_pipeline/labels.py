"""Binary meta-labels for the rolling meta-labeler.

Label vocabulary (D2 / ``RULE_SPEC`` **T17** / **I10**):

* ``1``  -- the trade reached its target (the phase-1 target is the 2R price).
* ``0``  -- the trade hit its stop.
* ``-1`` -- **unlabelled**: the trade is still open (it has reached neither the
  stop nor the target inside the horizon, or the series ended first).

The unlabelled state is *not* forced to ``0``.  Forcing it would silently
rewrite the base rate: every still-open trade would be counted as a loss, and
the classifier would be trained on a label that the market never produced.
Unlabelled rows are **kept in the candidate log** (``INV4``: no signal may be
erased after the fact) and are dropped **only** at training time.

Resolution conventions (identical to the rule engine's, see
``research/experiments/e1_rule_falsification.py``):

* the entry happens at the close of the confirmation bar, therefore **only bars
  strictly after ``ts_event`` can resolve the trade** -- a feature/label can
  never be influenced by the bar the decision was taken on;
* a bar that touches both the stop and the target resolves as a **stop** (the
  conservative tie-break);
* the scan stops after ``horizon_bars`` bars; the trade is then unlabelled.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dodgys_dd_quant.ml_pipeline import (
    DEFAULT_BAR_INTERVAL_MINUTES,
    LABEL_HORIZON_BARS,
    REQUIRED_BAR_COLUMNS,
    REQUIRED_CANDIDATE_COLUMNS,
)

__all__ = [
    "LABEL_TARGET",
    "LABEL_STOP",
    "LABEL_UNLABELLED",
    "build_labels",
    "summarize_labels",
    "max_holding_minutes",
    "label_horizon_bars",
]

LABEL_TARGET = 1
LABEL_STOP = 0
LABEL_UNLABELLED = -1


def label_horizon_bars() -> int:
    """The label horizon in bars -- *the* maximum holding period of the strategy."""
    return LABEL_HORIZON_BARS


def max_holding_minutes(bar_interval_minutes: int = DEFAULT_BAR_INTERVAL_MINUTES) -> int:
    """Maximum holding period in minutes.

    This is the number the walk-forward embargo has to be at least
    (``splits.make_folds`` derives it from here rather than assuming it).
    """
    return LABEL_HORIZON_BARS * int(bar_interval_minutes)


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...], what: str) -> None:
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise ValueError(f"{what} is missing required column(s): {missing}")


def _normalise_bars(bars: pd.DataFrame) -> pd.DataFrame:
    _require_columns(bars, REQUIRED_BAR_COLUMNS, "bars")
    out = bars.loc[:, list(REQUIRED_BAR_COLUMNS)].copy()
    out["ts_event"] = out["ts_event"].astype("int64")
    out = out.sort_values("ts_event", kind="stable").reset_index(drop=True)
    ts = out["ts_event"].to_numpy()
    if len(ts) > 1 and not np.all(np.diff(ts) > 0):
        raise ValueError("bars: ts_event must be strictly increasing (no duplicates)")
    return out


def build_labels(
    candidates: pd.DataFrame,
    bars: pd.DataFrame,
    *,
    horizon_bars: int | None = None,
) -> pd.DataFrame:
    """Attach ``label`` and ``r_multiple`` to a candidate log.

    Parameters
    ----------
    candidates:
        The D2 candidate log.  ``entry_price`` / ``stop_price`` / ``target_price``
        / ``risk`` are taken **from the log itself** -- the pipeline never
        re-derives the trade geometry, it only resolves the outcome.
    bars:
        The market series used to resolve the outcome.
    horizon_bars:
        Maximum number of bars the trade is allowed to live.  Defaults to
        ``LABEL_HORIZON_BARS`` (240 one-minute bars = 4 hours).

    Returns
    -------
    A copy of ``candidates`` with the columns ``label`` (int8), ``r_multiple``
    (float64, NaN while unlabelled), ``bars_held`` (int32, NaN while unlabelled)
    and ``exit_ts_event`` (int64 ns, NaN while unlabelled).

    Raises
    ------
    ValueError
        On a data-integrity violation: a non-positive risk, a target on the
        wrong side of the entry, a stop on the wrong side of the entry, a
        non-monotonic bar series.
    """
    if horizon_bars is None:
        horizon_bars = LABEL_HORIZON_BARS
    horizon_bars = int(horizon_bars)
    if horizon_bars <= 0:
        raise ValueError("horizon_bars must be positive")

    _require_columns(candidates, REQUIRED_CANDIDATE_COLUMNS, "candidates")
    b = _normalise_bars(bars)

    out = candidates.copy()
    n_cand = len(out)

    ts = out["ts_event"].astype("int64").to_numpy()
    side = pd.to_numeric(out["side"], errors="coerce").to_numpy(dtype="float64")
    entry = pd.to_numeric(out["entry_price"], errors="coerce").to_numpy(dtype="float64")
    stop = pd.to_numeric(out["stop_price"], errors="coerce").to_numpy(dtype="float64")
    target = pd.to_numeric(out["target_price"], errors="coerce").to_numpy(dtype="float64")
    risk = pd.to_numeric(out["risk"], errors="coerce").to_numpy(dtype="float64")

    if np.any(~np.isfinite(side)) or np.any(np.isin(side, (0.0,))):
        raise ValueError("candidates.side must be +1 (long) or -1 (short)")
    if np.any(~np.isfinite(risk)) or np.any(risk <= 0.0):
        raise ValueError("candidates.risk must be strictly positive for every candidate")
    if np.any(~np.isfinite(entry)) or np.any(~np.isfinite(stop)) or np.any(~np.isfinite(target)):
        raise ValueError("candidates entry/stop/target prices must be finite")

    is_long = side > 0
    bad_target = np.where(is_long, target <= entry, target >= entry)
    bad_stop = np.where(is_long, stop >= entry, stop <= entry)
    if bad_target.any():
        raise ValueError(
            f"{int(bad_target.sum())} candidate(s) have a target on the wrong side of the entry"
        )
    if bad_stop.any():
        raise ValueError(
            f"{int(bad_stop.sum())} candidate(s) have a stop on the wrong side of the entry"
        )

    # --- the first bar that can resolve the trade -------------------------
    bar_ts = b["ts_event"].to_numpy(dtype="int64")
    bar_low = b["low"].to_numpy(dtype="float64")
    bar_high = b["high"].to_numpy(dtype="float64")
    n_bars = len(b)
    start = np.searchsorted(bar_ts, ts, side="right")  # strictly after ts_event

    stop_offset = np.full(n_cand, -1, dtype="int64")
    target_offset = np.full(n_cand, -1, dtype="int64")

    for offset in range(horizon_bars):
        idx = start + offset
        valid = idx < n_bars
        if not valid.any():
            break
        safe = np.where(valid, idx, 0)
        low = bar_low[safe]
        high = bar_high[safe]
        hit_stop = valid & np.where(is_long, low <= stop, high >= stop)
        hit_target = valid & np.where(is_long, high >= target, low <= target)
        stop_offset = np.where(hit_stop & (stop_offset < 0), offset, stop_offset)
        target_offset = np.where(hit_target & (target_offset < 0), offset, target_offset)

    # --- resolve: the stop wins ties -------------------------------------
    stop_first = (stop_offset >= 0) & (
        (target_offset < 0) | (stop_offset <= target_offset)
    )
    label = np.full(n_cand, LABEL_UNLABELLED, dtype="int8")
    label[stop_first] = LABEL_STOP
    label[(~stop_first) & (target_offset >= 0)] = LABEL_TARGET

    # --- realised R and the exit timestamp -------------------------------
    exit_price = np.full(n_cand, np.nan, dtype="float64")
    exit_price[stop_first] = stop[stop_first]
    resolved_target = (~stop_first) & (target_offset >= 0)
    exit_price[resolved_target] = target[resolved_target]

    r_multiple = np.full(n_cand, np.nan, dtype="float64")
    signed = np.where(is_long, exit_price - entry, entry - exit_price)
    r_multiple = signed / risk

    exit_offset = np.where(stop_first, stop_offset, target_offset)
    bars_held = np.where(exit_offset >= 0, exit_offset + 1, np.nan)
    exit_ts = np.full(n_cand, np.nan, dtype="float64")
    resolved = exit_offset >= 0
    if resolved.any():
        exit_idx = np.clip(start[resolved] + exit_offset[resolved], 0, max(n_bars - 1, 0))
        exit_ts[resolved] = bar_ts[exit_idx]

    out["label"] = label
    out["r_multiple"] = r_multiple
    out["bars_held"] = pd.array(bars_held, dtype="Float64")
    out["exit_ts_event"] = pd.array(exit_ts, dtype="Int64")
    return out


def summarize_labels(labelled: pd.DataFrame) -> dict[str, float | int]:
    """Class balance and base rate of a labelled candidate log.

    ``base_rate`` is ``positives / labelled`` -- the unlabelled rows are
    excluded from the denominator, because they carry no outcome.
    """
    if "label" not in labelled.columns:
        raise ValueError("labelled frame has no 'label' column")
    label = labelled["label"].astype("int8")
    n_total = int(len(label))
    n_target = int((label == LABEL_TARGET).sum())
    n_stop = int((label == LABEL_STOP).sum())
    n_unlabelled = int((label == LABEL_UNLABELLED).sum())
    n_labelled = n_target + n_stop
    base_rate = (n_target / n_labelled) if n_labelled else float("nan")

    held = labelled["bars_held"] if "bars_held" in labelled.columns else None
    if held is not None:
        held_vals = pd.to_numeric(held, errors="coerce").dropna()
        max_held = float(held_vals.max()) if len(held_vals) else float("nan")
        mean_held = float(held_vals.mean()) if len(held_vals) else float("nan")
    else:
        max_held = float("nan")
        mean_held = float("nan")

    r = labelled["r_multiple"] if "r_multiple" in labelled.columns else None
    mean_r = float(pd.to_numeric(r, errors="coerce").mean()) if r is not None else float("nan")

    return {
        "n_candidates": n_total,
        "n_labelled": n_labelled,
        "n_target": n_target,
        "n_stop": n_stop,
        "n_unlabelled": n_unlabelled,
        "base_rate": base_rate,
        "class_balance_neg_to_pos": (n_stop / n_target) if n_target else float("inf"),
        "mean_bars_held": mean_held,
        "max_bars_held": max_held,
        "mean_r_multiple": mean_r,
    }
