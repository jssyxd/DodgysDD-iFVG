"""The DodgysDD iFVG rule engine.

A **pure function of the bar history**: no I/O, no engine calls, no clock.  It
emits the D2 candidate log (every candidate, including losers — nothing is ever
erased, ``AGENTS.md`` "Signal integrity").

Provenance
----------
The engine implements two rule families that are **never merged** (L2 §E.2):

``CODE``
    what the reference replica actually implements (``pine:L###``).  This is the
    **baseline**.
``DOC``
    what the design discussion describes (``iFVG几个模型的讨论.txt``).  Every
    DOC-only rule is an **arm**, added one at a time, and never presented as
    code-verified.

Bar semantics (the single most important convention)
-----------------------------------------------------
A candidate's **confirmation candle** is the bar whose *body close* penetrated
the far edge of the gap.  The signal is knowable at that bar's close; the
honest fill is the **open of the next bar**.  The reference instead draws the
setup one bar later and prices it at the confirmation close (``pine:L437``,
``pine:L441``) — that fiction is available as ``entry_fill="confirm_close"``
and is reported separately, never silently.

The reference evaluates its trigger on bar ``X`` using ``close[X-1]``; in
closed-bar terms the confirmation candle is ``X-1``.  The confirmation-candle
**age** is measured against the gap's **newest** candle, so the code-derived
window is ``[1, 15]`` — age 0 is arithmetically impossible (L2 §A.5).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable

import numpy as np

from dodgys_dd_quant.strategy.constants import (
    CHECKLIST_WEIGHTS,
    DECISION_THRESHOLD,
    DEFAULT_RR,
    DOC_INVERSION_MAX_BARS,
    DOC_INVERSION_MIN_BARS,
    EQUAL_LEVEL_ATR_TOL,
    GRADE_THRESHOLDS,
    INVERSION_MAX_BARS,
    INVERSION_MIN_BARS,
    US_OPEN_MINUTES,
    KILLZONE_NY_AM,
    KILLZONE_NY_PM,
    LIQUIDITY_TARGET_MIN_R,
    MIN_GAP_ATR_MULT,
    NY_TZ,
    SWING_FRACTAL,
    SWING_RIGHT_BARS,
)
from dodgys_dd_quant.strategy.structure import (
    Bars,
    PivotLevels,
    SweepDetector,
    SweepEvent,
    atr_wilder,
    causal_pivots,
    detect_fvg,
    local_minutes_of_day,
    session_extremes,
)

__all__ = [
    "RuleConfig",
    "Candidate",
    "CandidateLog",
    "run_state_machine",
    "PRESETS",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleConfig:
    """Every switch of the rule engine.

    The defaults are the **code-derived baseline** (the reference replica's
    behaviour).  The ATR floor is *off* by default because the reference has no
    ATR filter at all; the doc's floor is an arm.
    """

    symbol: str = "BTCUSDT"
    timeframe: str = "1m"

    # --- inversion window -------------------------------------------------
    inversion_min_bars: int = INVERSION_MIN_BARS
    inversion_max_bars: int = INVERSION_MAX_BARS

    # --- gap filter -------------------------------------------------------
    #: ``None`` disables the floor (the reference has no ATR filter at all).
    min_gap_atr_mult: float | None = None

    # --- sweep gate -------------------------------------------------------
    #: The reference's ``onlyShowSweptIFVG`` defaults to **false**; the doc
    #: makes the sweep a mandatory precondition.
    require_sweep: bool = False
    #: The doc's sweep semantics: the wick pierces the level **and** the body
    #: closes back inside.  The reference only tests the wick (``pine:L567``).
    sweep_requires_body_reclaim: bool = True
    #: The reference consumes a swept level exactly once (``pine:L560-575``).
    sweep_consumes_levels: bool = True

    # --- stop -------------------------------------------------------------
    #: ``"wick"`` (reference default), ``"body"``, ``"ifvg"`` (reference
    #: options) or ``"swing"`` (the doc's "beyond the recent swing").
    stop_placement: str = "wick"
    #: ``"confirm"`` scans ``[gap_newest, confirmation_bar]`` (no look-ahead);
    #: ``"confirm_plus_one"`` additionally includes the fill bar, which is what
    #: the reference (and E-1) do — the stop then depends on the very bar the
    #: position is entered on.
    stop_window: str = "confirm"

    # --- entry ------------------------------------------------------------
    #: ``"next_open"`` (honest: fill at the open of the bar after the
    #: confirmation candle) or ``"confirm_close"`` (the reference's fiction).
    entry_fill: str = "next_open"

    # --- risk -------------------------------------------------------------
    rr: float = DEFAULT_RR
    #: The stop is moved away from the entry by this factor.  A trade costs a
    #: fixed number of dollars, so a wider stop lowers the cost **in R** — the
    #: only lever that touches the cost ratio directly.
    stop_mult: float = 1.0

    # --- context gates ----------------------------------------------------
    #: The doc's killzone is a hard gate; the reference's sessions gate alerts
    #: only, so the default is **off** (parity with the code).
    killzone_gate: bool = False
    killzones: tuple[tuple[str, str, str], ...] = (
        ("America/New_York", *KILLZONE_NY_AM),
        ("America/New_York", *KILLZONE_NY_PM),
    )
    #: The reference's ``requireBEIntact`` gate (default **on** there).
    require_be_intact: bool = False

    # --- candidate generation --------------------------------------------
    #: ``False`` = scan every three-candle gap (the E-1 code-derived core).
    #: ``True``  = the reference's leg tracker: at most one live candidate per
    #: direction inside a swing leg.
    leg_tracker: bool = False

    # --- portfolio --------------------------------------------------------
    #: ``"drop"`` = a signal blocked by an open position is discarded (L2's
    #: recommendation for a portfolio); ``"defer"`` = the reference/E-1
    #: behaviour, where the candidate stays pending and may trigger later at a
    #: different price.
    portfolio_mode: str = "drop"

    # --- direction --------------------------------------------------------
    #: ``"neutral"``, ``"bullish"`` (long only) or ``"bearish"`` (short only).
    bias: str = "neutral"

    # --- meta-label -------------------------------------------------------
    decision_threshold: float = DECISION_THRESHOLD

    # --- references -------------------------------------------------------
    #: Symbol of the SMT reference instrument; ``None`` disables the check and
    #: records ``smt_divergence = -1`` (never guesses).
    smt_reference_symbol: str | None = None

    # --- session bookkeeping ---------------------------------------------
    #: Timezone used for the PDH/PDL day boundary and the killzone tests.
    session_timezone: str = NY_TZ

    def with_doc_window(self) -> "RuleConfig":
        """The doc-derived inversion band ``(7, 15)``."""
        return replace(
            self,
            inversion_min_bars=DOC_INVERSION_MIN_BARS,
            inversion_max_bars=DOC_INVERSION_MAX_BARS,
        )

    def with_code_window(self) -> "RuleConfig":
        """The code-derived inversion band ``(1, 15)``."""
        return replace(
            self,
            inversion_min_bars=INVERSION_MIN_BARS,
            inversion_max_bars=INVERSION_MAX_BARS,
        )


#: Named presets.  ``e1`` reproduces the D4 baseline semantics exactly (the
#: experiment harness), ``honest`` removes the reference's look-ahead, ``pine``
#: adds the reference's leg machinery and ``doc`` adds the doc's filters.
PRESETS: dict[str, RuleConfig] = {
    # Exactly the semantics of research/experiments/e1_rule_falsification.py's
    # ``code[0,15] / code:none / honest:open(k+1) / code:off`` arm.
    "e1": RuleConfig(
        min_gap_atr_mult=None,
        stop_window="confirm_plus_one",
        entry_fill="next_open",
        portfolio_mode="defer",
        require_sweep=False,
    ),
    # The same signal set, but with the reference's look-ahead removed.
    "honest": RuleConfig(
        min_gap_atr_mult=None,
        stop_window="confirm",
        entry_fill="next_open",
        portfolio_mode="drop",
        require_sweep=False,
    ),
    # Reference-faithful additions: the leg tracker and the BE-intact gate.
    "pine": RuleConfig(
        min_gap_atr_mult=None,
        stop_window="confirm",
        entry_fill="next_open",
        portfolio_mode="drop",
        require_sweep=False,
        leg_tracker=True,
        require_be_intact=True,
    ),
    # The doc's rules: ATR floor, sweep precondition, killzone.
    "doc": RuleConfig(
        min_gap_atr_mult=MIN_GAP_ATR_MULT,
        stop_window="confirm",
        entry_fill="next_open",
        portfolio_mode="drop",
        require_sweep=True,
        killzone_gate=True,
    ),
    # Ablations of the reference-faithful arm: each keeps one of its two
    # reference features so the contribution of each can be measured.
    "pine_leg": RuleConfig(
        min_gap_atr_mult=None,
        stop_window="confirm",
        entry_fill="next_open",
        portfolio_mode="drop",
        require_sweep=False,
        leg_tracker=True,
        require_be_intact=False,
    ),
    "pine_be": RuleConfig(
        min_gap_atr_mult=None,
        stop_window="confirm",
        entry_fill="next_open",
        portfolio_mode="drop",
        require_sweep=False,
        leg_tracker=False,
        require_be_intact=True,
    ),
}


# ---------------------------------------------------------------------------
# Candidate
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Candidate:
    """One iFVG setup: from the gap's formation to its outcome.

    Every candidate is kept, including the ones that never trigger, the ones
    that are dropped by the portfolio and the losers.  Erasing them is the
    upstream indicator's ``hideLosing`` behaviour and is banned (``AGENTS.md``).
    """

    ts_event: int = 0          # close time of the confirmation bar (ns)
    fvg_oldest: int = 0
    fvg_newest: int = 0
    confirm_bar: int = 0
    side: int = 0              # +1 long, -1 short
    fvg_type: int = 0          # +1 bullish gap (support), -1 bearish gap
    entry_bar: int = 0
    entry_price: float = 0.0
    stop_price: float = 0.0
    target_price: float = 0.0
    risk: float = 0.0
    fvg_low: float = 0.0
    fvg_high: float = 0.0
    far_edge: float = 0.0      # the edge the body close must penetrate
    bars_to_inversion: int = 0
    minutes_from_us_open: int = 0
    checklist_score: float = 0.0
    #: How many of the checklist's conditions could actually be **decided**
    #: for this candidate.  ``smt_divergence`` is undecidable where the
    #: reference instrument does not cover the window and the VXN regime is
    #: undecidable when no regime series is attached; the vision condition is
    #: never decidable because the layer does not exist (D12).
    checklist_known: int = 0
    checklist_flags: dict[str, bool] = field(default_factory=dict)
    smt_divergence: int = -1
    sweep_detected: int = 0
    vxn_known: float = float("nan")
    vxn_regime: int = -1
    origin_bar: int = -1
    origin_price: float = float("nan")
    outcome: str = "open"      # "stop" | "target" | "open" | "expired" | "discarded"
    r_multiple: float = float("nan")
    exit_bar: int = -1
    p_win: float = float("nan")

    @property
    def is_closed(self) -> bool:
        return self.outcome in ("stop", "target")

    @property
    def grade(self) -> str:
        """The doc's rubric label.  **Reported, never used as a filter** (D8)."""
        score = sum(CHECKLIST_WEIGHTS.get(k, 0.0) for k, v in self.checklist_flags.items() if v)
        for name, threshold in GRADE_THRESHOLDS:
            if score >= threshold:
                return name
        return "C"


# ---------------------------------------------------------------------------
# The log
# ---------------------------------------------------------------------------


@dataclass
class CandidateLog:
    """The D2 candidate log.

    The schema is **frozen** (``.herd-swarm/decisions.md`` D2) and is written
    verbatim, column for column, in the documented order.
    """

    candidates: list[Candidate]
    symbol: str
    timeframe: str

    D2_COLUMNS: tuple[str, ...] = (
        "ts_event",
        "symbol",
        "side",
        "entry_price",
        "stop_price",
        "target_price",
        "risk",
        "fvg_low",
        "fvg_high",
        "fvg_bar1",
        "fvg_bar3",
        "confirm_bar",
        "bars_to_inversion",
        "minutes_from_us_open",
        "checklist_score",
        "smt_divergence",
        "sweep_detected",
        "vxn_known",
        "vxn_regime",
        "vision_iou",
        "vision_confidence",
        "label",
        "r_multiple",
    )

    def __len__(self) -> int:
        return len(self.candidates)

    def __iter__(self) -> Iterable[Candidate]:
        return iter(self.candidates)

    def to_table(self) -> dict[str, np.ndarray]:
        """Build the D2 columns as numpy arrays (one entry per candidate)."""
        n = len(self.candidates)
        if n == 0:
            return {c: np.empty(0) for c in self.D2_COLUMNS}

        cands = self.candidates
        label = np.array(
            [1 if c.outcome == "target" else (0 if c.outcome == "stop" else -1) for c in cands],
            dtype=np.int8,
        )
        return {
            "ts_event": np.array([c.ts_event for c in cands], dtype=np.int64),
            "symbol": np.array([self.symbol] * n, dtype=object),
            "side": np.array([c.side for c in cands], dtype=np.int8),
            "entry_price": np.array([c.entry_price for c in cands], dtype=np.float64),
            "stop_price": np.array([c.stop_price for c in cands], dtype=np.float64),
            "target_price": np.array([c.target_price for c in cands], dtype=np.float64),
            "risk": np.array([c.risk for c in cands], dtype=np.float64),
            "fvg_low": np.array([c.fvg_low for c in cands], dtype=np.float64),
            "fvg_high": np.array([c.fvg_high for c in cands], dtype=np.float64),
            "fvg_bar1": np.array([c.fvg_oldest for c in cands], dtype=np.int64),
            "fvg_bar3": np.array([c.fvg_newest for c in cands], dtype=np.int64),
            "confirm_bar": np.array([c.confirm_bar for c in cands], dtype=np.int64),
            "bars_to_inversion": np.array([c.bars_to_inversion for c in cands], dtype=np.int32),
            "minutes_from_us_open": np.array(
                [c.minutes_from_us_open for c in cands], dtype=np.int32
            ),
            "checklist_score": np.array([c.checklist_score for c in cands], dtype=np.float64),
            "smt_divergence": np.array([c.smt_divergence for c in cands], dtype=np.int8),
            "sweep_detected": np.array([c.sweep_detected for c in cands], dtype=np.int8),
            "vxn_known": np.array([c.vxn_known for c in cands], dtype=np.float64),
            "vxn_regime": np.array([c.vxn_regime for c in cands], dtype=np.int8),
            # The vision layer does not exist (D12); the columns stay in the
            # schema and are filled with NaN.
            "vision_iou": np.full(n, np.nan, dtype=np.float64),
            "vision_confidence": np.full(n, np.nan, dtype=np.float64),
            "label": label,
            "r_multiple": np.array([c.r_multiple for c in cands], dtype=np.float64),
        }

    def write_parquet(self, path: str | Path) -> Path:
        """Write the D2 log to a parquet file (Zstd-7, per the lake contract)."""
        import pyarrow as pa
        import pyarrow.parquet as pq

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.table(self.to_table())
        pq.write_table(table, path, compression="zstd", compression_level=7)
        return path


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def run_state_machine(
    bars: Bars,
    config: RuleConfig | None = None,
    *,
    regime=None,
    reference: Bars | None = None,
) -> CandidateLog:
    """Run the rule engine over ``bars`` and return the D2 candidate log.

    Parameters
    ----------
    bars:
        Closed bars of the traded instrument.
    config:
        Rule configuration; defaults to the code-derived baseline.
    regime:
        Optional regime index exposing ``value_at(ts_ns) -> (vxn_known, regime)``.
    reference:
        Optional time-aligned series of the SMT reference instrument.
    """
    config = config or RuleConfig()
    n = len(bars)
    if n < 3:
        return CandidateLog([], config.symbol, config.timeframe)

    atr = atr_wilder(bars.high, bars.low, bars.close)
    fvgs = detect_fvg(bars, atr, config.min_gap_atr_mult)
    pivots = causal_pivots(bars.high, bars.low, left=SWING_FRACTAL - 1, right=SWING_RIGHT_BARS)
    origins = _origin_series(bars, pivots)

    minutes = local_minutes_of_day(bars.close_ts(), config.session_timezone)
    extremes = session_extremes(bars.ts, bars.high, bars.low, config.session_timezone)
    sweeps = _sweep_events(bars, pivots, config)
    sweep_flags = np.zeros(n, dtype=bool)
    for ev in sweeps:
        sweep_flags[ev.bar] = True

    # The bar gate (the doc's killzone and the sweep precondition) applies to
    # **both** scanning paths.  It used to be built only for the vectorised
    # scanner, so ``killzone_gate`` was silently ignored by the leg tracker
    # and the doc's session rule had no effect on the reference-faithful arm.
    gate = _bar_gates(config, minutes, sweep_flags)
    if config.leg_tracker:
        confirmations = _leg_confirmations(bars, fvgs, config, sweep_flags, pivots, gate)
    else:
        confirmations = _scan_confirmations(bars, fvgs, config, gate)

    candidates = _build_candidates(
        bars, fvgs, confirmations, config, origins, minutes, extremes, sweep_flags,
        pivots,
    )
    _attach_checklist(candidates, bars, pivots, extremes, atr, config)
    _attach_smt(candidates, bars, reference, config)
    _attach_regime(candidates, bars, regime)
    _score_checklist(candidates)
    _resolve_outcomes(candidates, bars, config)
    return CandidateLog(candidates, config.symbol, config.timeframe)


# ---------------------------------------------------------------------------
# Confirmation detection
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Confirmation:
    """A confirmed setup: the gap and the bar whose close confirmed it."""

    fvg_index: int
    confirm_bar: int


def _scan_confirmations(
    bars: Bars,
    fvgs,
    config: RuleConfig,
    gate: np.ndarray,
) -> list[_Confirmation]:
    """Find the first confirmation of every gap (the code-derived scanner).

    For a gap with newest candle ``c`` the confirmation candle lies in
    ``[c + min_age, c + max_age]`` and the trigger is a **body close strictly
    beyond the far edge**: ``close < gap_low`` for a bullish gap (a short) and
    ``close > gap_high`` for a bearish gap (a long).

    The search is vectorised over the candidates and never looks at a bar
    before the confirmation candle.
    """
    n = len(bars)
    n_fvg = len(fvgs)
    if n_fvg == 0:
        return []

    min_age = max(0, config.inversion_min_bars)
    max_age = max(min_age, config.inversion_max_bars)
    width = max_age - min_age + 1

    lo = fvgs.newest + min_age
    hi = np.minimum(fvgs.newest + max_age, n - 1)
    valid = lo <= hi
    if not valid.any():
        return []
    lo = lo[valid]
    hi = hi[valid]
    idx = np.flatnonzero(valid)

    # pad the tail with NaN so that a truncated age window never triggers
    # (NaN compares False against every threshold)
    close = np.concatenate([bars.close, np.full(max(0, width - 1), np.nan)])
    win = np.lib.stride_tricks.sliding_window_view(close, width)
    out: list[_Confirmation] = []
    chunk = 100_000
    for start in range(0, lo.shape[0], chunk):
        stop = min(start + chunk, lo.shape[0])
        rows = win[lo[start:stop]]                      # (m, width)
        is_bull = fvgs.fvg_type[idx[start:stop]] > 0
        beyond = np.where(
            is_bull[:, None],
            rows < fvgs.gap_low[idx[start:stop]][:, None],
            rows > fvgs.gap_high[idx[start:stop]][:, None],
        )
        # a candidate may only be confirmed inside its own age window
        cols = np.arange(width)[None, :]
        age_ok = (lo[start:stop, None] + cols) <= hi[start:stop, None]
        beyond &= age_ok
        has = beyond.any(axis=1)
        first = beyond.argmax(axis=1)
        conf = lo[start:stop] + first
        gate_ok = gate[conf]
        for j in np.flatnonzero(has & gate_ok):
            out.append(_Confirmation(fvg_index=int(idx[start + j]), confirm_bar=int(conf[j])))
    out.sort(key=lambda c: c.confirm_bar)
    return out


def _pivot_track(
    idx: np.ndarray, known: np.ndarray, price_src: np.ndarray, n: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The causal swing pivot of one direction, in force at every bar.

    Returns ``(origin_bar, origin_price, is_new)``: the bar index and price of
    the most recent pivot that was already *knowable* at each bar, and a flag
    that marks the bar on which a new pivot became known.

    A pivot at bar ``p`` is only knowable at bar ``p + SWING_RIGHT_BARS`` (see
    :func:`causal_pivots`), so the track never looks ahead.
    """
    origin_bar = np.full(n, -1, dtype=np.int64)
    origin_price = np.full(n, np.nan, dtype=np.float64)
    is_new = np.zeros(n, dtype=bool)
    if idx.shape[0]:
        pos = np.searchsorted(known, np.arange(n), side="right") - 1
        ok = pos >= 0
        origin_bar[ok] = idx[pos[ok]]
        origin_price[ok] = price_src[idx[pos[ok]]]
        conf = known[known < n]
        is_new[conf] = True
    return origin_bar, origin_price, is_new


def _leg_confirmations(
    bars: Bars,
    fvgs,
    config: RuleConfig,
    sweep_flags: np.ndarray,
    pivots: PivotLevels,
    gate: np.ndarray | None = None,
) -> list[_Confirmation]:
    """The reference's leg tracker (R1-R5): one live candidate per direction.

    A gap may only be created inside a swing leg and only while the leg is not
    frozen; at most one candidate per direction is live and the *worse* gap is
    discarded (the reference's ``Single`` arbitration, ``pine:L383-403``).

    This path is a per-bar walk, exactly like the reference, and is therefore
    markedly slower than the vectorised scanner.  The reference's ``Series``
    mode (merging consecutive gaps into one growing zone) is **not**
    implemented; only ``Single`` is supported.

    The leg boundaries are the module's own **fractal** pivots
    (:func:`causal_pivots`), the same definition the origin tracker uses.  An
    earlier revision used a 3-bar rolling minimum as the "pivot", which fires
    on roughly a third of all bars: the live gap was then discarded long
    before it could reach the 7-bar minimum inversion age, and the whole
    reference-faithful arm collapsed to a single trade over ten years.
    """
    n = len(bars)
    high_l = bars.high.tolist()
    low_l = bars.low.tolist()
    close_l = bars.close.tolist()

    low_bar, low_price, low_new = _pivot_track(
        pivots.low_idx, pivots.low_known, bars.low, n
    )
    high_bar, high_price, high_new = _pivot_track(
        pivots.high_idx, pivots.high_known, bars.high, n
    )

    # at most one gap per bar (the geometry is strict and mutually exclusive)
    fvg_at = np.full(n, -1, dtype=np.int64)
    fvg_type_at = np.zeros(n, dtype=np.int8)
    for i in range(len(fvgs)):
        c = int(fvgs.newest[i])
        fvg_at[c] = i
        fvg_type_at[c] = int(fvgs.fvg_type[i])

    out: list[_Confirmation] = []
    min_age = max(0, config.inversion_min_bars)
    max_age = max(min_age, config.inversion_max_bars)

    for fvg_type in (1, -1):
        # the leg's origin is the swing pivot of the same sense as the gap:
        # a bullish gap starts at a swing low, a bearish gap at a swing high.
        # The opposing pivot freezes the leg until its price is taken out.
        if fvg_type > 0:
            orig_bar_arr, orig_price_arr, orig_new = low_bar, low_price, low_new
            opp_price_arr, opp_new = high_price, high_new
        else:
            orig_bar_arr, orig_price_arr, orig_new = high_bar, high_price, high_new
            opp_price_arr, opp_new = low_price, low_new

        origin_bar = -1
        origin_price = math.nan
        frozen = False
        frozen_price = math.nan
        freeze_bar = -1
        live = -1            # index of the live gap
        confirmed = False    # the live gap already triggered

        for k in range(3, n):
            c = k - 1
            a = k - 3

            # --- the leg's own pivot resets the state -----------------------
            # the pivot fires when a *fractal* swing pivot of the origin sense
            # becomes knowable (bar p + SWING_RIGHT_BARS)
            if orig_new[k]:
                origin_bar = int(orig_bar_arr[k])
                origin_price = float(orig_price_arr[k])
                frozen = False
                frozen_price = math.nan
                freeze_bar = -1
                live = -1
                confirmed = False
            else:
                if frozen:
                    broke = (
                        high_l[k - 1] > frozen_price
                        if fvg_type > 0
                        else low_l[k - 1] < frozen_price
                    )
                    if broke:
                        frozen = False

                # --- gap creation ------------------------------------------
                if (
                    origin_bar >= 0
                    and a >= origin_bar - 1
                    and (not frozen or k == freeze_bar + 1)
                ):
                    i = fvg_at[c]
                    if i >= 0 and fvg_type_at[c] == fvg_type:
                        if live < 0:
                            live = i
                            confirmed = False
                        elif not confirmed:
                            # the reference keeps the better gap and deletes
                            # the other one; a confirmed candidate is never
                            # replaced (``pine:L390``)
                            better = (
                                fvgs.gap_high[i] > fvgs.gap_high[live]
                                if fvg_type > 0
                                else fvgs.gap_low[i] < fvgs.gap_low[live]
                            )
                            if better:
                                live = i

                # --- trigger test ------------------------------------------
                # The bar gate applies to the **confirmation bar**, exactly as
                # in the vectorised scanner: the doc's killzone and the sweep
                # precondition decide whether a setup may be taken.
                if live >= 0 and not confirmed and (gate is None or gate[c]):
                    age = c - int(fvgs.newest[live])
                    if min_age <= age <= max_age:
                        far = (
                            float(fvgs.gap_low[live])
                            if fvg_type > 0
                            else float(fvgs.gap_high[live])
                        )
                        triggered = (
                            close_l[c] < far if fvg_type > 0 else close_l[c] > far
                        )
                        if triggered:
                            confirmed = True
                            out.append(_Confirmation(fvg_index=int(live), confirm_bar=c))

            if not frozen and opp_new[k]:
                frozen = True
                frozen_price = float(opp_price_arr[k])
                freeze_bar = k

    out.sort(key=lambda x: x.confirm_bar)
    return out


# ---------------------------------------------------------------------------
# Origin tracker (swing origin -> break-even level)
# ---------------------------------------------------------------------------


def _origin_series(bars: Bars, pivots: PivotLevels) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    """The causal swing origin in force at every bar, per direction.

    ``+1`` is the bullish-gap tracker (its origin is a **swing low**), ``-1``
    the bearish-gap tracker (origin = swing high).  The origin price is the
    swing extreme itself, which is the level the reference uses as the
    **break-even** price (``pine:L476``).

    L2 §E-1 records that the reference's own origin sits **one bar before** the
    extreme (``originBar = bar_index - 1``); the two readings are reconciled
    here by using the extreme itself, which is the only reading under which the
    break-even level is a swing level at all.
    """
    n = len(bars)
    out: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for direction, (idx, known, price_src) in {
        1: (pivots.low_idx, pivots.low_known, bars.low),
        -1: (pivots.high_idx, pivots.high_known, bars.high),
    }.items():
        origin_bar = np.full(n, -1, dtype=np.int64)
        origin_price = np.full(n, np.nan, dtype=np.float64)
        if idx.shape[0]:
            pos = np.searchsorted(known, np.arange(n), side="right") - 1
            ok = pos >= 0
            origin_bar[ok] = idx[pos[ok]]
            origin_price[ok] = price_src[idx[pos[ok]]]
        out[direction] = (origin_bar, origin_price)
    return out


# ---------------------------------------------------------------------------
# Bar gates
# ---------------------------------------------------------------------------


def _bar_gates(config: RuleConfig, minutes: np.ndarray, sweep_flags: np.ndarray) -> np.ndarray:
    """Per-bar admissibility of a confirmation candle.

    Combines the doc's killzone gate (off by default, parity with the code)
    and the sweep precondition.
    """
    gate = np.ones(minutes.shape[0], dtype=bool)
    if config.killzone_gate and config.killzones:
        ok = np.zeros(minutes.shape[0], dtype=bool)
        for _tz, start, end in config.killzones:
            lo = _hhmm_to_minutes(start)
            hi = _hhmm_to_minutes(end)
            ok |= (minutes >= lo) & (minutes <= hi)
        gate &= ok
    if config.require_sweep:
        gate &= sweep_flags
    return gate


def _hhmm_to_minutes(text: str) -> int:
    hh, mm = text.split(":")
    return int(hh) * 60 + int(mm)


def _sweep_events(bars: Bars, pivots: PivotLevels, config: RuleConfig) -> list[SweepEvent]:
    """Every liquidity sweep, with the reference's one-shot level consumption.

    A level becomes usable one bar after it is published: the swing is known at
    the close of the confirming bar and the sweep test uses the bar's own
    high/low, which is only complete at that bar's close.
    """
    n = len(bars)
    det = SweepDetector(
        require_body_reclaim=config.sweep_requires_body_reclaim,
        consume_levels=config.sweep_consumes_levels,
    )
    published: list[tuple[int, float, int]] = []
    for known, price in zip(pivots.high_known, pivots.high_price):
        published.append((int(known) + 1, float(price), 1))
    for known, price in zip(pivots.low_known, pivots.low_price):
        published.append((int(known) + 1, float(price), -1))
    published.sort()

    events: list[SweepEvent] = []
    pi = 0
    high_l = bars.high.tolist()
    low_l = bars.low.tolist()
    close_l = bars.close.tolist()
    for i in range(n):
        while pi < len(published) and published[pi][0] <= i:
            det.add_level(published[pi][1], published[pi][2], published[pi][0] - 1)
            pi += 1
        hits = det.update(i, high_l[i], low_l[i], close_l[i])
        if hits:
            events.extend(hits)
    return events


# ---------------------------------------------------------------------------
# Candidate construction
# ---------------------------------------------------------------------------


def _build_candidates(
    bars: Bars,
    fvgs,
    confirmations: list[_Confirmation],
    config: RuleConfig,
    origins,
    minutes: np.ndarray,
    extremes,
    sweep_flags: np.ndarray,
    pivots: PivotLevels | None = None,
) -> list[Candidate]:
    """Turn confirmations into fully priced candidates."""
    n = len(bars)
    interval = bars.interval_ns
    out: list[Candidate] = []
    min_age = config.inversion_min_bars

    for conf in confirmations:
        i = conf.fvg_index
        fvg_type = int(fvgs.fvg_type[i])
        side = -fvg_type                       # the trade is opposite the gap
        if config.bias == "bullish" and side < 0:
            continue
        if config.bias == "bearish" and side > 0:
            continue
        c = int(fvgs.newest[i])
        confirm_bar = conf.confirm_bar
        age = confirm_bar - c
        if age < min_age or age > config.inversion_max_bars:
            continue

        gap_low = float(fvgs.gap_low[i])
        gap_high = float(fvgs.gap_high[i])
        far_edge = gap_low if fvg_type > 0 else gap_high

        # --- entry ---------------------------------------------------------
        if config.entry_fill == "confirm_close":
            entry_bar = confirm_bar
            entry_price = float(bars.close[confirm_bar])
        else:
            entry_bar = confirm_bar + 1
            if entry_bar >= n:
                continue
            entry_price = float(bars.open[entry_bar])

        # --- stop ----------------------------------------------------------
        stop, risk = _place_stop(
            bars, config, side, c, confirm_bar, entry_price, gap_low, gap_high, pivots
        )
        if stop is None or risk <= 0.0:
            continue
        target = entry_price + side * config.rr * risk

        origin_bar_arr, origin_price_arr = origins[side]

        # --- the BE-intact gate -------------------------------------------
        # The reference only takes a setup when the swing the leg started from
        # is still intact: if price already traded through the origin level
        # between the origin and the confirmation, the break-even level the
        # reference would move the stop to no longer exists.
        if config.require_be_intact:
            ob = int(origin_bar_arr[confirm_bar])
            op = float(origin_price_arr[confirm_bar])
            if ob >= 0 and not math.isnan(op):
                if side < 0:
                    taken = float(bars.high[ob : confirm_bar + 1].max()) > op
                else:
                    taken = float(bars.low[ob : confirm_bar + 1].min()) < op
                if taken:
                    continue

        out.append(
            Candidate(
                ts_event=int(bars.ts[confirm_bar]) + interval,
                fvg_oldest=int(fvgs.oldest[i]),
                fvg_newest=c,
                confirm_bar=confirm_bar,
                side=side,
                fvg_type=fvg_type,
                entry_bar=entry_bar,
                entry_price=entry_price,
                stop_price=stop,
                target_price=target,
                risk=risk,
                fvg_low=gap_low,
                fvg_high=gap_high,
                far_edge=far_edge,
                bars_to_inversion=age,
                minutes_from_us_open=int(minutes[confirm_bar]) - US_OPEN_MINUTES,
                origin_bar=int(origin_bar_arr[confirm_bar]),
                origin_price=float(origin_price_arr[confirm_bar]),
                sweep_detected=1 if sweep_flags[confirm_bar] else 0,
            )
        )
    return out


def _place_stop(
    bars: Bars,
    config: RuleConfig,
    side: int,
    gap_newest: int,
    confirm_bar: int,
    entry_price: float,
    gap_low: float,
    gap_high: float,
    pivots: PivotLevels | None = None,
) -> tuple[float | None, float]:
    """Place the stop and return ``(stop, risk)``.

    ``"wick"``  the extreme of the gap->confirmation window (the reference's
                default, ``pine:L293-302``).
    ``"body"``  the body-side edge of the extreme bar (``pine:L465``).
    ``"ifvg"``  the gap's far edge (``pine:L469``).
    ``"swing"`` the swing extreme (the doc's "beyond the recent swing").

    The scan window ends at the **confirmation bar** unless
    ``stop_window="confirm_plus_one"``, which additionally includes the fill
    bar.  The latter is what the reference does and it is a look-ahead: the
    stop would depend on the range of the very bar the position is entered on.
    """
    end = confirm_bar if config.stop_window == "confirm" else confirm_bar + 1
    end = min(end, len(bars) - 1)
    if end < gap_newest:
        return None, 0.0

    lo = bars.low[gap_newest : end + 1]
    hi = bars.high[gap_newest : end + 1]
    if side > 0:
        extreme = int(np.argmin(lo))
        stop = float(lo[extreme])
    else:
        extreme = int(np.argmax(hi))
        stop = float(hi[extreme])

    if config.stop_placement == "ifvg":
        stop = gap_low if side > 0 else gap_high
    elif config.stop_placement == "body":
        bar = gap_newest + extreme
        candle_bullish = bars.close[bar] > bars.open[bar]
        stop = float(bars.open[bar]) if candle_bullish == (side > 0) else float(bars.close[bar])
    elif config.stop_placement == "swing":
        stop = _swing_stop(bars, side, confirm_bar, pivots)
        if stop is None:
            return None, 0.0

    risk = (entry_price - stop) if side > 0 else (stop - entry_price)
    if risk <= 0.0:
        return None, 0.0

    # The cost of a trade is a fixed number of dollars, so its cost **in R**
    # falls as the stop gets wider.  ``stop_mult`` moves the stop away from
    # the entry by that factor, which is the only lever that touches the
    # cost ratio directly.
    if config.stop_mult != 1.0:
        stop = entry_price + (stop - entry_price) * config.stop_mult
        risk = (entry_price - stop) if side > 0 else (stop - entry_price)
        if risk <= 0.0:
            return None, 0.0
    return stop, risk


def _swing_stop(
    bars: Bars, side: int, confirm_bar: int, pivots: PivotLevels | None = None
) -> float | None:
    """The most recent swing extreme published before ``confirm_bar``.

    The pivots are passed in: recomputing them here would make the cost of
    one candidate proportional to the length of the whole series, so the
    ``"swing"`` stop placement would take hours on a ten-year sample.
    """
    if pivots is None:
        pivots = causal_pivots(
            bars.high, bars.low, left=SWING_FRACTAL - 1, right=SWING_RIGHT_BARS
        )
    if side > 0:
        end = int(np.searchsorted(pivots.low_known, confirm_bar, side="left"))
        if end == 0:
            return None
        return float(bars.low[int(pivots.low_idx[end - 1])])
    end = int(np.searchsorted(pivots.high_known, confirm_bar, side="left"))
    if end == 0:
        return None
    return float(bars.high[int(pivots.high_idx[end - 1])])


# ---------------------------------------------------------------------------
# Checklist (D8 — five named booleans, reported, never filtered)
# ---------------------------------------------------------------------------


def _attach_checklist(
    candidates: list[Candidate],
    bars: Bars,
    pivots: PivotLevels,
    extremes,
    atr: np.ndarray,
    config: RuleConfig,
) -> None:
    """Fill the five checklist booleans and their sum for every candidate.

    * ``smt_divergence``      the doc's SMT cross-check (filled by
      :func:`_attach_smt`; ``False`` when no reference instrument exists).
    * ``no_obstruction``      no tight equal-high/equal-low cluster between
      the entry and the 2R target.  The order-block half of the doc's condition
      has **no detector in any artefact** (L2 §C.4) and is therefore not
      implemented: this is a *partial* check and is labelled as such.
    * ``liquidity_target_2r`` a liquidity level at least 2R away.
    * ``vision_iou_pass``     always ``False``: the vision layer does not exist
      (D12) and its metric was replaced (D6).
    * ``vxn_regime_normal``   the regime index is in the normal band.
    """
    for cand in candidates:
        i = cand.confirm_bar
        entry = cand.entry_price
        ref = atr[i]
        tol = EQUAL_LEVEL_ATR_TOL * (float(ref) if np.isfinite(ref) else 0.0)
        hs = pivots.high_price[pivots.highs_known_before(i)]
        ls = pivots.low_price[pivots.lows_known_before(i)]
        pdh = float(extremes.pdh[i])
        pdl = float(extremes.pdl[i])
        reach = cand.risk * LIQUIDITY_TARGET_MIN_R

        if cand.side > 0:
            above = hs[hs > entry]
            has_target = bool(above.size and float(above.max()) - entry >= reach)
            if not has_target and math.isfinite(pdh) and pdh - entry >= reach:
                has_target = True
            obstructed = False
            if above.size:
                window = np.sort(above[above <= entry + reach])
                if window.size >= 2 and float(np.min(np.diff(window))) <= tol:
                    obstructed = True
        else:
            below = ls[ls < entry]
            has_target = bool(below.size and entry - float(below.min()) >= reach)
            if not has_target and math.isfinite(pdl) and entry - pdl >= reach:
                has_target = True
            obstructed = False
            if below.size:
                window = np.sort(below[below >= entry - reach])
                if window.size >= 2 and float(np.min(np.diff(window))) <= tol:
                    obstructed = True

        flags = {
            "smt_divergence": False,
            "no_obstruction": not obstructed,
            "liquidity_target_2r": has_target,
            "vision_iou_pass": False,
            "vxn_regime_normal": False,
        }
        cand.checklist_flags = flags
        cand.checklist_score = float(sum(1 for v in flags.values() if v))


def _score_checklist(candidates: list[Candidate]) -> None:
    """Score the checklist **after** every condition has been attached.

    The score must not be computed inside :func:`_attach_checklist`: the SMT
    and the VXN regime are attached later, so scoring there silently counted
    them as failures and capped the score at 2 of 5.

    A condition that could not be **decided** — the SMT where the reference
    instrument does not cover the window, the regime where no series is
    attached — is not counted against the candidate.  It is excluded from both
    the score and the number of decidable conditions
    (:attr:`Candidate.checklist_known`), so the score stays comparable across
    the sample.
    """
    for cand in candidates:
        flags = cand.checklist_flags
        decidable = {
            "smt_divergence": cand.smt_divergence >= 0,
            "no_obstruction": True,
            "liquidity_target_2r": True,
            "vision_iou_pass": False,        # the layer does not exist (D12)
            "vxn_regime_normal": cand.vxn_regime >= 0,
        }
        known = [name for name, ok in decidable.items() if ok]
        cand.checklist_known = len(known)
        cand.checklist_score = float(sum(1 for name in known if flags.get(name, False)))


# ---------------------------------------------------------------------------
# SMT
# ---------------------------------------------------------------------------


def _attach_smt(
    candidates: list[Candidate],
    bars: Bars,
    reference: Bars | None,
    config: RuleConfig,
) -> None:
    """Record the SMT divergence against a second, time-aligned instrument.

    Definition (the doc leaves "the same leg" undefined — A08 — so this is an
    explicit, documented choice): the **leg** of a candidate runs from the
    swing origin that was in force at its confirmation bar to the confirmation
    bar itself.  SMT divergence is ``1`` when the traded instrument made a new
    extreme over the leg that the reference instrument did **not** make.

    Without a reference series the value is ``-1`` (unknown) — never a guess.
    """
    if reference is None or len(reference) == 0:
        for cand in candidates:
            cand.smt_divergence = -1
            cand.checklist_flags["smt_divergence"] = False
        return

    # align the reference onto the traded timeline (as-of, never forward)
    idx = np.searchsorted(reference.ts, bars.ts, side="right") - 1
    valid = idx >= 0
    ref_high = np.full(len(bars), np.nan)
    ref_low = np.full(len(bars), np.nan)
    ref_high[valid] = reference.high[idx[valid]]
    ref_low[valid] = reference.low[idx[valid]]

    for cand in candidates:
        i = cand.confirm_bar
        leg_start = cand.origin_bar
        if leg_start < 0 or leg_start > i:
            cand.smt_divergence = -1
            continue
        length = i - leg_start + 1
        pre_start = leg_start - length
        if pre_start < 0:
            cand.smt_divergence = -1
            continue
        if cand.side > 0:
            traded_new = float(bars.low[leg_start : i + 1].min())
            traded_old = float(bars.low[pre_start:leg_start].min())
            ref_new_seg = ref_low[leg_start : i + 1]
            ref_old_seg = ref_low[pre_start:leg_start]
            if not np.isfinite(ref_new_seg).any() or not np.isfinite(ref_old_seg).any():
                # the reference instrument does not cover this window: the
                # divergence is UNKNOWN, not absent (the ES panel starts in
                # 2020-11 while NQ starts in 2015).
                cand.smt_divergence = -1
                continue
            ref_new = float(np.nanmin(ref_new_seg))
            ref_old = float(np.nanmin(ref_old_seg))
            divergence = traded_new < traded_old and not (ref_new < ref_old)
        else:
            traded_new = float(bars.high[leg_start : i + 1].max())
            traded_old = float(bars.high[pre_start:leg_start].max())
            ref_new_seg = ref_high[leg_start : i + 1]
            ref_old_seg = ref_high[pre_start:leg_start]
            if not np.isfinite(ref_new_seg).any() or not np.isfinite(ref_old_seg).any():
                cand.smt_divergence = -1
                continue
            ref_new = float(np.nanmax(ref_new_seg))
            ref_old = float(np.nanmax(ref_old_seg))
            divergence = traded_new > traded_old and not (ref_new > ref_old)
        cand.smt_divergence = 1 if divergence else 0
        cand.checklist_flags["smt_divergence"] = bool(divergence)


# ---------------------------------------------------------------------------
# Regime
# ---------------------------------------------------------------------------


def _attach_regime(candidates: list[Candidate], bars: Bars, regime) -> None:
    """Attach the strictly-lagged regime value to every candidate."""
    if regime is None:
        for cand in candidates:
            cand.vxn_known = float("nan")
            cand.vxn_regime = -1
        return

    known, label = regime.value_at(bars.ts)
    for cand in candidates:
        i = cand.confirm_bar
        cand.vxn_known = float(known[i])
        cand.vxn_regime = int(label[i])
        cand.checklist_flags["vxn_regime_normal"] = int(label[i]) == 1


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


def _resolve_outcomes(candidates: list[Candidate], bars: Bars, config: RuleConfig) -> None:
    """Resolve every candidate **standalone** (as if it were the only position).

    This is the *outcome join* of the D2 log: ``label`` is 1 when the target was
    reached, 0 when the stop was hit and -1 when the setup never resolved.
    The portfolio (one position at a time) selects a subset of these rows; the
    outcome of a selected row does not change.
    """
    if not candidates:
        return

    n = len(bars)
    low = bars.low
    high = bars.high
    # the suffix extremes answer "can this setup ever resolve?" in O(1), so a
    # setup that stays open to the end of the sample costs nothing
    suffix_min_low = np.minimum.accumulate(low[::-1])[::-1]
    suffix_max_high = np.maximum.accumulate(high[::-1])[::-1]
    for cand in candidates:
        scan_start = cand.entry_bar if config.entry_fill == "next_open" else cand.entry_bar + 1
        if scan_start >= n:
            cand.outcome = "open"
            continue
        if cand.side > 0:
            stop_possible = bool(suffix_min_low[scan_start] <= cand.stop_price)
            target_possible = bool(suffix_max_high[scan_start] >= cand.target_price)
        else:
            stop_possible = bool(suffix_max_high[scan_start] >= cand.stop_price)
            target_possible = bool(suffix_min_low[scan_start] <= cand.target_price)
        if not stop_possible and not target_possible:
            cand.outcome = "open"
            cand.r_multiple = float("nan")
            continue
        bar = _first_hit(low, high, scan_start, cand.side, cand.stop_price, cand.target_price)
        if bar < 0:
            cand.outcome = "open"
            cand.r_multiple = float("nan")
            continue
        hit_stop = (low[bar] <= cand.stop_price) if cand.side > 0 else (high[bar] >= cand.stop_price)
        if hit_stop:
            cand.outcome = "stop"
            cand.r_multiple = -1.0
        else:
            cand.outcome = "target"
            cand.r_multiple = config.rr
        cand.exit_bar = bar


def _first_hit(
    low: np.ndarray,
    high: np.ndarray,
    start: int,
    side: int,
    stop: float,
    target: float,
    chunk: int = 512,
    end: int | None = None,
) -> int:
    """Index of the first bar at or after ``start`` that hits the stop or the target.

    The stop has priority when a bar touches both (conservative, matching the
    experiment harness).  The search grows geometrically so that the common
    case (a setup that resolves within a few bars) costs almost nothing.
    """
    n = low.shape[0] if end is None else min(int(end), low.shape[0])
    pos = start
    span = chunk
    while pos < n:
        stop_at = min(pos + span, n)
        lo = low[pos:stop_at]
        hi = high[pos:stop_at]
        if side > 0:
            hit_sl = lo <= stop
            hit_tp = hi >= target
        else:
            hit_sl = hi >= stop
            hit_tp = lo <= target
        any_hit = hit_sl | hit_tp
        if any_hit.any():
            return pos + int(np.argmax(any_hit))
        pos = stop_at
        span *= 2
    return -1


# ---------------------------------------------------------------------------
# The experiment harness's one-position-at-a-time arm (deferred entries)
# ---------------------------------------------------------------------------


def run_deferred_portfolio(
    bars: Bars,
    config: RuleConfig | None = None,
) -> list[Candidate]:
    """The D4 baseline arm: one position at a time, **deferred** entries.

    This reproduces the accounting of
    ``research/experiments/e1_rule_falsification.py`` exactly: a signal that
    arrives while a position is open stays **pending** and may still trigger on
    a later bar, at a different price and with a different stop.  It is the
    arm the D4 baseline numbers were measured on, so it is the only way to
    compare this engine against that baseline like for like.

    The drop-the-signal semantics (L2's recommendation for a real portfolio)
    is :func:`dodgys_dd_quant.backtest.walk_forward.simulate_portfolio`.
    """
    config = config or RuleConfig()
    n = len(bars)
    if n < 4:
        return []

    atr = atr_wilder(bars.high, bars.low, bars.close)
    fvgs = detect_fvg(bars, atr, config.min_gap_atr_mult)
    if len(fvgs) == 0:
        return []
    # computed once: the "swing" stop placement needs them for every candidate
    pivots = causal_pivots(bars.high, bars.low, left=SWING_FRACTAL - 1, right=SWING_RIGHT_BARS)

    min_age = max(0, config.inversion_min_bars)
    max_age = max(min_age, config.inversion_max_bars)
    width = max_age - min_age + 1

    # --- the trigger matrix: which detection bar fires for which gap ------
    lo = fvgs.newest + min_age
    hi = np.minimum(fvgs.newest + max_age, n - 1)
    valid = lo <= hi
    if not valid.any():
        return []
    lo = lo[valid]
    hi = hi[valid]
    idx = np.flatnonzero(valid)

    close_padded = np.concatenate([bars.close, np.full(max(0, width - 1), np.nan)])
    win = np.lib.stride_tricks.sliding_window_view(close_padded, width)

    det_bars: list[np.ndarray] = []
    cand_ids: list[np.ndarray] = []
    chunk = 100_000
    for start in range(0, lo.shape[0], chunk):
        stop = min(start + chunk, lo.shape[0])
        rows = win[lo[start:stop]]
        is_bull = fvgs.fvg_type[idx[start:stop]] > 0
        beyond = np.where(
            is_bull[:, None],
            rows < fvgs.gap_low[idx[start:stop]][:, None],
            rows > fvgs.gap_high[idx[start:stop]][:, None],
        )
        cols = np.arange(width)[None, :]
        beyond &= (lo[start:stop, None] + cols) <= hi[start:stop, None]
        row_i, col_i = np.nonzero(beyond)
        if row_i.size == 0:
            continue
        det_bars.append(lo[start:stop][row_i] + col_i + 1)   # detection bar
        cand_ids.append(idx[start:stop][row_i])

    if not det_bars:
        return []
    det_all = np.concatenate(det_bars)
    cand_all = np.concatenate(cand_ids)
    order = np.argsort(det_all, kind="stable")     # within a bar: insertion order
    det_all = det_all[order]
    cand_all = cand_all[order]

    # --- the simulation ----------------------------------------------------
    # The exit bar of a position is a fact of the market, not of the signal
    # flow: it is computed once, when the position opens, and afterwards only
    # *compared* with the current bar.  That keeps the accounting causal (the
    # slot is free at a signal only if the position had already closed) while
    # avoiding a scan per signal.
    suffix_min_low = np.minimum.accumulate(bars.low[::-1])[::-1]
    suffix_max_high = np.maximum.accumulate(bars.high[::-1])[::-1]

    open_pos: Candidate | None = None
    trades: list[Candidate] = []
    # a gap may only be confirmed once, even though it can keep triggering
    confirmed = np.zeros(int(fvgs.newest.shape[0]), dtype=bool)
    i = 0
    total = det_all.shape[0]
    while i < total:
        bar = int(det_all[i])
        j = i
        while j < total and det_all[j] == bar:
            j += 1
        group = cand_all[i:j]

        # the open position has closed before this bar -> the slot is free
        if open_pos is not None and open_pos.exit_bar >= 0 and open_pos.exit_bar < bar:
            trades.append(open_pos)
            open_pos = None

        for c in group:
            i_fvg = int(c)
            if confirmed[i_fvg]:
                continue                       # already taken at an earlier bar
            if open_pos is not None:
                continue                       # blocked -> stays pending (defer)
            confirm_bar = bar - 1
            age = confirm_bar - int(fvgs.newest[i_fvg])
            if age < min_age or age > max_age:
                continue
            cand = _price_candidate(bars, fvgs, i_fvg, confirm_bar, config, pivots)
            if cand is None:
                continue
            confirmed[i_fvg] = True
            _resolve_one(cand, bars, config, suffix_min_low, suffix_max_high)
            open_pos = cand

        i = j

    if open_pos is not None:
        trades.append(open_pos)

    trades.sort(key=lambda c: c.entry_bar)
    return trades


def _resolve_one(
    cand: Candidate,
    bars: Bars,
    config: RuleConfig,
    suffix_min_low: np.ndarray,
    suffix_max_high: np.ndarray,
) -> None:
    """Resolve one position and record its outcome and exit bar."""
    start = cand.entry_bar if config.entry_fill == "next_open" else cand.entry_bar + 1
    if start >= len(bars):
        cand.outcome = "open"
        return
    if cand.side > 0:
        stop_possible = bool(suffix_min_low[start] <= cand.stop_price)
        target_possible = bool(suffix_max_high[start] >= cand.target_price)
    else:
        stop_possible = bool(suffix_max_high[start] >= cand.stop_price)
        target_possible = bool(suffix_min_low[start] <= cand.target_price)
    if not stop_possible and not target_possible:
        cand.outcome = "open"
        cand.exit_bar = -1
        return
    bar = _first_hit(
        bars.low, bars.high, start, cand.side, cand.stop_price, cand.target_price
    )
    if bar < 0:
        cand.outcome = "open"
        cand.exit_bar = -1
        return
    cand.exit_bar = bar
    hit_stop = (bars.low[bar] <= cand.stop_price) if cand.side > 0 else (bars.high[bar] >= cand.stop_price)
    if hit_stop:
        cand.outcome = "stop"
        cand.r_multiple = -1.0
    else:
        cand.outcome = "target"
        cand.r_multiple = config.rr


def _price_candidate(
    bars: Bars,
    fvgs,
    i_fvg: int,
    confirm_bar: int,
    config: RuleConfig,
    pivots: PivotLevels | None = None,
) -> Candidate | None:
    """Price one confirmed setup (entry, stop, target)."""
    n = len(bars)
    fvg_type = int(fvgs.fvg_type[i_fvg])
    side = -fvg_type
    c = int(fvgs.newest[i_fvg])
    gap_low = float(fvgs.gap_low[i_fvg])
    gap_high = float(fvgs.gap_high[i_fvg])

    if config.entry_fill == "confirm_close":
        entry_bar = confirm_bar
        entry_price = float(bars.close[confirm_bar])
    else:
        entry_bar = confirm_bar + 1
        if entry_bar >= n:
            return None
        entry_price = float(bars.open[entry_bar])

    stop, risk = _place_stop(
        bars, config, side, c, confirm_bar, entry_price, gap_low, gap_high, pivots
    )
    if stop is None or risk <= 0.0:
        return None
    target = entry_price + side * config.rr * risk
    return Candidate(
        ts_event=int(bars.ts[confirm_bar]) + bars.interval_ns,
        fvg_oldest=int(fvgs.oldest[i_fvg]),
        fvg_newest=c,
        confirm_bar=confirm_bar,
        side=side,
        fvg_type=fvg_type,
        entry_bar=entry_bar,
        entry_price=entry_price,
        stop_price=stop,
        target_price=target,
        risk=risk,
        fvg_low=gap_low,
        fvg_high=gap_high,
        far_edge=gap_low if fvg_type > 0 else gap_high,
        bars_to_inversion=confirm_bar - c,
        outcome="open",
    )
