"""Costs, isolated from the strategy (D9).

Fees and slippage live **here and only here** — never in the rule engine.  The
same profile is used by the backtest and by any paper run, so the two cannot
drift apart.

The D9 contract
---------------
* NQ: tick 0.25 pt = **$5.00**, multiplier **$20**, fee ≈ **$4.50** round trip
  ⇒ **$9.50 / $14.50 / $19.50** at 0 / 1 / 2 ticks of slippage.
* Binance USDT-M futures: taker **0.04 %**/side ⇒ **0.08 %** round trip, plus
  slippage.

The slippage is quoted **per round trip** (1 tick ⇒ one tick of total slippage,
not one tick per side), which is how the D9 numbers above are built.

Why the round-trip cost in R matters
------------------------------------
The measured gross edge of the rule engine is **≤ 0.052 R** (D4).  Unless one
unit of risk is large relative to the round trip, the edge is consumed by costs
alone.  Every report therefore prints the **break-even round-trip cost in R**
next to the expectancy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

__all__ = [
    "BINANCE_TICKS",
    "CostProfile",
    "COST_PROFILES",
    "get_profile",
    "profile_for",
    "round_trip_cost",
    "cost_in_r",
    "break_even_cost_r",
    "summarise_costs",
]


@dataclass(frozen=True)
class CostProfile:
    """The cost model of one instrument family.

    Attributes
    ----------
    tick_size:
        Price increment of one tick (``None`` for a purely percentage model).
    tick_value:
        Currency value of one tick per unit of quantity.
    multiplier:
        Contract multiplier (1 for a cash/perpetual unit).
    fee_round_trip:
        Fixed round-trip fee in currency.
    fee_pct_per_side:
        Percentage fee charged on each side (``None`` for a fixed-fee model).
    """

    name: str
    tick_size: float | None = None
    tick_value: float | None = None
    multiplier: float = 1.0
    fee_round_trip: float = 0.0
    fee_pct_per_side: float | None = None
    #: Ticks of crossing cost that are **always** charged, on top of the
    #: requested slippage.  D9's ladder ($9.50 / $14.50 / $19.50 at 0 / 1 / 2
    #: ticks for NQ) only reproduces with one tick of crossing in the baseline:
    #: $4.50 fee + 1 x $5.00 = $9.50, + 2 x $5.00 = $14.50, + 3 x $5.00 =
    #: $19.50.  A percentage-based profile (Binance) already contains the
    #: exchange's own crossing in the taker fee, so its baseline is 0.
    base_crossing_ticks: int = 0
    description: str = ""

    # -- cost components ---------------------------------------------------

    def fee(self, price: float, quantity: float = 1.0) -> float:
        """Round-trip fee in currency."""
        if self.fee_pct_per_side is not None:
            return 2.0 * self.fee_pct_per_side * price * quantity * self.multiplier
        return self.fee_round_trip * quantity

    def slippage(self, slippage_ticks: int = 0, quantity: float = 1.0) -> float:
        """Round-trip slippage in currency (D9 quotes slippage per round trip)."""
        ticks = self.base_crossing_ticks + max(0, slippage_ticks)
        if ticks <= 0:
            return 0.0
        if self.tick_value is None:
            raise ValueError(f"profile '{self.name}' has no tick value")
        return ticks * self.tick_value * quantity

    def round_trip(self, price: float, slippage_ticks: int = 0, quantity: float = 1.0) -> float:
        """Total round-trip cost in currency."""
        return self.fee(price, quantity) + self.slippage(slippage_ticks, quantity)

    def cost_in_r(
        self,
        price: float,
        risk: float,
        slippage_ticks: int = 0,
        quantity: float = 1.0,
    ) -> float:
        """Round-trip cost expressed in **R** (the risk unit of that trade).

        ``risk`` is the price distance between the entry and the stop, per unit
        of quantity; the currency risk is ``risk * quantity * multiplier``.
        """
        if risk <= 0.0:
            return float("nan")
        currency_risk = risk * quantity * self.multiplier
        return self.round_trip(price, slippage_ticks, quantity) / currency_risk


#: The instrument families the project cares about.
COST_PROFILES: dict[str, CostProfile] = {
    "nq": CostProfile(
        name="nq",
        tick_size=0.25,
        tick_value=5.00,
        multiplier=20.0,
        fee_round_trip=4.50,
        base_crossing_ticks=1,
        description="E-mini Nasdaq-100: 0.25 pt tick = $5.00, $20 multiplier, ~$4.50 round trip",
    ),
    "mes": CostProfile(
        name="mes",
        tick_size=0.25,
        tick_value=1.25,
        multiplier=5.0,
        fee_round_trip=2.25,
        base_crossing_ticks=1,
        description="Micro E-mini S&P-500: 0.25 pt tick = $1.25, $5 multiplier, ~$2.25 round trip",
    ),
    "es": CostProfile(
        name="es",
        tick_size=0.25,
        tick_value=12.50,
        multiplier=50.0,
        fee_round_trip=4.50,
        base_crossing_ticks=1,
        description="E-mini S&P-500: 0.25 pt tick = $12.50, $50 multiplier, ~$4.50 round trip",
    ),
    # The micro contracts: same price series as NQ/ES (same underlying), a
    # fifth / tenth of the tick value, and retail commission instead of the
    # institutional $4.50 round turn.
    "mnq": CostProfile(
        name="mnq",
        tick_size=0.25,
        tick_value=0.50,
        multiplier=2.0,
        fee_round_trip=1.05,
        base_crossing_ticks=1,
        description="CME Micro Nasdaq-100 (MNQ): tick 0.25 pt = $0.50, "
                    "multiplier $2, ~$1.05 round-turn commission + 1 tick crossing",
    ),
    "mes": CostProfile(
        name="mes",
        tick_size=0.25,
        tick_value=1.25,
        multiplier=5.0,
        fee_round_trip=1.25,
        base_crossing_ticks=1,
        description="CME Micro S&P 500 (MES): tick 0.25 pt = $1.25, "
                    "multiplier $5, ~$1.25 round-turn commission + 1 tick crossing",
    ),
    "binance": CostProfile(
        name="binance",
        tick_size=0.10,
        tick_value=0.10,
        multiplier=1.0,
        fee_round_trip=0.0,
        fee_pct_per_side=0.0004,
        description="Binance USDT-M futures: taker 0.04 %/side = 0.08 % round trip",
    ),
}


#: The price tick of each Binance USDT-M perp, in quote currency.  A single
#: "0.10" cannot serve every symbol: on XRP (price ~0.5) it is 20 % of the
#: price, and one tick of slippage then reads as -12 R per trade.
BINANCE_TICKS: dict[str, float] = {
    "BTCUSDT": 0.10,
    "ETHUSDT": 0.01,
    "SOLUSDT": 0.01,
    "BNBUSDT": 0.01,
    "XRPUSDT": 0.0001,
    "DOGEUSDT": 0.00001,
}


def profile_for(symbol: str, name: str | None = None) -> CostProfile:
    """The cost profile of ``symbol``, with that symbol's own tick.

    ``name`` defaults to ``binance`` for a USDT perp and ``nq`` otherwise.
    """
    key = (name or ("binance" if symbol.upper().endswith("USDT") else "nq")).lower()
    base = get_profile(key)
    if key != "binance":
        return base
    tick = BINANCE_TICKS.get(symbol.upper())
    if tick is None or tick == base.tick_size:
        return base
    from dataclasses import replace as _replace

    # a linear USDT-M contract: one tick of price move is ``tick`` quote
    # currency per coin, so the tick's value equals its size
    return _replace(base, tick_size=tick, tick_value=tick)


def get_profile(name: str) -> CostProfile:
    """Look up a cost profile by name (case-insensitive)."""
    key = name.strip().lower()
    try:
        return COST_PROFILES[key]
    except KeyError as exc:
        raise KeyError(
            f"unknown cost profile '{name}'; known: {sorted(COST_PROFILES)}"
        ) from exc


def round_trip_cost(
    profile: CostProfile,
    price: float,
    slippage_ticks: int = 0,
    quantity: float = 1.0,
) -> float:
    """Round-trip cost in currency for one trade."""
    return profile.round_trip(price, slippage_ticks, quantity)


def cost_in_r(
    profile: CostProfile,
    price: float,
    risk: float,
    slippage_ticks: int = 0,
    quantity: float = 1.0,
) -> float:
    """Round-trip cost in R for one trade."""
    return profile.cost_in_r(price, risk, slippage_ticks, quantity)


def break_even_cost_r(gross_expectancy_r: float) -> float:
    """The average round-trip cost in R that would exactly offset the edge.

    If the gross expectancy is ``E`` R per trade, the break-even cost is ``E``
    R per trade: a cost of that size drives the net expectancy to zero.  A
    **negative** break-even cost means the strategy is negative before any
    cost is charged.
    """
    return float(gross_expectancy_r)


def summarise_costs(
    profile: CostProfile,
    prices: Sequence[float],
    risks: Sequence[float],
    slippage_ticks: int = 0,
) -> dict[str, float]:
    """Aggregate the cost actually charged across a set of trades.

    Returns the mean/median cost in R, the mean cost in currency and the
    break-even cost in R implied by the gross expectancy.
    """
    if not prices:
        return {
            "mean_cost_r": float("nan"),
            "median_cost_r": float("nan"),
            "max_cost_r": float("nan"),
            "mean_cost_currency": float("nan"),
            "break_even_cost_r": float("nan"),
        }
    costs_r = [
        cost_in_r(profile, p, r, slippage_ticks)
        for p, r in zip(prices, risks)
        if r and r > 0 and math.isfinite(r)
    ]
    costs_cur = [round_trip_cost(profile, p, slippage_ticks) for p in prices]
    if not costs_r:
        return {
            "mean_cost_r": float("nan"),
            "median_cost_r": float("nan"),
            "max_cost_r": float("nan"),
            "mean_cost_currency": float("nan"),
            "break_even_cost_r": float("nan"),
        }
    ordered = sorted(costs_r)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else 0.5 * (ordered[mid - 1] + ordered[mid])
    return {
        "mean_cost_r": sum(costs_r) / len(costs_r),
        "median_cost_r": float(median),
        "max_cost_r": max(costs_r),
        "mean_cost_currency": sum(costs_cur) / len(costs_cur),
        "break_even_cost_r": float("nan"),
    }
