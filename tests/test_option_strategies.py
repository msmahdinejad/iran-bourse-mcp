"""Tests for option strategies, Black-Scholes Greeks, IV solver, visualizers and arbitrage scanner."""

from __future__ import annotations

import math

import pytest

from iran_bourse_mcp import derivatives as D
from iran_bourse_mcp import option_strategies as opt

AHRM = "اهرم"


@pytest.fixture()
def opts(fx):
    return fx("derivatives_option_watch")


# ------------------------------------------------------------------------------------------------ math & greeks


def test_normal_distribution_functions():
    assert math.isclose(opt.norm_cdf(0.0), 0.5, abs_tol=1e-7)
    assert math.isclose(opt.norm_cdf(5.0), 1.0, abs_tol=1e-6)
    assert math.isclose(opt.norm_cdf(-5.0), 0.0, abs_tol=1e-6)
    assert opt.norm_pdf(0.0) > 0.398


def test_black_scholes_pricing_and_put_call_parity():
    spot, strike, t_years, r, sigma = 22000.0, 24000.0, 45 / 365, 0.30, 0.40
    call = opt.bs_price(spot, strike, t_years, r, sigma, is_call=True)
    put = opt.bs_price(spot, strike, t_years, r, sigma, is_call=False)

    assert call > 0 and put > 0
    # Put-Call Parity: C - P = S - K * exp(-rT)
    expected_diff = spot - strike * math.exp(-r * t_years)
    assert math.isclose(call - put, expected_diff, abs_tol=1e-6)


def test_black_scholes_greeks_properties():
    spot, strike, t_years, r, sigma = 74000.0, 74000.0, 30 / 365, 0.30, 0.45
    call_g = opt.bs_greeks(spot, strike, t_years, r, sigma, is_call=True)
    put_g = opt.bs_greeks(spot, strike, t_years, r, sigma, is_call=False)

    assert 0.0 < call_g["delta"] < 1.0
    assert -1.0 < put_g["delta"] < 0.0
    # At-the-money Call delta minus Put delta is 1
    assert math.isclose(call_g["delta"] - put_g["delta"], 1.0, abs_tol=1e-2)

    # Gamma and Vega are identical for Call and Put
    assert call_g["gamma"] > 0
    assert math.isclose(call_g["gamma"], put_g["gamma"], abs_tol=1e-6)
    assert call_g["vega"] > 0
    assert math.isclose(call_g["vega"], put_g["vega"], abs_tol=1e-2)

    # Long options suffer negative theta decay
    assert call_g["theta"] < 0
    assert put_g["theta"] < 0


def test_implied_volatility_solver_accuracy():
    spot, strike, t_years, r, known_vol = 74000.0, 70000.0, 20 / 365, 0.30, 0.45
    call_mkt = opt.bs_price(spot, strike, t_years, r, known_vol, is_call=True)
    recovered_iv = opt.implied_volatility(spot, strike, t_years, r, call_mkt, is_call=True)
    assert recovered_iv is not None
    assert math.isclose(recovered_iv, 45.0, abs_tol=0.2)

    put_mkt = opt.bs_price(spot, strike, t_years, r, known_vol, is_call=False)
    recovered_put_iv = opt.implied_volatility(spot, strike, t_years, r, put_mkt, is_call=False)
    assert recovered_put_iv is not None
    assert math.isclose(recovered_put_iv, 45.0, abs_tol=0.2)

    # Negative / impossible price returns None
    assert opt.implied_volatility(spot, strike, t_years, r, -50.0, is_call=True) is None


# ------------------------------------------------------------------------------------------------ strategy evaluator


def test_bull_call_spread_evaluation():
    # Long Call 70,000 @ 8,000, Short Call 80,000 @ 3,000
    legs = [
        {"type": "call", "action": "buy", "strike": 70000, "premium": 8000, "contracts": 1, "size": 1000},
        {"type": "call", "action": "sell", "strike": 80000, "premium": 3000, "contracts": 1, "size": 1000},
    ]
    res = opt.evaluate_strategy("اهرم", 74000.0, legs, strategy_name="bull_call_spread", days_to_expiry=30)
    summary = res["summary"]

    # Net debit = (8000 - 3000) * 1000 = 5,000,000 Rial
    assert summary["net_premium_rial"] == -5000000
    assert summary["cash_flow_type"] == "debit"

    # Max profit = (80,000 - 70,000 - 5,000) * 1000 = 5,000,000 Rial
    assert summary["max_profit_rial"] == 5000000
    # Max loss = net debit = 5,000,000 Rial
    assert summary["max_loss_rial"] == -5000000
    # Break-even = 70,000 + 5,000 = 75,000 Rial
    assert summary["breakevens"] == [75000]

    # Visualizers exist
    assert "Profit (Rial)" in res["ascii_chart"]
    assert "<svg" in res["svg_chart"] and "</svg>" in res["svg_chart"]
    assert len(res["payoff_curve"]) >= 25


def test_covered_call_evaluation():
    legs = [
        {"type": "stock", "action": "buy", "entry_price": 74000, "contracts": 1, "size": 1000},
        {"type": "call", "action": "sell", "strike": 80000, "premium": 2500, "contracts": 1, "size": 1000},
    ]
    res = opt.evaluate_strategy("اهرم", 74000.0, legs, strategy_name="covered_call", days_to_expiry=30)
    summary = res["summary"]

    # Max profit is capped at strike: (80000 - 74000 + 2500) * 1000 = 8,500,000 Rial
    assert summary["max_profit_rial"] == 8500000
    # Break-even = 74000 - 2500 = 71500
    assert summary["breakevens"] == [71500]
    assert summary["max_loss_rial"] != "unlimited"  # Stock cannot go below zero


def test_long_straddle_evaluation():
    legs = [
        {"type": "call", "action": "buy", "strike": 74000, "premium": 3000, "contracts": 1, "size": 1000},
        {"type": "put", "action": "buy", "strike": 74000, "premium": 2500, "contracts": 1, "size": 1000},
    ]
    res = opt.evaluate_strategy("اهرم", 74000.0, legs, strategy_name="long_straddle", days_to_expiry=30)
    summary = res["summary"]

    assert summary["max_profit_rial"] == "unlimited"
    assert summary["max_loss_rial"] == -5500000
    # Two breakevens: 74000 - 5500 = 68500, 74000 + 5500 = 79500
    assert summary["breakevens"] == [68500, 79500]


# ------------------------------------------------------------------------------------------------ arbitrage scanner


def test_arbitrage_scanner_on_fixture(opts):
    parsed = D._parse_option_rows(opts)
    arb = opt.scan_option_arbitrage(parsed, max_days=90, min_yield_pct=20.0)

    assert "total_box_spreads" in arb
    assert "total_below_intrinsic" in arb
    assert "parity_discrepancies" in arb
    assert isinstance(arb["box_spread_opportunities"], list)

    # Box spread opportunities have legs, strikes, terminal_value_rial, and estimated_annualized_yield_pct
    if arb["box_spread_opportunities"]:
        first_box = arb["box_spread_opportunities"][0]
        assert "strikes" in first_box
        assert first_box["terminal_value_rial"] > 0
        assert first_box["estimated_annualized_yield_pct"] >= 20.0
        assert len(first_box["legs"]) == 4


# ------------------------------------------------------------------------------------------------ integration with D


def test_option_chain_includes_greeks_when_requested(opts):
    chain_with_greeks = D.option_chain(opts, AHRM, include_greeks=True)
    grp = chain_with_greeks["groups"][0]
    active_calls = [s["call"] for s in grp["strikes"] if s.get("call") and s["call"].get("close")]
    assert active_calls

    first_call_derived = active_calls[0]["derived"]
    assert "greeks" in first_call_derived
    assert "iv_pct" in first_call_derived
    if first_call_derived["greeks"]:
        assert "delta" in first_call_derived["greeks"]
        assert "theta" in first_call_derived["greeks"]
        assert "vega" in first_call_derived["greeks"]


def test_derivatives_option_strategy_preset_builder(opts):
    res = D.option_strategy(opts, AHRM, strategy="covered_call")
    assert res["strategy"] == "covered_call"
    assert res["underlying"] == AHRM
    assert "summary" in res
    assert "ascii_chart" in res
    assert "svg_chart" in res
    assert "payoff_curve" in res


def test_derivatives_option_arbitrage_entrypoint(opts):
    arb = D.option_arbitrage(opts, max_days=90)
    assert "total_box_spreads" in arb
    assert "box_spread_opportunities" in arb
