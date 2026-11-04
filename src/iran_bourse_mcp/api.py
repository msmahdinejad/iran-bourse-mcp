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

    async def client_type_history_all(self, ins: str) -> list[dict]:
        """Every day's real/legal figures of a symbol in one response (about 1.3 MB for a symbol listed since 2008)."""
        data = await self._cdn(f"/ClientType/GetClientTypeHistory/{ins}", "clientType", HOUR)
        return data if isinstance(data, list) else []

    async def client_type_all(self) -> list[dict]:
        return await self._cdn("/ClientType/GetClientTypeAll", "clientTypeAllDto", SHORT) or []

    # -- shareholders --------------------------------------------------------------------
    async def shareholders_last(self, ins: str) -> list[dict]:
        return await self._cdn(f"/Shareholder/GetInstrumentShareHolderLast/{ins}", "shareHolder", HOUR) or []

    async def shareholder_snapshots(self, ins: str, deven: int) -> list[dict]:
        return await self._cdn(f"/Shareholder/{ins}/{deven}", "shareShareholder", HOUR) or []

    async def holder_history(self, ins: str, share_id: int | str, top: int) -> list[dict]:
        """One major holder's daily position in one symbol, newest first."""
        return await self._cdn(f"/Shareholder/GetShareHolderHistory/{ins}/{share_id}/{top}", "shareHolder", HOUR) or []

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

    # -- official lists, corporate-action calendar, trading status ----------------------
    async def trade_top(self, kind: str, flow: int, top: int) -> list[dict]:
        return await self._cdn(f"/ClosingPrice/GetTradeTop/{kind}/{flow}/{top}", "tradeTop", LIVE) or []

    async def best_limits_top(self, kind: str, flow: int, top: int) -> list[dict]:
        return await self._cdn(f"/BestLimits/GetBestLimitsTop/{kind}/{flow}/{top}", "bestLimitsTop", LIVE) or []

    async def market_cap_top(self, kind: str, flow: int, top: int) -> list[dict]:
        return await self._cdn(f"/ClosingPrice/GetMarketCap/{kind}/{flow}/{top}", "marketCap", SHORT) or []

    async def sector_top(self, top: int = 0) -> list[dict]:
        return await self._cdn(f"/MarketData/GetSectorTop/{top}", "sectorTop", SHORT) or []

    async def share_changes_by_flow(self, flow: int) -> list[dict]:
        """Every share-count change of a market incl. future-dated ones (the exchange ignores `top`: 0.1 to 0.5 MB)."""
        return await self._cdn(f"/Instrument/GetInstrumentShareChangeByFlow/{flow}/10", "instrumentShareChange", HOUR) or []

    async def price_adjust_by_flow(self, flow: int, top: int) -> list[dict]:
        return await self._cdn(f"/ClosingPrice/GetPriceAdjustByFlow/{flow}/{top}", "priceAdjust", HOUR) or []

    async def supervision_list(self, source: int, list_type: int) -> list[dict]:
        return await self._cdn(f"/Supervision/GetSupervisionListBySourceID/{source}/{list_type}", "supervision", SHORT) or []

    async def supervision_for(self, ins: str) -> dict:
        return await self._cdn(f"/Supervision/GetSupervisionByInsCode/{ins}", "supervision", SHORT) or {}

    async def state_log(self, n: int) -> list[dict]:
        return await self._cdn(f"/MarketData/GetInstrumentStateTop/{n}", "instrumentState", SHORT) or []

    async def state_history(self, ins: str) -> list[dict]:
        return await self._cdn(f"/MarketData/GetInstrumentStateAll/{ins}", "instrumentState", SHORT) or []

    # -- indices: history, today's path, members ------------------------------------------
    async def index_history(self, ins: str) -> list[dict]:
        """Daily close/low/high of one index since 2008 (about 4,300 rows, 0.5 MB). The last row is today's."""
        return await self._cdn(f"/Index/GetIndexB2History/{ins}", "indexB2", SHORT) or []

    async def index_intraday(self, ins: str) -> list[dict]:
        """The index on a 5-minute grid for the latest session (about 125 rows)."""
        return await self._cdn(f"/Index/GetIndexB1LastDay/{ins}", "indexB1", SHORT) or []

    async def index_members(self, ins: str) -> list[dict]:
        """Member stocks with today's prices (405 for the total index). The reply also carries a 30-day close history of every member
        (about 11,700 rows, 2.4 MB for the total index) under ``relatedCompanyThirtyDayHistory``; only ``indexCompany`` is returned."""
        return await self._cdn(f"/ClosingPrice/GetIndexCompany/{ins}", "indexCompany", SHORT) or []

    async def index_effects(self, deven: int, flow: int, top: int = 9999) -> list[dict]:
        """Index points each stock added to the market's total index (flow 1 Bourse, 2 Fara). The server ignores ``deven``: the table is the latest session's."""
        return await self._cdn(f"/Index/GetInstEffect/{deven}/{flow}/{top}", "instEffect", SHORT) or []

    # -- funds -----------------------------------------------------------------------------
    async def funds(self, fund_type: int) -> list[dict]:
        """The fund registry for one type id (4, 5, 6, 7, 11, 12, 13, 16, 17, 18, 21-25). Ids 0 and 1 answer HTTP 500, other ids are empty."""
        return await self._cdn(f"/Fund/GetFunds/{fund_type}", "funds", HOUR) or []

    # -- derivatives (options and futures) -----------------------------------------------
    async def option_market_watch(self, flow: int = 0) -> list[dict]:
        """Option chain rows, one per strike/expiry pair with the call and the put side by side. flow 0 = all, 1 = Bourse, 2 = Fara Bourse."""
        return await self._cdn(f"/Instrument/GetInstrumentOptionMarketWatch/{int(flow)}", "instrumentOptMarketWatch", SHORT) or []

    async def future_market_watch(self) -> list[dict]:
        """Futures (آتی) with open interest and the underlying's prices."""
        return await self._cdn("/Instrument/GetInstrumentFutureMarketWatch/0", "instrumentFtMarketWatch", LIVE * 2) or []

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
