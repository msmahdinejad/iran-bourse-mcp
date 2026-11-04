"""Thin, typed-by-convention wrappers over the raw TSETMC / TSE gateway / Codal endpoints.

Everything here returns the *raw* upstream payload (inner list/dict). Turning that into clean,
unit-explicit output is the job of :mod:`iran_bourse_mcp.shape`.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote, urlencode

from .client import Http

CDN = os.environ.get("IRAN_BOURSE_CDN_URL", "https://cdn.tsetmc.com/api").rstrip("/")
WEBGW = os.environ.get("IRAN_BOURSE_WEBGW_URL", "https://webgw.tse.ir").rstrip("/")
CODAL_SEARCH = os.environ.get("IRAN_BOURSE_CODAL_URL", "https://search.codal.ir/api/search/v2/q")
CODAL_SITE = "https://codal.ir"

LIVE = 3.0  # seconds
SHORT = 30.0
HOUR = 3600.0
STATIC = 6 * 3600.0


class TseApi:
    def __init__(self, http: Http) -> None:
        self.http = http

    # -- plumbing ------------------------------------------------------------------------
    async def _cdn(self, path: str, key: str | None, ttl: float) -> Any:
        data = await self.http.get_json(f"{CDN}{path}", ttl=ttl)
        if key is None or not isinstance(data, dict):
            return data
        return data.get(key)

    # -- instruments ---------------------------------------------------------------------
    async def search(self, query: str) -> list[dict]:
        data = await self._cdn(f"/Instrument/GetInstrumentSearch/{quote(query)}", "instrumentSearch", SHORT * 4)
        return data or []

    async def instrument_info(self, ins: str) -> dict:
        return await self._cdn(f"/Instrument/GetInstrumentInfo/{ins}", "instrumentInfo", SHORT) or {}

    async def identity(self, ins: str) -> dict:
        return await self._cdn(f"/Instrument/GetInstrumentIdentity/{ins}", "instrumentIdentity", STATIC) or {}

    async def share_changes(self, ins: str) -> list[dict]:
        return await self._cdn(f"/Instrument/GetInstrumentShareChange/{ins}", "instrumentShareChange", HOUR) or []

    async def static_data(self) -> list[dict]:
        return await self._cdn("/StaticData/GetStaticData", "staticData", STATIC) or []

    async def server_time(self) -> str:
        return await self.http.get_text(f"{CDN}/StaticData/GetTime", ttl=1.0)

    # -- prices --------------------------------------------------------------------------
    async def closing_info(self, ins: str) -> dict:
        return await self._cdn(f"/ClosingPrice/GetClosingPriceInfo/{ins}", "closingPriceInfo", LIVE) or {}

    async def daily_prices(self, ins: str) -> list[dict]:
        return await self._cdn(f"/ClosingPrice/GetClosingPriceDailyList/{ins}/0", "closingPriceDaily", SHORT * 2) or []

    async def closing_history(self, ins: str, deven: int) -> list[dict]:
        return await self._cdn(f"/ClosingPrice/GetClosingPriceHistory/{ins}/{deven}", "closingPriceHistory", HOUR) or []

    async def prices_on_day(self, deven: int) -> list[dict]:
        return (
            await self._cdn(f"/ClosingPrice/GetInstrmentsHistoryInDay/{deven}", "closingPriceDailyHistoryWithInstDetails", HOUR)
            or []
        )

    async def price_adjustments(self, ins: str) -> list[dict]:
        return await self._cdn(f"/ClosingPrice/GetPriceAdjustList/{ins}", "priceAdjust", HOUR) or []

    async def related_companies(self, sector_code: str) -> list[dict]:
        return await self._cdn(f"/ClosingPrice/GetRelatedCompany/{quote(sector_code.strip())}", "relatedCompany", SHORT) or []

    # -- order book ----------------------------------------------------------------------
    async def best_limits(self, ins: str) -> list[dict]:
        return await self._cdn(f"/BestLimits/{ins}", "bestLimits", LIVE) or []

    async def best_limits_history(self, ins: str, deven: int, ttl: float = HOUR) -> list[dict]:
        return await self._cdn(f"/BestLimits/{ins}/{deven}", "bestLimitsHistory", ttl) or []

    # -- trades --------------------------------------------------------------------------
    async def trades_latest(self, ins: str) -> list[dict]:
        return await self._cdn(f"/Trade/GetTrade/{ins}", "trade", LIVE) or []

    async def trades_history(self, ins: str, deven: int, ttl: float = HOUR) -> list[dict]:
        return await self._cdn(f"/Trade/GetTradeHistory/{ins}/{deven}/false", "tradeHistory", ttl) or []

    # -- real / legal --------------------------------------------------------------------
    async def client_type(self, ins: str) -> dict:
        return await self._cdn(f"/ClientType/GetClientType/{ins}/1/0", "clientType", LIVE) or {}

    async def client_type_history(self, ins: str, deven: int, ttl: float = HOUR) -> dict:
        return await self._cdn(f"/ClientType/GetClientTypeHistory/{ins}/{deven}", "clientType", ttl) or {}

    async def client_type_all(self) -> list[dict]:
        return await self._cdn("/ClientType/GetClientTypeAll", "clientTypeAllDto", SHORT) or []

    # -- shareholders --------------------------------------------------------------------
    async def shareholders_last(self, ins: str) -> list[dict]:
        return await self._cdn(f"/Shareholder/GetInstrumentShareHolderLast/{ins}", "shareHolder", HOUR) or []

    async def shareholder_snapshots(self, ins: str, deven: int) -> list[dict]:
        return await self._cdn(f"/Shareholder/{ins}/{deven}", "shareShareholder", HOUR) or []

    async def holder_portfolio(self, share_id: int | str) -> list[dict]:
        return await self._cdn(f"/Shareholder/GetShareHolderCompanyList/{share_id}", "shareHolderShare", HOUR) or []

    async def holder_moves_market(self) -> dict:
        return await self._cdn("/Shareholder/GetShareHolderChanges/false", None, HOUR) or {}

    # -- market --------------------------------------------------------------------------
    async def market_overview(self, flow: int) -> dict:
        return await self._cdn(f"/MarketData/GetMarketOverview/{flow}", "marketOverview", SHORT) or {}

    async def sectors_summary(self) -> list[dict]:
        return await self._cdn("/MarketData/GetSectorsSummary", "sectorSummeries", SHORT) or []

    async def indices(self, flow: int) -> list[dict]:
        return await self._cdn(f"/Index/GetIndexB1LastAll/All/{flow}", "indexB1", SHORT) or []

    async def instrument_state(self, ins: str, deven: int) -> list[dict]:
        return await self._cdn(f"/MarketData/GetInstrumentState/{ins}/{deven}", "instrumentState", SHORT) or []

    async def statistics(self, ins: str) -> list[dict]:
        return await self._cdn(f"/MarketData/GetInstrumentStatistic/{ins}", "instrumentStatistic", HOUR) or []

    async def thresholds(self, ins: str, deven: int) -> list[dict]:
        return await self._cdn(f"/MarketData/GetStaticThreshold/{ins}/{deven}", "staticThreshold", HOUR) or []

    async def etf(self, ins: str) -> dict:
        return await self._cdn(f"/Fund/GetETFByInsCode/{ins}", "etf", SHORT) or {}

    # -- supervisor messages -------------------------------------------------------------
    async def messages_for(self, ins: str) -> list[dict]:
        return await self._cdn(f"/Msg/GetMsgByInsCode/{ins}", "msg", SHORT * 4) or []

    async def messages_flow(self, flow: int, top: int) -> list[dict]:
        return await self._cdn(f"/Msg/GetMsgByFlow/{flow}/{top}", "msg", SHORT) or []

    async def market_watch_all(self) -> list[dict]:
        """The exchange's own market-watch feed (what tsetmc.com's table and filter box run on): every instrument, 5-level book."""
        query = "market=0&industrialGroup=&showTraded=false&withBestLimits=true&hEven=0&RefID=0"
        data = await self.http.get_json(f"{CDN}/ClosingPrice/GetMarketWatch?{query}", ttl=LIVE * 2)
        return (data or {}).get("marketwatch", []) if isinstance(data, dict) else []

    # -- TSE gateway ---------------------------------------------------------------------
    async def market_watch(self) -> list[dict]:
        data = await self.http.get_json(
            f"{WEBGW}/InstrumentProvider/api/v1/MarketWatch/MarketWatchCash/fa", ttl=LIVE * 2
        )
        return (data or {}).get("Items", [])

    async def market_dates(self) -> list[dict]:
        return await self.http.get_json(f"{WEBGW}/api/v1/PublicData/MarketDate/fa", ttl=SHORT) or []

    async def company_states(self) -> list[dict]:
        return (
            await self.http.get_json(f"{WEBGW}/InstrumentProvider/api/v1/Instrument/CompanyState/fa", ttl=HOUR) or []
        )

    # -- Codal ---------------------------------------------------------------------------
    async def codal_search(self, **params: Any) -> dict:
        query = {
            "Audited": "true",
            "NotAudited": "true",
            "Consolidatable": "true",
            "NotConsolidatable": "true",
            "Childs": "true",
            "Mains": "true",
            "Publisher": "false",
            "CompanyState": "-1",
            "Category": "-1",
            "CompanyType": "-1",
            "LetterType": "-1",
            "Length": "-1",
            "PageNumber": "1",
        }
        query.update({k: str(v) for k, v in params.items() if v is not None})
        return await self.http.get_json(f"{CODAL_SEARCH}?{urlencode(query)}", ttl=SHORT) or {}

    async def codal_attachments(self, main_table_row_id: int | str) -> list[dict]:
        return (
            await self._cdn(f"/Codal/GetFileAttachmentByMainTableRowId/{main_table_row_id}", "fileAttachment", HOUR) or []
        )

    async def codal_publisher(self, symbol: str) -> dict:
        return await self._cdn(f"/Codal/GetCodalPublisherBySymbol/{quote(symbol)}", "codalPublisher", HOUR) or {}
