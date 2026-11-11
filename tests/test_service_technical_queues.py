"""technical_indicators, past-day queues in top_movers and the empty-list note, end to end on a synthetic upstream."""

from __future__ import annotations

import datetime as dt

import pytest
from test_service_market import WATCH, MarketApi

from iran_bourse_mcp import service
from iran_bourse_mcp.service import Bourse, InputError

DAY = 20261104


def table_row(watch: dict, ins: int, last: float, high: float, low: float, yesterday: float, value: float) -> dict:
    return {"instrumentID": watch["instrumentId"], "insCode": ins, "lVal18AFC": watch["instrumentName"], "lVal30": "شرکت",
            "pClosing": last, "pDrCotVal": last, "priceYesterday": yesterday, "priceFirst": yesterday, "priceMax": high,
            "priceMin": low, "qTotTran5J": 1000.0, "qTotCap": value, "zTotTran": 50.0}


def book(number, bid, bid_volume, ask, ask_volume, *, ref, time):
    return {"number": number, "pMeDem": bid, "qTitMeDem": bid_volume, "zOrdMeDem": 7 if bid_volume else 0, "pMeOf": ask,
            "qTitMeOf": ask_volume, "zOrdMeOf": 2 if ask_volume else 0, "refID": ref, "hEven": time}


class QueueApi(MarketApi):
    """Wednesday 2026-11-04: الف and ه close in a buy queue, ج at the ceiling with a seller left, ب in a sell queue."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def prices_on_day(self, deven):
        if deven != DAY:
            return []
        alef, be, jim, _, he = WATCH
        rows = [
            table_row(alef, 1000, 1030, 1030, 1000, 1000, 5e9),
            table_row(be, 1001, 970, 1000, 970, 1000, 9e8),
            table_row(jim, 1002, 1030, 1030, 1000, 1000, 9e9),
            table_row(he, 1004, 2060, 2060, 2000, 2000, 4e9),
        ]
        filler = {**alef, "instrumentId": "IRO1ZZZZ0001", "instrumentName": "پرکن"}
        rows += [table_row(filler, 2000 + i, 1001, 1005, 990, 1000, 1e6) for i in range(20)]  # traded, nowhere near a limit
        return rows

    async def thresholds(self, ins, deven, ttl=0):
        self.calls.append(f"thr {ins}")
        upper, lower = (2060.0, 1940.0) if str(ins) == "1004" else (1030.0, 970.0)
        return [{"dEven": deven - 1, "hEven": 1, "psGelStaMax": 1.0, "psGelStaMin": 1.0},
                {"dEven": deven, "hEven": 60125, "psGelStaMax": upper, "psGelStaMin": lower}]

    async def best_limits_history(self, ins, deven, ttl=0):
        self.calls.append(f"book {ins}")
        ins = str(ins)
        if ins == "1000":
            return [book(1, 1030, 500, 0, 0, ref=1, time=90005), book(1, 1030, 800, 0, 0, ref=2, time=122000),
                    book(1, 1030, 1, 990, 5, ref=3, time=133000)]  # after the close: ignored
        if ins == "1002":
            return [book(1, 1030, 500, 0, 0, ref=1, time=90005), book(1, 1030, 100, 1030, 20, ref=2, time=122500)]
        if ins == "1004":
            return [book(1, 2060, 300, 2070, 9, ref=1, time=120500)]  # the ask above the ceiling cannot trade
        if ins == "1001":
            return [book(1, 0, 0, 970, 4000, ref=1, time=100000)]
        return []


@pytest.fixture()
def bourse(monkeypatch):
    monkeypatch.setattr(service, "tehran_now", lambda: dt.datetime(2026, 11, 11, 14, 0))  # Wednesday, after the close
    b = Bourse()
    api = QueueApi()
    b.api = api
    b.resolver._api = api
    return b


async def test_past_buy_queues_are_confirmed_against_the_book_at_the_close(bourse):
    out = await bourse.top_movers("buy_queue", date="1405/08/13")
    assert (out["kind"], out["date"], out["jdate"], out["count"], out["confirmed"]) == ("buy_queue", "2026-11-04", "1405/08/13", 2, 2)
    assert [r["symbol"] for r in out["rows"]] == ["الف", "ه"]  # biggest queue value first; ج had a seller at the close
    top = out["rows"][0]
    assert top["queue_volume"] == 800 and top["queue_orders"] == 7 and top["queue_value"] == 800 * 1030
    assert top["price_limits"] == {"upper": 1030.0, "lower": 970.0}
    assert (top["book_time"], top["queue_since"], top["held_last_30_minutes"]) == ("12:20:00", "09:00:05", True)
    assert (top["last"], top["last_pct"], top["value"], top["trades"]) == (1030.0, 3.0, 5_000_000_000, 50)
    he = out["rows"][1]
    assert he["queue_since"] == "12:05:00" and he["held_last_30_minutes"] is False
    assert out["candidates"] == {
        "traded_instruments": 24, "last_trade_at_day_extreme": 3, "limits_checked": 3,
        "closed_at_official_limit": 3, "order_books_checked": 3,
    }
    assert "GetStaticThreshold" in out["method"] and out["note"] is None and "rial" in out["units"]


async def test_past_queues_filter_and_are_memoised(bourse):
    fara = await bourse.top_movers("buy_queue", market="fara", date="2026-11-04")
    assert [r["symbol"] for r in fara["rows"]] == ["ه"]
    calls = len(bourse.api.calls)
    again = await bourse.top_movers("buy_queue", date="2026-11-04", limit=1)
    assert again["count"] == 1 and again["confirmed"] == 2
    assert len(bourse.api.calls) == calls + 4  # ه's limits and book were remembered: only الف and ج are new
    again_calls = len(bourse.api.calls)
    await bourse.top_movers("buy_queue", date="2026-11-04")
    assert len(bourse.api.calls) == again_calls  # nothing is asked twice
    sell = await bourse.top_movers("sell_queue", date="2026-11-04")
    assert [r["symbol"] for r in sell["rows"]] == ["ب"] and sell["rows"][0]["queue_value"] == 4000 * 970


async def test_past_queue_date_is_validated(bourse):
    with pytest.raises(InputError, match="only with kind='buy_queue'"):
        await bourse.top_movers("gainers", date="2026-11-04")
    with pytest.raises(InputError, match="in the future"):
        await bourse.top_movers("buy_queue", date="2026-11-12")
    holiday = await bourse.top_movers("buy_queue", date="2026-11-05")
    assert holiday["count"] == 0 and "not a trading day" in holiday["note"]
    today = await bourse.top_movers("buy_queue", date="2026-11-11")
    assert "live queues" in today["note"] and "date" not in today


async def test_past_queues_are_capped(bourse, monkeypatch):
    monkeypatch.setattr(service, "PAST_QUEUE_BOOKS", 1)
    out = await bourse.top_movers("buy_queue", date="2026-11-04")
    assert out["candidates"]["order_books_checked"] == 1 and out["note"].startswith("Capped")
    assert out["rows"] == []  # only ج (9B, the largest value) was read, and it is no queue: الف (5B) was cut off


class IdleApi(QueueApi):
    async def market_watch(self):
        return [{**w, "tradeVolume": {"value": 0, "state": 0}, "tradeValue": {"value": 0, "state": 0}} for w in WATCH]


@pytest.fixture()
def idle(monkeypatch):
    monkeypatch.setattr(service, "tehran_now", lambda: dt.datetime(2026, 11, 11, 8, 15))  # Wednesday, before the open
    b = Bourse()
    api = IdleApi()
    b.api = api
    b.resolver._api = api
    return b


async def test_empty_lists_before_the_open_say_why(idle):
    queues = await idle.top_movers("buy_queue")
    assert queues["count"] == 0
    assert "has not started yet" in queues["note"] and "2026-11-10 (1405/08/19)" in queues["note"]
    assert "kind='buy_queue'" in queues["note"]
    gainers = await idle.top_movers("gainers")
    assert "market_snapshot" in gainers["note"]
    watch = await idle.market_watch()
    assert watch["rows"] == [] and "has not started yet" in watch["note"]
    screen = await idle.screen_stocks(filter="close_pct > 1")
    assert any("has not started yet" in n for n in screen["notes"])


async def test_an_empty_list_during_the_session_gets_no_idle_note(bourse):
    out = await bourse.top_movers("sell_queue", market="fara")
    assert out["count"] == 0 and out["note"] is None
    assert (await bourse.market_watch())["note"] is None


class PriceApi(QueueApi):
    async def daily_prices(self, ins):
        start = dt.date(2025, 6, 1)
        rows = []
        for i in range(260):
            day = int((start + dt.timedelta(days=i)).strftime("%Y%m%d"))
            close = 1000.0 + 5 * i
            rows.append({"dEven": day, "pClosing": close, "pDrCotVal": close, "priceYesterday": close - 5, "priceFirst": close,
                         "priceMax": close + 10, "priceMin": close - 10, "qTotTran5J": 1000.0, "qTotCap": close * 1000, "zTotTran": 9.0})
        rows[100] = {**rows[100], "priceMax": 0.0, "priceMin": 0.0, "priceFirst": 0.0, "zTotTran": 0.0, "qTotTran5J": 0.0}  # silent day
        # a capital increase on day 200: yesterday's price drops to half, the series continues from there
        for i in range(200, 260):
            for key in ("pClosing", "pDrCotVal", "priceFirst", "priceMax", "priceMin"):
                rows[i][key] = rows[i][key] / 2
            rows[i]["priceYesterday"] = rows[i]["priceYesterday"] / 2
        return rows


async def test_technical_indicators_use_adjusted_traded_sessions(monkeypatch):
    monkeypatch.setattr(service, "tehran_now", lambda: dt.datetime(2026, 11, 11, 14, 0))
    b = Bourse()
    api = PriceApi()
    b.api = api
    b.resolver._api = api
    out = await b.technical_indicators("فولاد", days=2)
    assert out["sessions_used"] == 259 and out["adjusted"] is True  # the silent day is left out
    assert [e["factor"] for e in out["adjustment_events_last_year"]] == [0.5]
    latest = out["latest"]
    assert latest["close"] == (1000 + 5 * 259) / 2 and out["price"]["close"] == latest["close"]
    assert latest["rsi_14"] == 100.0  # adjusted, the series rises every session: no loss
    assert latest["sma"]["20"] == pytest.approx(sum((1000 + 5 * i) / 2 for i in range(240, 260)) / 20, abs=0.01)
    assert len(out["series"]) == 2 and out["series"][-1]["date"] == out["as_of"]["date"]
    assert "does not publish" in out["note"] and "not investment advice" in out["note"].lower()
    raw = await b.technical_indicators("فولاد", days=0, adjusted=False)
    assert raw["adjustment_events_last_year"] is None and raw["series"] == []
    assert raw["latest"]["rsi_14"] < 100  # unadjusted, the halving is a fall
