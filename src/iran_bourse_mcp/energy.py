"""Iran Energy Exchange (IRENEX, بورس انرژی ایران): physical auctions and the electricity market, shaped for agents.

Pure shaping code over the public JSON API behind iee.ir (``webapi.iee.ir/api``, see ``api.TseApi.iee_*``); nothing here
touches the network. The exchange trades by *auction* (عرضه): a seller offers a volume at a base price, buyers enter orders,
and the auction ends with trades, a halt on surplus supply, or nothing. Every auction has an id (``auctionIdn``) that is
also the id of TSETMC's ``Energy/GetAuctionById``.

Units are the whole difficulty, so they are decided once, here, and checked against the exchange's own totals
(``totalValueRials`` of 2026-11-04 and the 2026-11-01 to 2026-11-04 week, 117 physical and 7 electricity rows):

* Physical, volume in tons (تن), price in rial (``priceUnitTitle`` "ریال"): the price is **rial per kilogram**.
  value = tons x 1,000 x price (60 t at 180,000 gave 10,800,000,000). The exchange's detail record says so itself
  (``volumeUnitTitlePrice`` "کیلوگرم", ``convertPriceVolume`` 1000, ``priceOnVolumeUnit`` "ریال/کیلوگرم").
* Physical, price in dollars ("دلار(مرکز مبادله...)"): **US dollars per tonne** (per cubic metre when the volume is in مترمکعب);
  value = volume x price x the exchange's dollar rate (1,874,444 rial on 2026-11-04, the rate IME published for the day before).
* Physical in liters (لیتر), price in rial: **rial per liter**; value = liters x price.
* Premium auctions ("پریمیوم دلاری"/"پریمیوم ریالی", کشف پریمیوم): the price is a premium (negative = discount) on the exchange's
  reference price, not a price; ``value_rial`` is still the exchange's figure.
* Electricity: a contract is sold in kW "of the consumption period in the delivery period" (کیلووات در هر ساعت از دوره مصرف در
  دوره تحویل): a sustained capacity, not energy. ``kwh`` is the energy it amounts to (9,000 kW for a 168-hour week = 1,512,000 kWh)
  and the price is **rial per kWh**: value = kWh x price (1,512,000 x 4,500 = 6,804,000,000).

``value_rial`` is always the exchange's ``totalValueRials`` / ``tradedValue`` unchanged. Dates are Jalali on the wire
(``1405/08/13``) and the service rejects Gregorian ones.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from .dates import DateError, fmt_date, from_date, jdate, parse_date, to_date
from .shape import _i
from .text import ascii_digits, clean, match_key

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MAX_TRADE_DAYS = 10
RECENT_DAYS = 7  # how far back the search for the latest session reaches
PAGE_SIZE = 1000
POWER_UNIT = "کیلووات در هر ساعت از دوره مصرف در دوره تحویل"
UNIT_EN = {
    "تن": "tonne",
    "مترمکعب": "cubic meter",
    "لیتر": "liter",
    "کیلوگرم": "kilogram",
    POWER_UNIT: "kW of capacity over the delivery period",
}
VIEWS = {
    "trades": "trades",
    "results": "trades",
    "offers": "offers",
    "announcements": "offers",
    "auction": "auction",
    "detail": "auction",
    "overview": "overview",
    "status": "overview",
}
MARKET_WORDS = {
    "physical": "physical",
    "oil": "physical",
    "gas": "physical",
    "فیزیکی": "physical",
    "power": "power",
    "electricity": "power",
    "برق": "power",
    "all": "all",
    "both": "all",
    "": "all",
}
SORT_KEYS = {
    "value": "value_rial",
    "volume": "traded_volume",
    "name": "product",
    "time": "auction_time",
}


@dataclass(frozen=True)
class EnergyRequest:
    """A validated ``energy_market`` call. ``start`` / ``end`` are Gregorian ``YYYYMMDD`` or ``None`` for the latest session."""

    view: str
    markets: tuple[str, ...]
    start: int | None
    end: int | None
    product: str | None
    auction_id: int | None
    traded_only: bool
    sort_by: str
    limit: int


def plan(
    view: str | None,
    market: str | None,
    date: str | int | None,
    to_date_: str | int | None,
    product: str | None,
    auction_id: int | None,
    traded_only: bool,
    sort_by: str | None,
    limit: int | None,
) -> EnergyRequest:
    """Check the arguments; raises ``ValueError`` (``DateError`` for bad dates) with advice an agent can act on."""
    chosen = VIEWS.get(str(view or "trades").strip().casefold())
    if chosen is None:
        raise ValueError(
            "view must be 'trades' (auction results, default), 'offers' (announced auctions), 'auction' (one auction by id) or 'overview' (open or closed, today's totals)."
        )
    kind = MARKET_WORDS.get(match_key(market) if market else "")
    if kind is None:
        raise ValueError(
            "market must be 'physical' (oil products, gas, petrochemicals, industrial gases), 'power' (electricity) or omitted for both."
        )
    markets = ("physical", "power") if kind == "all" else (kind,)
    start = parse_date(date) if date not in (None, "") else None
    end = parse_date(to_date_) if to_date_ not in (None, "") else None
    if end is not None and start is None:
        raise ValueError("to_date needs date: give the first day of the range as date.")
    if start is not None and end is not None:
        if end < start:
            raise ValueError("to_date is before date.")
        days = (to_date(end) - to_date(start)).days + 1
        if days > MAX_TRADE_DAYS:
            raise ValueError(
                f"trades covers at most {MAX_TRADE_DAYS} days at a time (asked for {days})."
            )
    if chosen == "auction" and (auction_id is None or int(auction_id) <= 0):
        raise ValueError(
            "view='auction' needs auction_id, the number in the auction_id field of a trades or offers row."
        )
    sort = str(sort_by or "value").strip().casefold()
    if sort not in SORT_KEYS:
        raise ValueError(f"sort_by must be one of {', '.join(SORT_KEYS)}.")
    size = DEFAULT_LIMIT if limit is None else int(limit)
    if not 1 <= size <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}.")
    wanted = clean(product) if product and clean(product) else None
    return EnergyRequest(
        chosen,
        markets,
        start,
        end,
        wanted,
        int(auction_id) if auction_id else None,
        bool(traded_only),
        sort,
        size,
    )


def recent_window(today: dt.date) -> tuple[str, str]:
    """Jalali bounds of the last week, for finding the latest session."""
    first = today - dt.timedelta(days=RECENT_DAYS - 1)
    return jdate(from_date(first)) or "", jdate(from_date(today)) or ""


def number(value: object) -> float | None:
    """``'3,818,790,300,000'`` -> float; numbers pass through; anything else -> ``None``."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    text = ascii_digits(str(value)).replace(",", "").replace("٬", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


_AMOUNT = re.compile(r"^\s*(-?[\d,]+(?:\.\d+)?)\s*(.*?)\s*$")


def amount_with_unit(text: object) -> tuple[float | None, str | None]:
    """``'1,000 تن'`` -> (1000.0, 'تن'); ``'750 کیلووات ...'`` likewise; unreadable -> (None, text)."""
    match = _AMOUNT.match(ascii_digits(str(text))) if text else None
    if not match:
        return None, clean(text) if text else None
    return number(match.group(1)), clean(match.group(2)) or None


def _iso(jalali: object) -> str | None:
    try:
        return fmt_date(parse_date(str(jalali))) if jalali else None
    except (DateError, ValueError):
        return None


def _day(jalali: object) -> int | None:
    try:
        return parse_date(str(jalali).split(" ")[0]) if jalali else None
    except (DateError, ValueError):
        return None


def _hhmm(text: object) -> str | None:
    """``'1405/08/13 - 15:0'`` or ``'14:00:00'`` -> ``'15:00'``."""
    match = re.search(r"(\d{1,2}):(\d{1,2})", ascii_digits(str(text))) if text else None
    return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}" if match else None


def price_basis(volume_unit: str | None, price_unit: str | None) -> tuple[str | None, str | None]:
    """(currency, human reading of the price) for a volume unit and the exchange's price unit; ``None`` where it was not verified."""
    text = clean(price_unit) or ""
    if text.startswith("پریمیوم دلاری"):
        return (
            "USD premium",
            "US dollars per tonne as a premium (negative = discount) on the exchange's reference price"
            if volume_unit == "تن"
            else "US dollars as a premium (negative = discount) on the exchange's reference price",
        )
    if text.startswith("پریمیوم ریالی"):
        return "IRR premium", "rial as a premium on the exchange's reference price"
    if text.startswith("دلار"):
        per = {"تن": "tonne", "مترمکعب": "cubic meter"}.get(volume_unit or "")
        return "USD", f"US dollars per {per}" if per else None
    if text.startswith("ریال"):
        per = {"تن": "kilogram", "لیتر": "liter", POWER_UNIT: "kWh"}.get(volume_unit or "")
        return "IRR", f"rial per {per}" if per else None
    return None, None


# --------------------------------------------------------------------------- trades


def shape_trade_row(raw: dict, market: str) -> dict:
    """One auction's result. Volumes are in ``volume_unit``; ``value_rial`` is the exchange's figure in rial."""
    unit = clean(raw.get("volumeUnitTitle"))
    price_unit = clean(raw.get("priceUnitTitle"))
    currency, basis = price_basis(unit, price_unit)
    kwh = number(raw.get("kiloWattHours"))
    return {
        "auction_id": _i(raw.get("auctionIdn")),
        "symbol": clean(raw.get("energySymbol")),
        "market": market,
        "board": clean(raw.get("boardName")),
        "product": clean(raw.get("instrumentDisplayName")),
        "description": clean(raw.get("auctionDesc")),
        "ring": clean(raw.get("targetMarketName")),
        "destination": clean(raw.get("destination")),
        "supplier": clean(raw.get("supplierName")),
        "producer": clean(raw.get("producerName")),
        "broker": clean(raw.get("brokerName")),
        "trade_date": _iso(raw.get("tradeDateShamsi")),
        "trade_date_jalali": raw.get("tradeDateShamsi"),
        "auction_time": _hhmm(raw.get("auctionDateShamsi")),
        "trade_type": clean(raw.get("tradeTypeTitle")),
        "contract": clean(raw.get("contractType")),
        "clearing": clean(raw.get("clearingType")),
        "volume_unit": unit,
        "volume_unit_en": UNIT_EN.get(unit or ""),
        "traded_volume": number(raw.get("totalTradedVolume")) or 0.0,
        "offered_volume": number(raw.get("auctionVolume")),
        "demand_volume": number(raw.get("orderBuyTradedVolume")),
        "trades": _i(number(raw.get("tradeNo"))) or 0,
        "price_currency": currency,
        "price_basis": basis,
        "price_unit": price_unit,
        "base_price": number(raw.get("basePrice")),
        "avg_price": number(raw.get("tradedAveragePrice")),
        "low_price": number(raw.get("tradeMinPrice")),
        "high_price": number(raw.get("tradeMaxPrice")),
        "value_rial": _i(number(raw.get("totalValueRials"))) or 0,
        "kwh": kwh if kwh else None,
    }


def latest_day(rows: Iterable[dict]) -> int | None:
    """The newest trade date (Gregorian ``YYYYMMDD``) among raw result rows: the newest day with a trade, else the newest day with any row
    (a session that has only announced its auctions so far must not hide the last finished one)."""
    items = [
        (d, (number(r.get("totalTradedVolume")) or 0) > 0)
        for r in rows
        if (d := _day(r.get("tradeDateShamsi"))) is not None
    ]
    traded = [d for d, did_trade in items if did_trade]
    return max(traded) if traded else max((d for d, _ in items), default=None)


def _matches(row: dict, needle: str | None) -> bool:
    if not needle:
        return True
    key = match_key(needle)
    return any(
        key in match_key(row.get(field))
        for field in ("product", "description", "symbol", "supplier", "producer")
    )


def shape_trades(
    raw_by_market: dict[str, Sequence[dict]],
    request: EnergyRequest,
    start: int,
    end: int,
    *,
    resolved: bool,
    truncated: Sequence[str] = (),
) -> dict:
    """Auction results of the requested markets for the dates, filtered and ranked, with totals over every row that passed the filters."""
    shaped = [
        shape_trade_row(r, market)
        for market, rows in raw_by_market.items()
        for r in rows
        if start <= (_day(r.get("tradeDateShamsi")) or 0) <= end
    ]
    matched = [
        r
        for r in shaped
        if _matches(r, request.product) and (not request.traded_only or r["traded_volume"] > 0)
    ]
    column = SORT_KEYS[request.sort_by]
    if request.sort_by == "name":
        ranked = sorted(matched, key=lambda r: match_key(r.get(column)))
    elif request.sort_by == "time":
        ranked = sorted(
            matched, key=lambda r: (r["trade_date"] or "", r["auction_time"] or ""), reverse=True
        )
    else:
        ranked = sorted(matched, key=lambda r: r.get(column) or 0, reverse=True)
    traded = [r for r in matched if r["traded_volume"] > 0]
    by_unit: dict[str, float] = defaultdict(float)
    by_market: dict[str, dict[str, int]] = defaultdict(
        lambda: {"auctions": 0, "traded_auctions": 0, "value_rial": 0}
    )
    by_product: dict[str, dict[str, Any]] = {}
    for r in matched:
        entry = by_market[r["market"]]
        entry["auctions"] += 1
        entry["traded_auctions"] += 1 if r["traded_volume"] > 0 else 0
        entry["value_rial"] += r["value_rial"]
        if r["traded_volume"] > 0:
            by_unit[r["volume_unit"] or "?"] += r["traded_volume"]
            product = by_product.setdefault(
                f"{r['product']}|{r['volume_unit']}",
                {
                    "product": r["product"],
                    "volume_unit": r["volume_unit"],
                    "auctions": 0,
                    "traded_volume": 0.0,
                    "value_rial": 0,
                },
            )
            product["auctions"] += 1
            product["traded_volume"] += r["traded_volume"]
            product["value_rial"] += r["value_rial"]
    notes = [
        "value_rial is the exchange's own figure in rial. Volumes are in each row's volume_unit (tonne for most physical products, kW of capacity for electricity) and are never added across units: see totals.volume_by_unit.",
        "price_basis says what avg_price / base_price are: rial per kilogram for tonne-and-rial auctions, US dollars per tonne for dollar auctions, a premium on a reference price for premium auctions, rial per kWh for electricity. kwh is the energy of an electricity contract.",
        "Rows with traded_volume 0 are auctions that ended without a trade (use traded_only=false to see them).",
    ]
    if not shaped:
        notes.append(
            "The exchange published no auction results for these dates: it trades Saturday to Wednesday, so Thursday, Friday and holidays are empty."
        )
    elif not matched:
        notes.append(
            "Results exist for these dates but none passed the product / traded_only filter."
        )
    quiet = [m for m in request.markets if shaped and not any(r["market"] == m for r in shaped)]
    if quiet:
        notes.append(
            f"No {' or '.join(quiet)} auctions on these dates (the electricity and physical markets do not hold auctions every day); widen the dates with to_date or pick market explicitly."
        )
    if truncated:
        notes.append(
            f"The exchange had more than {PAGE_SIZE} rows for {', '.join(truncated)}; only the first page was read."
        )
    one_day = start == end
    return {
        "exchange": "بورس انرژی ایران (Iran Energy Exchange)",
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
        "markets": list(request.markets),
        "filters": {"product": request.product, "traded_only": request.traded_only},
        "totals": {
            "auctions": len(matched),
            "traded_auctions": len(traded),
            "value_rial": sum(r["value_rial"] for r in matched),
            "volume_by_unit": {unit: round(volume, 3) for unit, volume in by_unit.items()},
        },
        "by_market": dict(by_market),
        "top_products": sorted((p for p in by_product.values()), key=lambda p: -p["value_rial"])[
            :10
        ],
        "sorted_by": request.sort_by,
        "returned": min(request.limit, len(ranked)),
        "rows": ranked[: request.limit],
        "notes": notes,
    }


# --------------------------------------------------------------------------- offers


def shape_offer_row(raw: dict, market: str) -> dict:
    """An announced auction. Physical offers carry the volume as text with its unit («1,000 تن»); electricity offers carry both."""
    volume = number(raw.get("auctionVolumeTooltip"))
    amount, text_unit = amount_with_unit(raw.get("auctionVolume"))
    unit = clean(raw.get("volumeUnitTitle")) or text_unit
    base_text = clean(raw.get("basePrice"))
    return {
        "auction_id": _i(raw.get("auctionIdn")),
        "symbol": clean(raw.get("energySymbol")),
        "market": market,
        "product": clean(raw.get("instrumentDisplayName")),
        "description": clean(raw.get("auctionDesc")),
        "ring": clean(raw.get("targetMarketName")),
        "supplier": clean(raw.get("supplier")),
        "producer": clean(raw.get("producerName")),
        "broker": clean(raw.get("brokerName")),
        "date": _iso(raw.get("auctionDateShamsi")),
        "date_jalali": (
            str(raw.get("auctionDateShamsi")).split(" ")[0]
            if raw.get("auctionDateShamsi")
            else None
        ),
        "time": _hhmm(raw.get("auctionTime")),
        "trade_type": clean(raw.get("tradeType")),
        "status": clean(raw.get("stepTitle")) or clean(raw.get("auctionState")) or None,
        "offered_volume": volume if volume is not None else amount,
        "volume_unit": unit,
        "volume_unit_en": UNIT_EN.get(unit or ""),
        "base_price": number(raw.get("basePriceTooltip")),
        "base_price_text": base_text,
        "reference_price": number(raw.get("referencePrice")),
        "minimum_purchase": clean(raw.get("minimumPurchase")),
        "maximum_purchase": clean(raw.get("maximumPurchase")),
        "delivery_terms": clean(raw.get("termsOfDelivery")),
        "delivery_place": clean(raw.get("deliveryLocationName")),
    }


def is_held(raw: dict) -> bool:
    """The electricity announcements are an archive of every auction since the start; held ones carry «برگزار شده» in ``auctionState``."""
    return bool(clean(raw.get("auctionState")))


def shape_offers(
    raw_by_market: dict[str, Sequence[dict]], request: EnergyRequest, *, more: Sequence[str] = ()
) -> dict:
    """Announced auctions of the requested markets that have not been held yet, soonest first. ``more`` names the markets whose page was
    all upcoming auctions, so the exchange may have announced more than were read."""
    upcoming = {
        market: [r for r in items if not is_held(r)] for market, items in raw_by_market.items()
    }
    announced = [shape_offer_row(r, market) for market, items in upcoming.items() for r in items]
    rows = [r for r in announced if _matches(r, request.product)]
    rows.sort(key=lambda r: (r["date"] or "9999", r["time"] or "", r["auction_id"] or 0))
    notes = [
        "Soonest first; auctions already held are left out. offered_volume is in volume_unit (tonne, or kW of capacity for electricity). base_price is numeric only where the exchange gives it separately; base_price_text is its own wording, which also carries the unit and whether it is a premium.",
        "Ask view='auction' with an auction_id for one auction's terms and, once the session ran, its buy and sell orders and trades.",
    ]
    if not announced:
        notes.append(
            "The exchange has no announced auctions for these markets right now (offers are published for the next sessions only)."
        )
    elif not rows:
        notes.append("Auctions are announced but none matches the product filter.")
    if more:
        notes.append(
            f"Only the newest announcements of {', '.join(more)} were read; the exchange may have announced more."
        )
    return {
        "exchange": "بورس انرژی ایران (Iran Energy Exchange)",
        "view": "offers",
        "markets": list(request.markets),
        "filters": {"product": request.product},
        "announced": {market: len(items) for market, items in upcoming.items()},
        "returned": min(request.limit, len(rows)),
        "rows": rows[: request.limit],
        "notes": notes,
    }


# --------------------------------------------------------------------------- one auction


def _levels(orders: Iterable[dict] | None) -> list[dict]:
    return [
        {
            "price": number(o.get("price")),
            "volume": number(o.get("totalQuantity")),
            "orders": _i(number(o.get("orderCount"))),
        }
        for o in (orders or [])
    ]


def shape_auction(detail: dict, trades: Sequence[dict]) -> dict:
    """Terms, order levels and trades of one auction (``results[0]`` of the detail record plus its trade list)."""
    unit = clean(detail.get("volumeUnitTitle"))
    price_unit = clean(detail.get("priceUnitTitle"))
    offered, _ = amount_with_unit(detail.get("auctionVolume"))
    lot = number(detail.get("lotSize"))
    min_buy, _ = amount_with_unit(detail.get("minimumPurchase"))
    min_discovery, _ = amount_with_unit(detail.get("minimumPurchaseForPriceDiscovery"))
    max_buy, _ = amount_with_unit(detail.get("maxBuyVolume"))
    base, _ = amount_with_unit(detail.get("basePrice"))
    currency, basis = price_basis(unit, price_unit)
    per = clean(detail.get("volumeUnitTitlePrice"))
    rows = [
        {
            "date": _iso(t.get("tradeDateShamsi")),
            "volume": number(t.get("tradedQuantity")),
            "price": number(t.get("tradedPrice")),
            "value_rial": _i(number(t.get("tradedValue"))),
            "price_per": clean(t.get("priceOnVolumeUnit")),
        }
        for t in trades
    ]
    buy, sell = _levels(detail.get("buyOrders")), _levels(detail.get("saleOrders"))
    conversion = number(detail.get("convertPriceVolume"))
    return {
        "exchange": "بورس انرژی ایران (Iran Energy Exchange)",
        "view": "auction",
        "symbol": clean(detail.get("energySymbol")),
        "product": clean(detail.get("instrumentDisplayName")),
        "description": clean(detail.get("auctionDesc")),
        "producer": clean(detail.get("producerName")),
        "status": clean(detail.get("stepTitle")),
        "date_jalali": detail.get("auctionDate"),
        "date": _iso(detail.get("auctionDate")),
        "time": _hhmm(detail.get("auctionTime")),
        "trade_type": clean(detail.get("tradeTypeTitle")),
        "units": {
            "volume": unit,
            "volume_en": UNIT_EN.get(unit or ""),
            "price": price_unit,
            "price_basis": basis,
            "price_per": per,
            "volume_to_price_unit": conversion,
            "note": f"1 {unit} = {int(conversion)} {per}"
            if conversion and conversion != 1 and unit and per
            else None,
        },
        "price_currency": currency,
        "offered_volume": offered,
        "maximum_purchase": max_buy,
        "minimum_purchase": min_buy,
        "minimum_for_price_discovery": min_discovery,
        "lot_size": lot,
        "base_price": base,
        "reference_price": number(detail.get("referencePrice")),
        "delivery": {
            "place": clean(detail.get("deliveryLocationName")),
            "period": clean(detail.get("deliveryPeriod")) or None,
        },
        "clearing": clean(detail.get("clearingType")),
        "destination": clean(detail.get("destination")),
        "payment_terms": clean(detail.get("termsOfPayment")),
        "buy_orders": buy,
        "sell_orders": sell,
        "demand_volume": round(sum(level["volume"] or 0 for level in buy), 3),
        "supply_volume": round(sum(level["volume"] or 0 for level in sell), 3),
        "trades": rows,
        "totals": {
            "trades": len(rows),
            "volume": round(sum(t["volume"] or 0 for t in rows), 3),
            "value_rial": sum(t["value_rial"] or 0 for t in rows),
        },
        "notes": [
            "buy_orders / sell_orders are aggregated price levels (orders = how many orders sit at that price); volumes are in units.volume.",
            "Prices are in units.price per units.price_per (rial per kilogram for tonne auctions). value_rial is the exchange's figure.",
        ],
    }


# --------------------------------------------------------------------------- overview


def shape_overview(today: Sequence[dict], physical: Sequence[dict], power: Sequence[dict]) -> dict:
    """Is the exchange trading, and how much has traded so far today (traded value is million rial on the wire)."""
    markets = [
        {
            "market_id": _i(m.get("marketSummaryType")),
            "market": clean(m.get("marketName")),
            "traded_value_rial": None
            if number(m.get("tradedValue")) is None
            else int(round((number(m.get("tradedValue")) or 0) * 1_000_000)),
            "trades": _i(number(m.get("tradedNo"))),
        }
        for m in today
    ]
    glance = (physical[0] if physical else {}) or {}
    rings = {
        name: glance.get(key) or {}
        for name, key in (
            ("all_rings", "allRings"),
            ("internal_ring", "internalRing"),
            ("international_ring", "internationalRing"),
        )
    }
    power_row = (power[0] if power else {}) or {}
    return {
        "exchange": "بورس انرژی ایران (Iran Energy Exchange)",
        "view": "overview",
        "physical_market": {
            "state": {name: clean(ring.get("marketState")) for name, ring in rings.items()},
            "trades_today": _i(number(rings["all_rings"].get("totalTradesCount"))),
        },
        "power_market": {
            "state": clean(power_row.get("marketState")),
            "trades_today": _i(number(power_row.get("totalTradesCount"))),
        },
        "traded_today": markets,
        "notes": [
            "state is the exchange's wording («بسته» = closed). traded_value_rial is today's total so far; the exchange publishes million rial and it is converted here.",
            "The exchange trades Saturday to Wednesday; on other days every figure is zero. Use view='trades' for a finished session.",
        ],
    }
