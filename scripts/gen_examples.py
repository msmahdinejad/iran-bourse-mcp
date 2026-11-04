"""Write docs/EXAMPLES.md: one real, trimmed response per tool, captured live.

    uv run python scripts/gen_examples.py       (needs access to TSETMC; best run after the market closes)
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from iran_bourse_mcp.service import Bourse

OUT = Path(__file__).resolve().parent.parent / "docs" / "EXAMPLES.md"
MAX_LINES = 46


def trim(obj: object) -> str:
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES] + [f"  … ({len(lines) - MAX_LINES} more lines)"]
    return "\n".join(lines)


async def main() -> None:
    b = Bourse()
    quote = await b.quote("فولاد")
    day = quote["date"]
    prices = await b.price_history("فولاد", limit=3)
    prev = prices["rows"][-2]["date"]
    holders = await b.shareholders("فولاد")
    cases = [
        ("Market", "market_status", "market_status()", b.market_status()),
        ("Market", "market_overview", 'market_overview(market="bourse")', b.market_overview("bourse")),
        ("Market", "indices", 'indices(market="bourse", only_headline=True)', b.indices("bourse", True)),
        ("Market", "market_watch", 'market_watch(sort_by="value", limit=3)', b.market_watch(limit=3)),
        ("Market", "top_movers", 'top_movers(kind="buy_queue", limit=3)', b.top_movers("buy_queue", limit=3)),
        ("Market", "industry_summary", "industry_summary()", b.industry_summary()),
        ("Market", "index_contributors", "index_contributors(limit=3)", b.index_contributors(3)),
        ("Market", "market_snapshot", f'market_snapshot(date="{prev}", limit=3)', b.market_snapshot(prev, limit=3)),
        ("Market", "market_holder_moves", "market_holder_moves(limit=3)", b.market_holder_moves(3)),
        ("Market", "supervisor_messages", "supervisor_messages(limit=2)", b.supervisor_messages(None, 2)),
        ("Screener", "screen_stocks", 'screen_stocks(filter="volume > 2 * avg(volume, 20) and close_pct[1] > 1 and close_pct > 0 and value > 5B", limit=3)',
         b.screen_stocks("volume > 2 * avg(volume, 20) and close_pct[1] > 1 and close_pct > 0 and value > 5B", limit=3)),
        ("Screener", "screen_stocks", 'screen_stocks(preset="smart_money", limit=3)', b.screen_stocks(preset="smart_money", limit=3)),
        ("Screener", "screener_reference", 'screener_reference(topic="presets")', b.screener_reference("presets")),
        ("Indices and funds", "index_history", 'index_history(index="شاخص کل", from_date="1405/07/01", limit=5)', b.index_history("شاخص کل", "1405/07/01", None, 5)),
        ("Indices and funds", "index_constituents", 'index_constituents(index="فلزات", limit=3)', b.index_constituents("فلزات", "effect", True, 3)),
        ("Indices and funds", "fund_ranking", 'fund_ranking(fund_type="equity", sort_by="return_1m", min_net_assets=1e13, limit=2)', b.fund_ranking("equity", "return_1m", True, 1e13, 2)),
        ("Derivatives", "option_chain", 'option_chain(underlying="اهرم", limit=4)', b.option_chain("اهرم", limit=4)),
        ("Derivatives", "futures_market", 'futures_market(underlying="اهرم")', b.futures_market("اهرم")),
        ("Lists, calendar and status", "top_lists", 'top_lists(list_name="block_trades", limit=3)', b.top_lists("block_trades", None, 3)),
        ("Lists, calendar and status", "capital_calendar", 'capital_calendar(direction="upcoming", days=30, limit=3)', b.capital_calendar(1, "upcoming", 30, 3)),
        ("Lists, calendar and status", "trading_status", 'trading_status(kind="suspended", limit=3)', b.trading_status("suspended", None, None, 3)),
        ("Symbol", "search_symbol", 'search_symbol(query="فولاد", limit=3)', b.search_symbol("فولاد", 3)),
        ("Symbol", "symbol_overview", 'symbol_overview(symbol="فولاد")', b.symbol_overview("فولاد")),
        ("Symbol", "quote", 'quote(symbol="فولاد")', b.quote("فولاد")),
        ("Symbol", "order_book", 'order_book(symbol="فولاد")', b.order_book("فولاد")),
        ("Symbol", "order_book_history", f'order_book_history(symbol="فولاد", date="{prev}", step_seconds=3600)', b.order_book_history("فولاد", prev, step_seconds=3600)),
        ("Symbol", "trades", f'trades(symbol="فولاد", date="{prev}", min_volume=250000, limit=3)', b.trades("فولاد", prev, min_volume=250_000, limit=3)),
        ("Symbol", "trade_summary", f'trade_summary(symbol="فولاد", date="{prev}", interval_minutes=30)', b.trade_summary("فولاد", prev, interval_minutes=30)),
        ("Symbol", "price_history", 'price_history(symbol="فولاد", limit=3, adjusted=True)', b.price_history("فولاد", limit=3, adjusted=True)),
        ("Symbol", "price_history", 'price_history(symbol="فولاد", granularity="monthly", limit=3)', b.price_history("فولاد", limit=3, adjusted=True, granularity="monthly")),
        ("Symbol", "real_legal_flow", 'real_legal_flow(symbol="فولاد", days=3)', b.real_legal_flow("فولاد", 3)),
        ("Symbol", "shareholders", 'shareholders(symbol="فولاد")', b.shareholders("فولاد")),
        ("Symbol", "shareholder_history", 'shareholder_history(symbol="فولاد")', b.shareholder_history("فولاد")),
        ("Symbol", "shareholder_history", 'shareholder_history(symbol="فولاد", holder="بازنشستگی", days=120)', b.shareholder_history("فولاد", holder="بازنشستگی", days=120)),
        ("Symbol", "shareholder_portfolio", f'shareholder_portfolio(holder_id="{holders["holders"][0]["holder_id"]}")', b.shareholder_portfolio(holders["holders"][0]["holder_id"])),
        ("Symbol", "corporate_actions", 'corporate_actions(symbol="فولاد")', b.corporate_actions("فولاد")),
        ("Symbol", "symbol_statistics", 'symbol_statistics(symbol="فولاد")', b.symbol_statistics("فولاد")),
        ("Symbol", "etf_nav", 'etf_nav(symbol="اهرم")', b.etf_nav("اهرم")),
        ("Codal", "codal_filings", 'codal_filings(symbol="فولاد", limit=2)', b.codal_filings("فولاد", limit=2)),
        ("Codal", "codal_company", 'codal_company(symbol="فولاد")', b.codal_company("فولاد")),
    ]
    out = [
        "# Real examples",
        "",
        f"_Captured live on {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}. Long responses are trimmed to {MAX_LINES} lines. "
        f"Latest session in these samples: {day}. Prices and values are in Rial._",
        "",
        "Every response is plain JSON. Keys named `estimate`/`estimated` are derived by the server; everything else is exchange data. "
        "Parameter details are in [TOOLS.md](TOOLS.md).",
        "",
    ]
    group = ""
    for grp, name, call, coro in cases:
        if grp != group:
            out += [f"## {grp}", ""]
            group = grp
        result = await coro
        out += [f"### `{name}`", "", f"```python\n{call}\n```", "", "```json", trim(result), "```", ""]
        print("ok", name)
    out += ["## Help", "", "### `glossary`", "", "```python\nglossary(term=\"صف خرید\")\n```", "", "```json",
            trim(__import__("iran_bourse_mcp.glossary", fromlist=["lookup"]).lookup("صف خرید")), "```", ""]
    await b.aclose()
    OUT.write_text("\n".join(out), encoding="utf-8")
    print("wrote", OUT, f"({len(out)} blocks)")


if __name__ == "__main__":
    asyncio.run(main())
