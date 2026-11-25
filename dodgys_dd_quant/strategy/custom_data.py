"""The engine's exogenous signals as Nautilus ``Data`` objects (doc module #3).

The design doc's module map gives the regime index and the vision verdict
their own ``Data`` types so that they can ride the **engine's timeline**:
the volatility regime attached to a bar, and the vision layer's verdict
attached to a candidate.  Without them the two signals are columns of the
D2 log that no engine component can see.

The custom-data decorator is **not** in ``nautilus_trader.model.custom_data``
(that module does not exist in 1.221); the verified location is
``nautilus_trader.model.custom.customdataclass`` (``NAUTILUS_API.md`` §4).
"""

# NOTE: no ``from __future__ import annotations`` here -- Nautilus's
# ``customdataclass`` reads the field annotations as *types*, and the future
# import would turn them into strings (``NAUTILUS_API.md`` §4).

from nautilus_trader.core.data import Data
from nautilus_trader.model.custom import customdataclass

__all__ = ["RegimeSignal", "VisionSignal"]


@customdataclass
class RegimeSignal(Data):
    """The volatility regime that was in force at a bar's close.

    The values are the **lagged** ones: the regime index is published with a
    delay (a daily index is known the next day), so a bar never sees its own
    day's close (L3 trap 1).
    """

    #: The band: 0 low / 1 normal / 2 high, -1 unknown.
    regime: int
    #: The index level that produced the band.
    level: float
    #: The trailing percentile of the level within its own history.
    percentile: float
    #: How many days old the level is.
    stale_days: int
    #: Which index produced it (``VXN``, ``VIX``, ``DVOL`` ...).
    index_name: str


@customdataclass
class VisionSignal(Data):
    """The vision layer's verdict for one candidate.

    The layer is a **feature generator, not a gate** (D6): the verdict rides
    the timeline and the ML pipeline reads it, but no rule ever filters on
    it -- the detector's own labels carry no outcome information.
    """

    #: The 2-D body IoU against the third candle's body rectangle.
    vision_iou: float
    #: The detector's confidence for the matched box.
    vision_confidence: float
    #: ``|box_rows & body_rows| / |box_rows|`` -- the sharper diagnostic.
    row_containment: float
    #: The bar slot the matched box's centre falls on, minus the FVG's
    #: third-candle slot.  Must be 0 for a match to count.
    bar_index_delta: int
    #: Whether the detector's class agrees with the gap's direction.
    class_match: bool
    #: Whether the three-part gate passed.
    passed: bool
