"""The RL state -- market-agnostic and lagged (L4 §D.2).

The state is what the policy observes.  Every component is either
**R-normalised** (scale-free) or dimensionless, so the state vector has the
same meaning on every market -- the precondition L4 §D.4 sets for any
transfer of a policy.

The one component the doc names that the lake cannot supply for every
market is the **order-book imbalance**: the only multi-year OFI series in
the project is BTC-only (``bar_ofi``) and it is not in the canonical lake.
L4 §D.3's first option is to replace it with a price-derived,
market-agnostic proxy -- the **close-location value**
``(close - low) / (high - low)``, which every market has.  That is what
this module uses.

Every value here is known at the bar's close, so nothing looks ahead.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["RLState", "build_state", "close_location_value"]


@dataclass(frozen=True, slots=True)
class RLState:
    """The state vector the policy observes."""

    #: The unrealised P&L in R (scale-free).
    open_pnl_r: float
    #: The largest unrealised P&L reached, in R (scale-free).
    peak_pnl_r: float
    #: The regime band: 0 low / 1 normal / 2 high.
    vxn_regime: int
    #: The holding time in bars, normalised by the episode's maximum.
    holding_time_bars: float
    #: The order-flow imbalance proxy, in [-1, 1] (the close-location value).
    order_book_imbalance: float

    def as_vector(self) -> np.ndarray:
        """The state as a flat float array."""
        return np.asarray(
            [
                self.open_pnl_r,
                self.peak_pnl_r,
                float(self.vxn_regime),
                self.holding_time_bars,
                self.order_book_imbalance,
            ],
            dtype=np.float64,
        )


def close_location_value(high: float, low: float, close: float) -> float:
    """``(close - low) / (high - low)``, in [0, 1].

    This is the market-agnostic imbalance proxy L4 §D.3 proposes in place of
    a market-specific order-book imbalance.
    """
    span = float(high) - float(low)
    if span <= 0.0:
        return 0.0
    value = (float(close) - float(low)) / span
    return min(1.0, max(0.0, value))


def build_state(
    *,
    entry_price: float,
    current_price: float,
    risk: float,
    peak_price: float,
    regime: int,
    holding_bars: int,
    max_holding_bars: int,
    high: float,
    low: float,
    close: float,
) -> RLState:
    """Build the state at one bar's close.

    Parameters
    ----------
    entry_price, current_price, risk:
        The position's entry, its current price and its risk unit (``R``).
    peak_price:
        The most favourable price the position has reached.
    regime:
        The regime band (0/1/2), lagged like every other input.
    holding_bars, max_holding_bars:
        The holding time and the episode's cap, so the time feature is
        dimensionless.
    high, low, close:
        The current bar's prices, for the imbalance proxy.
    """
    unit = float(risk) if risk > 0 else 1.0
    open_pnl_r = (float(current_price) - float(entry_price)) / unit
    peak_pnl_r = (float(peak_price) - float(entry_price)) / unit
    horizon = float(max_holding_bars) if max_holding_bars > 0 else 1.0
    return RLState(
        open_pnl_r=float(open_pnl_r),
        peak_pnl_r=float(peak_pnl_r),
        vxn_regime=int(regime),
        holding_time_bars=min(1.0, float(holding_bars) / horizon),
        order_book_imbalance=close_location_value(high, low, close),
    )
