"""The data layer: turning raw market data into a governed, roll-aware series.

Module #1 of the planned layout (``diagram-目录结构规划.svg``).  Nothing in
this package decides what to trade: it decides **which bars are comparable**.
"""

from __future__ import annotations

from dodgys_dd_quant.data_pipeline.roll import RollBoundary, RollFilter

__all__ = ["RollBoundary", "RollFilter"]
