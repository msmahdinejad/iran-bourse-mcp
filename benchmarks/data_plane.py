"""Data-plane benchmark: what a model must read and wait for, with and without iran-bourse-mcp.

For each task we measure the *raw route* (the fewest raw TSETMC/Codal HTTP requests that contain
the answer, i.e. the best case for an agent that already knows the hidden endpoints) against one
MCP tool call. We record requests, wall-clock time, payload bytes and estimated tokens, and we
check a set of "traps" that make naive readings of the raw JSON wrong.

    uv run python benchmarks/data_plane.py [--out benchmarks/results/data_plane.json]

Tokens are estimated with tiktoken's o200k_base encoding, a proxy: absolute numbers differ per
model, the ratios do not change much. Needs a connection that reaches TSETMC.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import urllib.parse
from pathlib import Path

import httpx
import tiktoken

from iran_bourse_mcp.client import USER_AGENT
from iran_bourse_mcp.service import Bourse

CDN = "https://cdn.tsetmc.com/api"
WEBGW = "https://webgw.tse.ir"
SYMBOL = "فولاد"
ENC = tiktoken.get_encoding("o200k_base")


def tokens(text: str) -> int:
    return len(ENC.encode(text, disallowed_special=()))


class Raw:
    """Sequential raw HTTP, the way a tool-using agent would do it."""

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True)
        self.requests = 0
        self.bytes = 0
        self.text_parts: list[str] = []
        self.seconds = 0.0

    async def get(self, url: str) -> object:
        # a raw-HTTP agent has to retry timeouts and 403s itself; every attempt counts as a request
        last = "?"
        for attempt in range(4):
            started = time.perf_counter()
            self.requests += 1
            try:
                response = await self.client.get(url)
            except httpx.TransportError as exc:
                self.seconds += time.perf_counter() - started
                last = f"{type(exc).__name__}: {exc}"
                await asyncio.sleep(1 + attempt)
                continue
            self.seconds += time.perf_counter() - started
            if response.status_code in (403, 429, 502, 503, 504):
                last = f"HTTP {response.status_code}"
                await asyncio.sleep(1 + attempt)
                continue
            break
        else:
            raise RuntimeError(f"giving up on {url} ({last})")
        self.bytes += len(response.content)
        self.text_parts.append(response.text)
        return response.json() if "json" in response.headers.get("content-type", "") else response.text

    def summary(self) -> dict:
        text = "".join(self.text_parts)
        return {"requests": self.requests, "seconds": round(self.seconds, 2), "bytes": self.bytes, "tokens": tokens(text)}

    async def aclose(self) -> None:
        await self.client.aclose()


async def find(raw: Raw, symbol: str) -> str:
    rows = (await raw.get(f"{CDN}/Instrument/GetInstrumentSearch/{urllib.parse.quote(symbol)}"))["instrumentSearch"]
    return str(next(r for r in rows if r["lVal18AFC"].replace("ي", "ی").replace("ك", "ک") == symbol)["insCode"])


async def id_map(raw: Raw) -> dict:
    """instrumentId -> insCode from the newest end-of-day table that has rows (today's is empty in-session)."""
    import datetime as dt

    overview = (await raw.get(f"{CDN}/MarketData/GetMarketOverview/1"))["marketOverview"]
    today = dt.date(overview["marketActivityDEven"] // 10000, overview["marketActivityDEven"] // 100 % 100, overview["marketActivityDEven"] % 100)
    for back in range(8):
        day = today - dt.timedelta(days=back)
        rows = (await raw.get(f"{CDN}/ClosingPrice/GetInstrmentsHistoryInDay/{day:%Y%m%d}"))["closingPriceDailyHistoryWithInstDetails"]
        if rows:
            return {r["instrumentID"]: r["insCode"] for r in rows}
    return {}


async def prev_trading_day(raw: Raw, ins: str) -> int:
    rows = (await raw.get(f"{CDN}/ClosingPrice/GetClosingPriceDailyList/{ins}/0"))["closingPriceDaily"]
    return sorted(r["dEven"] for r in rows)[-2]


# ------------------------------------------------------------------------------ raw routes
async def raw_quote(raw: Raw) -> None:
    ins = await find(raw, SYMBOL)
    await raw.get(f"{CDN}/Instrument/GetInstrumentInfo/{ins}")
    await raw.get(f"{CDN}/ClosingPrice/GetClosingPriceInfo/{ins}")


async def raw_order_book(raw: Raw) -> None:
    ins = await find(raw, SYMBOL)
    await raw.get(f"{CDN}/Instrument/GetInstrumentInfo/{ins}")
    await raw.get(f"{CDN}/BestLimits/{ins}")


async def raw_trade_summary(raw: Raw) -> None:
    ins = await find(raw, SYMBOL)
    day = await prev_trading_day(raw, ins)
    await raw.get(f"{CDN}/Trade/GetTradeHistory/{ins}/{day}/false")


async def raw_real_legal(raw: Raw) -> None:
    ins = await find(raw, SYMBOL)
    rows = (await raw.get(f"{CDN}/ClosingPrice/GetClosingPriceDailyList/{ins}/0"))["closingPriceDaily"]
    for row in sorted(rows, key=lambda r: r["dEven"], reverse=True)[:10]:
        await raw.get(f"{CDN}/ClientType/GetClientTypeHistory/{ins}/{row['dEven']}")


async def raw_shareholders(raw: Raw) -> None:
    ins = await find(raw, SYMBOL)
    await raw.get(f"{CDN}/Instrument/GetInstrumentInfo/{ins}")
    await raw.get(f"{CDN}/Shareholder/GetInstrumentShareHolderLast/{ins}")


async def raw_buy_queues(raw: Raw) -> None:
    watch = (await raw.get(f"{WEBGW}/InstrumentProvider/api/v1/MarketWatch/MarketWatchCash/fa"))["Items"]
    ids = await id_map(raw)
    candidates = [
        w for w in watch
        if "سهام" in (w.get("securitiesname") or "")
        and (w["maxValue"] or 0) and (w["lastPrice"]["value"] or 0) >= w["maxValue"] and w["instrumentId"] in ids
    ]
    candidates.sort(key=lambda w: w["tradeValue"]["value"] or 0, reverse=True)
    for w in candidates:
        await raw.get(f"{CDN}/BestLimits/{ids[w['instrumentId']]}")


async def raw_codal(raw: Raw) -> None:
    await raw.get(
        "https://search.codal.ir/api/search/v2/q?Symbol=" + urllib.parse.quote(SYMBOL)
        + "&PageNumber=1&Length=-1&Audited=true&NotAudited=true&Consolidatable=true&NotConsolidatable=true"
        "&Childs=true&Mains=true&Publisher=false&CompanyState=-1&Category=-1&CompanyType=-1&LetterType=-1"
    )


async def raw_price_history(raw: Raw) -> None:
    ins = await find(raw, SYMBOL)
    await raw.get(f"{CDN}/ClosingPrice/GetClosingPriceDailyList/{ins}/0")


async def raw_screen(raw: Raw) -> None:
    """The market watch plus the 20 previous trading days' end-of-day tables: the minimum needed to compute the screen."""
    import datetime as dt

    await raw.get(f"{WEBGW}/InstrumentProvider/api/v1/MarketWatch/MarketWatchCash/fa")
    overview =(await raw.get(f"{CDN}/MarketData/GetMarketOverview/1"))["marketOverview"]["marketActivityDEven"]
    day = dt.date(overview // 10000, overview // 100 % 100, overview % 100)
    found = 0
    while found < 20:
        day -= dt.timedelta(days=1)
        if day.weekday() in (3, 4):  # Thursday, Friday
            continue
        rows = (await raw.get(f"{CDN}/ClosingPrice/GetInstrmentsHistoryInDay/{day:%Y%m%d}"))["closingPriceDailyHistoryWithInstDetails"]
        found += 1 if len(rows) > 100 else 0


TASKS = [
    ("quote", "Live quote with correct % change", raw_quote, "quote", {"symbol": SYMBOL}),
    ("order_book", "Order book with queue detection", raw_order_book, "order_book", {"symbol": SYMBOL}),
    ("trade_summary", "One day of ticks: VWAP, biggest trades, bars", raw_trade_summary, "trade_summary", {"symbol": SYMBOL, "date": "PREV"}),
    ("real_legal_10d", "Real vs legal money flow, 10 days", raw_real_legal, "real_legal_flow", {"symbol": SYMBOL, "days": 10}),
    ("shareholders", "Major shareholders", raw_shareholders, "shareholders", {"symbol": SYMBOL}),
    ("buy_queues", "Market-wide ranking of buy queues", raw_buy_queues, "top_movers", {"kind": "buy_queue", "limit": 10}),
    ("codal_5", "Latest 5 Codal filings with links", raw_codal, "codal_filings", {"symbol": SYMBOL, "limit": 5}),
    ("price_history_1y", "One year of daily prices, adjusted", raw_price_history, "price_history", {"symbol": SYMBOL, "limit": 250, "adjusted": True}),
    (
        "screen_surge",
        "Screen the market: volume > 2x 20-day average, up yesterday and today",
        raw_screen,
        "screen_stocks",
        {"filter": "volume > 2 * avg(volume, 20) and close_pct[1] > 1 and close_pct > 0 and value > 5B", "limit": 10},
    ),
]


# ------------------------------------------------------------------------------ traps
async def traps() -> list[dict]:
    raw = Raw()
    out: list[dict] = []
    try:
        ins = await find(raw, SYMBOL)
        closing = (await raw.get(f"{CDN}/ClosingPrice/GetClosingPriceInfo/{ins}"))["closingPriceInfo"]
        true_change = closing["pDrCotVal"] - closing["priceYesterday"]
        out.append({
            "id": "price_change_field",
            "what": "The exchange's own `priceChange` field in GetClosingPriceInfo",
            "naive_reading": closing["priceChange"],
            "correct": true_change,
            "wrong": closing["priceChange"] != true_change,
        })

        day = await prev_trading_day(raw, ins)
        dated = (await raw.get(f"{CDN}/Shareholder/{ins}/{day}"))["shareShareholder"]
        last = (await raw.get(f"{CDN}/Shareholder/GetInstrumentShareHolderLast/{ins}"))["shareHolder"]
        out.append({
            "id": "shareholder_rows_doubled",
            "what": "Counting holders / summing percent from the dated shareholder endpoint",
            "naive_reading": {"holders": len(dated), "percent_sum": round(sum(r["perOfShares"] for r in dated), 2)},
            "correct": {"holders": len(last), "percent_sum": round(sum(r["perOfShares"] for r in last), 2)},
            "wrong": len(dated) != len(last),
        })

        history = (await raw.get(f"{CDN}/ClientType/GetClientTypeHistory/{ins}/{day}"))["clientType"]
        current = (await raw.get(f"{CDN}/ClientType/GetClientType/{ins}/1/0"))["clientType"]
        out.append({
            "id": "client_type_field_names",
            "what": "Reading real-buyer count with the key used by the live endpoint (`buy_CountI`) on history rows",
            "naive_reading": history.get("buy_CountI"),
            "correct": history.get("buy_I_Count"),
            "wrong": history.get("buy_CountI") is None and current.get("buy_CountI") is not None,
        })

        watch = (await raw.get(f"{WEBGW}/InstrumentProvider/api/v1/MarketWatch/MarketWatchCash/fa"))["Items"]
        stocks = [w for w in watch if "سهام" in (w.get("securitiesname") or "")]
        naive = [w for w in stocks if (w["maxValue"] or 0) and (w["lastPrice"]["value"] or 0) >= w["maxValue"] and not w["sellQuantity"]["value"]]
        ids = await id_map(raw)
        confirmed = 0
        for w in naive:
            if w["instrumentId"] not in ids:
                continue
            book = (await raw.get(f"{CDN}/BestLimits/{ids[w['instrumentId']]}"))["bestLimits"]
            asks = sum(b["qTitMeOf"] for b in book)
            bids = sum(b["qTitMeDem"] for b in book)
            if asks == 0 and bids > 0:
                confirmed += 1
        out.append({
            "id": "queue_false_positives",
            "what": "Calling every limit-up stock without visible sell orders a buy queue, using the gateway's market watch alone",
            "naive_reading": len(naive),
            "correct": confirmed,
            "wrong": len(naive) != confirmed,
            "note": "Only meaningful when the gateway's top-of-book fields are empty (outside the session)." if len(naive) != confirmed else "Gateway fields were populated; no divergence at this moment.",
        })

        name = (await raw.get(f"{CDN}/Instrument/GetInstrumentInfo/{ins}"))["instrumentInfo"]["lVal30"]
        out.append({
            "id": "arabic_letters",
            "what": "Matching the company name the user types (Persian letters) against the exchange's text (Arabic letters)",
            "naive_reading": "فولاد مبارکه اصفهان" in name,
            "correct": True,
            "wrong": "فولاد مبارکه اصفهان" not in name,
        })
    finally:
        await raw.aclose()
    return out


# ------------------------------------------------------------------------------ main
async def run(repeats: int, only: set[str] | None = None) -> dict:
    results = []
    for key, title, raw_route, tool, args in TASKS:
        if only and key not in only:
            continue
        raw_runs, mcp_runs = [], []
        for _ in range(repeats):
            await asyncio.sleep(3)  # be polite: the exchange throttles bursts
            raw = Raw()
            try:
                for attempt in range(3):
                    try:
                        await raw_route(raw)
                        break
                    except RuntimeError:
                        if attempt == 2:
                            raise
                        raw = Raw()  # fresh connection pool, then retry the whole route
                        await asyncio.sleep(5)
                raw_runs.append(raw.summary())
                prev = await prev_trading_day(raw, await find(raw, SYMBOL)) if args.get("date") == "PREV" else None
            finally:
                await raw.aclose()
            call_args = {k: (str(prev) if v == "PREV" else v) for k, v in args.items()}
            bourse = Bourse()  # cold cache each time: a fair first call
            started = time.perf_counter()
            result = await getattr(bourse, tool)(**call_args)
            seconds = time.perf_counter() - started
            text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            mcp_runs.append({"requests": 1, "seconds": round(seconds, 2), "bytes": len(text.encode()), "tokens": tokens(text)})
            await bourse.aclose()
        med = lambda runs, k: statistics.median(r[k] for r in runs)  # noqa: E731
        row = {
            "id": key,
            "title": title,
            "raw": {k: med(raw_runs, k) for k in ("requests", "seconds", "bytes", "tokens")},
            "mcp": {k: med(mcp_runs, k) for k in ("requests", "seconds", "bytes", "tokens")},
        }
        row["token_reduction"] = round(row["raw"]["tokens"] / max(row["mcp"]["tokens"], 1), 1)
        row["byte_reduction"] = round(row["raw"]["bytes"] / max(row["mcp"]["bytes"], 1), 1)
        results.append(row)
        print(f"{key:18} raw {row['raw']['requests']:>3} req {row['raw']['seconds']:>5.1f}s {row['raw']['tokens']:>9,} tok | "
              f"mcp {row['mcp']['seconds']:>5.1f}s {row['mcp']['tokens']:>6,} tok | x{row['token_reduction']}")
    if only:  # partial run: the caller merges these rows into an existing result file
        return {"tasks": results}
    browser = await browser_baseline()
    return {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "tokenizer": "tiktoken o200k_base (proxy)",
        "repeats": repeats,
        "tasks": results,
        "traps": await traps(),
        "browser_baseline": browser,
    }


async def browser_baseline() -> dict:
    """What a browser-less fetch of the human-facing pages yields."""
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=40, follow_redirects=True) as client:
        pages = {
            "tsetmc symbol page": "https://tsetmc.com/instInfo/46348559193224090",
            "codal report list": "https://www.codal.ir/ReportList.aspx?search&Symbol=%D9%81%D9%88%D9%84%D8%A7%D8%AF",
        }
        out = {}
        for name, url in pages.items():
            response = await client.get(url)
            body = response.text
            out[name] = {
                "status": response.status_code,
                "bytes": len(body.encode()),
                "tokens": tokens(body),
                "has_price_data": any(token in body for token in ("4210", "4330", "pClosing", "qTotTran5J")),
                "unrendered_template_markers": body.count("{{"),
            }
        return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="benchmarks/results/data_plane.json")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--only", help="comma-separated task ids; their rows are merged into the existing --out file")
    args = parser.parse_args()
    only = {t.strip() for t in args.only.split(",")} if args.only else None
    data = asyncio.run(run(args.repeats, only))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    if only:
        merged = json.loads(Path(args.out).read_text(encoding="utf-8"))
        known = {t["id"]: i for i, t in enumerate(merged["tasks"])}
        for row in data["tasks"]:
            if row["id"] in known:
                merged["tasks"][known[row["id"]]] = row
            else:
                merged["tasks"].append(row)
        merged["generated"] = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        Path(args.out).write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        print("merged", sorted(only), "into", args.out)
        raise SystemExit(0)
    Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\ntraps:")
    for t in data["traps"]:
        print(f"  {'WRONG' if t['wrong'] else 'ok   '} {t['id']:28} naive={t['naive_reading']} correct={t['correct']}")
    print("wrote", args.out)
