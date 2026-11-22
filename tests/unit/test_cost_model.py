"""Unit tests of the cost model (D9)."""

from __future__ import annotations

import pytest

from dodgys_dd_quant.backtest.cost_model import (
    COST_PROFILES,
    break_even_cost_r,
    cost_in_r,
    get_profile,
    round_trip_cost,
    summarise_costs,
)


def test_nq_profile_matches_the_d9_numbers():
    """$9.50 / $14.50 / $19.50 at 0 / 1 / 2 ticks (D9)."""
    nq = get_profile("nq")
    assert nq.tick_size == 0.25
    assert nq.tick_value == 5.00
    assert nq.multiplier == 20.0
    assert nq.fee_round_trip == 4.50

    assert round_trip_cost(nq, 20000.0, 0) == pytest.approx(9.50)
    assert round_trip_cost(nq, 20000.0, 1) == pytest.approx(14.50)
    assert round_trip_cost(nq, 20000.0, 2) == pytest.approx(19.50)


def test_es_profile_tick_value():
    es = get_profile("es")
    assert es.tick_value == 12.50
    assert es.multiplier == 50.0
    # $4.50 fee + the one-tick baseline crossing + the requested ticks
    assert round_trip_cost(es, 5000.0, 0) == pytest.approx(17.00)
    assert round_trip_cost(es, 5000.0, 1) == pytest.approx(29.50)
    assert round_trip_cost(es, 5000.0, 2) == pytest.approx(42.00)


def test_binance_profile_is_two_sides_of_four_basis_points():
    binance = get_profile("binance")
    assert binance.fee_pct_per_side == 0.0004
    price = 20000.0
    # 0.08 % round trip
    assert round_trip_cost(binance, price, 0) == pytest.approx(0.0008 * price)
    # the slippage is one tick of total round-trip cost
    assert round_trip_cost(binance, price, 1) == pytest.approx(0.0008 * price + 0.10)
    assert round_trip_cost(binance, price, 2) == pytest.approx(0.0008 * price + 0.20)


def test_cost_in_r_scales_with_the_risk_unit():
    """A tight stop makes the same fee a large fraction of R."""
    nq = get_profile("nq")
    wide = cost_in_r(nq, 20000.0, risk=200.0, slippage_ticks=1)
    tight = cost_in_r(nq, 20000.0, risk=20.0, slippage_ticks=1)
    assert wide == pytest.approx(14.50 / (200.0 * 20.0))
    assert tight == pytest.approx(14.50 / (20.0 * 20.0))
    assert tight == pytest.approx(wide * 10.0)


def test_break_even_cost_is_the_gross_expectancy():
    """The cost in R that exactly offsets the gross edge."""
    assert break_even_cost_r(0.05) == pytest.approx(0.05)
    assert break_even_cost_r(-0.02) == pytest.approx(-0.02)
    # a negative break-even cost means the strategy is negative before costs
    assert break_even_cost_r(-0.02) < 0.0


def test_summarise_costs_reports_the_mean_and_median():
    nq = get_profile("nq")
    prices = [20000.0, 20000.0]
    risks = [200.0, 100.0]
    out = summarise_costs(nq, prices, risks, slippage_ticks=0)
    assert out["mean_cost_currency"] == pytest.approx(9.50)
    assert out["mean_cost_r"] == pytest.approx(0.5 * (9.50 / 4000.0 + 9.50 / 2000.0))
    assert out["median_cost_r"] == pytest.approx(out["mean_cost_r"])


def test_unknown_profile_raises():
    with pytest.raises(KeyError):
        get_profile("nasdaq-something")


def test_every_profile_declares_its_cost_basis():
    for name, profile in COST_PROFILES.items():
        assert profile.name == name
        assert profile.fee_pct_per_side is not None or profile.fee_round_trip > 0.0
        if profile.fee_pct_per_side is None:
            assert profile.tick_value is not None and profile.tick_value > 0
