"""Index tools: finding an index by name, its daily history, today's 5-minute path and its member stocks.

Pure shaping code over payloads the service has already fetched; nothing here touches the network.

* ``Index/GetIndexB1LastAll/All/{1|2}`` lists the indices (Bourse flow 1, Fara Bourse flow 2) with their ``insCode``.
* ``Index/GetIndexB2History/{insCode}`` is the daily series: close, low and high per day, back to 2008 for the
  total index. The published low/high are rounded to 10 points in recent years and now and then carry a slipped
  digit, so they are widened to include the close and dropped when they sit more than 20% from it.
* ``Index/GetIndexB1LastDay/{insCode}`` is today's path on a 5-minute grid.
* ``ClosingPrice/GetIndexCompany/{insCode}`` lists the member stocks with today's prices; ``Index/GetInstEffect``
  adds how many points each stock moved the *total* index. The exchange publishes no weights.

Index values are index points, not rial. Anything derived here (change %, drawdown, volatility, market-cap share)
is labelled as derived or as an estimate.
"""

from __future__ import annotations

import datetime as dt
import math
import re
import statistics
from collections.abc import Sequence
from typing import Any

from .dates import fmt_date, fmt_time, gregorian_to_jalali, jdate, parse_date
from .dates import to_date as _to_date
from .shape import _f, _i, _r, pct_change, shape_index_row
from .text import ascii_digits, clean, match_key

DEFAULT_HISTORY_LIMIT = 120
MAX_ROWS = 500
GRANULARITIES = ("auto", "daily", "weekly", "monthly", "quarterly", "yearly")
TRADING_DAYS_PER_YEAR = 240  # assumption behind the annualised volatility: about five days a week minus holidays
RANGE_TOLERANCE = 0.2  # a published low/high further than 20% from the close is a data error, not a price
EFFECT_TOLERANCE = 0.05  # the effects must add up to the total index's move within 5% (or 0.05% of its level, for tiny moves)
FLAT_RUN = 3  # this many consecutive unchanged, range-less rows mean the market was closed (or the index did not trade)

EFFECT_SORTS = ("effect", "abs_effect", "value", "volume", "trades", "change", "market_cap")
_SORT_ALIASES = {
    "effect": "effect", "effect_on_index": "effect", "points": "effect", "abs_effect": "abs_effect", "absolute_effect": "abs_effect",
    "value": "value", "traded_value": "value", "volume": "volume", "trades": "trades",
    "change": "change", "change_pct": "change", "close_pct": "change", "market_cap": "market_cap", "cap": "market_cap",
}

# English words an agent may use -> a Persian name fragment that resolves through the normal matching below
INDEX_ALIASES = {
    "total": "شاخص کل", "tedpix": "شاخص کل", "main": "شاخص کل", "overall": "شاخص کل",
    "equal_weight": "شاخص کل (هم وزن)", "equalweight": "شاخص کل (هم وزن)", "equal_weighted": "شاخص کل (هم وزن)",
    "free_float": "شاخص آزاد شناور", "freefloat": "شاخص آزاد شناور",
    "fara": "شاخص کل فرابورس", "ifb": "شاخص کل فرابورس", "fara_total": "شاخص کل فرابورس", "ifb_total": "شاخص کل فرابورس",
    "fara_equal_weight": "شاخص کل هم وزن فرابورس",
    "first_market": "شاخص بازار اول", "second_market": "شاخص بازار دوم", "industry": "شاخص صنعت",
    "top30": "شاخص 30 شرکت بزرگ", "top50": "شاخص50شرکت فعالتر",
    "banks": "بانک", "bank": "بانک", "metals": "فلزات اساسی", "cement": "سیمان", "autos": "خودرو", "auto": "خودرو",
    "chemicals": "شیمیایی", "petrochemicals": "شیمیایی", "refinery": "فراورده نفتی", "pharma": "مواد دارویی",
    "insurance": "بیمه", "investment": "سرمایه گذاریها", "investments": "سرمایه گذاریها", "sugar": "قند و شکر",
}
_PUNCT = re.compile(r"[()\-_./،,\[\]]")


def _key(value: object) -> str:
    """Matching key: Persian letters, no spaces/ZWNJ/punctuation, digits as ASCII."""
    return _PUNCT.sub("", match_key(value))


# --------------------------------------------------------------------------------------- resolving an index


def index_catalogue(bourse_rows: Sequence[dict] | None, fara_rows: Sequence[dict] | None) -> list[dict]:
    """Every index of both markets as ``shape_index_row`` shapes plus ``market``, ``flow`` and the market's total-index change."""
    entries: list[dict] = []
    for market, flow, rows in (("bourse", 1, bourse_rows), ("fara", 2, fara_rows)):
        shaped = [shape_index_row(r) for r in rows or []]
        total = next((s for s in shaped if _key(s["name"]) == _key("شاخص کل فرابورس" if flow == 2 else "شاخص کل")), None)
        for item in shaped:
            entries.append(
                {
                    **item, "full_name": item["name"], "market": market, "flow": flow,
                    "is_market_total": total is not None and item["ins_code"] == total["ins_code"],
                    "market_total_change": total["change"] if total else None,
                    "market_total_value": total["value"] if total else None,
                }
            )
    return entries


def _describe(entry: dict) -> str:
    code = f" (code {entry['code']})" if entry.get("code") else ""
    return f"{entry['name']}{code} [{entry['market']}, insCode {entry['ins_code']}]"


def resolve_index(query: str | int | None, bourse_rows: Sequence[dict] | None, fara_rows: Sequence[dict] | None) -> dict:
    """Find one index from a name fragment, an English alias, an industry code or an insCode.

    Order: insCode, industry code (``27``), exact name, unique name fragment. Several fragment matches are an error that
    lists the candidates, because guessing between 'شاخص کل' and 'شاخص کل (هم وزن)' would silently return the wrong series.
    Returns the catalogue entry (see :func:`index_catalogue`).
    """
    text = clean(query) if query is not None else ""
    if not text:
        raise ValueError(
            "index is required: a name such as 'شاخص کل', 'شاخص کل (هم وزن)', 'شاخص کل فرابورس', 'فلزات', 'بانک', or an insCode. "
            "The indices tool lists every index with its insCode."
        )
    catalogue = index_catalogue(bourse_rows, fara_rows)
    if not catalogue:
        raise ValueError("The index list is empty right now, so no index can be matched. Try again shortly.")
    plain = ascii_digits(text).strip()
    if plain.isdigit() and len(plain) >= 8:  # insCode
        for entry in catalogue:
            if entry["ins_code"] == plain:
                return entry
        raise ValueError(f"insCode {plain} is not in the index list. The indices tool lists every index with its insCode.")
    alias = INDEX_ALIASES.get(re.sub(r"[\s\-]+", "_", text.casefold()))
    key = _key(alias or text)
    if plain.isdigit() and len(plain) <= 3:  # industry code as the exchange numbers them: 27 = فلزات اساسی
        by_code = [e for e in catalogue if e.get("code") and e["code"].lstrip("0") == plain.lstrip("0")]
        if len(by_code) == 1:
            return by_code[0]
        if len(by_code) > 1:
            raise ValueError(f"Industry code {plain} is ambiguous: " + "; ".join(_describe(e) for e in by_code[:6]) + ". Use the insCode.")
    exact = [e for e in catalogue if key in (_key(e["name"]), _key(e["full_name"]))]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ValueError(f"'{query}' names several indices: " + "; ".join(_describe(e) for e in exact[:6]) + ". Pass the insCode of the one you mean.")
    partial = [e for e in catalogue if key and key in _key(e["name"])]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise ValueError(f"No index matches '{query}'. Try a fragment of the Persian name ('فلزات', 'بانک', 'خودرو'), 'شاخص کل', or an insCode from the indices tool.")
    shown = "; ".join(_describe(e) for e in partial[:8])
    more = f" (+{len(partial) - 8} more)" if len(partial) > 8 else ""
    raise ValueError(f"'{query}' matches {len(partial)} indices: {shown}{more}. Use a longer name or the insCode.")


def _index_label(entry: dict) -> dict:
    return {k: entry.get(k) for k in ("name", "ins_code", "code", "market", "headline")}


# --------------------------------------------------------------------------------------- daily history


def _sane_range(close: float, low: float | None, high: float | None) -> tuple[float | None, float | None, bool]:
    """(low, high, suspect): published extremes widened to include the close, or None when implausible."""
    lo = low if low and (1 - RANGE_TOLERANCE) * close <= low <= (1 + RANGE_TOLERANCE) * close else None
    hi = high if high and (1 - RANGE_TOLERANCE) * close <= high <= (1 + RANGE_TOLERANCE) * close else None
    suspect = lo is None or hi is None
    return (None if lo is None else min(lo, close)), (None if hi is None else max(hi, close)), suspect


def _points(rows: Sequence[dict] | None) -> tuple[list[dict], int]:
    """Ascending, one point per day; rows without a date or a positive close are dropped (and counted).

    The exchange keeps writing a row for every closed day, repeating the last close with no range (2026-02-26 to
    2026-05-18 and 2025-06-12 to 2025-06-25 are such stretches). A run of ``FLAT_RUN`` or more rows whose close equals the
    previous close and whose low equals high (or repeats the previous row's range) is marked ``flat``.
    """
    by_day: dict[int, dict] = {}
    dropped = 0
    for raw in rows or []:
        day, close = _i(raw.get("dEven")), _f(raw.get("xNivInuClMresIbs"))
        if not day or close is None or close <= 0:
            dropped += 1
            continue
        low, high, suspect = _sane_range(close, _f(raw.get("xNivInuPbMresIbs")), _f(raw.get("xNivInuPhMresIbs")))
        by_day[day] = {
            "deven": day, "close": close, "low": low, "high": high, "suspect": suspect, "flat": False,
            "range": (_f(raw.get("xNivInuPbMresIbs")), _f(raw.get("xNivInuPhMresIbs"))),  # as published, for spotting repeated rows
        }
    points = [by_day[d] for d in sorted(by_day)]
    run: list[dict] = []
    prev: dict | None = None
    for point in points:
        repeats = prev is not None and point["close"] == prev["close"] and (
            point["range"][0] == point["range"][1] or point["range"] == prev["range"]
        )
        prev = point
        if repeats:
            run.append(point)
            continue
        if len(run) >= FLAT_RUN:
            for item in run:
                item["flat"] = True
        run = []
    if len(run) >= FLAT_RUN:
        for item in run:
            item["flat"] = True
    return points, dropped


def _bucket(deven: int, granularity: str) -> tuple:
    """Iranian calendar buckets: weeks start on Saturday, months, seasons and years are Jalali."""
    day = _to_date(deven)
    if granularity == "weekly":
        return ((day - dt.timedelta(days=(day.weekday() - 5) % 7)).toordinal(),)
    jy, jm, _ = gregorian_to_jalali(day.year, day.month, day.day)
    if granularity == "monthly":
        return (jy, jm)
    if granularity == "quarterly":
        return (jy, (jm - 1) // 3)
    return (jy,)


def _resample(points: list[dict], granularity: str) -> list[dict]:
    if granularity == "daily":
        return points
    out: list[dict] = []
    current: tuple | None = None
    for point in points:
        key = _bucket(point["deven"], granularity)
        if key != current:
            out.append({
                "deven": point["deven"], "first": point["deven"], "close": point["close"], "low": point["low"], "high": point["high"],
                "days": int(not point["flat"]),
            })
            current = key
            continue
        last = out[-1]
        lows = [v for v in (last["low"], point["low"]) if v is not None]
        highs = [v for v in (last["high"], point["high"]) if v is not None]
        last.update(
            deven=point["deven"], close=point["close"], low=min(lows) if lows else None, high=max(highs) if highs else None,
            days=last["days"] + int(not point["flat"]),
        )
    return out


def _spot(point: dict, key: str = "close") -> dict:
    return {"date": fmt_date(point["deven"]), "jdate": jdate(point["deven"]), "value": point[key]}


def _flat_runs(points: list[dict]) -> list[dict]:
    runs: list[dict] = []
    was_flat = False
    for point in points:
        if point["flat"] and was_flat:
            runs[-1].update(to=fmt_date(point["deven"]), days=runs[-1]["days"] + 1)
        elif point["flat"]:
            runs.append({"from": fmt_date(point["deven"]), "to": fmt_date(point["deven"]), "days": 1})
        was_flat = point["flat"]
    return runs


def _history_summary(points: list[dict], base_close: float | None) -> dict:
    first, last = points[0], points[-1]
    closes = [p["close"] for p in points]
    moves: list[tuple[int, float]] = []
    previous = base_close
    for point in points:
        if previous is not None and not point["flat"]:
            moves.append((point["deven"], (point["close"] / previous - 1) * 100))
        previous = point["close"]
    peak, peak_at = closes[0], 0
    worst, worst_peak, worst_trough = 0.0, 0, 0
    for i, close in enumerate(closes):
        if close > peak:
            peak, peak_at = close, i
        drop = (close / peak - 1) * 100
        if drop < worst:
            worst, worst_peak, worst_trough = drop, peak_at, i
    recovered = worst < 0 and any(c >= closes[worst_peak] for c in closes[worst_trough + 1:])
    highs = [(p["high"], p) for p in points if p["high"] is not None]
    lows = [(p["low"], p) for p in points if p["low"] is not None]
    high_close, low_close = max(points, key=lambda p: p["close"]), min(points, key=lambda p: p["close"])
    pcts = [m[1] for m in moves]
    daily_sd = statistics.stdev(pcts) if len(pcts) >= 2 else None
    best = max(moves, key=lambda m: m[1]) if moves else None
    worst_day = min(moves, key=lambda m: m[1]) if moves else None
    return {
        "from": _spot(first), "to": _spot(last), "trading_days": sum(1 for p in points if not p["flat"]), "flat_run_days": sum(1 for p in points if p["flat"]),
        "flat_runs": _flat_runs(points),
        "change_points": _r(last["close"] - first["close"]), "change_pct": pct_change(last["close"], first["close"]),
        "highest_close": _spot(high_close), "lowest_close": _spot(low_close),
        "intraday_high": _spot(max(highs, key=lambda h: h[0])[1], "high") if highs else None,
        "intraday_low": _spot(min(lows, key=lambda h: h[0])[1], "low") if lows else None,
        "max_drawdown": {
            "pct": _r(worst), "peak": _spot(points[worst_peak]), "trough": _spot(points[worst_trough]), "recovered": recovered,
        } if worst < 0 else {"pct": 0.0, "peak": None, "trough": None, "recovered": True},
        "up_days": sum(1 for p in pcts if round(p, 2) > 0), "down_days": sum(1 for p in pcts if round(p, 2) < 0),
        "flat_days": sum(1 for p in pcts if round(p, 2) == 0),
        "best_day": {"date": fmt_date(best[0]), "change_pct": _r(best[1])} if best and best[0] else None,
        "worst_day": {"date": fmt_date(worst_day[0]), "change_pct": _r(worst_day[1])} if worst_day and worst_day[0] else None,
        "volatility_estimate": {
            "daily_stdev_pct": _r(daily_sd),
            "annualized_pct": _r(daily_sd * math.sqrt(TRADING_DAYS_PER_YEAR)) if daily_sd is not None else None,
            "method": f"ESTIMATE: sample standard deviation of daily close-to-close % changes, annualised with sqrt({TRADING_DAYS_PER_YEAR})",
        },
        "basis": "daily closes; the first change is against the close before the range when there is one",
    }


def _day_before(deven: int) -> str:
    return (_to_date(deven) - dt.timedelta(days=1)).isoformat()


def _date_bound(value: str | int | None, name: str) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return parse_date(value)
    except ValueError as exc:
        raise ValueError(f"{name}: {exc}") from exc


def _limit(limit: int | None, default: int) -> int:
    try:
        return max(1, min(int(limit if limit is not None else default), MAX_ROWS))
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be a whole number") from exc


def shape_index_history(
    rows: Sequence[dict] | None,
    index: dict,
    *,
    from_date: str | int | None = None,
    to_date: str | int | None = None,
    limit: int | None = DEFAULT_HISTORY_LIMIT,
    granularity: str = "auto",
) -> dict:
    """Daily history of one index with a summary of the whole requested range.

    ``rows`` are the raw ``indexB2`` rows. The output rows are ascending; ``change_pct`` is derived (close against the
    previous trading day, or previous bucket close when resampled).

    Row cap: at most ``limit`` rows (default 120, hard maximum 500). ``granularity='auto'`` returns daily rows when the
    range fits, else weekly, monthly, quarterly or yearly rows, whichever is the finest that fits. A fixed granularity
    that still exceeds the cap returns its newest ``limit`` rows and ``next_to_date`` says where to continue. The
    ``summary`` always covers every trading day in the range, not only the rows shown.
    """
    mode = str(granularity or "auto").strip().casefold()
    if mode not in GRANULARITIES:
        raise ValueError(f"granularity must be one of {', '.join(GRANULARITIES)}.")
    cap = _limit(limit, DEFAULT_HISTORY_LIMIT)
    start, end = _date_bound(from_date, "from_date"), _date_bound(to_date, "to_date")
    if start and end and start > end:
        raise ValueError(f"from_date ({fmt_date(start)}) is after to_date ({fmt_date(end)}).")
    points, dropped = _points(rows)
    available = {"from": fmt_date(points[0]["deven"]), "to": fmt_date(points[-1]["deven"]), "rows": len(points)} if points else None
    base = None
    inside: list[dict] = []
    for point in points:
        if start and point["deven"] < start:
            base = point
        elif not end or point["deven"] <= end:
            inside.append(point)
    result: dict[str, Any] = {"index": _index_label(index), "units": "index points (not rial)", "data_available": available}
    if not inside:
        result.update(
            granularity=None, rows_in_range=0, returned=0, rows=[], summary=None,
            note="No trading days in the requested range." + (f" Data covers {available['from']} to {available['to']}." if available else ""),
        )
        return result

    if mode == "auto":
        mode = next((g for g in GRANULARITIES[1:] if len(_resample(inside, g)) <= cap), "yearly")
    series = _resample(inside, mode)
    previous = base["close"] if base else None
    shaped: list[dict] = []
    for item in series:
        row = {
            "date": fmt_date(item["deven"]), "jdate": jdate(item["deven"]), "close": item["close"],
            "change_pct": pct_change(item["close"], previous), "low": item["low"], "high": item["high"],
        }
        if mode != "daily":
            row["days"] = item["days"]
        elif item["flat"]:
            row["flat"] = True
        shaped.append(row)
        previous = item["close"]
    truncated = len(shaped) > cap
    shown = shaped[-cap:]
    notes = ["Rows ascending; close, low and high are published, change_pct is derived."]
    flat_days = sum(1 for p in inside if p["flat"])
    if flat_days:
        notes.append(
            f"{flat_days} rows are flat: the exchange writes a row for closed days that repeats the last close with no range. "
            "They stay in the series (marked flat when daily, not counted in days when resampled) but are left out of trading_days, "
            "the up/down counts and the volatility estimate."
        )
    if mode != "daily":
        notes.append(
            f"Rows are {mode} closes (last row of each Iranian-calendar bucket: weeks start Saturday, months/seasons/years are Jalali); "
            "low/high are the extremes inside the bucket and days counts its non-flat trading days."
        )
    if truncated:
        notes.append(f"Only the newest {cap} of {len(shaped)} {mode} rows are shown; use to_date before next_to_date to read earlier ones.")
    notes.append(
        "Published low/high are rounded to 10 points in recent years, so they are widened to include the close, and dropped "
        f"(null) when more than {int(RANGE_TOLERANCE * 100)}% from it."
    )
    suspect = sum(1 for p in inside if p["suspect"])
    result.update(
        granularity=mode, rows_in_range=len(inside), returned=len(shown), truncated=truncated,
        next_to_date=_day_before(series[len(series) - len(shown)].get("first", series[len(series) - len(shown)]["deven"])) if truncated else None,
        rows=shown, summary=_history_summary(inside, base["close"] if base else None),
        data_quality={"rows_dropped_no_close": dropped, "rows_with_unusable_low_high": suspect},
        note=" ".join(notes),
    )
    return result


# --------------------------------------------------------------------------------------- today's path


def shape_index_intraday(rows: Sequence[dict] | None, index: dict, *, limit: int | None = DEFAULT_HISTORY_LIMIT, today: int | None = None) -> dict:
    """The index's 5-minute path for the latest session.

    Rows before the first trade carry yesterday's close with no high/low and are dropped (that carried value is the
    previous close). Consecutive identical values are collapsed to their first row, the row marked ``last`` is always
    kept. If more than ``limit`` rows remain, every n-th row is kept with the first and last always included.
    """
    cap = _limit(limit, DEFAULT_HISTORY_LIMIT)
    points = sorted(
        (r for r in rows or [] if _i(r.get("dEven")) and _i(r.get("hEven")) is not None and (_f(r.get("xDrNivJIdx004")) or 0) > 0),
        key=lambda r: (_i(r["dEven"]), _i(r["hEven"]), bool(r.get("last"))),
    )
    base: dict[str, Any] = {"index": _index_label(index), "units": "index points (not rial)"}
    if not points:
        return {**base, "date": None, "rows": [], "summary": None, "note": "The exchange returned no intraday points for this index."}
    day = _i(points[-1]["dEven"])
    points = [r for r in points if _i(r["dEven"]) == day]
    started = [r for r in points if (_f(r.get("xPhNivJIdx004")) or 0) > 0]
    pre_open = [r for r in points if (_f(r.get("xPhNivJIdx004")) or 0) <= 0]
    previous_close = _f(pre_open[-1]["xDrNivJIdx004"]) if pre_open else None
    previous_source = "published (carried by the pre-open rows)"
    if previous_close is None and started:
        first = started[0]
        pct = _f(first.get("xVarIdxJRfV"))
        if pct is not None and pct > -100:
            previous_close = _r(_f(first["xDrNivJIdx004"]) / (1 + pct / 100))
            previous_source = "derived from the first session value and its change %"
    kept: list[dict] = []
    for r in started:
        sig = (r.get("xDrNivJIdx004"), r.get("xPhNivJIdx004"), r.get("xPbNivJIdx004"))
        if not kept or sig != kept[-1]["_sig"] or r.get("last"):
            kept.append({"_sig": sig, "raw": r})
    series = [k["raw"] for k in kept]
    stride = 1
    if len(series) > cap:
        stride = math.ceil((len(series) - 1) / max(cap - 1, 1))
        series = series[::stride]
        if series[-1] is not kept[-1]["raw"]:
            series = [*series[: cap - 1], kept[-1]["raw"]]
    shaped = [
        {"time": (fmt_time(_i(r["hEven"])) or "")[:5], "value": _f(r["xDrNivJIdx004"]), "change_pct": _f(r.get("xVarIdxJRfV"))}
        for r in series
    ]
    latest = started[-1] if started else points[-1]
    high, low = _f(latest.get("xPhNivJIdx004")) or None, _f(latest.get("xPbNivJIdx004")) or None
    value = _f(latest["xDrNivJIdx004"])

    def when(target: float | None) -> str | None:
        if not target:
            return None
        hit = next((r for r in started if abs(_f(r["xDrNivJIdx004"]) - target) < 0.01), None)
        return (fmt_time(_i(hit["hEven"])) or "")[:5] if hit else None

    summary = {
        "previous_close": previous_close, "previous_close_source": previous_source if previous_close is not None else None,
        "value": value, "change_points": _r(value - previous_close) if value is not None and previous_close is not None else None,
        "change_pct": _f(latest.get("xVarIdxJRfV")), "day_high": high, "day_low": low,
        "time_of_high": when(high), "time_of_low": when(low),
        "last_update": fmt_time(_i(latest.get("hEven"))), "raw_points": len(points), "session_points": len(started),
    }
    notes = [
        "5-minute grid. value, change_pct, day_high and day_low are published; change_points is derived; time_of_high/low is the first grid time with that value.",
        "The exchange keeps recalculating the index for a while after the 12:30 close, so late rows may differ slightly from the 12:30 value; the last row is the final value.",
    ]
    if not started:
        notes.append("The session has not produced a price yet (pre-open): every row carries the previous close.")
    if stride > 1:
        notes.append(f"Every {stride}th point is shown to respect limit={cap}.")
    if today is not None and day != today:
        notes.append(f"This is the latest session ({fmt_date(day)}), not today ({fmt_date(today)}).")
    return {
        **base, "date": fmt_date(day), "jdate": jdate(day), "is_today": None if today is None else day == today,
        "returned": len(shaped), "rows": shaped, "summary": summary, "note": " ".join(notes),
    }


# --------------------------------------------------------------------------------------- members


def effect_table(effects: Sequence[dict] | None) -> dict[str, float] | None:
    """insCode -> index points from ``Index/GetInstEffect`` rows; None when the table is missing or empty."""
    if not effects:
        return None
    return {str(r.get("insCode")): _f(r.get("instEffectValue")) or 0.0 for r in effects if r.get("insCode") is not None}


def effects_from_market_rows(rows: Sequence[dict], flow: int) -> list[dict]:
    """``instEffect``-shaped rows from shaped market-watch rows: their ``effect_on_index`` is the TSE gateway's live figure.

    A second source for the same numbers (checked: identical to the published table on the day the two agreed), used when the
    published table does not add up. The gateway lists Bourse shares only, so for flow 2 this comes back empty.
    """
    return [
        {"insCode": r["ins_code"], "instEffectValue": r["effect_on_index"]}
        for r in rows
        if r.get("flow") == flow and r.get("ins_code") and r.get("effect_on_index") is not None
    ]


def effects_usable(effects: Sequence[dict] | None, index: dict) -> bool:
    """True when an effect table adds up to the market's total-index move (or there is no move to compare with)."""
    return _check_effects(effect_table(effects), index)[1]


def _member_row(raw: dict, effects: dict[str, float] | None, caps: dict[str, float] | None) -> dict:
    inst = raw.get("instrument") or {}
    ins_code = str(inst.get("insCode") or raw.get("insCode") or "")
    close, last, yesterday = _f(raw.get("pClosing")), _f(raw.get("pDrCotVal")), _f(raw.get("priceYesterday"))
    trades, volume, value = _i(raw.get("zTotTran")) or 0, _i(raw.get("qTotTran5J")) or 0, _i(raw.get("qTotCap")) or 0
    traded = trades > 0 or volume > 0
    cap = (caps or {}).get(ins_code)
    return {
        "symbol": clean(inst.get("lVal18AFC")), "name": clean(inst.get("lVal30")), "ins_code": ins_code or None,
        "close": close if traded else None, "close_pct": pct_change(close, yesterday) if traded else None,
        "last": last if traded else None, "last_pct": pct_change(last, yesterday) if traded else None,
        "yesterday": yesterday, "volume": volume, "value": value, "trades": trades,
        "effect_on_total_index": None if effects is None else effects.get(ins_code, 0.0),
        "market_cap": _i(cap) if cap else None,
    }


def _check_effects(table: dict[str, float] | None, index: dict, source: str = "Index/GetInstEffect") -> tuple[dict | None, bool]:
    """(effect_check block, usable). The published effects of all stocks should add up to the market's total-index move."""
    if table is None:
        return None, False
    full = sum(table.values())
    change, level = index.get("market_total_change"), index.get("market_total_value")
    info: dict[str, Any] = {
        "scope": "effect on this index (it is the market's total index)" if index.get("is_market_total") else "effect on the market's total index, not on this index",
        "source": source, "sum_over_all_stocks": _r(full), "total_index_change_points": change,
        "covers_pct_of_change": _r(full / change * 100) if change else None,
    }
    if change is None:
        info["used"] = True
        return info, True
    tolerance = max(EFFECT_TOLERANCE * abs(change), 0.0005 * (level or 0))
    usable = abs(full - change) <= tolerance
    info["used"] = usable
    if not usable:
        info["warning"] = (
            "The effect table does not add up to the total index's move today (the exchange sometimes serves the previous session's table "
            "in the evening), so the effects are withheld; ask again later."
        )
    return info, usable


def shape_index_constituents(
    members: Sequence[dict] | None,
    index: dict,
    *,
    effects: Sequence[dict] | None = None,
    sort_by: str = "effect",
    descending: bool = True,
    limit: int | None = 25,
    market_caps: dict[str, float] | None = None,
    effects_source: str = "Index/GetInstEffect",
) -> dict:
    """Member stocks of an index with today's prices and, when ``effects`` is usable, their effect on the total index.

    ``members`` are the raw ``indexCompany`` rows (drop ``relatedCompanyThirtyDayHistory``, it is huge). ``effects`` are
    the raw ``instEffect`` rows for the index's market. ``market_caps`` maps insCode -> market cap in rial (the member rows
    carry no share count); it enables ``sort_by='market_cap'`` and the derived ``cap_share_pct``.
    The effect belongs to the *total* index of the market; for a sector index it is not the points inside that sector index.
    A member missing from a non-empty effect table did not change (untraded or unchanged close) and shows 0.
    The effect table is checked against the total index's move (``index['market_total_change']``); a table that does not add
    up is withheld (effects null, ``effect_check.used`` false) and an effect sort falls back to traded value.
    ``effects_source`` only labels where the table came from.
    """
    key = _SORT_ALIASES.get(str(sort_by or "effect").strip().casefold())
    if key is None:
        raise ValueError(f"sort_by must be one of {', '.join(EFFECT_SORTS)}.")
    if key == "market_cap" and not market_caps:
        raise ValueError("sort_by='market_cap' needs market caps, which the member list does not carry (no share counts).")
    cap = _limit(limit, 25)
    table = effect_table(effects)
    effect_info, usable = _check_effects(table, index, effects_source)
    if not usable:
        table = None
    rows = [_member_row(r, table, market_caps) for r in members or []]
    label = _index_label(index)
    meta = {"value": index.get("value"), "change": index.get("change"), "change_pct": index.get("change_pct"), "time": index.get("time")}
    if not rows:
        return {
            "index": {**label, **meta}, "members": 0, "rows": [],
            "note": "The exchange lists no member stocks for this index (it may be a derived index such as a dividend-yield index).",
        }
    total_cap = sum(r["market_cap"] or 0 for r in rows)
    if market_caps:
        for r in rows:
            r["cap_share_pct"] = _r(r["market_cap"] / total_cap * 100, 3) if r["market_cap"] and total_cap else None
    fallback = table is None and key in ("effect", "abs_effect")
    if fallback:
        key = "value"

    def sort_value(row: dict) -> float | None:
        effect = row["effect_on_total_index"]
        return {
            "effect": effect, "abs_effect": None if effect is None else abs(effect), "value": row["value"], "volume": row["volume"],
            "trades": row["trades"], "change": row["close_pct"], "market_cap": row["market_cap"],
        }[key]

    with_value = [r for r in rows if sort_value(r) is not None]
    without = [r for r in rows if sort_value(r) is None]
    with_value.sort(key=lambda r: (sort_value(r), r["value"]), reverse=descending)
    ordered = with_value + without
    traded = [r for r in rows if r["trades"] > 0 or r["volume"] > 0]
    moved = [r for r in traded if r["close_pct"] is not None]
    totals: dict[str, Any] = {
        "members": len(rows), "traded_today": len(traded),
        "advancers": sum(1 for r in moved if r["close_pct"] > 0), "decliners": sum(1 for r in moved if r["close_pct"] < 0),
        "unchanged": sum(1 for r in moved if r["close_pct"] == 0),
        "total_value": sum(r["value"] for r in rows), "total_volume": sum(r["volume"] for r in rows),
    }
    if table is not None:
        mine = [r["effect_on_total_index"] for r in rows]
        totals.update(sum_of_effects=_r(sum(mine)), positive_effects=_r(sum(e for e in mine if e > 0)), negative_effects=_r(sum(e for e in mine if e < 0)))
    notes = [
        "Prices come from the exchange's index member list: close_pct uses the closing price (the index is computed on it), last_pct the last trade; "
        "members that did not trade show null prices. volume is in shares, value in rial.",
        "The exchange publishes no index weights" + (", so cap_share_pct is derived: market cap / sum of the listed members' market caps, ignoring free float." if market_caps else "; ask for sort_by='market_cap' to see a derived cap share."),
    ]
    if table is None:
        notes.append(
            "Effects are withheld: "
            + ("the effect table did not add up to the index move." if effect_info else "the effect table was not available.")
            + " effect_on_total_index is null" + (" and the list is sorted by traded value instead." if fallback else ".")
        )
    else:
        notes.append(f"effect_on_total_index (index points) comes from {effects_source} and covers the latest session only.")
    return {
        "index": {**label, **meta}, "sorted_by": key, "descending": descending, "returned": min(cap, len(ordered)),
        "totals": totals, "effect_check": effect_info, "rows": ordered[:cap], "units": "prices and value in rial, volume in shares, effect in index points",
        "note": " ".join(notes),
    }
