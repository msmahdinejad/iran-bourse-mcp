"""Call every tool once against the live servers and print a short report.

    uv run python scripts/smoke_live.py [SYMBOL] [--full]

Needs a connection that can reach TSETMC/Codal (see README). Exit code is non-zero on any failure.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

from iran_bourse_mcp.dates import previous_trading_day, tehran_now
from iran_bourse_mcp.service import Bourse


async def main(symbol: str, full: bool) -> int:
    b = Bourse()
    q = await b.quote(symbol)
    last_day = q["date"]
    calls = [
        ("market_status", b.market_status()),
        ("market_overview", b.market_overview("bourse")),
        ("market_overview fara", b.market_overview("fara")),
        ("indices", b.indices("bourse")),
        ("market_watch", b.market_watch(limit=5)),
        ("market_watch full fara", b.market_watch(market="fara", limit=2, detail="full")),
        ("top_movers gainers", b.top_movers("gainers", limit=5)),
        ("top_movers buy_queue", b.top_movers("buy_queue", limit=5)),
        ("top_movers buy_queue past fara", b.top_movers("buy_queue", market="fara", limit=5, date=str(previous_trading_day(tehran_now().date())))),
        ("top_movers real_inflow", b.top_movers("real_inflow", limit=5)),
        ("top_movers real_buyer_power", b.top_movers("real_buyer_power", limit=5)),
        ("industry_summary", b.industry_summary()),
        ("index_contributors", b.index_contributors(5)),
        ("market_snapshot", b.market_snapshot(last_day, limit=3)),
        ("market_holder_moves", b.market_holder_moves(5)),
        ("supervisor_messages market", b.supervisor_messages(None, 3)),
        ("search_symbol", b.search_symbol(symbol, 3)),
        ("symbol_overview", b.symbol_overview(symbol)),
        ("quote", b.quote(symbol)),
        ("order_book", b.order_book(symbol)),
        ("order_book_history", b.order_book_history(symbol, step_seconds=1800)),
        ("trades", b.trades(symbol, limit=3)),
        ("trades history", b.trades(symbol, date=last_day, min_volume=1_000_000, limit=3)),
        ("trade_summary", b.trade_summary(symbol)),
        ("price_history", b.price_history(symbol, limit=3)),
        ("price_history adjusted", b.price_history(symbol, limit=3, adjusted=True)),
        ("technical_indicators", b.technical_indicators(symbol, days=3)),
        ("real_legal_flow", b.real_legal_flow(symbol, 5)),
        ("shareholders", b.shareholders(symbol)),
        ("shareholder_history", b.shareholder_history(symbol)),
        ("corporate_actions", b.corporate_actions(symbol)),
        ("symbol_statistics", b.symbol_statistics(symbol)),
        ("supervisor_messages symbol", b.supervisor_messages(symbol, 2)),
        ("etf_nav (fund)", b.etf_nav("اهرم")),
        ("etf_nav (stock)", b.etf_nav(symbol)),
        ("codal_filings", b.codal_filings(symbol, limit=3)),
        ("codal_filings range", b.codal_filings(symbol, from_date="1405/01/01", title_contains="صورت", limit=3)),
        ("codal_company", b.codal_company(symbol)),
    ]
    holders = await b.shareholders(symbol)
    calls.append(("shareholder_portfolio", b.shareholder_portfolio(holders["holders"][0]["holder_id"])))

    failures = 0
    for name, coro in calls:
        started = time.perf_counter()
        try:
            result = await coro
            text = json.dumps(result, ensure_ascii=False)
            print(f"OK   {name:32} {time.perf_counter() - started:5.1f}s {len(text):>8} chars")
            if full:
                print("     " + text[:1500])
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {name:32} {type(exc).__name__}: {exc}")
    await b.aclose()
    print(f"\n{len(calls) - failures}/{len(calls)} ok")
    return 1 if failures else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.exit(asyncio.run(main(args[0] if args else "فولاد", "--full" in sys.argv)))
