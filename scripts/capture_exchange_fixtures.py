"""Record real IME and Iran Energy Exchange responses into tests/fixtures (run from a machine that reaches ime.co.ir and iee.ir).

    PYTHONPATH=src python scripts/capture_exchange_fixtures.py

The dates are fixed, so the dated payloads (trades, roll-ups) come back identical on every run; the announced offers and today's
overview are "now" data and differ each time. Big lists are cut to a bounded number of rows; every field of a kept row is untouched
and each file says in ``_note`` what was recorded and what was left out.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from iran_bourse_mcp.api import IEE, IME, TseApi
from iran_bourse_mcp.client import Http

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
SESSION = "1405/08/13"  # Wednesday 2026-11-04, the last session before the capture
CAPTURED = "2026-11-05"


def dump(name: str, data: object) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print("wrote", name)


def wire(rows: list[dict]) -> dict:
    """The ASMX answer shape: the array is a JSON string under ``d``."""
    return {"d": json.dumps(rows, ensure_ascii=False)}


def pick_ime_rows(rows: list[dict]) -> list[dict]:
    """The biggest traded row of every (hall, contract type) pair plus the first two offers that did not trade."""
    best: dict[tuple, dict] = {}
    for row in rows:
        if (row.get("Quantity") or 0) > 0:
            key = (row["Talar"], row["ContractType"])
            if key not in best or (row["TotalPrice"] or 0) > (best[key]["TotalPrice"] or 0):
                best[key] = row
    untraded = [row for row in rows if not row.get("Quantity")][:2]
    return sorted(best.values(), key=lambda r: -(r["TotalPrice"] or 0)) + untraded


async def main() -> None:
    api = TseApi(Http())

    trades = await api.ime_trades(SESSION, SESSION)
    kept = pick_ime_rows(trades)
    dump(
        "commodity_ime_trades",
        {
            "_note": f"POST {IME}/GetAmareMoamelatList, fari=false, MainCat=0, {SESSION} (2026-11-04), recorded {CAPTURED}. The day has {len(trades)} rows; kept {len(kept)}: "
            "the largest traded row of every hall and contract type, then the first two offers that did not trade. Every field of a kept row is untouched.",
            **wire(kept),
        },
    )
    first, last = "1405/07/29", "1405/08/14"
    dump(
        "commodity_ime_rollups",
        {
            "_note": f"POST {IME}/GetHomeFizikiWithDateGrid, GetHomeNamaWithDateGrid, GetHajmArzeshMoamelatDateGrid, GetHomeExchangeRateData, recorded {CAPTURED}. "
            f"rings and markets are for {SESSION}; daily covers {first} to {last} (Thursday 1405/08/14 has no row); usd is the newest two days. Nothing trimmed. "
            "thursday is GetAmareMoamelatList for 1405/08/14, which answers an empty list.",
            "rings": wire(await api.ime_rings(SESSION, SESSION)),
            "markets": wire(await api.ime_markets(SESSION, SESSION)),
            "daily": wire(await api.ime_daily(first, last)),
            "usd": wire(await api.ime_usd_rate()),
            "thursday": wire(await api.ime_trades("1405/08/14", "1405/08/14")),
        },
    )

    physical = await api.iee_physical_trades(SESSION, SESSION)
    dump(
        "energy_iee_physical_trades",
        {
            "_note": f"GET {IEE}/PhysicalMarket/GetTradesStatistics?Lang=fa&PageNumber=1&PageSize=1000&FromDate={SESSION}&ToDate={SESSION}, recorded {CAPTURED}. Nothing trimmed (18 auctions).",
            **physical,
        },
    )
    power = await api.iee_power_trades("1405/08/05", "1405/08/13")
    dump(
        "energy_iee_power_trades",
        {
            "_note": f"GET {IEE}/PowerMarket/GetPowerTradesStatistics?Lang=fa&PageNumber=1&PageSize=1000&FromDate=1405/08/05&ToDate=1405/08/13, recorded {CAPTURED}. Nothing trimmed.",
            **power,
        },
    )
    offers = await api.iee_physical_offers(4)
    dump(
        "energy_iee_physical_offers",
        {
            "_note": f"GET {IEE}/PhysicalMarket/GetPhysicalMarketOffersAuction?Lang=fa&PageNumber=1&PageSize=4, recorded {CAPTURED}. Page 1 of 3; the exchange had 10 announced offers.",
            **offers,
        },
    )
    power_offers = await api.iee_power_offers(10)
    rows = power_offers["results"]
    power_offers["results"] = [r for r in rows if not r.get("auctionState")][:3] + [
        r for r in rows if r.get("auctionState")
    ][:2]
    dump(
        "energy_iee_power_offers",
        {
            "_note": f"GET {IEE}/PowerMarket/GetPowerMarketAuctionAnnouncements?Lang=fa&PageNumber=1&PageSize=10, recorded {CAPTURED}. The endpoint is an archive of all "
            f"{power_offers['pagedMetaData'][0]['totalCount']} announcements, newest first. Kept the first 3 upcoming records (auctionState empty) and the first 2 held ones "
            "(auctionState «برگزار شده»); every field of a kept record is untouched; pagedMetaData is the exchange's, for the full page of 10.",
            **power_offers,
        },
    )
    dump(
        "energy_iee_auction",
        {
            "_note": f"GET {IEE}/PhysicalMarket/GetMarketAuctionDetails/96519 and GetMarketAuctionDetailsTradeOnDay/96519, recorded {CAPTURED}. CSO of Shazand, 2026-11-04. Nothing trimmed.",
            "detail": await api.iee_auction(96519),
            "trades": await api.iee_auction_trades(96519),
        },
    )
    dump(
        "energy_iee_overview",
        {
            "_note": f"GET {IEE}/Home/GetTodayMarketsValues, PhysicalMarket/GetPhysicalMarketAtAGlance, PowerMarket/GetPowerMarketAtAGlance, recorded {CAPTURED} (Thursday: every market closed, every figure zero).",
            "today": await api.iee_markets_today(),
            "physical": await api.iee_physical_glance(),
            "power": await api.iee_power_glance(),
        },
    )
    await api.http.aclose()


if __name__ == "__main__":
    asyncio.run(main())
