"""Market-wide corporate-action calendar: capital increases, price adjustments and rights symbols with dates.

Two public feeds of the exchange carry the events, both per market segment ("flow"):

* ``GET /Instrument/GetInstrumentShareChangeByFlow/{flow}/{top}`` -> ``instrumentShareChange``: every change of a
  symbol's share count since 2008, with the effective date (``dEven``) and the old and new count. ``top`` is
  ignored (the whole table, 500 to 2,400 rows, comes back). Dates can lie a few days in the *future*: the exchange
  writes the row when the registered change is scheduled, so the forward horizon is short (days, not months).
* ``GET /ClosingPrice/GetPriceAdjustByFlow/{flow}/{top}`` -> ``priceAdjust``: price adjustments (تعدیل قیمت) for
  ex-dividend / ex-rights days, newest first, ``top`` honoured. The unadjusted and adjusted closing prices give the
  adjustment factor. Rows exist only for past days. The top-level ``insCode`` is 0; the symbol sits in ``instrument``.

Flows: 1 Bourse, 2 Fara Bourse, 4 Fara Bourse base market (disjoint sets of symbols; derivatives and commodities have none).

What the feeds do **not** have: the dividend per share, the AGM / ex-dividend announcement, the rights exercise price
and subscription dates. Those are in Codal letters (``codal_filings`` with ``title_contains='تقسیم سود'`` or
``'افزایش سرمایه'``).

Two quirks of the share-count table are handled so an agent is not misled:

* On Bourse price-adjustment days the exchange temporarily puts the share count *back* to the old figure and restores
  the new one 1 to 8 days later (a pair of opposite rows, 200+ of them). These are bookkeeping, not capital reductions;
  they are folded into the matching price adjustment and counted as ``hidden_roundtrip_rows``.
* Rights instruments (symbols ending in ح) appear with 0 shares before or after their life; they are reported as
  ``rights_symbol`` events, not as capital changes.

The functions are pure: the caller fetches the raw rows and passes ``today`` (default: the Tehran date).
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from .dates import fmt_date, jdate, parse_date, tehran_now, to_date
from .shape import _f, _i, _r, pct_change
from .text import clean

FLOW_TITLES = {1: "بورس", 2: "فرابورس", 4: "فرابورس - بازار پایه"}
FLOW_WORDS = {"bourse": 1, "tse": 1, "fara": 2, "farabourse": 2, "ifb": 2, "base": 4, "farabase": 4, "farabasemarket": 4}
ALL_FLOWS = (1, 2, 4)

DIRECTIONS = ("upcoming", "recent", "all")
KINDS = ("capital_increase", "price_adjustment", "capital_decrease", "rights_symbol", "share_count_roundtrip", "all")
_ALL_KINDS = ("capital_increase", "capital_decrease", "price_adjustment", "rights_symbol")  # what kind='all' returns
MAX_DAYS = 366
MAX_LIMIT = 500
ROUNDTRIP_DAYS = 10  # a temporary reduction is restored within this many days (observed: 1 to 8)
ROUNDTRIP_TOLERANCE = 0.01
EXTREME_FACTOR = (0.1, 10.0)  # adjustment factors outside this look like data errors or unit changes

NOT_AVAILABLE = (
    "Not in this feed: dividend per share, ex-dividend and AGM dates, rights exercise price and subscription deadlines. "
    "They are published in Codal letters (codal_filings with title_contains 'تقسیم سود' or 'افزایش سرمایه')."
)
HORIZON_NOTE = (
    "Future dates exist only for share-count changes the exchange has already scheduled (typically a few days ahead); "
    "price adjustments are listed after the fact."
)


def parse_flows(flow: int | str | None) -> list[int]:
    """``1``, ``'bourse'``, ``'fara'``, ``'base'`` or ``'all'`` -> the flows to read."""
    if flow is None or (isinstance(flow, str) and not flow.strip()):
        return [1]
    if isinstance(flow, bool):
        raise ValueError("flow must be 1 (Bourse), 2 (Fara Bourse), 4 (Fara base market) or 'all'.")
    if isinstance(flow, int):
        found: int | None = flow
    else:
        text = str(flow).strip().casefold().replace("-", "").replace("_", "").replace(" ", "")
        if text == "all":
            return list(ALL_FLOWS)
        found = int(text) if text.isdigit() else FLOW_WORDS.get(text)
    if found not in ALL_FLOWS:
        raise ValueError(f"flow '{flow}' has no corporate-action data. Use 1 (Bourse), 2 (Fara Bourse), 4 (Fara base market) or 'all'.")
    return [found]


def sources_needed(kind: str, direction: str = "all") -> tuple[bool, bool]:
    """(share changes, price adjustments) the caller has to download; skip what is not needed.

    Share changes are always read: they also tell which price adjustments came with a temporary share-count
    reduction. Price adjustments only exist for past days, so ``upcoming`` never needs them.
    """
    _check_kind(kind)
    return True, kind in ("price_adjustment", "all") and direction != "upcoming"


def adjustment_fetch_size(days: int) -> int:
    """How many newest price adjustments to ask for to cover ``days`` back (peak season has ~8 a day)."""
    return max(100, min(5000, int(days) * 10))


def _check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}.")


def check_arguments(direction: str, kind: str, days: int, limit: int) -> None:
    """Reject bad arguments before anything is downloaded (``capital_calendar`` calls this too)."""
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {', '.join(DIRECTIONS)}.")
    _check_kind(kind)
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= MAX_DAYS:
        raise ValueError(f"days must be a whole number between 1 and {MAX_DAYS}.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be a whole number between 1 and {MAX_LIMIT}.")


def _as_date(today: dt.date | str | int | None) -> dt.date:
    if today is None:
        return tehran_now().date()
    if isinstance(today, dt.datetime):
        return today.date()
    if isinstance(today, dt.date):
        return today
    return to_date(parse_date(today))


def _by_flow(rows: Mapping[int, list[dict]] | list[dict] | None, flows: list[int], label: str) -> dict[int, list[dict]]:
    if rows is None:
        return {}
    if isinstance(rows, Mapping):
        return {int(f): list(r or []) for f, r in rows.items()}
    if len(flows) != 1:
        raise ValueError(f"{label} must be a {{flow: rows}} mapping when several flows are read.")
    return {flows[0]: list(rows)}


def _day(deven: Any) -> dt.date | None:
    number = _i(deven)
    if not number:
        return None
    try:
        return to_date(number)
    except ValueError:
        return None


def _ident(code: Any, symbol: Any, name: Any, flow: int) -> dict[str, Any]:
    return {"symbol": clean(symbol), "name": clean(name), "ins_code": str(code) if code else None, "market": FLOW_TITLES.get(flow), "flow": flow}


def _when(day: dt.date, today: dt.date) -> dict[str, Any]:
    delta = (day - today).days
    deven = day.year * 10000 + day.month * 100 + day.day
    return {"date": fmt_date(deven), "jdate": jdate(deven), "days_from_today": delta, "status": "upcoming" if delta > 0 else "today" if delta == 0 else "past"}


# ------------------------------------------------------------------------------------------ share counts


def _near(a: float, b: float) -> bool:
    return bool(b) and abs(a / b - 1) <= ROUNDTRIP_TOLERANCE


def _share_events(rows: list[dict], flow: int, today: dt.date) -> list[dict[str, Any]]:
    """Classify one flow's share-count rows; round-trip pairs are tagged, not dropped."""
    by_code: dict[str, list[tuple[dt.date, float, float, dict]]] = defaultdict(list)
    for raw in rows:
        day, old, new = _day(raw.get("dEven")), _f(raw.get("numberOfShareOld")), _f(raw.get("numberOfShareNew"))
        if day is None or old is None or new is None or old == new:
            continue
        by_code[str(raw.get("insCode"))].append((day, old, new, raw))
    events: list[dict[str, Any]] = []
    for items in by_code.values():
        items.sort(key=lambda it: it[0])
        role: dict[int, tuple[str, dt.date | None]] = {}
        for i, (day, old, new, _raw) in enumerate(items):
            if not (old > 0 and 0 < new < old):
                continue
            for j in range(i + 1, len(items)):
                later, later_old, later_new, _ = items[j]
                if (later - day).days > ROUNDTRIP_DAYS:
                    break
                if j not in role and later_new > later_old and _near(later_old, new) and _near(later_new, old):
                    role[i], role[j] = ("temporary_reduction", later), ("restoration", day)
                    break
        for i, (day, old, new, raw) in enumerate(items):
            event = {**_when(day, today), **_ident(raw.get("insCode"), raw.get("lVal18AFC"), raw.get("lVal30"), flow),
                     "shares_before": _i(old), "shares_after": _i(new)}
            if i in role:
                tag, other = role[i]
                event.update(kind="share_count_roundtrip", part=tag, partner_date=fmt_date(other.year * 10000 + other.month * 100 + other.day))
                event["label"] = (f"share count temporarily back to {_i(new):,} (restored {event['partner_date']})" if tag == "temporary_reduction"
                                  else f"share count restored to {_i(new):,} after the temporary reduction of {event['partner_date']}")
            elif old <= 0 or new <= 0:
                listed = old <= 0
                event.update(kind="rights_symbol", change="listed" if listed else "removed", rights_count=_i(new if listed else old))
                event["label"] = (f"rights instrument (حق تقدم) listed: {_i(new):,} rights" if listed else f"rights instrument (حق تقدم) removed, {_i(old):,} rights before")
            elif new > old:
                pct = pct_change(new, old)
                event.update(kind="capital_increase", added_shares=_i(new - old), increase_pct=pct, ratio=_r(new / old, 4))
                event["label"] = f"capital increase (افزایش سرمایه) +{pct}%: {_i(old):,} -> {_i(new):,} shares"
            else:
                pct = pct_change(new, old)
                event.update(kind="capital_decrease", removed_shares=_i(old - new), change_pct=pct, ratio=_r(new / old, 4))
                event["label"] = f"capital decrease (کاهش سرمایه) {pct}%: {_i(old):,} -> {_i(new):,} shares"
            events.append(event)
    return events


# ---------------------------------------------------------------------------------------- price adjustments


def _adjustment_events(rows: list[dict], flow: int, today: dt.date) -> list[dict[str, Any]]:
    events = []
    for raw in rows:
        day = _day(raw.get("dEven"))
        before, after = _f(raw.get("pClosingNotAdjusted")), _f(raw.get("pClosing"))
        ins = raw.get("instrument") or {}
        if day is None or not before or not after:
            continue
        factor = after / before
        event = {
            **_when(day, today), **_ident(ins.get("insCode") or raw.get("insCode") or None, ins.get("lVal18AFC"), ins.get("lVal30"), flow),
            "kind": "price_adjustment", "price_before": before, "price_after": after, "factor": _r(factor, 6), "adjustment_pct": pct_change(after, before),
        }
        move = "cut" if factor < 1 else "raised" if factor > 1 else "unchanged"
        event["label"] = f"price adjustment (تعدیل قیمت) {event['adjustment_pct']:+}%: reference price {move}, {before:,.0f} -> {after:,.0f} rial"
        if not EXTREME_FACTOR[0] <= factor <= EXTREME_FACTOR[1]:
            event["flag"] = "extreme_factor: likely a data error or a unit change; verify on Codal"
        events.append(event)
    return events


def _attach_share_context(adjustments: list[dict], roundtrips: list[dict]) -> None:
    """A price adjustment on the day the share count was put back to the old figure says so."""
    reductions = {(e["ins_code"], e["date"]): e for e in roundtrips if e.get("part") == "temporary_reduction"}
    for event in adjustments:
        hit = reductions.get((event["ins_code"], event["date"]))
        if hit:
            event["share_count"] = {"temporarily": hit["shares_after"], "before_and_after": hit["shares_before"], "restored_on": hit["partner_date"]}


# ------------------------------------------------------------------------------------------------ public


def capital_calendar(
    share_changes: Mapping[int, list[dict]] | list[dict] | None,
    price_adjustments: Mapping[int, list[dict]] | list[dict] | None = None,
    *,
    flow: int | str | None = 1,
    direction: str = "upcoming",
    days: int = 30,
    limit: int = 50,
    kind: str = "all",
    today: dt.date | str | int | None = None,
    adjustments_top: int | None = None,
) -> dict:
    """Corporate actions around ``today``, sorted by date (soonest first; ``recent`` newest first).

    ``share_changes`` / ``price_adjustments`` are the raw rows (inner lists) of the two feeds, a list for one flow or a
    ``{flow: rows}`` mapping. ``upcoming`` is strictly after today, ``recent`` includes today, ``all`` is both sides.
    ``adjustments_top`` is the ``top`` that was requested for the adjustments, to tell the agent when the window may
    reach further back than the rows fetched.
    """
    check_arguments(direction, kind, days, limit)
    flows = parse_flows(flow)
    day0 = _as_date(today)
    start = day0 - dt.timedelta(days=days) if direction in ("recent", "all") else day0 + dt.timedelta(days=1)
    end = day0 + dt.timedelta(days=days) if direction in ("upcoming", "all") else day0
    shares = _by_flow(share_changes, flows, "share_changes")
    adjusts = _by_flow(price_adjustments, flows, "price_adjustments")

    share_events: list[dict] = []
    adjustment_events: list[dict] = []
    for f in flows:
        share_events += _share_events(shares.get(f, []), f, day0)
        adjustment_events += _adjustment_events(adjusts.get(f, []), f, day0)
    roundtrips = [e for e in share_events if e["kind"] == "share_count_roundtrip"]
    _attach_share_context(adjustment_events, roundtrips)

    wanted = _ALL_KINDS if kind == "all" else (kind,)
    first, last = start.isoformat(), end.isoformat()  # ISO dates compare as text
    in_window = [e for e in (*share_events, *adjustment_events) if e["kind"] in wanted and first <= e["date"] <= last]
    in_window.sort(key=lambda e: e["symbol"] or "")
    in_window.sort(key=lambda e: e["date"], reverse=direction == "recent")  # stable: symbols stay A-Z within a day
    counts: dict[str, int] = defaultdict(int)
    for e in in_window:
        counts[e["kind"]] += 1

    share_days = [d for d in (_day(r.get("dEven")) for rows in shares.values() for r in rows) if d]
    adjust_days = [d for d in (_day(r.get("dEven")) for rows in adjusts.values() for r in rows) if d]
    notes = [NOT_AVAILABLE, HORIZON_NOTE]
    out: dict[str, Any] = {
        "today": day0.isoformat(), "today_jdate": jdate(day0.year * 10000 + day0.month * 100 + day0.day),
        "direction": direction, "days": days, "kind": kind,
        "window": {"from": start.isoformat(), "to": end.isoformat()},
        "flows": {str(f): FLOW_TITLES[f] for f in flows},
        "total_in_window": len(in_window), "count": min(limit, len(in_window)), "counts": dict(counts),
        "events": in_window[:limit],
        "coverage": {
            "share_changes_latest": max(share_days).isoformat() if share_days else None,
            "price_adjustments_from": min(adjust_days).isoformat() if adjust_days else None,
            "price_adjustments_to": max(adjust_days).isoformat() if adjust_days else None,
        },
    }
    if not in_window:
        notes.append("No events in this window. Widen days, or try direction='recent' or 'all'.")
    if len(in_window) > limit:
        notes.append(f"{len(in_window) - limit} more events in the window; raise limit to see them.")
    if "price_adjustment" in wanted and adjust_days and adjustments_top and len(adjust_days) >= adjustments_top and min(adjust_days) > start:
        notes.append(f"Price adjustments were read back to {min(adjust_days).isoformat()} only (newest {adjustments_top}); earlier ones in the window are not shown.")
    if kind != "share_count_roundtrip":
        hidden = sum(1 for e in roundtrips if first <= e["date"] <= last)
        out["hidden_roundtrip_rows"] = hidden
        if hidden:
            notes.append(f"{hidden} paired share-count rows (a temporary reduction and its restoration around price adjustments) are hidden; use kind='share_count_roundtrip' to see them.")
    out["notes"] = notes
    return out
