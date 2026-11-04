"""Safe filter language for whole-market screening (the agent-facing twin of tsetmc.com's filter box).

A filter is a small expression evaluated for every instrument of the market watch::

    volume > 2 * avg(volume, 20) and close_pct > 1 and all(close_pct > 0, 2)

* today's values are plain names (``last``, ``volume``, ``real_net_value`` ...);
* ``close[1]`` is yesterday's value, ``avg(volume, 20)`` the mean of the 20 trading days before today;
* ``count`` / ``all`` / ``any`` / ``highest`` / ``lowest`` / ``sum`` / ``stdev`` aggregate any expression over
  the previous *n* trading days, evaluated day by day.

User text is parsed with :mod:`ast`, checked against a whitelist and compiled into closures. It is never
passed to ``eval``/``exec`` and cannot reach attributes, imports or the interpreter. Missing data
propagates as ``None`` with three-valued logic, and only rows whose filter is exactly ``True`` match.
"""

from __future__ import annotations

import ast
import difflib
import math
import re
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .text import ascii_digits, match_key

MAX_LOOKBACK = 60  # trading days of history a filter may reach into
MAX_TEXT = 1500
MAX_NODES = 200


class FilterError(ValueError):
    """The filter text is invalid. The message says where and how to fix it."""


# ------------------------------------------------------------------------------------------ fields


@dataclass(frozen=True)
class Field:
    name: str
    kind: str  # "num" | "bool" | "text"
    unit: str
    label: str  # Persian label, as the exchange's own site words it where possible
    doc: str
    history: bool = False  # usable as close[1] / inside avg(..., n)
    flows: bool = False  # needs the real/legal feed
    aliases: tuple[str, ...] = ()


def _f(name: str, kind: str, unit: str, label: str, doc: str, **kw: Any) -> Field:
    return Field(name, kind, unit, label, doc, **kw)


FIELDS: tuple[Field, ...] = (
    # identity
    _f("symbol", "text", "text", "نماد", "Ticker, e.g. فولاد.", aliases=("l18",)),
    _f("name", "text", "text", "نام شرکت", "Company name.", aliases=("l30",)),
    _f("industry", "text", "text", "گروه صنعت", "Industry group, e.g. 'فلزات اساسی'. Use has(industry, 'فلزات') or industry in ('بانکها', 'خودرو')."),
    _f("sub_industry", "text", "text", "زیرگروه صنعت", "Industry sub-group."),
    _f("market", "text", "text", "بازار", "'بورس' or 'فرابورس'."),
    _f("board", "text", "text", "تابلو", "Board, e.g. 'بازار اول - اصلی', 'تابلو فرعی', 'نوآفرین'."),
    _f("security_type", "text", "text", "نوع اوراق", "e.g. 'سهام عادی', 'حق تقدم'."),
    _f("status", "text", "text", "وضعیت نماد", "Trading status: 'مجاز', 'مجاز-محفوظ', 'ممنوع' ..."),
    # prices (history-capable)
    _f("last", "num", "rial", "آخرین معامله", "Last trade price.", history=True, aliases=("pl", "last_price")),
    _f("close", "num", "rial", "قیمت پایانی", "Closing (volume-weighted) price.", history=True, aliases=("pc", "closing_price")),
    _f("open", "num", "rial", "اولین قیمت", "First trade price of the day.", history=True, aliases=("pf", "first", "first_price")),
    _f("high", "num", "rial", "بیشترین قیمت", "Day high.", history=True, aliases=("pmax", "max_price")),
    _f("low", "num", "rial", "کمترین قیمت", "Day low.", history=True, aliases=("pmin", "min_price")),
    _f("yesterday", "num", "rial", "قیمت دیروز", "Reference price: previous day's adjusted close.", history=True, aliases=("py", "yesterday_price")),
    _f("last_change", "num", "rial", "تغییر آخرین معامله", "Last trade minus reference price.", history=True, aliases=("plc",)),
    _f("close_change", "num", "rial", "تغییر قیمت پایانی", "Close minus reference price.", history=True, aliases=("pcc",)),
    _f("last_pct", "num", "%", "درصد آخرین معامله", "Last trade vs reference price, in percent.", history=True, aliases=("plp",)),
    _f("close_pct", "num", "%", "درصد قیمت پایانی", "Close vs reference price, in percent.", history=True, aliases=("pcp",)),
    _f("vwap", "num", "rial", "میانگین قیمت معاملات", "value / volume.", history=True),
    # activity (history-capable)
    _f("volume", "num", "shares", "حجم معاملات", "Traded volume in shares.", history=True, aliases=("tvol", "vol")),
    _f("value", "num", "rial", "ارزش معاملات", "Traded value in rial (1B = one billion rial = 100M toman).", history=True, aliases=("tval",)),
    _f("trades", "num", "count", "تعداد معاملات", "Number of trades.", history=True, aliases=("tno",)),
    # limits and order book (today only)
    _f("upper_limit", "num", "rial", "حد مجاز بالا", "Upper price limit (سقف قیمت).", aliases=("tmax", "max_limit")),
    _f("lower_limit", "num", "rial", "حد مجاز پایین", "Lower price limit (کف قیمت).", aliases=("tmin", "min_limit")),
    _f("bid_price", "num", "rial", "بهترین قیمت خرید", "Best bid price.", aliases=("pd1",)),
    _f("bid_volume", "num", "shares", "حجم بهترین خرید", "Volume at the best bid.", aliases=("qd1",)),
    _f("bid_orders", "num", "count", "تعداد سفارش خرید", "Orders at the best bid.", aliases=("zd1",)),
    _f("ask_price", "num", "rial", "بهترین قیمت فروش", "Best ask price.", aliases=("po1",)),
    _f("ask_volume", "num", "shares", "حجم بهترین فروش", "Volume at the best ask.", aliases=("qo1",)),
    _f("ask_orders", "num", "count", "تعداد سفارش فروش", "Orders at the best ask.", aliases=("zo1",)),
    _f("bid_value", "num", "rial", "ارزش صف خرید (تخمین)", "bid_volume x bid_price (queue size when locked at the upper limit)."),
    _f("ask_value", "num", "rial", "ارزش صف فروش (تخمین)", "ask_volume x ask_price."),
    _f("at_upper_limit", "bool", "flag", "در سقف قیمت", "Last price is at the upper limit."),
    _f("at_lower_limit", "bool", "flag", "در کف قیمت", "Last price is at the lower limit."),
    _f("buy_queue", "bool", "flag", "صف خرید", "At the upper limit with nothing offered: a probable buy queue (top_movers confirms against the order book)."),
    _f("sell_queue", "bool", "flag", "صف فروش", "At the lower limit with nothing bid: a probable sell queue."),
    # valuation (today only)
    _f("pe", "num", "ratio", "P/E", "Price / earnings (null when loss-making).", aliases=("p_e",)),
    _f("eps", "num", "rial", "EPS", "Earnings per share, rial."),
    _f("market_cap", "num", "rial", "ارزش بازار", "Market capitalisation: closing price x shares outstanding, rial.", aliases=("mv", "market_value")),
    _f("index_effect", "num", "points", "تاثیر در شاخص", "Contribution to the total index, in index points.", aliases=("effect_on_index",)),
    # instrument facts (today only)
    _f("base_volume", "num", "shares", "حجم مبنا", "Base volume (the exchange's reference volume; 1 for nearly every symbol).", aliases=("bvol", "bv")),
    _f("shares", "num", "count", "تعداد سهام", "Shares outstanding (units for funds).", aliases=("z",)),
    _f("nav", "num", "rial", "NAV ابطال صندوق", "Fund redemption NAV per unit; empty for non-funds.", aliases=("predtran",)),
    _f("nav_premium_pct", "num", "%", "حباب صندوق", "(last / nav - 1) x 100 for funds: positive means trading above redemption NAV."),
    _f("open_interest", "num", "contracts", "موقعیت‌های باز", "Open interest of options and futures.", aliases=("buyop",)),
    _f("sector_code", "num", "code", "کد گروه صنعت", "Industry-group code of the exchange.", aliases=("cs",)),
    _f("type_code", "num", "code", "کد نوع ابزار", "The exchange's instrument-type code, e.g. 300 shares, 305 fund, 311 option."),
    _f("last_update", "num", "HHMMSS", "زمان آخرین بروزرسانی", "Time this row was last updated, e.g. 123000."),
    _f("bid_volume_5", "num", "shares", "حجم ۵ سطر خرید", "Total volume of the five best bids."),
    _f("ask_volume_5", "num", "shares", "حجم ۵ سطر فروش", "Total volume of the five best asks."),
    # derived price shape (today only)
    _f("gap_pct", "num", "%", "گپ بازگشایی", "(open / yesterday - 1) x 100."),
    _f("range_pct", "num", "%", "دامنه نوسان روز", "(high - low) / yesterday x 100."),
    _f("from_high_pct", "num", "%", "فاصله از سقف روز", "(last / high - 1) x 100; 0 when trading at the day high."),
    _f("from_low_pct", "num", "%", "فاصله از کف روز", "(last / low - 1) x 100."),
    _f("to_upper_limit_pct", "num", "%", "فاصله تا سقف مجاز", "(upper_limit / last - 1) x 100."),
    # real / legal (today only, from the exchange's client-type table)
    _f("real_buy_volume", "num", "shares", "حجم خرید حقیقی", "Real-person buy volume.", flows=True, aliases=("buy_i_volume", "ct_buy_i_volume")),
    _f("real_sell_volume", "num", "shares", "حجم فروش حقیقی", "Real-person sell volume.", flows=True, aliases=("sell_i_volume", "ct_sell_i_volume")),
    _f("real_buy_count", "num", "count", "تعداد خریدار حقیقی", "Number of real-person buyers.", flows=True, aliases=("buy_count_i", "ct_buy_counti")),
    _f("real_sell_count", "num", "count", "تعداد فروشنده حقیقی", "Number of real-person sellers.", flows=True, aliases=("sell_count_i", "ct_sell_counti")),
    _f("legal_buy_volume", "num", "shares", "حجم خرید حقوقی", "Legal-entity buy volume.", flows=True, aliases=("buy_n_volume", "ct_buy_n_volume")),
    _f("legal_sell_volume", "num", "shares", "حجم فروش حقوقی", "Legal-entity sell volume.", flows=True, aliases=("sell_n_volume", "ct_sell_n_volume")),
    _f("legal_buy_count", "num", "count", "تعداد خریدار حقوقی", "Number of legal-entity buyers.", flows=True, aliases=("buy_count_n", "ct_buy_countn")),
    _f("legal_sell_count", "num", "count", "تعداد فروشنده حقوقی", "Number of legal-entity sellers.", flows=True, aliases=("sell_count_n", "ct_sell_countn")),
    _f("real_net_volume", "num", "shares", "خالص حجم خرید حقیقی", "Real buy volume - real sell volume (>0 = real-person inflow).", flows=True),
    _f("real_net_value", "num", "rial", "خالص ورود پول حقیقی (تخمین)", "Estimate: real_net_volume x vwap.", flows=True),
    _f("legal_net_volume", "num", "shares", "خالص حجم خرید حقوقی", "Legal buy volume - legal sell volume.", flows=True),
    _f("real_buyer_power", "num", "ratio", "قدرت خریدار حقیقی", "Average real buy size / average real sell size (>1: buyers are bigger).", flows=True, aliases=("buyer_power",)),
    _f("real_buy_share", "num", "%", "سهم خرید حقیقی", "Real-person share of all buy volume, percent.", flows=True),
    _f("real_sell_share", "num", "%", "سهم فروش حقیقی", "Real-person share of all sell volume, percent.", flows=True),
)

_LEVEL_SPECS = (("pd", "rial", "bid price", "قیمت خرید"), ("qd", "shares", "bid volume", "حجم خرید"), ("zd", "count", "bid orders", "تعداد خریدار"),
                ("po", "rial", "ask price", "قیمت فروش"), ("qo", "shares", "ask volume", "حجم فروش"), ("zo", "count", "ask orders", "تعداد فروشنده"))
FIELDS += tuple(  # five-level order book; level 1 is bid_price, bid_volume ... above (pd1 and friends are their aliases)
    _f(f"{code}{n}", "num", unit, f"{fa}، سطر {n}", f"Order-book level {n}: {en}.")
    for n in range(2, 6)
    for code, unit, en, fa in _LEVEL_SPECS
)

_BY_NAME: dict[str, Field] = {}
for _field in FIELDS:
    _BY_NAME[_field.name] = _field
    for _alias in _field.aliases:
        _BY_NAME[_alias] = _field
HISTORY_FIELDS = tuple(f.name for f in FIELDS if f.history)


# ------------------------------------------------------------------------------------- data builders


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or not b:
        return None
    return a / b


def _pct(a: float | None, b: float | None) -> float | None:
    ratio = _div(a, b)
    return None if ratio is None else (ratio - 1) * 100


def build_today(row: dict, flow: dict | None = None) -> dict[str, Any]:
    """Field values for today from a shaped market-watch row (``shape.shape_watch_row``) and the raw client-type row."""
    limits = row.get("price_limits") or {}
    bid, ask = row.get("best_bid") or {}, row.get("best_ask") or {}
    last, high, low, open_, yest = row.get("last"), row.get("high"), row.get("low"), row.get("open"), row.get("yesterday")
    upper = limits.get("upper")
    out: dict[str, Any] = {
        "symbol": row.get("symbol"), "name": row.get("name"), "industry": row.get("industry"),
        "sub_industry": row.get("sub_industry"), "market": row.get("market"), "board": row.get("board"),
        "security_type": row.get("security_type"), "status": row.get("status"),
        "last": last, "close": row.get("close"), "open": open_, "high": high, "low": low, "yesterday": yest,
        "last_pct": row.get("last_pct"), "close_pct": row.get("close_pct"), "vwap": row.get("vwap"),
        "last_change": None if last is None or yest is None else last - yest,
        "close_change": None if row.get("close") is None or yest is None else row["close"] - yest,
        "volume": row.get("volume"), "value": row.get("value"), "trades": row.get("trades"),
        "upper_limit": upper, "lower_limit": limits.get("lower"),
        "bid_price": bid.get("price"), "bid_volume": bid.get("volume"), "bid_orders": bid.get("orders"),
        "ask_price": ask.get("price"), "ask_volume": ask.get("volume"), "ask_orders": ask.get("orders"),
        "bid_value": None if not bid.get("volume") or not bid.get("price") else bid["volume"] * bid["price"],
        "ask_value": None if not ask.get("volume") or not ask.get("price") else ask["volume"] * ask["price"],
        "at_upper_limit": bool(row.get("at_upper_limit")), "at_lower_limit": bool(row.get("at_lower_limit")),
        "buy_queue": bool(row.get("buy_queue_probable")), "sell_queue": bool(row.get("sell_queue_probable")),
        "pe": row.get("pe"), "eps": row.get("eps"), "market_cap": row.get("market_cap"), "index_effect": row.get("effect_on_index"),
        "gap_pct": _pct(open_, yest), "range_pct": _div(None if high is None or low is None else high - low, yest),
        "from_high_pct": _pct(last, high), "from_low_pct": _pct(last, low), "to_upper_limit_pct": _pct(upper, last),
    }
    if out["range_pct"] is not None:
        out["range_pct"] *= 100
    out.update(
        base_volume=row.get("base_volume"), shares=row.get("shares"), nav=row.get("nav"), open_interest=row.get("open_interest"),
        sector_code=_num(row.get("sector_code")), type_code=row.get("type_code"), last_update=row.get("last_update"),
        nav_premium_pct=_pct(last, row.get("nav")) if row.get("nav") else None,
    )
    book = row.get("book") or []
    if book:
        keys = {"pd": "bid_price", "qd": "bid_volume", "zd": "bid_orders", "po": "ask_price", "qo": "ask_volume", "zo": "ask_orders"}
        for n, level in enumerate(book[:5], start=1):
            if n > 1:
                for code, key in keys.items():
                    out[f"{code}{n}"] = level.get(key)
        out["bid_volume_5"] = sum(level.get("bid_volume") or 0 for level in book[:5])
        out["ask_volume_5"] = sum(level.get("ask_volume") or 0 for level in book[:5])
    if flow:
        buy_i, sell_i = _num(flow.get("buy_I_Volume")) or 0.0, _num(flow.get("sell_I_Volume")) or 0.0
        buy_n, sell_n = _num(flow.get("buy_N_Volume")) or 0.0, _num(flow.get("sell_N_Volume")) or 0.0
        cnt_bi = _num(flow.get("buy_CountI") if flow.get("buy_CountI") is not None else flow.get("buy_I_Count")) or 0.0
        cnt_si = _num(flow.get("sell_CountI") if flow.get("sell_CountI") is not None else flow.get("sell_I_Count")) or 0.0
        cnt_bn = _num(flow.get("buy_CountN") if flow.get("buy_CountN") is not None else flow.get("buy_N_Count")) or 0.0
        cnt_sn = _num(flow.get("sell_CountN") if flow.get("sell_CountN") is not None else flow.get("sell_N_Count")) or 0.0
        net = buy_i - sell_i
        vwap = out["vwap"] or out["last"] or 0.0
        power = _div(_div(buy_i, cnt_bi), _div(sell_i, cnt_si))
        out.update(
            real_buy_volume=buy_i, real_sell_volume=sell_i, real_buy_count=cnt_bi, real_sell_count=cnt_si,
            legal_buy_volume=buy_n, legal_sell_volume=sell_n, legal_buy_count=cnt_bn, legal_sell_count=cnt_sn,
            real_net_volume=net, real_net_value=net * vwap, legal_net_volume=buy_n - sell_n,
            real_buyer_power=power,
            real_buy_share=_div(buy_i * 100, buy_i + buy_n), real_sell_share=_div(sell_i * 100, sell_i + sell_n),
        )
    return out


def build_history_day(raw: dict) -> dict[str, Any]:
    """One past trading day from the exchange's end-of-day table row."""
    def price(key: str) -> float | None:
        value = _num(raw.get(key))
        return value if value else None

    close, yest, last = price("pClosing"), price("priceYesterday"), price("pDrCotVal")
    volume, value = _num(raw.get("qTotTran5J")), _num(raw.get("qTotCap"))
    return {
        "open": price("priceFirst"), "high": price("priceMax"), "low": price("priceMin"), "close": close, "last": last,
        "yesterday": yest, "close_pct": _pct(close, yest), "last_pct": _pct(last, yest),
        "close_change": None if close is None or yest is None else close - yest,
        "last_change": None if last is None or yest is None else last - yest,
        "volume": volume, "value": value, "trades": _num(raw.get("zTotTran")), "vwap": _div(value, volume),
    }


NOT_TRADED: dict[str, Any] = {"volume": 0.0, "value": 0.0, "trades": 0.0}  # listed, but silent that day
NO_DATA: dict[str, Any] = {}  # not listed yet (or the table is missing)

_PRICE_KEYS = ("open", "high", "low", "close", "last", "yesterday", "vwap", "close_change", "last_change")


def adjust_history(today_yesterday: float | None, days: list[dict[str, Any]], *, tolerance: float = 1e-3) -> list[dict[str, Any]]:
    """Back-adjust prices of ``days`` (newest first) for capital increases and dividends, in place.

    On an ex-date the exchange moves the reference price: the next row's ``yesterday`` no longer equals this row's
    close. That ratio, accumulated going back in time, restores a continuous series at today's price level.
    """
    factor = 1.0
    newer_yesterday = today_yesterday
    for day in days:
        close = day.get("close")
        if close is None:  # a silent or unknown day: link the traded days on either side of it instead
            continue
        raw_yesterday = day.get("yesterday")
        if newer_yesterday:
            ratio = newer_yesterday / close
            if abs(ratio - 1) > tolerance:
                factor *= ratio
        if factor != 1.0:
            for key in _PRICE_KEYS:
                if day.get(key) is not None:
                    day[key] *= factor
        newer_yesterday = raw_yesterday
    return days


# -------------------------------------------------------------------------------------- evaluation


class Ctx:
    """Everything known about one instrument: today's values and its previous trading days (newest first)."""

    __slots__ = ("today", "days")

    def __init__(self, today: dict[str, Any], days: Sequence[dict[str, Any]] = ()) -> None:
        self.today = today
        self.days = days

    def get(self, name: str, offset: int) -> Any:
        if offset == 0:
            return self.today.get(name)
        index = offset - 1
        return self.days[index].get(name) if index < len(self.days) else None


Eval = Callable[[Ctx, int], Any]


@dataclass
class Node:
    fn: Eval
    kind: str  # num | bool | text | any
    need: int = 0  # trading days of history required below the evaluation offset


@dataclass
class Compiled:
    text: str
    fn: Eval
    kind: str
    lookback: int
    uses_flows: bool
    fields: frozenset[str]
    evidence: list[tuple[str, Eval]] = field(default_factory=list)

    def __call__(self, ctx: Ctx) -> Any:
        return self.fn(ctx, 0)


def _truth(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return value != 0


def _and(values: Sequence[bool | None]) -> bool | None:
    if any(v is False for v in values):
        return False
    return None if any(v is None for v in values) else True


def _or(values: Sequence[bool | None]) -> bool | None:
    if any(v is True for v in values):
        return True
    return None if any(v is None for v in values) else False


def _safe(fn: Callable[..., Any], *args: Any) -> Any:
    try:
        out = fn(*args)
    except (ArithmeticError, ValueError, TypeError):
        return None
    if isinstance(out, float) and not math.isfinite(out):
        return None
    return out


def _clean_numbers(values: Sequence[Any]) -> list[float]:
    return [float(v) for v in values if v is not None and not isinstance(v, str)]


# ------------------------------------------------------------------------------------------ parsing

_STRING = re.compile(r"""("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')""")
_SUFFIX = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)([kKmMbBtT])(?![\w])")
_SUFFIX_FACTOR = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}
_QUOTES = str.maketrans({"“": '"', "”": '"', "«": '"', "»": '"', "‘": "'", "’": "'", "،": ",", "٫": ".", "؛": ";"})


def _suffix(match: re.Match[str]) -> str:
    return repr(float(match.group(1)) * _SUFFIX_FACTOR[match.group(2).lower()])


def _plain(segment: str) -> str:
    segment = re.sub(r"\bMath\.", "", segment)  # Math.abs(x), Math.max(a, b) from the exchange's JavaScript filters
    segment = re.sub(r"\bct\.(\w+)", r"ct_\1", segment)  # ct.Buy_I_Volume -> ct_buy_i_volume (an alias)
    segment = segment.replace("===", "==").replace("!==", "!=")
    segment = _SUFFIX.sub(_suffix, segment)
    segment = segment.replace("&&", " and ").replace("||", " or ").replace("<>", "!=")
    segment = re.sub(r"!(?!=)", " not ", segment)
    return re.sub(r"(?<![<>=!])=(?!=)", "==", segment)


def normalise(text: str) -> str:
    """Persian digits/quotes to ASCII, ``&&``/``||``/``!``/``=`` and 5B-style suffixes to Python spelling."""
    text = ascii_digits(str(text)).translate(_QUOTES).strip()
    parts = _STRING.split(text)  # odd entries are string literals: leave them alone
    return "".join(part if i % 2 else _plain(part) for i, part in enumerate(parts))


_COMPARE = {
    ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b, ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b, ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
}
_ARITH = {
    ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b, ast.Mod: lambda a, b: a % b, ast.FloorDiv: lambda a, b: a // b,
}
_AGGREGATES = {"avg", "sum", "highest", "lowest", "stdev", "count", "all", "any"}
_SCALARS = {
    "abs": (1, 1, "num"), "round": (1, 2, "num"), "sqrt": (1, 1, "num"), "log": (1, 1, "num"), "min": (2, 8, "num"),
    "max": (2, 8, "num"), "pct": (2, 2, "num"), "between": (3, 3, "bool"), "iff": (3, 3, "any"), "coalesce": (2, 8, "any"),
    "isnull": (1, 1, "bool"), "has": (2, 2, "bool"), "startswith": (2, 2, "bool"),
}
FUNCTION_DOCS = {
    "abs(x)": "absolute value",
    "round(x, digits=0)": "round",
    "sqrt(x), log(x)": "square root, natural log (null if undefined)",
    "min(a, b, ...), max(a, b, ...)": "smallest / largest of several values (null-safe)",
    "pct(a, b)": "(a / b - 1) x 100, the percent change from b to a",
    "between(x, lo, hi)": "lo <= x <= hi",
    "iff(cond, a, b)  or  a if cond else b": "conditional value",
    "coalesce(a, b, ...)": "first non-null value",
    "isnull(x)": "true when the value is missing",
    "has(text, 'sub')": "text contains (Persian/Arabic letter variants are equal), e.g. has(industry, 'خودرو')",
    "startswith(text, 'prefix')": "text starts with",
    "x in ('a', 'b')": "membership for text or numbers",
    "field[k]": "value k trading days ago (close[1] = yesterday); history fields only",
    "ago(expr, k)": "evaluate expr as of k trading days ago",
    "avg(expr, n)  sum  highest  lowest  stdev": "aggregate expr over the n trading days BEFORE today",
    "count(cond, n)": "how many of the last n days cond was true",
    "all(cond, n)  any(cond, n)": "cond true on every / at least one of the last n days (all needs n days of history)",
}


def _suggest(name: str) -> str:
    close = difflib.get_close_matches(name.casefold(), list(_BY_NAME), n=3, cutoff=0.55)
    return f" Did you mean {', '.join(repr(c) for c in close)}?" if close else " Use screener_reference to list the fields."


class _Compiler:
    def __init__(self, source: str) -> None:
        self.source = source
        self.nodes = 0
        self.fields: set[str] = set()
        self.flows = False
        self.evidence: list[tuple[str, Eval]] = []

    # -- errors
    def fail(self, node: ast.AST, message: str) -> FilterError:
        column = getattr(node, "col_offset", None)
        where = f" (at character {column + 1}: `{self.source[column:column + 28]}`)" if column is not None else ""
        return FilterError(message + where)

    def segment(self, node: ast.AST) -> str:
        return ast.get_source_segment(self.source, node) or ""

    # -- dispatch
    def visit(self, node: ast.AST, lagged: bool = False, in_agg: bool = False) -> Node:
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise FilterError(f"Filter is too complex (more than {MAX_NODES} parts).")
        method = getattr(self, "v_" + type(node).__name__, None)
        if method is None:
            raise self.fail(node, f"{type(node).__name__} is not allowed in a filter (only arithmetic, comparisons, and/or/not, functions and field names)")
        return method(node, lagged, in_agg)

    # -- leaves
    def v_Constant(self, node: ast.Constant, lagged: bool, in_agg: bool) -> Node:
        value = node.value
        if isinstance(value, bool):
            return Node(lambda c, o, v=value: v, "bool")
        if isinstance(value, (int, float)):
            number = float(value)
            return Node(lambda c, o, v=number: v, "num")
        if isinstance(value, str):
            return Node(lambda c, o, v=value: v, "text")
        if value is None:
            return Node(lambda c, o: None, "any")
        raise self.fail(node, "Unsupported literal")

    def field_node(self, node: ast.AST, name: str, offset: int, lagged: bool) -> Node:
        low = name.casefold()
        if low in ("true", "false"):
            return Node(lambda c, o, v=(low == "true"): v, "bool")
        if low in ("null", "none", "nan"):
            return Node(lambda c, o: None, "any")
        spec = _BY_NAME.get(low)
        if spec is None:
            raise self.fail(node, f"Unknown field '{name}'." + _suggest(name))
        if (lagged or offset) and not spec.history:
            raise self.fail(node, f"'{spec.name}' has no daily history, so it cannot be used as {spec.name}[k] or inside avg()/count()/ago(). History fields: {', '.join(HISTORY_FIELDS)}")
        self.fields.add(spec.name)
        self.flows = self.flows or spec.flows
        key = spec.name
        if offset:
            return Node(lambda c, o, k=key, d=offset: c.get(k, o + d), spec.kind, offset)
        return Node(lambda c, o, k=key: c.get(k, o), spec.kind, 0)

    def v_Name(self, node: ast.Name, lagged: bool, in_agg: bool) -> Node:
        return self.field_node(node, node.id, 0, lagged)

    def v_Subscript(self, node: ast.Subscript, lagged: bool, in_agg: bool) -> Node:
        if not isinstance(node.value, ast.Name):
            raise self.fail(node, "Only field[k] is allowed, for example close[1]")
        index = node.slice
        if not (isinstance(index, ast.Constant) and isinstance(index.value, int) and not isinstance(index.value, bool)) or not 0 <= index.value <= MAX_LOOKBACK:
            raise self.fail(node, f"The index in field[k] must be a whole number from 0 to {MAX_LOOKBACK} (days ago)")
        out = self.field_node(node, node.value.id, index.value, lagged)
        if not lagged:
            self.evidence.append((self.segment(node), out.fn))
        return out

    # -- operators
    def v_UnaryOp(self, node: ast.UnaryOp, lagged: bool, in_agg: bool) -> Node:
        inner = self.visit(node.operand, lagged, in_agg)
        if isinstance(node.op, ast.Not):
            if inner.kind == "text":
                raise self.fail(node, "'not' needs a condition, not text")
            return Node(lambda c, o, f=inner.fn: None if (t := _truth(f(c, o))) is None else not t, "bool", inner.need)
        if isinstance(node.op, (ast.USub, ast.UAdd)):
            self.numeric(node, inner)
            sign = -1 if isinstance(node.op, ast.USub) else 1
            return Node(lambda c, o, f=inner.fn, s=sign: None if (v := f(c, o)) is None else s * v, "num", inner.need)
        raise self.fail(node, "Operator not allowed")

    def numeric(self, node: ast.AST, *inner: Node) -> None:
        for item in inner:
            if item.kind == "text":
                raise self.fail(node, "Arithmetic needs numbers, but this is text")

    def v_BinOp(self, node: ast.BinOp, lagged: bool, in_agg: bool) -> Node:
        op = _ARITH.get(type(node.op))
        if op is None:
            raise self.fail(node, "Only + - * / % // are allowed (no powers; use sqrt/log/abs)")
        a, b = self.visit(node.left, lagged, in_agg), self.visit(node.right, lagged, in_agg)
        self.numeric(node, a, b)

        def run(c: Ctx, o: int, fa: Eval = a.fn, fb: Eval = b.fn, op: Callable[[Any, Any], Any] = op) -> Any:
            x, y = fa(c, o), fb(c, o)
            return None if x is None or y is None else _safe(op, x, y)

        return Node(run, "num", max(a.need, b.need))

    def v_BoolOp(self, node: ast.BoolOp, lagged: bool, in_agg: bool) -> Node:
        parts = [self.visit(v, lagged, in_agg) for v in node.values]
        for part in parts:
            if part.kind == "text":
                raise self.fail(node, "and/or need conditions, but one side is text")
        combine = _and if isinstance(node.op, ast.And) else _or
        return Node(lambda c, o, ps=tuple(parts), f=combine: f([_truth(p.fn(c, o)) for p in ps]), "bool", max(p.need for p in parts))

    def v_Compare(self, node: ast.Compare, lagged: bool, in_agg: bool) -> Node:
        operands = [self.visit(node.left, lagged, in_agg)]
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            # the right side of `in` is a literal list, not an expression
            operands.append(Node(lambda c, o: None, "any") if isinstance(op, (ast.In, ast.NotIn)) else self.visit(comparator, lagged, in_agg))
        links = []
        for i, op in enumerate(node.ops):
            left, right = operands[i], operands[i + 1]
            if isinstance(op, (ast.In, ast.NotIn)):
                links.append(self.membership(node, node.comparators[i], left, isinstance(op, ast.NotIn), lagged, in_agg))
                continue
            fn = _COMPARE.get(type(op))
            if fn is None:
                raise self.fail(node, "Operator not allowed")
            kinds = {left.kind, right.kind}
            if "any" not in kinds and "text" in kinds and len(kinds) > 1:
                raise self.fail(node, "Cannot compare text with a number")
            if "text" in kinds and not isinstance(op, (ast.Eq, ast.NotEq)):
                raise self.fail(node, "Text can only be compared with == / != (use has() or startswith() for 'contains')")
            links.append((left, right, fn, "text" in kinds))

        def run(c: Ctx, o: int) -> bool | None:
            results = []
            for link in links:
                if callable(link):
                    results.append(link(c, o))
                    continue
                left, right, fn, text = link
                x, y = left.fn(c, o), right.fn(c, o)
                if x is None or y is None:
                    results.append(None)
                    continue
                if text and isinstance(x, str) and isinstance(y, str):
                    x, y = match_key(x), match_key(y)
                results.append(bool(fn(x, y)))
            return _and(results)

        return Node(run, "bool", max(n.need for n in operands))

    def membership(self, node: ast.Compare, options: ast.AST, left: Node, negate: bool, lagged: bool, in_agg: bool) -> Eval:
        if not isinstance(options, (ast.Tuple, ast.List, ast.Set)) or not options.elts:
            raise self.fail(node, "'in' needs a list such as ('بانکها', 'خودرو') or (1, 2, 3)")
        values = []
        for element in options.elts:
            if not isinstance(element, ast.Constant) or element.value is None:
                raise self.fail(node, "Items of an 'in' list must be plain numbers or text")
            values.append(element.value)
        text = left.kind == "text"
        if text != all(isinstance(v, str) for v in values) and left.kind != "any":
            raise self.fail(node, "'in' list items must be the same kind (text or number) as the value on the left")
        keys = {match_key(v) if isinstance(v, str) else float(v) for v in values}

        def run(c: Ctx, o: int, f: Eval = left.fn) -> bool | None:
            x = f(c, o)
            if x is None:
                return None
            hit = (match_key(x) if isinstance(x, str) else float(x)) in keys
            return not hit if negate else hit

        return run

    def v_IfExp(self, node: ast.IfExp, lagged: bool, in_agg: bool) -> Node:
        cond, a, b = (self.visit(n, lagged, in_agg) for n in (node.test, node.body, node.orelse))
        kind = a.kind if a.kind == b.kind else "any"
        return Node(lambda c, o: a.fn(c, o) if _truth(cond.fn(c, o)) else b.fn(c, o), kind, max(cond.need, a.need, b.need))

    # -- calls
    def v_Call(self, node: ast.Call, lagged: bool, in_agg: bool) -> Node:
        if not isinstance(node.func, ast.Name) or node.keywords:
            raise self.fail(node, "Only plain function calls like avg(volume, 20) are allowed")
        name = node.func.id.casefold()
        if name in _AGGREGATES or name == "ago":
            return self.windowed(node, name, lagged, in_agg)
        spec = _SCALARS.get(name)
        if spec is None:
            known = sorted(set(_SCALARS) | _AGGREGATES | {"ago"})
            close = difflib.get_close_matches(name, known, n=3, cutoff=0.5)
            raise self.fail(node, f"Unknown function '{node.func.id}'." + (f" Did you mean {', '.join(close)}?" if close else f" Available: {', '.join(known)}"))
        low, high, kind = spec
        if not low <= len(node.args) <= high:
            raise self.fail(node, f"{name}() takes {low if low == high else f'{low} to {high}'} argument(s)")
        args = [self.visit(a, lagged, in_agg) for a in node.args]
        need = max(a.need for a in args)
        if name in ("has", "startswith"):
            if args[0].kind != "text" or args[1].kind != "text":
                raise self.fail(node, f"{name}(text, 'substring') takes two text values")
            if name == "has":
                return Node(lambda c, o: None if (t := args[0].fn(c, o)) is None else match_key(args[1].fn(c, o)) in match_key(t), "bool", need)
            return Node(lambda c, o: None if (t := args[0].fn(c, o)) is None else match_key(t).startswith(match_key(args[1].fn(c, o))), "bool", need)
        if any(a.kind == "text" for a in args) and name not in ("iff", "coalesce", "isnull"):
            raise self.fail(node, f"{name}() needs numbers, but got text")
        if name == "iff":
            out_kind = args[1].kind if args[1].kind == args[2].kind else "any"
            return Node(lambda c, o: args[1].fn(c, o) if _truth(args[0].fn(c, o)) else args[2].fn(c, o), out_kind, need)
        if name == "coalesce":
            def coalesce(c: Ctx, o: int) -> Any:
                for a in args:
                    v = a.fn(c, o)
                    if v is not None:
                        return v
                return None

            kinds = {a.kind for a in args}
            return Node(coalesce, kinds.pop() if len(kinds) == 1 else "any", need)
        if name == "isnull":
            return Node(lambda c, o: args[0].fn(c, o) is None, "bool", need)
        if name == "between":
            def between(c: Ctx, o: int) -> bool | None:
                x, lo, hi = (a.fn(c, o) for a in args)
                return None if x is None or lo is None or hi is None else lo <= x <= hi

            return Node(between, "bool", need)
        if name == "pct":
            return Node(lambda c, o: _pct(args[0].fn(c, o), args[1].fn(c, o)), "num", need)

        def scalar(c: Ctx, o: int) -> Any:
            values = [a.fn(c, o) for a in args]
            if name in ("min", "max"):
                present = [v for v in values if v is not None]
                return (min if name == "min" else max)(present) if present else None
            if values[0] is None:
                return None
            if name == "abs":
                return abs(values[0])
            if name == "sqrt":
                return _safe(math.sqrt, values[0])
            if name == "log":
                return _safe(math.log, values[0])
            digits = int(values[1]) if len(values) > 1 and values[1] is not None else 0
            return round(values[0], digits)

        return Node(scalar, kind, need)

    def window_size(self, node: ast.Call, arg: ast.AST, label: str) -> int:
        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, int) and not isinstance(arg.value, bool)) or not 1 <= arg.value <= MAX_LOOKBACK:
            raise self.fail(node, f"{label} must be a whole number of days from 1 to {MAX_LOOKBACK}")
        return arg.value

    def windowed(self, node: ast.Call, name: str, lagged: bool, in_agg: bool) -> Node:
        if len(node.args) != 2:
            raise self.fail(node, f"{name}(expression, days) takes exactly two arguments")
        if in_agg and name != "ago":
            raise self.fail(node, "Nested aggregates are not supported; use ago() or field[k] inside count()/avg()/...")
        days = self.window_size(node, node.args[1], "The number of days" if name != "ago" else "ago(expr, k): k")
        body = self.visit(node.args[0], True, name != "ago")
        need = days + body.need
        if need > MAX_LOOKBACK:
            raise self.fail(node, f"This reaches {need} trading days back; the limit is {MAX_LOOKBACK}")
        expr = body.fn
        if name == "ago":
            fn: Eval = lambda c, o: expr(c, o + days)  # noqa: E731
            node_out = Node(fn, body.kind, need)
        else:
            if name in ("count", "all", "any") and body.kind == "text":
                raise self.fail(node, f"{name}() needs a condition")
            if name not in ("count", "all", "any") and body.kind == "text":
                raise self.fail(node, f"{name}() needs a number")

            def run(c: Ctx, o: int) -> Any:
                values = [expr(c, o + i) for i in range(1, days + 1)]
                if name in ("count", "all", "any"):
                    flags = [_truth(v) for v in values]
                    if name == "count":
                        return float(sum(1 for f in flags if f))
                    if name == "all":
                        return all(f is True for f in flags)
                    return any(f is True for f in flags)
                numbers = _clean_numbers(values)
                if not numbers:
                    return None
                if name == "avg":
                    return sum(numbers) / len(numbers)
                if name == "sum":
                    return sum(numbers)
                if name == "highest":
                    return max(numbers)
                if name == "lowest":
                    return min(numbers)
                return statistics.pstdev(numbers) if len(numbers) > 1 else None

            out_kind = "bool" if name in ("all", "any") else "num"
            node_out = Node(run, out_kind, need)
        if not lagged:
            self.evidence.append((self.segment(node), node_out.fn))
        return node_out

    # -- anything else is rejected by visit()


def compile_expression(text: str) -> Compiled:
    """Compile any expression (value, condition, column or sort key)."""
    if not isinstance(text, str) or not text.strip():
        raise FilterError("Expression is empty.")
    if len(text) > MAX_TEXT:
        raise FilterError(f"Expression is too long (limit {MAX_TEXT} characters).")
    source = normalise(text)
    try:
        tree = ast.parse(source.strip(), mode="eval")
    except (RecursionError, MemoryError, ValueError):
        raise FilterError("Expression is too deeply nested or contains invalid characters.") from None
    except SyntaxError as exc:
        spot = f" at character {exc.offset}" if exc.offset else ""
        raise FilterError(
            f"Syntax error{spot}: {exc.msg}. Check the parentheses; combine conditions with and / or / not (or && || !); quote text like 'خودرو'."
        ) from None
    source = source.strip()
    compiler = _Compiler(source)
    try:
        root = compiler.visit(tree.body)
    except RecursionError:
        raise FilterError("Expression is too deeply nested.") from None
    return Compiled(source, root.fn, root.kind, root.need, compiler.flows, frozenset(compiler.fields), compiler.evidence)


def compile_filter(text: str) -> Compiled:
    """Compile a row filter: the expression must be a condition."""
    compiled = compile_expression(text)
    if compiled.kind in ("num", "text"):
        hint = " Add a comparison, e.g. `volume > 1000000`." if compiled.kind == "num" else " Compare it, e.g. `industry == 'بانکها'`, or use has()."
        raise FilterError(f"A filter must be a condition (true/false), but `{compiled.text}` is a {'number' if compiled.kind == 'num' else 'text'}." + hint)
    return compiled


def passes(compiled: Compiled, ctx: Ctx) -> bool:
    return _truth(compiled.fn(ctx, 0)) is True


def tidy(value: Any) -> Any:
    """JSON-friendly cell: integral floats become ints, others keep 4 decimals."""
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return int(value) if value == int(value) and abs(value) < 1e15 else round(value, 4)
    return value


# --------------------------------------------------------------------------------------------- presets


@dataclass(frozen=True)
class Preset:
    name: str
    title: str
    title_fa: str
    filter: str
    sort: str
    descending: bool = True
    doc: str = ""


PRESETS: tuple[Preset, ...] = (
    Preset("buy_queue", "Buy queues", "صف خرید", "buy_queue", "bid_value",
           doc="Probable buy queues from the live snapshot. For exact queue sizes use top_movers(kind='buy_queue')."),
    Preset("sell_queue", "Sell queues", "صف فروش", "sell_queue", "ask_value", doc="Probable sell queues."),
    Preset("near_upper_limit", "Within 1% of the upper limit", "نزدیک سقف قیمت",
           "not at_upper_limit and to_upper_limit_pct <= 1 and volume > 0", "to_upper_limit_pct", False),
    Preset("volume_surge", "Volume above twice the 20-day average", "جهش حجم معاملات",
           "value > 5B and volume > 2 * avg(volume, 20)", "volume / avg(volume, 20)",
           doc="Mid-session the volume is still partial, so the ratio understates the final one."),
    Preset("real_money_inflow", "Real-person money coming in", "ورود پول حقیقی",
           "value > 10B and real_net_value > 0 and real_buyer_power > 1.2", "real_net_value",
           doc="real_net_value is estimated as net real volume x vwap."),
    Preset("real_money_outflow", "Real-person money leaving", "خروج پول حقیقی",
           "value > 10B and real_net_value < 0 and real_buyer_power < 0.8", "real_net_value", False),
    Preset("smart_money", "Real buyers bigger than sellers on rising volume", "قدرت خریدار حقیقی همراه با حجم",
           "value > 10B and real_buyer_power > 1.5 and real_net_value > 0 and volume > avg(volume, 20)", "real_buyer_power"),
    Preset("breakout_20d", "Closing above the 20-day high", "شکست سقف ۲۰ روزه",
           "close > highest(high, 20) and volume > avg(volume, 20)", "pct(close, highest(high, 20))",
           doc="History is adjusted for capital increases and dividends."),
    Preset("breakdown_20d", "Closing below the 20-day low", "شکست کف ۲۰ روزه",
           "close < lowest(low, 20) and volume > avg(volume, 20)", "pct(close, lowest(low, 20))", False),
    Preset("three_green_days", "Three rising closes in a row (today included)", "سه روز صعودی متوالی",
           "close_pct > 0 and all(close_pct > 0, 2)", "value"),
    Preset("oversold_bounce", "Green day after three red days", "بازگشت پس از سه روز نزولی",
           "close_pct > 1 and all(close_pct < 0, 3)", "close_pct"),
    Preset("gap_up", "Opened more than 2% above the reference price and held", "گپ صعودی",
           "gap_pct > 2 and close >= open and value > 2B", "gap_pct"),
    Preset("strong_close", "Up more than 3% and closing at the day's high", "بسته‌شدن در سقف روز",
           "close_pct > 3 and from_high_pct > -0.5 and value > 5B", "close_pct"),
    Preset("cheap_with_value", "Low P/E with real liquidity", "P/E پایین با نقدشوندگی",
           "pe > 0 and pe < 5 and value > 5B", "pe", False),
    Preset("unusual_trade_count", "Trade count above twice the 20-day average", "جهش تعداد معاملات",
           "trades > 2 * avg(trades, 20) and value > 5B", "trades / avg(trades, 20)"),
)
_PRESET = {p.name: p for p in PRESETS}


def preset(name: str) -> Preset:
    found = _PRESET.get(name.strip().casefold().replace("-", "_"))
    if found is None:
        close = difflib.get_close_matches(name.casefold(), list(_PRESET), n=3, cutoff=0.4)
        raise FilterError(f"Unknown preset '{name}'." + (f" Did you mean {', '.join(close)}?" if close else f" Presets: {', '.join(_PRESET)}"))
    return found


# --------------------------------------------------------------------------------------- reference

SYNTAX = (
    "Conditions: comparisons (< <= > >= == !=), combine with and / or / not (also && || !), parentheses.",
    "Arithmetic: + - * / %  (no powers). Numbers accept suffixes k, m, b, t: 5B = 5 billion rial. Persian digits work.",
    "Text: quote it, 'بانکها'. Letter variants (ی/ي, ک/ك) are equal. has(industry, 'خودرو'), industry in ('بانکها', 'بیمه').",
    "History: close[1] is yesterday's close; avg(volume, 20) averages the 20 trading days before today; count(close_pct > 0, 5) counts rising days.",
    "Inside aggregates every field means 'that day': count(close > open, 3) counts days whose close was above their own open.",
    "Missing data makes a comparison unknown (not true), so a row with no history never matches a history condition.",
    "A past day on which the symbol did not trade counts as zero volume/value/trades (prices unknown); days before its listing are unknown.",
    "Prices are rial. History is adjusted for capital increases/dividends so close[5] is comparable with close.",
)

EXAMPLES = (
    ("Volume surge on a rising day", "volume > 2 * avg(volume, 20) and close_pct > 1"),
    ("Yesterday rose, today opens with a gap up", "close_pct[1] > 0 and gap_pct > 1.5"),
    ("Three red days then a green one", "close_pct > 0 and all(close_pct < 0, 3)"),
    ("Real-person buyers dominating", "real_buyer_power > 2 and real_net_value > 5B and value > 10B"),
    ("Breakout above the 20-day high on volume", "close > highest(high, 20) and volume > avg(volume, 20)"),
    ("Cheap banks with liquidity", "has(industry, 'بانک') and pe > 0 and pe < 6 and value > 3B"),
    ("Up 10% in 5 sessions", "pct(close, close[5]) > 10"),
)


def reference(topic: str = "overview") -> dict[str, Any]:
    """Self-documentation for agents. ``overview`` is compact; ``fields`` carries full detail; ``all`` everything."""
    topic = (topic or "overview").strip().casefold()
    if topic not in ("overview", "all", "fields", "functions", "presets", "syntax", "examples"):
        raise FilterError("topic must be one of: overview, fields, functions, presets, syntax, examples, all")
    full, brief = topic == "all", topic == "overview"
    out: dict[str, Any] = {}
    if full or brief or topic == "syntax":
        out["syntax"] = list(SYNTAX)
    if brief:
        out["fields"] = {f.name: f"{f.unit} | {f.label}" + (" | history" if f.history else "") for f in FIELDS}
        out["field_note"] = "'history' fields also work as name[k] and inside avg/sum/highest/lowest/stdev/count/all/any/ago. Use topic='fields' for meanings and aliases."
    if full or topic == "fields":
        out["fields"] = [
            {"name": f.name, "label_fa": f.label, "unit": f.unit, "type": f.kind, "history": f.history,
             **({"aliases": list(f.aliases)} if f.aliases else {}), "meaning": f.doc}
            for f in FIELDS
        ]
        out["history_fields"] = list(HISTORY_FIELDS)
    if full or brief or topic == "functions":
        out["functions"] = FUNCTION_DOCS
        out["limits"] = {"max_history_days": MAX_LOOKBACK, "max_expression_chars": MAX_TEXT}
    if full or topic == "presets":
        out["presets"] = [
            {"name": p.name, "title": p.title, "title_fa": p.title_fa, "filter": p.filter, "default_sort": p.sort, **({"note": p.doc} if p.doc else {})}
            for p in PRESETS
        ]
    elif brief:
        out["presets"] = {p.name: p.title for p in PRESETS}
        out["preset_note"] = "screen_stocks(preset=name); topic='presets' shows each preset's filter."
    if full or brief or topic == "examples":
        out["examples"] = [{"goal": goal, "filter": expr} for goal, expr in EXAMPLES]
    return out
