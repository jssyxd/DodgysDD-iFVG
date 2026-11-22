"""The deterministic rule layer: structure, the rule engine and the regime index.

Nothing here performs I/O on behalf of the engine: the rule engine is a pure
function of the bar history.  The only I/O lives in the loaders
(:func:`dodgys_dd_quant.strategy.structure.load_bars`,
:func:`dodgys_dd_quant.strategy.regime.VxnRegimeIndex.from_parquet`).
"""

from dodgys_dd_quant.strategy.constants import (
    DECISION_THRESHOLD,
    DEFAULT_RR,
    DOC_INVERSION_WINDOW,
    INVERSION_WINDOW,
    KILLZONE_NY_AM,
    KILLZONE_NY_PM,
    MIN_GAP_ATR_MULT,
    VXN_REGIME_BINS,
    MarketParams,
    RegimeParameters,
    market_params,
)
from dodgys_dd_quant.strategy.regime import (
    ConstantRegimeIndex,
    DvolRegimeIndex,
    RegimeIndex,
    VxnRegimeIndex,
    regime_label,
    regime_parameters,
)
from dodgys_dd_quant.strategy.state_machine import (
    PRESETS,
    Candidate,
    CandidateLog,
    RuleConfig,
    run_state_machine,
)
from dodgys_dd_quant.strategy.structure import (
    Bars,
    atr_wilder,
    causal_pivots,
    detect_fvg,
    load_bars,
)

__all__ = [
    "Bars",
    "Candidate",
    "CandidateLog",
    "ConstantRegimeIndex",
    "DECISION_THRESHOLD",
    "DEFAULT_RR",
    "DOC_INVERSION_WINDOW",
    "DvolRegimeIndex",
    "INVERSION_WINDOW",
    "KILLZONE_NY_AM",
    "KILLZONE_NY_PM",
    "MIN_GAP_ATR_MULT",
    "MarketParams",
    "PRESETS",
    "RegimeIndex",
    "RegimeParameters",
    "RuleConfig",
    "VXN_REGIME_BINS",
    "VxnRegimeIndex",
    "atr_wilder",
    "causal_pivots",
    "detect_fvg",
    "load_bars",
    "market_params",
    "regime_label",
    "regime_parameters",
    "run_state_machine",
]
