"""Service wiring of commodity_market and energy_market against responses recorded on 2026-11-05: which upstream calls are made, in which order."""

from __future__ import annotations

import datetime as dt
import json

import pytest
from conftest import load

from iran_bourse_mcp import service as service_module
from iran_bourse_mcp.client import NotAvailable, UpstreamError
from iran_bourse_mcp.service import Bourse, InputError


def wire(name: str, key: str | None = None) -> list[dict]:
    data = load(name)
    return json.loads((data[key] if key else data)["d"])


class ExchangeApi:
    """Answers each exchange endpoint with the payload recorded live (the same methods as TseApi, in the same order)."""

    def __init__(self, *, quiet_week: bool = False, usd_fails: bool = False):
        self.calls: list[tuple] = []
        self.quiet_week = quiet_week
        self.usd_fails = usd_fails

    # IME ----------------------------------------------------------------------------------
    async def ime_daily(self, first, last):
        self.calls.append(("ime_daily", first, last))
        return [] if self.quiet_week else wire("commodity_ime_rollups", "daily")

    async def ime_trades(self, jalali_from, jalali_to, main_cat=0):
        self.calls.append(("ime_trades", jalali_from, jalali_to, main_cat))
        return (
            wire("commodity_ime_rollups", "thursday")
            if jalali_from == "1405/08/14"
            else wire("commodity_ime_trades")
        )

    async def ime_rings(self, jalali_from, jalali_to):
        self.calls.append(("ime_rings", jalali_from, jalali_to))
        return wire("commodity_ime_rollups", "rings")

    async def ime_markets(self, jalali_from, jalali_to):
        self.calls.append(("ime_markets", jalali_from, jalali_to))
        return wire("commodity_ime_rollups", "markets")

    async def ime_usd_rate(self):
        self.calls.append(("ime_usd_rate",))
        if self.usd_fails:
            raise UpstreamError("down")
        return wire("commodity_ime_rollups", "usd")

    # Iran Energy Exchange -------------------------------------------------------------------
    async def iee_physical_trades(self, jalali_from, jalali_to, page_size=1000):
        self.calls.append(("iee_physical_trades", jalali_from, jalali_to))
        return load("energy_iee_physical_trades")

    async def iee_power_trades(self, jalali_from, jalali_to, page_size=1000):
        self.calls.append(("iee_power_trades", jalali_from, jalali_to))
        envelope = load("energy_iee_power_trades")
        return (
            {**envelope, "pagedMetaData": [{**envelope["pagedMetaData"][0], "hasNext": True}]}
            if self.quiet_week
            else envelope
        )

    async def iee_physical_offers(self, page_size=50):
        self.calls.append(("iee_physical_offers", page_size))
        return load("energy_iee_physical_offers")

    async def iee_power_offers(self, page_size=20):
        self.calls.append(("iee_power_offers", page_size))
        return load("energy_iee_power_offers")

    async def iee_auction(self, auction_id):
        self.calls.append(("iee_auction", auction_id))
        if auction_id == 1:
            raise NotAvailable("HTTP 400")
        if auction_id == 2:
            return {"results": []}
        return load("energy_iee_auction")["detail"]

    async def iee_auction_trades(self, auction_id):
        self.calls.append(("iee_auction_trades", auction_id))
        return load("energy_iee_auction")["trades"]

    async def iee_markets_today(self):
        self.calls.append(("iee_markets_today",))
        return load("energy_iee_overview")["today"]

    async def iee_physical_glance(self):
        self.calls.append(("iee_physical_glance",))
        return load("energy_iee_overview")["physical"]

    async def iee_power_glance(self):
        self.calls.append(("iee_power_glance",))
        return load("energy_iee_overview")["power"]


def make(monkeypatch, **kwargs) -> Bourse:
    monkeypatch.setattr(
        service_module, "tehran_now", lambda: dt.datetime(2026, 11, 5, 9, 0)
    )  # Thursday morning: the last session is Wednesday's
    b = Bourse()
    b.api = ExchangeApi(**kwargs)
    return b


@pytest.fixture()
def bourse(monkeypatch):
    return make(monkeypatch)


# ------------------------------------------------------------------------------- commodity_market


async def test_commodity_trades_find_the_latest_session_then_read_its_rows(bourse):
    out = await bourse.commodity_market(limit=3)
    assert bourse.api.calls == [
        ("ime_daily", "1405/08/01", "1405/08/14"),
        ("ime_trades", "1405/08/13", "1405/08/13", 0),
    ]
    assert out["date"] == "2026-11-04" and out["latest_session"] is True and out["returned"] == 3
    assert out["rows"][0]["symbol"] == "SRBK-CR08AB-00" and out["totals"]["traded_rows"] == 9


async def test_an_explicit_date_skips_the_lookup_and_is_sent_as_jalali(bourse):
    out = await bourse.commodity_market(date="2026-11-04", group="steel", product="مس")
    assert bourse.api.calls == [("ime_trades", "1405/08/13", "1405/08/13", 1)]
    assert (
        out["latest_session"] is False
        and out["filters"]["group"] == "صنعتی"
        and out["totals"]["rows"] == 1
    )
    bourse.api.calls.clear()
    await bourse.commodity_market(date="1405/08/09", to_date="2026-11-04")
    assert bourse.api.calls == [("ime_trades", "1405/08/09", "1405/08/13", 0)]


async def test_a_thursday_is_an_empty_session_not_an_error(bourse):
    out = await bourse.commodity_market(date="1405/08/14")
    assert out["rows"] == [] and any("Saturday to Wednesday" in n for n in out["notes"])


async def test_commodity_summary_reuses_the_lookup_for_the_daily_series(bourse):
    out = await bourse.commodity_market(view="summary")
    assert [c[0] for c in bourse.api.calls] == [
        "ime_daily",
        "ime_rings",
        "ime_markets",
        "ime_usd_rate",
    ]
    assert (
        out["physical_total"]["traded_tons"] == 181_729.0
        and out["daily"][-1]["date"] == "2026-11-04"
        and out["usd_rate"]["rial_per_usd"] == 1_878_192.0
    )


async def test_commodity_summary_of_a_given_day_asks_for_the_ten_sessions_before_it(bourse):
    await bourse.commodity_market(view="summary", date="1405/08/13")
    assert ("ime_daily", "1405/08/04", "1405/08/13") in bourse.api.calls and (
        "ime_rings",
        "1405/08/13",
        "1405/08/13",
    ) in bourse.api.calls
    bourse.api.calls.clear()
    await bourse.commodity_market(view="summary", date="1405/08/09", to_date="1405/08/13")
    assert (
        bourse.api.calls[0] == ("ime_rings", "1405/08/09", "1405/08/13")
        and ("ime_daily", "1405/08/09", "1405/08/13") in bourse.api.calls
    )


async def test_summary_survives_a_failed_dollar_rate(monkeypatch):
    b = make(monkeypatch, usd_fails=True)
    out = await b.commodity_market(view="summary")
    assert out["usd_rate"] is None and out["physical_rings"]


async def test_no_session_in_two_weeks_is_an_actionable_error(monkeypatch):
    b = make(monkeypatch, quiet_week=True)
    with pytest.raises(InputError, match="no physical-market session"):
        await b.commodity_market()


async def test_commodity_rejects_bad_arguments(bourse):
    for kwargs in (
        {"view": "chart"},
        {"date": "garbage"},
        {"group": "7"},
        {"sort_by": "colour"},
        {"limit": 0},
        {"to_date": "2026-11-04"},
    ):
        with pytest.raises(InputError):
            await bourse.commodity_market(**kwargs)
    assert bourse.api.calls == []  # nothing was asked of the exchange


# ------------------------------------------------------------------------------- energy_market


async def test_energy_trades_search_the_last_week_for_the_newest_session(bourse):
    out = await bourse.energy_market(limit=2)
    assert bourse.api.calls == [
        ("iee_physical_trades", "1405/08/08", "1405/08/14"),
        ("iee_power_trades", "1405/08/08", "1405/08/14"),
    ]
    assert (
        out["date"] == "2026-11-04"
        and out["latest_session"] is True
        and out["markets"] == ["physical", "power"]
    )
    assert out["rows"][0]["auction_id"] == 96517 and any(
        "No power auctions" in n for n in out["notes"]
    )


async def test_energy_trades_of_one_market_and_a_range(bourse):
    out = await bourse.energy_market(market="power", date="1405/08/05", to_date="2026-11-04")
    assert bourse.api.calls == [("iee_power_trades", "1405/08/05", "1405/08/13")]
    assert out["totals"]["traded_auctions"] == 6 and out["totals"]["volume_by_unit"] == {
        E_POWER_UNIT: 352000.0
    }
    assert out["date_from"] == "2026-10-27" and out["date_to"] == "2026-11-04"


E_POWER_UNIT = "کیلووات در هر ساعت از دوره مصرف در دوره تحویل"


async def test_a_full_page_is_reported_as_truncated(monkeypatch):
    b = make(monkeypatch, quiet_week=True)
    out = await b.energy_market(market="power", date="1405/08/05", to_date="1405/08/13")
    assert any("only the first page" in n for n in out["notes"])


async def test_energy_offers_read_one_market_after_the_other(bourse):
    out = await bourse.energy_market(view="offers")
    assert bourse.api.calls == [("iee_physical_offers", 50), ("iee_power_offers", 20)]
    assert out["announced"] == {"physical": 4, "power": 3} and out["returned"] == 7
    assert out["rows"][0]["market"] == "power"  # 2026-11-07 comes before 2026-11-08
    assert any(
        "may have announced more" in n and "physical" in n for n in out["notes"]
    )  # a page of upcoming auctions only, with more behind it
    only = await bourse.energy_market(view="offers", market="physical", product="گاز", limit=2)
    assert only["returned"] == 2 and {r["product"] for r in only["rows"]} == {"گاز مایع"}


async def test_energy_auction_reads_the_detail_and_its_trades(bourse):
    out = await bourse.energy_market(view="auction", auction_id=96519)
    assert bourse.api.calls == [("iee_auction", 96519), ("iee_auction_trades", 96519)]
    assert (
        out["totals"]["value_rial"] == 3_818_790_300_000
        and out["units"]["price_basis"] == "rial per kilogram"
    )


async def test_unknown_auction_ids_are_actionable_errors(bourse):
    for auction_id in (1, 2):  # HTTP 400, then an empty answer
        with pytest.raises(InputError, match="has no auction"):
            await bourse.energy_market(view="auction", auction_id=auction_id)
    assert ("iee_auction_trades", 1) not in bourse.api.calls


async def test_energy_overview_makes_three_cheap_calls(bourse):
    out = await bourse.energy_market(view="overview")
    assert [c[0] for c in bourse.api.calls] == [
        "iee_markets_today",
        "iee_physical_glance",
        "iee_power_glance",
    ]
    assert out["power_market"]["state"] == "بسته" and len(out["traded_today"]) == 4


async def test_energy_rejects_bad_arguments(bourse):
    for kwargs in (
        {"view": "chart"},
        {"market": "coal"},
        {"view": "auction"},
        {"date": "garbage"},
        {"date": "2026-10-01", "to_date": "2026-11-04"},
        {"limit": 1000},
    ):
        with pytest.raises(InputError):
            await bourse.energy_market(**kwargs)
    assert bourse.api.calls == []
