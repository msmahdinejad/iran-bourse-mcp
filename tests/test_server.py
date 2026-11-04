"""The MCP surface: every tool is registered, described and read-only."""

from __future__ import annotations

import pytest

from iran_bourse_mcp.glossary import lookup
from iran_bourse_mcp.server import mcp

EXPECTED = {
    "market_status", "market_overview", "indices", "market_watch", "top_movers", "industry_summary",
    "index_contributors", "market_snapshot", "market_holder_moves", "supervisor_messages", "search_symbol",
    "symbol_overview", "quote", "order_book", "order_book_history", "trades", "trade_summary",
    "price_history", "real_legal_flow", "shareholders", "shareholder_history", "shareholder_portfolio",
    "corporate_actions", "symbol_statistics", "etf_nav", "codal_filings", "codal_company", "glossary",
    "screen_stocks", "screener_reference", "option_chain", "futures_market",
}


@pytest.fixture()
async def tools():
    return await mcp.list_tools()


async def test_all_tools_registered(tools):
    assert {t.name for t in tools} == EXPECTED


async def test_every_tool_is_documented_and_read_only(tools):
    for t in tools:
        assert t.description and len(t.description) > 30, t.name
        annotations = getattr(t, "annotations", None)
        if annotations is not None:  # attribute names differ between SDK 1.x (camelCase) and 2.x (snake_case)
            read_only = getattr(annotations, "readOnlyHint", getattr(annotations, "read_only_hint", None))
            destructive = getattr(annotations, "destructiveHint", getattr(annotations, "destructive_hint", None))
            assert read_only is True, t.name
            assert destructive is False, t.name


async def test_symbol_parameters_are_described(tools):
    quote = next(t for t in tools if t.name == "quote")
    schema = getattr(quote, "inputSchema", None) or quote.input_schema
    assert "description" in schema["properties"]["symbol"]


def test_glossary_lookup():
    assert "صف خرید" in lookup("صف خرید")["matches"]
    assert lookup("buy queue")["matches"]
    assert lookup("zzz")["matches"] is None
    assert len(lookup(None)["terms"]) >= 15
