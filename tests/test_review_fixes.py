"""Regression tests for the findings of the independent QA review against v0.2.0."""

from __future__ import annotations

import asyncio

import pytest
from conftest import load
from test_service_market import MarketApi

from iran_bourse_mcp import market as M
from iran_bourse_mcp import server, shape
from iran_bourse_mcp.client import UpstreamError
from iran_bourse_mcp.service import Bourse


class PagedCodal(MarketApi):
    """Eight filings per page over five pages; only page 4 holds a capital-increase title."""

    def __init__(self):
        self.pages_asked: list[int] = []

    async def codal_search(self, **params):
        page = int(params["PageNumber"])
        self.pages_asked.append(page)
        template = load("codal_letters")["Letters"][0]
        letters = [dict(template, TracingNo=page * 100 + i, Title="افزایش سرمایه از محل سود" if page == 4 and i == 2 else f"صورت مالی {page}-{i}") for i in range(8)]
        return {"Total": 40, "Page": 5, "Letters": letters}


def bourse_with(api):
    b = Bourse()
    b.api = api
    b.resolver._api = api
    return b


async def test_codal_title_filter_reads_further_pages_until_it_finds_matches():
    api = PagedCodal()
    out = await bourse_with(api).codal_filings(None, title_contains="افزایش سرمایه", limit=1)
    assert api.pages_asked == [1, 2, 3, 4]  # stopped on page 4, where the match is: not just the first page
    assert out["returned"] == 1 and out["filings"][0]["title"].startswith("افزایش سرمایه")
    assert out["title_filter"] == {"scanned_filings": 32, "scanned_pages": 4, "next_page": 5}
    assert out["total_before_title_filter"] == 40 and "total_matches" not in out  # the unfiltered total is not a match count


async def test_codal_title_filter_stops_at_the_last_page_and_reports_it():
    api = PagedCodal()
    out = await bourse_with(api).codal_filings(None, title_contains="نامعتبر", limit=5)
    assert api.pages_asked == [1, 2, 3, 4, 5] and out["returned"] == 0 and out["title_filter"]["next_page"] is None


async def test_codal_without_a_title_filter_is_a_single_page_as_before():
    api = PagedCodal()
    out = await bourse_with(api).codal_filings(None, limit=3)
    assert api.pages_asked == [1] and out["total_matches"] == 40 and out["returned"] == 3 and "title_filter" not in out


async def test_persian_digits_in_a_symbol_are_searched_as_ascii():
    asked = []

    class Api(MarketApi):
        async def search(self, query):
            asked.append(query)
            return load("search_folad")

    await bourse_with(Api()).search_symbol("فولاد۲")
    assert asked == ["فولاد2"]


class TodayNotPublished(MarketApi):
    """The daily table already lists today, but the per-day client-type history is not available for it yet."""

    async def daily_prices(self, ins):
        return [{"dEven": d, "pClosing": 100.0, "zTotTran": 5.0, "qTotTran5J": 10.0} for d in (20261101, 20261102, 20261103, 20261104)]

    async def client_type_history(self, ins, deven, ttl=0):
        if deven == 20261104:
            raise UpstreamError("HTTP 500")
        return await super().client_type_history(ins, deven, ttl)


async def test_real_legal_flow_returns_the_requested_number_of_days():
    out = await bourse_with(TodayNotPublished()).real_legal_flow("فولاد", days=2)
    assert [r["date"] for r in out["history"]] == ["2026-11-02", "2026-11-03"] and out["history_summary"]["days"] == 2


def test_loss_makers_have_no_pe_in_either_feed():
    assert M.shape_market_row({"pe": "-3.2", "lva": "x"})["pe"] is None and M.shape_market_row({"pe": None, "lva": "x"})["pe"] is None
    assert M.shape_market_row({"pe": "4.5", "lva": "x"})["pe"] == 4.5
    assert shape.shape_watch_row({"pe": {"value": -2.0}})["pe"] is None and shape.shape_watch_row({"pe": {"value": 6.19}})["pe"] == 6.19


def test_order_book_levels_beyond_the_limits_are_flagged():
    rows = [{"number": 1, "pMeDem": 1434, "qTitMeDem": 10, "zOrdMeDem": 1, "pMeOf": 1440, "qTitMeOf": 20, "zOrdMeOf": 2}]
    book = shape.shape_order_book(rows, 1434.0, 1300.0)
    assert book["asks"][0]["outside_price_limits"] is True and "outside_price_limits" not in book["bids"][0]
    assert "next session" in book["note"]
    assert "note" not in shape.shape_order_book([dict(rows[0], pMeOf=1434)], 1434.0, 1300.0)


async def test_gainers_are_ranked_by_closing_change_with_value_breaking_ties():
    b = bourse_with(MarketApi())
    out = await b.top_movers("gainers", limit=3)
    closes = [r["close_pct"] for r in out["rows"]]
    assert closes == sorted(closes, reverse=True)


async def test_a_slow_optional_section_does_not_stall_the_dossier(monkeypatch):
    class Slow(MarketApi):
        async def codal_search(self, **params):
            await asyncio.sleep(5)

    monkeypatch.setattr("iran_bourse_mcp.service.SECTION_TIMEOUT", 0.05)
    out = await bourse_with(Slow()).symbol_overview("فولاد")
    assert "recent_filings" in out["unavailable_sections"] and "quote" in out


async def test_industry_summary_adds_estimated_real_money_flow():
    out = await bourse_with(MarketApi()).industry_summary()
    metals = next(i for i in out["industries"] if i["industry"].startswith("فلزات"))
    assert metals["real_net_value_estimated"] is not None and isinstance(metals["real_net_value_estimated"], int)


async def test_market_snapshot_rejects_an_unknown_security_type_with_the_valid_words():
    from iran_bourse_mcp.service import InputError

    with pytest.raises(InputError, match="stock, fund, bond"):
        await bourse_with(MarketApi()).market_snapshot("2026-11-04", security_type="crypto")


def test_snapshot_types_come_from_instrument_id_prefixes():
    assert [M.type_from_instrument_id(i) for i in ("IRO1FOLD0001", "IRO9AHRM0F01", "IRT1TRNF0001", "IRB3MSHD0721", "IRO7XXXX0001", "IRR1AAAA0001", "zzz")] == [
        "سهام", "اختیار معامله", "صندوق سرمایه گذاری", "اوراق بدهی", "بازار پایه فرابورس", "حق تقدم", "سایر"]
    with pytest.raises(ValueError, match="not recognised"):
        M.check_security_type("crypto")
    M.check_security_type("ETF")
    M.check_security_type("سهام عادی")


def test_server_reports_its_version():
    version = getattr(server.mcp, "version", None) or getattr(getattr(server.mcp, "_mcp_server", None), "version", None)
    assert version == server.__version__
