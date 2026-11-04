"""Contract scenarios: whole-market tools, indices and the exchange's lists.

Each check compares the tool's output with the recorded upstream payload it was computed from, so it keeps
working when the recordings are refreshed; literals appear only for dates that are history by now.
"""

from __future__ import annotations

import datetime as dt
from math import isclose

from contract_helpers import (
    assert_keys,
    by_symbol,
    clean,
    descending,
    hms,
    in_session,
    is_jdate,
    iso,
    one,
    pct,
    pick,
)
from contract_replay import scenario

COMPACT = "symbol name last last_pct close close_pct volume value trades pe market_cap at_upper_limit at_lower_limit industry"


def watch_rows(run):
    return run.rec.body("GetMarketWatch")["marketwatch"]


def traded_stock(raw):
    """The site's own rule for «سهام» in the market watch: share codes, no TAL board, no energy bourse, no housing facilities."""
    return (
        raw["yVal"] in (300, 303, 313)
        and raw["cGrValCot"].strip() not in ("F3", "G3", "U3")
        and raw["flow"] != 6
        and not clean(raw["lva"]).startswith(("تسه", "تملی"))
        and (raw["qtj"] or 0) > 0
    )


def industry_of(run, raw):
    """The industry name of a market-feed row: its sector code against the static table («01» and «1» are the same code)."""
    names = {
        str(int(r["code"])): clean(r["name"])
        for r in run.rec.body("GetStaticData")["staticData"]
        if r["type"] == "IndustrialGroup"
    }
    return names.get(str(int(raw["csv"])))


# ----------------------------------------------------------------------------- market state and indices
@scenario("market_status", "market_status")
def _market_status(run):
    out, raw = run.out, run.rec.body("GetMarketOverview")["marketOverview"]
    assert_keys(
        out,
        "tehran_time tehran_jdate weekday is_trading_weekday holiday is_trading_day day_status within_session_hours session "
        "next_session upcoming_holidays holiday_calendar bourse gateway exchange_server_time",
    )
    # the clock is frozen at the recording time
    assert out["tehran_time"] == run.now.strftime("%Y-%m-%d %H:%M:%S")
    assert out["weekday"] == run.now.strftime("%A")
    assert out["is_trading_weekday"] is (run.now.weekday() in (5, 6, 0, 1, 2))  # Saturday-Wednesday
    assert out["within_session_hours"] is in_session(run.now)
    # the holiday calendar: a trading day is a Saturday-Wednesday that is not a holiday, and the next session is never in the past
    assert out["is_trading_day"] is (out["is_trading_weekday"] and out["holiday"] is None)
    assert out["day_status"] in {"open", "before_open", "after_close", "weekend", "holiday"}
    assert out["next_session"]["date"] >= run.now.strftime("%Y-%m-%d") and out["next_session"]["opens_at"] == "09:00"
    assert all(h["date"] > run.now.strftime("%Y-%m-%d") for h in out["upcoming_holidays"])
    assert out["holiday_calendar"]["covers_this_year"] is True
    assert out["tehran_jdate"].startswith("14") and out["tehran_jdate"].count("/") == 2
    assert out["bourse"]["index"]["value"] == raw["indexLastValue"]
    assert out["bourse"]["market_state_code"] == raw["marketState"]
    dates = run.rec.body("MarketDate")
    assert out["gateway"] == [
        {
            "market": clean(d["stockType"]),
            "open_time": d["openTime"],
            "close_time": d["closeTime"],
            "is_open": d["isOpen"],
        }
        for d in dates
    ]
    assert out["exchange_server_time"] == str(run.rec.body("GetTime")).strip().strip('"')


@scenario("market_overview", "market_overview")
def _market_overview(run):
    out, raw = run.out, run.rec.body("GetMarketOverview")["marketOverview"]
    assert_keys(
        out,
        "market market_state market_state_code as_of index equal_weight_index trades volume value market_cap units",
    )
    assert out["market"] == "bourse" and out["units"] == "rial"
    assert out["as_of"] == {
        "date": iso(raw["marketActivityDEven"]),
        "time": hms(raw["marketActivityHEven"]),
    }
    assert out["index"] == {
        "value": raw["indexLastValue"],
        "change": raw["indexChange"],
        "change_pct": pct(raw["indexLastValue"], raw["indexLastValue"] - raw["indexChange"]),
    }
    assert out["equal_weight_index"] == {
        "value": raw["indexEqualWeightedLastValue"],
        "change": raw["indexEqualWeightedChange"],
    }
    assert out["trades"] == raw["marketActivityZTotTran"]
    assert out["volume"] == int(raw["marketActivityQTotTran"]) and out["value"] == int(
        raw["marketActivityQTotCap"]
    )
    assert out["market_cap"] == int(raw["marketValue"])
    assert out["market_state"] == clean(raw["marketStateTitle"])


@scenario("indices", "indices")
def _indices(run):
    out, raw = run.out, run.rec.body("GetIndexB1LastAll/All/1")["indexB1"]
    assert_keys(out, "market headline_indices industry_indices")
    assert out["market"] == "bourse"
    assert len(out["headline_indices"]) + len(out["industry_indices"]) == len(raw)
    assert all(r["headline"] for r in out["headline_indices"]) and not any(
        r["headline"] for r in out["industry_indices"]
    )
    assert descending(r["change_pct"] for r in out["industry_indices"])  # strongest industry first
    free_float = one(out["headline_indices"], lambda r: r["name"] == "شاخص آزاد شناور")
    assert_keys(free_float, "name code headline ins_code value change change_pct high low time")
    row = one(raw, lambda r: r["insCode"] == free_float["ins_code"])
    assert (free_float["value"], free_float["change"], free_float["change_pct"]) == (
        row["xDrNivJIdx004"],
        row["indexChange"],
        row["xVarIdxJRfV"],
    )
    assert (free_float["high"], free_float["low"], free_float["time"]) == (
        row["xPhNivJIdx004"],
        row["xPbNivJIdx004"],
        hms(row["hEven"]),
    )
    metals = one(out["industry_indices"], lambda r: r["code"] == "27")
    assert (
        metals["name"] == "فلزات اساسی"
    )  # the exchange writes «27-فلزات اساسی»: code and name are split


# ----------------------------------------------------------------------------- whole-market tables
@scenario("market_watch", "market_watch", limit=10)
def _market_watch(run):
    out, raw = run.out, watch_rows(run)
    assert_keys(out, "total_instruments source matched returned sorted_by rows units")
    assert (out["source"], out["sorted_by"], out["units"], out["returned"]) == (
        "tsetmc",
        "value",
        "rial",
        10,
    )
    assert out["total_instruments"] == len(
        raw
    )  # the recording holds a fixed set of instruments, not the whole market
    assert out["matched"] == sum(1 for r in raw if traded_stock(r))
    assert descending(r["value"] for r in out["rows"])
    assert out["rows"][0]["value"] == max(int(r["qtc"]) for r in raw if traded_stock(r))
    for row in out["rows"]:
        assert_keys(row, COMPACT)
    top = out["rows"][0]
    r = by_symbol(raw, top["symbol"])
    assert (top["last"], top["close"], top["volume"], top["value"], top["trades"]) == (
        r["pdv"],
        r["pcl"],
        int(r["qtj"]),
        int(r["qtc"]),
        int(r["ztt"]),
    )
    assert top["last_pct"] == pct(r["pdv"], r["py"]) and top["close_pct"] == pct(r["pcl"], r["py"])
    assert top["market_cap"] == int(r["pcl"] * r["ztd"])
    assert top["industry"] == industry_of(run, r)
    assert top["pe"] == (float(r["pe"]) if r["pe"] and float(r["pe"]) > 0 else None)
    assert top["at_upper_limit"] == (r["pdv"] >= r["pMax"]) and top["at_lower_limit"] == (
        r["pdv"] <= r["pMin"]
    )


@scenario("top_movers_real_inflow", "top_movers", kind="real_inflow", limit=10)
def _top_movers_real_inflow(run):
    out, raw = run.out, watch_rows(run)
    flows = {r["insCode"]: r for r in run.rec.body("GetClientTypeAll")["clientTypeAllDto"]}
    assert_keys(out, "kind count rows note")
    assert out["kind"] == "real_inflow" and out["count"] == len(out["rows"]) == 10
    assert "estimates" in out["note"]
    assert descending(r["real_net_value_estimated"] for r in out["rows"])
    for row in out["rows"]:
        assert_keys(
            row,
            COMPACT
            + " real_net_volume real_net_value_estimated real_buyer_power real_buyers real_sellers",
        )
        market = by_symbol(raw, row["symbol"])
        flow = flows[market["insCode"]]
        net = flow["buy_I_Volume"] - flow["sell_I_Volume"]
        assert (row["real_net_volume"], row["real_buyers"], row["real_sellers"]) == (
            int(net),
            flow["buy_CountI"],
            flow["sell_CountI"],
        )
        assert isclose(
            row["real_net_value_estimated"], net * market["qtc"] / market["qtj"], rel_tol=1e-3
        )  # net volume x VWAP
        power = (flow["buy_I_Volume"] / flow["buy_CountI"]) / (
            flow["sell_I_Volume"] / flow["sell_CountI"]
        )
        assert isclose(row["real_buyer_power"], power, abs_tol=0.01)


@scenario("top_movers_buy_queue", "top_movers", kind="buy_queue", limit=10)
def _top_movers_buy_queue(run):
    out, raw = run.out, watch_rows(run)
    assert_keys(out, "kind count rows note")
    assert (
        out["kind"] == "buy_queue" and out["count"] == len(out["rows"]) > 0 and out["note"] is None
    )
    assert descending(r["queue_value"] for r in out["rows"])  # biggest queue first
    for row in out["rows"]:
        assert_keys(row, COMPACT + " queue_volume queue_orders queue_value")
        assert row["at_upper_limit"] and row["queue_volume"] > 0 and row["queue_orders"] > 0
    top = out["rows"][0]
    market = by_symbol(raw, top["symbol"])
    book = run.rec.body(f"/BestLimits/{market['insCode']}")["bestLimits"]
    at_limit = [
        level for level in book if level["pMeDem"] >= market["pMax"]
    ]  # bids at the ceiling make the queue
    assert top["queue_volume"] == sum(level["qTitMeDem"] for level in at_limit)
    assert top["queue_orders"] == sum(level["zOrdMeDem"] for level in at_limit)
    assert top["queue_value"] == top["queue_volume"] * market["pMax"]


@scenario("industry_summary", "industry_summary", limit=10)
def _industry_summary(run):
    out, raw = run.out, watch_rows(run)
    assert_keys(out, "total_industries industries units")
    assert out["units"] == "rial"
    names = {industry_of(run, r) or "?" for r in raw if traded_stock(r)}
    assert out["total_industries"] == len(names) and len(out["industries"]) == 10
    assert descending(g["value"] for g in out["industries"])
    top = out["industries"][0]
    assert_keys(
        top,
        "industry symbols value volume market_cap avg_change_pct cap_weighted_change_pct index_effect top_gainer top_loser real_net_value_estimated in_buy_queue in_sell_queue",
    )
    members = [
        r for r in raw if traded_stock(r) and (industry_of(run, r) or "?") == top["industry"]
    ]
    assert top["symbols"] == len(members)
    assert top["value"] == sum(int(r["qtc"]) for r in members) and top["volume"] == sum(
        int(r["qtj"]) for r in members
    )
    assert top["market_cap"] == sum(int(r["pcl"] * r["ztd"]) for r in members)
    changes = [pct(r["pdv"], r["py"]) for r in members]
    assert top["top_gainer"] == {
        "symbol": clean(by_symbol(raw, top["top_gainer"]["symbol"])["lva"]),
        "pct": max(changes),
    }
    assert top["top_loser"]["pct"] == min(changes)
    flows = {r["insCode"]: r for r in run.rec.body("GetClientTypeAll")["clientTypeAllDto"]}
    estimate = sum(
        (flows[r["insCode"]]["buy_I_Volume"] - flows[r["insCode"]]["sell_I_Volume"])
        * r["qtc"]
        / r["qtj"]
        for r in members
        if r["insCode"] in flows
    )
    assert isclose(top["real_net_value_estimated"], estimate, rel_tol=1e-3)


@scenario("index_contributors", "index_contributors", limit=10)
def _index_contributors(run):
    out, raw = run.out, watch_rows(run)
    gateway = {
        clean(item["instrumentName"]): item for item in run.rec.body("MarketWatchCash")["Items"]
    }
    assert_keys(out, "positive negative unit")
    assert out["unit"] == "index points" and len(out["positive"]) == len(out["negative"]) == 10
    assert descending(r["effect_on_index"] for r in out["positive"])
    assert descending(-r["effect_on_index"] for r in out["negative"])
    assert out["positive"][0]["effect_on_index"] > 0 > out["negative"][0]["effect_on_index"]
    for row in out["positive"] + out["negative"]:
        assert_keys(row, "symbol effect_on_index last_pct industry")
        assert row["effect_on_index"] == float(
            gateway[row["symbol"]]["effectonIndex"]
        )  # the exchange's own figure, in points
        market = by_symbol(raw, row["symbol"])
        assert row["last_pct"] == pct(market["pdv"], market["py"]) and row[
            "industry"
        ] == industry_of(run, market)


@scenario("market_snapshot", "market_snapshot", date="2026-11-03", security_type="stock", limit=10)
def _market_snapshot(run):
    out, raw = (
        run.out,
        run.rec.body("GetInstrmentsHistoryInDay/20261103")[
            "closingPriceDailyHistoryWithInstDetails"
        ],
    )
    assert_keys(out, "date jdate traded_instruments rows units")
    assert (out["date"], out["jdate"], out["units"]) == ("2026-11-03", "1405/08/12", "rial")
    assert descending(r["value"] for r in out["rows"]) and len(out["rows"]) == 10
    assert out["traded_instruments"] >= 10 and {r["type"] for r in out["rows"]} == {"سهام"}
    for row in out["rows"]:
        assert_keys(
            row,
            "symbol name close last yesterday change_pct open high low volume value trades instrument_id type",
        )
        r = pick(raw, lambda x: x["instrumentID"], row["instrument_id"])
        assert (row["close"], row["last"], row["yesterday"]) == (
            r["pClosing"],
            r["pDrCotVal"],
            r["priceYesterday"],
        )
        assert (row["open"], row["high"], row["low"]) == (
            r["priceFirst"],
            r["priceMax"],
            r["priceMin"],
        )
        assert (row["volume"], row["value"], row["trades"]) == (
            int(r["qTotTran5J"]),
            int(r["qTotCap"]),
            int(r["zTotTran"]),
        )
        assert row["change_pct"] == pct(r["pClosing"], r["priceYesterday"]) and row["trades"] > 0


@scenario(
    "screen_stocks",
    "screen_stocks",
    filter="close_pct > 0 and volume > 1.2 * avg(volume, 5)",
    limit=10,
)
def _screen_stocks(run):
    out, raw = run.out, watch_rows(run)
    overview = run.rec.body("GetMarketOverview")["marketOverview"]
    tables = {
        int(rec.url.rsplit("/", 1)[1]): rec.body["closingPriceDailyHistoryWithInstDetails"]
        for rec in run.rec.find("GetInstrmentsHistoryInDay")
    }
    full_days = sorted(
        (d for d, rows in tables.items() if sum(1 for r in rows if r["zTotTran"]) >= 20),
        reverse=True,
    )[:5]
    assert_keys(
        out,
        "filter preset universe as_of history matched returned sorted_by descending rows units notes elapsed_seconds",
    )
    assert (
        out["filter"] == "(close_pct > 0 and volume > 1.2 * avg(volume, 5))"
        and out["preset"] is None
    )
    assert out["as_of"]["date"] == iso(overview["marketActivityDEven"]) and is_jdate(
        out["as_of"]["jdate"]
    )
    assert out["as_of"]["session_open"] is in_session(run.now)
    assert out["universe"] == {
        "instruments": sum(1 for r in raw if traded_stock(r)),
        "of_total_in_watch": len(raw),
        "market": None,
        "security_type": "سهام",
        "industry": None,
    }
    assert out["history"] == {
        "trading_days_loaded": 5,
        "from": iso(full_days[-1]),
        "to": iso(full_days[0]),
        "adjusted_for_capital_changes": True,
    }
    assert out["matched"] >= out["returned"] == len(out["rows"]) == 10
    assert (out["sorted_by"], out["descending"]) == ("value", True)
    if in_session(run.now):  # today's figures are partial while the session is open
        assert "session is still open" in out["notes"][0]
    else:
        assert out["notes"] == []
    assert isinstance(out["elapsed_seconds"], float)
    assert descending(r["value"] for r in out["rows"])
    for row in out["rows"]:  # every hit satisfies the condition it was selected by
        assert set(row) == {
            "symbol",
            "last",
            "close_pct",
            "volume",
            "value",
            "avg(volume, 5)",
        }  # the filter's own terms are shown as evidence
        assert row["close_pct"] > 0 and row["volume"] > 1.2 * row["avg(volume, 5)"]
    top = out["rows"][0]
    market = by_symbol(raw, top["symbol"])
    assert (top["last"], top["volume"], top["value"]) == (
        market["pdv"],
        int(market["qtj"]),
        int(market["qtc"]),
    )
    past = [
        one(tables[d], lambda r: r["instrumentID"] == market["insID"])["qTotTran5J"]
        for d in full_days
    ]
    assert isclose(top["avg(volume, 5)"], sum(past) / 5, rel_tol=1e-6)


@scenario("screener_reference", "screener_reference")
def _screener_reference(run):
    out = run.out
    assert not run.rec.items  # the reference is built into the server
    assert_keys(out, "syntax fields field_note functions limits presets preset_note examples")
    assert {"close", "volume", "close_pct", "value", "real_net_value"} <= set(out["fields"])
    assert out["fields"]["volume"].startswith("shares |") and out["fields"]["close"].startswith(
        "rial |"
    )  # unit | description
    assert all(
        any(name in signature for signature in out["functions"])
        for name in ("avg(", "highest", "count(")
    )
    assert {"volume_surge", "smart_money", "buy_queue"} <= set(out["presets"])
    assert out["syntax"] and out["examples"]


@scenario("market_holder_moves", "market_holder_moves", limit=10)
def _market_holder_moves(run):
    out, raw = run.out, run.rec.body("GetShareHolderChanges")
    assert_keys(out, "dates moves total_moves note")
    assert out["dates"] == [iso(d) for d in raw["dates"]] and len(out["dates"]) == 5
    assert len(out["moves"]) == 10 and descending(abs(m["change_pct"]) for m in out["moves"])
    changed = [
        (h["name"], i)
        for h in raw["shareHoldersChanges"]
        for i in h["insList"]
        if i["firstDay"] != i["fifthDay"]
    ]
    assert out["total_moves"] == len(changed)
    for move in out["moves"]:
        assert_keys(move, "holder instrument shares_first_day shares_last_day change change_pct")
        identity = (move["holder"], move["instrument"], move["shares_first_day"])
        holder, item = pick(
            changed,
            lambda c: (clean(c[0]), clean(c[1]["name"]), int(c[1]["firstDay"])),
            identity,
            "move",
        )
        assert (move["shares_first_day"], move["shares_last_day"]) == (
            int(item["firstDay"]),
            int(item["fifthDay"]),
        )
        assert move["change"] == move["shares_last_day"] - move["shares_first_day"]
        assert move["change_pct"] == pct(item["fifthDay"], item["firstDay"])


@scenario("supervisor_messages_market", "supervisor_messages", limit=5)
def _supervisor_messages_market(run):
    out, raw = run.out, run.rec.body("GetMsgByFlow/1")["msg"]
    assert_keys(out, "scope messages")
    assert out["scope"] == {"market": "bourse"} and len(out["messages"]) == 5
    newest = sorted(raw, key=lambda r: (r["dEven"], r["hEven"]), reverse=True)[
        :5
    ]  # pinned old notices must not crowd out new ones
    for message, row in zip(out["messages"], newest, strict=True):
        assert_keys(message, "date jdate time title text truncated")
        assert (message["date"], message["time"], message["title"]) == (
            iso(row["dEven"]),
            hms(row["hEven"]),
            clean(row["tseTitle"]),
        )
        assert (
            message["text"].startswith(clean(row["tseDesc"])[:50]) and len(message["text"]) <= 501
        )


# ----------------------------------------------------------------------------- the exchange's own lists
@scenario("top_lists_catalogue", "top_lists")
def _top_lists_catalogue(run):
    out = run.out
    assert not run.rec.items  # the catalogue is built into the server
    assert_keys(out, "count lists column_sets flows usage notes")
    assert out["count"] == len(out["lists"]) >= 60
    names = {item["name"] for item in out["lists"]}
    assert {"price_gainers", "block_trades", "largest_bids", "sectors_by_value"} <= names
    for item in out["lists"]:
        assert_keys(
            {k: v for k, v in item.items() if k not in ("note", "sorted_by")},
            "name group title description flows columns",
        )  # note and sorted_by are optional
        assert item["columns"] in out["column_sets"]
    assert out["flows"]["1"] == "بورس" and out["flows"]["2"] == "فرابورس"


@scenario("top_lists_gainers", "top_lists", list_name="price_gainers", limit=10)
def _top_lists_gainers(run):
    out, raw = run.out, run.rec.body("GetTradeTop/PClosingTop/1/10")["tradeTop"]
    assert_keys(
        out,
        "list title description group flow market exchange_type sorted_by as_of as_of_jdate count rows units",
    )
    assert (out["list"], out["flow"], out["market"], out["exchange_type"], out["sorted_by"]) == (
        "price_gainers",
        1,
        "بورس",
        "PClosingTop",
        "close_pct desc",
    )
    assert out["units"] == {
        "prices": "rial",
        "value": "rial",
        "volume": "shares (contracts for derivatives)",
    }
    assert out["count"] == len(out["rows"]) == len(raw) == 10
    assert [r["rank"] for r in out["rows"]] == list(
        range(1, 11)
    )  # the exchange's own order is kept
    for row, r in zip(out["rows"], raw, strict=True):
        assert_keys(
            row,
            "rank symbol name ins_code yesterday close close_pct last last_pct low high trades volume value",
        )
        assert (
            row["symbol"] == clean(r["instrument"]["lVal18AFC"]) and row["ins_code"] == r["insCode"]
        )
        assert (row["yesterday"], row["close"], row["low"], row["high"]) == (
            r["priceYesterday"],
            r["pClosing"],
            r["priceMin"],
            r["priceMax"],
        )
        assert (row["volume"], row["value"], row["trades"]) == (
            int(r["qTotTran5J"]),
            int(r["qTotCap"]),
            int(r["zTotTran"]),
        )
        assert row["close_pct"] == pct(r["pClosing"], r["priceYesterday"])
    assert out["as_of"] == iso(max(r["dEven"] for r in raw if r["dEven"])) and is_jdate(
        out["as_of_jdate"]
    )


# ----------------------------------------------------------------------------- calendar and status
def share_events(run):
    return run.rec.body("GetInstrumentShareChangeByFlow/1")["instrumentShareChange"]


@scenario("capital_calendar_upcoming", "capital_calendar")
def _capital_calendar_upcoming(run):
    out, raw = run.out, share_events(run)
    today = run.now.date()
    assert_keys(
        out,
        "today today_jdate direction days kind window flows total_in_window count counts events coverage hidden_roundtrip_rows notes",
    )
    assert (
        out["today"] == today.isoformat()
        and out["direction"] == "upcoming"
        and out["days"] == 30
        and out["kind"] == "all"
    )
    assert out["window"] == {
        "from": (today + dt.timedelta(days=1)).isoformat(),
        "to": (today + dt.timedelta(days=30)).isoformat(),
    }
    assert out["flows"] == {"1": "بورس"}
    assert out["count"] == len(out["events"]) == out["total_in_window"] > 0
    assert sum(out["counts"].values()) == out["count"]
    assert out["coverage"]["share_changes_latest"] == iso(max(r["dEven"] for r in raw))
    assert all(e["status"] == "upcoming" and e["days_from_today"] > 0 for e in out["events"])
    event = out["events"][0]
    assert_keys(
        event,
        "date jdate days_from_today status symbol name ins_code market flow shares_before shares_after kind added_shares increase_pct ratio label",
    )
    row = one(
        raw,
        lambda r: r["insCode"] == event["ins_code"] and iso(r["dEven"]) == event["date"],
        "share change",
    )
    assert (event["shares_before"], event["shares_after"]) == (
        int(row["numberOfShareOld"]),
        int(row["numberOfShareNew"]),
    )
    assert (
        event["kind"] == "capital_increase"
        and event["added_shares"] == event["shares_after"] - event["shares_before"]
    )
    assert event["increase_pct"] == pct(row["numberOfShareNew"], row["numberOfShareOld"])
    assert event["days_from_today"] == (dt.date.fromisoformat(event["date"]) - today).days


@scenario("capital_calendar_recent", "capital_calendar", direction="recent", days=30)
def _capital_calendar_recent(run):
    out, today = run.out, run.now.date()
    adjustments = run.rec.body("GetPriceAdjustByFlow/1")["priceAdjust"]
    assert out["direction"] == "recent" and out["window"] == {
        "from": (today - dt.timedelta(days=30)).isoformat(),
        "to": today.isoformat(),
    }
    assert out["count"] == len(out["events"]) > 0 and sum(out["counts"].values()) == out["count"]
    assert set(out["counts"]) <= {
        "capital_increase",
        "capital_decrease",
        "price_adjustment",
        "rights_symbol",
    }
    assert all(e["status"] == "past" and e["days_from_today"] <= 0 for e in out["events"])
    assert descending(e["date"] for e in out["events"])
    first = next(e for e in out["events"] if e["kind"] == "price_adjustment")
    assert_keys(
        first,
        "date jdate days_from_today status symbol name ins_code market flow kind price_before price_after factor adjustment_pct label",
    )
    row = one(
        adjustments,
        lambda r: (
            clean(r["instrument"]["lVal18AFC"]) == first["symbol"]
            and iso(r["dEven"]) == first["date"]
        ),
        "price adjustment",
    )
    assert (first["price_before"], first["price_after"]) == (
        row["pClosingNotAdjusted"],
        row["pClosing"],
    )
    assert first["factor"] == round(row["pClosing"] / row["pClosingNotAdjusted"], 6) and first[
        "adjustment_pct"
    ] == pct(row["pClosing"], row["pClosingNotAdjusted"])
    assert out["coverage"]["price_adjustments_to"] == iso(max(r["dEven"] for r in adjustments))
    assert out["coverage"]["price_adjustments_from"] == iso(min(r["dEven"] for r in adjustments))


@scenario("trading_status_suspended", "trading_status", limit=10)
def _trading_status_suspended(run):
    out = run.out
    lists = [rec.body["supervision"] for rec in run.rec.find("GetSupervisionListBySourceID")]
    assert_keys(out, "kind meaning total count summary rows notes")
    assert out["kind"] == "suspended" and out["count"] == len(out["rows"]) == 10
    assert out["total"] == sum(len(rows) for rows in lists)
    assert sum(m["suspended"] for m in out["summary"].values()) == out["total"]
    assert set(out["summary"]) == {"بورس", "فرابورس"}
    known = {clean(r["instrument"]["lVal18AFC"]): r for rows in lists for r in rows}
    for row in out["rows"]:
        assert_keys(
            row, "symbol name ins_code market status status_title since since_jdate reasons extra"
        )
        assert (
            row["status"] == "suspended" and row["status_title"] == "تعلیق شده" and row["reasons"]
        )
        assert row["ins_code"] == known[row["symbol"]]["insCode"]
        assert "<br>" not in "".join(
            row["reasons"]
        )  # the exchange's markup is turned into plain lines


@scenario("trading_status_state_changes", "trading_status", kind="state_changes", limit=10)
def _trading_status_state_changes(run):
    out, raw = run.out, run.rec.body("GetInstrumentStateTop/200")["instrumentState"]
    assert_keys(out, "kind records_read symbols_in_sample count rows sample state_codes notes")
    assert (
        out["kind"] == "state_changes"
        and out["records_read"] == len(raw)
        and out["count"] == len(out["rows"]) == 10
    )
    assert set(out["state_codes"]) == {"A", "AR", "AS", "I", "IR", "IS"}
    assert out["symbols_in_sample"] == len({r["insCode"] for r in raw})
    assert out["sample"]["records_by_state"] == {
        s: sum(1 for r in raw if r["cEtaval"].strip() == s)
        for s in out["sample"]["records_by_state"]
    }
    assert sum(out["sample"]["records_by_state"].values()) == len(raw)
    assert out["sample"]["to"] == iso(max(r["dEven"] for r in raw))
    for row in out["rows"]:
        assert_keys(
            row,
            "symbol name ins_code date jdate time state state_title category orders_accepted trading",
        )
        assert row["state"] in out["state_codes"] and row["trading"] == (row["state"] == "A")
    newest = max(raw, key=lambda r: (r["dEven"], r["hEven"]))
    assert (
        out["rows"][0]["time"] == hms(newest["hEven"])
        and out["rows"][0]["state"] == newest["cEtaval"].strip()
    )


# ----------------------------------------------------------------------------- index history and members
def index_close(raw_rows, deven):
    return one(raw_rows, lambda r: r["dEven"] == deven, f"index row {deven}")["xNivInuClMresIbs"]


@scenario(
    "index_history_daily",
    "index_history",
    index="شاخص کل",
    from_date="2026-09-01",
    to_date="2026-10-31",
)
def _index_history_daily(run):
    out, raw = run.out, run.rec.body("GetIndexB2History")["indexB2"]
    assert_keys(
        out,
        "index units data_available granularity rows_in_range returned truncated next_to_date rows summary data_quality note",
    )
    assert out["index"] == {
        "name": "شاخص کل",
        "ins_code": raw[0]["insCode"] and str(raw[0]["insCode"]),
        "code": None,
        "market": "bourse",
        "headline": True,
    }
    assert (
        out["units"] == "index points (not rial)"
        and out["granularity"] == "daily"
        and out["truncated"] is False
    )
    assert out["data_available"] == {
        "from": iso(min(r["dEven"] for r in raw)),
        "to": iso(max(r["dEven"] for r in raw)),
        "rows": len(raw),
    }
    rows = out["rows"]
    assert out["rows_in_range"] == out["returned"] == len(rows) == 43
    assert (
        [r["date"] for r in rows] == sorted(r["date"] for r in rows)
        and rows[0]["date"] == "2026-09-01"
        and rows[-1]["date"] == "2026-10-31"
    )
    for row in rows:
        assert_keys(row, "date jdate close change_pct low high")
        assert row["low"] <= row["close"] <= row["high"]
        assert row["close"] == index_close(raw, int(row["date"].replace("-", "")))
    summary = out["summary"]
    assert (summary["from"]["value"], summary["to"]["value"]) == (
        index_close(raw, 20260901),
        index_close(raw, 20261031),
    )
    assert summary["change_pct"] == pct(summary["to"]["value"], summary["from"]["value"])
    assert (
        summary["trading_days"] == 43
        and summary["up_days"] + summary["down_days"] + summary["flat_days"] == 43
    )
    # history no longer changes: exact values for this range
    assert (
        summary["change_pct"],
        summary["highest_close"]["date"],
        summary["lowest_close"]["date"],
    ) == (19.07, "2026-10-13", "2026-09-02")
    assert (summary["max_drawdown"]["pct"], summary["best_day"], summary["worst_day"]) == (
        -7.34,
        {"date": "2026-09-07", "change_pct": 2.74},
        {"date": "2026-09-20", "change_pct": -2.11},
    )
    assert summary["volatility_estimate"]["method"].startswith("ESTIMATE")


@scenario("index_history_intraday", "index_history", index="شاخص کل", intraday=True, limit=500)
def _index_history_intraday(run):
    out, raw = run.out, run.rec.body("GetIndexB1LastDay")["indexB1"]
    assert_keys(out, "index units date jdate is_today returned rows summary note")
    assert out["index"]["name"] == "شاخص کل" and out["units"] == "index points (not rial)"
    day = max(r["dEven"] for r in raw)
    assert out["date"] == iso(day)
    assert out["is_today"] is (
        out["date"] == run.now.date().isoformat()
    )  # judged against the frozen clock
    assert out["returned"] == len(out["rows"]) <= len(raw)
    times = [r["time"] for r in out["rows"]]
    assert (
        times == sorted(times) and times[0] >= "09:00"
    )  # the 5-minute grid of the session, then the closing values
    summary = out["summary"]
    assert_keys(
        summary,
        "previous_close previous_close_source value change_points change_pct day_high day_low time_of_high time_of_low last_update raw_points session_points",
    )
    assert summary["raw_points"] == len(raw) and summary["last_update"] == hms(
        max(r["hEven"] for r in raw)
    )
    assert summary["value"] == out["rows"][-1]["value"]
    assert summary["day_high"] == max(r["value"] for r in out["rows"]) and summary[
        "day_low"
    ] == min(r["value"] for r in out["rows"])
    assert isclose(
        summary["change_points"], summary["value"] - summary["previous_close"], abs_tol=0.01
    )
    assert out["rows"][0]["value"] in {r["xDrNivJIdx004"] for r in raw}


@scenario("index_constituents", "index_constituents", index="فلزات", limit=10)
def _index_constituents(run):
    out, members = run.out, run.rec.body("GetIndexCompany")["indexCompany"]
    effects = run.rec.body("GetInstEffect")["instEffect"]
    assert_keys(out, "index sorted_by descending returned totals effect_check rows units note")
    assert (out["index"]["name"], out["index"]["code"], out["index"]["market"]) == (
        "فلزات اساسی",
        "27",
        "bourse",
    )
    assert (
        out["sorted_by"] == "effect"
        and out["descending"] is True
        and out["returned"] == len(out["rows"]) == 10
    )
    totals = out["totals"]
    assert totals["members"] == len(members)
    assert totals["traded_today"] == sum(1 for m in members if m["zTotTran"])
    assert totals["advancers"] + totals["decliners"] + totals["unchanged"] == totals["traded_today"]
    assert totals["total_value"] == sum(int(m["qTotCap"]) for m in members)
    check = out["effect_check"]
    assert check["used"] is True and check["source"] == "Index/GetInstEffect"
    assert isclose(
        check["sum_over_all_stocks"], sum(e["instEffectValue"] for e in effects), abs_tol=0.01
    )
    assert descending(r["effect_on_total_index"] for r in out["rows"])
    top = out["rows"][0]
    assert_keys(
        top,
        "symbol name ins_code close close_pct last last_pct yesterday volume value trades effect_on_total_index market_cap",
    )
    member = one(members, lambda m: m["insCode"] == top["ins_code"])
    assert (top["close"], top["last"], top["yesterday"]) == (
        member["pClosing"],
        member["pDrCotVal"],
        member["priceYesterday"],
    )
    assert (top["volume"], top["value"], top["trades"]) == (
        int(member["qTotTran5J"]),
        int(member["qTotCap"]),
        int(member["zTotTran"]),
    )
    assert (
        top["effect_on_total_index"]
        == one(effects, lambda e: e["insCode"] == top["ins_code"])["instEffectValue"]
    )
    assert top["close_pct"] == pct(member["pClosing"], member["priceYesterday"])


@scenario("fund_ranking", "fund_ranking", fund_type="gold", limit=10)
def _fund_ranking(run):
    out, raw = run.out, run.rec.body("GetFunds/5")["funds"]
    assert_keys(out, "sorted_by descending min_net_assets types universe returned funds units note")
    assert (
        out["sorted_by"] == "return_1y"
        and out["descending"] is True
        and out["returned"] == len(out["funds"]) == 10
    )
    assert [t["id"] for t in out["types"]] == [5] and out["types"][0]["funds"] == len(raw)
    assert out["universe"]["funds"] == len(raw) and out["universe"]["total_net_assets"] == int(
        sum(f["netAsset"] for f in raw)
    )
    assert "net_assets in rial" in out["units"]
    returns = [f["returns_pct"]["1y"] for f in out["funds"]]
    assert descending(returns)
    top = out["funds"][0]
    assert_keys(
        top,
        "reg_no name type nav_date net_assets units nav_redemption nav_issue nav_statistical returns_pct portfolio_pct manager age_days",
    )
    fund = one(raw, lambda f: int(f["regNo"]) == top["reg_no"], "fund")
    assert (top["net_assets"], top["units"]) == (int(fund["netAsset"]), int(fund["units"]))
    assert (top["nav_redemption"], top["nav_issue"], top["nav_statistical"]) == (
        fund["navRed"],
        fund["navSub"],
        fund["navStat"],
    )
    assert top["nav_date"] == fund["recordDate"][:10] and top["manager"] == clean(fund["manager"])
    assert (
        top["returns_pct"]["1y"] == fund["day365Return"]
        and top["returns_pct"]["1d"] == fund["day1Return"]
    )
    assert top["returns_pct"]["1y"] == max(
        f["day365Return"] for f in raw if f["day365Return"] is not None
    )


# ----------------------------------------------------------------------------- derivatives
@scenario("option_chain_underlyings", "option_chain")
def _option_chain_underlyings(run):
    out, raw = run.out, run.rec.body("GetInstrumentOptionMarketWatch")["instrumentOptMarketWatch"]
    assert_keys(
        out, "mode market underlyings_total sorted_by underlyings expiries_listed hint units"
    )
    assert (out["mode"], out["market"], out["sorted_by"]) == ("underlyings", "all", "open_interest")
    assert out["underlyings_total"] == len(out["underlyings"]) == len({r["uaInsCode"] for r in raw})
    assert descending(u["open_interest"] for u in out["underlyings"])
    top = out["underlyings"][0]
    assert_keys(
        top,
        "underlying underlying_ins_code spot_close expiries nearest_expiry nearest_expiry_jalali days_to_nearest_expiry strikes open_interest put_call_oi_ratio volume value",
    )
    rows = [r for r in raw if r["uaInsCode"] == top["underlying_ins_code"]]
    assert top["open_interest"] == sum(r["oP_C"] + r["oP_P"] for r in rows)
    assert top["volume"] == sum(r["qTotTran5J_C"] + r["qTotTran5J_P"] for r in rows)
    assert top["value"] == int(sum(r["qTotCap_C"] + r["qTotCap_P"] for r in rows))
    assert top["spot_close"] == rows[0]["pClosing_UA"] and top["expiries"] == len(
        {r["endDate"] for r in rows}
    )
    assert top["nearest_expiry"] == iso(min(r["endDate"] for r in rows))
    assert "contract" in out["units"]


@scenario("option_chain", "option_chain", underlying="اهرم")
def _option_chain(run):
    out, raw = run.out, run.rec.body("GetInstrumentOptionMarketWatch")["instrumentOptMarketWatch"]
    assert_keys(
        out,
        "mode market underlying underlying_ins_code sorted_by groups other_expiries units notes",
    )
    assert (out["mode"], out["underlying"], out["sorted_by"]) == ("chain", "اهرم", "strike")
    rows = [r for r in raw if r["uaInsCode"] == out["underlying_ins_code"]]
    group = out["groups"][0]
    assert group["expiry"] == iso(min(r["endDate"] for r in rows))  # the nearest expiry by default
    nearest = [r for r in rows if iso(r["endDate"]) == group["expiry"]]
    assert (
        group["strikes_total"] == len(nearest)
        and group["contract_size"] == nearest[0]["contractSize"]
    )
    assert [s["strike"] for s in group["strikes"]] == sorted(s["strike"] for s in group["strikes"])
    assert group["totals"]["call_open_interest"] == sum(r["oP_C"] for r in nearest) and group[
        "totals"
    ]["put_open_interest"] == sum(r["oP_P"] for r in nearest)
    assert group["spot"]["close"] == nearest[0]["pClosing_UA"]
    strike = group["strikes"][0]
    row = one(nearest, lambda r: r["strikePrice"] == strike["strike"], "strike")
    call, put = strike["call"], strike["put"]
    assert (call["symbol"], call["last"], call["close"], call["volume"], call["open_interest"]) == (
        clean(row["lVal18AFC_C"]),
        row["pDrCotVal_C"],
        row["pClosing_C"],
        row["qTotTran5J_C"],
        row["oP_C"],
    )
    assert (put["symbol"], put["last"], put["close"], put["volume"], put["open_interest"]) == (
        clean(row["lVal18AFC_P"]),
        row["pDrCotVal_P"],
        row["pClosing_P"],
        row["qTotTran5J_P"],
        row["oP_P"],
    )
    spot = row["pClosing_UA"]
    assert call["derived"]["intrinsic"] == max(spot - row["strikePrice"], 0) and put["derived"][
        "intrinsic"
    ] == max(row["strikePrice"] - spot, 0)
    assert call["derived"]["moneyness"] == ("ITM" if spot > row["strikePrice"] else "OTM")


@scenario("futures_market", "futures_market", limit=10)
def _futures_market(run):
    out, raw = run.out, run.rec.body("GetInstrumentFutureMarketWatch")["instrumentFtMarketWatch"]
    assert_keys(out, "total_contracts matched returned sorted_by contracts units notes")
    assert (
        out["total_contracts"] == out["matched"] == len(raw)
        and out["returned"] == len(out["contracts"]) == 10
    )
    assert out["sorted_by"] == "expiry" and [c["expiry"] for c in out["contracts"]] == sorted(
        c["expiry"] for c in out["contracts"]
    )
    for contract in out["contracts"]:
        assert_keys(
            contract,
            "symbol underlying expiry expiry_jalali days_to_expiry contract_size last close close_pct yesterday bid bid_qty ask ask_qty volume trades value open_interest open_interest_change underlying_close derived",
        )
        row = pick(raw, lambda r: clean(r["lVal18AFC"]), contract["symbol"], "future")
        assert (
            contract["expiry"],
            contract["contract_size"],
            contract["volume"],
            contract["trades"],
        ) == (iso(row["endDate"]), row["contractSize"], row["qTotTran5J"], row["zTotTran"])
        assert (contract["yesterday"], contract["underlying_close"], contract["open_interest"]) == (
            row["priceYesterday"],
            row["pClosing_UA"],
            row["mop"],
        )
        assert (contract["bid"], contract["ask"]) == (
            row["pMeDem"] or None,
            row["pMeOf"] or None,
        )  # no order: null, not 0
        assert (
            contract["underlying"] == clean(row["lVal30_UA"])
            and contract["days_to_expiry"] == row["remainedDay"]
        )
        if row["zTotTran"]:  # traded today: the basis is the closing price against the underlying's
            assert contract["derived"]["basis"] == row["pClosing"] - row["pClosing_UA"]
        else:
            assert contract["close"] is None and contract["derived"]["basis"] is None
