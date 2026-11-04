"""The replay engine itself: matching, loud failures, the frozen clock and the SDK-neutral tool call."""

from __future__ import annotations

import datetime as dt
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
