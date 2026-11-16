"""Option strategies, Greeks, implied volatility, payoff visualization, and near-deadline arbitrage scanner.

Provides:
- Black-Scholes pricing and analytical Greeks (Delta, Gamma, Theta, Vega, Rho) adjusted for Iran's risk-free rate.
- Fast numerical Implied Volatility (IV) solver using Newton-Raphson with bisection fallback.
- Multi-leg strategy evaluator with P&L curves, max profit, max loss, break-even analysis, and return metrics.
- Visualizers: ASCII terminal graph and standalone SVG chart for any strategy payoff profile.
- Near-deadline Arbitrage scanner: identifies discounted ITM options (below intrinsic value), high-yield
  box spreads (synthetic loans exceeding the Akhza benchmark), and Put-Call parity deviations.

Pure mathematics and data transformations; no network I/O.
"""

from __future__ import annotations

import math
from typing import Any

DAYS_PER_YEAR = 365
DEFAULT_RISK_FREE_RATE = 0.30  # 30% annual Akhza / fixed-income benchmark in Iran


# ------------------------------------------------------------------------------------------------ math helpers


def norm_cdf(x: float) -> float:
    """Cumulative distribution function for standard normal distribution N(0, 1)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x: float) -> float:
    """Probability density function for standard normal distribution N(0, 1)."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_price(spot: float, strike: float, t_years: float, r: float, sigma: float, is_call: bool) -> float:
    """Black-Scholes theoretical price of European option with risk-free rate r and volatility sigma."""
    if spot <= 0 or strike <= 0:
        return 0.0
    if t_years <= 0 or sigma <= 0:
        return max(0.0, spot - strike) if is_call else max(0.0, strike - spot)

    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t_years) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    df = math.exp(-r * t_years)

    if is_call:
        return spot * norm_cdf(d1) - strike * df * norm_cdf(d2)
    return strike * df * norm_cdf(-d2) - spot * norm_cdf(-d1)


def bs_greeks(spot: float, strike: float, t_years: float, r: float, sigma: float, is_call: bool) -> dict[str, float]:
    """Analytical Black-Scholes Greeks: Delta, Gamma, Theta (1-day), Vega (1% vol), Rho (1% rate)."""
    if spot <= 0 or strike <= 0:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

    if t_years <= 0 or sigma <= 0:
        delta = 1.0 if (is_call and spot > strike) else (-1.0 if (not is_call and spot < strike) else 0.0)
        return {"delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t_years) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    pdf_d1 = norm_pdf(d1)
    df = math.exp(-r * t_years)

    if is_call:
        delta = norm_cdf(d1)
        theta_annual = -(spot * pdf_d1 * sigma) / (2.0 * sqrt_t) - r * strike * df * norm_cdf(d2)
        rho_annual = strike * t_years * df * norm_cdf(d2)
    else:
        delta = norm_cdf(d1) - 1.0
        theta_annual = -(spot * pdf_d1 * sigma) / (2.0 * sqrt_t) + r * strike * df * norm_cdf(-d2)
        rho_annual = -strike * t_years * df * norm_cdf(-d2)

    gamma = pdf_d1 / (spot * sigma * sqrt_t)
    vega_annual = spot * pdf_d1 * sqrt_t

    return {
        "delta": round(delta, 3),
        "gamma": round(gamma, 6),
        "theta": round(theta_annual / DAYS_PER_YEAR, 2),  # decay per calendar day
        "vega": round(vega_annual / 100.0, 2),            # per 1% change in vol
        "rho": round(rho_annual / 100.0, 2),              # per 1% change in interest rate
    }


def implied_volatility(
    spot: float, strike: float, t_years: float, r: float, market_price: float, is_call: bool
) -> float | None:
    """Numerical Implied Volatility (annualized %) using Newton-Raphson with bisection fallback.

    Returns None if market_price violates no-arbitrage bounds or inputs are invalid.
    """
    if spot <= 0 or strike <= 0 or market_price <= 0 or t_years <= 0:
        return None

    df = math.exp(-r * t_years)
    intrinsic_disc = max(0.0, spot - strike * df) if is_call else max(0.0, strike * df - spot)
    upper_bound = spot if is_call else strike * df

    if market_price <= intrinsic_disc * 0.999 or market_price >= upper_bound * 1.001:
        return None

    # Newton-Raphson iteration
    sigma = 0.5  # initial guess 50%
    for _ in range(30):
        price = bs_price(spot, strike, t_years, r, sigma, is_call)
        diff = price - market_price
        if abs(diff) < 0.2 or abs(diff) < 1e-4 * spot:
            return round(sigma * 100.0, 1)
        sqrt_t = math.sqrt(t_years)
        d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t_years) / (sigma * sqrt_t)
        vega = spot * norm_pdf(d1) * sqrt_t
        if vega < 1e-6:
            break
        step = diff / vega
        sigma -= step
        if sigma <= 0.01 or sigma >= 5.0:
            break

    # Fallback to Bisection between 1% and 500%
    lo, hi = 0.01, 5.0
    for _ in range(40):
        mid = (lo + hi) / 2.0
        p = bs_price(spot, strike, t_years, r, mid, is_call)
        diff = p - market_price
        if abs(diff) < 0.5 or abs(diff) < 1e-3 * spot:
            return round(mid * 100.0, 1)
        if diff > 0:
            hi = mid
        else:
            lo = mid
    return round(mid * 100.0, 1)


# ------------------------------------------------------------------------------------------------ strategy payoff


def _leg_payoff(leg: dict, spot_at_expiry: float) -> float:
    """Payoff in Rial for one leg at a given settlement price."""
    leg_type = str(leg.get("type", "call")).lower()
    action = str(leg.get("action", "buy")).lower()
    premium = float(leg.get("premium", 0.0))
    strike = float(leg.get("strike", 0.0))
    contracts = int(leg.get("contracts", 1))
    size = int(leg.get("size", 1000))
    total_units = contracts * size

    if leg_type in ("stock", "underlying"):
        entry_price = float(leg.get("entry_price") or premium or strike)
        if action == "buy":
            return (spot_at_expiry - entry_price) * total_units
        return (entry_price - spot_at_expiry) * total_units

    if leg_type in ("call", "c", "خرید"):
        intrinsic = max(0.0, spot_at_expiry - strike)
        if action == "buy":
            return (intrinsic - premium) * total_units
        return (premium - intrinsic) * total_units

    if leg_type in ("put", "p", "فروش"):
        intrinsic = max(0.0, strike - spot_at_expiry)
        if action == "buy":
            return (intrinsic - premium) * total_units
        return (premium - intrinsic) * total_units

    return 0.0


def evaluate_strategy(
    underlying_name: str,
    spot: float,
    legs: list[dict],
    strategy_name: str = "custom",
    contract_size: int = 1000,
    days_to_expiry: int = 30,
) -> dict[str, Any]:
    """Calculates full payoff metrics, break-even points, risk/reward, and curves for a strategy.

    legs is a list of dicts:
      {"type": "call"|"put"|"stock", "action": "buy"|"sell", "strike": float, "premium": float,
       "contracts": int, "symbol": str, "entry_price": float}
    """
    if not legs or spot <= 0:
        raise ValueError("legs must be a non-empty list and spot must be positive.")

    # Calculate net premium cash flow
    net_premium = 0.0
    for leg in legs:
        action = str(leg.get("action", "buy")).lower()
        premium = float(leg.get("premium", 0.0))
        contracts = int(leg.get("contracts", 1))
        size = int(leg.get("size") or contract_size)
        leg_cash = premium * contracts * size
        if action == "buy":
            net_premium -= leg_cash  # debit
        else:
            net_premium += leg_cash  # credit

    # Determine evaluation price range: from 70% of min strike/spot to 130% of max strike/spot
    all_prices = [spot] + [float(leg_item["strike"]) for leg_item in legs if leg_item.get("strike")]
    min_k, max_k = min(all_prices), max(all_prices)
    range_min = round(min_k * 0.70)
    range_max = round(max_k * 1.30)
    if range_max <= range_min:
        range_max = range_min + 10000

    num_points = 31
    step = (range_max - range_min) / (num_points - 1)
    curve_spots = [round(range_min + i * step) for i in range(num_points)]
    # Ensure exact spot and strikes are included in curve points for precision
    for p in all_prices:
        if range_min <= p <= range_max:
            curve_spots.append(round(p))
    curve_spots = sorted(set(curve_spots))

    payoff_curve: list[dict[str, Any]] = []
    for s_eval in curve_spots:
        profit = sum(_leg_payoff(leg, s_eval) for leg in legs)
        profit_pct = round((profit / (spot * contract_size)) * 100, 2)
        payoff_curve.append({
            "spot": s_eval,
            "profit_rial": round(profit),
            "profit_pct": profit_pct,
        })

    # Find break-even points (zero crossings)
    breakevens: list[int] = []
    for i in range(len(payoff_curve) - 1):
        p1, p2 = payoff_curve[i], payoff_curve[i + 1]
        y1, y2 = p1["profit_rial"], p2["profit_rial"]
        if y1 == 0:
            breakevens.append(p1["spot"])
        elif (y1 < 0 and y2 > 0) or (y1 > 0 and y2 < 0):
            # linear interpolation
            x1, x2 = p1["spot"], p2["spot"]
            zero_x = x1 - y1 * (x2 - x1) / (y2 - y1)
            breakevens.append(round(zero_x))
    if payoff_curve[-1]["profit_rial"] == 0:
        breakevens.append(payoff_curve[-1]["spot"])
    breakevens = sorted(set(breakevens))

    # Max profit / loss checks
    profits = [p["profit_rial"] for p in payoff_curve]
    min_profit, max_profit = min(profits), max(profits)

    # Check for unbounded profits / losses using slope as spot -> infinity
    slope_inf = 0
    for leg_item in legs:
        l_type = str(leg_item.get("type", "call")).lower()
        l_action = str(leg_item.get("action", "buy")).lower()
        contracts = int(leg_item.get("contracts", 1))
        size = int(leg_item.get("size") or contract_size)
        units = contracts * size
        if l_type in ("call", "c", "خرید"):
            slope_inf += units if l_action == "buy" else -units
        elif l_type in ("stock", "underlying"):
            slope_inf += units if l_action == "buy" else -units

    is_max_profit_unlimited = slope_inf > 0
    is_max_loss_unlimited = slope_inf < 0

    max_profit_rial: int | str = "unlimited" if is_max_profit_unlimited else round(max_profit)
    max_loss_rial: int | str = "unlimited" if is_max_loss_unlimited else round(min_profit)

    risk_reward = None
    if isinstance(max_profit_rial, (int, float)) and isinstance(max_loss_rial, (int, float)):
        if abs(max_loss_rial) > 0:
            risk_reward = round(max_profit_rial / abs(max_loss_rial), 2)

    return_on_risk = None
    if isinstance(max_loss_rial, (int, float)) and abs(max_loss_rial) > 0 and isinstance(max_profit_rial, (int, float)):
        return_on_risk = round((max_profit_rial / abs(max_loss_rial)) * 100, 2)

    annualized_return = None
    if return_on_risk is not None and days_to_expiry > 0:
        annualized_return = round(return_on_risk * DAYS_PER_YEAR / days_to_expiry, 2)

    # Visual graphs
    ascii_graph = generate_ascii_payoff(payoff_curve, spot, breakevens)
    svg_chart = generate_svg_payoff(strategy_name, underlying_name, payoff_curve, spot, breakevens, max_profit_rial, max_loss_rial)

    return {
        "strategy": strategy_name,
        "underlying": underlying_name,
        "spot": spot,
        "days_to_expiry": days_to_expiry,
        "legs": legs,
        "summary": {
            "net_premium_rial": round(net_premium),
            "cash_flow_type": "credit" if net_premium > 0 else ("debit" if net_premium < 0 else "neutral"),
            "max_profit_rial": max_profit_rial,
            "max_loss_rial": max_loss_rial,
            "breakevens": breakevens,
            "risk_reward_ratio": risk_reward,
            "return_on_risk_pct": return_on_risk,
            "annualized_return_pct": annualized_return,
        },
        "ascii_chart": ascii_graph,
        "svg_chart": svg_chart,
        "payoff_curve": payoff_curve,
    }


# ------------------------------------------------------------------------------------------------ visualizers


def generate_ascii_payoff(payoff_curve: list[dict], spot: float, breakevens: list[int]) -> str:
    """Renders a clean 12-line terminal ASCII chart of the profit/loss curve."""
    if not payoff_curve:
        return ""

    width = 45
    height = 10
    prices = [p["spot"] for p in payoff_curve]
    profits = [p["profit_rial"] for p in payoff_curve]

    min_p, max_p = min(prices), max(prices)
    min_y, max_y = min(profits), max(profits)

    if max_y == min_y:
        max_y += 1000
        min_y -= 1000

    # Ensure zero line is in view
    plot_min_y = min(min_y, 0)
    plot_max_y = max(max_y, 0)
    y_range = plot_max_y - plot_min_y if plot_max_y != plot_min_y else 1.0

    # Find row of zero
    zero_row = int(round((plot_max_y - 0.0) / y_range * (height - 1)))
    zero_row = max(0, min(height - 1, zero_row))

    # Grid init
    grid = [[" " for _ in range(width)] for _ in range(height)]

    # Draw zero axis
    for col in range(width):
        grid[zero_row][col] = "-"

    # Plot curve points
    p_range = max_p - min_p if max_p != min_p else 1.0
    for p in payoff_curve:
        col = int(round((p["spot"] - min_p) / p_range * (width - 1)))
        col = max(0, min(width - 1, col))
        row = int(round((plot_max_y - p["profit_rial"]) / y_range * (height - 1)))
        row = max(0, min(height - 1, row))
        grid[row][col] = "#" if p["profit_rial"] >= 0 else "x"

    # Spot column
    spot_col = int(round((spot - min_p) / p_range * (width - 1)))
    if 0 <= spot_col < width:
        for r in range(height):
            if grid[r][spot_col] in (" ", "-"):
                grid[r][spot_col] = "|"

    # Assemble lines
    lines = ["    Profit (Rial)"]
    for r in range(height):
        label = ""
        if r == 0:
            label = f"{int(plot_max_y):>9} +"
        elif r == zero_row:
            label = "        0 +"
        elif r == height - 1:
            label = f"{int(plot_min_y):>9} +"
        else:
            label = "          |"
        lines.append(f"{label}{''.join(grid[r])}")

    # X axis label
    be_str = ", ".join(f"{b:,}" for b in breakevens) if breakevens else "None"
    lines.append(f"          +{'=' * width}")
    lines.append(f"           {min_p:<10,}{spot:^20,} (Spot: |){max_p:>13,}")
    lines.append(f"           Break-even: {be_str} Rial (#: Profit, x: Loss)")

    return "\n".join(lines)


def generate_svg_payoff(
    strategy_name: str,
    underlying: str,
    payoff_curve: list[dict],
    spot: float,
    breakevens: list[int],
    max_profit: Any,
    max_loss: Any,
) -> str:
    """Generates a standalone, dark-themed responsive SVG payoff chart."""
    w, h = 600, 260
    pad_left, pad_right, pad_top, pad_bottom = 65, 30, 45, 40
    plot_w = w - pad_left - pad_right
    plot_h = h - pad_top - pad_bottom

    prices = [p["spot"] for p in payoff_curve]
    profits = [p["profit_rial"] for p in payoff_curve]
    min_x, max_x = min(prices), max(prices)
    min_y = min(min(profits), 0)
    max_y = max(max(profits), 0)
    if max_y == min_y:
        max_y += 1000
        min_y -= 1000

    def x_px(val: float) -> float:
        return pad_left + (val - min_x) / (max_x - min_x) * plot_w

    def y_px(val: float) -> float:
        return pad_top + (max_y - val) / (max_y - min_y) * plot_h

    zero_y = y_px(0)
    spot_x = x_px(spot)

    # Build SVG path for payoff line
    points = [f"{x_px(p['spot']):.1f},{y_px(p['profit_rial']):.1f}" for p in payoff_curve]
    path_d = "M " + " L ".join(points)

    be_text = ", ".join(f"{b:,}" for b in breakevens) if breakevens else "None"
    max_prof_str = f"{max_profit:,}" if isinstance(max_profit, (int, float)) else str(max_profit)
    max_loss_str = f"{max_loss:,}" if isinstance(max_loss, (int, float)) else str(max_loss)

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="100%" height="auto" style="background:#0d1117;font-family:ui-monospace,monospace;border-radius:8px;">',
        '  <defs>',
        '    <linearGradient id="profitGrad" x1="0" y1="0" x2="0" y2="1">',
        '      <stop offset="0%" stop-color="#10b981" stop-opacity="0.3"/>',
        '      <stop offset="100%" stop-color="#10b981" stop-opacity="0.0"/>',
        '    </linearGradient>',
        '    <linearGradient id="lossGrad" x1="0" y1="1" x2="0" y2="0">',
        '      <stop offset="0%" stop-color="#ef4444" stop-opacity="0.3"/>',
        '      <stop offset="100%" stop-color="#ef4444" stop-opacity="0.0"/>',
        '    </linearGradient>',
        '  </defs>',
        # Header / Title
        f'  <text x="{pad_left}" y="24" fill="#f3f4f6" font-size="13" font-weight="bold">{strategy_name.upper()} ({underlying})</text>',
        f'  <text x="{w - pad_right}" y="24" fill="#9ca3af" font-size="11" text-anchor="end">Max Profit: <tspan fill="#10b981">{max_prof_str}</tspan> | Max Loss: <tspan fill="#ef4444">{max_loss_str}</tspan></text>',
        # Axes & Zero Line
        f'  <line x1="{pad_left}" y1="{pad_top}" x2="{pad_left}" y2="{pad_top + plot_h}" stroke="#374151" stroke-width="1"/>',
        f'  <line x1="{pad_left}" y1="{pad_top + plot_h}" x2="{pad_left + plot_w}" y2="{pad_top + plot_h}" stroke="#374151" stroke-width="1"/>',
        f'  <line x1="{pad_left}" y1="{zero_y:.1f}" x2="{pad_left + plot_w}" y2="{zero_y:.1f}" stroke="#6b7280" stroke-width="1" stroke-dasharray="4,4"/>',
        f'  <text x="{pad_left - 8}" y="{zero_y + 4:.1f}" fill="#9ca3af" font-size="10" text-anchor="end">0</text>',
        f'  <text x="{pad_left - 8}" y="{pad_top + 10}" fill="#10b981" font-size="10" text-anchor="end">{int(max_y):,}</text>',
        f'  <text x="{pad_left - 8}" y="{pad_top + plot_h}" fill="#ef4444" font-size="10" text-anchor="end">{int(min_y):,}</text>',
        # Current Spot Line
        f'  <line x1="{spot_x:.1f}" y1="{pad_top}" x2="{spot_x:.1f}" y2="{pad_top + plot_h}" stroke="#3b82f6" stroke-width="1.5" stroke-dasharray="3,3"/>',
        f'  <text x="{spot_x:.1f}" y="{pad_top - 6}" fill="#60a5fa" font-size="10" text-anchor="middle">Spot {int(spot):,}</text>',
    ]

    # Break-even markers
    for be in breakevens:
        bx = x_px(be)
        if pad_left <= bx <= pad_left + plot_w:
            svg.append(f'  <circle cx="{bx:.1f}" cy="{zero_y:.1f}" r="4" fill="#fbbf24"/>')
            svg.append(f'  <text x="{bx:.1f}" y="{zero_y + 16:.1f}" fill="#fbbf24" font-size="9" text-anchor="middle">{be:,}</text>')

    # Payoff curve line
    svg.append(f'  <path d="{path_d}" fill="none" stroke="#22d3ee" stroke-width="2.5"/>')
    # Footer
    svg.append(f'  <text x="{pad_left}" y="{h - 10}" fill="#9ca3af" font-size="10">Underlying Price (Rial) | Break-even: {be_text}</text>')
    svg.append('</svg>')

    return "\n".join(svg)


# ------------------------------------------------------------------------------------------------ strategy builder


def build_preset_strategy(
    strategy_type: str,
    parsed_rows: list[dict],
    underlying_name: str,
    contracts: int = 1,
    lower_strike: float | None = None,
    upper_strike: float | None = None,
    strike: float | None = None,
    spot_override: float | None = None,
) -> dict[str, Any]:
    """Selects suitable strikes/contracts from parsed option rows and evaluates the strategy."""
    if not parsed_rows:
        raise ValueError(f"No option rows available for underlying '{underlying_name}'.")

    first = parsed_rows[0]
    spot = spot_override or first["spot"] or first["spot_close"] or first["spot_last"]
    if not spot:
        raise ValueError(f"Cannot determine underlying spot price for '{underlying_name}'.")

    days = first.get("days", 30)
    size = first.get("size", 1000)
    stk_map = {p["strike"]: p for p in parsed_rows}
    available_strikes = sorted(stk_map.keys())

    stype = strategy_type.strip().lower()
    legs: list[dict] = []

    def get_price(leg_dict: dict, action: str) -> float:
        if action == "buy":
            return leg_dict.get("ask") or leg_dict.get("close") or leg_dict.get("last") or 0.0
        return leg_dict.get("bid") or leg_dict.get("close") or leg_dict.get("last") or 0.0

    if stype == "covered_call":
        # Buy stock + Sell OTM Call
        otm_strikes = [k for k in available_strikes if k >= spot]
        sel_strike = strike or (otm_strikes[0] if otm_strikes else available_strikes[-1])
        row = stk_map[sel_strike]
        call_prem = get_price(row["C"], "sell")
        legs = [
            {"type": "stock", "action": "buy", "entry_price": spot, "contracts": contracts, "size": size, "symbol": underlying_name},
            {"type": "call", "action": "sell", "strike": sel_strike, "premium": call_prem, "contracts": contracts, "size": size, "symbol": row["C"]["symbol"]},
        ]

    elif stype == "protective_put":
        # Buy stock + Buy OTM Put
        otm_strikes = [k for k in available_strikes if k <= spot]
        sel_strike = strike or (otm_strikes[-1] if otm_strikes else available_strikes[0])
        row = stk_map[sel_strike]
        put_prem = get_price(row["P"], "buy")
        legs = [
            {"type": "stock", "action": "buy", "entry_price": spot, "contracts": contracts, "size": size, "symbol": underlying_name},
            {"type": "put", "action": "buy", "strike": sel_strike, "premium": put_prem, "contracts": contracts, "size": size, "symbol": row["P"]["symbol"]},
        ]

    elif stype == "cash_secured_put":
        # Sell OTM Put with cash collateral
        otm_strikes = [k for k in available_strikes if k <= spot]
        sel_strike = strike or (otm_strikes[-1] if otm_strikes else available_strikes[0])
        row = stk_map[sel_strike]
        put_prem = get_price(row["P"], "sell")
        legs = [
            {"type": "put", "action": "sell", "strike": sel_strike, "premium": put_prem, "contracts": contracts, "size": size, "symbol": row["P"]["symbol"]},
        ]

    elif stype == "bull_call_spread":
        # Buy lower Call + Sell higher Call
        k1 = lower_strike or min(available_strikes, key=lambda k: abs(k - spot))
        higher = [k for k in available_strikes if k > k1]
        k2 = upper_strike or (higher[0] if higher else available_strikes[-1])
        r1, r2 = stk_map[k1], stk_map[k2]
        legs = [
            {"type": "call", "action": "buy", "strike": k1, "premium": get_price(r1["C"], "buy"), "contracts": contracts, "size": size, "symbol": r1["C"]["symbol"]},
            {"type": "call", "action": "sell", "strike": k2, "premium": get_price(r2["C"], "sell"), "contracts": contracts, "size": size, "symbol": r2["C"]["symbol"]},
        ]

    elif stype == "bear_put_spread":
        # Buy higher Put + Sell lower Put
        k2 = upper_strike or min(available_strikes, key=lambda k: abs(k - spot))
        lower = [k for k in available_strikes if k < k2]
        k1 = lower_strike or (lower[-1] if lower else available_strikes[0])
        r1, r2 = stk_map[k1], stk_map[k2]
        legs = [
            {"type": "put", "action": "buy", "strike": k2, "premium": get_price(r2["P"], "buy"), "contracts": contracts, "size": size, "symbol": r2["P"]["symbol"]},
            {"type": "put", "action": "sell", "strike": k1, "premium": get_price(r1["P"], "sell"), "contracts": contracts, "size": size, "symbol": r1["P"]["symbol"]},
        ]

    elif stype in ("long_straddle", "short_straddle"):
        # Buy or Sell ATM Call + ATM Put
        atm = strike or min(available_strikes, key=lambda k: abs(k - spot))
        row = stk_map[atm]
        act = "buy" if stype == "long_straddle" else "sell"
        legs = [
            {"type": "call", "action": act, "strike": atm, "premium": get_price(row["C"], act), "contracts": contracts, "size": size, "symbol": row["C"]["symbol"]},
            {"type": "put", "action": act, "strike": atm, "premium": get_price(row["P"], act), "contracts": contracts, "size": size, "symbol": row["P"]["symbol"]},
        ]

    elif stype in ("long_strangle", "short_strangle"):
        # Buy or Sell OTM Put + OTM Call
        lowers = [k for k in available_strikes if k < spot]
        highers = [k for k in available_strikes if k > spot]
        k_put = lower_strike or (lowers[-1] if lowers else available_strikes[0])
        k_call = upper_strike or (highers[0] if highers else available_strikes[-1])
        r_put, r_call = stk_map[k_put], stk_map[k_call]
        act = "buy" if stype == "long_strangle" else "sell"
        legs = [
            {"type": "put", "action": act, "strike": k_put, "premium": get_price(r_put["P"], act), "contracts": contracts, "size": size, "symbol": r_put["P"]["symbol"]},
            {"type": "call", "action": act, "strike": k_call, "premium": get_price(r_call["C"], act), "contracts": contracts, "size": size, "symbol": r_call["C"]["symbol"]},
        ]

    elif stype == "box_spread":
        # Bull Call Spread (K1, K2) + Bear Put Spread (K1, K2)
        if len(available_strikes) < 2:
            raise ValueError(f"box_spread requires at least 2 strikes on '{underlying_name}'.")
        k1 = lower_strike or available_strikes[0]
        k2 = upper_strike or available_strikes[-1]
        r1, r2 = stk_map[k1], stk_map[k2]
        legs = [
            {"type": "call", "action": "buy", "strike": k1, "premium": get_price(r1["C"], "buy"), "contracts": contracts, "size": size, "symbol": r1["C"]["symbol"]},
            {"type": "call", "action": "sell", "strike": k2, "premium": get_price(r2["C"], "sell"), "contracts": contracts, "size": size, "symbol": r2["C"]["symbol"]},
            {"type": "put", "action": "buy", "strike": k2, "premium": get_price(r2["P"], "buy"), "contracts": contracts, "size": size, "symbol": r2["P"]["symbol"]},
            {"type": "put", "action": "sell", "strike": k1, "premium": get_price(r1["P"], "sell"), "contracts": contracts, "size": size, "symbol": r1["P"]["symbol"]},
        ]

    else:
        raise ValueError(
            f"Strategy '{strategy_type}' is not recognized. Supported strategies: covered_call, protective_put, "
            "cash_secured_put, bull_call_spread, bear_put_spread, long_straddle, short_straddle, "
            "long_strangle, short_strangle, box_spread, custom."
        )

    return evaluate_strategy(underlying_name, spot, legs, strategy_name=stype, contract_size=size, days_to_expiry=days)


# ------------------------------------------------------------------------------------------------ arbitrage scanner


def scan_option_arbitrage(
    parsed_rows: list[dict],
    max_days: int = 35,
    min_yield_pct: float = 30.0,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    min_volume: int = 0,
    underlying_filter: str | None = None,
) -> dict[str, Any]:
    """Scans parsed option rows for near-deadline arbitrage opportunities.

    Detects:
    1. Below Intrinsic Arbitrage: In-the-money options whose ask price is lower than intrinsic value.
    2. Box Spread Synthetic Loan Arbitrage: 4-leg combos delivering risk-free annualized yield above min_yield_pct.
    3. Put-Call Parity Deviations: Reversal/conversion opportunities where parity difference is abnormal.
    """
    below_intrinsic: list[dict[str, Any]] = []
    box_spreads: list[dict[str, Any]] = []
    parity_discrepancies: list[dict[str, Any]] = []

    # Group by (underlying, expiry)
    grouped: dict[tuple[str, int], list[dict]] = {}
    for p in parsed_rows:
        if underlying_filter and underlying_filter not in (p["ua_name"], p["ua_code"]):
            continue
        days = p.get("days", 0)
        if days > max_days:
            continue
        key = (p["ua_name"], p["end"])
        grouped.setdefault(key, []).append(p)

    for (ua_name, _end_date), group in grouped.items():
        first = group[0]
        spot = first["spot"] or first["spot_close"] or first["spot_last"]
        days = first.get("days", 0)
        size = first.get("size", 1000)
        t_years = max(days, 0.5) / DAYS_PER_YEAR

        if not spot:
            continue

        # 1. Below Intrinsic Arbitrage
        for p in group:
            strike = p["strike"]
            # Call side
            c = p["C"]
            ask_c = c.get("ask") or c.get("close")
            if ask_c and ask_c > 0 and (c.get("volume", 0) >= min_volume or c.get("ask_qty", 0) > 0):
                intrinsic_c = max(0.0, spot - strike)
                discount_c = intrinsic_c - ask_c
                if discount_c > 0:
                    ret_pct = (discount_c / ask_c) * 100
                    ann_yield = ret_pct * (DAYS_PER_YEAR / max(days, 1))
                    below_intrinsic.append({
                        "underlying": ua_name,
                        "type": "call",
                        "symbol": c["symbol"],
                        "strike": strike,
                        "spot": spot,
                        "ask_price": ask_c,
                        "intrinsic_value": round(intrinsic_c),
                        "discount_rial": round(discount_c),
                        "discount_pct": round(ret_pct, 2),
                        "estimated_annualized_yield_pct": round(ann_yield, 1),
                        "days_to_expiry": days,
                        "contract_size": size,
                        "profit_per_contract_rial": round(discount_c * size),
                    })

            # Put side
            p_leg = p["P"]
            ask_p = p_leg.get("ask") or p_leg.get("close")
            if ask_p and ask_p > 0 and (p_leg.get("volume", 0) >= min_volume or p_leg.get("ask_qty", 0) > 0):
                intrinsic_p = max(0.0, strike - spot)
                discount_p = intrinsic_p - ask_p
                if discount_p > 0:
                    ret_pct = (discount_p / ask_p) * 100
                    ann_yield = ret_pct * (DAYS_PER_YEAR / max(days, 1))
                    below_intrinsic.append({
                        "underlying": ua_name,
                        "type": "put",
                        "symbol": p_leg["symbol"],
                        "strike": strike,
                        "spot": spot,
                        "ask_price": ask_p,
                        "intrinsic_value": round(intrinsic_p),
                        "discount_rial": round(discount_p),
                        "discount_pct": round(ret_pct, 2),
                        "estimated_annualized_yield_pct": round(ann_yield, 1),
                        "days_to_expiry": days,
                        "contract_size": size,
                        "profit_per_contract_rial": round(discount_p * size),
                    })

        # 2. Box Spread Arbitrage (strike pairs K1 < K2)
        valid_strikes = [p for p in group if (p["C"].get("close") or p["C"].get("ask")) and (p["P"].get("close") or p["P"].get("ask"))]
        valid_strikes.sort(key=lambda x: x["strike"])

        for i in range(len(valid_strikes)):
            for j in range(i + 1, min(i + 4, len(valid_strikes))):  # inspect adjacent 3 strikes
                p1, p2 = valid_strikes[i], valid_strikes[j]
                k1, k2 = p1["strike"], p2["strike"]
                if k2 <= k1:
                    continue

                # Long Call K1, Short Call K2, Long Put K2, Short Put K1
                c1_price = p1["C"].get("ask") or p1["C"].get("close")
                c2_price = p2["C"].get("bid") or p2["C"].get("close")
                p2_price = p2["P"].get("ask") or p2["P"].get("close")
                p1_price = p1["P"].get("bid") or p1["P"].get("close")

                if not (c1_price and c2_price and p2_price and p1_price):
                    continue

                cost_per_unit = (c1_price - c2_price) + (p2_price - p1_price)
                terminal_value = k2 - k1

                if 0 < cost_per_unit < terminal_value:
                    profit_per_unit = terminal_value - cost_per_unit
                    yield_pct = (profit_per_unit / cost_per_unit) * 100
                    ann_yield = yield_pct * (DAYS_PER_YEAR / max(days, 1))

                    if ann_yield >= min_yield_pct:
                        box_spreads.append({
                            "underlying": ua_name,
                            "strikes": [k1, k2],
                            "terminal_value_rial": terminal_value,
                            "entry_cost_rial": round(cost_per_unit),
                            "profit_per_unit_rial": round(profit_per_unit),
                            "profit_per_contract_rial": round(profit_per_unit * size),
                            "estimated_annualized_yield_pct": round(ann_yield, 1),
                            "days_to_expiry": days,
                            "legs": [
                                f"+C {p1['C']['symbol']} ({k1}) @ {c1_price}",
                                f"-C {p2['C']['symbol']} ({k2}) @ {c2_price}",
                                f"+P {p2['P']['symbol']} ({k2}) @ {p2_price}",
                                f"-P {p1['P']['symbol']} ({k1}) @ {p1_price}",
                            ],
                        })

        # 3. Put-Call Parity Deviations
        df = math.exp(-risk_free_rate * t_years)
        for p in group:
            k = p["strike"]
            c_close = p["C"].get("close")
            p_close = p["P"].get("close")
            if c_close and p_close and spot:
                actual_spread = c_close - p_close
                theoretical_spread = spot - k * df
                deviation = actual_spread - theoretical_spread
                dev_pct = round((abs(deviation) / spot) * 100, 2)
                if dev_pct >= 2.0:  # significant deviation > 2% of spot
                    parity_discrepancies.append({
                        "underlying": ua_name,
                        "strike": k,
                        "spot": spot,
                        "call_close": c_close,
                        "put_close": p_close,
                        "actual_diff_rial": round(actual_spread),
                        "theoretical_diff_rial": round(theoretical_spread),
                        "deviation_rial": round(deviation),
                        "deviation_pct": dev_pct,
                        "action_hint": "conversion_opportunity (call overpriced)" if deviation > 0 else "reversal_opportunity (put overpriced)",
                        "days_to_expiry": days,
                    })

    # Sort opportunities by annualized yield / profit
    below_intrinsic.sort(key=lambda x: -x["estimated_annualized_yield_pct"])
    box_spreads.sort(key=lambda x: -x["estimated_annualized_yield_pct"])
    parity_discrepancies.sort(key=lambda x: -x["deviation_pct"])

    return {
        "max_days_filter": max_days,
        "risk_free_rate": risk_free_rate,
        "total_below_intrinsic": len(below_intrinsic),
        "total_box_spreads": len(box_spreads),
        "total_parity_discrepancies": len(parity_discrepancies),
        "below_intrinsic_opportunities": below_intrinsic[:25],
        "box_spread_opportunities": box_spreads[:25],
        "parity_discrepancies": parity_discrepancies[:25],
        "note": "Derived arbitrage opportunities based on live or closing market quotes. All numbers are estimates and subject to execution slippage and broker commission.",
    }
