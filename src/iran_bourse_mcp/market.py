"""The whole-market row: shaping the exchange's own filter feed (``ClosingPrice/GetMarketWatch``).

tsetmc.com's market watch and its filter box run on this one feed: every instrument (about 3,700: shares,
base market, funds, bonds, rights, options, futures, commodities) with a five-level order book, base volume,
share count, fund NAV and open interest. The TSE gateway watch the server used before lists only 582 shares.
Gateway rows, when available, are joined by instrument id only for what this feed lacks: sub-industry,
trading status and the index effect.
"""

from __future__ import annotations

from typing import Any

from .shape import _f, _i, _r, _safe_div, shape_watch_row
from .text import clean

TAL_BOARDS = frozenset({"F3", "G3", "U3"})  # closing-price-only (TAL) segments: their limits are meaningless
TYPE_GROUPS: tuple[tuple[str, frozenset[int]], ...] = (
    ("سهام", frozenset({300, 303, 313})),
    ("بازار پایه فرابورس", frozenset({309})),
    ("حق تقدم", frozenset({400, 403, 404})),
    ("اوراق بدهی", frozenset({306, 301, 706, 208, 206})),
    ("اختیار معامله", frozenset({600, 602, 605, 603, 311, 312, 320, 321})),
    ("آتی", frozenset({263, 304})),
    ("صندوق سرمایه گذاری", frozenset({305, 380})),
    ("بورس کالا", frozenset({308, 701})),
)
TYPE_TAL, TYPE_HOUSING, TYPE_ENERGY, TYPE_OTHER = "معاملات پایانی TAL", "تسهیلات مسکن", "انرژی", "سایر"
_BY_YVAL = {code: name for name, codes in TYPE_GROUPS for code in codes}
MARKET_BY_FLOW = {1: "بورس", 2: "فرابورس", 3: "بازار مشتقه", 4: "فرابورس - بازار پایه", 6: "بورس انرژی", 7: "بورس کالا"}
BOARD_TITLES = {
    "N1": "بازار اول (تابلوی اصلی) بورس", "N2": "بازار دوم (تابلوی اصلی) بورس", "Z1": "بازار دوم فرابورس", "1Z": "بازار اول فرابورس",
    "P1": "بازار پایه زرد فرابورس", "C1": "بازار پایه نارنجی فرابورس", "L1": "بازار پایه قرمز فرابورس", "V1": "بازار نوآفرین - رشد",
    "F1": "بازار عادی آتی", "N4": "بازار اوراق بدهی", "20": "بازار ابزارهای مشتقه", "13": "بازار ابزارهای مشتقه",
    "T1": "بازار ابزارهای نوین مالی فرابورس", "T2": "بازار ابزارهای نوین مالی فرابورس", "1A": "بازار ابزارهای نوین مالی فرابورس",
    "2A": "بازار ابزارهای نوین مالی فرابورس", "5A": "بازار صندوق های قابل معامله", "51": "بازار صندوق های قابل معامله",
    "H1": "بازار صندوق های قابل معامله", "QS": "صندوق های کالایی", "Q1": "بورس کالا",
}
_ID_PREFIX_TYPES = (  # instrument-id prefix -> type, for end-of-day tables that carry no type code
    ("IRO1", "سهام"), ("IRO3", "سهام"), ("IRO5", "سهام"), ("IRO7", "بازار پایه فرابورس"), ("IRO6", "تسهیلات مسکن"), ("IRO4", "آتی"),
    ("IRO9", "اختیار معامله"), ("IROF", "اختیار معامله"), ("IROA", "اختیار معامله"), ("IROB", "اختیار معامله"),
    ("IRT", "صندوق سرمایه گذاری"), ("IRB", "اوراق بدهی"), ("IRR", "حق تقدم"), ("IRK", "بورس کالا"), ("IRE", "انرژی"),
)
BOURSE_DERIVATIVE_CODES = frozenset({320, 321, 602, 603})  # options listed on the Tehran exchange (flow 3 is shared)

# English words an agent may use for ``security_type`` -> the Persian type name above
TYPE_WORDS = {
    "stock": "سهام", "stocks": "سهام", "share": "سهام", "shares": "سهام", "equity": "سهام", "equities": "سهام",
    "fund": "صندوق", "funds": "صندوق", "etf": "صندوق", "base": "پایه", "rights": "حق تقدم", "right": "حق تقدم",
    "bond": "اوراق بدهی", "bonds": "اوراق بدهی", "sukuk": "اوراق بدهی", "debt": "اوراق بدهی",
    "option": "اختیار", "options": "اختیار", "future": "آتی", "futures": "آتی", "commodity": "کالا",
    "housing": "مسکن", "tal": "TAL", "energy": "انرژی",
}


def classify_instrument(raw: dict) -> str:
    """The site's own paper-type rules, applied in its order (see tsetmc.com market watch settings)."""
    board = (raw.get("cGrValCot") or "").strip()
    if board in TAL_BOARDS:
        return TYPE_TAL
    if _i(raw.get("flow")) == 6:
        return TYPE_ENERGY
    symbol = clean(raw.get("lva")) or ""
    if symbol.startswith(("تسه", "تملی")):
        return TYPE_HOUSING
    return _BY_YVAL.get(_i(raw.get("yVal")) or -1, TYPE_OTHER)


def type_from_instrument_id(instrument_id: str | None) -> str:
    """Best-effort type of an instrument from its id (end-of-day tables have no type code; TAL rows cannot be told apart)."""
    for prefix, name in _ID_PREFIX_TYPES:
        if (instrument_id or "").startswith(prefix):
            return name
    return TYPE_OTHER


def market_of(raw: dict) -> str:
    return MARKET_BY_FLOW.get(_i(raw.get("flow")) or 0, "سایر")


def is_fara(raw: dict) -> bool:
    """tsetmc.com's own split: flow 2 and 4, plus derivatives that do not belong to the Tehran exchange."""
    flow, yval = _i(raw.get("flow")), _i(raw.get("yVal"))
    return flow in (2, 4) or (flow == 3 and yval not in BOURSE_DERIVATIVE_CODES)


def check_security_type(wanted: str | None) -> None:
    """Reject a ``security_type`` that matches no instrument class, so a typo is an error rather than an empty result."""
    if wanted is None or not str(wanted).strip():
        return
    key = str(wanted).strip().casefold()
    if key in ("all", "*", "همه") or key in TYPE_WORDS:
        return
    needle = clean(wanted) or ""
    known = (*(name for name, _ in TYPE_GROUPS), TYPE_TAL, TYPE_HOUSING, TYPE_ENERGY, TYPE_OTHER)
    if any(needle in name or name in needle for name in known):
        return
    raise ValueError(
        f"security_type '{wanted}' is not recognised. Use stock, fund, bond, option, future, rights, commodity, base, housing, energy, tal or all "
        "(or a Persian word such as 'سهام' or 'صندوق')."
    )


def security_type_matches(actual: str | None, wanted: str | None) -> bool:
    """``wanted`` is a substring of the Persian type name or an English word; ``all`` matches everything (TAL included)."""
    if wanted is None or not str(wanted).strip():
        return actual != TYPE_TAL  # the site hides the TAL segments unless asked
    key = str(wanted).strip().casefold()
    if key in ("all", "*", "همه"):
        return True
    needle = TYPE_WORDS.get(key, str(wanted).strip())
    return clean(needle) in (actual or "")


def _level(book: list[dict], n: int) -> dict:
    for item in book:
        if _i(item.get("n")) == n:
            return item
    return {}


def shape_market_row(raw: dict, *, industries: dict[str, str] | None = None, gateway: dict | None = None) -> dict:
    """One instrument in the shape ``shape.shape_watch_row`` produces, plus what only this feed knows."""
    py = _f(raw.get("py"))
    last, close = _f(raw.get("pdv")), _f(raw.get("pcl"))
    volume, value, trades = _f(raw.get("qtj")), _f(raw.get("qtc")), _i(raw.get("ztt")) or 0
    upper, lower = _f(raw.get("pMax")), _f(raw.get("pMin"))
    book = raw.get("blDs") or []
    levels = [_level(book, n) for n in range(1, 6)]
    best_bid, best_ask = levels[0], levels[0]
    bid_volume, ask_volume = _f(best_bid.get("qmd")) or 0.0, _f(best_ask.get("qmo")) or 0.0
    def live_volume(side_price: str, side_volume: str, ok) -> float:  # volume that can trade today (inside the price limits)
        return sum(_f(lv.get(side_volume)) or 0.0 for lv in levels if (_f(lv.get(side_price)) or 0.0) and ok(_f(lv.get(side_price)) or 0.0))

    live_asks = live_volume("pmo", "qmo", lambda p: not upper or p <= upper)
    live_bids = live_volume("pmd", "qmd", lambda p: not lower or p >= lower)
    traded = trades > 0
    limited = bool(upper and lower and upper != lower)  # TAL rows have equal limits
    at_upper = bool(traded and limited and last is not None and last >= upper)
    at_lower = bool(traded and limited and last is not None and last <= lower)
    shares = _f(raw.get("ztd"))
    pe = _f(raw.get("pe"))
    pe = pe if pe is not None and pe > 0 else None  # a loss-maker has no meaningful P/E
    sector = (raw.get("csv") or "").strip()
    gw = gateway or {}

    def pct(price: float | None) -> float | None:
        return None if price is None or not py else round((price - py) / py * 100, 2)

    row: dict[str, Any] = {
        "symbol": clean(raw.get("lva")),
        "name": clean(raw.get("lvc")),
        "instrument_id": raw.get("insID"),
        "ins_code": str(raw.get("insCode")) if raw.get("insCode") else None,
        "last": last if traded else None,
        "last_pct": pct(last) if traded else None,
        "close": close if traded else None,
        "close_pct": pct(close) if traded else None,
        "yesterday": py,
        "open": _f(raw.get("pf")) or None,
        "high": _f(raw.get("pmx")) or None,
        "low": _f(raw.get("pmn")) or None,
        "volume": _i(volume),
        "value": _i(value),
        "trades": trades,
        "vwap": _r(_safe_div(value, volume)),
        "price_limits": {"upper": upper, "lower": lower},
        "at_upper_limit": at_upper,
        "at_lower_limit": at_lower,
        "buy_queue_probable": bool(at_upper and bid_volume and (_f(best_bid.get("pmd")) or 0) >= (upper or 0) and not live_asks),
        "sell_queue_probable": bool(at_lower and ask_volume and (_f(best_ask.get("pmo")) or 0) <= (lower or 0) and not live_bids),
        "best_bid": {"price": _f(best_bid.get("pmd")) or None, "volume": _i(bid_volume) or None, "orders": _i(best_bid.get("zmd")) or None},
        "best_ask": {"price": _f(best_ask.get("pmo")) or None, "volume": _i(ask_volume) or None, "orders": _i(best_ask.get("zmo")) or None},
        "pe": pe or None,
        "eps": _f(raw.get("eps")),
        "market_cap": _i(close * shares) if close and shares else None,
        "effect_on_index": gw.get("effect_on_index"),
        "market": market_of(raw),
        "board": gw.get("board") or BOARD_TITLES.get((raw.get("cGrValCot") or "").strip()) or (raw.get("cGrValCot") or "").strip() or None,
        "industry": (industries or {}).get(sector) or gw.get("industry"),
        "sub_industry": gw.get("sub_industry"),
        "security_type": classify_instrument(raw),
        "status": gw.get("status"),
        "market_type": gw.get("market_type"),
        # only this feed
        "base_volume": _f(raw.get("bv")),
        "shares": _i(shares),
        "nav": _f(raw.get("pRedTran")) or None,
        "open_interest": _i(raw.get("buyOP")) or None,
        "sector_code": sector or None,
        "board_code": (raw.get("cGrValCot") or "").strip() or None,
        "type_code": _i(raw.get("yVal")),
        "flow": _i(raw.get("flow")),
        "last_update": _i(raw.get("hEven")),
        "fara": is_fara(raw),
        "book": [
            {"bid_price": _f(lv.get("pmd")) or None, "bid_volume": _i(lv.get("qmd")) or None, "bid_orders": _i(lv.get("zmd")) or None,
             "ask_price": _f(lv.get("pmo")) or None, "ask_volume": _i(lv.get("qmo")) or None, "ask_orders": _i(lv.get("zmo")) or None}
            for lv in levels
        ],
    }
    return row


def gateway_extras(item: dict) -> dict[str, Any]:
    """What the TSE gateway row adds to a feed row: names the feed only has as codes, plus status and index effect."""
    shaped = shape_watch_row(item)
    return {
        "effect_on_index": shaped["effect_on_index"], "board": shaped["board"], "industry": shaped["industry"],
        "sub_industry": shaped["sub_industry"], "status": shaped["status"], "market_type": shaped["market_type"],
    }


def industry_names(static: list[dict]) -> dict[str, str]:
    """Industry-group code (as the feed's ``csv``) -> Persian name, from the exchange's static data."""
    out: dict[str, str] = {}
    for item in static:
        if item.get("type") == "IndustrialGroup":
            code = str(item.get("code")).strip()
            if code and clean(item.get("name")):
                out[code] = clean(item.get("name")) or ""
    return out
