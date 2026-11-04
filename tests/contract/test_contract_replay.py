"""The replay engine itself: matching, loud failures, the frozen clock and the SDK-neutral tool call."""

from __future__ import annotations

import datetime as dt
import json
import sys
from types import SimpleNamespace
from urllib.parse import quote

import httpx
import pytest
from contract_replay import (
    Recorded,
    Recordings,
    Replay,
    Scenario,
    UnmatchedRequest,
    frozen_clock,
    load_recorded,
    replay_scenario,
    request_id,
    request_key,
    save_manifest,
    save_recorded,
    unwrap,
)

from iran_bourse_mcp import dates

SEARCH = "https://cdn.tsetmc.com/api/Instrument/GetInstrumentSearch/" + quote("فولاد")
WATCH = "https://cdn.tsetmc.com/api/ClosingPrice/GetMarketWatch?market=0&industrialGroup=&showTraded=false"
IME = "https://www.ime.co.ir/SubSystems/IME/Services/Home/imedata.asmx/GetHomeNamaWithDateGrid"


def recorded(url: str, body: object = None, status: int = 200) -> Recorded:
    return Recorded(
        "GET",
        url,
        status,
        "application/json; charset=utf-8",
        body if body is not None else {"ok": 1},
    )


async def fetch(replay: Replay, url: str) -> httpx.Response:
    async with httpx.AsyncClient(transport=replay.transport) as client:
        return await client.get(url)


def test_request_key_ignores_query_order_and_keeps_blank_values():
    a = request_key("get", WATCH)
    b = request_key(
        "GET",
        "https://cdn.tsetmc.com/api/ClosingPrice/GetMarketWatch?showTraded=false&market=0&industrialGroup=",
    )
    assert a == b and "industrialGroup=" in a
    assert request_key("GET", SEARCH).endswith(
        "GetInstrumentSearch/فولاد"
    )  # readable, not percent-encoded
    assert request_key("GET", WATCH) != request_key("GET", WATCH + "&x=1")
    assert request_id("GET", SEARCH) != request_id("GET", SEARCH + "?a=1")
    assert request_id("GET", SEARCH).startswith("cdn__api_Instrument_GetInstrumentSearch-")


async def test_replay_serves_the_recording_and_reports_the_unused_one():
    replay = Replay([recorded(SEARCH, {"hit": True}), recorded(WATCH)])
    response = await fetch(replay, SEARCH)
    assert response.status_code == 200 and response.json() == {"hit": True}
    assert response.headers["content-type"].startswith("application/json")
    assert replay.unused() == [WATCH]
    assert not replay.unmatched


async def test_replay_serves_text_and_error_statuses_as_recorded():
    text = Recorded(
        "GET",
        "https://cdn.tsetmc.com/api/StaticData/GetTime",
        200,
        "text/plain",
        text="2026-11-05 00:00:01",
    )
    broken = recorded("https://cdn.tsetmc.com/api/Fund/GetETFByInsCode/1", status=500)
    replay = Replay([text, broken])
    assert (await fetch(replay, text.url)).text == "2026-11-05 00:00:01"
    assert (await fetch(replay, broken.url)).status_code == 500


async def test_unmatched_request_fails_loudly_and_names_the_url():
    replay = Replay([recorded(SEARCH)])
    with pytest.raises(UnmatchedRequest, match="GetInstrumentInfo/123"):
        await fetch(replay, "https://cdn.tsetmc.com/api/Instrument/GetInstrumentInfo/123")
    assert replay.unmatched == ["GET https://cdn.tsetmc.com/api/Instrument/GetInstrumentInfo/123"]


async def test_a_recording_matches_its_exact_query_and_nothing_wider():
    replay = Replay([recorded(SEARCH), recorded(WATCH)])
    for url in (
        SEARCH + "?extra=1",
        WATCH + "&hEven=0",
        "https://cdn.tsetmc.com/api/ClosingPrice/GetMarketWatch",
    ):
        with pytest.raises(UnmatchedRequest):
            await fetch(replay, url)
    assert (
        await fetch(
            replay,
            "https://cdn.tsetmc.com/api/ClosingPrice/GetMarketWatch?industrialGroup=&showTraded=false&market=0",
        )
    ).status_code == 200


async def test_other_host_or_method_is_not_matched():
    replay = Replay([recorded(SEARCH)])
    with pytest.raises(UnmatchedRequest):
        await fetch(replay, SEARCH.replace("cdn.tsetmc.com", "webgw.tse.ir"))
    async with httpx.AsyncClient(transport=replay.transport) as client:
        with pytest.raises(UnmatchedRequest):
            await client.post(SEARCH)


def post_recorded(body: object, payload: object = None) -> Recorded:
    return Recorded(
        "POST",
        IME,
        200,
        "application/json; charset=utf-8",
        payload if payload is not None else {"d": "[]"},
        request_body=body,
    )


def test_a_request_body_is_part_of_the_identity_and_a_request_without_one_is_unchanged():
    a = {"Language": 8, "GregorianFromDate": "1405/08/13", "GregorianToDate": "1405/08/13"}
    shuffled = dict(reversed(list(a.items())))
    assert request_key("POST", IME, a) == request_key(
        "post", IME, shuffled
    )  # key order is irrelevant
    assert request_key("POST", IME, a) != request_key(
        "POST", IME, {**a, "GregorianToDate": "1405/08/14"}
    )
    assert request_key("POST", IME, a) != request_key("POST", IME)
    assert request_id("POST", IME, a) == request_id("POST", IME, shuffled)
    assert request_id("POST", IME, a) != request_id("POST", IME, {**a, "Language": 9})
    # a request without a body keeps the key and the file name it had before bodies were recorded
    assert request_key("GET", SEARCH, None) == request_key("GET", SEARCH)
    assert request_key("GET", WATCH) == (
        "GET https://cdn.tsetmc.com/api/ClosingPrice/GetMarketWatch?industrialGroup=&market=0&showTraded=false"
    )
    assert request_id("GET", SEARCH) == request_id("GET", SEARCH, None)
    assert request_id("POST", IME, a).startswith(
        "ime__imedata_asmx_GetHomeNamaWithDateGrid-"
    )  # the service name survives


def test_a_recording_with_a_body_round_trips_and_a_legacy_file_has_none(tmp_path):
    body = {"Language": 8, "fari": False, "GregorianFromDate": "1405/08/13"}
    rec = post_recorded(body)
    stored = json.loads(rec.to_file())
    assert stored["request"] == {"method": "POST", "url": IME, "body": body}
    save_recorded(rec, tmp_path)
    assert (
        load_recorded(rec.id, tmp_path).request_body == body
        and load_recorded(rec.id, tmp_path).id == rec.id
    )
    plain = json.loads(recorded(SEARCH).to_file())
    assert plain["request"] == {"method": "GET", "url": SEARCH}  # no "body" key when there is none
    assert Recorded.from_file(json.dumps(plain)).request_body is None
    assert rec.describe() == IME + ' {"GregorianFromDate":"1405/08/13","Language":8,"fari":false}'
    assert recorded(SEARCH).describe() == SEARCH


async def test_replay_tells_apart_requests_that_differ_only_in_their_body():
    one_day = {"Language": 8, "GregorianFromDate": "1405/08/13", "GregorianToDate": "1405/08/13"}
    two_days = {**one_day, "GregorianFromDate": "1405/08/12"}
    replay = Replay([post_recorded(one_day, {"d": "one"}), post_recorded(two_days, {"d": "two"})])
    async with httpx.AsyncClient(transport=replay.transport) as client:
        assert (await client.post(IME, json=dict(reversed(list(two_days.items()))))).json() == {
            "d": "two"
        }
        assert (await client.post(IME, json=one_day)).json() == {"d": "one"}
        with pytest.raises(
            UnmatchedRequest, match="1405/08/11"
        ):  # the body is named, so the missing recording is easy to find
            await client.post(IME, json={**one_day, "GregorianFromDate": "1405/08/11"})
        with pytest.raises(UnmatchedRequest):
            await client.post(IME)  # no body
        with pytest.raises(UnmatchedRequest):
            await client.get(IME)  # a GET does not match a POST recording
    assert replay.unused() == []
    assert "1405/08/11" in replay.unmatched[0] and replay.unmatched[0].startswith(f"POST {IME} ")


async def test_a_recording_with_a_body_that_was_never_sent_is_reported_stale_with_its_body():
    sent = {"Language": 8, "GregorianFromDate": "1405/08/13"}
    never = {"Language": 8, "GregorianFromDate": "1405/08/12"}
    replay = Replay([post_recorded(sent), post_recorded(never)])
    async with httpx.AsyncClient(transport=replay.transport) as client:
        assert (await client.post(IME, json=sent)).status_code == 200
    assert (
        replay.unused() == [post_recorded(never).describe()] and "1405/08/12" in replay.unused()[0]
    )


def test_recordings_lookup_by_url_or_body_fragment():
    items = Recordings(
        [post_recorded({"Language": 8, "MainCat": 1}), post_recorded({"Language": 8, "MainCat": 3})]
    )
    assert len(items.find("GetHomeNamaWithDateGrid")) == 2
    assert items.get('"MainCat":3').request_body == {"Language": 8, "MainCat": 3}
    with pytest.raises(AssertionError, match="found 2"):
        items.get("Language")


def test_recordings_lookup_by_url_fragment():
    items = Recordings([recorded(SEARCH), recorded(WATCH), recorded(WATCH + "&x=1")])
    assert items.get("GetInstrumentSearch").url == SEARCH
    assert items.body("GetInstrumentSearch") == {"ok": 1}
    with pytest.raises(AssertionError, match="found 2"):
        items.get("GetMarketWatch")
    with pytest.raises(AssertionError, match="found 0"):
        items.get("Nope")


def test_the_frozen_clock_reaches_every_module_that_imported_tehran_now_and_is_undone():
    from iran_bourse_mcp import calendar_events, service

    importers = [
        m
        for name, m in sys.modules.items()
        if name.startswith("iran_bourse_mcp") and hasattr(m, "tehran_now")
    ]
    assert {dates, service, calendar_events} <= set(importers)
    real = dates.tehran_now
    pinned = dt.datetime(2026, 11, 5, 9, 30, 0)
    with frozen_clock(pinned):
        assert all(m.tehran_now() == pinned for m in importers)
        assert dates.tehran_now(dt.datetime(2026, 1, 1, 0, 0)) == dt.datetime(
            2026, 1, 1, 3, 30
        )  # an explicit instant still converts
    assert all(m.tehran_now is real for m in importers)


def test_unwrap_reads_the_json_of_both_sdk_generations():
    payload = '{"a": [1, 2], "b": "فولاد"}'
    block = SimpleNamespace(type="text", text=payload)
    assert unwrap([block]) == {"a": [1, 2], "b": "فولاد"}  # SDK 1.x: content blocks
    assert unwrap(([block], {"ignored": True})) == {
        "a": [1, 2],
        "b": "فولاد",
    }  # 1.x with structured output
    assert unwrap({"a": 1}) == {"a": 1}  # 1.x structured dict
    assert unwrap(SimpleNamespace(content=[block], structured_content=None)) == {
        "a": [1, 2],
        "b": "فولاد",
    }  # SDK 2.x
    assert unwrap(SimpleNamespace(content=[], structuredContent={"a": 1})) == {"a": 1}
    with pytest.raises(AssertionError):
        unwrap(SimpleNamespace(content=[]))


async def test_a_scenario_whose_tool_asks_for_an_unrecorded_url_fails_naming_it(tmp_path):
    hit = {
        "instrumentSearch": [
            {"insCode": "1", "lVal18AFC": "فولاد", "lVal30": "فولاد مبارکه", "flow": 1}
        ]
    }
    save_recorded(recorded(SEARCH, hit), tmp_path / "requests")
    save_manifest(
        "quote_demo",
        "quote",
        dt.datetime(2026, 11, 5, 9, 30),
        [request_id("GET", SEARCH)],
        tmp_path / "scenarios",
    )
    sc = Scenario("quote_demo", "quote", {"symbol": "فولاد"}, lambda run: None)
    with pytest.raises(UnmatchedRequest, match="GetInstrumentInfo/1"):
        await replay_scenario(sc, tmp_path)


async def test_a_scenario_without_a_recording_says_how_to_record_it(tmp_path):
    with pytest.raises(FileNotFoundError, match="record_contract.py --record --only nothing_here"):
        await replay_scenario(Scenario("nothing_here", "glossary", {}, lambda run: None), tmp_path)
