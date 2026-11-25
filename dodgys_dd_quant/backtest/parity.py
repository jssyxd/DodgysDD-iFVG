"""The paper stage's slippage-parity check (L4 §E, stage 8).

The doc demands "验证实盘滑点与回测一致性" -- *prove* that the live
slippage matches the backtest's.  The audit says the check must be a
**quantitative assertion**, not a vibe:

1. every paper fill records ``fill_price - decision_price`` in **ticks**;
2. the paper distribution is compared with the backtest fill model (0/1/2
   ticks, D9): ``median(paper_ticks) <= backtest_ticks + 1`` and
   ``P(paper_ticks > backtest_ticks + 2) < 0.05``;
3. the paper **fill rate** is compared with the backtest's (a backtest fills
   every market order, a live book does not) -- a gap above 10 % invalidates
   the P&L comparison;
4. the acceptance test is then re-run on the **paper** series.

This module implements 1-3.  Stage 4 is the acceptance test itself, which
the backtest already runs; running it on a paper series is a matter of
feeding the paper P&L into the same function.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

__all__ = [
    "ParityReport",
    "slippage_ticks",
    "slippage_parity",
]

#: The largest tolerated excess of the paper's median slippage over the
#: backtest's modelled slippage, in ticks.
MEDIAN_TOLERANCE_TICKS: int = 1

#: The largest tolerated probability of a paper fill slipping more than two
#: ticks beyond the model.
TAIL_PROBABILITY_LIMIT: float = 0.05

#: The largest tolerated gap between the paper's and the backtest's fill rate.
FILL_RATE_GAP_LIMIT: float = 0.10


@dataclass(frozen=True)
class ParityReport:
    """The outcome of one parity check."""

    #: How many paper fills were compared.
    n_fills: int
    #: The median slippage of the paper fills, in ticks.
    median_ticks: float
    #: The share of paper fills that slipped more than two ticks beyond the
    #: model.
    tail_probability: float
    #: The paper fill rate minus the backtest's (NaN when it was not given).
    fill_rate_gap: float
    #: Whether every criterion holds.
    passed: bool
    #: Why it failed (empty when it passed).
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_fills": self.n_fills,
            "median_ticks": self.median_ticks,
            "tail_probability": self.tail_probability,
            "fill_rate_gap": self.fill_rate_gap,
            "passed": self.passed,
            "reasons": list(self.reasons),
        }


def slippage_ticks(
    decision_prices: Sequence[float],
    fill_prices: Sequence[float],
    tick_size: float,
) -> list[float]:
    """The slippage of every fill, in ticks.

    The sign follows the trade: a **buy** that fills above the decision
    price and a **sell** that fills below it are both adverse, so the caller
    passes the prices already signed for the direction.
    """
    if tick_size <= 0.0:
        raise ValueError("tick_size must be positive")
    if len(decision_prices) != len(fill_prices):
        raise ValueError("the decision and fill series must be the same length")
    return [
        (float(fill) - float(decision)) / float(tick_size)
        for decision, fill in zip(decision_prices, fill_prices)
    ]


def _median(values: Sequence[float]) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2.0)


def slippage_parity(
    *,
    decision_prices: Sequence[float],
    fill_prices: Sequence[float],
    tick_size: float,
    backtest_ticks: int,
    backtest_fill_rate: float | None = None,
    paper_fill_rate: float | None = None,
) -> ParityReport:
    """Compare a paper stage's fills with the backtest's fill model.

    ``backtest_ticks`` is the slippage the backtest models (0, 1 or 2 ticks
    per D9's ladder); the paper's fills are the ones the live book got.
    """
    ticks = slippage_ticks(decision_prices, fill_prices, tick_size)
    reasons: list[str] = []

    if not ticks:
        return ParityReport(
            n_fills=0,
            median_ticks=float("nan"),
            tail_probability=float("nan"),
            fill_rate_gap=float("nan"),
            passed=False,
            reasons=("no paper fills to compare",),
        )

    median = _median(ticks)
    limit = float(backtest_ticks) + MEDIAN_TOLERANCE_TICKS
    if not (median <= limit):
        reasons.append(
            f"the paper's median slippage is {median:.2f} ticks, above the "
            f"tolerance {limit:.2f}"
        )

    tail_limit = float(backtest_ticks) + 2.0
    tail = sum(1 for value in ticks if value > tail_limit) / len(ticks)
    if not (tail < TAIL_PROBABILITY_LIMIT):
        reasons.append(
            f"{tail:.1%} of the paper fills slipped more than {tail_limit:.0f} "
            f"ticks beyond the model (limit {TAIL_PROBABILITY_LIMIT:.0%})"
        )

    gap = float("nan")
    if backtest_fill_rate is not None and paper_fill_rate is not None:
        gap = float(paper_fill_rate) - float(backtest_fill_rate)
        if abs(gap) > FILL_RATE_GAP_LIMIT:
            reasons.append(
                f"the paper fill rate differs from the backtest's by "
                f"{gap:+.1%} (limit {FILL_RATE_GAP_LIMIT:.0%})"
            )

    return ParityReport(
        n_fills=len(ticks),
        median_ticks=median,
        tail_probability=tail,
        fill_rate_gap=gap,
        passed=not reasons,
        reasons=tuple(reasons),
    )
