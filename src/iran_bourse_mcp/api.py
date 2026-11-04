"""Thin, typed-by-convention wrappers over the raw TSETMC / TSE gateway / Codal endpoints.

Everything here returns the *raw* upstream payload (inner list/dict). Turning that into clean,
unit-explicit output is the job of :mod:`iran_bourse_mcp.shape`.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import quote, urlencode

from .client import Http, UpstreamError

CDN = os.environ.get("IRAN_BOURSE_CDN_URL", "https://cdn.tsetmc.com/api").rstrip("/")
WEBGW = os.environ.get("IRAN_BOURSE_WEBGW_URL", "https://webgw.tse.ir").rstrip("/")
CODAL_SEARCH = os.environ.get("IRAN_BOURSE_CODAL_URL", "https://search.codal.ir/api/search/v2/q")
CODAL_SITE = "https://codal.ir"
IME = os.environ.get("IRAN_BOURSE_IME_URL", "https://www.ime.co.ir/SubSystems/IME/Services/Home/imedata.asmx").rstrip("/")
IEE = os.environ.get("IRAN_BOURSE_IEE_URL", "https://webapi.iee.ir/api").rstrip("/")

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

    # -- Iran Mercantile Exchange (بورس کالای ایران), physical market ---------------------
    async def _ime(self, method: str, payload: dict[str, Any], ttl: float) -> list[dict]:
        """One ASMX service call. The answer is ``{"d": "<a JSON array as a string>"}``; this returns the array."""
        data = await self.http.post_json(f"{IME}/{method}", {"Language": 8, **payload}, ttl=ttl)
        inner = data.get("d") if isinstance(data, dict) else None
        if isinstance(inner, str):
            try:
                inner = json.loads(inner)
            except ValueError as exc:
                raise UpstreamError(f"IME {method} answered something that is not JSON: {inner[:80]!r}", status=200) from exc
        return inner if isinstance(inner, list) else []

    async def ime_trades(self, jalali_from: str, jalali_to: str, main_cat: int = 0) -> list[dict]:
        """Physical-market rows of one or more days (``GetAmareMoamelatList``, the page «آمار معاملات فیزیکی»): every offer and contract
        with traded tons, prices and the thousand-rial value. About 180 to 400 rows (100 to 400 KB) per day. Dates are Jalali ``1405/08/13``
        although the parameters are called Gregorian; a real Gregorian date makes the service answer HTTP 500. ``main_cat`` 0 is every group."""
        payload = {"fari": False, "GregorianFromDate": jalali_from, "GregorianToDate": jalali_to, "MainCat": int(main_cat), "Cat": 0, "SubCat": 0, "Producer": 0}
        return await self._ime("GetAmareMoamelatList", payload, SHORT)

    async def ime_rings(self, jalali_from: str, jalali_to: str) -> list[dict]:
        """The physical market by ring (``GetHomeFizikiWithDateGrid``): value in million rial, traded and offered volume (tons)."""
        return await self._ime("GetHomeFizikiWithDateGrid", {"GregorianFromDate": jalali_from, "GregorianToDate": jalali_to}, SHORT)

    async def ime_markets(self, jalali_from: str, jalali_to: str) -> list[dict]:
        """Traded value by market (physical, futures, options, financial, certificates) over the dates (``GetHomeNamaWithDateGrid``, million rial)."""
        return await self._ime("GetHomeNamaWithDateGrid", {"GregorianFromDate": jalali_from, "GregorianToDate": jalali_to}, SHORT)

    async def ime_daily(self, jalali_from: str, jalali_to: str) -> list[dict]:
        """One row per session with the physical market's traded value (million rial) and volume (``GetHajmArzeshMoamelatDateGrid``)."""
        return await self._ime("GetHajmArzeshMoamelatDateGrid", {"GregorianFromDate": jalali_from, "GregorianToDate": jalali_to}, SHORT)

    async def ime_usd_rate(self) -> list[dict]:
        """The dollar rate IME shows on its home page, newest two days (``GetHomeExchangeRateData``)."""
        return await self._ime("GetHomeExchangeRateData", {}, HOUR)

    # -- Iran Energy Exchange (بورس انرژی ایران) -----------------------------------------
    async def _iee(self, path: str, params: dict[str, Any] | None = None, ttl: float = SHORT) -> dict:
        """One GET on the exchange's public web API (``webapi.iee.ir``). Every answer is
        ``{"results": [...], "pagedMetaData": [...], "isSuccess": ..., "errors": [...]}``; this returns that object."""
        query = urlencode({"Lang": "fa", **(params or {})})
        data = await self.http.get_json(f"{IEE}{path}?{query}", ttl=ttl)
        if not isinstance(data, dict) or "results" not in data:
            raise UpstreamError(f"Energy Exchange API {path} answered an unexpected shape.", status=200)
        if data.get("isFailed") or data.get("isSuccess") is False:
            raise UpstreamError(f"Energy Exchange API {path} reported an error: {data.get('errors')}", status=200)
        return data

    async def iee_physical_trades(self, jalali_from: str, jalali_to: str, page_size: int = 1000) -> dict:
        """Auction results of the physical market (oil products, gas, petrochemicals, liquid gases ...), one row per auction, with the
        exchange's own value in rial. A day is 10 to 40 rows; text and numbers are strings with thousands separators."""
        params = {"PageNumber": 1, "PageSize": page_size, "FromDate": jalali_from, "ToDate": jalali_to}
        return await self._iee("/PhysicalMarket/GetTradesStatistics", params)

    async def iee_power_trades(self, jalali_from: str, jalali_to: str, page_size: int = 1000) -> dict:
        """Auction results of the electricity market (standard, free, green; kW over a delivery period and total kWh)."""
        params = {"PageNumber": 1, "PageSize": page_size, "FromDate": jalali_from, "ToDate": jalali_to}
        return await self._iee("/PowerMarket/GetPowerTradesStatistics", params)

    async def iee_physical_offers(self, page_size: int = 50) -> dict:
        """Announced physical-market offers (auctions not yet held), soonest first. Fast (0.2 s)."""
        return await self._iee("/PhysicalMarket/GetPhysicalMarketOffersAuction", {"PageNumber": 1, "PageSize": page_size}, SHORT * 2)

    async def iee_power_offers(self, page_size: int = 20) -> dict:
        """Electricity-market auction announcements, newest first: the whole archive (9,626 on 2026-11-05, held ones marked «برگزار شده» in
        ``auctionState``) with terms of delivery and payment, so the next sessions sit on page one. Slow: 4 to 5 s for 10 to 40 rows."""
        return await self._iee("/PowerMarket/GetPowerMarketAuctionAnnouncements", {"PageNumber": 1, "PageSize": page_size}, SHORT * 4)

    async def iee_auction(self, auction_id: int) -> dict:
        """One auction (physical or electricity) with its specification, units, buy and sell order levels and trades."""
        return await self._iee(f"/PhysicalMarket/GetMarketAuctionDetails/{int(auction_id)}", None, SHORT)

    async def iee_auction_trades(self, auction_id: int) -> dict:
        """The executed trades of one auction, each with price, quantity, rial value and the price's unit."""
        return await self._iee(f"/PhysicalMarket/GetMarketAuctionDetailsTradeOnDay/{int(auction_id)}", None, SHORT)

    async def iee_markets_today(self) -> dict:
        """Traded value (million rial) and trade count so far today for the physical, power, derivatives and other markets."""
        return await self._iee("/Home/GetTodayMarketsValues", None, LIVE * 5)

    async def iee_physical_glance(self) -> dict:
        """Market state (open or closed) and today's totals of the physical market, split by ring."""
        return await self._iee("/PhysicalMarket/GetPhysicalMarketAtAGlance", None, LIVE * 5)

    async def iee_power_glance(self) -> dict:
        """Market state and today's totals of the electricity market."""
        return await self._iee("/PowerMarket/GetPowerMarketAtAGlance", None, LIVE * 5)

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
