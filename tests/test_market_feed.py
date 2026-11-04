"""The whole-market feed: instrument classification, row shaping, the service built on it, and the gateway fallback."""

from __future__ import annotations

import pytest
from test_service_market import watch_row

from iran_bourse_mcp import market as M
from iran_bourse_mcp.client import NotAvailable
from iran_bourse_mcp.service import Bourse


def feed_row(symbol, ins_id, ins_code, *, yval=300, flow=1, board="N1", sector="27 ", last=1000.0, close=None, py=1000.0, upper=1100.0,
             lower=900.0, volume=1_000_000.0, value=1e9, trades=50, book=None, pe=None, shares=1e9, nav=0.0, oi=0, name=None):
    return {
        "lva": symbol, "lvc": name or "شرکت " + symbol, "eps": 100.0, "pe": pe, "pmd": last, "pmo": last, "qtj": volume, "pdv": last,
        "ztt": trades, "qtc": value, "bv": 1.0, "pc": last - py, "pcpc": (close or last) - py, "pmn": last, "pmx": last, "py": py, "pf": last,
        "pcl": close or last, "yVal": yval, "flow": flow, "cGrValCot": board, "yMarNSC": "NO", "csv": sector, "insID": ins_id, "pMax": upper,
        "pMin": lower, "ztd": shares, "pRedTran": nav, "buyOP": oi, "insCode": ins_code, "hEven": 123000,
        "blDs": book if book is not None else [{"n": 0, "qmd": 0, "zmd": 0, "pmd": 0.0, "pmo": 0.0, "zmo": 0, "qmo": 0}],
    }


def level(n, bid, bid_qty, bid_orders, ask, ask_qty, ask_orders):
    return {"n": n, "pmd": bid, "qmd": bid_qty, "zmd": bid_orders, "pmo": ask, "qmo": ask_qty, "zmo": ask_orders}


FEED = [
    # A: a share locked at its upper limit with nothing offered: a buy queue
    feed_row("الف", "IRO1AAAA0001", "111", last=1100.0, close=1090.0, upper=1100.0, lower=900.0, volume=5e6, value=5.4e9, trades=120, pe="6.2",
             book=[level(1, 1100, 9_000_000, 100, 0, 0, 0), level(2, 1090, 1_000_000, 20, 0, 0, 0), level(3, 1080, 500_000, 8, 0, 0, 0)]),
    # B: a Fara Bourse share at its lower limit with only sellers: a sell queue
    feed_row("ب", "IRO1BBBB0001", "222", flow=2, board="Z1", sector="57 ", last=900.0, volume=2e6, value=1.8e9,
             book=[level(1, 0, 0, 0, 900, 7_000_000, 60)]),
    # C: an ETF trading 10% under its redemption NAV
    feed_row("ج", "IRT1CCCC0001", "333", yval=305, board="5A", sector="68 ", last=90.0, py=90.0, upper=99.0, lower=81.0, volume=3e6, value=2.7e8, nav=100.0),
    # D: a call option (flow 3 is shared by derivatives and debt papers)
    feed_row("ضفلا", "IRO9DDDD0001", "444", yval=311, flow=3, board="31", sector="  ", last=500.0, py=480.0, upper=900.0, lower=100.0, oi=1500,
             name="اختيارخ فولاد-4000-1405/09/10"),
    # E: a TAL (closing-price only) row, whose limits are equal
    feed_row("تال3", "IRO1EEEE0001", "555", board="F3", last=1000.0, upper=1000.0, lower=1000.0),
    # F: a share that did not trade today (the feed repeats yesterday's price)
    feed_row("ه", "IRO1FFFF0001", "666", last=1000.0, volume=0.0, value=0.0, trades=0),
]
STATIC = [{"type": "IndustrialGroup", "code": 27, "name": "فلزات اساسی   "}, {"type": "IndustrialGroup", "code": 57, "name": "بانکها و موسسات اعتباری"},
          {"type": "PaperType", "code": 1, "name": "سهام"}]
GATEWAY = [watch_row("الف", "IRO1AAAA0001", 1100, 1000, 1100, 900, 5_000_000, 5.4e9, effect="12.5")]


class FeedApi:
    def __init__(self, feed=FEED):
        self.feed, self.best_limit_calls, self.flow_calls = feed, [], 0

    async def market_watch_all(self):
        if self.feed is None:
            raise NotAvailable("feed down")
        return self.feed

    async def static_data(self):
        return STATIC

    async def market_watch(self):
        return GATEWAY

    async def market_overview(self, flow):
        return {"marketActivityDEven": 20261104}

    async def prices_on_day(self, deven):
        return []

    async def client_type_all(self):
        self.flow_calls += 1
        return [{"insCode": 111, "buy_I_Volume": 4e6, "sell_I_Volume": 1e6, "buy_CountI": 50, "sell_CountI": 100, "buy_N_Volume": 1e6, "sell_N_Volume": 4e6}]

    async def best_limits(self, ins):
        self.best_limit_calls.append(str(ins))
        if str(ins) == "111":
            return [{"number": 1, "pMeDem": 1100, "qTitMeDem": 9_000_000, "zOrdMeDem": 100, "pMeOf": 0, "qTitMeOf": 0, "zOrdMeOf": 0}]
        return []


@pytest.fixture()
def bourse():
    b = Bourse()
    b.api = FeedApi()
    b.resolver._api = b.api
    return b


def symbols(result):
    return [r["symbol"] for r in result["rows"]]


# ------------------------------------------------------------------------------ classification


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"yVal": 300, "flow": 1, "cGrValCot": "N1", "lva": "فولاد"}, "سهام"),
        ({"yVal": 303, "flow": 2, "cGrValCot": "Z1", "lva": "x"}, "سهام"),
        ({"yVal": 309, "flow": 4, "cGrValCot": "P1", "lva": "x"}, "بازار پایه فرابورس"),
        ({"yVal": 305, "flow": 1, "cGrValCot": "5A", "lva": "اهرم"}, "صندوق سرمایه گذاری"),
        ({"yVal": 311, "flow": 3, "cGrValCot": "31", "lva": "ضهرم8024"}, "اختیار معامله"),
        ({"yVal": 263, "flow": 3, "cGrValCot": "F1", "lva": "x"}, "آتی"),
        ({"yVal": 306, "flow": 3, "cGrValCot": "N4", "lva": "x"}, "اوراق بدهی"),
        ({"yVal": 400, "flow": 1, "cGrValCot": "N1", "lva": "x"}, "حق تقدم"),
        ({"yVal": 308, "flow": 7, "cGrValCot": "x", "lva": "x"}, "بورس کالا"),
        ({"yVal": 300, "flow": 1, "cGrValCot": "N1", "lva": "تسهیلات1"}, "تسهیلات مسکن"),
        ({"yVal": 300, "flow": 1, "cGrValCot": "F3 ", "lva": "سآبیک3"}, "معاملات پایانی TAL"),
        ({"yVal": 999, "flow": 6, "cGrValCot": "x", "lva": "x"}, "انرژی"),
        ({"yVal": 999, "flow": 1, "cGrValCot": "x", "lva": "x"}, "سایر"),
    ],
)
def test_instrument_classes_follow_the_exchange_site(raw, expected):
    assert M.classify_instrument(raw) == expected


def test_fara_split_and_type_words():
    assert M.is_fara({"flow": 2, "yVal": 300}) and M.is_fara({"flow": 4, "yVal": 309}) and not M.is_fara({"flow": 1, "yVal": 300})
    assert not M.is_fara({"flow": 3, "yVal": 320}) and M.is_fara({"flow": 3, "yVal": 311})
    assert M.security_type_matches("سهام", None) and not M.security_type_matches(M.TYPE_TAL, None)
    assert M.security_type_matches(M.TYPE_TAL, "all") and M.security_type_matches("صندوق سرمایه گذاری", "ETF")
    assert M.security_type_matches("اختیار معامله", "options") and not M.security_type_matches("سهام", "fund")
    assert M.security_type_matches("سهام عادی", "سهام")  # gateway-style names still match


# ---------------------------------------------------------------------------------- shaping


def test_shape_market_row_buy_queue_book_and_names():
    industries = M.industry_names(STATIC)
    assert industries == {"27": "فلزات اساسی", "57": "بانکها و موسسات اعتباری"}
    row = M.shape_market_row(FEED[0], industries=industries, gateway=M.gateway_extras(GATEWAY[0]))
    assert row["symbol"] == "الف" and row["ins_code"] == "111" and row["instrument_id"] == "IRO1AAAA0001"
    assert row["last"] == 1100 and row["close"] == 1090 and row["last_pct"] == 10.0 and row["close_pct"] == 9.0
    assert row["at_upper_limit"] and row["buy_queue_probable"] and not row["sell_queue_probable"]
    assert row["best_bid"] == {"price": 1100.0, "volume": 9_000_000, "orders": 100} and row["best_ask"]["volume"] is None
    assert [lv["bid_volume"] for lv in row["book"]] == [9_000_000, 1_000_000, 500_000, None, None]
    assert row["pe"] == 6.2 and row["market_cap"] == 1090 * 1_000_000_000 and row["base_volume"] == 1.0 and row["shares"] == 1_000_000_000
    assert row["industry"] == "فلزات اساسی" and row["board"] == "بازار اول" and row["effect_on_index"] == 12.5
    assert row["security_type"] == "سهام" and row["market"] == "بورس" and row["fara"] is False and row["status"] == "مجاز"


def test_shape_market_row_sell_queue_untraded_tal_and_fund():
    sell = M.shape_market_row(FEED[1])
    assert sell["at_lower_limit"] and sell["sell_queue_probable"] and sell["market"] == "فرابورس" and sell["fara"] is True
    untraded = M.shape_market_row(FEED[5])
    assert untraded["last"] is None and untraded["close_pct"] is None and not untraded["at_upper_limit"] and untraded["volume"] == 0
    tal = M.shape_market_row(FEED[4])
    assert tal["security_type"] == M.TYPE_TAL and not tal["at_upper_limit"] and not tal["at_lower_limit"]  # equal limits mean nothing
    fund = M.shape_market_row(FEED[2])
    assert fund["nav"] == 100.0 and fund["security_type"] == "صندوق سرمایه گذاری"
    option = M.shape_market_row(FEED[3])
    assert option["open_interest"] == 1500 and option["market"] == "بازار مشتقه" and option["industry"] is None


# ------------------------------------------------------------------------------------ service


async def test_market_watch_defaults_to_stocks_and_reports_its_source(bourse):
    out = await bourse.market_watch()
    assert out["source"] == "tsetmc" and out["total_instruments"] == 6
    assert symbols(out) == ["الف", "ب"]  # the fund, option, TAL row and the untraded share are not stocks that traded
    assert all("book" not in r for r in (await bourse.market_watch(detail="full"))["rows"])
    assert symbols(await bourse.market_watch(security_type="fund")) == ["ج"]
    assert symbols(await bourse.market_watch(security_type="option")) == ["ضفلا"]
    assert set(symbols(await bourse.market_watch(security_type="all"))) == {"الف", "ب", "ج", "ضفلا", "تال3"}
    assert symbols(await bourse.market_watch(market="fara")) == ["ب"] and "ب" not in symbols(await bourse.market_watch(market="bourse"))
    assert symbols(await bourse.market_watch(industry="فلزات")) == ["الف"]


async def test_queues_and_real_flow_use_the_feeds_ins_code_without_an_index(bourse):
    queues = await bourse.top_movers("buy_queue")
    assert [r["symbol"] for r in queues["rows"]] == ["الف"] and queues["rows"][0]["queue_volume"] == 9_000_000
    assert bourse.api.best_limit_calls == ["111"]  # straight from the row, no end-of-day table lookup
    flows = await bourse.top_movers("real_inflow")
    assert [r["symbol"] for r in flows["rows"]] == ["الف"] and flows["rows"][0]["real_net_volume"] == 3_000_000


async def test_screener_sees_the_extra_fields_of_the_feed(bourse):
    depth = await bourse.screen_stocks(filter="qd1 > 0 and qd2 > 0 and qd3 > 0 and ask_volume_5 == 0",
                                       columns=["symbol", "pd2", "qd2", "bid_volume_5", "ask_volume_5", "shares", "bvol"])
    assert symbols(depth) == ["الف"] and depth["rows"][0]["bid_volume_5"] == 10_500_000 and depth["rows"][0]["shares"] == 1_000_000_000
    assert depth["universe"]["instruments"] == 2
    funds = await bourse.screen_stocks(filter="nav_premium_pct < -5 and predtran > 0", security_type="fund", columns=["symbol", "last", "nav", "nav_premium_pct"])
    assert funds["rows"] == [{"symbol": "ج", "last": 90, "nav": 100, "nav_premium_pct": -10}]
    options = await bourse.screen_stocks(filter="buyop > 1000 and open_interest < 2000", security_type="option", columns=["symbol", "open_interest"])
    assert options["rows"] == [{"symbol": "ضفلا", "open_interest": 1500}]
    assert symbols(await bourse.screen_stocks(preset="buy_queue")) == ["الف"] and symbols(await bourse.screen_stocks(preset="sell_queue")) == ["ب"]
    flowed = await bourse.screen_stocks(filter="real_net_volume > 0 and real_buyer_power > 5")
    assert symbols(flowed) == ["الف"]  # 4M bought by 50 people vs 1M sold by 100: power (80k / 10k) is 8


async def test_feed_outage_falls_back_to_the_gateway_and_says_so():
    b = Bourse()
    b.api = FeedApi(feed=None)
    b.resolver._api = b.api
    out = await b.market_watch(security_type=None)
    assert out["source"] == "tse-gateway" and out["total_instruments"] == 1 and symbols(out) == ["الف"]
    screened = await b.screen_stocks(filter="volume > 0")
    assert symbols(screened) == ["الف"]


def test_orders_beyond_the_limits_do_not_break_a_queue_in_the_feed_either():
    book = [level(1, 4330, 98_499_098, 609, 4340, 250_526, 10)]  # فولاد: the only ask is above the 4,330 ceiling
    row = M.shape_market_row(feed_row("فولاد", "IRO1FOLD0001", "46348559193224090", last=4330.0, py=4210.0, upper=4330.0, lower=4090.0, book=book))
    assert row["at_upper_limit"] and row["buy_queue_probable"]
    open_book = [level(1, 4330, 100, 1, 4330, 50, 1)]  # an ask AT the ceiling can still trade
    assert not M.shape_market_row(feed_row("x", "IRO1XXXX0001", "1", last=4330.0, py=4210.0, upper=4330.0, lower=4090.0, book=open_book))["buy_queue_probable"]
    sell = [level(1, 4000, 100, 1, 4090, 8_000_000, 90)]  # a bid below the 4,090 floor is next-session too
    flagged = M.shape_market_row(feed_row("y", "IRO1YYYY0001", "2", last=4090.0, py=4210.0, upper=4330.0, lower=4090.0, book=sell))
    assert flagged["at_lower_limit"] and flagged["sell_queue_probable"]
