"""Iran Mercantile Exchange (IME, بورس کالای ایران): the physical commodity market, shaped for agents.

Pure shaping code over the public ASMX services that ime.co.ir's own pages call (see ``api.TseApi.ime_*``); nothing here touches
the network. What the exchange publishes, and how it is read here:

* ``GetAmareMoamelatList`` (page «آمار معاملات فیزیکی»): one row per offer or contract of a session. ``Quantity`` is the traded
  volume in **tons** (``Unit`` is "تن" on every one of 1,184 rows checked over five sessions), ``Price`` is the weighted-average
  closing price in **rial per kilogram**, and ``TotalPrice`` is the value in **thousand rial** (the page's own column header,
  «ارزش معامله (هزارریال)»). The per-kilogram reading of ``Price`` is not stated by the exchange; it follows from
  ``TotalPrice = Price x Quantity`` holding to within 2e-5 on all 1,045 traded rows (tons x 1,000 kg/ton / 1,000 = thousand rial),
  and the Energy Exchange states the same convention in its own detail records (rial per kilogram, factor 1,000 per ton).
  ``arze`` is the offered volume (0 for matching contracts, which have no fixed offer), ``taghaza`` the demand, both in tons.
* ``GetHomeFizikiWithDateGrid`` / ``GetHomeNamaWithDateGrid`` / ``GetHajmArzeshMoamelatDateGrid``: roll-ups by ring, by market
  and by day. Values are million rial (the page's header «ارزش(میلیون ریال)»); the volume of a physical ring is tons
  (the sum of ``OfferVolume`` over the three rings, 414,056 t on 2026-11-04, is IME's own headline «۴۱۴ هزار تن»).
* The roll-up is **not** the sum of the list: the list excludes the sub-market (بازار فرعی) and other halls, and on 2026-11-04
  its value reached about 85% of the roll-up. Totals are therefore reported separately and never added together.

Dates are Jalali strings on the wire (``1405/08/13``); the parameters are called "Gregorian" and a Gregorian value is an HTTP 500.
The market trades Saturday to Wednesday; Thursday and Friday answer an empty list.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from .dates import DateError, fmt_date, from_date, jdate, parse_date, to_date
from .shape import _f, _i
from .text import clean, match_key

MARKET_NAME = "بورس کالای ایران - بازار فیزیکی (IME physical market)"
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MAX_TRADE_DAYS = 7  # a session is 100 to 400 KB of JSON; a week is 1.2 MB
MAX_SUMMARY_DAYS = 366
RECENT_DAYS = 14  # how far back the search for the latest session reaches
CHART_DAYS = 10  # sessions shown beside a one-day summary

# GetMainGroups on 2026-11-05. 7 («بازار فرعی», the sub-market) is served by a different flag of the list service and is not offered here.
MAIN_GROUPS: dict[int, str] = {
    1: "صنعتی",
    2: "کشاورزی",
    3: "پتروشیمی و فرآورده های نفتی",
    4: "معدنی",
    5: "فرآورده های نفتی",
    6: "اموال غیر منقول",
}
GROUP_WORDS = {
    "industrial": 1,
    "industry": 1,
    "metals": 1,
    "steel": 1,
    "cement": 1,
    "agricultural": 2,
    "agriculture": 2,
    "farm": 2,
    "petrochemical": 3,
    "petrochemicals": 3,
    "petrochem": 3,
    "mining": 4,
    "mineral": 4,
    "minerals": 4,
    "oil": 5,
    "oilproducts": 5,
    "realestate": 6,
    "property": 6,
}
SORT_KEYS = {
    "value": "value_rial",
    "volume": "volume_tons",
    "price": "price_rial_per_kg",
    "demand": "demand_tons",
    "offered": "offered_tons",
    "name": "product",
}
VIEWS = {
    "trades": "trades",
    "board": "trades",
    "offers": "trades",
    "summary": "summary",
    "overview": "summary",
    "history": "summary",
}


@dataclass(frozen=True)
class CommodityRequest:
    """A validated ``commodity_market`` call. ``start`` / ``end`` are Gregorian ``YYYYMMDD`` or ``None`` for the latest session."""

    view: str
    start: int | None
    end: int | None
    main_cat: int
    product: str | None
    traded_only: bool
    sort_by: str
    limit: int


def parse_group(group: object) -> int:
    """``None`` / 'all' -> 0 (every group); an id, an English word or a Persian fragment -> the main-group id."""
    if group is None or str(group).strip().casefold() in ("", "all", "*", "0", "همه"):
        return 0
    text = str(group).strip()
    if text.isdigit() and int(text) in MAIN_GROUPS:
        return int(text)
    word = GROUP_WORDS.get(match_key(text).replace("-", "").replace("_", ""))
    if word:
        return word
    key = match_key(text)
    found = [gid for gid, name in MAIN_GROUPS.items() if key and key in match_key(name)]
    if len(found) == 1:
        return found[0]
    if len(found) > 1:  # «نفتی» is in both 3 and 5: prefer the exact name, otherwise ask
        exact = [gid for gid in found if match_key(MAIN_GROUPS[gid]) == key]
        if len(exact) == 1:
            return exact[0]
    options = ", ".join(f"{gid} {name}" for gid, name in MAIN_GROUPS.items())
    raise ValueError(
        f"Unknown or ambiguous group '{group}'. Use an id or name: {options} (omit for every group)."
    )


def plan(
    view: str | None,
    date: str | int | None,
    to_date_: str | int | None,
    group: object,
    product: str | None,
    traded_only: bool,
    sort_by: str | None,
    limit: int | None,
) -> CommodityRequest:
    """Check the arguments; raises ``ValueError`` (``DateError`` for bad dates) with advice an agent can act on."""
    chosen = VIEWS.get(str(view or "trades").strip().casefold())
    if chosen is None:
        raise ValueError(
            "view must be 'trades' (the day's offers and contracts, default) or 'summary' (rings, markets, daily series, dollar rate)."
        )
    start = parse_date(date) if date not in (None, "") else None
    end = parse_date(to_date_) if to_date_ not in (None, "") else None
    if end is not None and start is None:
        raise ValueError("to_date needs date: give the first day of the range as date.")
    if start is not None and end is not None:
        if end < start:
            raise ValueError("to_date is before date.")
        days = (to_date(end) - to_date(start)).days + 1
        cap = MAX_TRADE_DAYS if chosen == "trades" else MAX_SUMMARY_DAYS
        if days > cap:
            hint = " Use view='summary' for longer ranges." if chosen == "trades" else ""
            raise ValueError(
                f"{chosen} covers at most {cap} days at a time (asked for {days}).{hint}"
            )
    sort = str(sort_by or "value").strip().casefold()
    if sort not in SORT_KEYS:
        raise ValueError(f"sort_by must be one of {', '.join(SORT_KEYS)}.")
    size = DEFAULT_LIMIT if limit is None else int(limit)
    if not 1 <= size <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}.")
    wanted = clean(product) if product and clean(product) else None
    return CommodityRequest(
        chosen, start, end, parse_group(group), wanted, bool(traded_only), sort, size
    )


def recent_window(today: dt.date) -> tuple[str, str]:
    """Jalali bounds of the last two weeks, for finding the latest session."""
    first = today - dt.timedelta(days=RECENT_DAYS - 1)
    return jdate(from_date(first)) or "", jdate(from_date(today)) or ""


def chart_window(day: int) -> tuple[str, str]:
    first = to_date(day) - dt.timedelta(days=CHART_DAYS - 1)
    return jdate(from_date(first)) or "", jdate(day) or ""


def _iso(jalali: object) -> str | None:
    """Jalali (or Gregorian) text from the exchange -> ISO date; ``None`` when it does not parse."""
    if not jalali:
        return None
    try:
        return fmt_date(parse_date(str(jalali)))
    except (DateError, ValueError):
        return None


def _day(jalali: object) -> int | None:
    try:
        return parse_date(str(jalali)) if jalali else None
    except (DateError, ValueError):
        return None


def latest_session(daily: Iterable[dict], *, upto: int | None = None) -> int | None:
    """The newest session (Gregorian ``YYYYMMDD``) with traded value in the roll-up rows, not after ``upto``."""
    days = [
        d
        for row in daily
        if (_f(row.get("TradeValue")) or 0) > 0
        and (d := _day(row.get("TradeDate"))) is not None
        and (upto is None or d <= upto)
    ]
    return max(days) if days else None


def daily_upto(daily: Iterable[dict], end: int) -> list[dict]:
    """The roll-up rows of sessions not after ``end`` (the recent-window lookup runs up to today)."""
    return [row for row in daily if (d := _day(row.get("TradeDate"))) is not None and d <= end]


def _thousand_rial(value: object) -> int | None:
    number = _f(value)
    return None if number is None else int(round(number * 1000))


def _million_rial(value: object) -> int | None:
    number = _f(value)
    return None if number is None else int(round(number * 1_000_000))


# --------------------------------------------------------------------------- trades


def shape_trade_row(raw: dict) -> dict:
    """One offer or contract. Volumes are tons, prices rial per kilogram, ``value_rial`` rial (the exchange's thousand rial x 1,000)."""
    contract = clean(raw.get("ContractType"))
    traded = _f(raw.get("Quantity")) or 0.0
    return {
        "symbol": clean(raw.get("Symbol")),
        "product": clean(raw.get("GoodsName")),
        "producer": clean(raw.get("ProducerName")),
        "supplier": clean(raw.get("ArzehKonandeh")),
        "hall": clean(raw.get("Talar")),
        "contract": contract,
        "matching": bool(contract and "مچینگ" in contract),
        "settlement": clean(raw.get("Tasvieh")),
        "packaging": clean(raw.get("PacketName")),
        "broker": clean(raw.get("cBrokerSpcName")),
        "date": _iso(raw.get("date")),
        "date_jalali": raw.get("date"),
        "delivery_date": _iso(raw.get("DeliveryDate")),
        "delivery_date_jalali": raw.get("DeliveryDate"),
        "delivery_place": clean(raw.get("Warehouse")),
        "unit": clean(raw.get("Unit")),
        "volume_tons": traded,
        "price_rial_per_kg": _f(raw.get("Price")),
        "price_low_rial_per_kg": _f(raw.get("MinPrice")),
        "price_high_rial_per_kg": _f(raw.get("MaxPrice")),
        "base_price_rial_per_kg": _f(raw.get("ArzeBasePrice")),
        "offered_tons": _f(raw.get("arze")),
        "demand_tons": _f(raw.get("taghaza")),
        "value_rial": _thousand_rial(raw.get("TotalPrice")),
        "offer_id": str(raw["arzehPk"]) if raw.get("arzehPk") is not None else None,
        "category_code": clean(raw.get("Category")),
    }


def _matches(row: dict, needle: str | None) -> bool:
    if not needle:
        return True
    key = match_key(needle)
    return any(
        key in match_key(row.get(field)) for field in ("product", "symbol", "producer", "supplier")
    )


def _sorter(sort_by: str):
    column = SORT_KEYS[sort_by]
    if sort_by == "name":
        return (lambda r: match_key(r.get(column))), False
    return (lambda r: r.get(column) if r.get(column) is not None else float("-inf")), True


def _rollup(rows: Sequence[dict], key: str) -> list[dict]:
    groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"rows": 0, "traded_rows": 0, "volume_tons": 0.0, "value_rial": 0}
    )
    for row in rows:
        entry = groups[row.get(key) or "?"]
        entry["rows"] += 1
        entry["traded_rows"] += 1 if row["volume_tons"] > 0 else 0
        entry["volume_tons"] += row["volume_tons"]
        entry["value_rial"] += row["value_rial"] or 0
    out = [
        {key: name, **{**e, "volume_tons": round(e["volume_tons"], 3)}}
        for name, e in groups.items()
    ]
    return sorted(out, key=lambda e: -e["value_rial"])


def _top_products(rows: Sequence[dict], limit: int = 10) -> list[dict]:
    out = _rollup([r for r in rows if r["volume_tons"] > 0], "product")[:limit]
    for entry in out:  # derived: value / kilograms
        tons = entry["volume_tons"]
        entry["avg_price_rial_per_kg"] = (
            round(entry["value_rial"] / (tons * 1000), 1) if tons else None
        )
    return out


def shape_trades(
    raw_rows: Sequence[dict], request: CommodityRequest, start: int, end: int, *, resolved: bool
) -> dict:
    """The day's (or range's) rows, filtered and ranked, with totals over every row that passed the filters."""
    shaped = [shape_trade_row(r) for r in raw_rows]
    odd_units = sorted({r["unit"] for r in shaped if r["unit"] not in (None, "تن")})
    matched = [
        r
        for r in shaped
        if _matches(r, request.product) and (not request.traded_only or r["volume_tons"] > 0)
    ]
    key, descending = _sorter(request.sort_by)
    ranked = sorted(matched, key=key, reverse=descending)
    traded = [r for r in matched if r["volume_tons"] > 0]
    notes = [
        "volume_tons is tons; price_rial_per_kg is the weighted-average closing price in rial per kilogram; value_rial = the exchange's value (thousand rial) x 1,000, which equals price x tons x 1,000.",
        "offered_tons is 0 for matching contracts (مچینگ), which have no fixed offer; rows with volume_tons 0 are offers that did not trade (price fields are null).",
        "Totals cover the main halls only; IME's own roll-up (view='summary') also counts the sub-market and is larger. Do not add the two.",
    ]
    if odd_units:
        notes.append(
            f"Some rows use another volume unit ({', '.join(odd_units)}); their volume_tons figure is in that unit, not tons."
        )
    if not shaped:
        notes.append(
            "IME published no physical-market rows for these dates: it trades Saturday to Wednesday, so Thursday, Friday and holidays are empty."
        )
    elif not matched:
        notes.append("Rows exist for these dates but none passed the product / traded_only filter.")
    one_day = start == end
    return {
        "market": MARKET_NAME,
        "view": "trades",
        **(
            {"date": fmt_date(start), "date_jalali": jdate(start)}
            if one_day
            else {
                "date_from": fmt_date(start),
                "date_to": fmt_date(end),
                "date_from_jalali": jdate(start),
                "date_to_jalali": jdate(end),
            }
        ),
        "latest_session": resolved,
        "units": {"volume": "tons (تن)", "price": "rial per kilogram", "value": "rial"},
        "filters": {
            "group": MAIN_GROUPS.get(request.main_cat),
            "product": request.product,
            "traded_only": request.traded_only,
        },
        "totals": {
            "rows": len(matched),
            "traded_rows": len(traded),
            "volume_tons": round(sum(r["volume_tons"] for r in traded), 3),
            "value_rial": sum(r["value_rial"] or 0 for r in traded),
            "offered_tons": round(sum(r["offered_tons"] or 0 for r in matched), 3),
            "demand_tons": round(sum(r["demand_tons"] or 0 for r in matched), 3),
        },
        "by_hall": _rollup(matched, "hall"),
        "by_contract": _rollup(matched, "contract"),
        "top_products": _top_products(matched),
        "sorted_by": f"{request.sort_by} {'desc' if descending else 'asc'}",
        "returned": min(request.limit, len(ranked)),
        "rows": ranked[: request.limit],
        "notes": notes,
    }


# --------------------------------------------------------------------------- summary


def shape_ring(raw: dict) -> dict:
    traded, offered = _f(raw.get("Volume")), _f(raw.get("OfferVolume"))
    return {
        "ring_id": _i(raw.get("ID")),
        "ring": clean(raw.get("xRingName")),
        "value_rial": _million_rial(raw.get("Value")),
        "traded_tons": traded,
        "offered_tons": offered,
        "traded_to_offered_pct": round(traded / offered * 100, 1)
        if traded is not None and offered
        else None,
    }


def shape_market(raw: dict) -> dict:
    return {
        "market_id": _i(raw.get("Id")),
        "market": clean(raw.get("name")),
        "value_rial": _million_rial(raw.get("TradeValue")),
        "volume": _f(raw.get("TradeVolume")),
    }


def shape_summary(
    rings: Sequence[dict],
    markets: Sequence[dict],
    daily: Sequence[dict],
    usd: Sequence[dict],
    start: int,
    end: int,
    *,
    resolved: bool,
) -> dict:
    """IME's own roll-ups for the dates: physical rings, all markets, one row per session (the window the caller asked for), and its dollar rate."""
    ring_rows = [shape_ring(r) for r in rings]
    series = [
        {
            "date": _iso(r.get("TradeDate")),
            "date_jalali": r.get("TradeDate"),
            "value_rial": _million_rial(r.get("TradeValue")),
            "volume_tons": _f(r.get("TradeVolume")),
        }
        for r in daily
        if _day(r.get("TradeDate")) is not None
    ]
    series.sort(key=lambda r: r["date"] or "")
    rate = max(
        (u for u in usd if _f(u.get("Nerkh"))),
        key=lambda u: _day(u.get("Tarikh")) or 0,
        default=None,
    )
    notes = [
        "Values are rial (the exchange publishes million rial). Ring volumes are tons; the other markets' volumes are in their own units (contracts, certificates, rial) as published.",
        "These roll-ups include the sub-market and are larger than the sum of view='trades' rows.",
    ]
    if not ring_rows:
        notes.append(
            "No physical-market roll-up for these dates: IME trades Saturday to Wednesday."
        )
    one_day = start == end
    return {
        "market": MARKET_NAME,
        "view": "summary",
        **(
            {"date": fmt_date(start), "date_jalali": jdate(start)}
            if one_day
            else {
                "date_from": fmt_date(start),
                "date_to": fmt_date(end),
                "date_from_jalali": jdate(start),
                "date_to_jalali": jdate(end),
            }
        ),
        "latest_session": resolved,
        "units": {
            "value": "rial",
            "ring_and_daily_volume": "tons (تن)",
            "market_volume": "the market's own unit, as published",
        },
        "physical_rings": ring_rows,
        "physical_total": {
            "value_rial": sum(r["value_rial"] or 0 for r in ring_rows),
            "traded_tons": round(sum(r["traded_tons"] or 0 for r in ring_rows), 3),
            "offered_tons": round(sum(r["offered_tons"] or 0 for r in ring_rows), 3),
        },
        "markets": [shape_market(m) for m in markets],
        "daily": series,
        "usd_rate": None
        if rate is None
        else {
            "date": _iso(rate.get("Tarikh")),
            "date_jalali": rate.get("Tarikh"),
            "rial_per_usd": _f(rate.get("Nerkh")),
            "note": "the dollar rate IME shows on its home page",
        },
        "notes": notes,
    }
