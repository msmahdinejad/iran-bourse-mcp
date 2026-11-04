"""The HTTP side of the IME and Iran Energy Exchange endpoints: the JSON POST, the ASMX envelope and the exchange's own error shape."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from conftest import load

from iran_bourse_mcp import client as client_module
from iran_bourse_mcp.api import IEE, IME, TseApi
from iran_bourse_mcp.client import Http, NotAvailable, UpstreamError


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_):
        return None

    monkeypatch.setattr(client_module.asyncio, "sleep", instant)


@respx.mock
async def test_ime_posts_a_json_body_and_unwraps_the_d_envelope():
    route = respx.post(f"{IME}/GetAmareMoamelatList").mock(
        return_value=httpx.Response(200, json=load("commodity_ime_trades"))
    )
    http = Http()
    rows = await TseApi(http).ime_trades("1405/08/13", "1405/08/13", 3)
    assert len(rows) == 11 and rows[0]["Symbol"] == "SRBK-CR08AB-00"
    request = route.calls[0].request
    assert request.headers["content-type"] == "application/json; charset=utf-8"
    assert json.loads(request.content) == {
        "Language": 8,
        "fari": False,
        "GregorianFromDate": "1405/08/13",
        "GregorianToDate": "1405/08/13",
        "MainCat": 3,
        "Cat": 0,
        "SubCat": 0,
        "Producer": 0,
    }
    await http.aclose()


@respx.mock
async def test_ime_dates_are_sent_as_given_and_each_endpoint_has_its_own_service():
    routes = {
        name: respx.post(f"{IME}/{name}").mock(return_value=httpx.Response(200, json={"d": "[]"}))
        for name in (
            "GetHomeFizikiWithDateGrid",
            "GetHomeNamaWithDateGrid",
            "GetHajmArzeshMoamelatDateGrid",
            "GetHomeExchangeRateData",
        )
    }
    http = Http()
    api = TseApi(http)
    assert (
        await api.ime_rings("1405/08/09", "1405/08/13") == []
        and await api.ime_markets("1405/08/09", "1405/08/13") == []
    )
    assert await api.ime_daily("1405/08/01", "1405/08/14") == [] and await api.ime_usd_rate() == []
    body = json.loads(routes["GetHajmArzeshMoamelatDateGrid"].calls[0].request.content)
    assert body == {
        "Language": 8,
        "GregorianFromDate": "1405/08/01",
        "GregorianToDate": "1405/08/14",
    }
    assert json.loads(routes["GetHomeExchangeRateData"].calls[0].request.content) == {"Language": 8}
    await http.aclose()


@respx.mock
async def test_post_answers_are_cached_per_body():
    route = respx.post(f"{IME}/GetHomeFizikiWithDateGrid").mock(
        return_value=httpx.Response(200, json={"d": "[]"})
    )
    http = Http()
    api = TseApi(http)
    await api.ime_rings("1405/08/13", "1405/08/13")
    await api.ime_rings("1405/08/13", "1405/08/13")
    assert route.call_count == 1  # same body: served from the cache
    await api.ime_rings("1405/08/12", "1405/08/12")
    assert route.call_count == 2  # another day is another request
    await http.aclose()


@respx.mock
async def test_ime_errors_are_reported_not_hidden():
    respx.post(f"{IME}/GetAmareMoamelatList").mock(
        return_value=httpx.Response(500, text="The page cannot be displayed")
    )  # what a Gregorian date gets
    http = Http()
    with pytest.raises(NotAvailable):
        await TseApi(http).ime_trades("2026-11-04", "2026-11-04")
    await http.aclose()
    respx.post(f"{IME}/GetHomeExchangeRateData").mock(
        return_value=httpx.Response(200, json={"d": "<html>not json</html>"})
    )
    http = Http()
    with pytest.raises(UpstreamError, match="not JSON"):
        await TseApi(http).ime_usd_rate()
    await http.aclose()


@respx.mock
async def test_a_rate_limited_post_cools_the_host_down():
    respx.post(f"{IME}/GetHomeNamaWithDateGrid").mock(return_value=httpx.Response(429))
    http = Http()
    api = TseApi(http)
    with pytest.raises(UpstreamError, match="Rate-limited"):
        await api.ime_markets("1405/08/13", "1405/08/13")
    with pytest.raises(
        UpstreamError, match="rate-limiting"
    ):  # the second ask is refused locally, without a request
        await api.ime_rings("1405/08/13", "1405/08/13")
    await http.aclose()


@respx.mock
async def test_energy_exchange_query_asks_in_persian_with_encoded_jalali_dates():
    route = respx.get(url__startswith=f"{IEE}/PhysicalMarket/GetTradesStatistics").mock(
        return_value=httpx.Response(200, json=load("energy_iee_physical_trades"))
    )
    http = Http()
    envelope = await TseApi(http).iee_physical_trades("1405/08/13", "1405/08/13")
    assert len(envelope["results"]) == 18 and envelope["pagedMetaData"][0]["totalCount"] == 18
    query = route.calls[0].request.url.params
    assert dict(query) == {
        "Lang": "fa",
        "PageNumber": "1",
        "PageSize": "1000",
        "FromDate": "1405/08/13",
        "ToDate": "1405/08/13",
    }
    assert "FromDate=1405%2F08%2F13" in str(route.calls[0].request.url)
    await http.aclose()


@respx.mock
async def test_each_energy_endpoint_has_its_own_path():
    ok = httpx.Response(200, json={"results": [], "isSuccess": True, "isFailed": False})
    paths = {
        "iee_power_trades": "/PowerMarket/GetPowerTradesStatistics",
        "iee_physical_offers": "/PhysicalMarket/GetPhysicalMarketOffersAuction",
        "iee_power_offers": "/PowerMarket/GetPowerMarketAuctionAnnouncements",
        "iee_markets_today": "/Home/GetTodayMarketsValues",
        "iee_physical_glance": "/PhysicalMarket/GetPhysicalMarketAtAGlance",
        "iee_power_glance": "/PowerMarket/GetPowerMarketAtAGlance",
    }
    for path in paths.values():
        respx.get(url__startswith=f"{IEE}{path}").mock(return_value=ok)
    respx.get(url__startswith=f"{IEE}/PhysicalMarket/GetMarketAuctionDetails/96519").mock(
        return_value=ok
    )
    respx.get(url__startswith=f"{IEE}/PhysicalMarket/GetMarketAuctionDetailsTradeOnDay/96519").mock(
        return_value=ok
    )
    http = Http()
    api = TseApi(http)
    await api.iee_power_trades("1405/08/13", "1405/08/13")
    for name in (
        "iee_physical_offers",
        "iee_power_offers",
        "iee_markets_today",
        "iee_physical_glance",
        "iee_power_glance",
    ):
        await getattr(api, name)()
    await api.iee_auction(96519)
    await api.iee_auction_trades(96519)
    seen = {call.request.url.path for call in respx.calls}
    assert {f"/api{p}" for p in paths.values()} <= seen
    assert (
        "/api/PhysicalMarket/GetMarketAuctionDetails/96519" in seen
        and "/api/PhysicalMarket/GetMarketAuctionDetailsTradeOnDay/96519" in seen
    )
    await http.aclose()


@respx.mock
async def test_energy_exchange_errors_are_surfaced():
    respx.get(url__startswith=f"{IEE}/Home/GetTodayMarketsValues").mock(
        return_value=httpx.Response(
            200, json={"results": [], "isSuccess": False, "isFailed": True, "errors": ["خطا"]}
        )
    )
    respx.get(url__startswith=f"{IEE}/PowerMarket/GetPowerMarketAtAGlance").mock(
        return_value=httpx.Response(200, json=[1, 2])
    )
    respx.get(url__startswith=f"{IEE}/PhysicalMarket/GetMarketAuctionDetails/1").mock(
        return_value=httpx.Response(400)
    )
    http = Http()
    api = TseApi(http)
    with pytest.raises(UpstreamError, match="reported an error"):
        await api.iee_markets_today()
    with pytest.raises(UpstreamError, match="unexpected shape"):
        await api.iee_power_glance()
    with pytest.raises(NotAvailable):
        await api.iee_auction(1)
    await http.aclose()
