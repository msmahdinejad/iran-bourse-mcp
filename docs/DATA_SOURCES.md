# Data sources and known quirks

Three public, **unofficial** sources are used. None has documented stability guarantees. Every item below was observed on the live servers (2 to 4 November 2026) while building this project.

| Source | Base URL | Key for an instrument | Used for |
|---|---|---|---|
| TSETMC API | `https://cdn.tsetmc.com/api` | `insCode` (numeric string) | quotes, history, order book, ticks, real/legal, shareholders, messages, Codal attachments |
| TSE gateway | `https://webgw.tse.ir` | `instrumentId` (e.g. `IRO1FOLD0001`) | whole-market watch (590 rows incl. P/E, EPS, industry, board, limits), market open flags |
| Codal search | `https://search.codal.ir/api/search/v2/q` | `Symbol` | filings with page/PDF/Excel/attachment links |

`instrumentId` (gateway) and `insCode` (TSETMC) are joined through `GetInstrmentsHistoryInDay`, which carries both.

All requests need a browser-like `User-Agent`; without one TSETMC answers 403.

## Endpoint map

| Tool | Endpoints |
|---|---|
| `quote`, `symbol_overview` | `Instrument/GetInstrumentInfo`, `ClosingPrice/GetClosingPriceInfo` |
| `order_book` | `BestLimits/{ins}`, thresholds from `GetInstrumentInfo` |
| `order_book_history` | `BestLimits/{ins}/{date}`, `MarketData/GetStaticThreshold/{ins}/{date}` |
| `trades`, `trade_summary` | `Trade/GetTrade/{ins}` (latest day), `Trade/GetTradeHistory/{ins}/{date}/false`, totals from `ClosingPrice/GetClosingPriceDailyList` |
| `price_history` | `ClosingPrice/GetClosingPriceDailyList/{ins}/0` |
| `real_legal_flow` | `ClientType/GetClientType/{ins}/1/0`, `ClientType/GetClientTypeHistory/{ins}/{date}` |
| `top_movers` (real_*) | `ClientType/GetClientTypeAll`, `ClosingPrice/GetInstrmentsHistoryInDay/{date}`, gateway market watch |
| queues in `top_movers` | gateway market watch to find limit-locked symbols, then `BestLimits/{ins}` for the true queue size |
| `shareholders` | `Shareholder/GetInstrumentShareHolderLast/{ins}` |
| `shareholder_history` | `Shareholder/{ins}/{date}` |
| `shareholder_portfolio` | `Shareholder/GetShareHolderCompanyList/{holderId}` |
| `market_holder_moves` | `Shareholder/GetShareHolderChanges/false` |
| `corporate_actions` | `ClosingPrice/GetPriceAdjustList/{ins}`, `Instrument/GetInstrumentShareChange/{ins}` |
| `symbol_statistics` | `MarketData/GetInstrumentStatistic/{ins}` |
| `etf_nav` | `Fund/GetETFByInsCode/{ins}` |
| `indices`, `market_overview` | `Index/GetIndexB1LastAll/All/{flow}`, `MarketData/GetMarketOverview/{flow}` (`flow` 1 = bourse, 2 = Fara Bourse) |
| `supervisor_messages` | `Msg/GetMsgByInsCode/{ins}`, `Msg/GetMsgByFlow/{flow}/{top}` |
| `codal_filings` | Codal search API |
| `codal_company` | `Codal/GetCodalPublisherBySymbol/{symbol}` |

## Quirks we found, and what we do about them

1. **`closingPriceInfo.priceChange` is unreliable.** It was `0.0` for a stock that closed 120 rial above yesterday. We recompute change from `pDrCotVal` (last trade) / `pClosing` (closing price) and `priceYesterday`.
2. **Two prices.** `pClosing` is the exchange's closing (weighted) price, `pDrCotVal` is the last trade. Both are returned (`last`, `close`).
3. **Order-book history is a delta feed.** Each `refID` lists only the levels that changed (1 to 5 rows). We rebuild full 5-level snapshots by carrying unchanged levels forward. Events are not limited to the session: orders entered before the open (from about 06:00) and after the close (until about 14:30) are recorded too, so `order_book_history` defaults to 08:30-12:35.
4. **Order-book history for the current day is partial.** On the day we measured, the endpoint stopped at about 09:02 for the current trading day but covered the full session for the previous day. We expose `events_span` and a `warning` instead of pretending.
5. **Tick data is complete.** `Trade/GetTradeHistory` and `GetTrade` matched the exchange's own totals exactly (6,819 and 15,643 trades, 100% of volume) for فولاد on two days. `trade_summary.completeness` repeats this check on every call.
6. **Field names differ between endpoints.** Counts are `buy_CountI` in `GetClientType` but `buy_I_Count` in `GetClientTypeHistory`; only the history variant carries Rial values. We accept both. Current-day values in `real_legal_flow.latest_session` are therefore *estimated* (volume x VWAP) and flagged `value_estimated`.
7. **`Shareholder/{ins}/{date}` returns each holder under two dates** (a current and a neighbouring snapshot). `shareholders` uses `GetInstrumentShareHolderLast` (clean, 1%+ holders); `shareholder_history` groups the dated rows and computes differences.
8. **ETF endpoint is stock-hostile.** `GetETFByInsCode` returns HTTP 500 for non-fund instruments. `etf_nav` converts that to a clear "not a fund" answer.
9. **Search is fuzzy.** `GetInstrumentSearch` returns about 41 hits for any query. We pick the exact normalised symbol match (Arabic ي/ك and Persian ی/ک are equal), preferring the lowest `flow` id when a symbol exists on several boards, and otherwise fail with suggestions.
10. **The gateway's market watch cannot confirm a queue.** A limit-up symbol with no visible sell volume looks like a buy queue, but in our check 85 symbols looked like queues from the watch alone while 83 were real, and the best-bid fields are unreliable outside the session. `top_movers(kind="buy_queue")` therefore confirms every limit-locked candidate against its real order book (one `BestLimits` call each, about ten seconds on a day with ~200 limit-up symbols).
11. **Adjusted prices are inferred.** TSETMC's `GetPriceAdjustList` covers dividend adjustments but omits many capital increases (e.g. فولاد 2026-03-30, 1500bn to 1935bn shares, factor 0.775). We infer adjustment events from the series itself: on an ex-date `priceYesterday` no longer equals the previous `pClosing`. Differences under 0.1% are treated as tick rounding. Very old rows (before about 2014) sometimes lack this continuity.
12. **Dates.** `dEven` is a Gregorian `YYYYMMDD` integer, `hEven` is `HHMMSS` (no leading zero, so `90013` is 09:00:13). `GetChartData` uses a nonstandard timestamp, so we do not use it.
13. **Text.** TSETMC stores Arabic letters (ي ك). We normalise returned text to Persian letters.
14. **Today's end-of-day table is empty during the session.** `GetInstrmentsHistoryInDay/{today}` returns nothing until the close, which breaks any join that relies on it (instrumentId to insCode for queues and real-money rankings). We build that mapping from the newest published day instead; the ids are stable.
15. **Overloaded upstream.** The exchange servers occasionally answer 502/503 under load. Requests are retried with backoff; a persistent failure is reported as an overloaded server, not as an IP problem.
16. **Codal.** The documented `codal.ir` pages are JavaScript templates; the working source is the public search API (`search.codal.ir/api/search/v2/q`). Its relative PDF link (`DownloadFile.aspx?...`) resolves against the site root, not `/Reports/`.
17. **Payload sizes.** A day of ticks is about 3 MB, order-book history 3 MB, supervisor messages for one symbol 3.5 MB, full daily price history 1.5 MB. Responses are cached for a short time and summarised before they reach the model.

## Commodity and energy exchanges (IME, Iran Energy Exchange)

Investigated for issue #9 on 5 November 2026 (data of the 4 November session, 1405/08/13), from an in-Iran proxy, **with no account, key, cookie, captcha or session trick**: every endpoint below answered a plain browser-like `User-Agent`. The two exchanges publish through their own sites, not through TSETMC, so two tools read them directly: `commodity_market` (IME) and `energy_market` (Iran Energy Exchange). Their *listed* instruments (certificates, forwards, funds, futures) are already in TSETMC's feed; see the last subsection.

| Source | Base URL | Request | Used for |
|---|---|---|---|
| IME ASMX services | `https://www.ime.co.ir/SubSystems/IME/Services/Home/imedata.asmx/<Method>` | `POST`, JSON body, `Content-Type: application/json; charset=utf-8`; the answer is `{"d": "<a JSON array as a string>"}` | `commodity_market` |
| Iran Energy Exchange web API | `https://webapi.iee.ir/api/<Controller>/<Action>?Lang=fa` | `GET`; the answer is `{"results": [...], "pagedMetaData": [{"totalCount", "hasNext", ...}], "isSuccess", "isFailed", "errors"}` | `energy_market` |
| TSETMC `Energy` API | `https://cdn.tsetmc.com/api/Energy/<Method>/...` | `GET` | verified, not used (same auctions, see below) |

All three are the services the exchanges' own pages call (found in `ime.co.ir`'s home page, in the React bundle of `iee.ir` and in the bundle of `main.tsetmc.com`). `robots.txt` allows them (`ime.co.ir` disallows only `/DownloadHandler.ashx`, `iee.ir` nothing). Dates are **Jalali strings** (`1405/08/13`) on both; IME's parameters are even named `GregorianFromDate`/`GregorianToDate`, and a real Gregorian value is an HTTP 500. The client converts.

### IME: physical market (`www.ime.co.ir`)

| Method (body besides `"Language":8`) | Returns | Size / latency | Used by |
|---|---|---|---|
| `GetAmareMoamelatList` `{"fari":false,"GregorianFromDate":"1405/08/13","GregorianToDate":"1405/08/13","MainCat":0,"Cat":0,"SubCat":0,"Producer":0}` | one row per offer or contract, 34 fields (below) | 181 rows, 183 KB, 0.3 s for one session; 1,184 rows, 1.2 MB, 0.7 s for five; Thursday: `[]` | `view="trades"` |
| `GetHomeFizikiWithDateGrid` `{"GregorianFromDate","GregorianToDate"}` | by ring: `{"ID":1,"xRingName":"صنعتی","Value":109469008.0,"Volume":129433.0,"OfferVolume":295659.0}` | 3 rows | `view="summary"` |
| `GetHomeNamaWithDateGrid` (same body) | by market: `{"name":"بازار فيزيکي","Id":"1","TradeValue":180697354.0,"TradeVolume":181729.0}` (physical, futures, options, financial, certificates) | 5 rows | `view="summary"` |
| `GetHajmArzeshMoamelatDateGrid` (same body) | one row per session: `{"TradeDate":"1405/08/13","TradeValue":180697354.0,"TradeVolume":181729.0}` | about 80 B per day | `view="summary"`, latest-session lookup |
| `GetHomeExchangeRateData` | the dollar rate on the home page: `{"Tarikh":"1405/08/13","Nerkh":1878192.0,"Sharh":"دلار"}`, newest two days | 150 B | `view="summary"` |
| `GetMainGroups`, `GetCatGroups` `{"MainCat":1}`, `GetSubCatGroups`, `GetProducers` | filter dictionaries (`{"Name":"صنعتی","code":1}`) | small | group ids hard-coded in `commodity.MAIN_GROUPS` |
| `GetHomeSaderatiGridWithDate`, `GetHomeNesbateMoameleBeArzeFizikiChartData`, `GetHomeArzeTaghiratChartData` | export hall (Kish) value and volume; ring totals over a range; offered volume by day | small | not used |

`GetAmareMoamelatList` fields (all kept): `GoodsName`, `Symbol` (`HAAL-PS10000-00`), `ProducerName`, `ArzehKonandeh` (supplier), `Talar` (hall), `ContractType` (`نقدی`, `سلف`, `نسیه`, each also `(مچینگ)`), `Tasvieh`, `PacketName`, `cBrokerSpcName`, `date`, `DeliveryDate`, `SettlementDate`, `Warehouse`, `Unit`, `Currency`, `Price` (weighted-average close; null if nothing traded), `MinPrice`, `MaxPrice`, `ArzeBasePrice`, `arze` (offered volume), `taghaza` (demand), `Quantity` (traded), `TotalPrice`, `Category`, `arzehPk`, plus `MinPrice1`, `Price1`, `arzeMinPrice`, `taghazavoroudi`, `taghazaMaxPrice`, `xTalarReportPK`, `bArzehRadifTarSarresid`, `ModeDescription`, `MethodDescription` that the tools do not use.

**Units** (IME states some, the rest is derived and checked). `Quantity`, `arze`, `taghaza` are **tons**: `Unit` is `تن` on all 1,184 rows of five sessions. `TotalPrice` is **thousand rial** (the page's own column header «ارزش معامله (هزارریال)»). `Price` is **rial per kilogram**: `TotalPrice = Price x Quantity` held to 2e-5 on all 1,045 traded rows, which is only possible if tons x 1,000 kg x price / 1,000 gives thousand rial; the Energy Exchange states the same convention (below). The roll-ups are **million rial** (headers «ارزش(میلیون ریال)») and their volumes are tons: the three rings' `OfferVolume` add to 414,056 t, IME's own headline that morning («۴۱۴ هزار تن محصول روی میز فروش می‌رود»).

Quirks: the list excludes the sub-market (`"fari":true` returns it with a thinner field set: no prices) and its value reached about 85% of the roll-up on 4 November (153.8 vs 180.7 trillion rial), so the two are never added; the main groups partition the list exactly (181 rows = 129 in group 1 + 52 in group 3; groups 2, 4, 5, 6 and 7 were empty that day); `arze` is 0 for matching (`مچینگ`) contracts; untraded offers have `Price` null and `Quantity` 0 (139 of 1,184 rows). IME's home page refreshes its financial and futures grids every 30 s; nothing here is faster than that.

### Iran Energy Exchange (`webapi.iee.ir`)

The site `iee.ir` redirects to `newsite.iee.ir`; its API host is `webapi.iee.ir` (certificate `*.iee.ir`, valid until 20 November 2026). The older names do not work: `irenex.ir` presents the `*.iee.ir` certificate (TLS verification fails: wrong principal) and answers 404 at `/`, `ienx.ir` fails the TLS handshake.

| Endpoint (`?Lang=fa` on all) | Returns | Size / latency | Used by |
|---|---|---|---|
| `PhysicalMarket/GetTradesStatistics?PageNumber=1&PageSize=1000&FromDate=1405/08/13&ToDate=1405/08/13` | one row per auction with its result, 32 fields: `auctionIdn`, `energySymbol`, `instrumentDisplayName`, `auctionDesc`, `targetMarketName`, `destination`, `supplierName`, `brokerName`, `tradeDateShamsi`, `auctionDateShamsi` (`1405/08/13 - 12:40`), `totalValueRials` (string, `10,800,000,000`), `totalTradedVolume`, `volumeUnitTitle`, `orderBuyTradedVolume`, `auctionVolume`, `basePrice`, `tradedAveragePrice`, `tradeMinPrice`, `tradeMaxPrice`, `priceUnitTitle`, `tradeTypeTitle`, `contractType`, `clearingType`, `kiloWattHours` ... All numbers are strings with thousands separators. Filters by trade date, so a forward auctioned on 12 Aban but traded on 13 Aban is in the 13th. | 18 rows, 21 KB, 1.2 s; seven days: 117 rows, 136 KB, 1.6 s | `view="trades"` |
| `PowerMarket/GetPowerTradesStatistics` (same query) | the same record for electricity (`volumeUnitTitle` is kW of capacity, `kiloWattHours` the energy) | 7 rows over 13 days, 0.5 s | `view="trades"` |
| `PhysicalMarket/GetPhysicalMarketOffersAuction?PageNumber=1&PageSize=50` | announced physical auctions: `auctionIdn`, `instrumentDisplayName`, `auctionVolume` (`1,000 تن`), `auctionVolumeTooltip`, `basePrice` (the exchange's wording), `basePriceTooltip` (the number), `auctionDateShamsi`, `auctionTime`, `supplier`, `referencePrice`, `tradeType`, `targetMarketName`, `stepTitle` | 10 offers, 6 KB, 0.2 s | `view="offers"` |
| `PowerMarket/GetPowerMarketAuctionAnnouncements?PageNumber=1&PageSize=10` | electricity announcements with terms of delivery and payment; **an archive of every auction since the start** (9,626 records, newest first; `auctionState` is `برگزار شده` for held ones, empty for coming ones) | 10 rows, 72 KB, 5 s (the cost is mostly fixed); 40 rows, 252 KB, 4.3 s | `view="offers"` |
| `PhysicalMarket/GetMarketAuctionDetails/{auctionIdn}` (the `PowerMarket/` twin returns the same; an unknown id is HTTP 400) | one auction: terms, `volumeUnitTitle`, `volumeUnitTitlePrice`, `convertPriceVolume`, `buyOrders` / `saleOrders` (price levels with `totalQuantity`, `price`, `orderCount`) | 2 KB, 0.2 s | `view="auction"` |
| `PhysicalMarket/GetMarketAuctionDetailsTradeOnDay/{auctionIdn}` | executed trades: `tradedQuantity`, `tradedPrice`, `tradedValue` (rial), `priceOnVolumeUnit` (`ریال/کیلوگرم`) | 0.6 KB per 1 trade | `view="auction"` |
| `Home/GetTodayMarketsValues`, `PhysicalMarket/GetPhysicalMarketAtAGlance`, `PowerMarket/GetPowerMarketAtAGlance` | market state (`بسته` closed) and today's totals; `tradedValue` is million rial. Zero on a closed day | 0.4 to 1.3 KB | `view="overview"` |

Not used: `PhysicalMarket/GetPhysicalMarketAuctionAnnouncements` (25 s for 3 rows), and about 100 other endpoints the site calls (listings and prospectuses, news, B2B producer directory, `OilPrice/GetHydroPrices`, `Report/GetPowerMarketMonthlyPrice`, `DerivativeMarket/*`, `OtherTradableSecurities/*` statistics); the listed derivatives and certificates are already in TSETMC's feed.

**Units**, which the exchange spells out in the detail record (`volumeUnitTitlePrice` `کیلوگرم`, `convertPriceVolume` 1000, `priceOnVolumeUnit` `ریال/کیلوگرم`) and which reconcile with `totalValueRials` on every row of 4 November and the week before it:

| Volume unit | Price unit | Price is | Value (`totalValueRials`) = |
|---|---|---|---|
| تن (tonne) | ریال | rial per **kilogram** | tons x 1,000 x price (60 t at 180,000: 10,800,000,000) |
| تن | دلار | US dollars per **tonne** | tons x price x the exchange's dollar rate (2,000 t at 598.4: 2,243,334,579,200 = x 1,874,444, the rate IME published for the previous day, 1405/08/12) |
| مترمکعب | دلار | US dollars per cubic meter | volume x price x dollar rate |
| لیتر | ریال | rial per liter | liters x price |
| تن | پریمیوم دلاری | a premium (negative = discount) on the reference price | the exchange's figure; not derivable from the row |
| کیلووات در هر ساعت از دوره مصرف در دوره تحویل | ریال | rial per **kWh** | `kiloWattHours` x price (9,000 kW for a 168-hour week = 1,512,000 kWh; x 4,500 = 6,804,000,000) |

The day's 18 physical auctions add up to 22,620,322,449,686 rial (12 traded, 6 without a trade), the figure `energy_market` reports.

### TSETMC `Energy` endpoints (verified, not wired)

Found in the bundle of `main.tsetmc.com` (the pages «بورس انرژی»). They describe the **same auctions with the same ids** (`idn` = `auctionIdn`: auction 96520 shows 60 t at 180,000 on both). They were left unwired because the Energy Exchange's own API is richer (physical rings, units, trades per day) and one host is enough to rate-limit.

| Endpoint | Observed |
|---|---|
| `Energy/GetGetAuctionListItemByType/{active\|ready\|ended\|mazad}/{top}/{isDPE}` | `auctionListItem`; **only** `isDPE` 2 (13 `ended` bond price-discovery auctions of 2019 to 2021), 4 (green electricity, 5 `ready`) and 5 (free electricity, 3 `ready`) returned rows; 0, 1, 3, 6 to 11 and -1 are empty for every type, so the physical rings cannot be listed this way |
| `Energy/GetAuctionById/{id}` | 4 to 10 KB; 56 fields incl. `auctionVol`, `volUnitTitle`, `priceUnitTitle`, `baseVolUnitTitle` (`كيلوگرم`), `stepTitle`; `idn` and `instrumentID` come back 0. It also answers for physical-ring auctions that the list below does not show (96520, liquid nitrogen) |
| `Energy/GetAuctionOrderById/{id}/{A\|V}` | `A` = buy orders (page header «سفارش خرید»), `V` = sell orders: `[{"orderCount":3,"orderPrice":6.5,"orderQuantity":4000.0}]` |
| `Energy/GetAuctionTradeById/{id}`, `Energy/GetInstrumentTradeByAuctionId/{id}` | `[{"tradeDate":"2026-11-04T12:52:00.130","tradedPrice":180000.0,"tradedQuantity":60.0}]` |
| `Energy/GetAuctionOverview/0`, `Energy/GetPowerOverview/{60\|62\|64\|69}` | auction totals (`totalCount`, `totalValue`, all 0 on a closed day); per-flow electricity totals (`f60_MarketActivityQTotCap` 476,929,008,000, `f60_MarketActivityZTotTran` 6) and `marketStateTitle` `بسته`; flows 6 and 71 answer HTTP 500 |
| `BestLimits/GetBestLimitsTopPower/{EnergyPowerBuy\|EnergyPowerSell}/{flow}/{top}/{loadType}` | electricity bids and asks (`pMeDem`, `qTitMeDem`, `title` `بارپايه ماهانه 14050901`); the one list `top_lists` still lists as not wired |
| `MarketData/GetContractBreakDownByFlow/{flow}` | ignores the flow: returns the Tehran Bourse breakdown for 6 and 7 alike. Useless here |

### What TSETMC already carries for both exchanges

`ClosingPrice/GetMarketWatch` (3,680 instruments on 5 November) holds the exchange-traded boards: **flow 7** (111 rows: standard forwards `سلف` type 308, 38 rows; commodity funds type 380, 65 rows; saffron certificates type 701, 8 rows) and **flow 6** (57 rows: parallel electricity and hydrocarbon forwards `سلف موازی` type 200, 32 rows; a capacity certificate 201; energy funds 315; base-load day/week/month products 801 to 804). `market_watch(security_type="commodity"|"energy")` and `top_lists` (groups `commodity` and `energy`, flows 6, 7, 60, 64, 67, 68, 69) reach them; the two new tools do not duplicate them.

### Tried and not used

| What | Result |
|---|---|
| `irenex.ir`, `ienx.ir` | TLS wrong principal / handshake failure; 404 at `/` (see above) |
| `ime.co.ir/.../MarketTotal.asmx` (`auction-total-report.html`) | answers JSON with embedded **HTML** tables and **stale data** (dated 1403/05/03, two years old) |
| `GetHomeMaliGrid`, `GetHomeAtiGrid` (IME financial and futures grids) | `[]` when probed (5 November, closed day) |
| `GetHomeFizikiContractChartData` | HTTP 500 for the arguments the page builds |
| `gold.ime.co.ir`, `silver.ime.co.ir`, `cdc.ime.co.ir` (certificate portals) | single-page apps (2.6 KB shell); not examined further |
| `GetAmareMoamelatList` with `"fari":true` | the sub-market: no prices, not offered by the tool |

### Cadence, hours and limits observed

IME and the Energy Exchange publish after the session; both are closed Thursday and Friday (IME's list for Thursday 1405/08/14 is `[]`, the Energy Exchange's overview says `بسته` and shows zeros), the next offers announced on Thursday are for Saturday. The sites poll their own tables every 30 s (IME's financial and futures grids), every 1.5 s (the Energy Exchange's at-a-glance widgets) and every 2 to 4 minutes (TSETMC's energy pages), so the tools cache for 30 s to 2 minutes. About 150 API requests to the three hosts (one after another, 1 to 2 s apart; plus about 160 static script files of the sites) produced no HTTP 429 and no 403; the client's existing handling (retry with back-off, a 60 s cool-down per host after a 429) applies unchanged. The slowest calls are the Energy Exchange's power announcements (about 5 s) and its physical announcements (25 s, unused).

## Not covered (yet)

Option Greeks and implied volatility (`option_chain` gives moneyness, intrinsic and time value only), index weights (the exchange publishes none; `index_constituents` gives each stock's effect in index points instead), the Persian public-holiday calendar (holidays are not modelled; the commodity tools simply report an empty session), IME's sub-market (`"fari":true`) and its gold, silver and certificate portals, TSETMC's `Energy` auction endpoints and electricity bids (`GetBestLimitsTopPower`), and the Energy Exchange's derivative and certificate statistics (their instruments are in `top_lists`).
