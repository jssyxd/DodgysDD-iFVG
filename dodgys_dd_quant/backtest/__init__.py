"""The backtest harness: costs, the rolling walk-forward and the entry point.

Nothing in this package decides *what* to trade — that is the rule engine's
job (``dodgys_dd_quant.strategy``).  This package decides **how the trades are
accounted for**: one position at a time (D4), costs charged inside the trade
(D9), a forward-only model (D3) and a multiple-testing correction on the
resulting Sharpe.
"""

from dodgys_dd_quant.backtest.cost_model import (
    COST_PROFILES,
    CostProfile,
    break_even_cost_r,
    cost_in_r,
    get_profile,
    round_trip_cost,
)
from dodgys_dd_quant.backtest.walk_forward import (
    Fold,
    FoldReport,
    ForwardOnlyViolation,
    ModelScorer,
    TradeStats,
    WalkForwardReport,
    assert_forward_only,
    deflated_sharpe,
    load_walk_forward_index,
    simulate_portfolio,
    summarise_trades,
    walk_forward,
)

__all__ = [
    "COST_PROFILES",
    "CostProfile",
    "Fold",
    "FoldReport",
    "ForwardOnlyViolation",
    "ModelScorer",
    "TradeStats",
    "WalkForwardReport",
    "assert_forward_only",
    "break_even_cost_r",
    "cost_in_r",
    "deflated_sharpe",
    "get_profile",
    "load_walk_forward_index",
    "round_trip_cost",
    "simulate_portfolio",
    "summarise_trades",
    "walk_forward",
]
