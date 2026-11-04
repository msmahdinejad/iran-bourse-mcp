import httpx
import pytest
import respx

from iran_bourse_mcp import client as client_module
from iran_bourse_mcp.api import TseApi
from iran_bourse_mcp.client import Http, NotAvailable, UpstreamError
from iran_bourse_mcp.resolver import Resolver, SymbolError


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_):
        return None

    monkeypatch.setattr(client_module.asyncio, "sleep", instant)


URL = "https://cdn.tsetmc.com/api/x"


@respx.mock
async def test_retries_403_then_succeeds():
    route = respx.get(URL).mock(side_effect=[httpx.Response(403), httpx.Response(200, json={"ok": 1})])
    http = Http()
    assert await http.get_json(URL) == {"ok": 1}
    assert route.call_count == 2
    await http.aclose()


@respx.mock
async def test_persistent_403_mentions_iranian_ip():
    respx.get(URL).mock(return_value=httpx.Response(403))
    http = Http()
    with pytest.raises(UpstreamError) as err:
        await http.get_json(URL)
    assert "Iranian" in str(err.value)
    await http.aclose()


@respx.mock
async def test_500_becomes_not_available():
    respx.get(URL).mock(return_value=httpx.Response(500))
    http = Http()
    with pytest.raises(NotAvailable):
        await http.get_json(URL)
    await http.aclose()


@respx.mock
async def test_network_error_has_hint():
    respx.get(URL).mock(side_effect=httpx.ConnectError("boom"))
    http = Http()
    with pytest.raises(UpstreamError) as err:
        await http.get_json(URL)
    assert "IRAN_BOURSE_PROXY" in str(err.value)
    await http.aclose()


@respx.mock
async def test_cache_serves_until_ttl_expires(monkeypatch):
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"n": 1}))
    http = Http()
    await http.get_json(URL, ttl=60)
    await http.get_json(URL, ttl=60)
    assert route.call_count == 1
    real = client_module.time.monotonic
    monkeypatch.setattr(client_module.time, "monotonic", lambda: real() + 120)
    await http.get_json(URL, ttl=60)
    assert route.call_count == 2
    await http.aclose()


@respx.mock
async def test_uncached_requests_always_hit_the_network():
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"n": 1}))
    http = Http()
    await http.get_json(URL, ttl=0)
    await http.get_json(URL, ttl=0)
    assert route.call_count == 2
    await http.aclose()


@respx.mock
async def test_non_json_body_is_reported():
    respx.get(URL).mock(return_value=httpx.Response(200, text="<html>blocked</html>"))
    http = Http()
    with pytest.raises(UpstreamError, match="Expected JSON"):
        await http.get_json(URL)
    await http.aclose()


# ------------------------------------------------------------------------- resolver
def row(symbol, name, ins, flow=1, code="N1"):
    return {"lVal18AFC": symbol, "lVal30": name, "insCode": ins, "flow": flow, "cgrValCot": code, "cgrValCotTitle": ""}


@respx.mock
async def test_resolver_prefers_exact_symbol_and_normalises(fx):
    respx.get(url__regex=r".*GetInstrumentSearch/.*").mock(
        return_value=httpx.Response(200, json={"instrumentSearch": [row("فولادح", "حق فولاد", "2"), row("فولاد", "فولاد مباركه اصفهان", "1")]})
    )
    http = Http()
    inst = await Resolver(TseApi(http)).resolve("فولاد")
    assert inst.ins_code == "1" and inst.name == "فولاد مبارکه اصفهان"
    await http.aclose()


@respx.mock
async def test_resolver_matches_arabic_and_persian_letter_variants():
    respx.get(url__regex=r".*GetInstrumentSearch/.*").mock(
        return_value=httpx.Response(200, json={"instrumentSearch": [row("كگل", "گل گهر", "7")]})
    )
    http = Http()
    assert (await Resolver(TseApi(http)).resolve("کگل")).ins_code == "7"
    await http.aclose()


@respx.mock
async def test_resolver_same_symbol_on_two_boards_prefers_lowest_flow():
    respx.get(url__regex=r".*GetInstrumentSearch/.*").mock(
        return_value=httpx.Response(200, json={"instrumentSearch": [row("اهرم", "x", "9", flow=3), row("اهرم", "y", "8", flow=1)]})
    )
    http = Http()
    assert (await Resolver(TseApi(http)).resolve("اهرم")).ins_code == "8"
    await http.aclose()


@respx.mock
async def test_resolver_no_exact_match_suggests_alternatives():
    respx.get(url__regex=r".*GetInstrumentSearch/.*").mock(
        return_value=httpx.Response(200, json={"instrumentSearch": [row("فولاد", "فولاد مباركه", "1")]})
    )
    http = Http()
    with pytest.raises(SymbolError, match="Closest"):
        await Resolver(TseApi(http)).resolve("فولادد")
    await http.aclose()


@respx.mock
async def test_resolver_ins_code_goes_through_instrument_info():
    respx.get(url__regex=r".*GetInstrumentInfo/46348559193224090").mock(
        return_value=httpx.Response(200, json={"instrumentInfo": {"lVal18AFC": "فولاد", "lVal30": "فولاد مباركه", "flow": 1}})
    )
    http = Http()
    inst = await Resolver(TseApi(http)).resolve("46348559193224090")
    assert inst.symbol == "فولاد"
    await http.aclose()


async def test_resolver_rejects_empty():
    http = Http()
    with pytest.raises(SymbolError):
        await Resolver(TseApi(http)).resolve("  ")
    await http.aclose()


@respx.mock
async def test_persistent_502_is_reported_as_an_overloaded_server_not_an_ip_problem():
    respx.get(URL).mock(return_value=httpx.Response(502))
    http = Http()
    with pytest.raises(UpstreamError) as err:
        await http.get_json(URL)
    assert "overloaded" in str(err.value) and "Iranian" not in str(err.value) and err.value.status == 502
    await http.aclose()


@respx.mock
async def test_cache_respects_a_byte_budget():
    big = "x" * 4000
    for name in "abc":
        respx.get(f"{URL}/{name}").mock(return_value=httpx.Response(200, json={"v": big}))
    http = Http(max_cache_bytes=10_000)  # room for two 4 kB responses, not three
    for name in "abc":
        await http.get_json(f"{URL}/{name}", ttl=60)
    assert http._cache_bytes <= 10_000 and len(http._cache) == 2
    assert f"j:{URL}/a" not in http._cache  # oldest was evicted
    huge = httpx.Response(200, json={"v": "y" * 20_000})
    respx.get(f"{URL}/huge").mock(return_value=huge)
    await http.get_json(f"{URL}/huge", ttl=60)
    assert f"j:{URL}/huge" not in http._cache  # larger than half the budget: never cached
    await http.aclose()


@respx.mock
async def test_rate_limiting_is_reported_as_such_and_the_host_is_left_alone_for_a_while(monkeypatch):
    route = respx.get(URL).mock(return_value=httpx.Response(429))
    http = Http()
    with pytest.raises(UpstreamError, match=r"Rate-limited by cdn\.tsetmc\.com.*not an Iranian-IP problem") as err:
        await http.get_json(URL)
    assert err.value.status == 429 and "Iranian IP address" not in str(err.value) and route.call_count == 4
    # the cooldown makes the next call (any path on that host) fail at once, without touching the network
    with pytest.raises(UpstreamError, match="rate-limiting this client"):
        await http.get_json("https://cdn.tsetmc.com/api/other")
    assert route.call_count == 4
    other_host = respx.get("https://webgw.tse.ir/x").mock(return_value=httpx.Response(200, json={"ok": 2}))
    assert await http.get_json("https://webgw.tse.ir/x") == {"ok": 2} and other_host.called  # other hosts are unaffected
    real = client_module.time.monotonic()
    monkeypatch.setattr(client_module.time, "monotonic", lambda: real + client_module.RATE_LIMIT_COOLDOWN + 1)
    respx.get("https://cdn.tsetmc.com/api/other").mock(return_value=httpx.Response(200, json={"ok": 3}))
    assert await http.get_json("https://cdn.tsetmc.com/api/other") == {"ok": 3}  # and the host is retried after the cooldown
    await http.aclose()
