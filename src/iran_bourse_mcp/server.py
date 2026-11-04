"""FastMCP server: registers every tool, resource and prompt."""

from __future__ import annotations

import functools
import inspect
from typing import Annotated, Any

from pydantic import Field

try:  # MCP Python SDK >= 2
    from mcp.server.mcpserver import MCPServer as FastMCP
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # MCP Python SDK 1.x
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.exceptions import ToolError

from . import __version__
from .client import UpstreamError
from .dates import DateError
from .glossary import lookup
from .resolver import SymbolError
from .service import Bourse, InputError

try:  # ToolAnnotations exists in recent SDKs; degrade gracefully on older ones.
    from mcp.types import ToolAnnotations

    _RO: Any = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
except Exception:  # pragma: no cover
    _RO = None

INSTRUCTIONS = """\
Tehran Stock Exchange (TSETMC / بورس تهران و فرابورس) and Codal data. All tools are read-only.

How to work:
- Symbols are Persian (فولاد، خودرو، وبملت). Persian/Arabic letter variants (ی/ي, ک/ك) are both fine.
- Start with symbol_overview for a stock; use market_watch / top_movers for the whole market.
- To find stocks that satisfy conditions (volume spikes, price patterns over past days, real-money flow, valuation,
  queues), write a filter for screen_stocks instead of paging through market_watch. screener_reference lists fields.
- Prices and values are in RIAL. Dates accept Gregorian (2026-11-03) or Jalali (1405/08/12).
- The market trades Saturday-Wednesday 09:00-12:30 Tehran time. Outside that, data is the last session.
- Anything marked *estimate*/*estimated* is derived by this server, not published by the exchange.
- Big payloads are summarised on purpose (trade_summary, order_book_history). Use trades with filters
  when you really need raw ticks.
- This is information, not investment advice.
"""

if "version" in inspect.signature(FastMCP.__init__).parameters:  # SDK 2.x: shown to clients as serverInfo.version
    mcp = FastMCP("iran-bourse", instructions=INSTRUCTIONS, version=__version__)
else:  # SDK 1.x leaves it empty unless the low-level server is told
    mcp = FastMCP("iran-bourse", instructions=INSTRUCTIONS)
    try:
        mcp._mcp_server.version = __version__
    except AttributeError:  # pragma: no cover
        pass
_service: Bourse | None = None


def svc() -> Bourse:
    global _service
    if _service is None:
        _service = Bourse()
    return _service


_EXPECTED_ERRORS = (SymbolError, InputError, DateError, UpstreamError)


def tool(**kwargs: Any):
    """Register a read-only tool; expected failures reach the agent as readable tool errors.

    MCP SDK 2.x hides arbitrary exception text from clients, so we re-raise ours as ``ToolError``.
    """
    if _RO is not None:
        kwargs.setdefault("annotations", _RO)
    register = mcp.tool(**kwargs)

    def decorator(func: Any) -> Any:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kw: Any) -> Any:
            try:
                return await func(*args, **kw)
            except _EXPECTED_ERRORS as exc:
                raise ToolError(str(exc)) from exc

        register(wrapper)
        return wrapper

    return decorator


Symbol = Annotated[str, Field(description="Persian symbol such as 'فولاد', or an insCode")]
Date = Annotated[str | None, Field(description="Gregorian 2026-11-03 / 20261103 or Jalali 1405/08/12. Omit for the latest trading day.")]
DateBound = Annotated[str | None, Field(description="Range bound: Gregorian 2026-11-03 / 20261103 or Jalali 1405/08/12. Omit for no bound.")]
Market = Annotated[str | None, Field(description="'bourse' or 'fara' (Fara Bourse). Omit for both where applicable.")]

# ----------------------------------------------------------------------------- market


@tool()
async def market_status() -> dict:
    """Is the Tehran market open right now? Tehran time, session hours, bourse state and totals (وضعیت بازار)."""
    return await svc().market_status()


@tool()
async def market_overview(market: Annotated[str, Field(description="'bourse' or 'fara'")] = "bourse") -> dict:
    """Index value, equal-weight index, total value/volume/trades and market cap for the market (نمای کلی بازار)."""
    return await svc().market_overview(market)


@tool()
async def indices(
    market: Annotated[str, Field(description="'bourse' or 'fara'")] = "bourse",
    only_headline: Annotated[bool, Field(description="Skip the ~50 industry indices")] = False,
) -> dict:
    """All indices: total, equal-weight, free-float and every industry index with change % (شاخص‌ها و شاخص صنایع)."""
    return await svc().indices(market, only_headline)


@tool()
async def market_watch(
    market: Market = None,
    security_type: Annotated[str | None, Field(description="Type of instrument: 'stock' (default, سهام), 'fund' (صندوق), 'bond', 'option', 'future', 'rights', 'commodity', 'base' (بازار پایه) or 'all'; a Persian substring such as 'صندوق' works too.")] = "سهام",
    industry: Annotated[str | None, Field(description="Industry name substring, e.g. 'فلزات', 'بانک'")] = None,
    board: Annotated[str | None, Field(description="Board substring, e.g. 'اول', 'دوم', 'پایه'")] = None,
    min_value: Annotated[float, Field(description="Minimum traded value in rial")] = 0,
    only_traded: bool = True,
    sort_by: Annotated[str, Field(description="last_pct, close_pct, value, volume, trades, market_cap, pe, effect_on_index")] = "value",
    descending: bool = True,
    limit: Annotated[int, Field(ge=1, le=700)] = 50,
    detail: Annotated[str, Field(description="'compact' (default) or 'full' (every field incl. best bid/ask, limits, EPS, base volume, NAV)")] = "compact",
) -> dict:
    """Whole-market table (دیده‌بان بازار) of the exchange's own feed: about 3,700 instruments (shares, base market, funds, bonds, options, futures, rights, commodities) on Bourse and Fara Bourse, filtered, sorted and paged in one call. To find instruments by conditions use screen_stocks."""
    return await svc().market_watch(market, security_type, industry, board, min_value, only_traded, sort_by, descending, limit, detail)


@tool()
async def top_movers(
    kind: Annotated[
        str,
        Field(description="gainers, losers, value, volume, trades, buy_queue, sell_queue, real_inflow, real_outflow, real_buyer_power"),
    ] = "gainers",
    market: Market = None,
    security_type: Annotated[str | None, Field(description="'stock' (default, سهام), 'fund', 'option', 'bond', 'all' ...")] = "سهام",
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
) -> dict:
    """Ranked lists: top gainers/losers, most traded, buy/sell queues (صف خرید/فروش, confirmed against each symbol's real order book; about 10 s on a strong day), real-person money inflow/outflow (ورود/خروج پول حقیقی), buyer power."""
    return await svc().top_movers(kind, market, security_type, limit)


@tool()
async def industry_summary(market: Market = None, limit: Annotated[int, Field(ge=1, le=80, description="How many industries to return, largest traded value first")] = 15) -> dict:
    """Per-industry breakdown: traded value, average and cap-weighted change, index effect, queue counts (گروه‌های صنعتی)."""
    return await svc().industry_summary(market, limit)


@tool()
async def index_contributors(limit: Annotated[int, Field(ge=1, le=60)] = 15) -> dict:
    """Stocks pushing the total index up or down the most, in index points (بیشترین تاثیر بر شاخص)."""
    return await svc().index_contributors(limit)


@tool()
async def market_snapshot(
    date: Annotated[str, Field(description="Gregorian or Jalali date of a past trading day")],
    sort_by: Annotated[str, Field(description="value, volume, trades, change_pct")] = "value",
    limit: Annotated[int, Field(ge=1, le=300)] = 30,
    security_type: Annotated[str | None, Field(description="stock, fund or bond")] = None,
) -> dict:
    """End-of-day table for every instrument on a past date (تاریخچه کل بازار در یک روز)."""
    return await svc().market_snapshot(date, sort_by, limit, security_type)


@tool()
async def screen_stocks(
    filter: Annotated[
        str | None,
        Field(
            description="Condition checked for every stock, e.g. \"volume > 2 * avg(volume, 20) and close_pct > 1\". "
            "Today: last close open high low yesterday last_pct close_pct volume value(rial) trades pe eps market_cap bid_volume "
            "ask_volume at_upper_limit buy_queue real_net_value real_buyer_power industry symbol. Past days: close[1] (yesterday), "
            "avg(volume, 20), highest(high, 10), count(close_pct > 0, 5), all(close_pct < 0, 3). Operators: and or not, has(industry, 'بانک'), "
            "5B = 5 billion rial. All fields and functions: screener_reference."
        ),
    ] = None,
    preset: Annotated[str | None, Field(description="Ready-made filter, e.g. volume_surge, smart_money, breakout_20d, buy_queue (screener_reference lists them). ANDed with filter.")] = None,
    market: Market = None,
    security_type: Annotated[str | None, Field(description="Instrument type: 'stock' (default, سهام), 'fund' (صندوق, has nav and nav_premium_pct), 'option', 'future', 'bond', 'rights', 'commodity', 'base' or 'all'")] = "سهام",
    industry: Annotated[str | None, Field(description="Industry name substring, e.g. 'بانک'")] = None,
    columns: Annotated[list[str] | None, Field(description="Expressions to show, optionally 'expr as label'. Default: symbol, last, close_pct, volume, value plus the fields and window values the filter uses.")] = None,
    sort: Annotated[str | None, Field(description="Expression to sort by, e.g. 'volume / avg(volume, 20)'. Default: the preset's, else value.")] = None,
    descending: bool | None = None,
    limit: Annotated[int, Field(ge=1, le=300)] = 30,
    include_untraded: Annotated[bool, Field(description="Also consider symbols with no trades today")] = False,
    adjusted: Annotated[bool, Field(description="Adjust past prices for capital increases and dividends so close[5] is comparable with close")] = True,
) -> dict:
    """Stock screener (فیلتر نویسی): the filter box of tsetmc.com driven by an expression. Returns only the stocks that pass your condition right now, using today's live values plus up to 60 past trading days (close[1], avg(volume, 20), count(close_pct > 0, 3)) and real/legal money flow, in one call with a validated, safe expression (nothing is executed)."""
    return await svc().screen_stocks(filter, preset, market, security_type, industry, columns, sort, descending, limit, include_untraded, adjusted)


@tool()
async def screener_reference(
    topic: Annotated[str, Field(description="overview (default), fields, functions, presets, syntax, examples or all")] = "overview",
) -> dict:
    """Fields, functions, ready-made presets and examples for screen_stocks filters. Call it when a filter is rejected or you need a field name."""
    return await svc().screener_reference(topic)


@tool()
async def market_holder_moves(limit: Annotated[int, Field(ge=1, le=200)] = 30) -> dict:
    """Large holders whose positions changed most over the last 5 reported days, market-wide (تغییرات سهامداران عمده)."""
    return await svc().market_holder_moves(limit)


@tool()
async def supervisor_messages(
    symbol: Annotated[str | None, Field(description="Symbol, or omit for market-wide messages")] = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 10,
    full_text: bool = False,
    market: Annotated[str, Field(description="'bourse' or 'fara' (when no symbol)")] = "bourse",
) -> dict:
    """Exchange supervisor notices (پیام ناظر): trading restrictions, clarifications, halts."""
    return await svc().supervisor_messages(symbol, limit, full_text, market)


# ----------------------------------------------------------------------------- symbol


@tool()
async def search_symbol(query: str, limit: Annotated[int, Field(ge=1, le=50)] = 15) -> dict:
    """Find instruments by symbol or name fragment; returns symbol, name, market, board, insCode (جستجوی نماد)."""
    return await svc().search_symbol(query, limit)


@tool()
async def symbol_overview(symbol: Symbol) -> dict:
    """One-call dossier for a symbol: identity, quote, order book, real/legal flow, top shareholders, latest Codal filings and supervisor notices. Start here."""
    return await svc().symbol_overview(symbol)


@tool()
async def quote(symbol: Symbol) -> dict:
    """Live/last quote with correct change %, volume, value, VWAP, price limits, ranges, P/E and market cap (قیمت لحظه‌ای)."""
    return await svc().quote(symbol)


@tool()
async def order_book(symbol: Symbol) -> dict:
    """Five-level order book (عمق بازار) with order counts, imbalance and buy/sell queue (صف) detection."""
    return await svc().order_book(symbol)


@tool()
async def order_book_history(
    symbol: Symbol,
    date: Date = None,
    from_time: Annotated[str | None, Field(description="HH:MM[:SS] Tehran time")] = None,
    to_time: Annotated[str | None, Field(description="HH:MM[:SS] Tehran time")] = None,
    step_seconds: Annotated[int, Field(ge=5, le=3600, description="Sampling step")] = 300,
) -> dict:
    """Intraday order-book evolution rebuilt from every event: sampled depth plus buy/sell queue episodes with peak sizes (تاریخچه صف خرید و فروش)."""
    return await svc().order_book_history(symbol, date, from_time, to_time, step_seconds)


@tool()
async def trades(
    symbol: Symbol,
    date: Date = None,
    from_time: Annotated[str | None, Field(description="HH:MM[:SS]")] = None,
    to_time: Annotated[str | None, Field(description="HH:MM[:SS]")] = None,
    min_volume: Annotated[int, Field(ge=0, description="Only trades with at least this many shares")] = 0,
    limit: Annotated[int, Field(ge=1, le=5000)] = 200,
    newest_first: bool = False,
) -> dict:
    """Raw tick-by-tick trades (ریز معاملات) with time, price, volume, value. Filter by time and size; prefer trade_summary for analysis."""
    return await svc().trades(symbol, date, from_time, to_time, min_volume, limit, newest_first)


@tool()
async def trade_summary(
    symbol: Symbol,
    date: Date = None,
    from_time: Annotated[str | None, Field(description="HH:MM[:SS]")] = None,
    to_time: Annotated[str | None, Field(description="HH:MM[:SS]")] = None,
    interval_minutes: Annotated[int, Field(ge=1, le=60)] = 5,
) -> dict:
    """Aggregate a day's ticks: intraday bars, VWAP, biggest trades, volume by price level, tick-rule pressure estimate, and a completeness check against official totals."""
    return await svc().trade_summary(symbol, date, from_time, to_time, interval_minutes)


@tool()
async def price_history(
    symbol: Symbol,
    from_date: DateBound = None,
    to_date: DateBound = None,
    limit: Annotated[int, Field(ge=1, le=5000)] = 250,
    adjusted: Annotated[bool, Field(description="Back-adjust for capital increases/dividends (تعدیل شده)")] = False,
) -> dict:
    """Daily OHLCV history since listing, optionally adjusted (تاریخچه قیمت)."""
    return await svc().price_history(symbol, from_date, to_date, limit, adjusted)


@tool()
async def real_legal_flow(
    symbol: Symbol,
    days: Annotated[int, Field(ge=0, le=90, description="How many past trading days of history to add (0 = latest session only)")] = 10,
) -> dict:
    """Real vs legal buying/selling (حقیقی و حقوقی): counts, per-capita, buyer power, net money flow, with daily history."""
    return await svc().real_legal_flow(symbol, days)


@tool()
async def shareholders(symbol: Symbol) -> dict:
    """Major shareholders (سهامداران عمده) with shares, percent and the holder_id for deeper lookups."""
    return await svc().shareholders(symbol)


@tool()
async def shareholder_history(
    symbol: Symbol,
    date: Date = None,
    holder: Annotated[str | None, Field(description="Name fragment (or holder_id) of one major holder, e.g. 'کشوری'. Returns that holder's position over time and the days it changed, instead of snapshots.")] = None,
    days: Annotated[int, Field(ge=5, le=500, description="With holder: how many daily records to read (default 250, about one year)")] = 250,
) -> dict:
    """Dated major-holder snapshots for a symbol with computed changes between snapshots; or, with holder=..., one major holder's position over time and the days it bought or sold (تاریخچه سهامدار عمده)."""
    return await svc().shareholder_history(symbol, date, holder, days)


@tool()
async def shareholder_portfolio(holder_id: Annotated[str, Field(description="holder_id from shareholders")]) -> dict:
    """Everything else that major holder owns across the market (پرتفوی سهامدار)."""
    return await svc().shareholder_portfolio(holder_id)


@tool()
async def corporate_actions(symbol: Symbol) -> dict:
    """Capital increases and price adjustments (افزایش سرمایه، تعدیل قیمت) with dates and factors."""
    return await svc().corporate_actions(symbol)


@tool()
async def symbol_statistics(symbol: Symbol) -> dict:
    """Exchange-computed averages and stats for the symbol (e.g. average traded value over 3 months)."""
    return await svc().symbol_statistics(symbol)


@tool()
async def etf_nav(symbol: Symbol) -> dict:
    """Fund/ETF issue and redemption NAV vs market price: premium/discount (صدور و ابطال)."""
    return await svc().etf_nav(symbol)


# ----------------------------------------------------------------------------- Codal


@tool()
async def codal_filings(
    symbol: Annotated[str | None, Field(description="Symbol, or omit for all companies")] = None,
    from_date: DateBound = None,
    to_date: DateBound = None,
    title_contains: Annotated[str | None, Field(description="Client-side title filter, e.g. 'صورت‌های مالی', 'افزایش سرمایه', 'فعالیت ماهانه'")] = None,
    category: Annotated[int, Field(description="Codal category id, -1 for all")] = -1,
    letter_type: Annotated[int, Field(description="Codal letter type id, -1 for all")] = -1,
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
    page: Annotated[int, Field(ge=1)] = 1,
) -> dict:
    """Search Codal disclosures (کدال): title, publish time, tracing number and links to the page, PDF, Excel and attachments."""
    return await svc().codal_filings(symbol, from_date, to_date, title_contains, category, letter_type, limit, page)


@tool()
async def codal_company(symbol: Symbol) -> dict:
    """Issuer profile from Codal: CEO, ISIC, address, activity description (اطلاعات ناشر)."""
    return await svc().codal_company(symbol)


# ----------------------------------------------------------------------------- misc


@tool()
async def glossary(term: Annotated[str | None, Field(description="Persian or English term; omit to list all")] = None) -> dict:
    """Explain Iranian market terms (صف خرید، سرانه خرید، حقیقی/حقوقی، دامنه نوسان …) so answers use them correctly."""
    return lookup(term)


@mcp.resource("bourse://glossary")
def glossary_resource() -> dict:
    """Full Persian/English market glossary."""
    return lookup(None)


@mcp.prompt()
def analyze_symbol(symbol: str) -> str:
    """Full analyst-style review of one symbol."""
    return (
        f"Analyse the Iranian stock «{symbol}». Call symbol_overview first, then real_legal_flow (days=10), "
        "trade_summary, order_book_history and shareholders as needed. Report: price action and limits, "
        "queue behaviour, real vs legal money flow trend, concentration of ownership, recent Codal filings and "
        "supervisor notices, valuation (P/E vs sector). Quote numbers in Toman where helpful (1 Toman = 10 Rial) "
        "and state which numbers are estimates. Finish with risks; this is not investment advice."
    )


@mcp.prompt()
def daily_market_report() -> str:
    """End-of-day market report."""
    return (
        "Write today's Tehran market report. Use market_status, market_overview, indices, industry_summary, "
        "top_movers (gainers, losers, buy_queue, sell_queue, real_inflow, real_outflow) and index_contributors. "
        "Cover index level and breadth, strongest and weakest industries, queue pressure, where real-person "
        "money moved, and the symbols driving the index. Be concise and numeric."
    )


@mcp.prompt()
def find_stocks(criteria: str) -> str:
    """Turn a plain-language description into a screen_stocks filter, run it and verify the hits."""
    return (
        f"Find Iranian stocks matching: {criteria}\n"
        "Translate it into a screen_stocks filter (call screener_reference if unsure of a field name; prices are in rial, "
        "'5B' means five billion rial; yesterday is close[1]; averages use avg(field, days)). Prefer a preset when one fits. "
        "State the exact filter you used, run it, then check the top 3-5 hits with symbol_overview or real_legal_flow before "
        "reporting. If nothing matches, relax the thresholds one by one and say which one mattered. Not investment advice."
    )


@mcp.prompt()
def smart_money_scan() -> str:
    """Find symbols where real-person buying power and money inflow stand out."""
    return (
        "Scan for accumulation: call top_movers with kind=real_buyer_power and kind=real_inflow, then for the top "
        "5 symbols call real_legal_flow (days=10) and trade_summary. Flag symbols where real inflow persists for "
        "several days with buyer power above 1 and volume above its average, and say why they might be false "
        "positives (block deals, queue effects). Not investment advice."
    )


def main(transport: str = "stdio") -> None:  # pragma: no cover - thin wrapper
    mcp.run(transport=transport)  # type: ignore[arg-type]


__all__ = ["mcp", "main", "__version__"]
