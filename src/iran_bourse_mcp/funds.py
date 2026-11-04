"""Investment-fund universe and ranking (صندوق‌های سرمایه‌گذاری) from the exchange's own fund registry.

Pure shaping code over ``Fund/GetFunds/{type}`` rows the service has already fetched; nothing here touches the network.

The registry covers every fund licensed in Iran (about 580 under 15 type ids), not only the exchange-traded ones, with
NAV, size, returns and portfolio mix as the Securities and Exchange Organization publishes them. Two things to know:

* It carries no trading symbol or insCode. To find the exchange-traded unit of a fund, search the name with
  ``search_symbol`` and compare the unit's NAV (``etf_nav``) with ``nav_redemption`` when ``nav_date`` is today.
  Names are not matched automatically: the registry's names and the market's abbreviations do not map one to one.
* ``fixIncome`` in each upstream row repeats the type id the list was requested with (the field called ``fundType`` is
  always 0), and ``name`` is null: the display name is ``mfName`` without the words 'صندوق سرمایه‌گذاری'.

Everything in a row is as published by the exchange except ``age_days``, ``stale`` and the summary totals. Amounts are rial,
returns are percent (not annualised unless the horizon is a year).
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .dates import from_date, jdate
from .shape import _f, _i
from .text import ascii_digits, clean, match_key

MAX_ROWS = 300
DEFAULT_LIMIT = 25
STALE_DAYS = 7  # a NAV this much older than the newest NAV in the registry is flagged

# id -> key, short Persian name, official name (fipiran's list; the id equality with Fund/GetFunds was checked against the
# fund names in each list), English words
FUND_TYPES: dict[int, dict[str, Any]] = {
    4: {"key": "fixed_income", "fa": "درآمد ثابت", "official": "در اوراق بهادار با درآمد ثابت", "en": ("fixed_income", "bond", "bonds", "debt", "income")},
    5: {"key": "gold_commodity", "fa": "کالایی", "official": "در اوراق بهادار مبتنی بر سپرده کالایی", "en": ("gold_commodity", "gold", "commodity", "commodities")},
    6: {"key": "equity_general", "fa": "در سهام", "official": "در سهام", "en": ("equity_general", "plain_equity", "general_equity")},
    7: {"key": "mixed", "fa": "مختلط", "official": "مختلط", "en": ("mixed", "balanced")},
    11: {"key": "market_maker", "fa": "اختصاصی بازارگردانی", "official": "اختصاصی بازارگردانی", "en": ("market_maker", "market_making", "marketmaker")},
    12: {"key": "venture", "fa": "جسورانه", "official": "جسورانه", "en": ("venture", "vc")},
    13: {"key": "project", "fa": "پروژه‌ای", "official": "پروژه‌ای", "en": ("project",)},
    16: {"key": "private", "fa": "خصوصی", "official": "خصوصی", "en": ("private",)},
    17: {"key": "fund_of_funds", "fa": "صندوق در صندوق", "official": "صندوق در صندوق", "en": ("fund_of_funds", "fof")},
    18: {"key": "real_estate", "fa": "املاک و مستغلات", "official": "املاک و مستغلات", "en": ("real_estate", "property", "realestate")},
    21: {"key": "sector_equity", "fa": "سهام بخشی", "official": "در سهام-بخشی", "en": ("sector_equity", "sector", "sectoral")},
    22: {"key": "leveraged_equity", "fa": "سهامی اهرمی", "official": "در سهام-سهامی اهرمی", "en": ("leveraged_equity", "leveraged")},
    23: {"key": "index_equity", "fa": "سهام شاخصی", "official": "در سهام-شاخصی", "en": ("index_equity", "index", "indexed")},
    24: {"key": "principal_protected", "fa": "با تضمین اصل سرمایه", "official": "با تضمین اصل مبلغ سرمایه گذاری", "en": ("principal_protected", "guaranteed", "capital_protected")},
    25: {"key": "supplementary_pension", "fa": "بازنشستگی تکمیلی", "official": "بازنشستگی تکمیلی", "en": ("supplementary_pension", "pension", "retirement")},
}
FETCH_TYPES = tuple(FUND_TYPES)  # every id that holds funds today; 0 and 1 answer HTTP 500, 2, 3, 8-10, 14, 15, 19, 20 are empty
EMPTY_TYPES = {14: "زمین و ساختمان (land and building)", 19: "لغو مجوز تاسیس و فعالیت (licence withdrawn)"}
EQUITY_IDS = (6, 21, 22, 23)
GROUPS = {"equity": EQUITY_IDS, "equities": EQUITY_IDS, "stock": EQUITY_IDS, "stocks": EQUITY_IDS, "allequity": EQUITY_IDS, "سهام": EQUITY_IDS}
_ALL_WORDS = {"", "all", "*", "همه", "allfunds", "everything"}
_NOISE = re.compile(r"[\s_\-./،,]+")

RETURN_FIELDS = (
    ("1d", "day1Return", 1), ("1w", "day7Return", 7), ("1m", "day30Return", 30), ("3m", "day90Return", 90),
    ("6m", "day180Return", 180), ("1y", "day365Return", 365), ("since_inception", "dayFirstReturn", None),
)
SORT_KEYS = (
    "return_1d", "return_1w", "return_1m", "return_3m", "return_6m", "return_1y", "return_since_inception", "net_assets", "units", "nav", "age",
)
_SORT_ALIASES = {
    "1d": "return_1d", "day": "return_1d", "daily": "return_1d", "1w": "return_1w", "week": "return_1w", "weekly": "return_1w", "7d": "return_1w",
    "1m": "return_1m", "month": "return_1m", "monthly": "return_1m", "30d": "return_1m", "3m": "return_3m", "quarter": "return_3m",
    "quarterly": "return_3m", "90d": "return_3m", "6m": "return_6m", "180d": "return_6m", "1y": "return_1y", "year": "return_1y",
    "annual": "return_1y", "365d": "return_1y", "since_inception": "return_since_inception", "inception": "return_since_inception",
    "total_return": "return_since_inception", "size": "net_assets", "aum": "net_assets", "assets": "net_assets", "nav_redemption": "nav",
    "initiation": "age", "oldest": "age",
}


def _norm(value: object) -> str:
    return _NOISE.sub("", match_key(value)).casefold()


def type_catalogue() -> list[dict]:
    """The type ids that hold funds, with their keys and Persian names (what the tool description lists)."""
    return [{"id": i, "key": t["key"], "name": t["fa"], "official_name": t["official"]} for i, t in FUND_TYPES.items()]


def _type_label(type_id: int) -> dict:
    info = FUND_TYPES.get(type_id, {})
    return {"id": type_id, "key": info.get("key"), "name": info.get("fa")}


def resolve_fund_types(fund_type: str | int | None) -> list[int]:
    """Type ids to request for a ``fund_type`` argument: None/'all' -> every type; names, ids or comma-separated lists.

    English words (``fixed_income``, ``gold``, ``equity``...), Persian names or fragments (``درآمد ثابت``, ``بخشی``) and
    numeric ids are accepted. ``equity``/``سهام`` mean every stock fund (types 6, 21, 22, 23); ``در سهام`` is only type 6.
    """
    if fund_type is None:
        return list(FETCH_TYPES)
    wanted: set[int] = set()
    parts = [p for p in re.split(r"[,،]", str(fund_type)) if p.strip()] or [""]
    for part in parts:
        key = _norm(part)
        digits = ascii_digits(part).strip()
        if key in _ALL_WORDS:
            return list(FETCH_TYPES)
        if digits.isdigit():
            number = int(digits)
            if number in FUND_TYPES:
                wanted.add(number)
                continue
            if number in EMPTY_TYPES:
                raise ValueError(f"fund type {number} ({EMPTY_TYPES[number]}) has no funds on the exchange. Valid ids: {', '.join(map(str, FETCH_TYPES))}.")
            raise ValueError(f"unknown fund type id {number}. Valid ids: {', '.join(map(str, FETCH_TYPES))}.")
        if key in GROUPS:
            wanted.update(GROUPS[key])
            continue
        exact = [i for i, t in FUND_TYPES.items() if key in {_norm(w) for w in (*t["en"], t["key"], t["fa"], t["official"])}]
        if exact:
            wanted.update(exact)
            continue
        fuzzy = [i for i, t in FUND_TYPES.items() if len(key) >= 2 and any(key in _norm(w) for w in (t["fa"], t["official"]))]
        if not fuzzy:
            names = "; ".join(f"{t['key']} ({t['fa']})" for t in FUND_TYPES.values())
            raise ValueError(f"fund_type '{part.strip()}' is not recognised. Use one of: {names}; 'equity' for all stock funds; or omit for every type.")
        wanted.update(fuzzy)
    return [i for i in FETCH_TYPES if i in wanted]


def resolve_sort(sort_by: str | None) -> str:
    key = re.sub(r"[\s\-]+", "_", str(sort_by or "return_1y").strip().casefold())
    key = _SORT_ALIASES.get(key, key)
    if key not in SORT_KEYS:
        raise ValueError(f"sort_by must be one of {', '.join(SORT_KEYS)} (aliases: 1y, 1m, 3m, size, week, inception).")
    return key


# --------------------------------------------------------------------------------------- rows


def _date(value: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _pos(value: Any) -> float | None:
    number = _f(value)
    return number if number else None


def _name(raw: dict) -> str | None:
    text = clean(raw.get("mfName") or raw.get("name")) or ""
    return text.lstrip("> ").strip() or None


def _returns(raw: dict, age: int | None) -> dict[str, float | None]:
    """Published percent returns. 0.0 over a week or more is how the registry says 'not available' (young fund), so it is null."""
    out: dict[str, float | None] = {}
    for label, field, window in RETURN_FIELDS:
        value = _f(raw.get(field))
        unreached = value == 0 and (window is None or window > 1 or (age is not None and age < 1))
        out[label] = None if value is None or unreached else value
    return out


def shape_fund(raw: dict, type_id: int | None = None, *, detail: str = "compact") -> dict:
    """One registry row. ``compact`` is the screening view; ``full`` adds custodian, guarantor, website and the zero-filled optional fields."""
    kind = type_id if type_id in FUND_TYPES else _i(raw.get("fixIncome"))
    record, start = _date(raw.get("recordDate")), _date(raw.get("initiationDate"))
    age = (record - start).days if record and start and record >= start else None
    mix = {
        "stock": _f(raw.get("portfolioStock")), "bond": _f(raw.get("portfolioBond")), "deposit": _f(raw.get("portfolioDeposit")),
        "cash": _f(raw.get("portfolioCash")), "other": _f(raw.get("portfolioOther")),
    }
    kind_info = FUND_TYPES.get(kind or -1) or {}
    row: dict[str, Any] = {
        "reg_no": _i(raw.get("regNo")), "name": _name(raw), "type": kind_info.get("key"),
        "nav_date": record.isoformat() if record else None,
        "net_assets": _i(_pos(raw.get("netAsset"))), "units": _i(_pos(raw.get("units"))),
        "nav_redemption": _pos(raw.get("navRed")), "nav_issue": _pos(raw.get("navSub")), "nav_statistical": _pos(raw.get("navStat")),
        "returns_pct": _returns(raw, age),
        "portfolio_pct": mix if any(mix.values()) else None,
        "manager": clean(raw.get("manager")) or clean(raw.get("investmentManager")),
        "age_days": age,
    }
    if detail != "full" and mix["cash"] == mix["deposit"]:
        mix.pop("cash")  # repeats deposit for nearly every fund
    investors = {
        "retail_pct": _pos(raw.get("retInvPercent")), "institutional_pct": _pos(raw.get("insInvPercent")),
        "retail_count": _i(_pos(raw.get("retInvNo"))), "institutional_count": _i(_pos(raw.get("insInvNo"))),
    }
    extras = {
        "investors": investors if any(investors.values()) else None,
        "estimated_yield_pct": _pos(raw.get("estimatedEarningRate")), "guaranteed_yield_pct": _pos(raw.get("guaranteedEarningRate")),
        "market_maker": clean(raw.get("marketMaker")),
    }
    if detail == "full":
        row.update(extras)
        row.update(
            type_name=kind_info.get("fa"), jdate=jdate(from_date(record)) if record else None, top5_holdings_pct=_f(raw.get("portfolioFiveBest")), initiation_date=start.isoformat() if start else None,
            custodian=clean(raw.get("custodian")), guarantor=None if clean(raw.get("guarantor")) in (None, "", "----") else clean(raw.get("guarantor")),
            investment_manager=clean(raw.get("investmentManager")), website=clean(raw.get("webSite")) or None,
        )
    else:
        row.update({k: v for k, v in extras.items() if v})
    return row


def _sort_value(row: dict, key: str) -> float | None:
    if key.startswith("return_"):
        return row["returns_pct"].get(key[len("return_"):])
    return {"net_assets": row["net_assets"], "units": row["units"], "nav": row["nav_redemption"], "age": row["age_days"]}[key]


def shape_fund_ranking(
    funds_by_type: Mapping[int, Sequence[dict] | None],
    *,
    sort_by: str = "return_1y",
    descending: bool = True,
    min_net_assets: float | None = None,
    limit: int | None = DEFAULT_LIMIT,
    detail: str = "compact",
) -> dict:
    """Rank the fund registry. ``funds_by_type`` maps a type id to that type's raw ``funds`` rows.

    Sorting is on a published number (a return, size, NAV) or on ``age`` (derived); funds without the number go last in
    either direction. ``min_net_assets`` is rial and drops funds below it or with no net-asset figure. A fund listed
    under two types is kept once.
    """
    key = resolve_sort(sort_by)
    if detail not in ("compact", "full"):
        raise ValueError("detail must be 'compact' or 'full'.")
    if min_net_assets is not None:
        try:
            threshold = float(min_net_assets)
        except (TypeError, ValueError) as exc:
            raise ValueError("min_net_assets must be a number in rial (1 toman = 10 rial).") from exc
        if threshold < 0:
            raise ValueError("min_net_assets cannot be negative.")
    else:
        threshold = None
    try:
        cap = max(1, min(int(limit if limit is not None else DEFAULT_LIMIT), MAX_ROWS))
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be a whole number") from exc

    seen: set[int] = set()
    universe: list[dict] = []
    per_type: dict[int, int] = {}
    for type_id, rows in funds_by_type.items():
        per_type[type_id] = 0
        for raw in rows or []:
            row = shape_fund(raw, type_id, detail=detail)
            if row["reg_no"] in seen:
                continue
            seen.add(row["reg_no"])
            per_type[type_id] += 1
            universe.append(row)
    dates = [r["nav_date"] for r in universe if r["nav_date"]]
    latest = max(dates) if dates else None
    cutoff = (dt.date.fromisoformat(latest) - dt.timedelta(days=STALE_DAYS)).isoformat() if latest else None
    for r in universe:
        if cutoff and r["nav_date"] and r["nav_date"] < cutoff:
            r["stale"] = True
    matched = [r for r in universe if threshold is None or (r["net_assets"] or 0) >= threshold]
    ranked = [r for r in matched if _sort_value(r, key) is not None]
    ranked.sort(key=lambda r: (_sort_value(r, key), r["net_assets"] or 0), reverse=descending)
    ordered = ranked + [r for r in matched if _sort_value(r, key) is None]
    matched_per_type = {t: sum(1 for r in matched if r["type"] == (FUND_TYPES.get(t) or {}).get("key")) for t in per_type}
    notes = [
        "Published by the exchange: net_assets, units, the three NAVs, returns_pct, portfolio_pct, manager. Derived here: age_days (NAV date minus start date), stale, and the summary totals.",
        "returns_pct is in percent and not annualised (1y is the trailing 365-day return, since_inception is cumulative); null means not published, "
        "including the registry's 0.0 for horizons a young fund has not reached. 1d is kept as published, so a 0.0 there can mean an unchanged NAV.",
        "Portfolio percentages are as published and need not add up to 100; cash is left out of the compact view when it equals deposit (almost every fund).",
        "NAV dates differ by fund (nav_date); stale marks a NAV more than a week older than the newest one. The registry has no trading symbol: "
        "search the fund's name with search_symbol, then compare etf_nav with nav_redemption.",
    ]
    if key == "return_since_inception" or key == "return_1y":
        notes.append("Market-maker (اختصاصی بازارگردانی) and very young funds show extreme returns; use min_net_assets or fund_type to filter.")
    return {
        "sorted_by": key, "descending": descending, "min_net_assets": threshold, "types": [{**_type_label(t), "funds": n, "matched": matched_per_type[t]} for t, n in per_type.items()],
        "universe": {
            "funds": len(universe), "matched": len(matched), "total_net_assets": sum(r["net_assets"] or 0 for r in matched),
            "latest_nav_date": latest, "stale_nav_funds": sum(1 for r in matched if r.get("stale")),
        },
        "returned": min(cap, len(ordered)), "funds": ordered[:cap],
        "units": "net_assets in rial, nav in rial per unit, returns and portfolio in percent",
        "note": " ".join(notes),
    }

