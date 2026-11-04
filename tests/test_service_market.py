"""Market-wide and secondary tools, exercised end to end against a synthetic upstream."""

from __future__ import annotations

import pytest
from conftest import load

from iran_bourse_mcp.client import NotAvailable
from iran_bourse_mcp.service import Bourse, InputError


def watch_row(symbol, iid, last, yesterday, upper, lower, volume, value, *, industry="فلزات اساسی", kind="سهام عادی",
              market="بورس", sell=None, buy=None, mcap=1e12, effect="1.5"):
    pct = round((last - yesterday) / yesterday * 100, 2)
    v = lambda x: {"value": x, "state": 0}  # noqa: E731
    return {
        "instrumentId": iid, "instrumentName": symbol, "companyNamePersian": "شرکت " + symbol,
        "tradeVolume": v(volume), "tradeValue": v(value), "tradeCount": v(100), "highValue": v(last), "lowValue": v(last),
        "minValue": lower, "maxValue": upper, "lastPrice": v(last), "lastPriceChange": v(last - yesterday),
        "lastPriceChangePercent": v(pct), "closingPrice": v(last), "closingPriceChange": v(last - yesterday),
        "closingPriceChangePercent": v(pct), "yesterdayPrice": v(yesterday), "effectonIndex": effect, "pe": v(10), "eps": v(100),
        "marketValue": v(mcap), "sellPrice": v(None), "buyPrice": v(None), "firstPrice": v(yesterday),
        "sellQuantity": v(sell), "sellCount": v(None), "buyQuantity": v(buy), "buyCount": v(None), "boardName": "بازار اول",
        "marketname": market, "industryname": industry, "industrysubname": "x", "securitiesname": kind, "statename": "مجاز",
        "markettypename": "نرمال",
    }


WATCH = [
    watch_row("الف", "IRO1AAAA0001", 1030, 1000, 1030, 970, 5_000_000, 5e9, mcap=3e12, effect="9.0"),   # at upper limit (queue)
    watch_row("ب", "IRO1BBBB0001", 970, 1000, 1030, 970, 1_000_000, 9e8, industry="بانکها", effect="-4.0"),  # at lower limit
    watch_row("ج", "IRO1CCCC0001", 1010, 1000, 1030, 970, 9_000_000, 9e9, mcap=1e12, effect="2.0"),
    watch_row("د", "IRT1DDDD0001", 100, 100, 103, 97, 0, 0, kind="صندوق قابل معامله", effect="0"),         # untraded fund
    watch_row("ه", "IRO1EEEE0001", 2060, 2000, 2060, 1940, 2_000_000, 4e9, market="فرابورس", industry="بانکها", effect="1.0"),
]


class MarketApi:
    async def market_watch(self):
        return WATCH

    async def market_watch_all(self):
        raise NotAvailable("exchange feed unavailable in this test")

    async def market_overview(self, flow):
        return {"marketActivityDEven": 20261104, "marketState": "F", "marketStateTitle": "بسته", "indexLastValue": 100.0,
                "indexChange": 1.0, "marketActivityZTotTran": 5, "marketActivityQTotCap": 1e12, "marketActivityQTotTran": 10,
                "marketValue": 1e15, "marketActivityHEven": 123000}

    async def market_dates(self):
        return [{"stockType": "بورس", "openTime": "9:00", "closeTime": "12:30", "isOpen": False}]

    async def server_time(self):
        return "11/04/2026 14:00:00"

    async def prices_on_day(self, deven):
        base = [{"instrumentID": w["instrumentId"], "insCode": 1000 + i, "lVal18AFC": w["instrumentName"], "lVal30": "n",
                 "pClosing": 100.0, "pDrCotVal": 100.0, "priceYesterday": 90.0, "priceFirst": 95.0, "priceMax": 101.0, "priceMin": 94.0,
                 "qTotTran5J": 1000.0 * (i + 1), "qTotCap": 1e6 * (i + 1), "zTotTran": 10.0 + i} for i, w in enumerate(WATCH)]
        return base if deven == 20261104 else []

    async def client_type_all(self):
        return [
            {"insCode": 1000, "buy_I_Volume": 900.0, "buy_CountI": 3, "sell_I_Volume": 100.0, "sell_CountI": 10},
            {"insCode": 1001, "buy_I_Volume": 100.0, "buy_CountI": 10, "sell_I_Volume": 900.0, "sell_CountI": 3},
            {"insCode": 1002, "buy_I_Volume": 500.0, "buy_CountI": 5, "sell_I_Volume": 500.0, "sell_CountI": 5},
        ]

    async def best_limits(self, ins):
        if str(ins) == "1000":  # real buy queue
            return [{"number": 1, "pMeDem": 1030, "qTitMeDem": 7_000_000, "zOrdMeDem": 300, "pMeOf": 0, "qTitMeOf": 0, "zOrdMeOf": 0}]
        if str(ins) == "1001":  # at lower limit with a real sell queue
            return [{"number": 1, "pMeDem": 0, "qTitMeDem": 0, "zOrdMeDem": 0, "pMeOf": 970, "qTitMeOf": 4_000_000, "zOrdMeOf": 80}]
        return []

    async def indices(self, flow):
        return [{"lVal30": "شاخص كل", "insCode": 1, "xDrNivJIdx004": 100.0, "xVarIdxJRfV": 1.0, "indexChange": 1.0},
                {"lVal30": "27-فلزات", "insCode": 2, "xDrNivJIdx004": 50.0, "xVarIdxJRfV": 2.5, "indexChange": 1.2},
                {"lVal30": "57-بانک", "insCode": 3, "xDrNivJIdx004": 60.0, "xVarIdxJRfV": -1.5, "indexChange": -0.9}]

    async def holder_moves_market(self):
        return {"dates": [20261031, 20261101, 20261102, 20261103, 20261104], "shareHoldersChanges": [
            {"name": "صندوق الف", "insList": [
                {"insCode": "1", "name": "الف", "firstDay": 100.0, "secondDay": 100.0, "thirdDay": 120.0, "fourthDay": 150.0, "fifthDay": 200.0},
                {"insCode": "2", "name": "ب", "firstDay": 50.0, "secondDay": 50.0, "thirdDay": 50.0, "fourthDay": 50.0, "fifthDay": 50.0}]}]}

    async def messages_flow(self, flow, top):
        return [{"dEven": 20261103, "hEven": 100000, "tseTitle": "اطلاعيه", "tseDesc": "متن " * 200}]

    async def messages_for(self, ins):
        return [{"dEven": 20261101, "hEven": 90000, "tseTitle": "قدیمی", "tseDesc": "a"}, {"dEven": 20261103, "hEven": 90000, "tseTitle": "جدید", "tseDesc": "b"}]

    # symbol-level extras
    async def search(self, query):
        return load("search_folad")

    async def instrument_info(self, ins):
        return load("info")

    async def closing_info(self, ins):
        return load("closing_info")

    async def daily_prices(self, ins):
        return [{"dEven": 20261100 + d, "pClosing": 100.0 + d, "pDrCotVal": 100.0 + d, "priceYesterday": 99.0 + d, "priceFirst": 99.0,
                 "priceMax": 110.0, "priceMin": 90.0, "qTotTran5J": 10.0, "qTotCap": 1000.0, "zTotTran": 5.0} for d in range(1, 5)]

    async def client_type_history_all(self, ins):
        raise NotAvailable("one-call history unavailable in this test")

    async def client_type_history(self, ins, deven, ttl=0):
        return {"recDate": deven, "buy_I_Volume": 10.0, "buy_I_Value": 1000.0, "buy_I_Count": 5, "sell_I_Volume": 5.0,
                "sell_I_Value": 400.0, "sell_I_Count": 2, "buy_N_Volume": 0.0, "buy_N_Value": 0.0, "buy_N_Count": 0,
                "sell_N_Volume": 0.0, "sell_N_Value": 0.0, "sell_N_Count": 0}

    async def client_type(self, ins):
        return load("client_type")

    async def price_adjustments(self, ins):
        return [{"dEven": 20260803, "pClosing": 2549.0, "pClosingNotAdjusted": 2604.0}]

    async def share_changes(self, ins):
        return [{"dEven": 20260330, "numberOfShareNew": 1935.0, "numberOfShareOld": 1500.0}]

    async def statistics(self, ins):
        return [{"dataType": 1, "dataTypeDesc": "میانگین ارزش 3 ماه", "dataValue": "123"}, {"dataType": 2, "dataTypeDesc": "نام", "dataValue": "abc"}]

    async def etf(self, ins):
        if str(ins) == "999":
            raise NotAvailable("not a fund")
        return {"deven": 20261104, "hEven": 120000, "pRedTran": 90.0, "pSubTran": 92.0}

    async def codal_search(self, **params):
        letters = load("codal_letters")["Letters"]
        return {"Total": 2, "Page": 1, "Letters": letters}

    async def codal_publisher(self, symbol):
        return {"name": "فولاد مبارکه", "isic": "27", "executiveManager": "مدیر", "address": "اصفهان", "telNo": "1", "faxNo": "2", "activitySubject": "فولاد"}

    async def shareholders_last(self, ins):
        return load("shareholders_last")

    async def shareholder_snapshots(self, ins, deven):
        return [{"shareHolderName": "الف", "numberOfShares": 100, "perOfShares": 10, "dEven": 20261103},
                {"shareHolderName": "الف", "numberOfShares": 120, "perOfShares": 12, "dEven": 20261104}]

    async def holder_portfolio(self, share_id):
        return [{"instrument": {"lVal18AFC": "الف", "lVal30": "شرکت"}, "numberOfShares": 5, "perOfShares": 2.0, "changeAmount": 0.0}]

    async def best_limits_history(self, ins, deven, ttl=0):
        return []

    async def identity(self, ins):
        return {}

    async def thresholds(self, ins, deven):
        return []


@pytest.fixture()
def bourse():
    b = Bourse()
    api = MarketApi()
    b.api = api
    b.resolver._api = api
    return b


async def test_market_status_has_both_sources(bourse):
    out = await bourse.market_status()
    assert out["bourse"]["market_state"] == "بسته" and out["gateway"][0]["is_open"] is False
    assert "tehran_time" in out and out["exchange_server_time"].startswith("11/04/2026")


async def test_overview_and_indices_split_headline_from_industries(bourse):
    assert (await bourse.market_overview("fara"))["market"] == "fara-bourse"
    out = await bourse.indices("bourse")
    assert [r["name"] for r in out["headline_indices"]] == ["شاخص کل"]
    assert [r["code"] for r in out["industry_indices"]] == ["27", "57"]  # best change first
    assert all(r["headline"] for r in out["headline_indices"])
    assert (await bourse.indices("bourse", only_selected=True))["industry_indices"] == []


async def test_market_watch_filters_sorts_and_pages(bourse):
    out = await bourse.market_watch(sort_by="value", limit=2)
    assert out["total_instruments"] == 5 and out["matched"] == 4  # the untraded fund is hidden
    assert [r["symbol"] for r in out["rows"]] == ["ج", "الف"] and "best_bid" not in out["rows"][0]
    stocks = await bourse.market_watch(security_type="سهام", industry="بانک", only_traded=False, detail="full")
    assert {r["symbol"] for r in stocks["rows"]} == {"ب", "ه"} and "best_bid" in stocks["rows"][0]
    assert [r["symbol"] for r in (await bourse.market_watch(market="fara"))["rows"]] == ["ه"]
    assert {r["symbol"] for r in (await bourse.market_watch(market="bourse"))["rows"]} == {"الف", "ب", "ج"}
    assert (await bourse.market_watch(min_value=5e9))["matched"] == 2
    ascending = await bourse.market_watch(sort_by="last_pct", descending=False, limit=1)
    assert ascending["rows"][0]["symbol"] == "ب"
    with pytest.raises(InputError):
        await bourse.market_watch(sort_by="nonsense")
    with pytest.raises(InputError):
        await bourse.market_watch(market="nasdaq")


@pytest.mark.parametrize(("kind", "first"), [("gainers", "الف"), ("losers", "ب"), ("value", "ج"), ("volume", "ج")])
async def test_top_movers_plain_rankings(bourse, kind, first):
    out = await bourse.top_movers(kind, limit=3)
    assert out["rows"][0]["symbol"] == first


async def test_buy_and_sell_queues_are_confirmed_against_the_book(bourse):
    buy = await bourse.top_movers("buy_queue")
    assert [(r["symbol"], r["queue_volume"]) for r in buy["rows"]] == [("الف", 7_000_000)]
    sell = await bourse.top_movers("sell_queue")
    assert [(r["symbol"], r["queue_volume"]) for r in sell["rows"]] == [("ب", 4_000_000)]


async def test_real_money_rankings_use_client_type_join(bourse):
    inflow = await bourse.top_movers("real_inflow")
    assert inflow["rows"][0]["symbol"] == "الف" and inflow["rows"][0]["real_net_volume"] == 800
    assert "estimate" in inflow["note"]
    outflow = await bourse.top_movers("real_outflow")
    assert outflow["rows"][0]["symbol"] == "ب"
    power = await bourse.top_movers("real_buyer_power")
    assert all(r["real_buyer_power"] is not None for r in power["rows"])


async def test_industry_summary_and_index_contributors(bourse):
    out = await bourse.industry_summary(limit=50)
    assert out["total_industries"] == 2
    assert len((await bourse.industry_summary(limit=1))["industries"]) == 1
    names = {r["industry"]: r for r in out["industries"]}
    assert names["فلزات اساسی"]["symbols"] == 2 and names["فلزات اساسی"]["in_buy_queue"] == 1
    assert names["بانکها"]["in_sell_queue"] == 1
    contrib = await bourse.index_contributors(limit=2)
    assert contrib["positive"][0]["symbol"] == "الف" and contrib["negative"][0]["symbol"] == "ب"


async def test_market_snapshot(bourse):
    out = await bourse.market_snapshot("2026-11-04", sort_by="volume", limit=2, security_type="all")
    assert out["traded_instruments"] == 5 and out["rows"][0]["volume"] >= out["rows"][1]["volume"]
    assert (await bourse.market_snapshot("2026-11-04"))["traded_instruments"] == 4  # stocks only by default: options and funds are not stocks
    assert (await bourse.market_snapshot("2026-11-04", security_type="fund"))["traded_instruments"] == 1
    assert (await bourse.market_snapshot("2026-11-01"))["count"] == 0
    with pytest.raises(InputError):
        await bourse.market_snapshot("2026-11-04", security_type="crypto")
    with pytest.raises(InputError):
        await bourse.market_snapshot("2026-11-04", sort_by="x")


async def test_holder_moves_skip_unchanged_positions(bourse):
    out = await bourse.market_holder_moves()
    assert out["total_moves"] == 1 and out["moves"][0]["change"] == 100 and out["moves"][0]["change_pct"] == 100.0


async def test_supervisor_messages(bourse):
    market = await bourse.supervisor_messages(None, 5)
    assert market["messages"][0]["truncated"] is True and len(market["messages"][0]["text"]) < 520
    assert not (await bourse.supervisor_messages(None, 5, full_text=True))["messages"][0]["truncated"]
    symbol = await bourse.supervisor_messages("فولاد", 1)
    assert symbol["messages"][0]["title"] == "جدید"  # newest first


async def test_search_symbol_limit(bourse):
    out = await bourse.search_symbol("فولاد", 2)
    assert out["count"] == 2 and out["results"][0]["symbol"] == "فولاد"


async def test_price_history_ranges_and_adjustment(bourse):
    out = await bourse.price_history("فولاد", from_date="20261102", to_date="20261103", limit=10)
    assert [r["date"] for r in out["rows"]] == ["2026-11-02", "2026-11-03"] and out["total_in_range"] == 2
    adjusted = await bourse.price_history("فولاد", adjusted=True)
    assert adjusted["adjusted"] is True and "adjustment_events" in adjusted


async def test_real_legal_flow_history(bourse):
    out = await bourse.real_legal_flow("فولاد", days=3)
    assert len(out["history"]) == 3 and out["history_summary"]["days_with_real_inflow"] == 3
    assert out["history_summary"]["real_net_value_total"] == 3 * 600


async def test_corporate_actions_statistics_etf_codal(bourse):
    actions = await bourse.corporate_actions("فولاد")
    assert actions["price_adjustments"][0]["factor"] == pytest.approx(0.978879, abs=1e-5)
    assert actions["capital_changes"][0]["increase_pct"] == pytest.approx(29.0)
    stats = await bourse.symbol_statistics("فولاد")
    assert stats["metrics"][0]["value"] == 123.0 and stats["metrics"][1]["value"] == "abc"
    nav = await bourse.etf_nav("فولاد")
    assert nav["available"] and nav["nav_redemption"] == 90.0
    filings = await bourse.codal_filings("فولاد", from_date="1405/01/01", title_contains="zzz-no-match")
    assert filings["returned"] == 0
    assert (await bourse.codal_filings("فولاد"))["returned"] == 2
    assert (await bourse.codal_company("فولاد"))["ceo"] == "مدیر"


async def test_shareholder_tools(bourse):
    history = await bourse.shareholder_history("فولاد")
    assert history["snapshots"][1]["holders"][0]["shares_change"] == 20
    portfolio = await bourse.shareholder_portfolio(123)
    assert portfolio["holdings"][0]["symbol"] == "الف"


async def test_symbol_overview_bundles_everything(bourse):
    out = await bourse.symbol_overview("فولاد")
    assert {"identity", "quote", "order_book", "real_legal", "major_shareholders", "recent_filings", "recent_supervisor_messages"} <= set(out)


async def test_etf_nav_reports_non_funds_gracefully():
    class NoEtf(MarketApi):
        async def etf(self, ins):
            raise NotAvailable("500")

    b = Bourse()
    api = NoEtf()
    b.api = api
    b.resolver._api = api
    out = await b.etf_nav("فولاد")
    assert out["available"] is False


async def test_price_history_only_reports_adjustments_that_affect_the_returned_rows():
    class Split(MarketApi):
        async def daily_prices(self, ins):
            def day(d, close, yesterday):
                return {"dEven": d, "pClosing": close, "pDrCotVal": close, "priceYesterday": yesterday, "priceFirst": close,
                        "priceMax": close, "priceMin": close, "qTotTran5J": 1.0, "qTotCap": 1.0, "zTotTran": 1.0}

            return [day(20260101, 100, 100), day(20260102, 102, 100), day(20260103, 51, 51), day(20260104, 52, 51)]

    b = Bourse()
    api = Split()
    b.api = api
    b.resolver._api = api
    everything = await b.price_history("فولاد", adjusted=True)
    assert len(everything["adjustment_events"]) == 1
    recent = await b.price_history("فولاد", adjusted=True, limit=2)  # rows after the split
    assert recent["adjustment_events"] == []


async def test_symbol_overview_survives_a_failing_optional_section():
    from iran_bourse_mcp.client import UpstreamError

    class Flaky(MarketApi):
        async def messages_for(self, ins):
            raise UpstreamError("HTTP 502")

        async def codal_search(self, **params):
            raise NotAvailable("500")

    b = Bourse()
    api = Flaky()
    b.api = api
    b.resolver._api = api
    out = await b.symbol_overview("فولاد")
    assert out["quote"]["last"]["price"] and out["order_book"] is not None
    assert out["unavailable_sections"] == ["recent_filings", "recent_supervisor_messages"]
    assert "recent_filings" not in out
