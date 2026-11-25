"""The roll-boundary detector (Q5: "data sufficient, and how to roll?").

Q5's answer is that the NQ/ES 1-minute gap is multi-year **per-contract**
data with a roll rule, and the crypto lane is sufficient.  A continuous
series still needs the roll boundary *identified*: a contract switch leaves
a price gap that a rule engine will read as a liquidity sweep.

The detector is therefore deliberately conservative: it flags bars around
a **discontinuous price jump**, and the backtest excludes them and reports
how many it excluded (``n_roll_boundary_bars_excluded``).  It never
reprices anything -- the roll rule's job is to decide *which* contract to
use, and that decision needs per-contract data this repo does not have.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence

__all__ = ["RollFilter", "RollBoundary"]


class RollBoundary:
    """One detected roll boundary."""

    __slots__ = ("index", "ts", "previous_close", "open", "gap_frac")

    def __init__(
        self,
        index: int,
        ts: int,
        previous_close: float,
        open: float,
        gap_frac: float,
    ) -> None:
        self.index = index
        self.ts = ts
        self.previous_close = previous_close
        self.open = open
        self.gap_frac = gap_frac

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "ts": self.ts,
            "previous_close": self.previous_close,
            "open": self.open,
            "gap_frac": self.gap_frac,
        }


class RollFilter:
    """Finds the bars around a contract roll and excludes them.

    Parameters
    ----------
    price_gap_frac:
        The relative size of the jump that marks a roll.  The default is
        1 %: a continuous futures series rarely gaps more than that on
        its own, while a contract switch routinely gaps several percent.
    bars_around:
        How many bars on each side of the boundary are excluded.  The
        bars immediately after a roll carry the new contract's opening
        range, which is not comparable with the old contract's.
    """

    def __init__(
        self,
        *,
        price_gap_frac: float = 0.01,
        bars_around: int = 2,
    ) -> None:
        if price_gap_frac <= 0.0:
            raise ValueError("price_gap_frac must be positive")
        if bars_around < 0:
            raise ValueError("bars_around must not be negative")
        self.price_gap_frac = float(price_gap_frac)
        self.bars_around = int(bars_around)

    # --- detection ---------------------------------------------------------

    def boundaries(self, bars: Sequence[Mapping[str, Any]]) -> list[RollBoundary]:
        """The roll boundaries in the series."""
        out: list[RollBoundary] = []
        previous_close: float | None = None
        for index, bar in enumerate(bars):
            open_price = float(bar["open"])
            if previous_close is not None and previous_close > 0.0:
                gap = abs(open_price - previous_close) / previous_close
                if gap >= self.price_gap_frac:
                    out.append(
                        RollBoundary(
                            index=index,
                            ts=int(bar["ts"]),
                            previous_close=previous_close,
                            open=open_price,
                            gap_frac=gap,
                        )
                    )
            close = bar.get("close")
            if close is not None and math.isfinite(float(close)):
                previous_close = float(close)
        return out

    def excluded_bars(self, bars: Sequence[Mapping[str, Any]]) -> set[int]:
        """The indices of the bars to exclude: the boundary and its neighbours."""
        n = len(bars)
        excluded: set[int] = set()
        for boundary in self.boundaries(bars):
            start = max(0, boundary.index - self.bars_around)
            stop = min(n, boundary.index + self.bars_around + 1)
            excluded.update(range(start, stop))
        return excluded

    def filter(
        self,
        bars: Sequence[Mapping[str, Any]],
    ) -> tuple[list[Mapping[str, Any]], int]:
        """The bars with the roll boundaries removed, and how many were removed."""
        excluded = self.excluded_bars(bars)
        kept = [bar for index, bar in enumerate(bars) if index not in excluded]
        return kept, len(excluded)
