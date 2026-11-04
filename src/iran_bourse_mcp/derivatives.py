"""Options (اختیار معامله) and futures (آتی): the derivatives market's own chain feeds, shaped for agents.

``Instrument/GetInstrumentOptionMarketWatch/{flow}`` returns one row per strike/expiry pair (about 940 pairs on 27
underlyings): the call and the put of a pair share the row with the underlying's prices. ``Instrument/
GetInstrumentFutureMarketWatch/0`` returns the futures (about 16 contracts). Everything here is pure: raw rows in,
dicts out, no I/O.

What the feeds say and do not say (checked against the live feeds, 2026-11-04):

* prices are rial per underlying unit; volume and open interest count contracts and one contract is ``contract_size``
  units of the underlying (1,000 for almost every underlying); value is rial of premium (contracts x size x price);
* a leg that did not trade today still carries a price (the previous one, or a placeholder of 1 rial), so ``last`` and
  ``close`` are None unless it traded today, and nothing is derived from a stale price;
* open interest is published once a day by the clearing house: for options the exchange's own "change" is 0 on every
  row, and for futures ``yesterdayMOP`` is 0 on every contract. It is reported as published, never as an intraday change;
* the feed's ``notionalValue`` is wrong for some underlyings (it uses another symbol's price) and is not used;
* the exchange's own ITM/OTM column compares the strike with the underlying's *closing* price (checked on all 1,872
  legs); moneyness, intrinsic value, time value and break-even here use the same prices: the option's closing price
  against the underlying's closing price (both are volume-weighted averages of the day).

Anything the exchange does not publish lives under a ``derived`` key (or is named ``estimate``).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .dates import DateError, fmt_date, jdate, parse_date
from .shape import _f, _i, _r, pct_change
from .text import clean, match_key

OPTION_MARKETS = {"all": 0, "both": 0, "bourse": 1, "fara": 2, "fara-bourse": 2, "ifb": 2}  # option-chain "flow" of each market word
MARKET_LABELS = {0: "all", 1: "bourse", 2: "fara"}
OPTION_SORT_KEYS = ("strike", "distance", "volume", "open_interest", "value")  # strike rows of a chain
UNDERLYING_SORT_KEYS = ("open_interest", "volume", "value", "name", "expiry")  # the underlyings summary
FUTURES_SORT_KEYS = ("expiry", "underlying", "open_interest", "volume", "value", "basis_pct")
DEFAULT_STRIKES, MAX_STRIKES = 15, 60  # strike rows returned by one chain call (all expiries together)
DEFAULT_UNDERLYINGS, MAX_UNDERLYINGS = 30, 60
DEFAULT_FUTURES, MAX_FUTURES = 20, 50
DAYS_PER_YEAR = 365  # simple annualisation of the futures basis
_SIDE_NAMES = {"C": "call", "P": "put"}
_TYPE_WORDS = {"call": "C", "calls": "C", "c": "C", "خرید": "C", "put": "P", "puts": "P", "p": "P", "فروش": "P", "both": None, "all": None, "": None}
_MONEYNESS_WORDS = {"itm": "ITM", "otm": "OTM", "atm": "ATM", "all": None, "any": None, "": None}

UNITS = "rial per underlying unit; volume and open_interest in contracts (1 contract = contract_size underlying units); value in rial"
CHAIN_NOTES = [
    "derived = computed here, not published: moneyness, intrinsic, time_value, breakeven, spread_pct, put_call_* and max_pain_estimate. "
    "They use the option's and the underlying's closing prices (the exchange's own ITM/OTM rule), intrinsic = max(spot - strike, 0) for a call and "
    "max(strike - spot, 0) for a put, time_value = close - intrinsic (negative when the two prices are from different moments), "
    "breakeven = strike + close (call) or strike - close (put), spread_pct = (ask - bid) / mid, put_call_* = put / call, "
    "max_pain_estimate = the listed strike where the summed intrinsic value of all open calls and puts is lowest.",
    "null last/close = no trade today (the feed repeats an old price); {symbol, active: false} = no trades, open interest or quotes. "
    "totals and derived ratios cover the whole expiry. open_interest is the clearing house's daily figure, not intraday.",
]
FUTURES_NOTES = [
    "derived = computed here, not published: basis = close - underlying close (rial per unit), basis_pct = basis / underlying close, "
    "annualized_basis_pct_estimate = basis_pct * 365 / days_to_expiry (simple, not compounded; null on the expiry day). "
    "The basis mixes carry (interest) with sentiment and thin trading; it is None without a trade today.",
    "null last/close = no trade today (the feed repeats an old price). Bid and ask are mostly market-maker quotes and can be very wide. "
    "open_interest_change is null because the exchange publishes no figure for yesterday's open interest (0 on every contract).",
]


# ------------------------------------------------------------------------------------------------ small helpers


def _n(value: Any) -> int | float | None:
    """A rial amount: int when whole (the feed sends 26800.0), else two decimals."""
    number = _f(value)
    if number is None:
        return None
    return int(number) if number == int(number) else round(number, 2)


def _pos(value: Any) -> int | float | None:
    """A price or quantity that exists: positive, else None (0 means "no quote" in these feeds)."""
    number = _f(value)
    return _n(number) if number is not None and number > 0 else None


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def _none_last(value: Any, descending: bool) -> tuple:
    """Sort key that puts None last in either direction."""
    if value is None:
        return (1, 0)
    return (0, -value if descending else value)


def _ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def option_flow(market: str | None) -> int:
    """The feed's ``flow`` for a market word: omit/'all' = 0 (both), 'bourse' = 1, 'fara' = 2. Raises ValueError otherwise."""
    if market is None or not str(market).strip():
        return 0
    flow = OPTION_MARKETS.get(str(market).strip().lower())
    if flow is None:
        raise ValueError("market must be 'bourse', 'fara' or omitted (both markets).")
    return flow


def option_side(option_type: str | None) -> str | None:
    """'C' for call (خرید), 'P' for put (فروش), None for both."""
    if option_type is None:
        return None
    key = (clean(option_type) or "").casefold()
    if key in _TYPE_WORDS:
        return _TYPE_WORDS[key]
    raise ValueError(f"option_type '{option_type}' is not recognised. Use 'call', 'put' or 'both' (omit for both).")


def option_moneyness(moneyness: str | None) -> str | None:
    """'ITM', 'ATM', 'OTM' or None (no filter)."""
    if moneyness is None:
        return None
    key = (clean(moneyness) or "").casefold()
    if key in _MONEYNESS_WORDS:
        return _MONEYNESS_WORDS[key]
    raise ValueError(
        f"moneyness '{moneyness}' is not recognised. Use 'itm' (in the money), 'otm' (out of the money) or 'atm' "
        "(the strike nearest to the underlying's price)."
    )


def _check_sort(sort_by: str | None, allowed: tuple[str, ...], default: str) -> str:
    key = default if sort_by is None or not str(sort_by).strip() else str(sort_by).strip().lower()
    if key not in allowed:
        raise ValueError(f"sort_by must be one of {', '.join(allowed)}.")
    return key


def _expiry_arg(expiry: str | int | None) -> tuple[str, int | None]:
    """('default'|'nearest'|'all'|'date', YYYYMMDD)."""
    if expiry is None or not str(expiry).strip():
        return "default", None
    text = clean(expiry) or ""
    key = text.casefold()
    if key in ("nearest", "near", "first"):
        return "nearest", None
    if key in ("all", "*"):
        return "all", None
    try:
        return "date", parse_date(text)
    except DateError as exc:
        raise ValueError(
            f"expiry '{expiry}' is not 'nearest', 'all' or a date. Use 2026-11-18 or 20261118 (Gregorian) or 1405/08/27 (Jalali)."
        ) from exc


def _expiry_label(deven: int) -> str:
    return f"{fmt_date(deven)} ({jdate(deven)})"


# ------------------------------------------------------------------------------------------------ parsing


def _leg(raw: dict, side: str) -> dict:
    """One side (C or P) of a chain row as plain numbers; prices exist only if the leg traded today."""
    volume, trades = _i(raw.get(f"qTotTran5J_{side}")) or 0, _i(raw.get(f"zTotTran_{side}")) or 0
    traded = volume > 0 or trades > 0
    bid_qty, ask_qty = _i(raw.get(f"qTitMeDem_{side}")) or 0, _i(raw.get(f"qTitMeOf_{side}")) or 0
    bid = _pos(raw.get(f"pMeDem_{side}")) if bid_qty > 0 else None
    ask = _pos(raw.get(f"pMeOf_{side}")) if ask_qty > 0 else None
    open_interest = _i(raw.get(f"oP_{side}")) or 0
    return {
        "symbol": clean(raw.get(f"lVal18AFC_{side}")),
        "ins_code": str(raw.get(f"insCode_{side}") or "") or None,
        "traded": traded,
        "last": _pos(raw.get(f"pDrCotVal_{side}")) if traded else None,
        "close": _pos(raw.get(f"pClosing_{side}")) if traded else None,
        "yesterday": _pos(raw.get(f"priceYesterday_{side}")),
        "bid": bid,
        "bid_qty": bid_qty if bid else None,
        "ask": ask,
        "ask_qty": ask_qty if ask else None,
        "volume": volume,
        "trades": trades,
        "value": _i(raw.get(f"qTotCap_{side}")) or 0,
        "open_interest": open_interest,
        "active": traded or open_interest > 0 or bid is not None or ask is not None,
    }


def _parse_option_row(raw: dict) -> dict | None:
    strike, end = _pos(raw.get("strikePrice")), _i(raw.get("endDate"))
    name = clean(raw.get("lval30_UA") or raw.get("lVal30_UA"))
    if strike is None or not end or not name:
        return None
    close, last = _pos(raw.get("pClosing_UA")), _pos(raw.get("pDrCotVal_UA"))
    return {
        "ua_code": str(raw.get("uaInsCode") or name),
        "ua_name": name,
        "strike": strike,
        "end": end,
        "days": _i(raw.get("remainedDay")),
        "size": _i(raw.get("contractSize")) or 1000,
        "spot": close or last,  # the exchange's ITM/OTM flag uses the underlying's closing price
        "spot_close": close,
        "spot_last": last,
        "spot_yesterday": _pos(raw.get("priceYesterday_UA")),
        "C": _leg(raw, "C"),
        "P": _leg(raw, "P"),
    }


def _parse_option_rows(rows: list[dict] | None) -> list[dict]:
    parsed = (_parse_option_row(r) for r in rows or [] if isinstance(r, dict))
    return [p for p in parsed if p is not None]


# ------------------------------------------------------------------------------------------------ derived values


def _moneyness(side: str, strike: float, spot: float | None) -> str | None:
    if spot is None:
        return None
    if spot == strike:
        return "ATM"
    in_money = spot > strike if side == "C" else spot < strike
    return "ITM" if in_money else "OTM"


def _intrinsic(side: str, strike: float, spot: float | None) -> int | float | None:
    if spot is None:
        return None
    return _n(max(spot - strike, 0) if side == "C" else max(strike - spot, 0))


def _derived(side: str, strike: float, spot: float | None, leg: dict) -> dict:
    """Moneyness, intrinsic value, time value, break-even and spread of one leg. None where an input is missing."""
    intrinsic, close = _intrinsic(side, strike, spot), leg["close"]
    time_value = _n(close - intrinsic) if close is not None and intrinsic is not None else None
    breakeven = None
    if close is not None:
        breakeven = _n(strike + close if side == "C" else strike - close)
    bid, ask = leg["bid"], leg["ask"]
    spread = None
    if bid is not None and ask is not None and ask >= bid:
        spread = _r((ask - bid) / ((ask + bid) / 2) * 100)
    return {
        "moneyness": _moneyness(side, strike, spot),
        "intrinsic": intrinsic,
        "time_value": time_value,
        "breakeven": breakeven,
        "breakeven_pct": pct_change(breakeven, spot) if breakeven is not None else None,
        "spread_pct": spread,
    }


def max_pain_estimate(strikes: list[dict], size: int, spot: float | None) -> dict | None:
    """The listed strike at which the summed intrinsic value of all open calls and puts of one expiry is lowest.

    ``payout_rial`` is that sum (open contracts x contract size x intrinsic value per unit). The sum is convex and
    piecewise linear with kinks at the listed strikes, so its minimum is always at one of them; ties go to the strike
    nearest the spot. An estimate: open interest is the clearing house's last published figure and positions may be
    closed or exercised before expiry. None when there is no open interest.
    """
    book = [(p["strike"], p["C"]["open_interest"], p["P"]["open_interest"]) for p in strikes]
    if not any(c or p for _, c, p in book):
        return None
    candidates = [
        (sum(c * max(settle - k, 0) + p * max(k - settle, 0) for k, c, p in book) * size, abs(settle - spot) if spot else 0.0, settle)
        for settle, _, _ in book
    ]
    payout, _, strike = min(candidates)
    return {"strike": _n(strike), "payout_rial": _i(payout)}


def _top_oi(strikes: list[dict], side: str, spot: float | None) -> dict | None:
    """The strike with the most open interest on one side (ties: nearest the spot, then lower)."""
    ranked = [(p["strike"], p[side]["open_interest"]) for p in strikes if p[side]["open_interest"] > 0]
    if not ranked:
        return None
    strike, oi = min(ranked, key=lambda t: (-t[1], abs(t[0] - spot) if spot else 0.0, t[0]))
    return {"strike": _n(strike), "open_interest": oi}


def _nearest_strike(strikes: list[dict], spot: float | None) -> float | None:
    if spot is None or not strikes:
        return None
    return min((p["strike"] for p in strikes), key=lambda k: (abs(k - spot), k))


def _sum(strikes: list[dict], side: str, field: str) -> int:
    return sum(p[side][field] for p in strikes)


def _group_totals(strikes: list[dict], spot: float | None, size: int) -> tuple[dict, dict]:
    totals = {
        "call_volume": _sum(strikes, "C", "volume"), "put_volume": _sum(strikes, "P", "volume"),
        "call_value": _sum(strikes, "C", "value"), "put_value": _sum(strikes, "P", "value"),
        "call_open_interest": _sum(strikes, "C", "open_interest"), "put_open_interest": _sum(strikes, "P", "open_interest"),
    }
    derived = {
        "put_call_oi_ratio": _ratio(totals["put_open_interest"], totals["call_open_interest"]),
        "put_call_volume_ratio": _ratio(totals["put_volume"], totals["call_volume"]),
        "atm_strike": _n(_nearest_strike(strikes, spot)),
        "max_oi_strike": {"call": _top_oi(strikes, "C", spot), "put": _top_oi(strikes, "P", spot)},
        "max_pain_estimate": max_pain_estimate(strikes, size, spot),
    }
    return totals, derived


# ------------------------------------------------------------------------------------------------ underlyings


def _underlying_names(parsed: list[dict]) -> dict[str, str]:
    return {p["ua_code"]: p["ua_name"] for p in parsed}


def resolve_underlying(parsed: list[dict], query: str) -> tuple[str, str, int | None]:
    """(underlying code, name, expiry hint) for a Persian name or fragment, its insCode, or one of its options (symbol or insCode).

    An exact name wins over a fragment; a fragment that fits several underlyings is an error that lists them.
    The expiry hint is only set when ``query`` is an option symbol (then that option's expiry is the default).
    """
    names = _underlying_names(parsed)
    key = match_key(query)
    if not key:
        raise ValueError("underlying is empty. Pass a Persian symbol such as 'اهرم' or 'شپنا', or omit it to list the underlyings.")
    if str(query).strip() in names:
        return str(query).strip(), names[str(query).strip()], None
    exact = [(code, name) for code, name in names.items() if match_key(name) == key]
    if len(exact) == 1:
        return exact[0][0], exact[0][1], None
    fuzzy = exact or [(code, name) for code, name in names.items() if key in match_key(name)]
    if len(fuzzy) == 1:
        return fuzzy[0][0], fuzzy[0][1], None
    if len(fuzzy) > 1:
        listed = ", ".join(sorted(name for _, name in fuzzy))
        raise ValueError(f"'{query}' matches {len(fuzzy)} underlyings ({listed}). Be more specific.")
    for p in parsed:  # an option symbol such as ضهرم8029 (or its insCode) leads to its underlying and expiry
        if key in (match_key(p["C"]["symbol"]), match_key(p["P"]["symbol"]), p["C"]["ins_code"], p["P"]["ins_code"]):
            return p["ua_code"], p["ua_name"], p["end"]
    listed = ", ".join(sorted(names.values()))
    raise ValueError(
        f"No underlying with listed options matches '{query}'. Underlyings with options ({len(names)}): {listed}. "
        "Omit underlying to see them with their expiries."
    )


def _pick_expiries(available: list[int], mode: str, date: int | None, hint: int | None, name: str) -> list[int]:
    if mode == "all":
        return available
    if mode == "date":
        if date not in available:
            listed = ", ".join(_expiry_label(d) for d in available)
            raise ValueError(f"{name} has no option expiring {_expiry_label(date or 0)}. Listed expiries: {listed}.")
        return [date]
    if mode == "default" and hint in available:
        return [hint]
    return available[:1]


def _expiry_info(group: list[dict]) -> dict:
    end = group[0]["end"]
    return {
        "expiry": fmt_date(end), "expiry_jalali": jdate(end), "days_to_expiry": group[0]["days"],
        "strikes": len(group), "open_interest": sum(p["C"]["open_interest"] + p["P"]["open_interest"] for p in group),
    }


# ------------------------------------------------------------------------------------------------ chain output


def _leg_out(side: str, p: dict, spot: float | None) -> dict:
    leg = p[side]
    derived = _derived(side, p["strike"], spot, leg)
    if not leg["active"]:
        return {"symbol": leg["symbol"], "active": False, "derived": {"moneyness": derived["moneyness"], "intrinsic": derived["intrinsic"]}}
    return {
        "symbol": leg["symbol"],
        "last": leg["last"], "close": leg["close"], "close_pct": pct_change(leg["close"], leg["yesterday"]),
        "bid": leg["bid"], "bid_qty": leg["bid_qty"], "ask": leg["ask"], "ask_qty": leg["ask_qty"],
        "volume": leg["volume"], "trades": leg["trades"], "value": leg["value"], "open_interest": leg["open_interest"],
        "derived": derived,
    }


def _entry_metric(entry: dict, field: str) -> float:
    return sum((entry.get(name) or {}).get(field) or 0 for name in ("call", "put"))


def _group_out(group: list[dict], *, side: str | None, money: str | None, min_volume: float, min_oi: float, window: float | None,
               sort_by: str, budget: int) -> dict:
    first = group[0]
    spot, size = first["spot"], first["size"]
    totals, derived = _group_totals(group, spot, size)
    atm = _nearest_strike(group, spot)
    sides = [side] if side else ["C", "P"]
    entries: list[dict] = []
    for p in group:
        k = p["strike"]
        if window is not None and (spot is None or abs(k / spot - 1) * 100 > window):
            continue
        if money == "ATM" and k != atm:
            continue
        legs: dict[str, dict] = {}
        for s in sides:
            leg = p[s]
            if money in ("ITM", "OTM") and _moneyness(s, k, spot) != money:
                continue
            if leg["volume"] < min_volume or leg["open_interest"] < min_oi:
                continue
            legs[_SIDE_NAMES[s]] = _leg_out(s, p, spot)
        if not legs:
            continue
        entry: dict[str, Any] = {"strike": _n(k), "strike_vs_spot_pct": pct_change(k, spot)}
        if k == atm:
            entry["atm"] = True
        entries.append({**entry, **legs})
    matched = len(entries)

    def rank(entry: dict) -> tuple:
        if sort_by in ("strike", "distance"):  # trimming keeps the strikes nearest the spot
            return (abs(entry["strike"] - spot) if spot else 0.0, entry["strike"])
        return (-_entry_metric(entry, sort_by), entry["strike"])

    if matched > budget:
        entries = sorted(entries, key=rank)[:budget]
    entries.sort(key=(lambda e: e["strike"]) if sort_by == "strike" else rank)
    return {
        "expiry": fmt_date(first["end"]), "expiry_jalali": jdate(first["end"]), "days_to_expiry": first["days"],
        "expires_today": first["days"] == 0, "contract_size": size,
        "spot": {"close": first["spot_close"], "last": first["spot_last"], "yesterday": first["spot_yesterday"],
                 "close_pct": pct_change(first["spot_close"], first["spot_yesterday"])},
        "strikes_total": len(group), "strikes_matched": matched, "truncated": matched > len(entries),
        "totals": totals, "derived": derived,
        "strikes": entries,
    }


def option_chain(
    rows: list[dict] | None,
    underlying: str | None = None,
    expiry: str | int | None = None,
    *,
    market: str | None = None,
    option_type: str | None = None,
    moneyness: str | None = None,
    min_volume: float = 0,
    min_open_interest: float = 0,
    strike_window_pct: float | None = None,
    sort_by: str | None = None,
    limit: int | None = None,
) -> dict:
    """The option chain of one underlying, or (without ``underlying``) the list of underlyings that have options.

    ``rows`` is the ``instrumentOptMarketWatch`` list of the feed. ``market`` only labels the result (the service
    chooses the feed's flow with :func:`option_flow`). With ``underlying`` (Persian name or fragment, insCode, or one
    of its option symbols) the result has one group per expiry: ``expiry`` is 'nearest' (default), 'all' or a
    Gregorian/Jalali date. ``option_type`` (call/put), ``moneyness`` (itm/otm/atm), ``min_volume``,
    ``min_open_interest`` and ``strike_window_pct`` (strikes within that percent of the spot) choose which legs and
    strikes are shown, and ``sort_by`` (strike, distance, volume, open_interest, value) orders them. ``limit`` caps
    the strike rows in total; when more match, the ones nearest the spot (or with the most volume/open interest)
    are kept. Group totals, ratios and max pain always cover the whole expiry. Raises ValueError for bad input.
    """
    label = MARKET_LABELS[option_flow(market)]
    side, money = option_side(option_type), option_moneyness(moneyness)
    mode, date = _expiry_arg(expiry)
    min_volume, min_open_interest = min_volume or 0, min_open_interest or 0
    if min_volume < 0 or min_open_interest < 0:
        raise ValueError("min_volume and min_open_interest must be 0 or more.")
    if strike_window_pct is not None and strike_window_pct <= 0:
        raise ValueError("strike_window_pct must be above 0 (for example 10 keeps strikes within 10% of the underlying's price).")
    parsed = _parse_option_rows(rows)
    if underlying is None or not str(underlying).strip():
        if side or money or min_volume or min_open_interest or strike_window_pct is not None:
            raise ValueError(
                "option_type, moneyness, min_volume, min_open_interest and strike_window_pct filter the legs of one chain: "
                "pass underlying (omit it to list the underlyings and their expiries)."
            )
        return _underlyings_out(parsed, label, mode, date, _check_sort(sort_by, UNDERLYING_SORT_KEYS, "open_interest"),
                                _clamp(DEFAULT_UNDERLYINGS if limit is None else limit, 1, MAX_UNDERLYINGS))
    sort = _check_sort(sort_by, OPTION_SORT_KEYS, "strike")
    count = _clamp(DEFAULT_STRIKES if limit is None else limit, 1, MAX_STRIKES)
    if not parsed:
        return {"mode": "chain", "market": label, "underlying": clean(underlying), "groups": [], "note": "The exchange lists no options right now."}
    code, name, hint = resolve_underlying(parsed, str(underlying))
    mine = [p for p in parsed if p["ua_code"] == code]
    by_expiry: dict[int, list[dict]] = defaultdict(list)
    for p in mine:
        by_expiry[p["end"]].append(p)
    available = sorted(by_expiry)
    chosen = _pick_expiries(available, mode, date, hint, name)
    budget = max(1, count // len(chosen))
    groups = [
        _group_out(sorted(by_expiry[end], key=lambda p: p["strike"]), side=side, money=money, min_volume=min_volume, min_oi=min_open_interest,
                   window=strike_window_pct, sort_by=sort, budget=budget)
        for end in chosen
    ]
    filters = {k: v for k, v in {
        "option_type": _SIDE_NAMES.get(side or ""), "moneyness": money.lower() if money else None,
        "min_volume": min_volume or None, "min_open_interest": min_open_interest or None, "strike_window_pct": strike_window_pct,
    }.items() if v is not None}
    result: dict[str, Any] = {
        "mode": "chain", "market": label, "underlying": name, "underlying_ins_code": code, "sorted_by": sort,
        "groups": groups,
    }
    if filters:
        result["filters"] = filters
    others = [_expiry_info(sorted(by_expiry[end], key=lambda p: p["strike"])) for end in available if end not in chosen]
    if others:
        result["other_expiries"] = others
    if not any(g["strikes"] for g in groups):
        result["note"] = "No strike matches these filters; loosen them or call without filters."
    result["units"] = UNITS
    result["notes"] = CHAIN_NOTES
    return result


def _underlyings_out(parsed: list[dict], label: str, mode: str, date: int | None, sort_by: str, limit: int) -> dict:
    """One line per underlying that has options: expiries, open interest and volume (``expiry`` narrows the rows counted)."""
    by_ua: dict[str, list[dict]] = defaultdict(list)
    for p in parsed:
        by_ua[p["ua_code"]].append(p)
    items: list[dict] = []
    for code, rows in by_ua.items():
        expiries = sorted({p["end"] for p in rows})
        if mode == "nearest":
            expiries = expiries[:1]
        elif mode == "date":
            expiries = [d for d in expiries if d == date]
        if not expiries:
            continue
        sel = [p for p in rows if p["end"] in expiries]
        call_oi, put_oi = sum(p["C"]["open_interest"] for p in sel), sum(p["P"]["open_interest"] for p in sel)
        first = min(sel, key=lambda p: p["end"])
        items.append({
            "underlying": rows[0]["ua_name"], "underlying_ins_code": code, "spot_close": first["spot_close"],
            "expiries": len(expiries), "nearest_expiry": fmt_date(expiries[0]), "nearest_expiry_jalali": jdate(expiries[0]),
            "days_to_nearest_expiry": first["days"], "strikes": len(sel),
            "open_interest": call_oi + put_oi, "put_call_oi_ratio": _ratio(put_oi, call_oi),
            "volume": sum(p["C"]["volume"] + p["P"]["volume"] for p in sel), "value": sum(p["C"]["value"] + p["P"]["value"] for p in sel),
        })
    if sort_by == "name":
        items.sort(key=lambda i: match_key(i["underlying"]))
    elif sort_by == "expiry":
        items.sort(key=lambda i: (i["nearest_expiry"], match_key(i["underlying"])))
    else:
        items.sort(key=lambda i: (-i[sort_by], match_key(i["underlying"])))
    listed = sorted({p["end"] for p in parsed})
    result: dict[str, Any] = {
        "mode": "underlyings", "market": label, "underlyings_total": len(items), "sorted_by": sort_by, "underlyings": items[:limit],
        "expiries_listed": [fmt_date(d) for d in listed],
        "hint": "Pass underlying='<name>' (and optionally expiry, option_type, moneyness) for its call/put chain.",
        "units": UNITS,
    }
    if not items:
        result["note"] = f"No option expires {_expiry_label(date)}. expiries_listed has the expiry dates." if date else "The exchange lists no options right now."
    return result


# ------------------------------------------------------------------------------------------------ futures


def _future(raw: dict) -> dict | None:
    name, end = clean(raw.get("lVal30_UA")), _i(raw.get("endDate"))
    if not name or not end:
        return None
    volume, trades = _i(raw.get("qTotTran5J")) or 0, _i(raw.get("zTotTran")) or 0
    traded = volume > 0 or trades > 0
    bid_qty, ask_qty = _i(raw.get("qTitMeDem")) or 0, _i(raw.get("qTitMeOf")) or 0
    bid = _pos(raw.get("pMeDem")) if bid_qty > 0 else None
    ask = _pos(raw.get("pMeOf")) if ask_qty > 0 else None
    close, last = (_pos(raw.get("pClosing")), _pos(raw.get("pDrCotVal"))) if traded else (None, None)
    yesterday_oi = _i(raw.get("yesterdayMOP")) or 0
    open_interest = _i(raw.get("mop")) or 0
    spot_close = _pos(raw.get("pClosing_UA"))
    days = _i(raw.get("remainedDay"))
    basis = _n(close - spot_close) if close is not None and spot_close is not None else None
    annualized = None
    if basis is not None and days and days > 0:  # from the unrounded percentage
        annualized = _r((close - spot_close) / spot_close * 100 * DAYS_PER_YEAR / days)
    return {
        "symbol": clean(raw.get("lVal18AFC")), "underlying": name,
        "expiry": fmt_date(end), "expiry_jalali": jdate(end), "days_to_expiry": days, "contract_size": _i(raw.get("contractSize")) or 1000,
        "last": last, "close": close, "close_pct": pct_change(close, _pos(raw.get("priceYesterday"))), "yesterday": _pos(raw.get("priceYesterday")),
        "bid": bid, "bid_qty": bid_qty if bid else None, "ask": ask, "ask_qty": ask_qty if ask else None,
        "volume": volume, "trades": trades, "value": _i(raw.get("qTotCap")) or 0,
        "open_interest": open_interest, "open_interest_change": open_interest - yesterday_oi if yesterday_oi > 0 else None,
        "underlying_close": spot_close,
        "derived": {"basis": basis, "basis_pct": pct_change(close, spot_close), "annualized_basis_pct_estimate": annualized},
        "_end": end,
    }


def futures_market(
    rows: list[dict] | None,
    underlying: str | None = None,
    *,
    sort_by: str | None = None,
    descending: bool | None = None,
    limit: int | None = None,
) -> dict:
    """The futures (آتی) of the market with basis against the underlying.

    ``rows`` is the ``instrumentFtMarketWatch`` list of the feed. ``underlying`` is a Persian name or fragment (or the
    contract's own symbol); ``sort_by`` is expiry (default, nearest first), underlying, open_interest, volume, value or
    basis_pct, and ``descending`` flips the default direction (largest first for the numeric keys). Raises ValueError
    for an unknown ``sort_by`` or an underlying with no futures.
    """
    key = _check_sort(sort_by, FUTURES_SORT_KEYS, "expiry")
    count = _clamp(DEFAULT_FUTURES if limit is None else limit, 1, MAX_FUTURES)
    contracts = [c for c in (_future(r) for r in rows or [] if isinstance(r, dict)) if c is not None]
    total = len(contracts)
    if underlying is not None and str(underlying).strip():
        needle = match_key(underlying)
        hit = [c for c in contracts if needle in match_key(c["underlying"]) or needle == match_key(c["symbol"])]
        if not hit and contracts:
            listed = ", ".join(sorted({c["underlying"] for c in contracts}, key=match_key))
            raise ValueError(f"No futures contract matches '{underlying}'. Underlyings with futures: {listed}.")
        contracts = hit
    numeric = {
        "open_interest": lambda c: c["open_interest"], "volume": lambda c: c["volume"], "value": lambda c: c["value"],
        "basis_pct": lambda c: c["derived"]["basis_pct"],
    }
    if key in numeric:
        desc = True if descending is None else descending
        contracts.sort(key=lambda c: (_none_last(numeric[key](c), desc), c["_end"], c["symbol"]))
    elif key == "underlying":
        contracts.sort(key=lambda c: (match_key(c["underlying"]), c["_end"], c["symbol"]), reverse=bool(descending))
    else:
        contracts.sort(key=lambda c: (c["_end"], match_key(c["underlying"]), c["symbol"]), reverse=bool(descending))
    matched = len(contracts)
    out = [{k: v for k, v in c.items() if k != "_end"} for c in contracts[:count]]
    result: dict[str, Any] = {
        "total_contracts": total, "matched": matched, "returned": len(out), "sorted_by": key, "contracts": out,
        "units": UNITS,
        "notes": FUTURES_NOTES,
    }
    if not total:
        result["note"] = "The exchange lists no futures right now."
    return result
