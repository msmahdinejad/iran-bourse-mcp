"""Trading status: which symbols are suspended, under supervision, or just changed state.

Sources (all on cdn.tsetmc.com/api, plus one optional gateway feed):

* ``Supervision/GetSupervisionListBySourceID/{source}/{listType}`` -> ``supervision``. ``source`` 1 = Bourse,
  2 = Fara Bourse. ``listType`` is the exchange's own supervision status, named like its site does
  (tsetmc.com "ناظر" tabs): **1 مشمول فرآیند تعلیق** (subject to the suspension process: still trading, duties overdue),
  **2 معامله تحت احتیاط** (trading under caution) and **3 تعلیق شده** (suspended). Each row carries the symbol and the
  reasons as HTML (``<br>`` separated Persian lines); the list rows have no date. ``listType`` 0 returns every
  supervised symbol with empty reasons (344 on the Bourse) and is not used here.
* ``Supervision/GetSupervisionByInsCode/{ins}`` -> one symbol's status, reasons and ``insertionDateTime`` (the
  date it was set); empty strings for a symbol that is not supervised.
* ``MarketData/GetInstrumentStateTop/{n}`` -> ``instrumentState``: the market-wide change log of the order-entry /
  matching state (the newest ``n`` records, all markets, in no strict order).
* ``MarketData/GetInstrumentStateAll/{insCode}`` -> ``instrumentState``: one symbol's whole state history
  (newest first; Foolad has 747 records since 2008).
* webgw ``Instrument/CompanyState/fa`` (``TseApi.company_states``), optional: Bourse companies on list 1 and 3 with
  ``lastdatechange`` (Jalali), the only bulk source of *since when*. It is slow and sometimes empty; ``since`` is
  ``None`` without it.

State codes (``cEtaval``) are two-part: A = orders allowed (مجاز), I = forbidden (ممنوع); then R = reserved (محفوظ),
S = stopped (متوقف), G = blocked (مسدود) or nothing. A normal day runs IS/I -> IR -> AR -> A -> I/IS; a symbol that
re-opens after a trading stop shows IR -> AR -> A about 30 minutes later. The exchange publishes only the Persian
titles; the plain-English meanings below are our reading of those words and of the live logs.

The functions are pure; ``plan_trading_status`` says what to download, the ``shape_*`` functions turn it into output.
Problems raise ``ValueError`` with advice an agent can act on.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from html import unescape
from typing import Any

from .dates import DateError, fmt_date, fmt_time, jdate, parse_date
from .shape import _i
from .text import clean, match_key

KINDS = ("suspended", "supervision", "state_changes", "symbol_history")
SOURCES = {"bourse": 1, "fara": 2, "fara-bourse": 2, "ifb": 2}
SOURCE_TITLES = {1: "بورس", 2: "فرابورس"}
MAX_LIMIT = 300
STATE_LOG_MIN = 200  # records fetched for the market-wide log, whatever the limit

# supervision list type -> (status key, Persian title as tsetmc.com words it, English meaning)
SUPERVISION_LISTS: dict[int, tuple[str, str, str]] = {
    1: ("subject_to_suspension", "مشمول فرآیند تعلیق",
        "Suspension process started: the symbol still trades, but the disclosure duties listed in `reasons` are overdue and the exchange will suspend it if they stay unmet."),
    2: ("cautionary", "معامله تحت احتیاط",
        "Trading under caution: a warning flag. The symbol is tradable; read `reasons` before relying on its price."),
    3: ("suspended", "تعلیق شده",
        "Suspended: trading is halted until the reasons are resolved. These symbols are normally missing from the live market-watch feed."),
}
KIND_LISTS = {"suspended": (3,), "supervision": (1, 2)}


@dataclass(frozen=True)
class StateInfo:
    title: str
    orders: bool  # new orders are accepted
    matching: bool  # orders are matched, i.e. trading happens
    category: str  # open | reserved | stopped | blocked | closed
    meaning: str


STATE_CODES: dict[str, StateInfo] = {
    "A": StateInfo("مجاز", True, True, "open", "Open: orders are accepted and matched (normal trading)."),
    "AR": StateInfo("مجاز-محفوظ", True, False, "reserved", "Reserved: orders are accepted and kept but not matched yet (pre-open, or the auction before a re-opening)."),
    "AS": StateInfo("مجاز-متوقف", True, False, "stopped", "Stopped: trading is halted but orders can still be entered."),
    "AG": StateInfo("مجاز-مسدود", True, False, "blocked", "Blocked: orders allowed but the symbol is blocked from matching (rare)."),
    "I": StateInfo("ممنوع", False, False, "closed", "Closed: no order entry (before the pre-open and after the close)."),
    "IR": StateInfo("ممنوع-محفوظ", False, False, "reserved", "Reserved, orders not yet accepted: the step just before AR when a symbol (re)opens."),
    "IS": StateInfo("ممنوع-متوقف", False, False, "stopped", "Stopped and closed to orders: a halted symbol, and also the normal state of every symbol after the close."),
}


def state_info(code: str | None, title: str | None = None) -> StateInfo:
    key = (code or "").strip().upper()
    return STATE_CODES.get(key) or StateInfo(clean(title) or key or "?", False, False, "unknown", f"Unrecognised state code '{key}'.")


# ------------------------------------------------------------------------------------------------ plan


@dataclass(frozen=True)
class StatusPlan:
    """What to download for one ``trading_status`` call."""

    kind: str
    supervision_lists: tuple[tuple[int, int], ...]  # (source, listType) pairs for GetSupervisionListBySourceID
    state_top: int | None  # n for GetInstrumentStateTop
    symbol: str | None
    limit: int


def parse_sources(market: str | int | None) -> tuple[int, ...]:
    if market is None or (isinstance(market, str) and market.strip().casefold() in ("", "both", "all", "any")):
        return (1, 2)
    if isinstance(market, int) and not isinstance(market, bool) and market in SOURCE_TITLES:
        return (market,)
    found = SOURCES.get(str(market).strip().casefold())
    if found is None:
        raise ValueError(f"market '{market}' is not recognised. Use 'bourse', 'fara' or omit it for both.")
    return (found,)


def plan_trading_status(kind: str, market: str | int | None = None, symbol: str | None = None, limit: int = 50) -> StatusPlan:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be a whole number between 1 and {MAX_LIMIT}.")
    symbol = (symbol or "").strip() or None
    sources = parse_sources(market)
    if kind == "symbol_history":
        if symbol is None:
            raise ValueError("symbol is required for kind='symbol_history' (e.g. symbol='فولاد').")
        return StatusPlan(kind, (), None, symbol, limit)
    if kind == "state_changes":
        if symbol is not None:
            raise ValueError("state_changes is the market-wide log and cannot be filtered by symbol; use kind='symbol_history' for one symbol.")
        return StatusPlan(kind, (), max(limit, STATE_LOG_MIN), None, limit)
    return StatusPlan(kind, tuple((s, t) for s in sources for t in KIND_LISTS[kind]), None, symbol, limit)


# ------------------------------------------------------------------------------------------------ text

_TAGS = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)


def split_reasons(html: str | None) -> list[str]:
    """The exchange's reasons are Persian lines joined by ``<br>``: plain, normalised, de-duplicated lines."""
    text = unescape(_TAGS.sub(" ", _BREAK.sub("\n", html or "")))
    lines: list[str] = []
    for part in text.splitlines():
        line = clean(part)
        if line and line not in lines:
            lines.append(line)
    return lines


def _day(deven: Any) -> int | None:
    number = _i(deven)
    return number if number and 19000101 <= number <= 29991231 else None


def _since_from_jalali(text: str | None) -> int | None:
    try:
        return parse_date(text) if text and str(text).strip() else None
    except DateError:
        return None


def _since_from_iso(text: str | None) -> int | None:
    """'2026-10-05T15:23:47.637' -> 20261005; the exchange's 0001-01-01 placeholder -> None."""
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", text or "")
    if not match:
        return None
    return _day(int(match.group(1)) * 10000 + int(match.group(2)) * 100 + int(match.group(3)))


def _company_since(company_states: list[dict] | None) -> dict[str, int]:
    """webgw rows -> {symbol key: date of the last status change}; the symbol is the text before '(' in `nam`."""
    out: dict[str, int] = {}
    for row in company_states or []:
        name = clean(row.get("nam")) or ""
        symbol = clean(row.get("kodenamaddarsamane")) or name.split("(")[0].strip()
        since = _since_from_jalali(row.get("lastdatechange"))
        if symbol and since:
            out[match_key(symbol)] = since
    return out


# ----------------------------------------------------------------------------------------------- shaping


def shape_supervision(
    lists: Mapping[tuple[int, int], list[dict]],
    *,
    kind: str,
    symbol: str | None = None,
    limit: int = 50,
    company_states: list[dict] | None = None,
) -> dict:
    """``lists`` maps (source, listType) to the raw rows of that list (as ``plan_trading_status`` asked for them)."""
    since_by_symbol = _company_since(company_states)
    wanted = match_key(symbol) if symbol else None
    rows: list[dict[str, Any]] = []
    totals: Counter[tuple[str, str]] = Counter()
    for (source, list_type), raw_rows in sorted(lists.items()):
        status, title, _ = SUPERVISION_LISTS[list_type]
        for raw in raw_rows or []:
            ins = raw.get("instrument") or {}
            name = clean(ins.get("lVal18AFC"))
            if wanted and match_key(name) != wanted:
                continue
            totals[(SOURCE_TITLES[source], status)] += 1
            since = _since_from_iso(raw.get("insertionDateTime")) or (since_by_symbol.get(match_key(name)) if source == 1 else None)
            rows.append({
                "symbol": name, "name": clean(ins.get("lVal30")), "ins_code": str(raw.get("insCode") or ins.get("insCode") or "") or None,
                "market": SOURCE_TITLES[source], "status": status, "status_title": title,
                "since": fmt_date(since), "since_jdate": jdate(since),
                "reasons": split_reasons(raw.get("reasons")), "extra": clean(raw.get("additionalInfo")) or None,
            })
    rows.sort(key=lambda r: r["symbol"] or "")
    rows.sort(key=lambda r: r["since"] or "", reverse=True)  # newest status change first, undated ones last, A-Z within a day
    summary: dict[str, dict[str, int]] = {}
    for (market_title, status), count in totals.items():
        summary.setdefault(market_title, {})[status] = count
    used = sorted({lt for _, lt in lists})
    notes: list[str] = []
    if not any(r["since"] for r in rows) and rows:
        notes.append("`since` is empty: the list rows carry no date. Call symbol_history for one symbol to get the date its status was set.")
    if wanted and not rows:
        notes.append(f"'{symbol}' is not on the {kind} list" + (" of this market." if len(lists) == 1 else "s."))
    if not rows and not wanted:
        notes.append("No symbols on this list right now.")
    out: dict[str, Any] = {
        "kind": kind,
        "meaning": {SUPERVISION_LISTS[lt][0]: SUPERVISION_LISTS[lt][2] for lt in used},
        "total": len(rows),
        "count": min(limit, len(rows)),
        "summary": summary,
        "rows": rows[:limit],
    }
    if len(rows) > limit:
        notes.append(f"{len(rows) - limit} more rows; raise limit to see them.")
    if notes:
        out["notes"] = notes
    return out


def _state_row(raw: dict, *, with_symbol: bool) -> dict[str, Any]:
    code = (raw.get("cEtaval") or "").strip().upper()
    info = state_info(code, raw.get("cEtavalTitle"))
    row: dict[str, Any] = {}
    if with_symbol:
        row.update(symbol=clean(raw.get("lVal18AFC")), name=clean(raw.get("lVal30")), ins_code=str(raw.get("insCode") or "") or None)
    deven = _day(raw.get("dEven"))
    row.update(
        date=fmt_date(deven), jdate=jdate(deven), time=fmt_time(_i(raw.get("hEven"))) if raw.get("hEven") is not None else None,
        state=code, state_title=clean(raw.get("cEtavalTitle")) or info.title, category=info.category,
        orders_accepted=info.orders, trading=info.matching,
    )
    return row


def _newest_first(rows: list[dict]) -> list[dict]:
    """Stable sort by date and time, newest first. Records of one second keep the order the exchange sent them."""
    return sorted(rows, key=lambda r: (_i(r.get("dEven")) or 0, _i(r.get("hEven")) or 0), reverse=True)


def _decode(codes: set[str]) -> dict[str, str]:
    return {c: f"{state_info(c).title}: {state_info(c).meaning}" for c in sorted(codes)}


def shape_state_changes(rows: list[dict] | None, *, limit: int = 50) -> dict:
    """The market-wide log of order-entry state changes (newest first) with a count of every state seen."""
    ordered = _newest_first([r for r in rows or [] if isinstance(r, dict)])
    shaped = [_state_row(r, with_symbol=True) for r in ordered[:limit]]
    seen = Counter((r.get("cEtaval") or "").strip().upper() for r in ordered)
    symbols = {r.get("insCode") for r in ordered}
    latest: dict[Any, str] = {}
    for r in reversed(ordered):  # oldest to newest, so the last write wins
        latest[r.get("insCode")] = (r.get("cEtaval") or "").strip().upper()
    out: dict[str, Any] = {
        "kind": "state_changes", "records_read": len(ordered), "symbols_in_sample": len(symbols), "count": len(shaped), "rows": shaped,
        "sample": {
            "from": fmt_date(_day(ordered[-1].get("dEven"))) if ordered else None, "to": fmt_date(_day(ordered[0].get("dEven"))) if ordered else None,
            "records_by_state": dict(seen.most_common()), "latest_state_by_symbol": dict(Counter(latest.values()).most_common()),
        },
        "state_codes": _decode(set(seen)),
        "notes": [
            "Market-wide for Bourse, Fara Bourse and derivatives together; the log has no market field.",
            "A symbol's state moves IS/I -> IR -> AR -> A each morning and back to I/IS at the close, so most records are routine. "
            "During the session a symbol whose latest state is AS or IS (stopped), or AR / IR long after 09:00 (reserved), is halted or waiting to re-open.",
        ],
    }
    if not shaped:
        out["notes"].append("The exchange returned no state records.")
    return out


def shape_symbol_history(
    rows: list[dict] | None,
    *,
    instrument: dict | None = None,
    supervision: dict | None = None,
    limit: int = 30,
) -> dict:
    """One symbol's state history (newest first) with its current state and, when given, its supervision record."""
    ordered = _newest_first([r for r in rows or [] if isinstance(r, dict)])
    shaped = [_state_row(r, with_symbol=False) for r in ordered[:limit]]
    seen = Counter((r.get("cEtaval") or "").strip().upper() for r in ordered)
    out: dict[str, Any] = {"kind": "symbol_history", "instrument": instrument}
    if ordered:
        current = _state_row(ordered[0], with_symbol=False)
        out["current"] = {**current, "meaning": state_info(current["state"]).meaning}
        out["first_record"] = fmt_date(_day(ordered[-1].get("dEven")))
    out.update(records=len(ordered), count=len(shaped), history=shaped, records_by_state=dict(seen.most_common()), state_codes=_decode(set(seen)))
    sup = shape_supervision_record(supervision)
    if sup is not None:
        out["supervision"] = sup
    notes = ["Several records can share one second; they are listed in the order the exchange sent them."]
    if not ordered:
        notes.append("The exchange has no state records for this symbol.")
    out["notes"] = notes
    return out


def shape_supervision_record(raw: dict | None) -> dict | None:
    """``GetSupervisionByInsCode`` -> status, reasons and date; ``None`` when the payload is missing, ``status: none`` when clean."""
    if not isinstance(raw, dict):
        return None
    code = _i(raw.get("underSupervision")) or 0
    reasons = split_reasons(raw.get("reasons"))
    if code not in SUPERVISION_LISTS:
        return {"status": "none", "status_title": None, "reasons": reasons, "since": None, "since_jdate": None}
    status, title, meaning = SUPERVISION_LISTS[code]
    since = _since_from_iso(raw.get("insertionDateTime"))
    return {"status": status, "status_title": clean(raw.get("underSupervisionTitle")) or title, "meaning": meaning,
            "reasons": reasons, "since": fmt_date(since), "since_jdate": jdate(since)}
