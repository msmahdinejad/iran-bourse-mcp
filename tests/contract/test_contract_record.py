"""The recorder (scripts/record_contract.py) without a network: trimming, throttling, retries and secret stripping."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "record_contract.py"
_spec = importlib.util.spec_from_file_location("record_contract", SCRIPT)
rc = importlib.util.module_from_spec(_spec)
sys.modules["record_contract"] = rc
_spec.loader.exec_module(rc)

NOW = dt.datetime(2026, 11, 5, 9, 30, 0)
CDN = "https://cdn.tsetmc.com/api"


class FakeTime:
    """A clock that only moves when the recorder sleeps, so the pauses can be asserted instead of waited for."""

    def __init__(self) -> None:
        self.now, self.sleeps = 0.0, []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def recorder(handler, **kwargs) -> tuple[rc.RecordingTransport, FakeTime, list[httpx.Request]]:
    fake, seen = FakeTime(), []

    def inner(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    transport = rc.RecordingTransport(
        httpx.MockTransport(inner), now=NOW, sleep=fake.sleep, clock=fake.clock, **kwargs
    )
    return transport, fake, seen


async def get(transport: rc.RecordingTransport, url: str) -> httpx.Response:
    async with httpx.AsyncClient(transport=transport) as client:
        return await client.get(url)


IME = "https://www.ime.co.ir/SubSystems/IME/Services/Home/imedata.asmx"


async def post(transport: rc.RecordingTransport, url: str, body: object) -> httpx.Response:
    async with httpx.AsyncClient(transport=transport) as client:
        return await client.post(url, json=body)


def ime_row(hall: str, total: float, quantity: float = 1.0, **extra) -> dict:
    return {"Talar": hall, "TotalPrice": total, "Quantity": quantity, "Unit": "تن", **extra}


def market_row(
    symbol: str, code: int, value: float, *, upper_locked: bool = False, traded: bool = True
) -> dict:
    """A GetMarketWatch row; ``upper_locked`` makes a buy queue (last at the ceiling, bids waiting, no asks)."""
    price = 1000.0
    book = (
        [{"n": 1, "pmd": price, "qmd": 5000, "zmd": 3, "pmo": 0, "qmo": 0, "zmo": 0}]
        if upper_locked
        else []
    )
    return {
        "lva": symbol,
        "insCode": str(code),
        "insID": f"IRO1{code:08d}",
        "qtc": value,
        "ztt": 10 if traded else 0,
        "qtj": value / price,
        "pdv": price,
        "pcl": price,
        "py": 950.0,
        "pMax": price,
        "pMin": 900.0,
        "yVal": 300,
        "flow": 1,
        "cGrValCot": "N1",
        "blDs": book,
    }


def test_keep_newest_keeps_whole_rows_in_upstream_order_and_says_what_was_cut():
    rows = [{"dEven": d, "a": d * 2, "b": [d], "c": None} for d in (3, 9, 1, 7, 5)]
    body = {"series": list(rows)}
    notes = rc.keep_newest(body, "series", 3, "dEven")
    assert body["series"] == [
        rows[1],
        rows[3],
        rows[4],
    ]  # the 3 largest, still in the order the server sent them, fields untouched
    assert notes == [{"path": "series", "kept": 3, "of": 5, "rule": "newest 3 rows by dEven"}]
    assert rc.keep_newest(body, "series", 10, "dEven") == []  # nothing to cut, nothing to say


def test_keep_where_and_keep_first_report_only_real_cuts():
    body = {"rows": [{"k": 1}, {"k": 2}, {"k": 3}]}
    assert rc.keep_where(body, "rows", lambda r: r["k"] != 2, "no twos")[0]["of"] == 3
    assert body["rows"] == [{"k": 1}, {"k": 3}]
    assert rc.keep_first(body, "rows", 5) == []
    assert rc.keep_first(body, "rows", 1)[0]["kept"] == 1
    with pytest.raises(rc.RecordingError, match="expected a list"):
        rc.keep_first({"rows": 3}, "rows", 1)


def test_the_instrument_set_keeps_the_busiest_queues_and_pinned_symbols():
    rows = [market_row(f"س{i}", 100 + i, 1e9 * (200 - i)) for i in range(150)]
    rows.append(market_row("صف", 900, 1.0, upper_locked=True))  # tiny value but a buy queue
    rows.append(market_row("فولاد", 901, 1.0))  # pinned
    rows.append(market_row("بیکار", 902, 0.0, traded=False))
    universe = rc.build_universe(rows)
    assert {
        "100",
        "189",
        "900",
        "901",
        "902",
    } <= universe.ins_codes  # quota of 90 busiest shares, queue, pinned, idle
    assert "190" not in universe.ins_codes  # the 91st busiest share is cut
    assert universe.ins_ids == {f"IRO1{int(code):08d}" for code in universe.ins_codes}


async def test_a_response_is_stored_with_status_content_type_and_body_only():
    def handler(request):
        return httpx.Response(
            200,
            json={"x": 1},
            headers={"Set-Cookie": "session=secret", "Authorization": "Bearer abc", "X-Token": "t"},
        )

    transport, _, _ = recorder(handler)
    assert (await get(transport, f"{CDN}/Instrument/GetInstrumentInfo/1")).json() == {"x": 1}
    (rec,) = transport.cache.values()
    stored = rec.to_file()
    for secret in ("secret", "Bearer", "set-cookie", "Set-Cookie", "X-Token"):
        assert secret not in stored
    assert set(json.loads(stored)["response"]) == {"status", "content_type", "json"}


async def test_requests_are_sequential_throttled_and_never_repeated():
    transport, fake, seen = recorder(lambda request: httpx.Response(200, json={"n": 1}))
    await get(transport, f"{CDN}/A/1")
    await get(transport, f"{CDN}/A/1")  # same request: answered from the recording, not asked again
    await get(transport, f"{CDN}/A/2")
    await get(transport, "https://search.codal.ir/api/search/v2/q?x=1")
    await get(transport, "https://search.codal.ir/api/search/v2/q?x=2")
    assert len(seen) == 4 and transport.upstream_requests == 4
    assert fake.sleeps == pytest.approx(
        [0.5, 6.0]
    )  # a pause between two cdn requests and between two Codal requests


async def test_a_rate_limited_request_waits_and_asks_again_later():
    answers = iter([429, 429, 200])
    transport, fake, seen = recorder(
        lambda request: httpx.Response(next(answers), json={"ok": True})
    )
    assert (await get(transport, f"{CDN}/A/1")).status_code == 200
    assert len(seen) == 3
    assert fake.sleeps[:2] == [30, 60]  # long waits, growing, before each retry
    assert next(iter(transport.cache.values())).status == 200  # only the final answer is kept


async def test_giving_up_is_reported_and_remembered_for_the_scenario():
    transport, _, seen = recorder(lambda request: httpx.Response(429))
    transport.begin()
    with pytest.raises(rc.RecordingError, match="after 6 tries"):
        await get(transport, f"{CDN}/A/1")
    assert len(seen) == 6 and "A/1" in transport.errors[0]
    assert not transport.cache  # nothing half-recorded


async def test_structural_errors_and_text_bodies_are_recorded_as_they_came():
    def handler(request):
        if request.url.path.endswith("/Fund/GetETFByInsCode/9"):
            return httpx.Response(500, text="")
        return httpx.Response(
            200, text="2026-11-05 00:00:01", headers={"content-type": "text/plain"}
        )

    transport, _, _ = recorder(handler)
    assert (await get(transport, f"{CDN}/Fund/GetETFByInsCode/9")).status_code == 500
    assert (await get(transport, f"{CDN}/StaticData/GetTime")).text == "2026-11-05 00:00:01"
    assert {r.status: r.text for r in transport.cache.values()} == {
        500: "",
        200: "2026-11-05 00:00:01",
    }


async def test_market_feeds_are_cut_to_one_instrument_set_and_the_scenario_sees_the_cut():
    watch = {"marketwatch": [market_row(f"س{i}", 100 + i, 1e9 * (500 - i)) for i in range(120)]}
    clients = {
        "clientTypeAllDto": [
            {"insCode": str(100 + i), "buy_I_Volume": 1.0} for i in range(0, 120, 2)
        ]
        + [{"insCode": "999"}]
    }

    def handler(request):
        return httpx.Response(200, json=watch if "GetMarketWatch" in request.url.path else clients)

    transport, _, seen = recorder(handler)
    flows = (await get(transport, f"{CDN}/ClientType/GetClientTypeAll")).json()["clientTypeAllDto"]
    assert {row["insCode"] for row in flows} <= {
        str(100 + i) for i in range(120)
    }  # 999 is not in the set
    assert len(flows) == 45  # the 90 busiest shares are kept: every second client row of those
    assert sorted(request.url.path.rsplit("/", 1)[1] for request in seen) == [
        "GetClientTypeAll",
        "GetMarketWatch",
    ]  # the full feed, once, to choose the set
    market_rec = (await get(transport, rc.MARKET_WATCH)).json()["marketwatch"]
    assert (
        len(market_rec) == 90 and len(seen) == 2
    )  # served from the copy already fetched, not asked again
    (client_rec,) = [r for r in transport.cache.values() if "ClientType" in r.url]
    assert client_rec.trimmed[0]["of"] == 61 and client_rec.trimmed[0]["kept"] == 45


async def test_a_post_body_is_forwarded_recorded_and_part_of_the_identity():
    def handler(request):
        return httpx.Response(
            200, json={"d": json.dumps([json.loads(request.content)["GregorianFromDate"]])}
        )

    transport, _, seen = recorder(handler)
    day13 = {"Language": 8, "GregorianFromDate": "1405/08/13", "GregorianToDate": "1405/08/13"}
    day12 = {**day13, "GregorianFromDate": "1405/08/12"}
    url = f"{IME}/GetHomeNamaWithDateGrid"
    assert (await post(transport, url, day13)).json() == {"d": '["1405/08/13"]'}
    assert (await post(transport, url, day13)).status_code == 200  # same body: not asked again
    assert (await post(transport, url, day12)).json() == {
        "d": '["1405/08/12"]'
    }  # another body, same URL: asked
    assert len(seen) == 2 and transport.upstream_requests == 2
    assert json.loads(seen[0].content) == day13  # the body reached the server untouched
    assert {r.request_body["GregorianFromDate"] for r in transport.cache.values()} == {
        "1405/08/13",
        "1405/08/12",
    }
    assert len({r.id for r in transport.cache.values()}) == 2
    stored = json.loads(next(iter(transport.cache.values())).to_file())
    assert stored["request"]["body"]["Language"] == 8 and set(stored["request"]) == {
        "method",
        "url",
        "body",
    }


async def test_a_post_with_a_body_that_is_not_json_is_refused():
    transport, _, _ = recorder(lambda request: httpx.Response(200, json={}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(rc.RecordingError, match="not JSON"):
            await client.post(f"{IME}/GetHomeNamaWithDateGrid", content=b"a=1&b=2")
    assert not transport.cache


async def test_a_get_is_recorded_without_a_body_key():
    transport, _, _ = recorder(lambda request: httpx.Response(200, json={"x": 1}))
    await get(transport, f"{CDN}/Instrument/GetInstrumentInfo/1")
    (rec,) = transport.cache.values()
    assert rec.request_body is None and "body" not in json.loads(rec.to_file())["request"]


def test_the_ime_list_keeps_the_biggest_rows_of_every_hall_and_a_few_idle_offers():
    rows = [ime_row("A", 100 + i) for i in range(20)] + [ime_row("B", 5.0 + i) for i in range(20)]
    rows += [ime_row("A", 0.0, quantity=0.0, Price=None, n=i) for i in range(10)]
    inner = json.dumps(rows, ensure_ascii=False)
    body = {"d": inner}
    notes = rc.trim_ime_trades(body, rc.TrimContext(None, NOW))
    kept = json.loads(body["d"])
    assert isinstance(body["d"], str)  # still the ASMX shape: a JSON array inside a string
    traded = [r for r in kept if r["Quantity"] > 0]
    assert len(traded) == 2 * rc.IME_ROWS_PER_HALL
    assert {r["TotalPrice"] for r in traded if r["Talar"] == "A"} == {
        100.0 + i for i in range(8, 20)
    }  # the 12 largest of A
    assert {r["TotalPrice"] for r in traded if r["Talar"] == "B"} == {5.0 + i for i in range(8, 20)}
    idle = [r for r in kept if r["Quantity"] == 0]
    assert [r["n"] for r in idle] == list(
        range(rc.IME_IDLE_OFFERS)
    )  # the first idle offers, every field kept
    assert kept == [r for r in rows if r in kept]  # the exchange's order
    assert (
        notes == [{"path": "d", "kept": len(kept), "of": 50, "rule": notes[0]["rule"]}]
        and "largest" in notes[0]["rule"]
    )
    small = {"d": json.dumps(rows[:3])}
    assert (
        rc.trim_ime_trades(small, rc.TrimContext(None, NOW)) == []
        and json.loads(small["d"]) == rows[:3]
    )
    with pytest.raises(rc.RecordingError, match="JSON string"):
        rc.trim_ime_trades({"d": [1]}, rc.TrimContext(None, NOW))


def test_the_ime_rule_matches_the_service_url_only():
    rule = next(r for r in rc.RULES if "GetAmareMoamelatList" in r.pattern)
    assert rule.matches(httpx.URL(f"{IME}/GetAmareMoamelatList"))
    assert not rule.matches(httpx.URL(f"{IME}/GetHomeNamaWithDateGrid"))


def test_the_electricity_archive_keeps_the_coming_auctions_and_a_few_held_ones():
    rows = [{"auctionIdn": 900 + i, "auctionState": ""} for i in range(8)]
    rows += [{"auctionIdn": 800 + i, "auctionState": "برگزار شده"} for i in range(12)]
    body = {"results": list(rows), "pagedMetaData": [{"totalCount": 9626}]}
    notes = rc.trim_power_announcements(body, rc.TrimContext(None, NOW))
    assert [r["auctionIdn"] for r in body["results"]] == [900 + i for i in range(8)] + [
        800,
        801,
        802,
    ]
    assert (
        notes[0]["kept"] == 11
        and notes[0]["of"] == 20
        and body["pagedMetaData"] == [{"totalCount": 9626}]
    )
    assert rc.trim_power_announcements({"results": rows[:9]}, rc.TrimContext(None, NOW)) == []


async def test_an_untrimmed_giant_is_refused_instead_of_stored():
    transport, _, _ = recorder(
        lambda request: httpx.Response(200, json={"rows": ["x" * 100] * 8000})
    )
    with pytest.raises(rc.RecordingError, match="add a rule to RULES"):
        await get(transport, f"{CDN}/Unknown/Endpoint")
