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
from collections import deque
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable

import numpy as np

from dodgys_dd_quant.strategy.constants import (
    CHECKLIST_WEIGHTS,
    LABEL_HORIZON_BARS,
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
    MAX_TRACKED_SETUPS,
    MIN_GAP_ATR_MULT,
    NY_TZ,
    SWING_FRACTAL,
    SWING_RIGHT_BARS,
)
from dodgys_dd_quant.strategy.regime import regime_parameters
from dodgys_dd_quant.strategy.structure import (
    Bars,
    PivotLevels,
    SweepDetector,
    SweepEvent,
    aggregate_htf,
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
    #: Which sweep **object** the engine uses.
    #:
    #: ``"swings"``       the code-derived detector: the same timeframe, a
    #:                   five-bar fractal, an added body-reclaim condition and
    #:                   no consumption of the reference's level set (L2 D-06).
    #: ``"htf_fractal"``  the reference's own object: the levels are the
    #:                   three-bar fractals of the **hand-aggregated HTF
    #:                   series**, the pierce is strict (no body reclaim) and
    #:                   every pierced level is consumed once
    #:                   (``pine:L544-630``).
    sweep_source: str = "swings"
    #: The HTF timeframe of the reference's sweep detector and of the
    #: confluence gate (``autoHTF()``: 1m -> 15m, ``pine:L544-552``).
    htf_timeframe_minutes: int = 15
    #: The reference's ``onlyShowHtfAlignedIFVG`` (default **false**): the
    #: setup must overlap an **unreclaimed HTF FVG zone** (``pine:L635-647``).
    require_htf_alignment: bool = False
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

    # --- the label horizon ------------------------------------------------
    #: The maximum holding period, in **bars of the scanned series**.  The
    #: default is the project constant (240).  A caller that wants a *time*
    #: horizon derives the bar count from its bar interval, so "8 hours" means
    #: the same duration at 1m, 5m and 15m instead of 240 bars of each.
    horizon_bars: int = LABEL_HORIZON_BARS

    # --- references -------------------------------------------------------
    #: Symbol of the SMT reference instrument; ``None`` disables the check and
    #: records ``smt_divergence = -1`` (never guesses).
    smt_reference_symbol: str | None = None

    # --- roll boundary ----------------------------------------------------
    #: A contract roll leaves a **price gap** that the rule engine would read
    #: as a liquidity sweep (Q5: "a roll gap can fake a liquidity sweep").
    #: ``None`` disables the guard -- the crypto lane has no rolls -- and a
    #: value is the relative jump that counts as one.
    roll_gap_frac: float | None = None
    #: How many bars around a roll boundary are excluded.
    roll_bars_around: int = 2

    # --- the break-even exit ----------------------------------------------
    #: The reference closes a trade at the **leg's origin** (its "B.E." exit,
    #: ``pine:L476-491``).  The code-derived arm (E-1) and the doc have no such
    #: exit, so it is **off** by default and the honest arm keeps its E-1
    #: parity; the reference-faithful ``pine`` preset turns it on.
    resolve_break_even: bool = False

    # --- setup history ----------------------------------------------------
    #: The reference keeps only the last ``setupHistory`` setups (default 2)
    #: and an evicted, still unresolved setup **stops being managed**
    #: (``pine:L13``, ``pine:L482-495``).  ``0`` disables the cap, so every
    #: setup is managed to its end -- the code-derived behaviour and the safer
    #: one (L2 row 28, audit D-11).
    setup_history_cap: int = 0

    # --- swing origin -----------------------------------------------------
    #: The reference's origin sits one bar *before* the extreme it names
    #: (``pine:L369``: ``originBar = bar_index - 1``); the port reconciles the
    #: two readings by using the extreme itself.  ``-1`` restores the
    #: reference's literal bar index (the price is unchanged either way).
    origin_bar_offset: int = 0

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
        resolve_break_even=True,
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
    checklist_flags: dict[str, bool] = field(default_factory=dict)
    smt_divergence: int = -1
    sweep_detected: int = 0
    vxn_known: float = float("nan")
    vxn_regime: int = -1
    origin_bar: int = -1
    origin_price: float = float("nan")
    #: The reference's **break-even level** (``pine:L476``): the swing origin
    #: of the leg that produced the gap.  ``NaN`` when the leg has no known
    #: pivot yet.
    be_price: float = float("nan")
    #: The bar at which the price first reached ``be_price`` after the fill,
    #: ``-1`` when it never did inside the label horizon.
    be_hit_bar: int = -1
    #: The **next liquidity pool** at least ``LIQUIDITY_TARGET_MIN_R`` R away
    #: in the trade's direction (the doc's target definition).  ``NaN`` when no
    #: such pool exists.
    liquidity_target_price: float = float("nan")
    #: The vision layer's verdict on this candidate, filled by the **offline**
    #: batch (``vision_validator.batch``): the 2-D body IoU and the detector's
    #: confidence.  ``NaN`` until the batch has run -- the D2 schema keeps
    #: both columns, the engine never fills them (D12).
    vision_iou: float = float("nan")
    vision_confidence: float = float("nan")
    #: Whether a liquidity sweep of the tracker side happened between the
    #: leg's origin pivot and the confirmation bar (the reference's ``swept``
    #: flag, ``pine:L246-259``).
    sweep_since_origin: bool = False
    #: Whether the reference's per-direction tracking array dropped this
    #: candidate's gap (``MAX_TRACKED_SETUPS``, L2 row 29).  The reference
    #: drops it silently; the port records it and keeps the row.
    dropped_by_cap: bool = False
    #: Whether the cap dropped the gap **before** it could trigger -- the
    #: reference's "it can never trigger" case.  Such a setup is logged but
    #: never traded.
    never_tradable: bool = False
    #: The regime band's risk multiplier (L109: the high-volatility band
    #: halves the risk per trade).  1.0 when no regime is attached.
    risk_multiplier: float = 1.0
    outcome: str = "open"      # "stop" | "target" | "break_even" | "open" | "expired" | "discarded"
    r_multiple: float = float("nan")
    exit_bar: int = -1
    p_win: float = float("nan")
    #: The meta-label gate's decision for this candidate (``False`` when no
    #: model ran).  Kept on the object so the archive records the *decision*
    #: rather than reconstructing it from a threshold after the fact.
    gate_approved: bool = False

    @property
    def is_closed(self) -> bool:
        # A break-even exit is a **closed** trade: the reference closes the
        # position at the leg's origin, so the portfolio must carry its exit
        # bar and its realised multiple.
        return self.outcome in ("stop", "target", "break_even")

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
            # The vision columns are filled by the **offline** batch
            # (``vision_validator.batch``); the engine never renders or runs
            # a detector, so they stay NaN until that pass has run (D12).
            "vision_iou": np.asarray(
                [c.vision_iou for c in cands], dtype=np.float64
            ),
            "vision_confidence": np.asarray(
                [c.vision_confidence for c in cands], dtype=np.float64
            ),
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

    # --- the regime, resolved once -----------------------------------------
    # The regime must reach the *decision*, not just a feature column: it
    # selects the target distance, the gap filter's ATR floor and the risk
    # per trade (L107-109).  When no regime index is attached the config's
    # own values stand, which is what the code-derived baseline does.
    regime_levels = None
    regime_labels = None
    if regime is not None:
        regime_levels, regime_labels = regime.value_at(bars.ts)

    atr = atr_wilder(bars.high, bars.low, bars.close)
    gap_floor = _regime_atr_floor(config, regime_labels)
    fvgs = detect_fvg(bars, atr, gap_floor)
    pivots = causal_pivots(bars.high, bars.low, left=SWING_FRACTAL - 1, right=SWING_RIGHT_BARS)
    origins = _origin_series(bars, pivots, config.origin_bar_offset)

    minutes = local_minutes_of_day(bars.close_ts(), config.session_timezone)
    extremes = session_extremes(bars.ts, bars.high, bars.low, config.session_timezone)
    htf = None
    if config.sweep_source == "htf_fractal" or config.require_htf_alignment:
        htf = aggregate_htf(bars, config.htf_timeframe_minutes)

    # --- the roll boundary (Q5) -------------------------------------------
    roll_excluded: set[int] = set()
    if config.roll_gap_frac is not None:
        roll_excluded = _roll_boundary_bars(
            bars, config.roll_gap_frac, config.roll_bars_around
        )

    sweeps = _sweep_events(bars, pivots, config, htf)
    if roll_excluded:
        # a roll gap must not be read as a liquidity sweep
        sweeps = [ev for ev in sweeps if ev.bar not in roll_excluded]
    sweep_flags = np.zeros(n, dtype=bool)
    for ev in sweeps:
        sweep_flags[ev.bar] = True
    # Sweep bars per pierced side, sorted: the reference's ``swept`` flag is
    # set by a sweep of the **tracker's** side (``pine:L246-259``).
    sweep_bars: dict[int, np.ndarray] = {}
    for direction in (1, -1):
        bars_of_side = np.array(
            sorted(ev.bar for ev in sweeps if ev.direction == direction), dtype=np.int64
        )
        sweep_bars[direction] = bars_of_side

    if config.leg_tracker:
        confirmations = _leg_confirmations(bars, fvgs, config, sweep_flags)
    else:
        gate = _bar_gates(config, minutes, sweep_flags)
        confirmations = _scan_confirmations(bars, fvgs, config, gate)

    if roll_excluded:
        confirmations = [
            conf for conf in confirmations if conf.confirm_bar not in roll_excluded
        ]

    # The reference's per-direction candidate cap (L2 row 29): the drops are
    # recorded on the candidates instead of being silently swallowed.
    evicted, never_tradable = _candidate_cap_drops(fvgs, confirmations, config)

    candidates = _build_candidates(
        bars,
        fvgs,
        confirmations,
        config,
        origins,
        minutes,
        extremes,
        sweep_flags,
        regime_labels=regime_labels,
        sweep_bars=sweep_bars,
        evicted=evicted,
        never_tradable=never_tradable,
        htf=htf,
    )
    _attach_checklist(candidates, bars, pivots, extremes, atr, config)
    _attach_smt(candidates, bars, reference, config)
    _attach_regime(candidates, bars, regime, levels=regime_levels, labels=regime_labels)
    _resolve_outcomes(candidates, bars, config)
    if config.setup_history_cap > 0:
        _apply_setup_history_cap(candidates, config.setup_history_cap)
    return CandidateLog(candidates, config.symbol, config.timeframe)


def _regime_atr_floor(config: RuleConfig, regime_labels) -> object:
    """The gap filter's ATR floor, per candle.

    Without a regime the config's own floor stands.  With one, the regime
    band decides: the doc raises the floor in the high-volatility band and
    tightens it in the low one (L107-109).
    """
    if regime_labels is None:
        return config.min_gap_atr_mult
    floor = np.full(len(regime_labels), np.nan, dtype=np.float64)
    for label in np.unique(regime_labels):
        if label < 0:
            continue
        params = regime_parameters(int(label))
        floor[regime_labels == label] = params.atr_floor_mult
    if not np.isfinite(floor).any():
        return config.min_gap_atr_mult
    # A bar with no regime keeps the config's floor.
    fallback = config.min_gap_atr_mult
    if fallback is None:
        fallback = 0.0
    floor = np.where(np.isfinite(floor), floor, float(fallback))
    return floor


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


def _leg_confirmations(
    bars: Bars,
    fvgs,
    config: RuleConfig,
    sweep_flags: np.ndarray,
) -> list[_Confirmation]:
    """The reference's leg tracker (R1-R5): one live candidate per direction.

    A gap may only be created inside a swing leg and only while the leg is not
    frozen; at most one candidate per direction is live and the *worse* gap is
    discarded (the reference's ``Single`` arbitration, ``pine:L383-403``).

    This path is a per-bar walk, exactly like the reference, and is therefore
    markedly slower than the vectorised scanner.  The reference's ``Series``
    mode (merging consecutive gaps into one growing zone) is **not**
    implemented; only ``Single`` is supported.
    """
    n = len(bars)
    high_l = bars.high.tolist()
    low_l = bars.low.tolist()
    close_l = bars.close.tolist()

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
            # the pivot fires when bar k is the extreme of the last 3 bars
            window_low = min(low_l[k - 2], low_l[k - 1], low_l[k])
            window_high = max(high_l[k - 2], high_l[k - 1], high_l[k])
            pivot_origin = fvg_type > 0 and low_l[k] <= window_low
            pivot_opp = fvg_type > 0 and high_l[k] >= window_high
            if fvg_type < 0:
                pivot_origin = high_l[k] >= window_high
                pivot_opp = low_l[k] <= window_low

            if pivot_origin:
                origin_bar = k
                origin_price = low_l[k] if fvg_type > 0 else high_l[k]
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
                if live >= 0 and not confirmed:
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

            if not frozen and pivot_opp:
                frozen = True
                frozen_price = high_l[k - 1] if fvg_type > 0 else low_l[k - 1]
                freeze_bar = k

    out.sort(key=lambda x: x.confirm_bar)
    return out


# ---------------------------------------------------------------------------
# Origin tracker (swing origin -> break-even level)
# ---------------------------------------------------------------------------


def _origin_series(
    bars: Bars,
    pivots: PivotLevels,
    offset: int = 0,
) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    """The causal swing origin in force at every bar, per direction.

    ``+1`` is the bullish-gap tracker (its origin is a **swing low**), ``-1``
    the bearish-gap tracker (origin = swing high).  The origin price is the
    swing extreme itself, which is the level the reference uses as the
    **break-even** price (``pine:L476``).

    L2 §E-1 records that the reference's own origin sits **one bar before** the
    extreme (``originBar = bar_index - 1``); the two readings are reconciled
    here by using the extreme itself, which is the only reading under which the
    break-even level is a swing level at all.

    ``offset`` restores the reference's literal bar index (``-1``) without
    touching the price: both readings name the same level, they only disagree
    about *when* it was published.
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
        if offset:
            shifted = origin_bar + int(offset)
            origin_bar = np.where(origin_bar >= 0, np.maximum(shifted, -1), -1)
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


def _sweep_events(
    bars: Bars,
    pivots: PivotLevels,
    config: RuleConfig,
    htf=None,
) -> list[SweepEvent]:
    """Every liquidity sweep, with the reference's one-shot level consumption.

    A level becomes usable one bar after it is published: the swing is known at
    the close of the confirming bar and the sweep test uses the bar's own
    high/low, which is only complete at that bar's close.

    ``config.sweep_source`` selects the **object**: ``"swings"`` uses the
    code-derived detector (the same timeframe, a five-bar fractal and an added
    body-reclaim condition); ``"htf_fractal"`` reproduces the reference's own
    detector -- the levels are the three-bar fractals of the hand-aggregated
    HTF series and the pierce is strict (``pine:L544-630``).
    """
    n = len(bars)
    if config.sweep_source == "htf_fractal":
        if htf is None:
            raise ValueError("the 'htf_fractal' sweep source needs the HTF series")
        det = SweepDetector(require_body_reclaim=False, consume_levels=True)
        published = [
            (int(level.known_at) + 1, float(level.price), int(level.direction))
            for level in htf.levels
        ]
        published.sort()
    else:
        det = SweepDetector(
            require_body_reclaim=config.sweep_requires_body_reclaim,
            consume_levels=config.sweep_consumes_levels,
        )
        published = []
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
    *,
    regime_labels: np.ndarray | None = None,
    sweep_bars: dict[int, np.ndarray] | None = None,
    evicted: dict[int, int] | None = None,
    never_tradable: set[int] | None = None,
    htf=None,
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

        # --- the reference's HTF confluence gate ----------------------------
        # ``onlyShowHtfAlignedIFVG`` (default **false**): the setup must
        # overlap an unreclaimed HTF FVG zone that is knowable at the
        # confirmation bar (``pine:L635-647``, ``pine:L444-445``).
        if config.require_htf_alignment:
            if htf is None:
                raise ValueError("the HTF confluence gate needs the HTF series")
            zones = htf.zones_at(confirm_bar)
            gap_low = float(fvgs.gap_low[i])
            gap_high = float(fvgs.gap_high[i])
            aligned = any(
                zone.bottom <= gap_high and zone.top >= gap_low for zone in zones
            )
            if not aligned:
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
            bars, config, side, c, confirm_bar, entry_price, gap_low, gap_high
        )
        if stop is None or risk <= 0.0:
            continue

        # --- the regime decides the trade's shape ---------------------------
        # The doc's per-regime policy (L107-109): the target distance, the
        # risk per trade and the gap filter's ATR floor all follow the band.
        rr = config.rr
        risk_multiplier = 1.0
        if regime_labels is not None:
            label = int(regime_labels[confirm_bar])
            if label >= 0:
                params = regime_parameters(label)
                rr = params.rr
                risk_multiplier = params.risk_multiplier
        target = entry_price + side * rr * risk

        # The origin belongs to the **tracker that produced the gap**, not to
        # the trade: the reference's bullish-gap tracker (``isLow=true``) is
        # fed by swing *lows* and its bearish twin by swing *highs*
        # (``pine:L246-259``).  The trade runs *against* the gap, so the
        # tracker key is ``fvg_type`` -- using the trade side here pointed the
        # break-even level at the wrong leg of the market (and made the
        # ``require_be_intact`` gate reject almost everything).
        origin_bar_arr, origin_price_arr = origins[fvg_type]
        origin_price = float(origin_price_arr[confirm_bar])

        # --- the break-even-intact gate -------------------------------------
        # The reference's ``requireBEIntact`` (default **on**) drops a setup
        # whose *confirmation close* has already reached the swing origin --
        # the level the trade would break even at.  It is a **predictive**
        # filter: it removes setups before they exist, so it changes the
        # population rather than the rendering (L2 row 14, PINE R16).
        if config.require_be_intact and math.isfinite(origin_price):
            close = float(bars.close[confirm_bar])
            breached = close >= origin_price if side > 0 else close <= origin_price
            if breached:
                continue

        origin_bar = int(origin_bar_arr[confirm_bar])
        sweep_since_origin = False
        if sweep_bars is not None and origin_bar >= 0:
            side_bars = sweep_bars.get(fvg_type)
            if side_bars is not None and side_bars.size:
                idx = int(np.searchsorted(side_bars, origin_bar, side="right"))
                sweep_since_origin = bool(
                    idx < side_bars.size and int(side_bars[idx]) <= confirm_bar
                )

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
                origin_bar=origin_bar,
                origin_price=origin_price,
                be_price=origin_price,
                sweep_since_origin=sweep_since_origin,
                dropped_by_cap=bool(evicted and i in evicted),
                never_tradable=bool(never_tradable and i in never_tradable),
                sweep_detected=1 if sweep_flags[confirm_bar] else 0,
                risk_multiplier=risk_multiplier,
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
        stop = _swing_stop(bars, side, confirm_bar)
        if stop is None:
            return None, 0.0

    risk = (entry_price - stop) if side > 0 else (stop - entry_price)
    if risk <= 0.0:
        return None, 0.0
    return stop, risk


def _swing_stop(bars: Bars, side: int, confirm_bar: int) -> float | None:
    """The most recent swing extreme published before ``confirm_bar``."""
    pivots = causal_pivots(bars.high, bars.low, left=SWING_FRACTAL - 1, right=SWING_RIGHT_BARS)
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
            target_price = float("nan")
            if above.size:
                ordered = np.sort(above)
                idx = int(np.searchsorted(ordered, entry + reach, side="left"))
                if idx < ordered.size:
                    target_price = float(ordered[idx])
            if not math.isfinite(target_price) and math.isfinite(pdh) and pdh - entry >= reach:
                target_price = float(pdh)
            has_target = math.isfinite(target_price)
            obstructed = False
            if above.size:
                window = np.sort(above[above <= entry + reach])
                if window.size >= 2 and float(np.min(np.diff(window))) <= tol:
                    obstructed = True
        else:
            below = ls[ls < entry]
            has_target = bool(below.size and entry - float(below.min()) >= reach)
            target_price = float("nan")
            if below.size:
                ordered = np.sort(below)
                # the nearest pool below the entry is the largest one that is
                # still at least ``reach`` away
                idx = int(np.searchsorted(ordered, entry - reach, side="right")) - 1
                if idx >= 0:
                    target_price = float(ordered[idx])
            if not math.isfinite(target_price) and math.isfinite(pdl) and entry - pdl >= reach:
                target_price = float(pdl)
            has_target = math.isfinite(target_price)
            obstructed = False
            if below.size:
                window = np.sort(below[below >= entry - reach])
                if window.size >= 2 and float(np.min(np.diff(window))) <= tol:
                    obstructed = True

        cand.liquidity_target_price = target_price

        flags = {
            "smt_divergence": False,
            "no_obstruction": not obstructed,
            "liquidity_target_2r": has_target,
            "vision_iou_pass": False,
            "vxn_regime_normal": False,
        }
        cand.checklist_flags = flags
        cand.checklist_score = float(sum(1 for v in flags.values() if v))


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
            ref_new = float(np.nanmin(ref_low[leg_start : i + 1]))
            ref_old = float(np.nanmin(ref_low[pre_start:leg_start]))
            divergence = traded_new < traded_old and not (ref_new < ref_old)
        else:
            traded_new = float(bars.high[leg_start : i + 1].max())
            traded_old = float(bars.high[pre_start:leg_start].max())
            ref_new = float(np.nanmax(ref_high[leg_start : i + 1]))
            ref_old = float(np.nanmax(ref_high[pre_start:leg_start]))
            divergence = traded_new > traded_old and not (ref_new > ref_old)
        cand.smt_divergence = 1 if divergence else 0
        cand.checklist_flags["smt_divergence"] = bool(divergence)


# ---------------------------------------------------------------------------
# Regime
# ---------------------------------------------------------------------------


def _attach_regime(
    candidates: list[Candidate],
    bars: Bars,
    regime,
    *,
    levels: np.ndarray | None = None,
    labels: np.ndarray | None = None,
) -> None:
    """Attach the strictly-lagged regime value to every candidate."""
    if regime is None:
        for cand in candidates:
            cand.vxn_known = float("nan")
            cand.vxn_regime = -1
        return

    if levels is None or labels is None:
        levels, labels = regime.value_at(bars.ts)
    for cand in candidates:
        i = cand.confirm_bar
        cand.vxn_known = float(levels[i])
        cand.vxn_regime = int(labels[i])
        cand.checklist_flags["vxn_regime_normal"] = int(labels[i]) == 1


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


def _roll_boundary_bars(
    bars: Bars,
    price_gap_frac: float,
    bars_around: int = 2,
) -> set[int]:
    """The bars around a contract roll -- a discontinuous price jump.

    A continuous series that switches contract leaves a gap the engine would
    read as a liquidity sweep, so the bars around the jump are excluded from
    the signal population (Q5: the roll rule matters because a roll gap can
    fake a sweep).
    """
    if price_gap_frac <= 0.0 or len(bars) < 2:
        return set()
    close = bars.close
    previous = close[:-1]
    current = close[1:]
    with np.errstate(divide="ignore", invalid="ignore"):
        relative = np.abs(current - previous) / np.maximum(np.abs(previous), 1e-12)
    jumps = np.flatnonzero(relative >= price_gap_frac) + 1
    excluded: set[int] = set()
    n = len(bars)
    for jump in jumps:
        start = max(0, int(jump) - bars_around)
        stop = min(n, int(jump) + bars_around + 1)
        excluded.update(range(start, stop))
    return excluded


def _apply_setup_history_cap(candidates: list[Candidate], cap: int) -> None:
    """The reference's ``setupHistory`` cap (L2 row 28, audit D-11).

    The reference keeps only the last ``setupHistory`` setups in
    ``setupRecords``; when a new setup is pushed, the oldest is shifted out
    **and removed from the live-trade array**, so an unresolved setup stops
    being managed and never resolves (``pine:L482-495``).

    The port reproduces that side effect: an evicted setup that had not
    resolved yet loses its outcome and is reported as ``"unmanaged"`` -- it is
    neither a stop nor a target, and it keeps the censored label ``-1``.
    """
    live: list[Candidate] = []
    for cand in sorted(candidates, key=lambda c: (c.ts_event, c.side)):
        live.append(cand)
        if len(live) <= cap:
            continue
        oldest = live.pop(0)
        resolved_before = oldest.exit_bar >= 0 and oldest.exit_bar <= cand.entry_bar
        if resolved_before:
            continue
        oldest.outcome = "unmanaged"
        oldest.r_multiple = float("nan")
        oldest.exit_bar = -1


def _candidate_cap_drops(
    fvgs,
    confirmations: list[_Confirmation],
    config: RuleConfig,
) -> tuple[dict[int, int], set[int]]:
    """Emulate the reference's per-direction candidate cap (L2 row 29).

    The reference keeps at most ``MAX_TRACKED_SETUPS`` gaps **per direction**
    in its tracking array (``pine:L78``, ``pine:L286-291``).  A push beyond
    the cap drops the **oldest** entry, which can then never trigger.

    Two rules of that array decide *when* the cap binds, and both are
    reproduced here:

    * an entry that has already **confirmed** is never removed from the
      array -- the expiry branch sits inside ``if not e.ifvgConfirmed``
      (``pine:L437``, ``pine:L500``) -- so confirmed entries accumulate and
      the array saturates;
    * an entry that has **not** confirmed is dropped once it is older than
      the grace window (``bar_index - fvgBar1 > graceCandles``).

    The evaluation bars follow the reference: the gap is pushed on the bar
    after its third candle, the trigger is tested on the bar after the
    confirmation candle and the age is measured from the gap's **newest**
    candle (``fvgBar1`` in the reference's naming).

    Returns the eviction bar per gap index and the set of gaps the cap
    dropped *before* they could trigger.
    """
    confirm_by_gap = {conf.fvg_index: conf.confirm_bar for conf in confirmations}
    grace = max(0, config.inversion_max_bars)
    evicted: dict[int, int] = {}
    never_tradable: set[int] = set()
    for direction in (1, -1):
        events: list[tuple[int, int, int]] = []
        for i in range(len(fvgs)):
            if int(fvgs.fvg_type[i]) != direction:
                continue
            c = int(fvgs.newest[i])
            events.append((c + 1, 0, i))                      # push
            conf_bar = confirm_by_gap.get(i)
            if conf_bar is not None:
                events.append((conf_bar + 1, 1, i))          # trigger
            events.append((c + grace + 1, 2, i))             # expiry
        if not events:
            continue
        events.sort()
        array: deque[int] = deque()
        confirmed: set[int] = set()
        for bar, kind, i in events:
            if kind == 0:
                array.append(i)
                if len(array) > MAX_TRACKED_SETUPS:
                    old = array.popleft()
                    evicted[old] = bar
                    if old not in confirmed:
                        never_tradable.add(old)
            elif kind == 1:
                confirmed.add(i)
            elif i not in confirmed and i in array:
                # the entry expired unconfirmed and leaves the array
                array.remove(i)
    return evicted, never_tradable


def _resolve_outcomes(candidates: list[Candidate], bars: Bars, config: RuleConfig) -> None:
    """Resolve every candidate **standalone** (as if it were the only position).

    This is the *outcome join* of the D2 log: ``label`` is 1 when the target was
    reached, 0 when the stop was hit and -1 when the setup never resolved.
    The portfolio (one position at a time) selects a subset of these rows; the
    outcome of a selected row does not change.

    The resolution is capped at ``LABEL_HORIZON_BARS``: a setup that has
    resolved neither way within the horizon is **censored** (``-1``), not
    left open forever.  This is what makes the horizon -- and therefore the
    purge and the embargo -- well defined, and it gives the log **one** label
    definition: the ML pipeline's ``build_labels`` uses the same horizon and
    the same cap, so the two agree row for row (F6).
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
        if cand.never_tradable:
            # The reference's tracking array dropped this setup before it
            # could trigger: it is logged (never erased) but never traded.
            cand.outcome = "discarded"
            cand.r_multiple = float("nan")
            cand.exit_bar = -1
            continue
        scan_start = cand.entry_bar if config.entry_fill == "next_open" else cand.entry_bar + 1
        if scan_start >= n:
            cand.outcome = "open"
            continue
        # The end of the resolution window: the horizon in bars from the fill.
        scan_end = min(n, scan_start + int(config.horizon_bars))
        # The reference's break-even level: the swing origin of the leg that
        # produced the gap.  Recorded for every candidate (L2 row 19) and used
        # to resolve the setups our own stop/target never reach (row 20).
        be_bar = (
            _break_even_hit(bars, cand, scan_start, scan_end)
            if config.resolve_break_even
            else -1
        )
        cand.be_hit_bar = be_bar
        if cand.side > 0:
            stop_possible = bool(suffix_min_low[scan_start] <= cand.stop_price)
            target_possible = bool(suffix_max_high[scan_start] >= cand.target_price)
        else:
            stop_possible = bool(suffix_max_high[scan_start] >= cand.stop_price)
            target_possible = bool(suffix_min_low[scan_start] <= cand.target_price)
        if not stop_possible and not target_possible:
            # The stop and the target are both still out of reach at the end
            # of the sample; the reference's break-even level may still have
            # resolved the trade.
            cand.outcome = "open"
            cand.r_multiple = float("nan")
            if be_bar >= 0:
                cand.outcome = "break_even"
                cand.exit_bar = int(be_bar)
                cand.r_multiple = _realised_multiple(cand, float(cand.be_price))
            continue
        bar = _first_hit(
            low,
            high,
            scan_start,
            cand.side,
            cand.stop_price,
            cand.target_price,
            end=scan_end,
        )
        if bar < 0:
            # Neither the stop nor the target was reached within the horizon:
            # the setup is censored, not a loss.
            cand.outcome = "expired"
            cand.r_multiple = float("nan")
            if be_bar >= 0:
                # The reference closes the trade at the leg origin (its
                # "B.E." exit, ``pine:L476-491``): the setup *did* resolve,
                # just not at our stop or target.  The D2 label vocabulary has
                # no code for that third closed state, so the row keeps the
                # censored label ``-1`` -- the same value the ML pipeline's
                # ``build_labels`` gives it (F6).
                cand.outcome = "break_even"
                cand.exit_bar = int(be_bar)
                cand.r_multiple = _realised_multiple(cand, float(cand.be_price))
            continue
        hit_stop = (low[bar] <= cand.stop_price) if cand.side > 0 else (high[bar] >= cand.stop_price)
        if hit_stop:
            cand.outcome = "stop"
            cand.r_multiple = -1.0
        else:
            cand.outcome = "target"
            # The realised multiple is the **actual** target distance, which
            # follows the regime's RR when one is attached -- not the config's.
            cand.r_multiple = (cand.target_price - cand.entry_price) * cand.side / cand.risk
        cand.exit_bar = bar


def _realised_multiple(cand: Candidate, exit_price: float) -> float:
    """The realised multiple of a candidate that closed at ``exit_price``."""
    risk = float(cand.risk)
    if not math.isfinite(risk) or risk <= 0.0:
        return float("nan")
    return (float(exit_price) - float(cand.entry_price)) * int(cand.side) / risk


def _break_even_hit(bars: Bars, cand: Candidate, start: int, end: int) -> int:
    """The first bar at or after ``start`` that reaches the break-even level.

    The break-even level is the swing **origin** of the leg that produced the
    gap (``pine:L476``): for a long it is the swing high the bearish leg
    started from, for a short the swing low the bullish leg started from.  The
    reference closes the trade when price gets back there.

    ``-1`` is returned when the level is unknown (no pivot yet) or when price
    never reached it inside ``[start, end)``.
    """
    level = cand.be_price
    if not math.isfinite(level):
        return -1
    if end <= start:
        return -1
    if cand.side > 0:
        hits = bars.high[start:end] >= level
    else:
        hits = bars.low[start:end] <= level
    if not hits.any():
        return -1
    return start + int(np.argmax(hits))


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
            cand = _price_candidate(bars, fvgs, i_fvg, confirm_bar, config)
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
        bars, config, side, c, confirm_bar, entry_price, gap_low, gap_high
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
