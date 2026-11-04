"""screen_stocks end to end against a synthetic exchange: history loading, joins, adjustment, sorting, notes."""

from __future__ import annotations

import pytest
from test_service_market import watch_row

from iran_bourse_mcp.client import NotAvailable
from iran_bourse_mcp.service import Bourse, InputError

TODAY = 20261104  # a Wednesday
TRADING_DAYS = [20261103, 20261102, 20261101]  # Tue, Mon, Sun (Thu and Fri never trade)

WATCH = [
    watch_row("الف", "IRO1AAAA0001", 1100, 1000, 1100, 900, 9_000_000, 9.9e9, industry="بانکها", effect="3"),
    watch_row("ب", "IRO1BBBB0001", 970, 1000, 1100, 900, 1_000_000, 9.7e8, industry="بانکها", effect="-1"),
    watch_row("ج", "IRO1CCCC0001", 1010, 1000, 1100, 900, 3_000_000, 3.03e9, industry="خودرو", effect="2"),
    watch_row("ه", "IRO1EEEE0001", 2060, 2000, 2060, 1940, 2_000_000, 4e9, market="فرابورس", industry="خودرو", effect="1"),
    watch_row("د", "IRT1DDDD0001", 100, 100, 103, 97, 0, 0, kind="صندوق قابل معامله"),
]
# (close, volume, close_pct) of each symbol on the three previous trading days, newest first
HISTORY = {
    "IRO1AAAA0001": [(990.0, 1_000_000.0, 1.0), (980.0, 1_000_000.0, 1.0), (970.0, 1_000_000.0, -1.0)],
    "IRO1BBBB0001": [(1000.0, 2_000_000.0, -1.0), (1010.0, 2_000_000.0, -1.0), (1020.0, 2_000_000.0, -1.0)],
    # a 100% bonus issue today: yesterday closed at 2000 while today's reference price is 1000
    "IRO1CCCC0001": [(2000.0, 3_000_000.0, 0.5), (1990.0, 3_000_000.0, 0.5), (1980.0, 3_000_000.0, 0.5)],
    "IRO1EEEE0001": [(1990.0, 1_000_000.0, 2.0), (1950.0, 1_000_000.0, 2.0), (1910.0, 1_000_000.0, 2.0)],
}


def day_table(index):
    rows = []
    for n, (iid, series) in enumerate(HISTORY.items()):
        close, volume, pct = series[index]
        rows.append({"instrumentID": iid, "insCode": 1000 + n, "lVal18AFC": iid[-8:], "pClosing": close, "pDrCotVal": close,
                     "priceYesterday": close / (1 + pct / 100), "priceFirst": close, "priceMax": close * 1.01, "priceMin": close * 0.99,
                     "qTotTran5J": volume, "qTotCap": volume * close, "zTotTran": 50.0})
    for k in range(25):  # filler instruments so the table looks like a trading day
        rows.append({"instrumentID": f"IRO1FILL{k:04d}", "insCode": 5000 + k, "pClosing": 10.0, "pDrCotVal": 10.0, "priceYesterday": 10.0,
                     "priceFirst": 10.0, "priceMax": 10.0, "priceMin": 10.0, "qTotTran5J": 5.0, "qTotCap": 50.0, "zTotTran": 3.0})
    return rows


class ScreenApi:
    def __init__(self):
        self.day_calls: list[int] = []

    async def market_watch(self):
        return WATCH

    async def market_watch_all(self):
        raise NotAvailable("exchange feed unavailable in this test")

    async def market_overview(self, flow):
        return {"marketActivityDEven": TODAY}

    async def prices_on_day(self, deven):
        self.day_calls.append(deven)
        return day_table(TRADING_DAYS.index(deven)) if deven in TRADING_DAYS else []

    async def client_type_all(self):
        return [{"insCode": 1000, "buy_I_Volume": 8e6, "sell_I_Volume": 1e6, "buy_CountI": 100, "sell_CountI": 400,
                 "buy_N_Volume": 1e6, "sell_N_Volume": 8e6},
                {"insCode": 1001, "buy_I_Volume": 1e5, "sell_I_Volume": 8e5, "buy_CountI": 50, "sell_CountI": 20}]

    async def best_limits(self, ins):
        return []


@pytest.fixture()
def bourse():
    b = Bourse()
    b.api = ScreenApi()
    b.resolver._api = b.api
    return b


def symbols(result):
    return [r["symbol"] for r in result["rows"]]


async def test_volume_surge_uses_the_average_of_previous_trading_days(bourse):
    out = await bourse.screen_stocks(filter="volume > 2 * avg(volume, 3)")
    assert symbols(out) == ["الف"]  # 9M today vs a 1M average; ج (3M vs 3M) and ه (2M vs 1M: exactly 2x, not more) do not pass
    assert out["history"]["trading_days_loaded"] == 3 and out["history"]["to"] == "2026-11-03" and out["history"]["from"] == "2026-11-01"
    assert out["as_of"]["date"] == "2026-11-04" and out["matched"] == 1
    row = out["rows"][0]
    assert row["avg(volume, 3)"] == 1_000_000 and row["volume"] == 9_000_000  # the evidence column explains the hit
    assert {"symbol", "last", "close_pct", "volume", "value"} <= set(row)


async def test_thursdays_and_fridays_are_never_requested(bourse):
    await bourse.screen_stocks(filter="avg(volume, 3) > 0")
    requested = {d for d in bourse.api.day_calls}
    assert 20261029 not in requested and 20261030 not in requested  # Thu, Fri


async def test_history_is_adjusted_for_capital_increases_by_default(bourse):
    adjusted = await bourse.screen_stocks(filter="close[1] == 1000 and close[2] == 995")
    assert symbols(adjusted) == ["ج"]
    raw = await bourse.screen_stocks(filter="close[1] == 2000 and close[2] == 1990", adjusted=False)
    assert symbols(raw) == ["ج"] and raw["history"]["adjusted_for_capital_changes"] is False
    assert (await bourse.screen_stocks(filter="close[1] == 2000"))["matched"] == 0


async def test_streaks_and_comparisons_with_yesterday(bourse):
    out = await bourse.screen_stocks(filter="close_pct > 0 and all(close_pct > 0, 3)")
    assert set(symbols(out)) == {"ه", "ج"}  # الف had a red day three sessions ago
    assert set(symbols(await bourse.screen_stocks(filter="close_pct > 0 and all(close_pct > 0, 2)"))) == {"الف", "ه", "ج"}
    out = await bourse.screen_stocks(filter="close_pct < 0 and all(close_pct < 0, 3)")
    assert symbols(out) == ["ب"]
    out = await bourse.screen_stocks(filter="close > close[1]")
    assert set(symbols(out)) == {"الف", "ه", "ج"}


async def test_not_enough_history_means_no_match(bourse):
    out = await bourse.screen_stocks(filter="all(close_pct > -50, 8)")
    assert out["matched"] == 0 and any("Only 3 of the 8" in n for n in out["notes"])


async def test_real_money_flow_fields_join_through_the_daily_table(bourse):
    out = await bourse.screen_stocks(filter="real_net_value > 0 and real_buyer_power > 1", columns=["symbol", "real_net_value", "real_buyer_power"])
    assert symbols(out) == ["الف"] and out["rows"][0]["real_buyer_power"] == pytest.approx((8e6 / 100) / (1e6 / 400))
    assert out["rows"][0]["real_net_value"] == pytest.approx(7e6 * 9.9e9 / 9e6)
    losing = await bourse.screen_stocks(filter="real_net_value < 0")
    assert symbols(losing) == ["ب"]
    assert any("estimated" in n for n in out["notes"])


async def test_universe_filters_and_untraded_symbols(bourse):
    assert set(symbols(await bourse.screen_stocks(filter="value > 0", industry="بانک"))) == {"الف", "ب"}
    assert symbols(await bourse.screen_stocks(filter="value > 0", market="fara")) == ["ه"]
    everything = await bourse.screen_stocks(filter="value >= 0", security_type=None, include_untraded=True)
    assert "د" in symbols(everything) and everything["universe"]["instruments"] == 5
    assert "د" not in symbols(await bourse.screen_stocks(filter="value >= 0", security_type=None))


async def test_sorting_limit_columns_and_aliases(bourse):
    out = await bourse.screen_stocks(filter="value > 0", sort="close_pct", descending=False, limit=2, columns=["close_pct", "value / 1e9 as value_b"])
    assert symbols(out) == ["ب", "ج"] and out["returned"] == 2 and out["matched"] == 4
    assert list(out["rows"][0]) == ["symbol", "close_pct", "value_b"]  # symbol is always shown first
    assert out["rows"][0]["value_b"] == pytest.approx(0.97)
    by_default = await bourse.screen_stocks(filter="value > 0")
    assert symbols(by_default)[0] == "الف"  # value, descending


async def test_presets_work_alone_and_combined_with_a_filter(bourse):
    out = await bourse.screen_stocks(preset="buy_queue")
    assert out["preset"] == "buy_queue" and symbols(out) == ["الف", "ه"]
    narrowed = await bourse.screen_stocks(preset="buy_queue", filter="industry == 'خودرو'")
    assert symbols(narrowed) == ["ه"] and narrowed["filter"].count("(") == 2
    assert (await bourse.screen_stocks(preset="volume-surge"))["preset"] == "volume_surge"


async def test_bad_input_is_reported_as_a_readable_error(bourse):
    for kwargs, message in [
        ({}, "Give a filter"),
        ({"filter": "volum > 1"}, "Did you mean"),
        ({"filter": "volume"}, "condition"),
        ({"preset": "nope"}, "Unknown preset"),
        ({"filter": "volume > 1", "sort": "bogus + 1"}, "Unknown field"),
        ({"filter": "volume > 1", "columns": ["nonsense"]}, "Unknown field"),
    ]:
        with pytest.raises(InputError, match=message):
            await bourse.screen_stocks(**kwargs)


async def test_text_sort_and_missing_sort_values_go_last(bourse):
    out = await bourse.screen_stocks(filter="value > 0", sort="pe")
    assert out["returned"] == 4
    named = await bourse.screen_stocks(filter="value > 0", sort="symbol", descending=False, columns=["symbol"])
    assert symbols(named) == sorted(symbols(named))


async def test_screener_reference_tool(bourse):
    assert "fields" in await bourse.screener_reference()
    with pytest.raises(InputError):
        await bourse.screener_reference("nope")


class GappyApi(ScreenApi):
    """ب did not trade on 2 Nov; ه is missing from the oldest day because it was not listed yet."""

    async def prices_on_day(self, deven):
        rows = await super().prices_on_day(deven)
        drop = {20261102: "IRO1BBBB0001", 20261101: "IRO1EEEE0001"}.get(deven)
        return [r for r in rows if r.get("instrumentID") != drop]


async def test_silent_days_count_as_zero_volume_but_unlisted_days_do_not():
    b = Bourse()
    b.api = GappyApi()
    b.resolver._api = b.api
    out = await b.screen_stocks(filter="volume > 0", columns=["symbol", "avg(volume, 3) as avg3", "volume[2] as vol_2_days_ago"], limit=10)
    rows = {r["symbol"]: r for r in out["rows"]}
    assert rows["ب"]["avg3"] == pytest.approx((2_000_000 + 0 + 2_000_000) / 3) and rows["ب"]["vol_2_days_ago"] == 0
    assert rows["ه"]["avg3"] == pytest.approx(1_000_000)  # only the two sessions it traded in
    streak = await b.screen_stocks(filter="close_pct < 0 and all(close_pct < 0, 3)")
    assert streak["matched"] == 0  # a silent day has no price change, so the streak is broken
