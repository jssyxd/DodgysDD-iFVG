"""Feature engineering for the rolling meta-labeler.

Every feature must be computable **at decision time** -- that is, from
information that exists at or before ``ts_event`` (the close of the inversion
confirmation bar).  Nothing in this module may read a value dated after
``ts_event``.  ``assert_no_lookahead`` proves that property (it re-derives the
features from a *perturbed future* and requires the pre-perturbation rows to be
bit-identical), and ``tests/unit/test_labels.py`` exercises it.

Feature universe
----------------
``RULE_SPEC`` **T26** (the discussion's L146 feature list) is the normative
list.  Two of its items are not available in this repository today:

* **"VXN 1-hour change rate"** -- dropped.  The only VXN series in the lake is
  *daily* (``macro/vxn/VXN_1d_consolidated.parquet``); a daily index cannot
  produce a 1-hour change rate, and a daily proxy would merely duplicate the
  level feature (``RULE_SPEC`` **A18**, option (b)).
* **"visual confidence"** -- optional.  The vision layer does not exist
  (**D12**), so the column is normally absent or all-NaN; the pipeline then
  excludes it and records the exclusion in the artefact metadata.

``EXTENSION_FEATURES`` are *causal* extras that are **off by default** because
they are not part of the frozen doc list.  They are available behind
``extra_features=True`` for the experiments that need volatility-normalised
inputs; they never touch a future value either.

Availability legend used in the docstrings below:

* ``[FACT]`` -- the value exists in this repository today (a D2 column, or a
  value derivable from the D2 columns).
* ``[DERIVED]`` -- computable from the D2 columns / the market series, but only
  at a decision-time information cut-off.
* ``[ABSENT]`` -- not available today; the pipeline degrades gracefully.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np
import pandas as pd

from dodgys_dd_quant.ml_pipeline import (
    DEFAULT_BAR_INTERVAL_MINUTES,
    REQUIRED_BAR_COLUMNS,
    REQUIRED_CANDIDATE_COLUMNS,
)

__all__ = [
    "CORE_FEATURES",
    "OPTIONAL_FEATURES",
    "EXTENSION_FEATURES",
    "FEATURE_LIST",
    "FEATURE_SOURCES",
    "FEATURE_AVAILABILITY",
    "build_features",
    "candidate_consistency_report",
    "resolve_feature_list",
    "assert_no_lookahead",
    "minutes_from_us_open",
    "vxn_regime_from_level",
]

#: The doc's feature list (L146) minus the dropped VXN 1-hour change rate.
CORE_FEATURES: tuple[str, ...] = (
    "checklist_score",       # [FACT]  D2 column (rule engine, five named checks)
    "smt_divergence",        # [FACT]  D2 column, int8: 1 yes / 0 no / -1 unknown
    "vxn_level",             # [FACT]  D2 ``vxn_known`` -- the *lagged* VXN close
    "vxn_regime",            # [FACT]  D2 column, recomputed here from the lagged level
    "bars_to_inversion",     # [FACT]  D2 column: confirm_bar - fvg_bar3
    "minutes_from_us_open",  # [FACT]  D2 column, recomputed here from ts_event
)

#: Optional features: used when the column is present *and* not all-NaN.
OPTIONAL_FEATURES: tuple[str, ...] = ("vision_confidence",)  # [ABSENT] today (D12)

#: Causal extras, off by default (not part of the frozen L146 list).
EXTENSION_FEATURES: tuple[str, ...] = (
    "atr14",                  # [DERIVED] Wilder ATR(14) of the last closed bar
    "risk_atr",               # [DERIVED] risk / atr14  -- normalised stop distance
    "gap_atr",                # [DERIVED] |fvg_high - fvg_low| / atr14
    "volume_zscore_60",       # [DERIVED] volume z-score over the last 60 closed bars
    # --- the higher-timeframe / setup-quality block (2026-11-25) ----------
    "htf_bias_1h",            # [HTF] 1H close-vs-open direction, x side (+1 agrees)
    "htf_bias_15m",           # [HTF] the same on 15m
    "dist_to_htf_liquidity",  # [HTF] nearest prior 1H swing on the target side, / atr14
    "inversion_speed",        # [SETUP] 1 / bars_to_inversion
    "gap_quality",            # [SETUP] |fvg_high - fvg_low| / risk
    "session_quality",        # [SETUP] 2 = NY killzone, 1 = London, 0 = other
    "recent_same_side_wr",    # [STATE] win rate of the last 20 RESOLVED same-side setups
    "vxn_zscore",             # [STATE] (vxn_known - past-100 mean) / past-100 std
)

#: The declared universe: what the pipeline *may* use.
FEATURE_LIST: tuple[str, ...] = CORE_FEATURES + OPTIONAL_FEATURES

#: feature -> the D2 column it is read from (None => computed).
FEATURE_SOURCES: dict[str, str | None] = {
    "checklist_score": "checklist_score",
    "smt_divergence": "smt_divergence",
    "vxn_level": "vxn_known",
    "vxn_regime": "vxn_regime",
    "bars_to_inversion": "bars_to_inversion",
    "minutes_from_us_open": "minutes_from_us_open",
    "vision_confidence": "vision_confidence",
    "atr14": None,
    "risk_atr": None,
    "gap_atr": None,
    "volume_zscore_60": None,
    "htf_bias_1h": None,
    "htf_bias_15m": None,
    "dist_to_htf_liquidity": None,
    "inversion_speed": None,
    "gap_quality": None,
    "session_quality": None,
    "recent_same_side_wr": None,
    "vxn_zscore": None,
}

#: Human readable availability, quoted verbatim in the README and the artefact.
FEATURE_AVAILABILITY: dict[str, str] = {
    "checklist_score": "[FACT] D2 column; produced by the rule engine (D8: report, never filter)",
    "smt_divergence": "[FACT] D2 column; -1 (unknown) when no reference instrument exists",
    "vxn_level": "[FACT] D2 'vxn_known' -- the lagged VXN close (INV6)",
    "vxn_regime": "[FACT] D2 column; recomputed here from the lagged level (RULE_SPEC 1.9)",
    "bars_to_inversion": "[FACT] D2 column",
    "minutes_from_us_open": "[FACT] D2 column; recomputed here from ts_event (ET)",
    "vision_confidence": "[ABSENT] vision layer does not exist (D12) -> excluded when missing",
    "atr14": "[DERIVED] Wilder ATR(14), causal (extension, off by default)",
    "risk_atr": "[DERIVED] risk / atr14 (extension, off by default)",
    "gap_atr": "[DERIVED] FVG gap width / atr14 (extension, off by default)",
    "volume_zscore_60": "[DERIVED] causal rolling z-score (extension, off by default)",
    "htf_bias_1h": "[HTF] 15m/1H resampled from the 1m bars, only closed bars used",
    "htf_bias_15m": "[HTF] as above on 15m",
    "dist_to_htf_liquidity": "[HTF] prior 1H fractal swings, publication time honoured",
    "inversion_speed": "[SETUP] 1 / bars_to_inversion",
    "gap_quality": "[SETUP] gap width / risk (a different normalisation from gap_atr)",
    "session_quality": "[SETUP] ET killzone membership (NY=2, London=1)",
    "recent_same_side_wr": "[STATE] strictly causal: only outcomes RESOLVED before the setup",
    "vxn_zscore": "[STATE] causal, over the previous 100 candidates",
}

#: Minutes from the same day's 09:30 ET open -- signed.
US_OPEN_MINUTES = 9 * 60 + 30  # 570

#: VXN regime bins, corrected per ``RULE_SPEC`` 1.9 (resolves I05).
#: (-inf, 18) -> 0 | [18, 28] -> 1 | (28, inf) -> 2
VXN_REGIME_LOW, VXN_REGIME_NORMAL, VXN_REGIME_HIGH = 0, 1, 2


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _require_columns(frame: pd.DataFrame, columns: Sequence[str], what: str) -> None:
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise ValueError(f"{what} is missing required column(s): {missing}")


def minutes_from_us_open(ts_event: pd.Series) -> pd.Series:
    """Signed minutes from the **same day's** 09:30 ET open.

    ``+90`` == 11:00 ET, ``-60`` == 08:30 ET, ``0`` == 09:30 ET.  The sign is
    kept: for a 24/7 market a pre-open candidate is *before* the open, and
    hiding that behind a wrapped value would destroy the time-of-day signal.
    """
    ts = pd.to_datetime(ts_event, unit="ns", utc=True)
    et = ts.dt.tz_convert("America/New_York")
    minutes = et.dt.hour * 60 + et.dt.minute + et.dt.second / 60.0
    return minutes - US_OPEN_MINUTES


def vxn_regime_from_level(vxn_level: pd.Series) -> pd.Series:
    """Bin a (lagged) VXN level into 0 low / 1 normal / 2 high.

    Uses the *corrected* bins of ``RULE_SPEC`` 1.9 -- the discussion's literal
    ``pd.cut(bins=[0,18,28,200])`` is right-closed and disagrees with the prose
    at 18 and 28 (``I05``).  NaN input stays NaN.
    """
    level = pd.to_numeric(vxn_level, errors="coerce")
    out = pd.Series(np.nan, index=level.index, dtype="float64")
    out[level < 18.0] = VXN_REGIME_LOW
    out[(level >= 18.0) & (level <= 28.0)] = VXN_REGIME_NORMAL
    out[level > 28.0] = VXN_REGIME_HIGH
    return out


def _wilder_atr(bars: pd.DataFrame, period: int = 14) -> np.ndarray:
    """Wilder ATR(14) over *closed* bars.

    Same convention as ``research/experiments/e1_rule_falsification.py``
    (``atr_wilder``): the first value appears at index ``period`` and is the
    simple mean of TR[1:period+1]; afterwards it is the Wilder RMA.  Values
    before the warm-up are NaN (``RULE_SPEC`` A03: no signal before the warm-up).
    """
    high = bars["high"].to_numpy(dtype="float64")
    low = bars["low"].to_numpy(dtype="float64")
    close = bars["close"].to_numpy(dtype="float64")
    n = len(bars)
    out = np.full(n, np.nan, dtype="float64")
    if n <= period:
        return out
    prev_close = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    tr[0] = high[0] - low[0]
    out[period] = tr[1 : period + 1].sum() / period
    for i in range(period + 1, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def _normalise_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Validate the market series and return it sorted by ``ts_event``."""
    _require_columns(bars, REQUIRED_BAR_COLUMNS, "bars")
    columns = list(REQUIRED_BAR_COLUMNS)
    if "volume" in bars.columns:
        columns.append("volume")
    out = bars.loc[:, columns].copy()
    out["ts_event"] = out["ts_event"].astype("int64")
    out = out.sort_values("ts_event", kind="stable").reset_index(drop=True)
    ts = out["ts_event"].to_numpy()
    if len(ts) > 1 and not np.all(np.diff(ts) > 0):
        raise ValueError("bars: ts_event must be strictly increasing (no duplicates)")
    return out


def _bar_interval_minutes(bars: pd.DataFrame) -> int:
    """Median bar spacing in minutes (rounded down, at least 1)."""
    ts = bars["ts_event"].to_numpy(dtype="int64")
    if len(ts) < 2:
        return DEFAULT_BAR_INTERVAL_MINUTES
    deltas = np.diff(ts)
    step_ns = int(np.median(deltas))
    minutes = max(1, int(round(step_ns / 60_000_000_000)))
    return minutes


# ---------------------------------------------------------------------------
# feature resolution
# ---------------------------------------------------------------------------
def resolve_feature_list(
    candidates: pd.DataFrame,
    *,
    extra_features: bool = False,
) -> tuple[list[str], list[str]]:
    """Split the declared feature universe into (used, excluded).

    A feature is **excluded** when its source column is absent from the
    candidate log, or when the column is entirely NaN (e.g. the vision columns,
    which cannot exist until the vision layer is built -- **D12**).  Excluded
    features are recorded in the artefact metadata; they are never silently
    imputed.
    """
    used: list[str] = []
    excluded: list[str] = []
    universe = list(FEATURE_LIST) + (list(EXTENSION_FEATURES) if extra_features else [])
    for name in universe:
        source = FEATURE_SOURCES.get(name)
        if source is None:
            # a computed feature that could not be computed (all-NaN, e.g. a
            # volume statistic on a series without volume) is excluded exactly
            # like a missing optional column
            if name in candidates.columns and candidates[name].isna().all():
                excluded.append(name)
                continue
            used.append(name)
            continue
        if source not in candidates.columns:
            excluded.append(name)
            continue
        column = candidates[source]
        if column.isna().all():
            excluded.append(name)
            continue
        used.append(name)
    return used, excluded


# ---------------------------------------------------------------------------
# feature construction
# ---------------------------------------------------------------------------
def candidate_consistency_report(candidates: pd.DataFrame) -> dict:
    """Check the log's own derived columns against the values recomputed here.

    Reports (never raises) how many candidates disagree with the definitions
    this module uses.  The recomputed value always wins inside
    ``build_features``; this report exists so that a mismatch is *visible*
    instead of silently overwritten.
    """
    report = {
        "minutes_from_us_open_mismatches": 0,
        "max_drift_minutes": 0.0,
        "vxn_regime_mismatches": 0,
    }
    if "minutes_from_us_open" in candidates.columns:
        computed = minutes_from_us_open(candidates["ts_event"].astype("int64"))
        logged = pd.to_numeric(candidates["minutes_from_us_open"], errors="coerce")
        both = logged.notna() & computed.notna()
        if bool(both.any()):
            drift = (logged[both] - computed[both]).abs()
            report["minutes_from_us_open_mismatches"] = int((drift > 1.0).sum())
            report["max_drift_minutes"] = float(drift.max())
    if "vxn_known" in candidates.columns:
        computed = vxn_regime_from_level(
            pd.to_numeric(candidates["vxn_known"], errors="coerce")
        )
        if "vxn_regime" in candidates.columns:
            logged = pd.to_numeric(candidates["vxn_regime"], errors="coerce")
        else:
            logged = pd.Series(np.nan, index=candidates.index)
        both = logged.notna() & computed.notna()
        if bool(both.any()):
            report["vxn_regime_mismatches"] = int(
                (~np.isclose(logged[both], computed[both])).sum()
            )
    return report


def build_features(
    candidates: pd.DataFrame,
    bars: pd.DataFrame | None = None,
    *,
    extra_features: bool = False,
    strict: bool = False,
) -> pd.DataFrame:
    """Turn a D2 candidate log (+ the market series) into a feature frame.

    Parameters
    ----------
    candidates:
        The D2 candidate log.  Required columns: ``ts_event`` (int64 ns),
        ``side``, ``entry_price``, ``stop_price``, ``target_price``, ``risk``.
        Optional columns are read when present (``vxn_known``, ``checklist_score``,
        ``smt_divergence``, ``bars_to_inversion``, ``minutes_from_us_open``,
        ``vision_confidence``, ``fvg_low``/``fvg_high``).
    bars:
        The market series, with ``ts_event`` (int64 ns) and OHLC.  Only needed
        for the extension features; every value used from it is the last bar
        that closed **at or before** ``ts_event`` (``merge_asof`` backwards).
    extra_features:
        Enable the causal extension features (off by default -- they are not
        part of the frozen L146 list).
    strict:
        When True, raise if the log's own ``minutes_from_us_open`` /
        ``vxn_regime`` disagree with the values recomputed here (a
        data-integrity violation).  When False (the default) the recomputed
        values win and the disagreement is reported by
        ``candidate_consistency_report``.

    Returns
    -------
    A copy of ``candidates`` with the feature columns added (or recomputed) and
    a ``feature_cutoff_ns`` column: the information cut-off used for that row.
    ``feature_cutoff_ns <= ts_event`` holds for every row -- that is the
    no-look-ahead invariant in machine-checkable form.
    """
    _require_columns(candidates, REQUIRED_CANDIDATE_COLUMNS, "candidates")
    out = candidates.copy()
    ts = out["ts_event"].astype("int64")

    # --- recomputed from ts_event (always available) ----------------------
    computed_open = minutes_from_us_open(ts)
    if "minutes_from_us_open" in out.columns and strict:
        logged = pd.to_numeric(out["minutes_from_us_open"], errors="coerce")
        both = logged.notna() & computed_open.notna()
        if both.any():
            drift = (logged[both] - computed_open[both]).abs().max()
            if drift > 1.0:
                raise ValueError(
                    "candidates.minutes_from_us_open disagrees with the value recomputed "
                    f"from ts_event (max drift {drift:.2f} min). Expected: signed minutes "
                    "from the same day's 09:30 America/New_York open."
                )
    out["minutes_from_us_open"] = computed_open

    # --- VXN level (lagged by construction, D2 'vxn_known') ---------------
    if "vxn_known" in out.columns:
        out["vxn_level"] = pd.to_numeric(out["vxn_known"], errors="coerce")
    else:
        out["vxn_level"] = np.nan

    # --- VXN regime, recomputed from the lagged level (RULE_SPEC 1.9) ----
    computed_regime = vxn_regime_from_level(out["vxn_level"])
    if "vxn_regime" in out.columns and strict:
        logged = pd.to_numeric(out["vxn_regime"], errors="coerce")
        both = logged.notna() & computed_regime.notna()
        if both.any() and not np.allclose(logged[both], computed_regime[both]):
            raise ValueError(
                "candidates.vxn_regime disagrees with the regime recomputed from the "
                "lagged vxn_known level. Expected bins (RULE_SPEC 1.9): <18 -> 0, "
                "[18,28] -> 1, >28 -> 2."
            )
    out["vxn_regime"] = computed_regime

    # --- feature cut-off --------------------------------------------------
    # Nothing outside the candidate's own row is consulted for the core
    # features, so the cut-off *is* ts_event.
    out["feature_cutoff_ns"] = ts

    # --- optional / extension features ------------------------------------
    if extra_features:
        if bars is None:
            raise ValueError("build_features(extra_features=True) requires the bars frame")
        out = _add_extension_features(out, bars)

    return out


def _add_extension_features(candidates: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """Attach the causal extension features (ATR context, volume z-score).

    Every value is taken from the last bar that closed at or before
    ``ts_event`` -- the merge is a backwards ``merge_asof``, so a future bar
    can never influence an earlier row.
    """
    b = _normalise_bars(bars)
    out = candidates.copy()

    atr = _wilder_atr(b)
    vol = b["volume"].to_numpy(dtype="float64") if "volume" in b.columns else None
    if vol is not None:
        mean60 = pd.Series(vol).rolling(60, min_periods=20).mean().to_numpy()
        std60 = pd.Series(vol).rolling(60, min_periods=20).std(ddof=0).to_numpy()
        z = np.divide(vol - mean60, std60, out=np.full_like(vol, np.nan), where=std60 > 0)
    else:
        z = np.full(len(b), np.nan)

    context = pd.DataFrame({"ts_event": b["ts_event"], "atr14": atr, "volume_zscore_60": z})
    context = context.sort_values("ts_event", kind="stable")

    left = out.loc[:, ["ts_event"]].copy()
    left["_row"] = np.arange(len(left))
    merged = pd.merge_asof(
        left.sort_values("ts_event", kind="stable"),
        context,
        on="ts_event",
        direction="backward",
    ).sort_values("_row", kind="stable")
    out["atr14"] = merged["atr14"].to_numpy()
    out["volume_zscore_60"] = merged["volume_zscore_60"].to_numpy()

    if "risk" in out.columns:
        out["risk_atr"] = out["risk"].astype("float64") / out["atr14"]
    else:
        out["risk_atr"] = np.nan
    if "fvg_low" in out.columns and "fvg_high" in out.columns:
        width = (out["fvg_high"].astype("float64") - out["fvg_low"].astype("float64")).abs()
        out["gap_atr"] = width / out["atr14"]
    else:
        out["gap_atr"] = np.nan

    out = _add_htf_features(out, bars)
    return out


# ---------------------------------------------------------------------------
# higher-timeframe / setup-quality block
# ---------------------------------------------------------------------------

#: The 1H swing a candidate's liquidity target is read from.  The backward scan
#: is bounded so the cost stays linear; 200 published swings is ~8 days of 1H.
HTF_PIVOT_LOOKBACK = 200
#: The rolling window for ``recent_same_side_wr`` and ``vxn_zscore``.
STATE_WINDOW = 20
VXN_WINDOW = 100


def _resample_ohlc(b: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """1-minute bars -> ``minutes`` buckets, published at the bucket's last close.

    A bucket is only usable once its **last** 1-minute bar has closed, so the
    publication timestamp is that bar's ``ts_event``.  The final bucket of the
    sample may be partial; it is still causal (its close exists) and is flagged
    by nothing more than being the last row.
    """
    step = minutes * 60 * 1_000_000_000
    bucket = (b["ts_event"].to_numpy(dtype="int64") // step)
    frame = pd.DataFrame({
        "bucket": bucket,
        "ts_event": b["ts_event"].to_numpy(dtype="int64"),
        "open": b["open"].to_numpy(dtype="float64"),
        "high": b["high"].to_numpy(dtype="float64"),
        "low": b["low"].to_numpy(dtype="float64"),
        "close": b["close"].to_numpy(dtype="float64"),
    })
    g = frame.groupby("bucket", sort=True)
    out = pd.DataFrame({
        "ts_event": g["ts_event"].max(),        # the bucket's last 1m close time
        "open": g["open"].first(),
        "high": g["high"].max(),
        "low": g["low"].min(),
        "close": g["close"].last(),
    }).sort_values("ts_event", kind="stable")
    return out


def _merge_backward(left_ts: np.ndarray, frame: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """``merge_asof`` backwards on ``ts_event`` -- a future bar can never leak in."""
    left = pd.DataFrame({"ts_event": left_ts})
    left["_row"] = np.arange(len(left))
    merged = pd.merge_asof(
        left.sort_values("ts_event", kind="stable"),
        frame.sort_values("ts_event", kind="stable")[["ts_event", *cols]],
        on="ts_event",
        direction="backward",
    ).sort_values("_row", kind="stable")
    return merged


def _resolution_bars(
    candidates: pd.DataFrame, b: pd.DataFrame, cap: int = 20_000
) -> np.ndarray:
    """The bar at which each candidate's trade resolved (-1 if it never did).

    Re-derived from the bars with the **first-touch** rule the engine uses (a
    tie on one bar counts as the stop).  This is what makes
    ``recent_same_side_wr`` provably causal: a past candidate's outcome may only
    be used once its own resolution bar is strictly before the current setup.

    A fixed embargo is not an option -- the measured maximum holding time on the
    NQ sample is **15,039 bars**, so a constant would either leak or discard most
    of the sample.

    The scan is chunked and capped at ``cap`` bars: the median hold is 9 bars, so
    the common case touches one 256-bar chunk.  A trade that would hold longer
    than ``cap`` is reported as unresolved, which only *removes* it from the
    feature's history -- it cannot leak.
    """
    low = b["low"].to_numpy(dtype="float64")
    high = b["high"].to_numpy(dtype="float64")
    nb = len(low)
    stop = candidates["stop_price"].to_numpy(dtype="float64")
    target = candidates["target_price"].to_numpy(dtype="float64")
    side = candidates["side"].to_numpy(dtype="int64")
    entry_bar = candidates["confirm_bar"].to_numpy(dtype="int64") + 1
    out = np.full(len(candidates), -1, dtype="int64")
    chunk = 256

    def first_true(k: int, end: int, s: float, t: float, sd: int, which: int) -> int:
        """First bar in [k, end) where the stop (which=0) or target (1) is touched."""
        while k < end:
            e = min(end, k + chunk)
            if which == 0:
                m = (low[k:e] <= s) if sd > 0 else (high[k:e] >= s)
            else:
                m = (high[k:e] >= t) if sd > 0 else (low[k:e] <= t)
            if m.any():
                return k + int(m.argmax())
            k = e
        return -1

    for i in range(len(candidates)):
        j = int(entry_bar[i])
        if j >= nb:
            continue
        end = min(nb, j + cap)
        ia = first_true(j, end, stop[i], target[i], int(side[i]), 0)
        ic = first_true(j, end, stop[i], target[i], int(side[i]), 1)
        if ia < 0 and ic < 0:
            continue
        out[i] = ia if (ic < 0 or (ia >= 0 and ia <= ic)) else ic
    return out


def _add_htf_features(candidates: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """Attach the higher-timeframe and setup-quality features.

    Every value comes from information that exists at or before ``ts_event``:
    a resampled bucket is used only from its last underlying 1-minute close
    onwards, a 1H swing only after its fractal is published, and a past
    candidate's outcome only after that trade has actually resolved.
    """
    from dodgys_dd_quant.strategy.constants import (
        KILLZONE_LONDON_ET, KILLZONE_NY_AM, KILLZONE_NY_PM,
    )
    from dodgys_dd_quant.strategy.structure import causal_pivots

    b = _normalise_bars(bars)
    out = candidates.copy()
    ts = out["ts_event"].to_numpy(dtype="int64")
    side = out["side"].to_numpy(dtype="int64") if "side" in out.columns else np.ones(len(out))

    # --- htf_bias_1h / htf_bias_15m -------------------------------------
    for minutes, name in ((60, "htf_bias_1h"), (15, "htf_bias_15m")):
        r = _resample_ohlc(b, minutes)
        r["bias"] = np.sign(r["close"].to_numpy() - r["open"].to_numpy())
        col = _merge_backward(ts, r, ["bias"])["bias"].to_numpy(dtype="float64")
        out[name] = col * side          # +1 => the HTF bar agrees with the trade

    # --- dist_to_htf_liquidity ------------------------------------------
    h1 = _resample_ohlc(b, 60)
    piv = causal_pivots(
        h1["high"].to_numpy(dtype="float64"), h1["low"].to_numpy(dtype="float64")
    )
    h1_ts = h1["ts_event"].to_numpy(dtype="int64")
    hi_known = h1_ts[piv.high_known] if len(piv.high_known) else np.empty(0, "int64")
    hi_price = h1["high"].to_numpy(dtype="float64")[piv.high_idx] if len(piv.high_idx) else np.empty(0)
    lo_known = h1_ts[piv.low_known] if len(piv.low_known) else np.empty(0, "int64")
    lo_price = h1["low"].to_numpy(dtype="float64")[piv.low_idx] if len(piv.low_idx) else np.empty(0)
    entry = out["entry_price"].to_numpy(dtype="float64") if "entry_price" in out.columns \
        else np.full(len(out), np.nan)
    atr = out["atr14"].to_numpy(dtype="float64") if "atr14" in out.columns \
        else np.full(len(out), np.nan)
    dist = np.full(len(out), np.nan)
    for i in range(len(out)):
        t = ts[i]
        # the pivots published before this setup
        if side[i] > 0:
            n = int(np.searchsorted(hi_known, t, side="left"))
            if n == 0:
                continue
            window = hi_price[max(0, n - HTF_PIVOT_LOOKBACK):n]
            cand_prices = window[window > entry[i]]     # the liquidity above
            if cand_prices.size:
                dist[i] = (cand_prices.min() - entry[i]) / atr[i]
        else:
            n = int(np.searchsorted(lo_known, t, side="left"))
            if n == 0:
                continue
            window = lo_price[max(0, n - HTF_PIVOT_LOOKBACK):n]
            cand_prices = window[window < entry[i]]     # the liquidity below
            if cand_prices.size:
                dist[i] = (entry[i] - cand_prices.max()) / atr[i]
    out["dist_to_htf_liquidity"] = dist

    # --- setup quality ---------------------------------------------------
    bti = out["bars_to_inversion"].to_numpy(dtype="float64") if "bars_to_inversion" in out.columns \
        else np.full(len(out), np.nan)
    out["inversion_speed"] = np.divide(1.0, bti, out=np.full_like(bti, np.nan), where=bti > 0)

    width = (out["fvg_high"].to_numpy(dtype="float64")
             - out["fvg_low"].to_numpy(dtype="float64")).__abs__() \
        if {"fvg_low", "fvg_high"} <= set(out.columns) else np.full(len(out), np.nan)
    risk = out["risk"].to_numpy(dtype="float64") if "risk" in out.columns \
        else np.full(len(out), np.nan)
    out["gap_quality"] = np.divide(width, risk, out=np.full_like(width, np.nan), where=risk > 0)

    # --- session_quality --------------------------------------------------
    et_minutes = _et_minute_of_day(ts)
    def _in(window: tuple[str, str]) -> np.ndarray:
        lo_h, lo_m = (int(x) for x in window[0].split(":"))
        hi_h, hi_m = (int(x) for x in window[1].split(":"))
        return (et_minutes >= lo_h * 60 + lo_m) & (et_minutes <= hi_h * 60 + hi_m)
    ny = _in(KILLZONE_NY_AM) | _in(KILLZONE_NY_PM)
    lon = _in(KILLZONE_LONDON_ET)
    out["session_quality"] = np.where(ny, 2, np.where(lon, 1, 0)).astype("float64")

    # --- recent_same_side_wr (strictly causal) ---------------------------
    out["recent_same_side_wr"] = _recent_same_side_wr(out, b)

    # --- vxn_zscore -------------------------------------------------------
    if "vxn_known" in out.columns:
        v = out["vxn_known"].astype("float64")
        past = v.shift(1)                      # strictly past rows only
        mean = past.rolling(VXN_WINDOW, min_periods=20).mean()
        std = past.rolling(VXN_WINDOW, min_periods=20).std(ddof=0)
        out["vxn_zscore"] = np.divide(v - mean, std, out=np.full(len(v), np.nan),
                                      where=(std.to_numpy() > 0))
    else:
        out["vxn_zscore"] = np.nan
    return out


def _et_minute_of_day(ts: np.ndarray) -> np.ndarray:
    """The Eastern-Time minute of the day for each ns timestamp."""
    stamp = pd.to_datetime(ts.astype("int64"), utc=True).tz_convert("America/New_York")
    return (stamp.hour * 60 + stamp.minute).to_numpy(dtype="int64")


def _recent_same_side_wr(candidates: pd.DataFrame, b: pd.DataFrame) -> np.ndarray:
    """Win rate of the recent same-side setups whose outcome is **already known**.

    Eligibility is ``exit_bar < confirm_bar`` of the current setup -- that past
    trade has actually resolved, so reading its label is causal.  Among the
    eligible ones the most recently **resolved** ``STATE_WINDOW`` are averaged.

    A fixed embargo cannot do this: the measured maximum holding time on the NQ
    sample is 15,039 bars, so any constant would either leak or throw away most
    of the sample.
    """
    import heapq

    if "label" not in candidates.columns or "confirm_bar" not in candidates.columns:
        return np.full(len(candidates), np.nan)
    if not pd.api.types.is_numeric_dtype(candidates["label"]):
        # a caller that did not carry the outcome (the D2 table does) cannot
        # have this feature -- return the "unknown" value rather than guessing
        return np.full(len(candidates), np.nan)
    exit_bar = _resolution_bars(candidates, b)
    cb = candidates["confirm_bar"].to_numpy(dtype="int64")
    side = candidates["side"].to_numpy(dtype="int64")
    label = candidates["label"].to_numpy(dtype="int64")
    out = np.full(len(candidates), np.nan, dtype="float64")
    heaps: dict[int, list[tuple[int, int]]] = {1: [], -1: []}
    recent: dict[int, list[int]] = {1: [], -1: []}
    cursor = 0
    for i in range(len(candidates)):
        while cursor < i:                    # every earlier setup is now "past"
            ps = int(side[cursor])
            if exit_bar[cursor] >= 0:
                heapq.heappush(heaps[ps], (int(exit_bar[cursor]), int(label[cursor])))
            cursor += 1
        s_i = int(side[i])
        while heaps[s_i] and heaps[s_i][0][0] < cb[i]:
            _, lab = heapq.heappop(heaps[s_i])
            recent[s_i].append(lab)
            if len(recent[s_i]) > STATE_WINDOW:
                recent[s_i].pop(0)
        if recent[s_i]:
            vals = [v for v in recent[s_i] if v >= 0]
            if vals:
                out[i] = float(np.mean(vals))
    return out


# ---------------------------------------------------------------------------
# look-ahead proof
# ---------------------------------------------------------------------------
def _perturb_future(bars: pd.DataFrame, from_ts: int) -> pd.DataFrame:
    """Return a copy of ``bars`` whose rows at/after ``from_ts`` are wrecked.

    The perturbation multiplies OHLC by a large factor and sets the volume to
    a different value, so *any* feature that leaks a future price changes.
    """
    out = bars.copy()
    mask = out["ts_event"].astype("int64") >= from_ts
    for column in ("open", "high", "low", "close"):
        if column in out.columns:
            out.loc[mask, column] = out.loc[mask, column].astype("float64") * 3.0 + 11.0
    if "volume" in out.columns:
        out.loc[mask, "volume"] = out.loc[mask, "volume"].astype("float64") * 7.0
    return out


def assert_no_lookahead(
    candidates: pd.DataFrame,
    features: pd.DataFrame,
    *,
    bars: pd.DataFrame | None = None,
    perturb_from: int | None = None,
    feature_columns: Iterable[str] | None = None,
    extra_features: bool = False,
) -> None:
    """Assert that no feature uses information dated after ``ts_event``.

    Two layers of proof:

    1. **Static** -- every row's information cut-off (``feature_cutoff_ns``) is
       at or before its ``ts_event``; the frame is row-aligned with the
       candidate log; no undeclared feature column is present.
    2. **Dynamic** -- when ``bars`` and ``perturb_from`` are given, the features
       are re-derived from a market series whose *future* has been wrecked.  The
       rows whose ``ts_event`` precedes the perturbation must be bit-identical.
       A feature that leaked the future would change, and the assertion fires.

    Raises ``AssertionError`` on any violation.
    """
    assert len(features) == len(candidates), (
        f"features/candidates length mismatch: {len(features)} != {len(candidates)}"
    )
    assert "feature_cutoff_ns" in features.columns, "features lack 'feature_cutoff_ns'"
    assert "ts_event" in features.columns, "features lack 'ts_event'"

    ts = features["ts_event"].astype("int64").to_numpy()
    cutoff = features["feature_cutoff_ns"].astype("int64").to_numpy()
    bad = np.nonzero(cutoff > ts)[0]
    assert bad.size == 0, (
        f"{bad.size} row(s) use information dated after ts_event "
        f"(first offending row index {int(bad[0])})"
    )

    cand_ts = candidates["ts_event"].astype("int64").to_numpy()
    assert np.array_equal(ts, cand_ts), "features are not row-aligned with candidates"

    # A column that is neither a candidate column nor a declared feature is a
    # smuggling route for a look-ahead: the trainer would have no way to know
    # where it came from.
    allowed = set(candidates.columns) | set(FEATURE_SOURCES) | {"feature_cutoff_ns"}
    unknown = set(features.columns) - allowed
    assert not unknown, (
        f"undeclared column(s) in the features frame: {sorted(unknown)}. Only the D2 "
        "candidate columns and the declared features may appear."
    )
    if feature_columns is not None:
        declared = set(feature_columns)
        present = {c for c in features.columns if c in set(FEATURE_SOURCES)}
        undeclared = present - declared
        assert not undeclared, f"undeclared feature column(s) present: {sorted(undeclared)}"

    if bars is None or perturb_from is None:
        return

    perturbed = _perturb_future(bars, int(perturb_from))
    recomputed = build_features(candidates, perturbed, extra_features=extra_features)
    columns = [c for c in FEATURE_SOURCES if c in features.columns and c in recomputed.columns]
    if not columns:
        return
    before = ts < int(perturb_from)
    if not before.any():
        return
    left = features.loc[before, columns].to_numpy(dtype="float64")
    right = recomputed.loc[before, columns].to_numpy(dtype="float64")
    if not np.allclose(left, right, rtol=0.0, atol=0.0, equal_nan=True):
        differing = [
            c
            for c, a, b in zip(columns, left.T, right.T)
            if not np.array_equal(a, b, equal_nan=True)
        ]
        raise AssertionError(
            "look-ahead detected: feature(s) "
            f"{differing} changed when the market data after ts={int(perturb_from)} was "
            "modified. A feature must not depend on the future."
        )
