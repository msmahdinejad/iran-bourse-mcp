"""High-level, agent-facing operations. Each public coroutine maps 1:1 to an MCP tool."""

from __future__ import annotations

import asyncio
import datetime as dt
import time
from typing import Any

from . import calendar_events, derivatives, screener, shape, status, toplists
from . import funds as fundmod
from . import indices as indexmod
from . import market as marketfeed
from .api import CODAL_SITE, TseApi
from .client import Http, NotAvailable, UpstreamError
from .dates import (
    DateError,
    fmt_date,
    fmt_time,
    from_date,
    is_session_hours,
    jdate,
    parse_date,
    parse_time,
    tehran_now,
    to_date,
)
from .resolver import FLOW_NAMES, Instrument, Resolver
from .text import ascii_digits, clean, match_key

MARKET_FLOW = {"bourse": 1, "fara": 2, "fara-bourse": 2, "ifb": 2}
MAX_ROWS = 5000
QUEUE_CANDIDATES = 400  # every limit-locked symbol (about 200 on a strong day); one BestLimits call each
CODAL_SCAN_PAGES = 8  # pages of 20 filings read while a title filter is looking for matches
SECTION_TIMEOUT = 8.0  # seconds an optional symbol_overview section may take before it is reported as unavailable
SESSION_WINDOW = (83000, 123500)  # HHMMSS: pre-open through just after close


class InputError(ValueError):
    """Bad tool arguments (reported to the agent as a normal tool error)."""


def _flow(market: str | None) -> int:
    if market is None:
        return 1
    flow = MARKET_FLOW.get(str(market).strip().lower())
    if flow is None:
        raise InputError("market must be 'bourse' or 'fara'.")
    return flow


def _check_type(security_type: str | None) -> None:
    try:
        marketfeed.check_security_type(security_type)
    except ValueError as exc:
        raise InputError(str(exc)) from exc


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def _today_deven() -> int:
    return from_date(tehran_now().date())


def _date_arg(value: str | int | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return parse_date(value)
    except DateError as exc:
        raise InputError(str(exc)) from exc


def _time_arg(value: str | int | None) -> int | None:
    try:
        return parse_time(value)
    except DateError as exc:
        raise InputError(str(exc)) from exc


class Bourse:
    """Facade over :class:`TseApi` implementing every tool."""

    def __init__(self, http: Http | None = None) -> None:
        self.http = http or Http()
        self.api = TseApi(self.http)
        self.resolver = Resolver(self.api)
        self.market_source = "tsetmc"

    async def aclose(self) -> None:
        await self.http.aclose()

    # ------------------------------------------------------------------ shared helpers
    async def _inst(self, symbol: str) -> Instrument:
        return await self.resolver.resolve(symbol)

    async def _latest_deven(self, ins: str) -> int:
        closing = await self.api.closing_info(ins)
        deven = int(closing.get("dEven") or 0)
        if deven:
            return deven
        overview = await self.api.market_overview(1)
        return int(overview.get("marketActivityDEven") or from_date(tehran_now().date()))

    async def _limits(self, ins: str, deven: int, info: dict | None = None) -> tuple[float | None, float | None]:
        try:
            rows = await self.api.thresholds(ins, deven)
        except NotAvailable:
            rows = []
        same_day = [r for r in rows if int(r.get("dEven") or 0) == deven]
        if same_day:
            row = sorted(same_day, key=lambda r: r.get("hEven") or 0)[-1]
            return shape._f(row.get("psGelStaMax")), shape._f(row.get("psGelStaMin"))
        if info is None:
            info = await self.api.instrument_info(ins)
        thr = info.get("staticThreshold") or {}
        return shape._f(thr.get("psGelStaMax")), shape._f(thr.get("psGelStaMin"))

    async def _official_day(self, ins: str, deven: int) -> dict | None:
        rows = await self.api.daily_prices(ins)
        for row in rows:
            if int(row.get("dEven") or 0) == deven:
                return row
        return None

    # ------------------------------------------------------------------ market level
    async def market_status(self) -> dict:
        now = tehran_now()
        overview, dates, server_time = await asyncio.gather(
            self.api.market_overview(1),
            self.api.market_dates(),
            self.api.server_time(),
            return_exceptions=True,
        )
        result: dict[str, Any] = {
            "tehran_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "tehran_jdate": jdate(from_date(now.date())),
            "weekday": now.strftime("%A"),
            "is_trading_weekday": now.weekday() in (5, 6, 0, 1, 2),
            "within_session_hours": is_session_hours(now),
            "session": "Saturday-Wednesday 09:00-12:30 Asia/Tehran (public holidays are not modelled)",
        }
        if not isinstance(overview, Exception):
            result["bourse"] = shape.shape_overview(overview)
        if not isinstance(dates, Exception):
            result["gateway"] = [
                {"market": clean(d.get("stockType")), "open_time": d.get("openTime"), "close_time": d.get("closeTime"), "is_open": d.get("isOpen")}
                for d in dates
            ]
        if not isinstance(server_time, Exception):
            result["exchange_server_time"] = str(server_time).strip()
        return result

    async def market_overview(self, market: str = "bourse") -> dict:
        flow = _flow(market)
        overview = await self.api.market_overview(flow)
        return {"market": "bourse" if flow == 1 else "fara-bourse", **shape.shape_overview(overview)}

    async def indices(self, market: str = "bourse", only_selected: bool = False) -> dict:
        flow = _flow(market)
        rows = [shape.shape_index_row(r) for r in await self.api.indices(flow)]
        headline = [r for r in rows if r["headline"]]
        industries = [r for r in rows if not r["headline"]]
        industries.sort(key=lambda r: r["change_pct"] if r["change_pct"] is not None else -999, reverse=True)
        return {
            "market": "bourse" if flow == 1 else "fara-bourse",
            "headline_indices": headline,
            "industry_indices": [] if only_selected else industries,
        }

    async def _market_rows(self) -> tuple[list[dict], str]:
        """Every instrument as a shaped row, from the exchange's market-watch feed (about 3,700 rows).

        If that feed is unavailable the TSE gateway's 582 ordinary shares are used instead, and the source says so.
        """
        try:
            feed = await self.api.market_watch_all()
        except (NotAvailable, UpstreamError):
            feed = []
        if not feed:
            return [shape.shape_watch_row(r) for r in await self.api.market_watch()], "tse-gateway"
        static, gateway = await asyncio.gather(self.api.static_data(), self.api.market_watch(), return_exceptions=True)
        industries = {} if isinstance(static, Exception) else marketfeed.industry_names(static)
        extras = {} if isinstance(gateway, Exception) else {g.get("instrumentId"): marketfeed.gateway_extras(g) for g in gateway}
        return [marketfeed.shape_market_row(r, industries=industries, gateway=extras.get(r.get("insID"))) for r in feed], "tsetmc"

    async def _watch_universe(
        self,
        market_name: str | None = None,
        security_type: str | None = None,
        industry: str | None = None,
        board: str | None = None,
        min_value: float = 0,
        only_traded: bool = True,
    ) -> tuple[int, list[dict]]:
        """Shaped market rows after the common universe filters; returns (all rows, kept rows)."""
        _check_type(security_type)
        rows, self.market_source = await self._market_rows()
        total = len(rows)

        def contains(haystack: str | None, needle: str | None) -> bool:
            return needle is None or match_key(needle) in match_key(haystack)

        if market_name:
            want_fara = _flow(market_name) == 2
            rows = [r for r in rows if bool(r["fara"] if "fara" in r else "فرابورس" in (r["market"] or "")) == want_fara]
        rows = [
            r
            for r in rows
            if marketfeed.security_type_matches(r["security_type"], security_type)
            and contains(r["industry"], industry)
            and contains(r["board"], board)
            and (r["value"] or 0) >= min_value
            and (not only_traded or (r["volume"] or 0) > 0)
        ]
        return total, rows

    async def market_watch(
        self,
        market: str | None = None,
        security_type: str | None = "سهام",
        industry: str | None = None,
        board: str | None = None,
        min_value: float = 0,
        only_traded: bool = True,
        sort_by: str = "value",
        descending: bool = True,
        limit: int = 50,
        detail: str = "compact",
    ) -> dict:
        if sort_by not in shape.WATCH_SORT_KEYS:
            raise InputError(f"sort_by must be one of {sorted(shape.WATCH_SORT_KEYS)}")
        total, rows = await self._watch_universe(market, security_type, industry, board, min_value, only_traded)
        key = shape.WATCH_SORT_KEYS[sort_by]
        rows.sort(key=lambda r: (r[key] is None, -(r[key] or 0) if descending else (r[key] or 0)))
        matched = len(rows)
        rows = rows[: _clamp(limit, 1, 700)]
        if detail != "full":
            rows = [_compact_watch(r) for r in rows]
        else:
            rows = [{k: v for k, v in r.items() if k != "book"} for r in rows]
        return {"total_instruments": total, "source": self.market_source, "matched": matched, "returned": len(rows), "sorted_by": sort_by, "rows": rows, "units": "rial"}

    async def _instrument_index(self) -> dict[str, str]:
        """instrumentId (as used by the TSE gateway) -> insCode (as used by the cdn API).

        Built from the end-of-day table. During the session today's table is still empty, so walk
        back to the most recent day that has rows (the ids are stable across days).
        """
        cached = getattr(self, "_index_cache", None)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        overview = await self.api.market_overview(1)
        today = to_date(int(overview.get("marketActivityDEven") or from_date(tehran_now().date())))
        rows: list[dict] = []
        for back in range(8):
            rows = await self.api.prices_on_day(from_date(today - dt.timedelta(days=back)))
            if rows:
                break
        index = {r["instrumentID"]: str(r["insCode"]) for r in rows if r.get("instrumentID") and r.get("insCode")}
        self._index_cache = (time.monotonic() + 6 * 3600, index)
        return index

    async def _client_flows_by_instrument(self, rows: list[dict] | None = None) -> dict[str, dict]:
        """instrumentId -> raw client-type row. Rows from the exchange feed carry their insCode; gateway rows are joined through the daily table."""
        flows = await self.api.client_type_all()
        by_code = {str(f["insCode"]): f for f in flows}
        if rows is not None and all(r.get("ins_code") for r in rows):
            return {r["instrument_id"]: by_code[r["ins_code"]] for r in rows if r["ins_code"] in by_code}
        index = await self._instrument_index()
        by_ins = {v: k for k, v in index.items()}
        return {by_ins[code]: f for code, f in by_code.items() if code in by_ins}

    async def _confirm_queues(self, rows: list[dict], side: str) -> list[dict]:
        """Fetch the real order book of limit-locked candidates and keep genuine queues.

        The gateway's top-of-book fields cannot confirm a queue (and are unreliable outside the session),
        so queue presence and size come from BestLimits. On a strong day about 200 symbols sit at the upper limit, so this makes up to
        that many calls (cached, six in flight): expect around ten seconds.
        """
        index = await self._instrument_index() if any(not r.get("ins_code") for r in rows) else {}
        code_of = lambda r: r.get("ins_code") or index.get(r["instrument_id"])  # noqa: E731
        flag = "at_upper_limit" if side == "buy" else "at_lower_limit"
        candidates = sorted((r for r in rows if r[flag] and code_of(r)), key=lambda r: r["value"] or 0, reverse=True)[:QUEUE_CANDIDATES]
        books = await asyncio.gather(*(self.api.best_limits(code_of(r)) for r in candidates), return_exceptions=True)
        wanted = "buy_queue" if side == "buy" else "sell_queue"
        out = []
        for row, book in zip(candidates, books, strict=True):
            if isinstance(book, Exception):
                continue
            shaped = shape.shape_order_book(book, row["price_limits"]["upper"], row["price_limits"]["lower"])
            if shaped["queue"]["state"] == wanted:
                out.append({**row, "queue_volume": shaped["queue"]["queue_volume"], "queue_orders": shaped["queue"]["queue_orders"], "queue_value": shaped["queue"]["queue_value"]})
        out.sort(key=lambda r: r["queue_value"], reverse=True)
        return out

    async def top_movers(self, kind: str = "gainers", market: str | None = None, security_type: str | None = "سهام", limit: int = 20) -> dict:
        kinds = {
            "gainers", "losers", "value", "volume", "trades",
            "buy_queue", "sell_queue", "real_inflow", "real_outflow", "real_buyer_power",
        }
        if kind not in kinds:
            raise InputError(f"kind must be one of {sorted(kinds)}")
        watch = await self.market_watch(
            market=market, security_type=security_type, only_traded=True, sort_by="value", limit=700, detail="full"
        )
        rows = watch["rows"]
        limit = _clamp(limit, 1, 100)

        if kind in ("gainers", "losers"):
            rows.sort(key=lambda r: (r["close_pct"] if r["close_pct"] is not None else 0, r["value"] or 0), reverse=(kind == "gainers"))
        elif kind in ("value", "volume", "trades"):
            rows.sort(key=lambda r: r[kind] or 0, reverse=True)
        elif kind in ("buy_queue", "sell_queue"):
            rows = await self._confirm_queues(rows, "buy" if kind == "buy_queue" else "sell")
        else:
            flows = await self._client_flows_by_instrument(rows)
            enriched = []
            for r in rows:
                f = flows.get(r["instrument_id"])
                if not f:
                    continue
                buy_v, sell_v = shape._f(f.get("buy_I_Volume")) or 0, shape._f(f.get("sell_I_Volume")) or 0
                buy_c, sell_c = shape._f(f.get("buy_CountI")) or 0, shape._f(f.get("sell_CountI")) or 0
                net = buy_v - sell_v
                vwap = r["vwap"] or r["last"] or 0
                power = shape._safe_div(shape._safe_div(buy_v, buy_c), shape._safe_div(sell_v, sell_c))
                enriched.append(
                    {
                        **r,
                        "real_net_volume": int(net),
                        "real_net_value_estimated": int(net * vwap),
                        "real_buyer_power": shape._r(power),
                        "real_buyers": int(buy_c),
                        "real_sellers": int(sell_c),
                    }
                )
            rows = enriched
            if kind == "real_inflow":
                rows.sort(key=lambda r: r["real_net_value_estimated"], reverse=True)
            elif kind == "real_outflow":
                rows.sort(key=lambda r: r["real_net_value_estimated"])
            else:  # real_buyer_power
                rows = [r for r in rows if r["real_buyer_power"] is not None and (r["value"] or 0) > 5e9]
                rows.sort(key=lambda r: r["real_buyer_power"], reverse=True)

        out = [
            _compact_watch(r, extra=("real_net_volume", "real_net_value_estimated", "real_buyer_power", "real_buyers", "real_sellers", "queue_volume", "queue_orders", "queue_value"))
            for r in rows[:limit]
        ]
        return {"kind": kind, "count": len(out), "rows": out, "note": "real_* values are estimates: net real volume x symbol VWAP." if kind.startswith("real") else None}

    # ------------------------------------------------------------------ screener
    async def _trading_day_tables(self, today: int, depth: int) -> list[tuple[int, list[dict]]]:
        """End-of-day market tables of the ``depth`` trading days before ``today`` (newest first).

        Thursday and Friday are skipped without a request; other non-trading days (public holidays) come back
        empty or nearly empty and are skipped after the fact, so a few extra tables may be fetched around holidays.
        """
        found: list[tuple[int, list[dict]]] = []
        cursor, budget = to_date(today), depth * 2 + 30
        while len(found) < depth and budget > 0:
            batch: list[int] = []
            while len(batch) < max(depth - len(found), 3) and budget > 0:
                cursor -= dt.timedelta(days=1)
                budget -= 1
                if cursor.weekday() not in (3, 4):  # Thursday, Friday
                    batch.append(from_date(cursor))
            results = await asyncio.gather(*(self.api.prices_on_day(d) for d in batch), return_exceptions=True)
            for deven, rows in zip(batch, results, strict=True):
                if isinstance(rows, NotAvailable):
                    continue
                if isinstance(rows, Exception):
                    raise rows
                if sum(1 for r in rows if r.get("zTotTran")) >= 20 and len(found) < depth:
                    found.append((deven, rows))
        found.sort(key=lambda item: item[0], reverse=True)
        return found

    async def screener_reference(self, topic: str = "overview") -> dict:
        try:
            return screener.reference(topic)
        except screener.FilterError as exc:
            raise InputError(str(exc)) from exc

    async def screen_stocks(
        self,
        filter: str | None = None,  # noqa: A002 - public tool argument name
        preset: str | None = None,
        market: str | None = None,
        security_type: str | None = "سهام",
        industry: str | None = None,
        columns: list[str] | None = None,
        sort: str | None = None,
        descending: bool | None = None,
        limit: int = 30,
        include_untraded: bool = False,
        adjusted: bool = True,
    ) -> dict:
        started = time.monotonic()
        try:
            chosen = screener.preset(preset) if preset else None
            has_filter = bool(filter and filter.strip())
            if not has_filter and chosen is None:
                raise InputError('Give a filter (e.g. "volume > 2 * avg(volume, 20) and close_pct > 1"), a preset, or both. See screener_reference.')
            sources = ([chosen.filter] if chosen else []) + ([filter] if has_filter else [])
            conditions = [screener.compile_filter(text) for text in sources]
            custom_sort = bool(sort and sort.strip())
            sort_text = sort.strip() if custom_sort else (chosen.sort if chosen else "value")
            sort_key = screener.compile_expression(sort_text)
            if descending is None:
                descending = chosen.descending if chosen and not custom_sort else True
            labelled: list[tuple[str, screener.Compiled]] = []
            for spec in columns or []:
                body, label = spec.rsplit(" as ", 1) if " as " in spec else (spec, spec)
                labelled.append((label.strip() or body.strip(), screener.compile_expression(body)))
        except screener.FilterError as exc:
            raise InputError(str(exc)) from exc

        if not labelled:
            labelled = [(name, screener.compile_expression(name)) for name in ("symbol", "last", "close_pct", "volume", "value")]
            shown = {label for label, _ in labelled}
            order_of = [f.name for f in screener.FIELDS]
            for name in sorted({n for c in conditions for n in c.fields}, key=order_of.index):
                spec = next(f for f in screener.FIELDS if f.name == name)
                if name not in shown and spec.kind != "text" and len(labelled) < 12:
                    labelled.append((name, screener.compile_expression(name)))
                    shown.add(name)
            for condition in conditions:  # the aggregate/lagged terms of the filter, as evidence for each hit
                for text, fn in condition.evidence[:4]:
                    if text not in shown and len(labelled) < 16:
                        labelled.append((text, screener.Compiled(text, fn, "num", condition.lookback, False, frozenset())))
                        shown.add(text)
        elif labelled[0][0] != "symbol":
            labelled.insert(0, ("symbol", screener.compile_expression("symbol")))

        everything = [*conditions, sort_key, *(c for _, c in labelled)]
        depth = max(c.lookback for c in everything)
        need_flows = any(c.uses_flows for c in everything)

        (total, universe), overview = await asyncio.gather(
            self._watch_universe(market, security_type, industry, None, 0, not include_untraded),
            self.api.market_overview(1),
        )
        today = int(overview.get("marketActivityDEven") or from_date(tehran_now().date()))
        tables, flows = await asyncio.gather(
            self._trading_day_tables(today, depth) if depth else _just([]),
            self._client_flows_by_instrument(universe) if need_flows else _just({}),
        )

        wanted = {r["instrument_id"] for r in universe}
        per_day = [{r.get("instrumentID"): r for r in rows if r.get("instrumentID") in wanted} for _, rows in tables]
        by_instrument: dict[str, list[dict]] = {}
        for iid in wanted:
            # The end-of-day table lists only symbols that traded. A silent day after the symbol's first appearance
            # counts as zero volume; days before it first appeared stay unknown.
            sequence = [day.get(iid) for day in per_day]
            first_seen = max((i for i, raw in enumerate(sequence) if raw), default=-1)
            by_instrument[iid] = [
                screener.build_history_day(raw) if raw else (screener.NOT_TRADED if i < first_seen else screener.NO_DATA)
                for i, raw in enumerate(sequence)
            ]

        matched: list[screener.Ctx] = []
        for row in universe:
            today_values = screener.build_today(row, flows.get(row["instrument_id"]) if need_flows else None)
            days = by_instrument.get(row["instrument_id"], [])
            if adjusted and days:
                days = [dict(d) for d in days]
                screener.adjust_history(today_values.get("yesterday"), days)
            ctx = screener.Ctx(today_values, days)
            if all(screener.passes(c, ctx) for c in conditions):
                matched.append(ctx)

        keyed = []
        for ctx in matched:
            value = sort_key.fn(ctx, 0)
            keyed.append((None if value is None else (int(value) if isinstance(value, bool) else value), ctx))
        present_rows = [item for item in keyed if item[0] is not None]
        absent_rows = [item for item in keyed if item[0] is None]
        try:
            present_rows.sort(key=lambda item: item[0], reverse=bool(descending))
        except TypeError as exc:
            raise InputError("The sort expression must give numbers (or text) for every row.") from exc
        ordered = [ctx for _, ctx in present_rows + absent_rows]
        limit = _clamp(limit, 1, 300)
        out = [{label: screener.tidy(c.fn(ctx, 0)) for label, c in labelled} for ctx in ordered[:limit]]

        now = tehran_now()
        notes: list[str] = []
        if is_session_hours(now):
            notes.append("The session is still open: today's volume, value, trades and real/legal flows are partial, so ratios to past averages are understated.")
        if depth and len(tables) < depth:
            notes.append(f"Only {len(tables)} of the {depth} requested past trading days were available; rows lacking history do not match history conditions.")
        if need_flows:
            notes.append("real_* values come from the exchange's client-type table; *_value fields are estimated as net volume x vwap.")
        if not ordered:
            notes.append("No instrument matched. Loosen a threshold, or check field names with screener_reference.")
        return {
            "filter": " and ".join(f"({text.strip()})" for text in sources),
            "preset": chosen.name if chosen else None,
            "universe": {"instruments": len(universe), "of_total_in_watch": total, "market": market, "security_type": security_type, "industry": industry},
            "as_of": {"date": fmt_date(today), "jdate": jdate(today), "session_open": is_session_hours(now)},
            "history": {
                "trading_days_loaded": len(tables),
                "from": fmt_date(tables[-1][0]) if tables else None,
                "to": fmt_date(tables[0][0]) if tables else None,
                "adjusted_for_capital_changes": bool(adjusted and tables),
            },
            "matched": len(ordered),
            "returned": len(out),
            "sorted_by": sort_text,
            "descending": bool(descending),
            "rows": out,
            "units": "prices and values in rial, volumes in shares, percentages in percent",
            "notes": notes,
            "elapsed_seconds": round(time.monotonic() - started, 2),
        }

    async def industry_summary(self, market: str | None = None, limit: int = 15) -> dict:
        watch = await self.market_watch(market=market, security_type="سهام", only_traded=True, limit=700, detail="full")
        try:
            flows = await self._client_flows_by_instrument(watch["rows"])
        except (NotAvailable, UpstreamError):
            flows = {}
        groups: dict[str, list[dict]] = {}
        for r in watch["rows"]:
            groups.setdefault(r["industry"] or "?", []).append(r)
        out = []
        for name, rows in groups.items():
            cap = sum(r["market_cap"] or 0 for r in rows)
            weighted = (
                sum((r["last_pct"] or 0) * (r["market_cap"] or 0) for r in rows) / cap if cap else None
            )
            best = max(rows, key=lambda r: r["last_pct"] if r["last_pct"] is not None else -999)
            worst = min(rows, key=lambda r: r["last_pct"] if r["last_pct"] is not None else 999)
            out.append(
                {
                    "industry": name,
                    "symbols": len(rows),
                    "value": sum(r["value"] or 0 for r in rows),
                    "volume": sum(r["volume"] or 0 for r in rows),
                    "market_cap": cap,
                    "avg_change_pct": shape._r(sum(r["last_pct"] or 0 for r in rows) / len(rows)),
                    "cap_weighted_change_pct": shape._r(weighted),
                    "index_effect": shape._r(sum(r["effect_on_index"] or 0 for r in rows)),
                    "top_gainer": {"symbol": best["symbol"], "pct": best["last_pct"]},
                    "top_loser": {"symbol": worst["symbol"], "pct": worst["last_pct"]},
                    "real_net_value_estimated": _real_net_value(rows, flows) if flows else None,
                    "in_buy_queue": sum(1 for r in rows if r["buy_queue_probable"]),
                    "in_sell_queue": sum(1 for r in rows if r["sell_queue_probable"]),
                }
            )
        out.sort(key=lambda r: r["value"], reverse=True)
        return {"total_industries": len(out), "industries": out[: _clamp(limit, 1, 80)], "units": "rial"}

    async def index_contributors(self, limit: int = 15) -> dict:
        watch = await self.market_watch(security_type="سهام", only_traded=False, limit=700, detail="full")
        rows = [r for r in watch["rows"] if r["effect_on_index"] is not None]
        limit = _clamp(limit, 1, 60)
        pos = sorted(rows, key=lambda r: r["effect_on_index"], reverse=True)[:limit]
        neg = sorted(rows, key=lambda r: r["effect_on_index"])[:limit]
        cut = lambda r: {"symbol": r["symbol"], "effect_on_index": r["effect_on_index"], "last_pct": r["last_pct"], "industry": r["industry"]}  # noqa: E731
        return {"positive": [cut(r) for r in pos], "negative": [cut(r) for r in neg], "unit": "index points"}

    # ------------------------------------------------------------------ indices: history, members
    async def _resolve_index(self, index: str) -> dict:
        bourse, fara = await asyncio.gather(self.api.indices(1), self.api.indices(2))
        try:
            return indexmod.resolve_index(index, bourse, fara)
        except ValueError as exc:
            raise InputError(str(exc)) from exc

    async def index_history(
        self,
        index: str,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 120,
        intraday: bool = False,
        granularity: str = "auto",
    ) -> dict:
        entry = await self._resolve_index(index)
        try:
            if intraday:
                return indexmod.shape_index_intraday(await self.api.index_intraday(entry["ins_code"]), entry, limit=limit, today=_today_deven())
            rows = await self.api.index_history(entry["ins_code"])
            return indexmod.shape_index_history(rows, entry, from_date=from_date, to_date=to_date, limit=limit, granularity=granularity)
        except ValueError as exc:
            raise InputError(str(exc)) from exc

    async def _index_effects(self, entry: dict) -> tuple[list[dict] | None, str]:
        """Each stock's effect (index points) on the market's total index, with where it came from.

        The published table (Index/GetInstEffect) is used when it adds up to the total index's move; the exchange sometimes serves the
        previous session's table in the evening. Then, for the Bourse, the TSE gateway's live ``effectonIndex`` figures (the same numbers,
        already in the market rows) are tried. Otherwise the published table is returned anyway so the output can say why effects are withheld.
        """
        source = "Index/GetInstEffect"
        try:
            table: list[dict] | None = await self.api.index_effects(_today_deven(), entry["flow"])
        except (NotAvailable, UpstreamError):
            table = None
        if table and indexmod.effects_usable(table, entry):
            return table, source
        if entry["flow"] == 1:
            try:
                rows, _ = await self._market_rows()
            except (NotAvailable, UpstreamError):
                rows = []
            gateway = indexmod.effects_from_market_rows(rows, 1)
            if gateway and indexmod.effects_usable(gateway, entry):
                return gateway, "TSE gateway (effectonIndex)"
        return table, source

    async def index_constituents(self, index: str, sort_by: str = "effect", descending: bool = True, limit: int = 25) -> dict:
        entry = await self._resolve_index(index)
        members = await self.api.index_members(entry["ins_code"])
        effects, effects_source = await self._index_effects(entry)  # a bonus: without it the members still come back, effects null
        caps = None
        if str(sort_by).strip().casefold() in ("market_cap", "cap"):  # the member list has no share counts: take them from the market feed
            rows, _ = await self._market_rows()
            caps = {r["ins_code"]: r["market_cap"] for r in rows if r.get("market_cap") and r.get("ins_code")}
        try:
            return indexmod.shape_index_constituents(
                members, entry, effects=effects, sort_by=sort_by, descending=descending, limit=limit, market_caps=caps, effects_source=effects_source
            )
        except ValueError as exc:
            raise InputError(str(exc)) from exc

    # ------------------------------------------------------------------ fund registry
    async def fund_ranking(
        self,
        fund_type: str | None = None,
        sort_by: str = "return_1y",
        descending: bool = True,
        min_net_assets: float | None = None,
        limit: int = 25,
        detail: str = "compact",
    ) -> dict:
        try:
            ids = fundmod.resolve_fund_types(fund_type)
            fundmod.resolve_sort(sort_by)  # fail before fetching anything
        except ValueError as exc:
            raise InputError(str(exc)) from exc
        by_type: dict[int, list[dict]] = {}
        for start in range(0, len(ids), 4):  # a few at a time: 15 small requests for "all types"
            batch = ids[start : start + 4]
            for type_id, rows in zip(batch, await asyncio.gather(*(self.api.funds(i) for i in batch)), strict=True):
                by_type[type_id] = rows
        try:
            return fundmod.shape_fund_ranking(
                by_type, sort_by=sort_by, descending=descending, min_net_assets=min_net_assets, limit=limit, detail=detail
            )
        except ValueError as exc:
            raise InputError(str(exc)) from exc

    async def market_snapshot(self, date: str | int, sort_by: str = "value", limit: int = 30, security_type: str | None = "stock") -> dict:
        deven = _date_arg(date)
        if deven is None:
            raise InputError("date is required")
        _check_type(security_type)
        rows = await self.api.prices_on_day(deven)
        if not rows:
            return {"date": fmt_date(deven), "jdate": jdate(deven), "count": 0, "rows": [], "note": "No data (holiday or future date?)."}
        keymap = {"value": "qTotCap", "volume": "qTotTran5J", "trades": "zTotTran", "change_pct": "priceChange"}
        if sort_by not in keymap:
            raise InputError(f"sort_by must be one of {sorted(keymap)}")
        shaped = []
        for r in rows:
            close, y = shape._f(r.get("pClosing")), shape._f(r.get("priceYesterday"))
            shaped.append(
                {
                    "symbol": clean(r.get("lVal18AFC")),
                    "name": clean(r.get("lVal30")),
                    "close": close,
                    "last": shape._f(r.get("pDrCotVal")),
                    "yesterday": y,
                    "change_pct": shape.pct_change(close, y),
                    "open": shape._f(r.get("priceFirst")),
                    "high": shape._f(r.get("priceMax")),
                    "low": shape._f(r.get("priceMin")),
                    "volume": shape._i(r.get("qTotTran5J")),
                    "value": shape._i(r.get("qTotCap")),
                    "trades": shape._i(r.get("zTotTran")),
                    "instrument_id": r.get("instrumentID"),
                }
            )
        live_types: dict[str, str] = {}
        try:  # today's instruments carry their exact type (and TAL segments) in the live feed
            live_types = {r["instrument_id"]: r["security_type"] for r in (await self._market_rows())[0]}
        except (NotAvailable, UpstreamError):
            pass
        for r in shaped:
            r["type"] = live_types.get(r["instrument_id"]) or marketfeed.type_from_instrument_id(r["instrument_id"])
        shaped = [r for r in shaped if marketfeed.security_type_matches(r["type"], security_type)]
        shaped = [r for r in shaped if (r["trades"] or 0) > 0 and (r["yesterday"] or 0) > 1]  # a reference price of 1 is an unpriced contract
        key = "change_pct" if sort_by == "change_pct" else sort_by
        shaped.sort(key=lambda r: (r[key] is None, -(r[key] or 0)))
        return {
            "date": fmt_date(deven),
            "jdate": jdate(deven),
            "traded_instruments": len(shaped),
            "rows": shaped[: _clamp(limit, 1, 300)],
            "units": "rial",
        }

    async def market_holder_moves(self, limit: int = 30) -> dict:
        data = await self.api.holder_moves_market()
        dates = [fmt_date(d) for d in data.get("dates", [])]
        rows = []
        for holder in data.get("shareHoldersChanges", []):
            for item in holder.get("insList", []):
                days = [shape._f(item.get(k)) for k in ("firstDay", "secondDay", "thirdDay", "fourthDay", "fifthDay")]
                if None in days or days[0] == days[-1]:
                    continue
                rows.append(
                    {
                        "holder": clean(holder.get("name")),
                        "instrument": clean(item.get("name")),
                        "shares_first_day": int(days[0]),
                        "shares_last_day": int(days[-1]),
                        "change": int(days[-1] - days[0]),
                        "change_pct": shape.pct_change(days[-1], days[0]),
                    }
                )
        rows.sort(key=lambda r: abs(r["change_pct"] or 0), reverse=True)
        return {"dates": dates, "moves": rows[: _clamp(limit, 1, 200)], "total_moves": len(rows),
                "note": "Large holders whose position in an instrument changed over the last 5 reported days."}

    # ------------------------------------------------------------------ symbol level
    async def search_symbol(self, query: str, limit: int = 15) -> dict:
        rows = await self.api.search(ascii_digits(clean(query) or query))
        out = []
        for r in rows[: _clamp(limit, 1, 50)]:
            out.append(
                {
                    "symbol": clean(r.get("lVal18AFC")),
                    "name": clean(r.get("lVal30")),
                    "ins_code": str(r.get("insCode")),
                    "market": FLOW_NAMES.get(int(r.get("flow") or 0), str(r.get("flow"))),
                    "board": clean(r.get("cgrValCotTitle")) or clean(r.get("cgrValCot")),
                }
            )
        return {"query": query, "count": len(out), "results": out}

    async def quote(self, symbol: str) -> dict:
        inst = await self._inst(symbol)
        info, closing = await asyncio.gather(self.api.instrument_info(inst.ins_code), self.api.closing_info(inst.ins_code))
        return {"instrument": inst.brief(), **shape.shape_quote(closing, info)}

    async def order_book(self, symbol: str) -> dict:
        inst = await self._inst(symbol)
        info, rows, closing = await asyncio.gather(
            self.api.instrument_info(inst.ins_code), self.api.best_limits(inst.ins_code), self.api.closing_info(inst.ins_code)
        )
        thr = info.get("staticThreshold") or {}
        book = shape.shape_order_book(rows, shape._f(thr.get("psGelStaMax")), shape._f(thr.get("psGelStaMin")))
        return {
            "instrument": inst.brief(),
            "as_of": {"date": fmt_date(closing.get("dEven")), "last_trade_time": fmt_time(closing.get("hEven"))},
            **book,
        }

    async def order_book_history(
        self,
        symbol: str,
        date: str | None = None,
        from_time: str | None = None,
        to_time: str | None = None,
        step_seconds: int = 300,
    ) -> dict:
        inst = await self._inst(symbol)
        deven = _date_arg(date) or await self._latest_deven(inst.ins_code)
        rows = await self.api.best_limits_history(inst.ins_code, deven)
        if not rows:
            return {"instrument": inst.brief(), "date": fmt_date(deven), "snapshots_in_range": 0, "note": "No order-book events (holiday, suspended, or not traded)."}
        upper, lower = await self._limits(inst.ins_code, deven)
        snaps = shape.reconstruct_book(rows)
        start = _time_arg(from_time) if from_time else SESSION_WINDOW[0]
        end = _time_arg(to_time) if to_time else SESSION_WINDOW[1]
        timeline = shape.book_timeline(
            snaps, upper, lower, start=start, end=end, step_seconds=_clamp(step_seconds, 5, 3600)
        )
        first_event, last_event = snaps[0]["time"], snaps[-1]["time"]
        complete = last_event >= 122500
        return {
            "instrument": inst.brief(),
            "date": fmt_date(deven),
            "jdate": jdate(deven),
            "total_events": len(snaps),
            "events_span": {"first": fmt_time(first_event), "last": fmt_time(last_event), "covers_full_session": complete},
            "warning": None
            if complete
            else "TSETMC's order-book history for this day ends before the close. For the current trading day it "
            "is typically published only partially until the next trading day; use order_book for the live book.",
            "price_limits": {"upper": upper, "lower": lower},
            "window": {"from": fmt_time(start), "to": fmt_time(end)},
            **timeline,
            "note": "Snapshots are rebuilt from TSETMC's delta feed by carrying unchanged levels forward. "
            "The default window covers pre-open and the session (08:30-12:35); pass from_time/to_time "
            "('00:00', '23:59') to include the out-of-session order entry that TSETMC also records.",
        }

    async def _ticks(self, ins: str, date: str | None) -> tuple[int, list[dict]]:
        deven = _date_arg(date)
        latest = await self._latest_deven(ins)
        if deven is None or deven == latest:
            return latest, await self.api.trades_latest(ins)
        return deven, await self.api.trades_history(ins, deven)

    async def trades(
        self,
        symbol: str,
        date: str | None = None,
        from_time: str | None = None,
        to_time: str | None = None,
        min_volume: int = 0,
        limit: int = 200,
        newest_first: bool = False,
    ) -> dict:
        inst = await self._inst(symbol)
        deven, raw = await self._ticks(inst.ins_code, date)
        ticks = shape.shape_ticks(raw)
        start, end = _time_arg(from_time), _time_arg(to_time)
        if start or end:
            ticks = [t for t in ticks if (start is None or _hms(t["time"]) >= start) and (end is None or _hms(t["time"]) <= end)]
        if min_volume:
            ticks = [t for t in ticks if t["volume"] >= min_volume]
        matched = len(ticks)
        if newest_first:
            ticks.reverse()
        limit = _clamp(limit, 1, MAX_ROWS)
        return {
            "instrument": inst.brief(),
            "date": fmt_date(deven),
            "jdate": jdate(deven),
            "matched": matched,
            "returned": min(matched, limit),
            "truncated": matched > limit,
            "trades": ticks[:limit],
            "units": "price/value in rial, volume in shares",
        }

    async def trade_summary(
        self,
        symbol: str,
        date: str | None = None,
        from_time: str | None = None,
        to_time: str | None = None,
        interval_minutes: int = 5,
    ) -> dict:
        inst = await self._inst(symbol)
        deven, raw = await self._ticks(inst.ins_code, date)
        start, end = _time_arg(from_time), _time_arg(to_time)
        if start or end:
            raw = [r for r in raw if (start is None or (r.get("hEven") or 0) >= start) and (end is None or (r.get("hEven") or 0) <= end)]
        official = None if (start or end) else await self._official_day(inst.ins_code, deven)
        result = shape.aggregate_ticks(
            raw,
            interval_minutes=_clamp(interval_minutes, 1, 60),
            official_volume=shape._f(official.get("qTotTran5J")) if official else None,
            official_count=shape._f(official.get("zTotTran")) if official else None,
        )
        return {"instrument": inst.brief(), "date": fmt_date(deven), "jdate": jdate(deven), **result}

    async def price_history(
        self,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 250,
        adjusted: bool = False,
        granularity: str = "daily",
    ) -> dict:
        inst = await self._inst(symbol)
        raw = await self.api.daily_prices(inst.ins_code)
        series, events = shape.shape_daily_prices(raw, adjusted=adjusted)
        start, end = _date_arg(from_date), _date_arg(to_date)
        if start:
            series = [r for r in series if int(r["date"].replace("-", "")) >= start]
        if end:
            series = [r for r in series if int(r["date"].replace("-", "")) <= end]
        try:
            series = shape.aggregate_prices(series, granularity)
        except ValueError as exc:
            raise InputError(str(exc)) from exc
        total = len(series)
        series = series[-_clamp(limit, 1, MAX_ROWS):]
        if events and series:  # only events after the first returned row change the values shown
            first_day = series[0].get("date") or series[0]["from"]  # aggregated bars carry from/to instead of one date
            events = [e for e in events if e["date"] > first_day]
        return {
            "instrument": inst.brief(),
            "adjusted": adjusted,
            "adjustment_events": events if adjusted else None,
            "total_in_range": total,
            "returned": len(series),
            "rows": series,
            "units": "rial",
            "note": "Rows are ascending by date; 'close' is the exchange closing (weighted) price, 'last' the last trade."
            + (" Prices are back-adjusted for capital increases and dividends." if adjusted else ""),
        }

    async def real_legal_flow(self, symbol: str, days: int = 10) -> dict:
        inst = await self._inst(symbol)
        days = _clamp(days, 0, 90)
        current, closing = await asyncio.gather(self.api.client_type(inst.ins_code), self.api.closing_info(inst.ins_code))
        volume, value = shape._f(closing.get("qTotTran5J")), shape._f(closing.get("qTotCap"))
        vwap = shape._safe_div(value, volume)
        out: dict[str, Any] = {
            "instrument": inst.brief(),
            "latest_session": {"date": fmt_date(closing.get("dEven")), **shape.shape_client_type(current, vwap=vwap)},
        }
        if days:
            rows = await self._client_type_rows(inst.ins_code, days)
            series = shape.shape_client_type_history(rows)
            net = [s["real_net_value"] for s in series if s["real_net_value"] is not None]
            out["history"] = series
            out["history_summary"] = {
                "days": len(series),
                "real_net_value_total": sum(net) if net else None,
                "days_with_real_inflow": sum(1 for n in net if n > 0),
                "days_with_real_outflow": sum(1 for n in net if n < 0),
            }
        out["units"] = (
            "value in rial, volume in shares. history rows are published by the exchange; latest_session values are estimated "
            "(net volume x VWAP) because the live table has volumes and counts only"
        )
        return out

    async def _client_type_rows(self, ins: str, days: int) -> list[dict]:
        """The newest ``days`` trading days of real/legal figures: one call for the whole history, per-day calls as a fallback."""
        try:
            everything = await self.api.client_type_history_all(ins)
        except (NotAvailable, UpstreamError):
            everything = []
        traded = [r for r in everything if any((r.get(k) or 0) > 0 for k in ("buy_I_Volume", "buy_N_Volume", "sell_I_Volume", "sell_N_Volume"))]
        if traded:
            return sorted(traded, key=lambda r: r.get("recDate") or 0, reverse=True)[:days]
        daily = await self.api.daily_prices(ins)
        dates = [int(r["dEven"]) for r in sorted(daily, key=lambda r: r["dEven"], reverse=True) if (r.get("zTotTran") or 0) > 0][: days + 2]
        results = await asyncio.gather(*(self.api.client_type_history(ins, d) for d in dates), return_exceptions=True)
        # today's history is not always published yet: ask for two extra dates and keep the newest `days` that exist
        return [dict(r, recDate=r.get("recDate") or d) for d, r in zip(dates, results, strict=True) if isinstance(r, dict) and r][:days]

    async def shareholders(self, symbol: str) -> dict:
        inst = await self._inst(symbol)
        info, rows = await asyncio.gather(self.api.instrument_info(inst.ins_code), self.api.shareholders_last(inst.ins_code))
        holders = shape.shape_holders(rows)
        shares_out = shape._f(info.get("zTitad"))
        listed_pct = sum(h["percent"] or 0 for h in holders)
        return {
            "instrument": inst.brief(),
            "shares_outstanding": shape._i(shares_out),
            "listed_holders": len(holders),
            "listed_percent_total": shape._r(listed_pct),
            "other_holders_percent": shape._r(100 - listed_pct),
            "top5_percent": shape._r(sum(h["percent"] or 0 for h in holders[:5])),
            "holders": holders,
            "note": "TSETMC lists holders above ~1% (major shareholders / سهامداران عمده). holder_id (valid for this snapshot) can be passed to shareholder_portfolio.",
        }

    async def _holder_series(self, inst: Instrument, holder: str, days: int) -> dict:
        """One major holder's position over time, reduced to the days on which it changed."""
        current = await self.api.shareholders_last(inst.ins_code)
        key = match_key(holder)
        found = [r for r in current if key == match_key(r.get("shareHolderShareID")) or key in match_key(r.get("shareHolderName"))]
        names = "; ".join(clean(r.get("shareHolderName")) or "?" for r in sorted(current, key=lambda r: -(r.get("perOfShares") or 0))[:8])
        if not found:
            raise InputError(f"No major holder of {inst.symbol} matches '{holder}'. Current holders: {names}")
        if len(found) > 1:
            raise InputError(f"'{holder}' matches {len(found)} holders of {inst.symbol}; be more specific: " + "; ".join(clean(r.get("shareHolderName")) or "?" for r in found[:6]))
        pick = found[0]
        rows = await self.api.holder_history(inst.ins_code, pick["shareHolderShareID"], _clamp(days, 5, 500))
        series = sorted((r for r in rows if r.get("dEven")), key=lambda r: r["dEven"])
        changes: list[dict] = []
        previous: float | None = None
        for r in series:
            shares = shape._f(r.get("numberOfShares"))
            if shares is not None and shares != previous:
                changes.append(
                    {
                        "date": fmt_date(r["dEven"]),
                        "jdate": jdate(r["dEven"]),
                        "shares": int(shares),
                        "percent": shape._f(r.get("perOfShares")),
                        "shares_change": None if previous is None else int(shares - previous),
                    }
                )
            previous = shares if shares is not None else previous
        first, last = (series[0], series[-1]) if series else ({}, {})
        net = shape._f(last.get("numberOfShares")) is not None and shape._f(first.get("numberOfShares")) is not None
        return {
            "instrument": inst.brief(),
            "holder": clean(pick.get("shareHolderName")),
            "holder_id": pick.get("shareHolderShareID"),
            "period": {"from": fmt_date(first["dEven"]) if first else None, "to": fmt_date(last["dEven"]) if last else None, "days_read": len(series)},
            "net_change_shares": int(shape._f(last["numberOfShares"]) - shape._f(first["numberOfShares"])) if net else None,
            "net_change_percent_points": shape._r((shape._f(last.get("perOfShares")) or 0) - (shape._f(first.get("perOfShares")) or 0), 3) if net else None,
            "changes": changes,
            "note": "Daily position of this holder; only days on which the number of shares changed are listed (the first row is the starting position).",
        }

    async def shareholder_history(self, symbol: str, date: str | None = None, holder: str | None = None, days: int = 250) -> dict:
        inst = await self._inst(symbol)
        if holder:
            return await self._holder_series(inst, holder, days)
        deven = _date_arg(date) or await self._latest_deven(inst.ins_code)
        rows = await self.api.shareholder_snapshots(inst.ins_code, deven)
        return {"instrument": inst.brief(), "snapshots": shape.shape_holder_snapshots(rows)}

    async def shareholder_portfolio(self, holder_id: int | str) -> dict:
        rows = await self.api.holder_portfolio(holder_id)
        holdings = []
        for r in rows:
            instrument = r.get("instrument") or {}
            holdings.append(
                {
                    "symbol": clean(instrument.get("lVal18AFC")),
                    "name": clean(instrument.get("lVal30")),
                    "shares": shape._i(r.get("numberOfShares")),
                    "percent": shape._f(r.get("perOfShares")),
                    "change_amount": shape._f(r.get("changeAmount")),
                }
            )
        holdings.sort(key=lambda h: h["percent"] or 0, reverse=True)
        return {"holder_id": holder_id, "holdings": holdings}

    async def corporate_actions(self, symbol: str) -> dict:
        inst = await self._inst(symbol)
        adjustments, capital = await asyncio.gather(self.api.price_adjustments(inst.ins_code), self.api.share_changes(inst.ins_code))
        adj = []
        for r in sorted(adjustments, key=lambda r: r.get("dEven") or 0, reverse=True):
            before, after = shape._f(r.get("pClosingNotAdjusted")), shape._f(r.get("pClosing"))
            adj.append(
                {
                    "date": fmt_date(r.get("dEven")),
                    "jdate": jdate(r.get("dEven")),
                    "price_before": before,
                    "price_after": after,
                    "factor": shape._r(shape._safe_div(after, before), 6),
                }
            )
        cap = []
        for r in sorted(capital, key=lambda r: r.get("dEven") or 0, reverse=True):
            old, new = shape._f(r.get("numberOfShareOld")), shape._f(r.get("numberOfShareNew"))
            cap.append(
                {
                    "date": fmt_date(r.get("dEven")),
                    "jdate": jdate(r.get("dEven")),
                    "shares_before": shape._i(old),
                    "shares_after": shape._i(new),
                    "increase_pct": shape.pct_change(new, old),
                }
            )
        return {"instrument": inst.brief(), "price_adjustments": adj, "capital_changes": cap}

    async def symbol_statistics(self, symbol: str) -> dict:
        inst = await self._inst(symbol)
        rows = await self.api.statistics(inst.ins_code)
        return {"instrument": inst.brief(), "metrics": shape.shape_statistics(rows)}

    async def supervisor_messages(self, symbol: str | None = None, limit: int = 10, full_text: bool = False, market: str = "bourse") -> dict:
        limit = _clamp(limit, 1, 100)
        if symbol:
            inst = await self._inst(symbol)
            rows = await self.api.messages_for(inst.ins_code)
            label: Any = inst.brief()
        else:
            # the exchange lists a few pinned old notices first, so asking for exactly `limit` rows loses recent ones
            rows = await self.api.messages_flow(_flow(market), min(max(limit * 3, 30), 200))
            label = {"market": market}
        rows = sorted(rows, key=lambda r: (r.get("dEven") or 0, r.get("hEven") or 0), reverse=True)[:limit]
        return {"scope": label, "messages": [shape.shape_message(r, full_text=full_text) for r in rows]}

    async def etf_nav(self, symbol: str) -> dict:
        inst = await self._inst(symbol)
        try:
            etf, closing = await asyncio.gather(self.api.etf(inst.ins_code), self.api.closing_info(inst.ins_code))
        except NotAvailable:
            return {"instrument": inst.brief(), "available": False, "note": "Not a fund/ETF unit, so no NAV data."}
        last = shape._f(closing.get("pDrCotVal"))
        redemption, issue = shape._f(etf.get("pRedTran")), shape._f(etf.get("pSubTran"))
        return {
            "instrument": inst.brief(),
            "available": True,
            "date": fmt_date(etf.get("deven")),
            "time": fmt_time(etf.get("hEven")),
            "last_price": last,
            "nav_redemption": redemption,
            "nav_issue": issue,
            "premium_to_redemption_nav_pct": shape.pct_change(last, redemption),
            "premium_to_issue_nav_pct": shape.pct_change(last, issue),
            "note": "pRedTran / pSubTran are the exchange's redemption (ابطال) and issue (صدور) NAV figures.",
        }

    # ------------------------------------------------------------------ Codal
    # ------------------------------------------------------------------ official lists, calendar, trading status
    async def top_lists(self, list_name: str | None = "catalogue", flow: int | str | None = None, limit: int = 20) -> dict:
        try:
            if toplists.is_catalogue(list_name):
                return toplists.catalogue(flow)
            request = toplists.resolve_top_list(str(list_name), flow, limit)
        except ValueError as exc:
            raise InputError(str(exc)) from exc
        family = request.definition.family
        try:
            if family == toplists.FAMILY_SECTORS:
                rows = await self.api.sector_top(request.top)
            else:
                fetch = {toplists.FAMILY_TRADE: self.api.trade_top, toplists.FAMILY_LIMITS: self.api.best_limits_top, toplists.FAMILY_CAP: self.api.market_cap_top}[family]
                rows = await fetch(request.site_type, request.flow, request.top)
        except NotAvailable as exc:  # the exchange answers HTTP 500 for a list it does not serve
            raise InputError(f"The exchange does not serve '{request.definition.name}' for flow {request.flow} right now (HTTP 500). Call top_lists with list_name='catalogue' for the others.") from exc
        return toplists.shape_top_list(request, rows)

    async def capital_calendar(
        self, flow: int | str | None = 1, direction: str = "upcoming", days: int = 30, limit: int = 50, kind: str = "all", today: str | None = None
    ) -> dict:
        try:
            flows = calendar_events.parse_flows(flow)
            calendar_events.check_arguments(direction, kind, days, limit)
        except ValueError as exc:
            raise InputError(str(exc)) from exc
        top = calendar_events.adjustment_fetch_size(days)
        wants_adjustments = calendar_events.sources_needed(kind, direction)[1]
        shares = await asyncio.gather(*(self.api.share_changes_by_flow(f) for f in flows))
        adjustments = await asyncio.gather(*(self.api.price_adjust_by_flow(f, top) for f in flows)) if wants_adjustments else None
        try:
            return calendar_events.capital_calendar(
                dict(zip(flows, shares, strict=True)), dict(zip(flows, adjustments, strict=True)) if adjustments else None,
                flow=flow, direction=direction, days=days, limit=limit, kind=kind, today=today, adjustments_top=top if adjustments else None,
            )
        except ValueError as exc:  # an unreadable `today`
            raise InputError(str(exc)) from exc

    async def trading_status(self, kind: str = "suspended", market: str | None = None, symbol: str | None = None, limit: int = 50) -> dict:
        try:
            plan = status.plan_trading_status(kind, market, symbol, limit)
        except ValueError as exc:
            raise InputError(str(exc)) from exc
        if plan.kind in ("suspended", "supervision"):
            fetched = await asyncio.gather(*(self.api.supervision_list(s, t) for s, t in plan.supervision_lists))
            return status.shape_supervision(dict(zip(plan.supervision_lists, fetched, strict=True)), kind=plan.kind, symbol=plan.symbol, limit=plan.limit)
        if plan.kind == "state_changes":
            return status.shape_state_changes(await self.api.state_log(plan.state_top or 200), limit=plan.limit)
        inst = await self._inst(plan.symbol or "")
        history, record = await asyncio.gather(self.api.state_history(inst.ins_code), self.api.supervision_for(inst.ins_code))
        return status.shape_symbol_history(history, instrument=inst.brief(), supervision=record, limit=plan.limit)

    # ------------------------------------------------------------------ derivatives (options, futures)
    async def option_chain(
        self,
        underlying: str | None = None,
        expiry: str | None = None,
        market: str | None = None,
        option_type: str | None = None,
        moneyness: str | None = None,
        min_volume: float = 0,
        min_open_interest: float = 0,
        strike_window_pct: float | None = None,
        sort_by: str | None = None,
        limit: int | None = None,
    ) -> dict:
        try:
            flow = derivatives.option_flow(market)
        except ValueError as exc:
            raise InputError(str(exc)) from exc
        rows = await self.api.option_market_watch(flow)
        try:
            return derivatives.option_chain(
                rows, underlying, expiry, market=market, option_type=option_type, moneyness=moneyness, min_volume=min_volume,
                min_open_interest=min_open_interest, strike_window_pct=strike_window_pct, sort_by=sort_by, limit=limit,
            )
        except ValueError as exc:
            raise InputError(str(exc)) from exc

    async def futures_market(
        self, underlying: str | None = None, sort_by: str | None = None, limit: int | None = None, descending: bool | None = None
    ) -> dict:
        rows = await self.api.future_market_watch()
        try:
            return derivatives.futures_market(rows, underlying, sort_by=sort_by, descending=descending, limit=limit)
        except ValueError as exc:
            raise InputError(str(exc)) from exc

    async def codal_filings(
        self,
        symbol: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        title_contains: str | None = None,
        category: int = -1,
        letter_type: int = -1,
        limit: int = 20,
        page: int = 1,
    ) -> dict:
        params: dict[str, Any] = {"Category": category, "LetterType": letter_type, "PageNumber": max(1, page)}
        if symbol:
            inst = await self._inst(symbol)
            params["Symbol"] = inst.symbol
        for key, value in (("FromDate", from_date), ("ToDate", to_date)):
            deven = _date_arg(value)
            if deven:
                jy, jm, jd = _jalali(deven)
                params[key] = f"{jy:04d}/{jm:02d}/{jd:02d}"
        wanted = _clamp(limit, 1, 100)
        needle = match_key(title_contains) if title_contains else None
        letters: list[dict] = []
        scanned = pages_read = 0
        current, total_pages, total = params["PageNumber"], None, None
        while True:  # a title filter is applied here, so keep reading pages until enough titles match
            params["PageNumber"] = current
            data = await self.api.codal_search(**params)
            total, total_pages = data.get("Total"), data.get("Page")
            page_letters = [shape.shape_codal_letter(r, CODAL_SITE) for r in data.get("Letters", [])]
            scanned += len(page_letters)
            pages_read += 1
            letters += [r for r in page_letters if needle is None or needle in match_key(r["title"])]
            exhausted = not page_letters or bool(total_pages and current >= total_pages)
            if needle is None or len(letters) >= wanted or exhausted or pages_read >= CODAL_SCAN_PAGES:
                break
            current += 1
        out: dict[str, Any] = {
            "total_matches": total if needle is None else None,
            "total_before_title_filter": total if needle else None,
            "pages": total_pages,
            "page": params["PageNumber"] if needle is None else current - pages_read + 1,
            "returned": len(letters[:wanted]),
            "filings": letters[:wanted],
            "note": "published/sent are Jalali timestamps as shown on Codal. Pass 'page' to read older filings.",
        }
        if needle:
            out["title_filter"] = {"scanned_filings": scanned, "scanned_pages": pages_read, "next_page": None if exhausted else current + 1}
        return {k: v for k, v in out.items() if v is not None}

    async def codal_company(self, symbol: str) -> dict:
        inst = await self._inst(symbol)
        data = await self.api.codal_publisher(inst.symbol)
        if not data:
            return {"instrument": inst.brief(), "available": False}
        return {
            "instrument": inst.brief(),
            "available": True,
            "name": clean(data.get("name")),
            "isic": data.get("isic"),
            "ceo": clean(data.get("executiveManager")),
            "address": clean(data.get("address")),
            "phone": data.get("telNo"),
            "fax": data.get("faxNo"),
            "activity": clean(data.get("activitySubject")),
        }

    # ------------------------------------------------------------------ everything about one symbol
    async def symbol_overview(self, symbol: str) -> dict:
        inst = await self._inst(symbol)
        ins = inst.ins_code

        missing: list[str] = []

        async def safe(name: str, coro: Any) -> Any:
            """Optional sections must not sink the whole dossier; say which ones are missing instead."""
            try:
                return await asyncio.wait_for(coro, timeout=SECTION_TIMEOUT)
            except (UpstreamError, asyncio.TimeoutError):
                missing.append(name)
                return None

        info, identity, closing, book, client, holders, filings, messages = await asyncio.gather(
            self.api.instrument_info(ins),
            safe("identity", self.api.identity(ins)),
            self.api.closing_info(ins),
            safe("order_book", self.api.best_limits(ins)),
            safe("real_legal", self.api.client_type(ins)),
            safe("major_shareholders", self.api.shareholders_last(ins)),
            safe("recent_filings", self.api.codal_search(Symbol=inst.symbol, PageNumber=1)),
            safe("recent_supervisor_messages", self.api.messages_for(ins)),
        )
        quote = shape.shape_quote(closing, info)
        thr = info.get("staticThreshold") or {}
        out: dict[str, Any] = {
            "identity": shape.shape_identity(info, identity),
            "quote": quote,
            "order_book": shape.shape_order_book(book or [], shape._f(thr.get("psGelStaMax")), shape._f(thr.get("psGelStaMin"))),
        }
        if client:
            out["real_legal"] = shape.shape_client_type(client, vwap=quote["vwap"])
        if holders:
            top = shape.shape_holders(holders)
            out["major_shareholders"] = {"top5_percent": shape._r(sum(h["percent"] or 0 for h in top[:5])), "top": top[:5]}
        if filings:
            out["recent_filings"] = [shape.shape_codal_letter(r, CODAL_SITE) for r in filings.get("Letters", [])[:5]]
        if messages:
            recent = sorted(messages, key=lambda r: (r.get("dEven") or 0, r.get("hEven") or 0), reverse=True)[:3]
            out["recent_supervisor_messages"] = [shape.shape_message(r, limit=240) for r in recent]
        if missing:
            out["unavailable_sections"] = sorted(set(missing))
        return out


# ---------------------------------------------------------------------- module helpers
def _real_net_value(rows: list[dict], flows: dict[str, dict]) -> int:
    """Estimated real-person net inflow of a group of symbols: net real volume x each symbol's vwap, rial."""
    total = 0.0
    for r in rows:
        f = flows.get(r["instrument_id"])
        if f:
            net = (shape._f(f.get("buy_I_Volume")) or 0) - (shape._f(f.get("sell_I_Volume")) or 0)
            total += net * (r["vwap"] or r["last"] or 0)
    return int(total)


async def _just(value: Any) -> Any:
    return value


def _hms(text: str | None) -> int:
    return int(ascii_digits((text or "00:00:00").replace(":", "")))


def _jalali(deven: int) -> tuple[int, int, int]:
    from .dates import gregorian_to_jalali

    d = to_date(deven)
    return gregorian_to_jalali(d.year, d.month, d.day)


_COMPACT = (
    "symbol", "name", "last", "last_pct", "close", "close_pct", "volume", "value", "trades",
    "pe", "market_cap", "at_upper_limit", "at_lower_limit", "industry",
)


def _compact_watch(row: dict, extra: tuple[str, ...] = ()) -> dict:
    out = {k: row.get(k) for k in _COMPACT}
    for key in extra:
        if key in row:
            out[key] = row[key]
    return out


def utc_now() -> dt.datetime:  # pragma: no cover - tiny wrapper for easy patching
    return dt.datetime.now(dt.timezone.utc)
