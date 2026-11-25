"""Tests for the regime layer and the regime correlation test.

The regime must reach the **decision**, not just a feature column: the
doc's per-band policy (L107-109) says the low-volatility band trades a
1:1.5-1:2 target, the normal band 1:2.5-1:3 and the high-volatility
band halves the risk per trade and raises the ATR gap floor.

The correlation test is the deliverable the audit records as *"no
correlation check implemented: no"* (L3 §A.2).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from dodgys_dd_quant.analysis.regime_correlation import (
    holm_bonferroni,
    moving_block_permutation,
    regime_correlation_test,
)
from dodgys_dd_quant.strategy.constants import REGIME_PARAMETERS
from dodgys_dd_quant.strategy.regime import (
    ConstantRegimeIndex,
    RegimeSeries,
    RegimeState,
    VxnRegimeIndex,
    regime_parameters,
    regime_state,
)
from dodgys_dd_quant.strategy.state_machine import RuleConfig, run_state_machine

NS_PER_DAY = 86_400_000_000_000


def _bars(n: int = 4000, seed: int = 3):
    from bench import fixtures

    return fixtures.btc_1m().slice(0, n)


# ---------------------------------------------------------------------------
# The regime reaches the order
# ---------------------------------------------------------------------------


def test_the_regime_selects_the_target_distance():
    """The low-volatility band trades 1:1.5 and the high band 1:2."""
    bars = _bars()
    config = RuleConfig(symbol="BTCUSDT")

    def ratios(regime: int) -> set[float]:
        index = ConstantRegimeIndex(value=30.0, regime=regime)
        log = run_state_machine(bars, config, regime=index)
        return {
            round(abs(c.target_price - c.entry_price) / c.risk, 4)
            for c in log
            if c.risk > 0
        }

    low = ratios(0)
    high = ratios(2)
    assert low == {round(regime_parameters(0).rr, 4)}
    assert high == {round(regime_parameters(2).rr, 4)}
    assert low != high


def test_the_high_volatility_band_halves_the_risk():
    bars = _bars()
    config = RuleConfig(symbol="BTCUSDT")
    index = ConstantRegimeIndex(value=40.0, regime=2)
    log = run_state_machine(bars, config, regime=index)
    multipliers = {round(c.risk_multiplier, 4) for c in log}
    assert multipliers == {round(REGIME_PARAMETERS[2].risk_multiplier, 4)}
    assert REGIME_PARAMETERS[2].risk_multiplier < 1.0


def test_without_a_regime_the_config_still_decides():
    """No regime attached means the code-derived baseline, unchanged."""
    bars = _bars()
    config = RuleConfig(symbol="BTCUSDT", rr=2.0)
    log = run_state_machine(bars, config)
    ratios = {
        round(abs(c.target_price - c.entry_price) / c.risk, 4)
        for c in log
        if c.risk > 0
    }
    assert ratios == {2.0}
    assert {c.risk_multiplier for c in log} == {1.0}


# ---------------------------------------------------------------------------
# The regime state
# ---------------------------------------------------------------------------


def test_the_regime_state_carries_its_staleness():
    days = np.asarray([19_000, 19_001, 19_002], dtype=np.int64)
    closes = np.asarray([10.0, 20.0, 30.0])
    series = RegimeSeries(days=days, closes=closes)

    # Three days after the last observation.
    asof = int(days[-1]) * NS_PER_DAY + 3 * NS_PER_DAY
    state = regime_state("VXN", asof, series)
    assert isinstance(state, RegimeState)
    assert state.level == pytest.approx(30.0)
    assert state.stale_days == 3
    assert state.regime == 2
    assert state.index_name == "VXN"
    assert state.known_at_ns <= asof


def test_the_regime_state_is_never_back_filled():
    """Before the first observation there is no state at all (L3 trap 2)."""
    days = np.asarray([19_000], dtype=np.int64)
    series = RegimeSeries(days=days, closes=np.asarray([10.0]))
    assert regime_state("VXN", int(days[0]) * NS_PER_DAY, series) is None


def test_the_vxn_index_is_strictly_lagged():
    days = np.asarray([19_000, 19_001, 19_002], dtype=np.int64)
    closes = np.asarray([10.0, 20.0, 30.0])
    index = VxnRegimeIndex(days=days, closes=closes)
    # A bar on a given day sees the **previous** day's close, never its own.
    bar_ts = np.asarray([19_002 * NS_PER_DAY], dtype=np.int64)
    known, _ = index.value_at(bar_ts)
    assert float(known[0]) == pytest.approx(20.0)
    # The next day sees the most recent close.
    bar_ts = np.asarray([19_003 * NS_PER_DAY], dtype=np.int64)
    known, _ = index.value_at(bar_ts)
    assert float(known[0]) == pytest.approx(30.0)
    # The very first day has no prior observation: no back-fill.
    bar_ts = np.asarray([19_000 * NS_PER_DAY], dtype=np.int64)
    known, _ = index.value_at(bar_ts)
    assert not math.isfinite(float(known[0]))


# ---------------------------------------------------------------------------
# The correlation test
# ---------------------------------------------------------------------------


def _frame(bands, outcomes, ts=None):
    n = len(bands)
    if ts is None:
        ts = 19_000 * NS_PER_DAY + np.arange(n) * NS_PER_DAY
    return pd.DataFrame(
        {
            "ts_event": ts,
            "vxn_regime": bands,
            "label": outcomes,
            "r_multiple": outcomes.astype(float) * 2.0,
        }
    )


def test_the_correlation_test_separates_the_bands():
    """A band with a different outcome rate must be detected."""
    rng = np.random.default_rng(5)
    n = 3000
    bands = rng.integers(0, 3, n)
    # Band 2 wins twice as often as the others.
    win_p = np.where(bands == 2, 0.9, 0.4)
    outcomes = (rng.random(n) < win_p).astype(int)
    result = regime_correlation_test(_frame(bands, outcomes), replications=200)
    assert set(result["bands"]) == {0, 1, 2}
    assert result["bands"][2]["expectancy_r"] > result["bands"][0]["expectancy_r"]
    assert result["p_value"] < 0.10


def test_the_correlation_test_finds_nothing_in_noise():
    rng = np.random.default_rng(7)
    n = 3000
    bands = rng.integers(0, 3, n)
    outcomes = (rng.random(n) < 0.4).astype(int)
    result = regime_correlation_test(_frame(bands, outcomes), replications=200)
    assert result["p_value"] > 0.05


def test_the_permutation_uses_the_hit_scale():
    """The statistic must not be inflated by the band's own RR policy.

    The regime sets the target distance, so the raw ``r_multiple`` is not
    comparable across bands.  The test therefore runs on the hit scale.
    """
    rng = np.random.default_rng(11)
    n = 2000
    bands = rng.integers(0, 3, n)
    outcomes = (rng.random(n) < 0.4).astype(int)
    frame = _frame(bands, outcomes)
    # A regime-dependent RR would make the raw means differ by band alone.
    frame["r_multiple"] = np.where(bands == 2, 2.5, 2.0) * outcomes
    result = regime_correlation_test(frame, replications=200)
    assert result["outcome_scale"] == "hit"
    # The hit scale shows no effect, so the p-value must not be significant.
    assert result["p_value"] > 0.05


def test_the_holm_correction_is_monotone():
    result = holm_bonferroni([0.001, 0.02, 0.04, 0.3])
    assert result["family_size"] == 4
    adjusted = result["p_adjusted"]
    assert adjusted == sorted(adjusted)
    assert all(a >= p for a, p in zip(adjusted, [0.001, 0.02, 0.04, 0.3]))
    assert result["rejected"][0] is True
    assert result["rejected"][3] is False


def test_the_permutation_needs_more_than_one_cluster():
    result = moving_block_permutation(
        np.asarray([1.0, -1.0]),
        np.asarray([0, 1]),
        np.asarray([0, 0]),
        replications=10,
    )
    assert result.n_clusters == 1
    assert result.p_value == 1.0
