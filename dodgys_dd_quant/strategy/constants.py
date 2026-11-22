"""Every tunable threshold of the system, in one module.

`AGENTS.md`: *"Put all tunable thresholds in one constants module — never inline magic
numbers in logic."*  Nothing in this file has behaviour; it is a single source of
truth that the strategy, the regime layer, the cost model and the backtest all read.

Provenance tags used below
---------------------------
``DOC``   stated in ``iFVG几个模型的讨论.txt`` (the master design discussion).
``PINE``  stated in the reference replica ``research/github/IFVG-Ultimate-Dodgy/
          ifvgUltimatePlus.pine`` (read-only; cited as ``pine:L###``).
``L2``    established by the rule-fidelity audit ``research/audit/L2_RULES.md``.
``D#``    a frozen swarm decision from ``.herd-swarm/decisions.md``.

Two rule families exist and are **never merged** (L2 §E.2): ``DOC`` (the prose) and
``PINE``/``CODE`` (the executable replica).  Where they disagree, both values are
exposed and A/B'd by the backtest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# ---------------------------------------------------------------------------
# FVG geometry (DOC L121 / PINE L354-356) — the two sources agree here
# ---------------------------------------------------------------------------

#: Minimum gap width as a multiple of ATR(14).  ``DOC L121``: "缺口大小必须大于
#: 0.25 * ATR(14)" — strictly greater.  The Pine has **no** ATR filter at all
#: (``grep -ci atr`` -> 0), so ``None`` is a legal value meaning "no ATR floor".
MIN_GAP_ATR_MULT: Final[float | None] = 0.25

#: ATR lookback.  ``DOC L121``; Wilder RMA (see ``structure.atr_wilder``).
ATR_PERIOD: Final[int] = 14

#: The FVG is measured on **wicks** and is **strict**: a zero-width gap is not a
#: gap (DOC L121 ``<`` / ``>``; PINE L354-356).
FVG_GEOMETRY_STRICT: Final[bool] = True

# ---------------------------------------------------------------------------
# Inversion window — the code-derived and the doc-derived band
# ---------------------------------------------------------------------------
#
# L2 §A.5 proved that age 0 is *arithmetically impossible* under the Pine's own
# trigger predicate (a bullish FVG needs ``low[c] > high[c-2]`` while the age-0
# trigger needs ``close[c] < high[c-2]``, and ``close[c] >= low[c]``).  The
# effective code-derived window is therefore **(1, 15)**, not (0, 15).
#
# The doc's band is (7, 15) (``DOC L123``), but the "7" originates in the
# original indicator's own UI label (``pine:L9``: title "Allow 7 - 15 Candle
# IFVGs", tooltip "may form within 15 candles" — the two contradict each other).
# Both are exposed; neither is hard-coded into logic.

#: Code-derived effective lower bound of the confirmation-candle age.
INVERSION_MIN_BARS: Final[int] = 1

#: Code-derived upper bound of the confirmation-candle age (``pine:L658``
#: ``graceCandles = allowExtIFVG ? 15 : 6``).
INVERSION_MAX_BARS: Final[int] = 15

#: Doc-derived lower bound (``DOC L123``).
DOC_INVERSION_MIN_BARS: Final[int] = 7

#: Doc-derived upper bound (same as the code-derived one).
DOC_INVERSION_MAX_BARS: Final[int] = 15

#: The code-derived window, as a ``(min_age, max_age)`` pair.
INVERSION_WINDOW: Final[tuple[int, int]] = (INVERSION_MIN_BARS, INVERSION_MAX_BARS)

#: The doc-derived window, as a ``(min_age, max_age)`` pair.
DOC_INVERSION_WINDOW: Final[tuple[int, int]] = (
    DOC_INVERSION_MIN_BARS,
    DOC_INVERSION_MAX_BARS,
)

# ---------------------------------------------------------------------------
# Meta-label gate and risk
# ---------------------------------------------------------------------------

#: Probability-of-win gate applied by the meta-label filter (DOC L107 / the
#: four-layer diagram).  Owned by the ML leaf; the backtest only *applies* it.
DECISION_THRESHOLD: Final[float] = 0.58

#: Fixed risk/reward used by the phase-1 baseline (``DOC L170``: 固定 1:2).
DEFAULT_RR: Final[float] = 2.0

#: Cap on the number of tracked level/session records kept in memory.  Mirrors
#: the reference's ``MAX_SWING_HISTORY = 50`` (``pine:L74``).
MAX_SESSIONS: Final[int] = 50

# ---------------------------------------------------------------------------
# Killzones / sessions
# ---------------------------------------------------------------------------

#: NY AM killzone, ``America/New_York``, endpoint-inclusive (DOC L115, A21).
KILLZONE_NY_AM: Final[tuple[str, str]] = ("09:30", "11:30")

#: NY PM killzone, ``America/New_York``, endpoint-inclusive (DOC L115, A21).
KILLZONE_NY_PM: Final[tuple[str, str]] = ("13:30", "15:30")

#: Hard-coded exchange timezone used for every session test (``pine:L79``).
NY_TZ: Final[str] = "America/New_York"

#: RTH window used for the PDH/PDL and session-extreme bookkeeping.
RTH_ET: Final[tuple[str, str]] = ("09:30", "16:00")

#: London killzone used by GC (DOC migration table: "Windows shift to London
#: 03:00 ET").  Only the **start** is specified by the doc; the end time is an
#: invented value and is flagged as such.
KILLZONE_LONDON_ET: Final[tuple[str, str]] = ("03:00", "05:00")

#: COMEX killzone used by GC (DOC migration table: "COMEX 08:20 ET").  The end
#: time is invented, as above.
KILLZONE_COMEX_ET: Final[tuple[str, str]] = ("08:20", "09:20")

#: Crypto killzones (DOC migration table: "24/7; sweeps concentrate at 09:30 ET
#: and UTC 00:00").  The end times are invented.
KILLZONE_CRYPTO_ET: Final[tuple[str, str]] = ("09:30", "11:30")
KILLZONE_CRYPTO_UTC: Final[tuple[str, str]] = ("00:00", "02:00")

# ---------------------------------------------------------------------------
# Regime layer
# ---------------------------------------------------------------------------

#: VXN regime bin edges (DOC L265-266): ``0 / 18 / 28 / 200``.
VXN_REGIME_BINS: Final[tuple[float, float, float, float]] = (0.0, 18.0, 28.0, 200.0)

#: Regime labels: 0 low-vol range, 1 normal trend, 2 high-vol panic.
REGIME_LOW: Final[int] = 0
REGIME_NORMAL: Final[int] = 1
REGIME_HIGH: Final[int] = 2

#: Level at or above which the high-vol regime is considered "extreme".  The doc
#: defines three labels, so this only refines regime 2 and is reported, never
#: used as a fourth label.
VXN_REGIME_EXTREME: Final[float] = 200.0

# ---------------------------------------------------------------------------
# Checklist (D8 — report, never filter)
# ---------------------------------------------------------------------------

#: The five named checklist conditions of ``DOC L124-126`` (plus the two regime /
#: vision components of the doc's rubric).  Their **sum** is ``checklist_score``.
#: They are reported as a distribution and are **never** used as a filter.
CHECKLIST_CONDITIONS: Final[tuple[str, ...]] = (
    "smt_divergence",        # DOC L119
    "no_obstruction",         # DOC L125
    "liquidity_target_2r",    # DOC L126
    "vision_iou_pass",        # DOC L139 — always False: the vision layer does not
                              # exist (D12) and D6 replaced its metric
    "vxn_regime_normal",      # DOC L108
)

#: The doc's weighted rubric (RULE_SPEC §1.7).  Reported as a label only.
CHECKLIST_WEIGHTS: Final[dict[str, float]] = {
    "smt_divergence": 2.0,
    "no_obstruction": 1.0,
    "liquidity_target_2r": 1.0,
    "vision_iou_pass": 1.0,
    "vxn_regime_normal": 1.0,
}

#: Grade thresholds of the doc's rubric (RULE_SPEC §1.7).  Labels only.
GRADE_THRESHOLDS: Final[tuple[tuple[str, float], ...]] = (
    ("A+", 5.0),
    ("A", 4.0),
    ("B", 3.0),
    ("C", 0.0),
)

# ---------------------------------------------------------------------------
# Liquidity / structure tolerances
# ---------------------------------------------------------------------------

#: Price tolerance used to cluster equal-high / equal-low levels.  **Undefined in
#: every artefact** (L2 §C.3); the value below is an invented default expressed
#: as a fraction of ATR and is documented as such.
EQUAL_LEVEL_ATR_TOL: Final[float] = 0.10

#: The doc's checklist requires a liquidity target at *at least* 2R (DOC L126).
LIQUIDITY_TARGET_MIN_R: Final[float] = 2.0

#: Pivot lookback for the causal swing detector (the reference uses a 3-bar
#: fractal, ``pine:L350``; the adapted third-party detector uses 5).
SWING_FRACTAL: Final[int] = 3

#: Bars to the right of a pivot before it may be used.  A pivot at bar ``p`` is
#: only knowable at bar ``p + right``.
SWING_RIGHT_BARS: Final[int] = 2

# ---------------------------------------------------------------------------
# Sweep detection
# ---------------------------------------------------------------------------

#: The reference's sweep detector consumes every swept swing level exactly once
#: (``pine:L560-575``).  A level can therefore never be swept twice.
SWEEP_LEVELS_CONSUMED_ONCE: Final[bool] = True

#: The doc requires the body to close back inside the swept level ("扫止损");
#: the reference only tests the wick (``pine:L567``) and never inspects the body.
#: Both semantics are implemented; this is the default (doc-derived).
SWEEP_REQUIRES_BODY_RECLAIM: Final[bool] = True


# ---------------------------------------------------------------------------
# Per-market parameter table (DOC migration table, AGENTS.md "Market Expansion")
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarketParams:
    """Per-market rule parameters.

    Attributes
    ----------
    symbol:
        Canonical symbol.
    smt_reference:
        Instrument used for the SMT cross-check, or ``None`` when the market has
        no reference (recorded as ``smt_divergence = -1``, never guessed).
    regime_index:
        Name of the volatility index that drives the regime layer.
    atr_coefficient:
        Minimum-gap coefficient as a multiple of ATR(14).
    session_windows:
        Killzone windows as ``(timezone, start, end)`` triples.
    """

    symbol: str
    smt_reference: str | None
    regime_index: str
    atr_coefficient: float
    session_windows: tuple[tuple[str, str, str], ...]


MARKET_PARAMS: Final[dict[str, MarketParams]] = {
    "NQ": MarketParams(
        symbol="NQ",
        smt_reference="ES",
        regime_index="VXN",
        atr_coefficient=0.25,
        session_windows=(("America/New_York", *KILLZONE_NY_AM), ("America/New_York", *KILLZONE_NY_PM)),
    ),
    "MNQ": MarketParams(
        symbol="MNQ",
        smt_reference="ES",
        regime_index="VXN",
        atr_coefficient=0.25,
        session_windows=(("America/New_York", *KILLZONE_NY_AM), ("America/New_York", *KILLZONE_NY_PM)),
    ),
    "MES": MarketParams(
        symbol="MES",
        smt_reference="NQ",
        regime_index="VIX",
        atr_coefficient=0.20,
        session_windows=(("America/New_York", *KILLZONE_NY_AM), ("America/New_York", *KILLZONE_NY_PM)),
    ),
    "QQQ": MarketParams(
        symbol="QQQ",
        smt_reference="SPY",
        regime_index="VXN",
        atr_coefficient=0.25,
        session_windows=(("America/New_York", *KILLZONE_NY_AM), ("America/New_York", *KILLZONE_NY_PM)),
    ),
    "GC": MarketParams(
        symbol="GC",
        smt_reference="SI",
        regime_index="GVZ",
        atr_coefficient=0.25,
        session_windows=(("America/New_York", *KILLZONE_LONDON_ET), ("America/New_York", *KILLZONE_COMEX_ET)),
    ),
    "BTCUSDT": MarketParams(
        symbol="BTCUSDT",
        smt_reference="ETHUSDT",
        regime_index="DVOL",
        atr_coefficient=0.25,
        session_windows=(("America/New_York", *KILLZONE_CRYPTO_ET), ("UTC", *KILLZONE_CRYPTO_UTC)),
    ),
    "ETHUSDT": MarketParams(
        symbol="ETHUSDT",
        smt_reference="BTCUSDT",
        regime_index="DVOL",
        atr_coefficient=0.25,
        session_windows=(("America/New_York", *KILLZONE_CRYPTO_ET), ("UTC", *KILLZONE_CRYPTO_UTC)),
    ),
}


def market_params(symbol: str) -> MarketParams:
    """Return the parameter row for ``symbol``, falling back to a neutral row.

    An unknown symbol is **not** an error: the backtest must be able to run on a
    symbol the table does not know.  The fallback is explicit and carries no
    SMT reference (``smt_divergence = -1``).
    """
    try:
        return MARKET_PARAMS[symbol]
    except KeyError:
        return MarketParams(
            symbol=symbol,
            smt_reference=None,
            regime_index="VXN",
            atr_coefficient=MIN_GAP_ATR_MULT or 0.25,
            session_windows=(("America/New_York", *KILLZONE_NY_AM),),
        )


# ---------------------------------------------------------------------------
# Regime-driven parameters (DOC L107-109 + the migration table)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegimeParameters:
    """What the regime layer changes about a trade.

    ``DOC L107-109``: low volatility -> trade only the best setups with a
    1:1.5-1:2 target; normal -> 1:2.5-1:3; high -> halve the risk per trade and
    raise the minimum ATR gap threshold.

    The doc's "tighten to A+ only" (low volatility) is **not implementable**
    (D8: no artefact defines A+), and is therefore replaced by "tighten the ATR
    floor and the risk/reward".
    """

    rr: float
    atr_floor_mult: float
    risk_multiplier: float
    note: str


REGIME_PARAMETERS: Final[dict[int, RegimeParameters]] = {
    REGIME_LOW: RegimeParameters(
        rr=1.5,
        atr_floor_mult=0.375,
        risk_multiplier=1.0,
        note="low vol: A+ only is unimplementable (D8); tighten the ATR floor and the RR instead",
    ),
    REGIME_NORMAL: RegimeParameters(
        rr=2.5,
        atr_floor_mult=0.25,
        risk_multiplier=1.0,
        note="normal vol: RR 1:2.5-1:3 towards the opposite liquidity pool",
    ),
    REGIME_HIGH: RegimeParameters(
        rr=2.0,
        atr_floor_mult=0.375,
        risk_multiplier=0.5,
        note="high vol: halve the risk per trade, raise the minimum ATR gap threshold",
    ),
}


#: Minutes from local midnight to the US cash open (09:30 America/New_York).
#: D2 defines ``minutes_from_us_open`` as *signed* minutes since that open:
#: +90 == 11:00 ET, -60 == 08:30 ET, 0 == 09:30 ET. The sign is kept so a
#: pre-open candidate on a 24/7 market is visibly *before* the open.
US_OPEN_MINUTES: int = 9 * 60 + 30
