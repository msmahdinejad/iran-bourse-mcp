"""Pure functions that turn raw TSETMC payloads into clean, unit-explicit, LLM-friendly data.

Conventions
-----------
* Prices and values are in **Rial** unless a key says otherwise.
* ``date`` is Gregorian ISO, ``jdate`` is Jalali.
* Names/symbols are normalised to Persian letters (ی ک).
* Anything *derived* (not provided by the exchange) lives under an ``estimate``/``derived`` key
  or has ``estimated`` in its name, so an agent can tell facts from inferences.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from .dates import fmt_date, fmt_time, jdate, seconds_of_day
from .text import ascii_digits, clean

# --------------------------------------------------------------------------- helpers


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _i(value: Any) -> int | None:
    number = _f(value)
    return None if number is None else int(round(number))


def _r(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def pct_change(new: float | None, base: float | None) -> float | None:
    if new is None or not base:
        return None
    return round((new - base) / base * 100, 2)


def _safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or not b:
        return None
    return a / b


# --------------------------------------------------------------------------- quote


def shape_status(closing: dict) -> dict:
    state = closing.get("instrumentState") or {}
    return {
        "code": (state.get("cEtaval") or "").strip() or None,
        "title": clean(state.get("cEtavalTitle")),
        "under_supervision": state.get("underSupervision"),
    }


def shape_quote(closing: dict, info: dict) -> dict:
    """Live/last quote. Fixes the unreliable ``priceChange`` field by recomputing from prices."""
    last = _f(closing.get("pDrCotVal"))
    close = _f(closing.get("pClosing"))
    yesterday = _f(closing.get("priceYesterday"))
    volume = _f(closing.get("qTotTran5J"))
    value = _f(closing.get("qTotCap"))
    thr = info.get("staticThreshold") or {}
    upper, lower = _f(thr.get("psGelStaMax")), _f(thr.get("psGelStaMin"))
    shares = _f(info.get("zTitad"))
    eps_block = info.get("eps") or {}
    eps = _f(eps_block.get("estimatedEPS")) or _f(eps_block.get("epsValue"))
    avg_volume = _f(info.get("qTotTran5JAvg"))
    vwap = _safe_div(value, volume)

    return {
        "date": fmt_date(closing.get("dEven")),
        "jdate": jdate(closing.get("dEven")),
        "last_update": fmt_time(closing.get("hEven")),
        "status": shape_status(closing),
        "last": {"price": last, "change": _r(None if last is None or yesterday is None else last - yesterday), "change_pct": pct_change(last, yesterday)},
        "close": {"price": close, "change": _r(None if close is None or yesterday is None else close - yesterday), "change_pct": pct_change(close, yesterday)},
        "yesterday_close": yesterday,
        "open": _f(closing.get("priceFirst")),
        "high": _f(closing.get("priceMax")),
        "low": _f(closing.get("priceMin")),
        "volume": _i(volume),
        "value": _i(value),
        "trades": _i(closing.get("zTotTran")),
        "vwap": _r(vwap),
        "price_limits": {"upper": upper, "lower": lower},
        "at_upper_limit": bool(upper and last is not None and last >= upper),
        "at_lower_limit": bool(lower and last is not None and last <= lower),
        "ranges": {
            "week": {"low": _f(info.get("minWeek")), "high": _f(info.get("maxWeek"))},
            "year": {"low": _f(info.get("minYear")), "high": _f(info.get("maxYear"))},
        },
        "avg_volume": _i(avg_volume),
        "volume_vs_avg": _r(_safe_div(volume, avg_volume)),
        "fundamentals": {
            "eps": eps,
            "pe": _r(_safe_div(last, eps)) if eps and eps > 0 else None,
            "sector_pe": _f(eps_block.get("sectorPE")),
            "psr": _f(eps_block.get("psr")),
            "shares_outstanding": _i(shares),
            "market_cap": _i(last * shares) if last and shares else None,
            "note": "eps is the exchange's estimated EPS; pe = last price / eps",
        },
        "units": "rial",
    }


def shape_identity(info: dict, identity: dict | None = None) -> dict:
    identity = identity or {}
    sector = identity.get("sector") or info.get("sector") or {}
    sub = identity.get("subSector") or {}
    return {
        "symbol": clean(info.get("lVal18AFC") or identity.get("lVal18AFC")),
        "name": clean(info.get("lVal30") or identity.get("lVal30")),
        "name_en": clean(info.get("lVal18") or identity.get("lVal18")),
        "ins_code": str(info.get("insCode") or ""),
        "isin": info.get("cIsin") or identity.get("cIsin"),
        "instrument_id": info.get("instrumentID") or identity.get("instrumentID"),
        "market": clean(info.get("flowTitle")),
        "board": clean(info.get("cgrValCotTitle") or identity.get("cgrValCotTitle")),
        "sector": clean(sector.get("lSecVal")),
        "sector_code": (sector.get("cSecVal") or "").strip() or None,
        "sub_sector": clean(sub.get("lSoSecVal")),
        "instrument_kind": classify_instrument(info.get("cIsin") or identity.get("cIsin"), info.get("cgrValCot")),
    }


def classify_instrument(isin: str | None, board_code: str | None) -> str:
    """Rough instrument kind from the ISIN prefix (documented in docs/FIELDS.md)."""
    if not isin:
        return "unknown"
    prefix = isin[:4]
    if prefix in ("IRO1", "IRO3", "IRO5", "IRO7"):
        return "stock"
    if prefix == "IRT1":
        return "fund_unit"
    if prefix == "IRO9":
        return "option_or_derivative"
    if isin.startswith("IRB"):
        return "bond_or_sukuk"
    if prefix.startswith("IR"):
        return "other"
    return "unknown"


# --------------------------------------------------------------------------- order book


def _levels(rows: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    bids: list[dict] = []
    asks: list[dict] = []
    for row in sorted(rows, key=lambda r: r.get("number") or 0):
        bid_volume = _i(row.get("qTitMeDem")) or 0
        ask_volume = _i(row.get("qTitMeOf")) or 0
        if bid_volume > 0:
            bids.append(
                {"level": row.get("number"), "price": _f(row.get("pMeDem")), "volume": bid_volume, "orders": _i(row.get("zOrdMeDem"))}
            )
        if ask_volume > 0:
            asks.append(
                {"level": row.get("number"), "price": _f(row.get("pMeOf")), "volume": ask_volume, "orders": _i(row.get("zOrdMeOf"))}
            )
    return bids, asks


def queue_state(bids: list[dict], asks: list[dict], upper: float | None, lower: float | None) -> dict:
    """Detect a buy queue (صف خرید) or sell queue (صف فروش) from the top of the book."""
    if bids and not asks and upper and bids[0]["price"] is not None and bids[0]["price"] >= upper:
        top = bids[0]
        return {
            "state": "buy_queue",
            "queue_volume": top["volume"],
            "queue_orders": top["orders"],
            "queue_value": _i(top["volume"] * top["price"]),
        }
    if asks and not bids and lower and asks[0]["price"] is not None and asks[0]["price"] <= lower:
        top = asks[0]
        return {
            "state": "sell_queue",
            "queue_volume": top["volume"],
            "queue_orders": top["orders"],
            "queue_value": _i(top["volume"] * top["price"]),
        }
    return {"state": None, "queue_volume": 0, "queue_orders": 0, "queue_value": 0}


def book_metrics(bids: list[dict], asks: list[dict]) -> dict:
    bid_volume = sum(b["volume"] for b in bids)
    ask_volume = sum(a["volume"] for a in asks)
    best_bid = bids[0]["price"] if bids else None
    best_ask = asks[0]["price"] if asks else None
    total = bid_volume + ask_volume
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": _r(best_ask - best_bid) if best_bid and best_ask else None,
        "spread_pct": pct_change(best_ask, best_bid) if best_bid and best_ask else None,
        "total_bid_volume": bid_volume,
        "total_ask_volume": ask_volume,
        "total_bid_orders": sum(b["orders"] or 0 for b in bids),
        "total_ask_orders": sum(a["orders"] or 0 for a in asks),
        "imbalance": _r((bid_volume - ask_volume) / total, 4) if total else None,
    }


def shape_order_book(rows: list[dict], upper: float | None, lower: float | None) -> dict:
    bids, asks = _levels(rows)
    outside = 0
    for level in (*bids, *asks):  # after the close the book can already hold next-session orders beyond today's limits
        price = level["price"]
        if price is not None and ((upper and price > upper) or (lower and price < lower)):
            level["outside_price_limits"] = True
            outside += 1
    out = {
        "bids": bids,
        "asks": asks,
        **book_metrics(bids, asks),
        "queue": queue_state(bids, asks, upper, lower),
        "price_limits": {"upper": upper, "lower": lower},
        "units": "price in rial, volume in shares",
    }
    if outside:
        out["note"] = f"{outside} level(s) are priced outside today's limits (orders for the next session): flagged outside_price_limits."
    return out


def reconstruct_book(rows: list[dict]) -> list[dict]:
    """Rebuild full 5-level snapshots from TSETMC's delta feed (carry-forward by ``refID``).

    ``BestLimits/{ins}/{date}`` lists only the levels that changed at each event; the rest
    keep their previous value.
    """
    groups: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        groups[int(row["refID"])].append(row)
    state: dict[int, dict] = {}
    snapshots: list[dict] = []
    for ref in sorted(groups):
        group = groups[ref]
        for row in group:
            state[int(row["number"])] = row
        snapshots.append({"ref": ref, "time": int(group[0]["hEven"]), "rows": [state[k] for k in sorted(state)]})
    return snapshots


def book_timeline(
    snapshots: list[dict],
    upper: float | None,
    lower: float | None,
    *,
    start: int | None = None,
    end: int | None = None,
    step_seconds: int = 300,
    max_points: int = 120,
) -> dict:
    """Sample the reconstructed book and extract queue episodes."""
    selected = [s for s in snapshots if (start is None or s["time"] >= start) and (end is None or s["time"] <= end)]
    samples: list[dict] = []
    last_bucket: int | None = None
    episodes: list[dict] = []
    current: dict | None = None
    peak_depth = {"max_bid_volume": 0, "max_ask_volume": 0}

    for snap in selected:
        bids, asks = _levels(snap["rows"])
        metrics = book_metrics(bids, asks)
        queue = queue_state(bids, asks, upper, lower)
        peak_depth["max_bid_volume"] = max(peak_depth["max_bid_volume"], metrics["total_bid_volume"])
        peak_depth["max_ask_volume"] = max(peak_depth["max_ask_volume"], metrics["total_ask_volume"])

        bucket = seconds_of_day(snap["time"]) // max(step_seconds, 1)
        if bucket != last_bucket:
            last_bucket = bucket
            samples.append(
                {
                    "time": fmt_time(snap["time"]),
                    "best_bid": metrics["best_bid"],
                    "best_ask": metrics["best_ask"],
                    "bid_volume": metrics["total_bid_volume"],
                    "ask_volume": metrics["total_ask_volume"],
                    "imbalance": metrics["imbalance"],
                    "queue": queue["state"],
                    "queue_volume": queue["queue_volume"],
                }
            )

        state = queue["state"]
        if state and (current is None or current["type"] != state):
            if current:
                episodes.append(current)
            current = {
                "type": state,
                "start": fmt_time(snap["time"]),
                "end": fmt_time(snap["time"]),
                "start_volume": queue["queue_volume"],
                "end_volume": queue["queue_volume"],
                "peak_volume": queue["queue_volume"],
            }
        elif state and current:
            current["end"] = fmt_time(snap["time"])
            current["end_volume"] = queue["queue_volume"]
            current["peak_volume"] = max(current["peak_volume"], queue["queue_volume"])
        elif not state and current:
            episodes.append(current)
            current = None
    if current:
        episodes.append(current)

    if len(samples) > max_points:
        stride = len(samples) / max_points
        samples = [samples[int(i * stride)] for i in range(max_points)]

    return {"snapshots_in_range": len(selected), "samples": samples, "queue_episodes": episodes, **peak_depth}


# --------------------------------------------------------------------------- ticks


def _clean_ticks(raw: list[dict]) -> tuple[list[dict], int]:
    ticks: list[dict] = []
    cancelled = 0
    for row in raw:
        if row.get("canceled"):
            cancelled += 1
            continue
        price, volume = _f(row.get("pTran")), _f(row.get("qTitTran"))
        if price is None or volume is None:
            continue
        ticks.append({"n": _i(row.get("nTran")) or 0, "t": _i(row.get("hEven")) or 0, "p": price, "v": volume})
    ticks.sort(key=lambda t: (t["n"], t["t"]))
    return ticks, cancelled


def shape_ticks(raw: list[dict]) -> list[dict]:
    ticks, _ = _clean_ticks(raw)
    return [
        {"n": t["n"], "time": fmt_time(t["t"]), "price": t["p"], "volume": int(t["v"]), "value": int(t["p"] * t["v"])}
        for t in ticks
    ]


def aggregate_ticks(
    raw: list[dict],
    *,
    interval_minutes: int = 5,
    top_trades: int = 10,
    top_price_levels: int = 10,
    official_volume: float | None = None,
    official_count: float | None = None,
) -> dict:
    ticks, cancelled = _clean_ticks(raw)
    if not ticks:
        return {"ticks": 0, "note": "No trades found for this symbol/date."}

    total_volume = sum(t["v"] for t in ticks)
    total_value = sum(t["p"] * t["v"] for t in ticks)

    # --- bars
    width = max(interval_minutes, 1) * 60
    buckets: dict[int, list[dict]] = defaultdict(list)
    for t in ticks:
        buckets[seconds_of_day(t["t"]) // width * width].append(t)
    bars = []
    for start in sorted(buckets):
        group = buckets[start]
        volume = sum(t["v"] for t in group)
        value = sum(t["p"] * t["v"] for t in group)
        bars.append(
            {
                "from": f"{start // 3600:02d}:{(start // 60) % 60:02d}",
                "open": group[0]["p"],
                "high": max(t["p"] for t in group),
                "low": min(t["p"] for t in group),
                "close": group[-1]["p"],
                "volume": int(volume),
                "value": int(value),
                "trades": len(group),
                "vwap": _r(value / volume) if volume else None,
            }
        )

    # --- tick-rule pressure (estimate): trade above previous price => buyer-initiated
    up = down = neutral = 0.0
    direction = 0
    previous: float | None = None
    for t in ticks:
        if previous is not None:
            if t["p"] > previous:
                direction = 1
            elif t["p"] < previous:
                direction = -1
        previous = t["p"]
        if direction > 0:
            up += t["v"]
        elif direction < 0:
            down += t["v"]
        else:
            neutral += t["v"]

    # --- biggest trades and price levels
    biggest = sorted(ticks, key=lambda t: t["p"] * t["v"], reverse=True)[:top_trades]
    levels: dict[float, float] = defaultdict(float)
    for t in ticks:
        levels[t["p"]] += t["v"]
    ranked = sorted(levels.items(), key=lambda kv: kv[1], reverse=True)

    summary = {
        "ticks": len(ticks),
        "cancelled_ticks": cancelled,
        "first_trade": fmt_time(ticks[0]["t"]),
        "last_trade": fmt_time(ticks[-1]["t"]),
        "volume": int(total_volume),
        "value": int(total_value),
        "vwap": _r(total_value / total_volume) if total_volume else None,
        "open": ticks[0]["p"],
        "high": max(t["p"] for t in ticks),
        "low": min(t["p"] for t in ticks),
        "close": ticks[-1]["p"],
        "avg_trade_volume": int(total_volume / len(ticks)),
        "median_trade_volume": int(sorted(t["v"] for t in ticks)[len(ticks) // 2]),
    }
    completeness: dict[str, Any] = {"ticks_volume": int(total_volume), "ticks_count": len(ticks)}
    if official_volume:
        completeness["official_volume"] = int(official_volume)
        completeness["volume_coverage_pct"] = _r(total_volume / official_volume * 100)
    if official_count:
        completeness["official_trade_count"] = int(official_count)
        completeness["count_coverage_pct"] = _r(len(ticks) / official_count * 100)
    completeness["note"] = "Coverage compares tick data with the exchange's own daily totals; ~100% means nothing is missing."

    return {
        "summary": summary,
        "completeness": completeness,
        "bars": bars,
        "pressure_estimate": {
            "method": "classic tick rule: a trade above the previous price counts as up, below as down, and a trade at an unchanged price keeps the previous direction",
            "uptick_volume_pct": _r(up / total_volume * 100),
            "downtick_volume_pct": _r(down / total_volume * 100),
            "neutral_volume_pct": _r(neutral / total_volume * 100),
            "caveat": "TSETMC does not publish who initiated a trade; this is a heuristic, not exchange data.",
        },
        "biggest_trades": [
            {"time": fmt_time(t["t"]), "price": t["p"], "volume": int(t["v"]), "value": int(t["p"] * t["v"])} for t in biggest
        ],
        "price_levels": [
            {"price": p, "volume": int(v), "share_pct": _r(v / total_volume * 100)} for p, v in ranked[:top_price_levels]
        ],
        "point_of_control": ranked[0][0] if ranked else None,
        "units": "price/value in rial, volume in shares",
    }


# --------------------------------------------------------------------------- real / legal


def _first(ct: dict, *keys: str) -> Any:
    """First present key; TSETMC names the same field differently across endpoints."""
    for key in keys:
        if ct.get(key) is not None:
            return ct[key]
    return None


def _side(volume: Any, count: Any, value: Any = None, price_hint: float | None = None) -> dict:
    vol, cnt = _f(volume) or 0.0, _f(count) or 0.0
    val = _f(value)
    estimated = False
    if val is None and price_hint:
        val = vol * price_hint
        estimated = True
    basis = val if val is not None else vol
    return {
        "volume": int(vol),
        "count": int(cnt),
        "value": None if val is None else int(val),
        "value_estimated": estimated,
        "avg_per_participant": _r(basis / cnt) if cnt else None,
        "avg_volume_per_participant": _r(vol / cnt) if cnt else None,
    }


def shape_client_type(ct: dict, *, vwap: float | None = None) -> dict:
    """Real (حقیقی) vs legal (حقوقی) buy/sell breakdown with derived money-flow metrics."""
    out: dict[str, Any] = {}
    for key, label in (("I", "real"), ("N", "legal")):
        buy = _side(
            ct.get(f"buy_{key}_Volume"), _first(ct, f"buy_Count{key}", f"buy_{key}_Count"), ct.get(f"buy_{key}_Value"), vwap
        )
        sell = _side(
            ct.get(f"sell_{key}_Volume"), _first(ct, f"sell_Count{key}", f"sell_{key}_Count"), ct.get(f"sell_{key}_Value"), vwap
        )
        net_value = None if buy["value"] is None or sell["value"] is None else buy["value"] - sell["value"]
        out[label] = {"buy": buy, "sell": sell, "net_volume": buy["volume"] - sell["volume"], "net_value": net_value}

    rb, rs = out["real"]["buy"], out["real"]["sell"]
    power = _safe_div(rb["avg_per_participant"], rs["avg_per_participant"])
    total_buy = out["real"]["buy"]["volume"] + out["legal"]["buy"]["volume"]
    total_sell = out["real"]["sell"]["volume"] + out["legal"]["sell"]["volume"]
    out["real_buyer_power"] = _r(power)  # قدرت خریدار حقیقی (per-capita buy / per-capita sell)
    out["real_share_of_buy_volume_pct"] = _r(rb["volume"] / total_buy * 100) if total_buy else None
    out["real_share_of_sell_volume_pct"] = _r(rs["volume"] / total_sell * 100) if total_sell else None
    out["reading"] = (
        "real_buyer_power > 1: the average real-person buyer is larger than the average real-person seller "
        "(smart-money accumulation proxy). net_* > 0 on 'real' means money flowed INTO the stock from real persons."
    )
    return out


def shape_client_type_history(rows: list[dict]) -> list[dict]:
    """Daily rows (each already a client-type dict with ``recDate``) -> compact time series."""
    series = []
    for row in sorted(rows, key=lambda r: r.get("recDate") or 0):
        shaped = shape_client_type(row)
        series.append(
            {
                "date": fmt_date(row.get("recDate")),
                "jdate": jdate(row.get("recDate")),
                "real_net_volume": shaped["real"]["net_volume"],
                "real_net_value": shaped["real"]["net_value"],
                "real_buy_value": shaped["real"]["buy"]["value"],
                "real_sell_value": shaped["real"]["sell"]["value"],
                "real_buy_count": shaped["real"]["buy"]["count"],
                "real_sell_count": shaped["real"]["sell"]["count"],
                "real_buyer_power": shaped["real_buyer_power"],
                "legal_net_value": shaped["legal"]["net_value"],
            }
        )
    return series


# --------------------------------------------------------------------------- prices


def shape_daily_prices(rows: list[dict], *, adjusted: bool = False) -> tuple[list[dict], list[dict]]:
    """Ascending daily OHLCV. With ``adjusted`` the series is back-adjusted for corporate actions.

    Adjustment events are inferred from the data itself: on an ex-date TSETMC's
    ``priceYesterday`` no longer equals the previous row's ``pClosing``. This captures capital
    increases as well as dividends (the exchange's own adjustment list omits many of them).
    Differences below 0.1% are treated as tick rounding and ignored.
    """
    ordered = sorted((r for r in rows if r.get("dEven")), key=lambda r: r["dEven"])
    factors = [1.0] * len(ordered)
    events: list[dict] = []
    if adjusted:
        running = 1.0
        for i in range(len(ordered) - 1, 0, -1):
            factors[i] = running
            prev_close = _f(ordered[i - 1].get("pClosing"))
            base = _f(ordered[i].get("priceYesterday"))
            if prev_close and base and abs(base / prev_close - 1) > 1e-3:
                ratio = base / prev_close
                running *= ratio
                events.append({"date": fmt_date(ordered[i]["dEven"]), "jdate": jdate(ordered[i]["dEven"]), "factor": round(ratio, 6)})
        factors[0] = running
        events.reverse()

    out = []
    for row, factor in zip(ordered, factors, strict=True):
        def adj(key: str, row: dict = row, factor: float = factor) -> float | None:
            value = _f(row.get(key))
            return None if value is None else round(value * factor, 2)

        close = adj("pClosing")
        base = adj("priceYesterday")
        out.append(
            {
                "date": fmt_date(row["dEven"]),
                "jdate": jdate(row["dEven"]),
                "open": adj("priceFirst"),
                "high": adj("priceMax"),
                "low": adj("priceMin"),
                "close": close,
                "last": adj("pDrCotVal"),
                "volume": _i(row.get("qTotTran5J")),
                "value": _i(row.get("qTotCap")),
                "trades": _i(row.get("zTotTran")),
                "change_pct": pct_change(close, base),
            }
        )
    return out, events


# --------------------------------------------------------------------------- holders


def shape_holders(rows: list[dict]) -> list[dict]:
    holders = [
        {
            "name": clean(r.get("shareHolderName")),
            "shares": _i(r.get("numberOfShares")),
            "percent": _f(r.get("perOfShares")),
            "change_amount": _f(r.get("changeAmount")),
            "holder_id": r.get("shareHolderShareID"),
        }
        for r in rows
    ]
    holders.sort(key=lambda h: h["percent"] or 0, reverse=True)
    return holders


def shape_holder_snapshots(rows: list[dict]) -> list[dict]:
    """Group the dated holder rows into snapshots and compute differences between them."""
    by_date: dict[int, dict[str, dict]] = defaultdict(dict)
    for r in rows:
        name = clean(r.get("shareHolderName")) or "?"
        by_date[int(r.get("dEven") or 0)][name] = r
    snapshots = []
    previous: dict[str, dict] | None = None
    for deven in sorted(by_date):
        current = by_date[deven]
        entries = []
        for name, r in sorted(current.items(), key=lambda kv: -(_f(kv[1].get("perOfShares")) or 0)):
            shares = _f(r.get("numberOfShares")) or 0
            old = _f(previous[name].get("numberOfShares")) if previous and name in previous else None
            entries.append(
                {
                    "name": name,
                    "shares": int(shares),
                    "percent": _f(r.get("perOfShares")),
                    "shares_change": None if old is None else int(shares - old),
                    "new_in_list": previous is not None and name not in previous,
                }
            )
        dropped = [n for n in (previous or {}) if n not in current]
        snapshots.append({"date": fmt_date(deven), "holders": entries, "dropped_from_list": dropped})
        previous = current
    return snapshots


# --------------------------------------------------------------------------- market watch


def _v(value: Any) -> Any:
    return value.get("value") if isinstance(value, dict) else value


def shape_watch_row(row: dict) -> dict:
    last = _f(_v(row.get("lastPrice")))
    upper, lower = _f(row.get("maxValue")), _f(row.get("minValue"))
    sell_qty = _f(_v(row.get("sellQuantity")))
    buy_qty = _f(_v(row.get("buyQuantity")))
    volume = _f(_v(row.get("tradeVolume")))
    value = _f(_v(row.get("tradeValue")))
    at_upper = bool(upper and last is not None and last >= upper)
    at_lower = bool(lower and last is not None and last <= lower)
    effect = _f(row.get("effectonIndex"))
    return {
        "symbol": clean(row.get("instrumentName")),
        "name": clean(row.get("companyNamePersian")),
        "instrument_id": row.get("instrumentId"),
        "last": last,
        "last_pct": _f(_v(row.get("lastPriceChangePercent"))),
        "close": _f(_v(row.get("closingPrice"))),
        "close_pct": _f(_v(row.get("closingPriceChangePercent"))),
        "yesterday": _f(_v(row.get("yesterdayPrice"))),
        "open": _f(_v(row.get("firstPrice"))),
        "high": _f(_v(row.get("highValue"))),
        "low": _f(_v(row.get("lowValue"))),
        "volume": _i(volume),
        "value": _i(value),
        "trades": _i(_v(row.get("tradeCount"))),
        "vwap": _r(_safe_div(value, volume)),
        "price_limits": {"upper": upper, "lower": lower},
        "at_upper_limit": at_upper,
        "at_lower_limit": at_lower,
        "buy_queue_probable": bool(at_upper and not sell_qty),
        "sell_queue_probable": bool(at_lower and not buy_qty),
        "best_bid": {"price": _f(_v(row.get("buyPrice"))), "volume": _i(buy_qty), "orders": _i(_v(row.get("buyCount")))},
        "best_ask": {"price": _f(_v(row.get("sellPrice"))), "volume": _i(sell_qty), "orders": _i(_v(row.get("sellCount")))},
        "pe": next((p for p in (_f(_v(row.get("pe"))),) if p is not None and p > 0), None),
        "eps": _f(_v(row.get("eps"))),
        "market_cap": _i(_v(row.get("marketValue"))),
        "effect_on_index": effect,
        "market": clean(row.get("marketname")),
        "board": clean(row.get("boardName")),
        "industry": clean(row.get("industryname")),
        "sub_industry": clean(row.get("industrysubname")),
        "security_type": clean(row.get("securitiesname")),
        "status": clean(row.get("statename")),
        "market_type": clean(row.get("markettypename")),
    }


WATCH_SORT_KEYS = {
    "last_pct": "last_pct",
    "close_pct": "close_pct",
    "value": "value",
    "volume": "volume",
    "trades": "trades",
    "market_cap": "market_cap",
    "pe": "pe",
    "effect_on_index": "effect_on_index",
}


_LEADING_CODE = re.compile(r"^(\d{1,3})\s*[-–]?\s*(.+)$")
_TRAILING_CODE = re.compile(r"^(.+?)\s*[-–]?\s*(\d{2,3})$")


def shape_index_row(row: dict) -> dict:
    """Index row. Industry indices carry a numeric code that TSETMC writes as ``01-name``, ``26name`` or ``name11``."""
    name = clean(row.get("lVal30")) or ""
    headline = name.startswith("شاخص")
    code: str | None = None
    title = name
    if not headline:
        match = _LEADING_CODE.match(name)
        if match:
            code, title = match.group(1), match.group(2)
        else:
            match = _TRAILING_CODE.match(name)
            if match:
                title, code = match.group(1), match.group(2)
    return {
        "name": title.strip(),
        "code": code,
        "headline": headline,
        "ins_code": str(row.get("insCode")),
        "value": _f(row.get("xDrNivJIdx004")),
        "change": _f(row.get("indexChange")),
        "change_pct": _f(row.get("xVarIdxJRfV")),
        "high": _f(row.get("xPhNivJIdx004")),
        "low": _f(row.get("xPbNivJIdx004")),
        "time": fmt_time(row.get("hEven")),
    }


def shape_overview(overview: dict) -> dict:
    return {
        "market_state": clean(overview.get("marketStateTitle")),
        "market_state_code": overview.get("marketState"),
        "as_of": {"date": fmt_date(overview.get("marketActivityDEven")), "time": fmt_time(overview.get("marketActivityHEven"))},
        "index": {
            "value": _f(overview.get("indexLastValue")),
            "change": _f(overview.get("indexChange")),
            "change_pct": pct_change(_f(overview.get("indexLastValue")), (_f(overview.get("indexLastValue")) or 0) - (_f(overview.get("indexChange")) or 0)),
        },
        "equal_weight_index": {
            "value": _f(overview.get("indexEqualWeightedLastValue")),
            "change": _f(overview.get("indexEqualWeightedChange")),
        },
        "trades": _i(overview.get("marketActivityZTotTran")),
        "volume": _i(overview.get("marketActivityQTotTran")),
        "value": _i(overview.get("marketActivityQTotCap")),
        "market_cap": _i(overview.get("marketValue")),
        "units": "rial",
    }


# --------------------------------------------------------------------------- messages / codal


def shape_message(row: dict, *, full_text: bool = False, limit: int = 500) -> dict:
    text = clean(row.get("tseDesc")) or ""
    return {
        "date": fmt_date(row.get("dEven")),
        "jdate": jdate(row.get("dEven")),
        "time": fmt_time(row.get("hEven")),
        "title": clean(row.get("tseTitle")),
        "text": text if full_text or len(text) <= limit else text[:limit] + "…",
        "truncated": not full_text and len(text) > limit,
    }


def _absolute(base: str, path: str | None) -> str | None:
    from urllib.parse import urljoin

    if not path:
        return None
    return urljoin(base, path)


def shape_codal_letter(row: dict, site: str = "https://codal.ir") -> dict:
    url = row.get("Url")
    page = _absolute(site, url)
    return {
        "tracing_no": row.get("TracingNo"),
        "symbol": clean(row.get("Symbol")),
        "company": clean(row.get("CompanyName")),
        "title": clean(row.get("Title")),
        "letter_code": clean(row.get("LetterCode")),
        "published": ascii_digits(row.get("PublishDateTime") or ""),
        "sent": ascii_digits(row.get("SentDateTime") or ""),
        "under_supervision": bool(row.get("UnderSupervision")),
        "is_estimate": bool(row.get("IsEstimate")),
        "has": {
            "html": bool(row.get("HasHtml")),
            "pdf": bool(row.get("HasPdf")),
            "excel": bool(row.get("HasExcel")),
            "xbrl": bool(row.get("HasXbrl")),
            "attachment": bool(row.get("HasAttachment")),
        },
        "links": {
            "page": page,
            "pdf": _absolute(site + "/", row.get("PdfUrl")) if row.get("HasPdf") else None,
            "excel": row.get("ExcelUrl") or None,
            "attachments": _absolute(site, row.get("AttachmentUrl")) if row.get("HasAttachment") else None,
        },
    }


def shape_statistics(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        raw = r.get("dataValue")
        number = _f(raw)
        out.append(
            {
                "metric": clean(r.get("dataTypeDesc")),
                "value": number if number is not None else clean(raw),
                "code": r.get("dataType"),
            }
        )
    return out
