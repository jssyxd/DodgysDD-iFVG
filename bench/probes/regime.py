"""Regime probes -- Q4 (is VXN/VIX correlated and wired in?).

The audit's answer was blunt: **no, on all five paths**.

```
CORRELATION CHECK IMPLEMENTED:  no
REGIME IN STRATEGY:             no
REGIME IN ORDER DECISION:       no
REGIME IN ML FEATURES:          no
REGIME IN RL STATE:             no
```

VXN is now ingested and governed (CBOE official, 4,327 daily bars, one-day
lag enforced), but **no correlation test has been run** and the regime
never reaches an order.  These probes cover both halves:

* **the correlation test** (L3 §C.2): a per-band expectancy with
  cluster-robust errors and a **moving-block permutation** p-value --
  the test that respects time ordering, which the audit specified but never
  executed;
* **the wiring** (the five paths above), each checked by observing the
  value actually reach the decision.
"""

from __future__ import annotations

import math

from bench.probes import register

__all__ = []


@register(
    "regime.correlation_test_runs",
    "regime",
    16,
    "a regime correlation test exists and runs: per-band E[R] with a permutation p-value",
)
def _correlation_test() -> tuple[bool, str]:
    """The deliverable L3 §C.2 specifies and the audit says was never run."""
    import importlib

    module = None
    for name in (
        "dodgys_dd_quant.analysis.regime_correlation",
        "dodgys_dd_quant.strategy.regime_correlation",
        "dodgys_dd_quant.backtest.regime_correlation",
    ):
        try:
            module = importlib.import_module(name)
        except Exception:
            continue
        break
    if module is None:
        return False, (
            "no regime-correlation module "
            "(dodgys_dd_quant.analysis.regime_correlation)"
        )

    fn = None
    for attr in ("regime_correlation_test", "correlation_test", "band_expectancy_test"):
        candidate = getattr(module, attr, None)
        if callable(candidate):
            fn = candidate
            break
    if fn is None:
        return False, f"{module.__name__} exposes no correlation-test function"

    from bench import fixtures

    labelled = fixtures.labelled_frame()
    try:
        result = fn(labelled)
    except TypeError:
        try:
            result = fn(labelled, regime_column="vxn_regime")
        except Exception as exc:
            return False, f"the correlation test failed: {type(exc).__name__}: {exc}"
    except Exception as exc:
        return False, f"the correlation test failed: {type(exc).__name__}: {exc}"

    if not isinstance(result, dict):
        return False, f"the correlation test returned {type(result).__name__}, expected a dict"
    bands = result.get("bands")
    if not isinstance(bands, dict) or len(bands) < 2:
        return False, f"no per-band results (got {bands!r})"
    p_value = result.get("p_value", result.get("p_value_permutation"))
    if p_value is None:
        return False, "the result carries no p-value"
    p_value = float(p_value)
    if not (0.0 <= p_value <= 1.0):
        return False, f"p_value = {p_value}, expected a probability"
    return True, f"{len(bands)} bands, permutation p={p_value:.4f}"


@register(
    "regime.reaches_order_decision",
    "regime",
    12,
    "the regime changes the trade parameters (RR / ATR floor / risk), not just a feature",
)
def _reaches_decision() -> tuple[bool, str]:
    """F10: ``REGIME_PARAMETERS`` is implemented but **never called**.

    The observable consequence: attaching a *low-volatility* regime and a
    *high-volatility* regime to the engine must change the trades it
    produces -- the doc's policy is RR 1:1.5-1:2 in the low band and a
    raised ATR floor plus halved risk in the high band.
    """
    from dodgys_dd_quant.strategy.regime import ConstantRegimeIndex, regime_parameters
    from dodgys_dd_quant.strategy.state_machine import RuleConfig, run_state_machine

    bars = _bars()
    config = RuleConfig(symbol="BTCUSDT")

    def ratios_for(regime: int) -> set[float]:
        index = ConstantRegimeIndex(value=30.0, regime=regime)
        log = run_state_machine(bars, config, regime=index)
        return {
            round((c.target_price - c.entry_price) / c.risk, 4)
            for c in log
            if c.risk > 0
        }

    low = ratios_for(0)
    high = ratios_for(2)
    if not low or not high:
        return False, "no candidates produced"
    if low == high:
        return False, (
            f"the low-vol and high-vol regimes produce the same target distances "
            f"({sorted(low)}) -- the regime never reaches the order decision"
        )
    expected_low = round(regime_parameters(0).rr, 4)
    expected_high = round(regime_parameters(2).rr, 4)
    if expected_low not in low or expected_high not in high:
        return False, (
            f"the regime RR table is not honoured: low={sorted(low)} (expected "
            f"{expected_low}), high={sorted(high)} (expected {expected_high})"
        )
    return True, f"the regime drives the RR: low={sorted(low)}, high={sorted(high)}"


@register(
    "regime.parameters_are_used",
    "regime",
    8,
    "the regime parameter table is actually called somewhere (F10)",
)
def _parameters_used() -> tuple[bool, str]:
    """``regime_parameters`` must be *called* by the engine or the backtest.

    The audit found it defined and referenced nowhere outside its own
    definition -- an inert table.
    """
    import ast
    from pathlib import Path

    import dodgys_dd_quant

    package = Path(dodgys_dd_quant.__file__).resolve().parent
    callers: list[str] = []
    for path in sorted(package.rglob("*.py")):
        if path.name == "regime.py" and "def regime_parameters" in path.read_text(encoding="utf-8"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                if name == "regime_parameters":
                    callers.append(str(path.relative_to(package.parent)))
    if not callers:
        return False, "regime_parameters() is never called -- the table is inert"
    return True, f"regime_parameters() is called from {callers}"


@register(
    "regime.in_ml_features",
    "regime",
    10,
    "the regime reaches the ML feature table (vxn_level / vxn_regime)",
)
def _in_ml_features() -> tuple[bool, str]:
    from dodgys_dd_quant.ml_pipeline.features import FEATURE_LIST, build_features

    import pandas as pd

    candidates = pd.DataFrame(
        {
            "ts_event": [1_700_000_000_000_000_000],
            "side": [1],
            "entry_price": [100.0],
            "stop_price": [99.0],
            "target_price": [102.0],
            "risk": [1.0],
            "vxn_known": [22.0],
        }
    )
    frame = build_features(candidates)
    if "vxn_level" not in frame.columns:
        return False, "build_features does not produce vxn_level"
    if "vxn_regime" not in frame.columns:
        return False, "build_features does not produce vxn_regime"
    if "vxn_level" not in FEATURE_LIST:
        return False, "vxn_level is not in the declared feature list"
    level = float(frame["vxn_level"].iloc[0])
    regime = int(frame["vxn_regime"].iloc[0])
    if not math.isclose(level, 22.0):
        return False, f"vxn_level came out as {level}, expected the logged 22.0"
    if regime != 1:
        return False, f"vxn_regime came out as {regime} for a level of 22.0, expected 1"
    return True, "vxn_level and vxn_regime reach the feature table"


@register(
    "regime.index_is_pluggable",
    "regime",
    8,
    "the regime index is an interface: a different series can be plugged in",
)
def _pluggable() -> tuple[bool, str]:
    from dodgys_dd_quant.strategy.regime import ConstantRegimeIndex, RegimeIndex

    if not issubclass(ConstantRegimeIndex, RegimeIndex):
        return False, "ConstantRegimeIndex does not implement the RegimeIndex interface"
    index = ConstantRegimeIndex(value=30.0, regime=2)
    import numpy as np

    known, labels = index.value_at(np.asarray([1_700_000_000_000_000_000], dtype=np.int64))
    if int(labels[0]) != 2:
        return False, f"the constant index returned regime {int(labels[0])}, expected 2"
    return True, "the regime index is an interface with a pluggable implementation"


@register(
    "regime.no_future_backfill",
    "regime",
    8,
    "the regime is not back-filled from the future (L3 trap 2): the head is dropped",
)
def _no_backfill() -> tuple[bool, str]:
    from dodgys_dd_quant.strategy.regime import VxnRegimeIndex

    from bench import fixtures

    days, closes = fixtures.vxn_daily()
    index = VxnRegimeIndex(days=days, closes=closes)
    import numpy as np

    first_day = days[0]
    bar_ts = np.asarray([first_day * 86_400_000_000_000], dtype=np.int64)
    known, _ = index.value_at(bar_ts)
    if math.isfinite(float(known[0])):
        return False, "the first day of the index carries a value back-filled from the future"
    return True, "the first day carries no value (no back-fill)"


@register(
    "regime.stale_days_is_visible",
    "regime",
    8,
    "a carried-forward regime is marked with its age (stale_days), per L3 trap 2",
)
def _stale_days() -> tuple[bool, str]:
    import importlib

    module = None
    for name in (
        "dodgys_dd_quant.strategy.regime",
        "dodgys_dd_quant.analysis.regime_correlation",
    ):
        try:
            module = importlib.import_module(name)
        except Exception:
            continue
        break
    if module is None:
        return False, "no regime module"
    if not hasattr(module, "RegimeState"):
        return False, "no RegimeState dataclass carrying stale_days"
    fields = getattr(module.RegimeState, "__dataclass_fields__", {})
    for name in ("stale_days", "percentile", "known_at_ns"):
        if name not in fields:
            return False, f"RegimeState has no {name} field"
    return True, "RegimeState carries stale_days, percentile and known_at_ns"


def _bars():
    from bench import fixtures

    return fixtures.btc_1m()
