"""Contract scenarios: tools about one symbol. فولاد is the flagship; حتاید is liquid enough to be real but small
enough that a whole day of its ticks and order-book events is recorded untrimmed (so completeness checks are exact).

Dated scenarios use fixed past days, whose data no longer changes: those checks pin exact values.
"""

from __future__ import annotations

from math import isclose

from contract_helpers import assert_keys, clean, descending, hms, is_jdate, iso, one, pct, pick
from contract_replay import scenario

INSTRUMENT = "symbol name ins_code market"


def instrument(out, symbol, ins_code):
    assert (
        out["symbol"] == symbol
        and out["ins_code"] == ins_code
        and out["market"] == "bourse"
        and out["name"]
    )
    assert set(out) <= set((INSTRUMENT + " board").split())


def daily_row(run, deven):
    return one(
        run.rec.body("GetClosingPriceDailyList")["closingPriceDaily"],
        lambda r: r["dEven"] == deven,
        f"daily row {deven}",
    )


def check_quote(q, closing, info):
    """The quote block (shared by quote and symbol_overview) against GetClosingPriceInfo and GetInstrumentInfo."""
    assert_keys(
        q,
        "date jdate last_update status last close yesterday_close open high low volume value trades vwap price_limits "
        "at_upper_limit at_lower_limit ranges avg_volume volume_vs_avg fundamentals units",
    )
    last, close, yesterday = closing["pDrCotVal"], closing["pClosing"], closing["priceYesterday"]
    assert (q["date"], q["last_update"], q["units"]) == (
        iso(closing["dEven"]),
        hms(closing["hEven"]),
        "rial",
    ) and is_jdate(q["jdate"])
    assert q["last"] == {
        "price": last,
        "change": last - yesterday,
        "change_pct": pct(last, yesterday),
    }  # recomputed: the feed's own change is unreliable
    assert q["close"] == {
        "price": close,
        "change": close - yesterday,
        "change_pct": pct(close, yesterday),
    }
    assert (q["yesterday_close"], q["open"], q["high"], q["low"]) == (
        yesterday,
        closing["priceFirst"],
        closing["priceMax"],
        closing["priceMin"],
    )
    assert (q["volume"], q["value"], q["trades"]) == (
        int(closing["qTotTran5J"]),
        int(closing["qTotCap"]),
        int(closing["zTotTran"]),
    )
    assert q["vwap"] == round(closing["qTotCap"] / closing["qTotTran5J"], 2)
    state = closing["instrumentState"]
    assert q["status"] == {
        "code": state["cEtaval"].strip(),
        "title": clean(state["cEtavalTitle"]),
        "under_supervision": state["underSupervision"],
    }
    limits = info["staticThreshold"]
    assert q["price_limits"] == {"upper": limits["psGelStaMax"], "lower": limits["psGelStaMin"]}
    assert q["at_upper_limit"] is (last >= limits["psGelStaMax"]) and q["at_lower_limit"] is (
        last <= limits["psGelStaMin"]
    )
    assert q["ranges"] == {
        "week": {"low": info["minWeek"], "high": info["maxWeek"]},
        "year": {"low": info["minYear"], "high": info["maxYear"]},
    }
    assert q["avg_volume"] == int(info["qTotTran5JAvg"])
    funds = q["fundamentals"]
    eps = float(info["eps"]["estimatedEPS"])
    assert (funds["eps"], funds["sector_pe"], funds["psr"]) == (
        eps,
        info["eps"]["sectorPE"],
        info["eps"]["psr"],
    )
    assert funds["pe"] == round(close / eps, 2) and funds["shares_outstanding"] == int(
        info["zTitad"]
    )
    assert funds["market_cap"] == int(last * info["zTitad"])


def check_book(book, rows, info):
    """An order-book block against BestLimits: levels, totals, the queue and the price limits."""
    limits = info["staticThreshold"]
    upper, lower = limits["psGelStaMax"], limits["psGelStaMin"]
    levels = sorted(rows, key=lambda r: r["number"])
    bids = [
        {
            "level": r["number"],
            "price": r["pMeDem"],
            "volume": r["qTitMeDem"],
            "orders": r["zOrdMeDem"],
        }
        for r in levels
        if r["qTitMeDem"] > 0
    ]
    asks = [
        {
            "level": r["number"],
            "price": r["pMeOf"],
            "volume": r["qTitMeOf"],
            "orders": r["zOrdMeOf"],
        }
        for r in levels
        if r["qTitMeOf"] > 0
    ]
    assert [
        {k: v for k, v in b.items() if k != "outside_price_limits"} for b in book["bids"]
    ] == bids
    assert [
        {k: v for k, v in a.items() if k != "outside_price_limits"} for a in book["asks"]
    ] == asks
    assert all(
        a.get("outside_price_limits", False) == (a["price"] > upper) for a in book["asks"]
    )  # orders for the next session are flagged
    assert (book["best_bid"], book["best_ask"]) == (bids[0]["price"], asks[0]["price"])
    assert book["spread"] == asks[0]["price"] - bids[0]["price"] and book["spread_pct"] == pct(
        asks[0]["price"], bids[0]["price"]
    )
    bid_volume, ask_volume = sum(b["volume"] for b in bids), sum(a["volume"] for a in asks)
    assert (book["total_bid_volume"], book["total_ask_volume"]) == (bid_volume, ask_volume)
    assert (book["total_bid_orders"], book["total_ask_orders"]) == (
        sum(b["orders"] for b in bids),
        sum(a["orders"] for a in asks),
    )
    assert book["imbalance"] == round((bid_volume - ask_volume) / (bid_volume + ask_volume), 4)
    assert (
        book["price_limits"] == {"upper": upper, "lower": lower}
        and book["units"] == "price in rial, volume in shares"
    )
    live_asks = [a for a in asks if a["price"] <= upper]
    if (
        bids[0]["price"] >= upper and not live_asks
    ):  # bids at the ceiling and nobody selling: a buy queue
        assert book["queue"] == {
            "state": "buy_queue",
            "queue_volume": bids[0]["volume"],
            "queue_orders": bids[0]["orders"],
            "queue_value": bids[0]["volume"] * bids[0]["price"],
        }
    else:
        assert book["queue"]["state"] != "buy_queue"
    assert lower < upper


def check_holders(holders, rows):
    assert [
        (h["name"], h["shares"], h["percent"], h["change_amount"], h["holder_id"]) for h in holders
    ] == [
        (
            clean(r["shareHolderName"]),
            int(r["numberOfShares"]),
            r["perOfShares"],
            r["changeAmount"],
            r["shareHolderShareID"],
        )
        for r in sorted(rows, key=lambda r: -r["perOfShares"])
    ]


# ----------------------------------------------------------------------------- finding and quoting
@scenario("search_symbol", "search_symbol", query="فولاد", limit=5)
def _search_symbol(run):
    out, raw = run.out, run.rec.body("GetInstrumentSearch")["instrumentSearch"]
    assert_keys(out, "query count results")
    assert out["query"] == "فولاد" and out["count"] == len(out["results"]) == 5 < len(raw)
    for row, r in zip(out["results"], raw, strict=False):
        assert_keys(row, "symbol name ins_code market board")
        assert (row["symbol"], row["name"], row["ins_code"]) == (
            clean(r["lVal18AFC"]),
            clean(r["lVal30"]),
            str(r["insCode"]),
        )
        assert row["market"] == {1: "bourse", 2: "fara-bourse"}.get(r["flow"], row["market"])
    assert out["results"][0]["symbol"] == "فولاد" and out["results"][0]["market"] == "bourse"


@scenario("quote", "quote", symbol="فولاد")
def _quote(run):
    out = run.out
    closing, info = (
        run.rec.body("GetClosingPriceInfo")["closingPriceInfo"],
        run.rec.body("GetInstrumentInfo")["instrumentInfo"],
    )
    assert_keys(
        out,
        "instrument date jdate last_update status last close yesterday_close open high low volume value trades vwap price_limits at_upper_limit at_lower_limit ranges avg_volume volume_vs_avg fundamentals units",
    )
    assert out["instrument"] == {
        "symbol": "فولاد",
        "name": "فولاد مبارکه اصفهان",
        "ins_code": "46348559193224090",
        "market": "bourse",
    }
    check_quote({k: v for k, v in out.items() if k != "instrument"}, closing, info)


@scenario("order_book", "order_book", symbol="فولاد")
def _order_book(run):
    out = run.out
    closing, info = (
        run.rec.body("GetClosingPriceInfo")["closingPriceInfo"],
        run.rec.body("GetInstrumentInfo")["instrumentInfo"],
    )
    assert_keys(
        out,
        "instrument as_of bids asks best_bid best_ask spread spread_pct total_bid_volume total_ask_volume total_bid_orders total_ask_orders imbalance queue price_limits units note",
    )
    assert out["instrument"]["symbol"] == "فولاد" and out["as_of"] == {
        "date": iso(closing["dEven"]),
        "last_trade_time": hms(closing["hEven"]),
    }
    assert len(out["bids"]) == len(out["asks"]) == 5
    assert_keys(out["queue"], "state queue_volume queue_orders queue_value")
    check_book(out, run.rec.body("/BestLimits/46348559193224090")["bestLimits"], info)


@scenario("symbol_overview", "symbol_overview", codal=True, symbol="فولاد")
def _symbol_overview(run):
    out = run.out
    closing, info = (
        run.rec.body("GetClosingPriceInfo")["closingPriceInfo"],
        run.rec.body("GetInstrumentInfo")["instrumentInfo"],
    )
    assert_keys(
        out,
        "identity quote order_book real_legal major_shareholders recent_filings recent_supervisor_messages",
    )  # no unavailable_sections
    identity = out["identity"]
    assert_keys(
        identity,
        "symbol name name_en ins_code isin instrument_id market board sector sector_code sub_sector instrument_kind",
    )
    assert (
        identity["symbol"],
        identity["ins_code"],
        identity["isin"],
        identity["sector_code"],
        identity["instrument_kind"],
    ) == ("فولاد", "46348559193224090", "IRO1FOLD0009", "27", "stock")
    assert identity["sector"] == clean(info["sector"]["lSecVal"])
    check_quote(out["quote"], closing, info)
    check_book(out["order_book"], run.rec.body("/BestLimits/46348559193224090")["bestLimits"], info)
    flow = run.rec.body("GetClientType/")["clientType"]
    assert (
        out["real_legal"]["real"]["buy"]["volume"] == int(flow["buy_I_Volume"])
        and out["real_legal"]["legal"]["sell"]["count"] == flow["sell_CountN"]
    )
    holders = run.rec.body("GetInstrumentShareHolderLast")["shareHolder"]
    top = sorted(holders, key=lambda r: -r["perOfShares"])[:5]
    assert out["major_shareholders"]["top5_percent"] == round(sum(r["perOfShares"] for r in top), 2)
    assert [h["name"] for h in out["major_shareholders"]["top"]] == [
        clean(r["shareHolderName"]) for r in top
    ]
    letters = run.rec.body("search.codal.ir")["Letters"]
    assert [f["tracing_no"] for f in out["recent_filings"]] == [r["TracingNo"] for r in letters[:5]]
    messages = sorted(
        run.rec.body("GetMsgByInsCode")["msg"], key=lambda r: (r["dEven"], r["hEven"]), reverse=True
    )[:3]
    assert [(m["date"], m["time"]) for m in out["recent_supervisor_messages"]] == [
        (iso(r["dEven"]), hms(r["hEven"])) for r in messages
    ]


# ----------------------------------------------------------------------------- the trading day in detail (a symbol with a whole day recorded)
@scenario(
    "order_book_history", "order_book_history", symbol="حتاید", date="2026-11-03", step_seconds=900
)
def _order_book_history(run):
    out, raw = run.out, run.rec.body("/BestLimits/3722699128879020/20261103")["bestLimitsHistory"]
    limits = [
        r for r in run.rec.body("GetStaticThreshold")["staticThreshold"] if r["dEven"] == 20261103
    ][-1]
    assert_keys(
        out,
        "instrument date jdate total_events events_span warning price_limits window snapshots_in_range samples queue_episodes max_bid_volume max_ask_volume note",
    )
    instrument(out["instrument"], "حتاید", "3722699128879020")
    assert (out["date"], out["jdate"]) == ("2026-11-03", "1405/08/12")
    assert out["total_events"] == len({r["refID"] for r in raw}) and out["warning"] is None
    first, last = min(r["hEven"] for r in raw), max(r["hEven"] for r in raw)
    assert out["events_span"] == {
        "first": hms(first),
        "last": hms(last),
        "covers_full_session": last >= 122500,
    }
    assert out["price_limits"] == {"upper": limits["psGelStaMax"], "lower": limits["psGelStaMin"]}
    assert out["window"] == {"from": "08:30:00", "to": "12:35:00"}  # pre-open and the session
    samples = out["samples"]
    assert 0 < len(samples) <= 17 and [s["time"] for s in samples] == sorted(
        s["time"] for s in samples
    )  # 15-minute steps
    for sample in samples:
        assert_keys(
            sample, "time best_bid best_ask bid_volume ask_volume imbalance queue queue_volume"
        )
    episode = out["queue_episodes"][0]
    assert_keys(episode, "type start end start_volume end_volume peak_volume")
    assert (
        episode["type"] == "buy_queue"
        and 0 < episode["peak_volume"] <= out["max_bid_volume"]
        and out["max_ask_volume"] > 0
    )
    # this day is history: exact values
    assert (out["total_events"], out["events_span"]["first"], out["events_span"]["last"]) == (
        651,
        "06:01:28",
        "14:08:02",
    )
    assert (
        out["price_limits"] == {"upper": 9150.0, "lower": 8630.0} and episode["start"] == "09:00:13"
    )


@scenario("trades", "trades", symbol="حتاید", limit=20)
def _trades(run):
    out, raw = run.out, run.rec.body("/Trade/GetTrade/3722699128879020")["trade"]
    closing = run.rec.body("GetClosingPriceInfo")["closingPriceInfo"]
    assert_keys(out, "instrument date jdate matched returned truncated trades units")
    instrument(out["instrument"], "حتاید", "3722699128879020")
    assert out["date"] == iso(closing["dEven"]) and is_jdate(
        out["jdate"]
    )  # no date asked: the latest session
    ticks = sorted((r for r in raw if not r["canceled"]), key=lambda r: (r["nTran"], r["hEven"]))
    assert (
        out["matched"] == len(ticks)
        and out["returned"] == len(out["trades"]) == 20
        and out["truncated"] is True
    )
    assert out["units"] == "price/value in rial, volume in shares"
    for trade, r in zip(out["trades"], ticks, strict=False):
        assert_keys(trade, "n time price volume value")
        assert (trade["n"], trade["time"], trade["price"], trade["volume"]) == (
            r["nTran"],
            hms(r["hEven"]),
            r["pTran"],
            r["qTitTran"],
        )
        assert trade["value"] == int(r["pTran"] * r["qTitTran"])
    assert sum(t["qTitTran"] for t in ticks) == int(
        closing["qTotTran5J"]
    )  # a whole day: the ticks add up to the official volume


@scenario("trade_summary", "trade_summary", symbol="حتاید", date="2026-11-02", interval_minutes=30)
def _trade_summary(run):
    out, raw = run.out, run.rec.body("GetTradeHistory/3722699128879020/20261102")["tradeHistory"]
    official = daily_row(run, 20261102)
    ticks = sorted((r for r in raw if not r["canceled"]), key=lambda r: (r["nTran"], r["hEven"]))
    volume, value = (
        sum(r["qTitTran"] for r in ticks),
        sum(r["qTitTran"] * r["pTran"] for r in ticks),
    )
    assert_keys(
        out,
        "instrument date jdate summary completeness bars pressure_estimate biggest_trades price_levels point_of_control units",
    )
    assert (out["date"], out["jdate"]) == ("2026-11-02", "1405/08/11")
    summary = out["summary"]
    assert (summary["ticks"], summary["cancelled_ticks"], summary["volume"], summary["value"]) == (
        len(ticks),
        len(raw) - len(ticks),
        volume,
        int(value),
    )
    assert summary["vwap"] == round(value / volume, 2)
    assert (summary["open"], summary["close"]) == (ticks[0]["pTran"], ticks[-1]["pTran"])
    assert (summary["high"], summary["low"]) == (
        max(r["pTran"] for r in ticks),
        min(r["pTran"] for r in ticks),
    )
    assert (summary["first_trade"], summary["last_trade"]) == (
        hms(ticks[0]["hEven"]),
        hms(ticks[-1]["hEven"]),
    )
    completeness = out["completeness"]  # the ticks against the exchange's own daily totals
    assert (completeness["official_volume"], completeness["official_trade_count"]) == (
        int(official["qTotTran5J"]),
        int(official["zTotTran"]),
    )
    assert (completeness["volume_coverage_pct"], completeness["count_coverage_pct"]) == (
        100.0,
        100.0,
    )
    assert sum(b["volume"] for b in out["bars"]) == volume and sum(
        b["trades"] for b in out["bars"]
    ) == len(ticks)
    for bar in out["bars"]:
        assert_keys(bar, "from open high low close volume value trades vwap")
        assert (
            bar["low"] <= bar["open"] <= bar["high"] and bar["low"] <= bar["close"] <= bar["high"]
        )
    assert [b["from"] for b in out["bars"]] == sorted(b["from"] for b in out["bars"]) and all(
        b["from"][3:] in ("00", "30") for b in out["bars"]
    )
    pressure = out["pressure_estimate"]
    assert isclose(
        pressure["uptick_volume_pct"]
        + pressure["downtick_volume_pct"]
        + pressure["neutral_volume_pct"],
        100,
        abs_tol=0.05,
    )
    assert "heuristic" in pressure["caveat"]
    biggest = out["biggest_trades"]
    assert len(biggest) == 10 and descending(t["value"] for t in biggest)
    assert biggest[0]["value"] == max(int(r["qTitTran"] * r["pTran"]) for r in ticks)
    for trade in biggest:
        assert_keys(trade, "time price volume value")
        assert trade["value"] == int(trade["volume"] * trade["price"])
    volume_at = {}
    for r in ticks:
        volume_at[r["pTran"]] = volume_at.get(r["pTran"], 0) + r["qTitTran"]
    top = max(volume_at, key=volume_at.get)
    assert out["point_of_control"] == top == out["price_levels"][0]["price"]
    assert out["price_levels"][0]["volume"] == volume_at[top] and out["price_levels"][0][
        "share_pct"
    ] == round(volume_at[top] / volume * 100, 2)
    # this day is history: exact values
    assert (summary["ticks"], summary["volume"], summary["value"], summary["close"]) == (
        1401,
        45592481,
        405330048120,
        9030.0,
    )


# ----------------------------------------------------------------------------- history and flows
@scenario(
    "price_history",
    "price_history",
    symbol="فولاد",
    from_date="2026-03-25",
    to_date="2026-04-06",
    adjusted=True,
)
def _price_history(run):
    out, raw = run.out, run.rec.body("GetClosingPriceDailyList")["closingPriceDaily"]
    assert_keys(
        out, "instrument adjusted adjustment_events total_in_range returned rows units note"
    )
    assert out["adjusted"] is True and out["units"] == "rial" and "back-adjusted" in out["note"]
    days = sorted((r for r in raw if 20260325 <= r["dEven"] <= 20260406), key=lambda r: r["dEven"])
    assert out["total_in_range"] == out["returned"] == len(out["rows"]) == len(days) == 8
    # every event after the first row shown, oldest first: the capital increase and the dividend of 2026, then any later one
    events = out["adjustment_events"]
    assert [e["date"] for e in events[:2]] == ["2026-03-30", "2026-08-05"]
    assert [e["date"] for e in events] == sorted(e["date"] for e in events)
    for event in events:
        assert_keys(event, "date jdate factor")
    for row, r in zip(out["rows"], days, strict=True):
        assert_keys(row, "date jdate open high low close last volume value trades change_pct")
        assert row["date"] == iso(r["dEven"]) and (row["volume"], row["value"], row["trades"]) == (
            int(r["qTotTran5J"]),
            int(r["qTotCap"]),
            int(r["zTotTran"]),
        )
        scale = 1.0
        for event in events:  # an older price is multiplied by the factor of every event after it
            if event["date"] > row["date"]:
                scale *= event["factor"]
        assert isclose(row["close"], r["pClosing"] * scale, abs_tol=0.01) and isclose(
            row["last"], r["pDrCotVal"] * scale, abs_tol=0.01
        )
    assert out["rows"][-1]["date"] == "2026-04-06"
    assert [(e["factor"], e["jdate"]) for e in events] == [
        (0.775231, "1405/01/10"),
        (0.978879, "1405/05/14"),
    ]  # history: exact


@scenario("real_legal_flow", "real_legal_flow", symbol="فولاد", days=5)
def _real_legal_flow(run):
    out, current = run.out, run.rec.body("GetClientType/")["clientType"]
    closing = run.rec.body("GetClosingPriceInfo")["closingPriceInfo"]
    history = run.rec.body("GetClientTypeHistory")["clientType"]
    assert_keys(out, "instrument latest_session history history_summary units")
    session = out["latest_session"]
    assert_keys(
        session,
        "date real legal real_buyer_power real_share_of_buy_volume_pct real_share_of_sell_volume_pct reading",
    )
    assert session["date"] == iso(closing["dEven"])
    vwap = closing["qTotCap"] / closing["qTotTran5J"]
    real = session["real"]
    assert (
        real["buy"]["volume"],
        real["buy"]["count"],
        real["sell"]["volume"],
        real["sell"]["count"],
    ) == (
        int(current["buy_I_Volume"]),
        current["buy_CountI"],
        int(current["sell_I_Volume"]),
        current["sell_CountI"],
    )
    assert real["buy"]["value_estimated"] is True and "estimated" in out["units"]
    assert real["net_volume"] == int(current["buy_I_Volume"] - current["sell_I_Volume"])
    assert isclose(real["net_value"], real["net_volume"] * vwap, rel_tol=1e-3)  # net volume x VWAP
    assert session["legal"]["net_volume"] == -real["net_volume"] or isclose(
        session["legal"]["net_volume"], -real["net_volume"], abs_tol=1
    )
    assert session["real_buyer_power"] == round(
        (current["buy_I_Volume"] / current["buy_CountI"])
        / (current["sell_I_Volume"] / current["sell_CountI"]),
        2,
    )
    days = out["history"]
    assert len(days) == 5 and [d["date"] for d in days] == sorted(d["date"] for d in days)
    newest = sorted(history, key=lambda r: r["recDate"], reverse=True)[:5]
    for day, r in zip(sorted(days, key=lambda d: d["date"], reverse=True), newest, strict=True):
        assert_keys(
            day,
            "date jdate real_net_volume real_net_value real_buy_value real_sell_value real_buy_count real_sell_count real_buyer_power legal_net_value",
        )
        assert day["date"] == iso(r["recDate"])  # published by the exchange, not estimated
        assert day["real_buy_value"] == int(r["buy_I_Value"]) and day["real_sell_value"] == int(
            r["sell_I_Value"]
        )
        assert day["real_net_value"] == int(r["buy_I_Value"] - r["sell_I_Value"]) and day[
            "real_net_volume"
        ] == int(r["buy_I_Volume"] - r["sell_I_Volume"])
        assert (day["real_buy_count"], day["real_sell_count"]) == (
            int(r["buy_I_Count"]),
            int(r["sell_I_Count"]),
        )
    nets = [d["real_net_value"] for d in days]
    assert out["history_summary"] == {
        "days": 5,
        "real_net_value_total": sum(nets),
        "days_with_real_inflow": sum(1 for n in nets if n > 0),
        "days_with_real_outflow": sum(1 for n in nets if n < 0),
    }


@scenario("shareholders", "shareholders", symbol="فولاد")
def _shareholders(run):
    out, rows = run.out, run.rec.body("GetInstrumentShareHolderLast")["shareHolder"]
    info = run.rec.body("GetInstrumentInfo")["instrumentInfo"]
    assert_keys(
        out,
        "instrument shares_outstanding listed_holders listed_percent_total other_holders_percent top5_percent holders note",
    )
    assert out["shares_outstanding"] == int(info["zTitad"]) and out["listed_holders"] == len(
        rows
    ) == len(out["holders"])
    check_holders(out["holders"], rows)
    listed = sum(r["perOfShares"] for r in rows)
    assert out["listed_percent_total"] == round(listed, 2) and out[
        "other_holders_percent"
    ] == round(100 - listed, 2)
    assert out["top5_percent"] == round(
        sum(sorted((r["perOfShares"] for r in rows), reverse=True)[:5]), 2
    )
    assert descending(h["percent"] for h in out["holders"]) and "holder_id" in out["note"]


@scenario("shareholder_history_snapshots", "shareholder_history", symbol="فولاد", date="2026-11-03")
def _shareholder_history_snapshots(run):
    out, rows = run.out, run.rec.body("/Shareholder/46348559193224090/20261103")["shareShareholder"]
    assert_keys(out, "instrument snapshots")
    snapshots = out["snapshots"]
    assert [s["date"] for s in snapshots] == sorted(
        {iso(r["dEven"]) for r in rows}
    )  # one snapshot per recorded day
    assert sum(len(s["holders"]) for s in snapshots) == len(rows)
    for snapshot in snapshots:
        assert_keys(snapshot, "date holders dropped_from_list")
        day = [r for r in rows if iso(r["dEven"]) == snapshot["date"]]
        assert {h["name"] for h in snapshot["holders"]} == {
            clean(r["shareHolderName"]) for r in day
        }
        for holder in snapshot["holders"]:
            assert_keys(holder, "name shares percent shares_change new_in_list")
    first = snapshots[0]["holders"][0]
    r = one(
        rows,
        lambda x: (
            clean(x["shareHolderName"]) == first["name"] and iso(x["dEven"]) == snapshots[0]["date"]
        ),
        "holder row",
    )
    assert (first["shares"], first["percent"]) == (
        int(r["numberOfShares"]),
        r["perOfShares"],
    ) and first["shares_change"] is None  # the first snapshot has nothing to compare with


@scenario(
    "shareholder_history_holder",
    "shareholder_history",
    symbol="فولاد",
    holder="ونوسازی معادن",
    days=60,
)
def _shareholder_history_holder(run):
    out, rows = (
        run.out,
        run.rec.body("GetShareHolderHistory/46348559193224090/1460960/60")["shareHolder"],
    )
    assert_keys(
        out,
        "instrument holder holder_id period net_change_shares net_change_percent_points changes note",
    )
    assert (
        out["holder"] == "سازمان توسعه ونوسازی معادن وصنایع معدنی ایران"
        and out["holder_id"] == 1460960
    )  # a name fragment found the holder
    series = sorted(rows, key=lambda r: r["dEven"])
    assert out["period"] == {
        "from": iso(series[0]["dEven"]),
        "to": iso(series[-1]["dEven"]),
        "days_read": len(series),
    }
    assert out["net_change_shares"] == int(
        series[-1]["numberOfShares"] - series[0]["numberOfShares"]
    )
    assert (
        out["changes"][0]["shares"] == int(series[0]["numberOfShares"])
        and out["changes"][0]["shares_change"] is None
    )
    shares = [int(r["numberOfShares"]) for r in series]
    assert [c["shares"] for c in out["changes"]] == [
        s for i, s in enumerate(shares) if i == 0 or s != shares[i - 1]
    ]  # only the days it changed


@scenario("shareholder_portfolio", "shareholder_portfolio", holder_id="1460960")
def _shareholder_portfolio(run):
    out, rows = run.out, run.rec.body("GetShareHolderCompanyList/1460960")["shareHolderShare"]
    assert_keys(out, "holder_id holdings")
    assert out["holder_id"] == "1460960" and len(out["holdings"]) == len(rows)
    assert descending(h["percent"] for h in out["holdings"])
    for holding in out["holdings"]:
        assert_keys(holding, "symbol name shares percent change_amount")
        r = pick(rows, lambda x: clean(x["instrument"]["lVal18AFC"]), holding["symbol"], "holding")
        assert (holding["name"], holding["shares"], holding["percent"]) == (
            clean(r["instrument"]["lVal30"]),
            int(r["numberOfShares"]),
            r["perOfShares"],
        )


@scenario("corporate_actions", "corporate_actions", symbol="فولاد")
def _corporate_actions(run):
    out = run.out
    adjustments, capital = (
        run.rec.body("GetPriceAdjustList")["priceAdjust"],
        run.rec.body("GetInstrumentShareChange")["instrumentShareChange"],
    )
    assert_keys(out, "instrument price_adjustments capital_changes")
    assert len(out["price_adjustments"]) == len(adjustments) and len(out["capital_changes"]) == len(
        capital
    )
    assert descending(a["date"] for a in out["price_adjustments"]) and descending(
        c["date"] for c in out["capital_changes"]
    )
    for row in out["price_adjustments"]:
        assert_keys(row, "date jdate price_before price_after factor")
        r = pick(adjustments, lambda x: iso(x["dEven"]), row["date"], "price adjustment")
        assert (row["price_before"], row["price_after"], row["factor"]) == (
            r["pClosingNotAdjusted"],
            r["pClosing"],
            round(r["pClosing"] / r["pClosingNotAdjusted"], 6),
        )
    for row in out["capital_changes"]:
        assert_keys(row, "date jdate shares_before shares_after increase_pct")
        r = pick(capital, lambda x: iso(x["dEven"]), row["date"], "share change")
        assert (row["shares_before"], row["shares_after"], row["increase_pct"]) == (
            int(r["numberOfShareOld"]),
            int(r["numberOfShareNew"]),
            pct(r["numberOfShareNew"], r["numberOfShareOld"]),
        )
    increase = one(
        out["capital_changes"], lambda c: c["date"] == "2026-03-30", "the 2026 capital increase"
    )  # history: exact
    assert increase == {
        "date": "2026-03-30",
        "jdate": "1405/01/10",
        "shares_before": 1500000000000,
        "shares_after": 1935000000000,
        "increase_pct": 29.0,
    }


@scenario("symbol_statistics", "symbol_statistics", symbol="فولاد")
def _symbol_statistics(run):
    out, rows = run.out, run.rec.body("GetInstrumentStatistic")["instrumentStatistic"]
    assert_keys(out, "instrument metrics")
    assert len(out["metrics"]) == len(rows) > 50
    first = out["metrics"][0]
    assert_keys(first, "metric value code")
    assert (first["metric"], first["value"], first["code"]) == (
        clean(rows[0]["dataTypeDesc"]),
        float(rows[0]["dataValue"]),
        rows[0]["dataType"],
    )
    assert (
        "میانگین ارزش معاملات" in first["metric"]
    )  # «average traded value over the last 3 months»


@scenario("etf_nav", "etf_nav", symbol="اهرم")
def _etf_nav(run):
    out, etf = run.out, run.rec.body("GetETFByInsCode")["etf"]
    closing = run.rec.body("GetClosingPriceInfo")["closingPriceInfo"]
    assert_keys(
        out,
        "instrument available date time last_price nav_redemption nav_issue premium_to_redemption_nav_pct premium_to_issue_nav_pct note",
    )
    assert out["instrument"]["symbol"] == "اهرم" and out["available"] is True
    assert (out["nav_redemption"], out["nav_issue"], out["last_price"]) == (
        etf["pRedTran"],
        etf["pSubTran"],
        closing["pDrCotVal"],
    )
    assert out["premium_to_redemption_nav_pct"] == pct(closing["pDrCotVal"], etf["pRedTran"])
    assert out["premium_to_issue_nav_pct"] == pct(closing["pDrCotVal"], etf["pSubTran"])
    assert (out["date"], out["time"]) == (iso(etf["deven"]), hms(etf["hEven"]))


# ----------------------------------------------------------------------------- notices and status of one symbol
@scenario("supervisor_messages_symbol", "supervisor_messages", symbol="فولاد", limit=5)
def _supervisor_messages_symbol(run):
    out, raw = run.out, run.rec.body("GetMsgByInsCode")["msg"]
    assert_keys(out, "scope messages")
    instrument(out["scope"], "فولاد", "46348559193224090")
    newest = sorted(raw, key=lambda r: (r["dEven"], r["hEven"]), reverse=True)[:5]
    assert len(out["messages"]) == 5
    for message, r in zip(out["messages"], newest, strict=True):
        assert_keys(message, "date jdate time title text truncated")
        assert (message["date"], message["time"], message["title"]) == (
            iso(r["dEven"]),
            hms(r["hEven"]),
            clean(r["tseTitle"]),
        )
        assert message["truncated"] == (
            len(clean(r["tseDesc"])) > 500
        )  # long notices are cut at 500 characters unless full_text


@scenario(
    "trading_status_symbol_history",
    "trading_status",
    kind="symbol_history",
    symbol="فولاد",
    limit=10,
)
def _trading_status_symbol_history(run):
    out, raw = run.out, run.rec.body("GetInstrumentStateAll")["instrumentState"]
    supervision = run.rec.body("GetSupervisionByInsCode")["supervision"]
    assert_keys(
        out,
        "kind instrument current first_record records count history records_by_state state_codes supervision notes",
    )
    instrument(out["instrument"], "فولاد", "46348559193224090")
    assert out["records"] == len(raw) and out["count"] == len(out["history"]) == 10
    newest = max(raw, key=lambda r: (r["dEven"], r["hEven"]))
    assert (
        out["current"]["state"] == newest["cEtaval"].strip()
        and out["current"]["date"] == iso(newest["dEven"])
        and out["current"]["time"] == hms(newest["hEven"])
    )
    assert out["first_record"] == iso(min(r["dEven"] for r in raw))
    assert sum(out["records_by_state"].values()) == len(raw)
    assert [(h["date"], h["time"]) for h in out["history"]][0] == (
        out["current"]["date"],
        out["current"]["time"],
    )  # newest first
    assert set(out["state_codes"]) >= set(out["records_by_state"])
    assert supervision["underSupervision"] == 0 and not supervision["reasons"]  # nothing flagged
    assert out["supervision"] == {
        "status": "none",
        "status_title": None,
        "reasons": [],
        "since": None,
        "since_jdate": None,
    }
