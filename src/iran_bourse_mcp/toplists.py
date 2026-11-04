"""The exchange's own «برترین‌ها» (best-of) lists, shaped for agents.

tsetmc.com's home page is a wall of small ranked tables. All of them come from four response families, which
this module knows by name, so an agent asks for ``price_gainers`` or ``largest_bids`` instead of guessing URLs:

* ``trade``   ``GET /ClosingPrice/GetTradeTop/{type}/{flow}/{top}``  -> ``tradeTop`` (prices, trades, volume, value)
* ``limits``  ``GET /BestLimits/GetBestLimitsTop/{type}/{flow}/{top}`` -> ``bestLimitsTop`` (largest best bids / asks)
* ``cap``     ``GET /ClosingPrice/GetMarketCap/{Top|Btm}/{flow}/{top}`` -> ``marketCap`` (market-value change)
* ``sectors`` ``GET /MarketData/GetSectorTop/{n}``                     -> ``sectorTop`` (industries by traded value)

The exchange ranks every list itself, so rows keep the order it publishes; ``sorted_by`` says on which column
(only where verified against live data). Each list lives in a *flow* (market segment): 1 Bourse, 2 Fara Bourse,
3 derivatives, 6 energy, 7 commodity, 11 / 12 first / second market of the Bourse (boards N1 / N2), 27 / 28 / 29 Fara
base market yellow / orange / red (boards P1 / C1 / L1). A list only answers for the flows the site itself uses.

The functions here are pure: ``resolve_top_list`` checks the arguments and names the URL, the caller fetches it,
``shape_top_list`` turns the raw rows into stable keys. Problems raise ``ValueError`` with advice an agent can act on.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any

from .dates import fmt_date, jdate
from .market import MARKET_BY_FLOW
from .shape import _f, _i, _safe_div, pct_change
from .text import clean

MAX_LIMIT = 300
DEFAULT_LIMIT = 20

FLOW_TITLES: dict[int, str] = {
    **MARKET_BY_FLOW,
    11: "بازار اول بورس", 12: "بازار دوم بورس",
    25: "فرابورس - بازار نوآفرین-رشد (تابلوی V1)", 26: "فرابورس - تابلوی W1",
    27: "فرابورس - بازار پایه زرد (P1)", 28: "فرابورس - بازار پایه نارنجی (C1)", 29: "فرابورس - بازار پایه قرمز (L1)",
    60: "بازار برق آزاد", 64: "بازار مصرف‌کنندگان بزرگ برق", 67: "آتی انرژی", 68: "گواهی سپرده حامل‌های انرژی", 69: "بازار برق سبز",
}
FLOW_WORDS = {
    "bourse": 1, "tse": 1, "tehran": 1, "fara": 2, "farabourse": 2, "ifb": 2, "derivatives": 3, "derivative": 3,
    "energy": 6, "commodity": 7, "ime": 7, "market1": 11, "firstmarket": 11, "market2": 12, "secondmarket": 12,
}

FAMILY_TRADE, FAMILY_LIMITS, FAMILY_CAP, FAMILY_SECTORS = "trade", "limits", "cap", "sectors"
_ENDPOINTS = {  # family -> (path template, key of the rows in the JSON answer)
    FAMILY_TRADE: ("/ClosingPrice/GetTradeTop/{type}/{flow}/{top}", "tradeTop"),
    FAMILY_LIMITS: ("/BestLimits/GetBestLimitsTop/{type}/{flow}/{top}", "bestLimitsTop"),
    FAMILY_CAP: ("/ClosingPrice/GetMarketCap/{type}/{flow}/{top}", "marketCap"),
    FAMILY_SECTORS: ("/MarketData/GetSectorTop/{top}", "sectorTop"),
}

# ----------------------------------------------------------------------------------------------- columns
_IDENT = ("rank", "symbol", "name", "ins_code")
_PRICES = ("yesterday", "close", "close_pct", "last", "last_pct", "low", "high", "trades", "volume", "value")
COLS_RANKED = (*_IDENT, "close", "trades", "volume", "value", "market_cap")  # value / volume leaders: the feed omits the day's prices
COLS_MOVERS = (*_IDENT, *_PRICES)
COLS_GAP = (*_IDENT, "yesterday", "close", "last", "last_vs_close_pct", "last_pct", "low", "high", "trades", "volume", "value")
COLS_FUND = (*COLS_MOVERS, "nav", "nav_premium_pct")
COLS_FUTURE = (*COLS_MOVERS, "open_interest")
COLS_OPTION = (*COLS_FUTURE, "notional_value")
COLS_LIMITS = (*_IDENT, "side", "price", "volume", "orders", "value", "counter_volume", "one_sided")
COLS_CAP = (*_IDENT, "market_cap", "market_cap_yesterday", "change", "change_pct")
COLS_SECTOR = ("rank", "sector_code", "sector", "market_cap", "trades", "volume", "value", "value_share_pct")
COLUMN_SETS = {  # the catalogue names a list's columns by set, so 69 entries do not repeat them
    "ranked": COLS_RANKED, "movers": COLS_MOVERS, "gap": COLS_GAP, "fund": COLS_FUND, "future": COLS_FUTURE,
    "option": COLS_OPTION, "limits": COLS_LIMITS, "cap": COLS_CAP, "sector": COLS_SECTOR,
}
_SET_OF = {columns: name for name, columns in COLUMN_SETS.items()}


@dataclass(frozen=True)
class ListDef:
    name: str
    group: str
    family: str
    types: tuple[tuple[int, str], ...]  # (flow, exchange type name) pairs this list answers for
    title_fa: str
    title_en: str
    columns: tuple[str, ...]
    sort: str | None = None  # column the exchange sorts by, only where verified live ("close_pct desc")
    side: str | None = None  # limits family: "buy" or "sell"
    note: str = ""
    aliases: tuple[str, ...] = ()

    @property
    def flows(self) -> tuple[int, ...]:
        return tuple(flow for flow, _ in self.types)

    def site_type(self, flow: int | None) -> str:
        for f, t in self.types:
            if f == flow:
                return t
        return self.types[0][1]


def _d(name: str, group: str, family: str, flows: str | dict[int, str], fa: str, en: str, columns: tuple[str, ...], **kw: Any) -> ListDef:
    """``flows`` is either {flow: type} or "Type:1,2,11" (one exchange type for several flows)."""
    if isinstance(flows, str):
        site_type, _, ids = flows.partition(":")
        pairs = tuple((int(i), site_type) for i in ids.split(",")) if ids else ((0, site_type),)
    else:
        pairs = tuple(flows.items())
    return ListDef(name, group, family, pairs, fa, en, columns, **kw)


T, L, C = FAMILY_TRADE, FAMILY_LIMITS, FAMILY_CAP
CATALOGUE: tuple[ListDef, ...] = (
    # --- shares: Bourse (1), Fara Bourse (2) and the sub-markets
    _d("most_active", "stocks", T, "MostVisited:1,2,3,11,12,25,26,27,28,29", "نمادهای پرتراکنش", "Most trades (the busiest symbols by number of trades); flow 3 = futures", COLS_MOVERS,
       sort="trades desc", aliases=("most_visited", "busiest")),
    _d("top_value", "stocks", T, "MostTradedValue:1,2,11,12", "بیشترین ارزش معامله", "Largest traded value (rial); includes funds and bonds on the main market", COLS_RANKED, sort="value desc",
       note="The exchange sends only the close, counts and market value for this list (no last price or day range)."),
    _d("top_volume", "stocks", T, "MostTradedVolume:1,2,11,12", "بیشترین حجم معامله", "Largest traded volume (shares)", COLS_RANKED, sort="volume desc"),
    _d("price_gainers", "stocks", T, "PClosingTop:1,2,11,12", "بیشترین افزایش قیمت", "Biggest rise of the closing price vs yesterday", COLS_MOVERS, sort="close_pct desc", aliases=("gainers",)),
    _d("price_losers", "stocks", T, "PClosingBtm:1,2,11,12", "بیشترین کاهش قیمت", "Biggest fall of the closing price vs yesterday", COLS_MOVERS, sort="close_pct asc", aliases=("losers",)),
    _d("last_above_close", "stocks", T, "TwoPriceDiffTop:1,2,11,12", "افزایش آخرین قیمت به پایانی", "Last trade price furthest above the closing price (late buying pressure)", COLS_GAP,
       sort="last_vs_close_pct desc"),
    _d("last_below_close", "stocks", T, "TwoPriceDiffBtm:1,2", "کاهش آخرین قیمت به پایانی", "Last trade price furthest below the closing price (late selling pressure)", COLS_GAP,
       sort="last_vs_close_pct asc"),
    _d("rights", "stocks", T, "Priority:1,2,11,12", "حق تقدم", "Rights (حق تقدم) traded today", COLS_MOVERS, note="Usually 1 to 8 symbols; empty when no rights issue is open."),
    _d("new_instruments", "stocks", T, "Bonds:1,2", "ابزارهای نوین مالی", "New financial instruments board", COLS_MOVERS, note="Often empty."),
    _d("block_trades", "stocks", T, {1: "Block", 11: "Block", 12: "Block", 2: "BlockOTC"}, "معاملات عمده", "Block trades (symbols with a suffix 4); one row per symbol, aggregated over the day", COLS_MOVERS,
       sort="close_pct desc", aliases=("block",), note="Rows are the block-market twins of a share (suffix 4), so volume and value are the day's block deals."),
    _d("closing_price_only", "stocks", T, {1: "TAL", 11: "TAL", 12: "TAL", 2: "TALOTC"}, "معاملات پایانی TAL", "Closing-price-only (TAL, suffix 3) trades", COLS_MOVERS, sort="close_pct desc", aliases=("tal",),
       note="TAL twins trade only at the closing price. The tool top_movers hides them; this list shows them."),
    _d("professional_investors", "stocks", T, "ProInvest:1", "بازار سرمایه‌گذاری حرفه‌ای", "Professional investors' market", COLS_MOVERS, aliases=("pro_invest",)),
    _d("fara_stocks_active", "stocks", T, "TCS:2", "سهام - نمادهای پرتراکنش", "Fara Bourse: busiest shares only", COLS_MOVERS),
    _d("fara_debt_active", "debt", T, "TCSDebt:2", "اوراق بدهی فرابورس", "Fara Bourse: busiest debt papers (sukuk, murabaha)", COLS_MOVERS),
    # --- funds
    _d("etf_trades", "etf", T, "ETF:1,2", "معاملات صندوق‌های قابل معامله", "Exchange-traded funds by number of trades", COLS_FUND, sort="trades desc", aliases=("etf",)),
    _d("etf_top_volume", "etf", T, "MostTradedETF:1,2", "بیشترین حجم معاملات صندوق‌ها", "ETFs by traded volume", COLS_FUND, sort="volume desc"),
    _d("etf_gainers", "etf", T, "PClosingTopETF:1,2", "بیشترین افزایش قیمت صندوق‌ها", "ETFs with the biggest closing-price rise", COLS_FUND, sort="close_pct desc"),
    _d("etf_losers", "etf", T, "PClosingBtmETF:1,2", "بیشترین کاهش قیمت صندوق‌ها", "ETFs with the biggest closing-price fall", COLS_FUND, sort="close_pct asc"),
    # --- derivatives (flow 3 is shared; the Fara Bourse variants have the _fara suffix)
    _d("options_active", "derivatives", T, "FutureOption:3", "معاملات اختیار معامله", "Options by number of trades (Bourse)", COLS_OPTION, sort="trades desc"),
    _d("option_calls", "derivatives", T, "OptionCall:3", "اختیار خرید با بیشترین حجم معامله", "Call options (اختیار خرید) by traded volume (Bourse)", COLS_OPTION, sort="volume desc"),
    _d("option_puts", "derivatives", T, "OptionPut:3", "اختیار فروش با بیشترین حجم معامله", "Put options (اختیار فروش) by traded volume (Bourse)", COLS_OPTION, sort="volume desc"),
    _d("option_open_interest", "derivatives", T, "OptionOP:3", "اختیار با بیشترین موقعیت باز", "Options with the largest open interest (Bourse)", COLS_OPTION, sort="open_interest desc"),
    _d("future_open_interest", "derivatives", T, "FutureOP:3", "بیشترین موقعیت باز آتی", "Futures with the largest open interest (Bourse)", COLS_FUTURE, sort="open_interest desc"),
    _d("consequential_puts_active", "derivatives", T, "FutureOptionConsequential:3", "معاملات اختیار فروش تبعی", "Consequential put options by trades (Bourse)", COLS_OPTION, note="Often empty."),
    _d("debt_papers_active", "debt", T, "FutureBedehi:3", "معاملات اوراق بدهی", "Debt papers (sukuk, murabaha) listed with the derivatives, by trades (Bourse)", COLS_MOVERS, sort="trades desc"),
    _d("options_active_fara", "derivatives", T, "FutureOptionOTC:3", "معاملات اختیار معامله فرابورس", "Options by number of trades (Fara Bourse)", COLS_OPTION),
    _d("option_calls_fara", "derivatives", T, "OptionCallOTC:3", "اختیار خرید فرابورس با بیشترین حجم", "Call options by traded volume (Fara Bourse)", COLS_OPTION, sort="volume desc"),
    _d("option_puts_fara", "derivatives", T, "OptionPutOTC:3", "اختیار فروش فرابورس با بیشترین حجم", "Put options by traded volume (Fara Bourse)", COLS_OPTION, sort="volume desc"),
    _d("option_open_interest_fara", "derivatives", T, "OptionOPOTC:3", "اختیار فرابورس با بیشترین موقعیت باز", "Options with the largest open interest (Fara Bourse)", COLS_OPTION, sort="open_interest desc"),
    _d("future_open_interest_fara", "derivatives", T, "FutureOPOTC:3", "بیشترین موقعیت باز آتی فرابورس", "Futures with the largest open interest (Fara Bourse)", COLS_FUTURE, note="Often empty."),
    _d("futures_active_fara", "derivatives", T, "FutureTradeOTC:3", "معاملات آتی فرابورس", "Futures by number of trades (Fara Bourse)", COLS_FUTURE, note="Often empty."),
    _d("consequential_puts_active_fara", "derivatives", T, "FutureOptionConsequentialOTC:3", "معاملات اختیار فروش تبعی فرابورس", "Consequential put options by trades (Fara Bourse)", COLS_OPTION, note="Often empty."),
    _d("debt_papers_active_fara", "debt", T, "FutureBedehiOTC:3", "معاملات اوراق بدهی فرابورس", "Debt papers listed with the derivatives, by trades (Fara Bourse)", COLS_MOVERS),
    # --- energy exchange
    _d("power_contracts", "energy", T, "EnergyPowerTrade:6,60,64,69", "فهرست معاملات برق", "Electricity contracts traded (flow 6 day-ahead, 60 free market, 64 large consumers, 69 green)", COLS_MOVERS,
       note="`symbol` is the contract title (e.g. بارپایه روزانه 14050817); prices are rial per kWh."),
    _d("energy_salaf", "energy", T, "EnergySalaf:6", "سلف موازی استاندارد - قراردادهای فعال", "Standard parallel forward (salaf) contracts, active", COLS_MOVERS),
    _d("energy_salaf_expired", "energy", T, "EnergySalafExpired:6", "سلف موازی استاندارد - منقضی‌شده", "Standard parallel forward (salaf) contracts, expired", COLS_MOVERS),
    _d("energy_etf", "energy", T, "EETF:6", "صندوق‌های سرمایه‌گذاری قابل معامله انرژی", "Energy exchange-traded funds", COLS_MOVERS),
    _d("capacity_certificates", "energy", T, "IRBZ:6", "اوراق گواهی ظرفیت", "Capacity certificates", COLS_MOVERS),
    _d("saving_certificates", "energy", T, "IRBS:6", "گواهی صرفه‌جویی انرژی - فعال", "Energy-saving certificates, active", COLS_MOVERS),
    _d("saving_certificates_expired", "energy", T, "IRBSExpired:6", "گواهی صرفه‌جویی انرژی - منقضی‌شده", "Energy-saving certificates, expired", COLS_MOVERS),
    _d("energy_futures", "energy", T, "EnergyFuture:67", "قراردادهای آتی انرژی", "Energy futures (settlement prices are in `close`)", COLS_MOVERS, note="`close` is the settlement price; contracts without trades still show it."),
    _d("energy_deposit_certificates", "energy", T, "EngDepContinuous:68", "گواهی سپرده حامل‌های انرژی - فعال", "Energy-carrier deposit certificates, active", COLS_MOVERS),
    _d("energy_deposit_certificates_expired", "energy", T, "EngDepContinuousExpired:68", "گواهی سپرده حامل‌های انرژی - منقضی‌شده", "Energy-carrier deposit certificates, expired", COLS_MOVERS),
    # --- commodity exchange
    _d("standard_salaf", "commodity", T, "StandardSalaf:7", "سلف موازی استاندارد - قراردادهای فعال", "Standard parallel forwards on commodities, active", COLS_MOVERS),
    _d("standard_salaf_expired", "commodity", T, "StandardSalafExpired:7", "سلف موازی استاندارد - منقضی‌شده", "Standard parallel forwards on commodities, expired", COLS_MOVERS),
    _d("gold_funds", "commodity", T, "CommodityFundGold:7", "صندوق‌های کالایی مبتنی بر طلا", "Gold commodity funds", COLS_MOVERS),
    _d("silver_funds", "commodity", T, "CommodityFundSilver:7", "صندوق‌های کالایی مبتنی بر نقره", "Silver commodity funds", COLS_MOVERS),
    _d("agriculture_funds", "commodity", T, "CommodityFundAgriculture:7", "صندوق‌های کالایی کشاورزی", "Agricultural commodity funds", COLS_MOVERS),
    _d("commodity_certificates", "commodity", T, "CommodityMercantileContinuous:7", "گواهی سپرده کالایی پیوسته", "Commodity deposit certificates, continuous trading", COLS_MOVERS),
    _d("commodity_certificates_discontinuous", "commodity", T, "CommodityMercantileDiscontinuous:7", "گواهی سپرده کالایی ناپیوسته", "Commodity deposit certificates, discontinuous trading", COLS_MOVERS, note="Often empty."),
    # --- order-book extremes (BestLimits)
    _d("largest_bids", "queues", L, "Buy:1,2", "برترین تقاضا", "Largest best bids by value right now (ETFs and shares): the biggest buy queues", COLS_LIMITS, sort="value desc", side="buy",
       aliases=("buy_queues", "demand"), note="Best bid only; `one_sided` is true when nobody offers at all, which is what a buy queue (صف خرید) looks like."),
    _d("largest_asks", "queues", L, "Sell:1,2", "برترین عرضه", "Largest best asks by value right now: the biggest sell queues", COLS_LIMITS, sort="value desc", side="sell",
       aliases=("sell_queues", "supply"), note="Best ask only; `one_sided` is true when nobody bids at all, which is what a sell queue (صف فروش) looks like."),
    _d("pro_largest_bids", "queues", L, "ProInvestBuy:1", "تقاضای بازار سرمایه‌گذاری حرفه‌ای", "Largest best bids in the professional investors' market", COLS_LIMITS, side="buy"),
    _d("pro_largest_asks", "queues", L, "ProInvestSell:1", "عرضه بازار سرمایه‌گذاری حرفه‌ای", "Largest best asks in the professional investors' market", COLS_LIMITS, side="sell"),
    _d("future_bids", "queues", L, "FutureBuy:3", "تقاضای آتی", "Largest best bids on futures", COLS_LIMITS, side="buy"),
    _d("future_asks", "queues", L, "FutureSell:3", "عرضه آتی", "Largest best asks on futures", COLS_LIMITS, side="sell"),
    _d("option_bids", "queues", L, "OptionBuy:3", "تقاضای اختیار معامله", "Largest best bids on options (Bourse)", COLS_LIMITS, side="buy"),
    _d("option_asks", "queues", L, "OptionSell:3", "عرضه اختیار معامله", "Largest best asks on options (Bourse)", COLS_LIMITS, side="sell"),
    _d("consequential_put_bids", "queues", L, "OptionConsequentialBuy:3", "تقاضای اختیار فروش تبعی", "Largest best bids on consequential puts (Bourse)", COLS_LIMITS, side="buy", note="Often empty."),
    _d("consequential_put_asks", "queues", L, "OptionConsequentialSell:3", "عرضه اختیار فروش تبعی", "Largest best asks on consequential puts (Bourse)", COLS_LIMITS, side="sell", note="Often empty."),
    _d("debt_bids", "queues", L, "BedehiBuy:3", "تقاضای اوراق بدهی", "Largest best bids on debt papers (Bourse)", COLS_LIMITS, side="buy"),
    _d("debt_asks", "queues", L, "BedehiSell:3", "عرضه اوراق بدهی", "Largest best asks on debt papers (Bourse)", COLS_LIMITS, side="sell"),
    _d("option_bids_fara", "queues", L, "OptionOTCBuy:3", "تقاضای اختیار معامله فرابورس", "Largest best bids on options (Fara Bourse)", COLS_LIMITS, side="buy"),
    _d("option_asks_fara", "queues", L, "OptionOTCSell:3", "عرضه اختیار معامله فرابورس", "Largest best asks on options (Fara Bourse)", COLS_LIMITS, side="sell"),
    _d("debt_bids_fara", "queues", L, "BedehiBuyOTC:3", "تقاضای اوراق بدهی فرابورس", "Largest best bids on debt papers (Fara Bourse)", COLS_LIMITS, side="buy"),
    _d("debt_asks_fara", "queues", L, "BedehiSellOTC:3", "عرضه اوراق بدهی فرابورس", "Largest best asks on debt papers (Fara Bourse)", COLS_LIMITS, side="sell"),
    # --- market value and industries
    _d("market_cap_gainers", "market_cap", C, "Top:1,2", "افزایش ارزش بازار", "Biggest rise of market value (rial) vs yesterday", COLS_CAP, sort="change desc",
       note="Ranked by the rial amount of market value gained, so large caps lead; `change_pct` is relative."),
    _d("market_cap_losers", "market_cap", C, "Btm:1,2", "کاهش ارزش بازار", "Biggest fall of market value (rial) vs yesterday", COLS_CAP, sort="change asc"),
    _d("sectors_by_value", "sectors", FAMILY_SECTORS, {1: "SectorTop"}, "برترین گروه‌های صنعت", "Industries of the Bourse ranked by traded value", COLS_SECTOR, sort="value desc",
       aliases=("sectors", "industries"), note="Equity industries only (Bourse); value_share_pct is relative to the sum of the listed industries."),
)

_BY_NAME = {d.name: d for d in CATALOGUE}
GROUPS = tuple(dict.fromkeys(d.group for d in CATALOGUE))
NOT_AVAILABLE = (
    "FutureBuyOTC / FutureSellOTC (Fara futures bids and asks): the exchange answers HTTP 500 for them.",
    "EnergyPowerBuy / EnergyPowerSell (electricity bids and asks): a different endpoint (BestLimits/GetBestLimitsTopPower) that is not wired here.",
    "A list can legitimately be empty (HTTP 200, no rows) when nothing qualifies, e.g. block trades before the first deal of the day.",
)


def _norm(text: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text).casefold())


def _index() -> dict[str, list[tuple[ListDef, int]]]:
    index: dict[str, list[tuple[ListDef, int]]] = {}
    for d in CATALOGUE:
        for key in (d.name, *d.aliases):
            index.setdefault(_norm(key), []).append((d, d.types[0][0]))
        for flow, site_type in d.types:  # the exchange's own type name also works: PClosingTop, OptionOP ...
            index.setdefault(_norm(site_type), []).append((d, flow))
    return index


_INDEX = _index()


def parse_flow(flow: int | str | None) -> int | None:
    """``1``, ``'1'``, ``'bourse'``, ``'fara'``, ``'derivatives'`` ... -> flow id; ``None`` stays ``None``."""
    if flow is None or (isinstance(flow, str) and not flow.strip()):
        return None
    if isinstance(flow, bool):
        raise ValueError("flow must be a number such as 1 (Bourse) or 2 (Fara Bourse).")
    if isinstance(flow, int):
        return flow
    text = str(flow).strip()
    if text.lstrip("-").isdigit():
        return int(text)
    word = FLOW_WORDS.get(_norm(text))
    if word is None:
        raise ValueError(f"Unknown flow '{flow}'. Use a number (1 Bourse, 2 Fara Bourse, 3 derivatives, 7 commodity, 11 / 12 first / second Bourse market ...) or bourse, fara, derivatives, energy, commodity.")
    return word


def is_catalogue(list_name: str | None) -> bool:
    """True when the agent asked for the list of lists (``None``, empty, ``catalogue``, ``catalog``, ``list``, ``help``, ``all``)."""
    return list_name is None or _norm(list_name) in ("", "catalogue", "catalog", "list", "lists", "help", "all")


def flow_title(flow: int | None) -> str | None:
    return None if flow is None else FLOW_TITLES.get(flow)


def catalogue(flow: int | str | None = None, group: str | None = None) -> dict:
    """What can be asked: every list with its title, valid flows (the first is the default), ranking column and column set."""
    wanted = parse_flow(flow)
    if group is not None and group not in GROUPS:
        raise ValueError(f"Unknown group '{group}'. Groups: {', '.join(GROUPS)}.")
    lists = []
    for d in CATALOGUE:
        if (wanted is not None and wanted not in d.flows) or (group is not None and d.group != group):
            continue
        entry: dict[str, Any] = {
            "name": d.name, "group": d.group, "title": d.title_fa, "description": d.title_en,
            "flows": list(d.flows), "columns": _SET_OF[d.columns],
        }
        if d.sort:
            entry["sorted_by"] = d.sort
        if d.note:
            entry["note"] = d.note
        lists.append(entry)
    if wanted is not None and not lists:
        raise ValueError(f"No list answers for flow {wanted}. Flows with lists: {', '.join(str(f) for f in sorted({f for d in CATALOGUE for f in d.flows}))}.")
    used = dict.fromkeys(e["columns"] for e in lists)
    return {
        "count": len(lists),
        "lists": lists,
        "column_sets": {name: [c for c in COLUMN_SETS[name] if c not in _IDENT] for name in used},
        "flows": {str(f): FLOW_TITLES.get(f, "?") for f in sorted({f for d in CATALOGUE for f in d.flows})},
        "usage": "top_lists(list_name='price_gainers', flow=1, limit=20). Without a flow, the first flow of the list is used. Every row has rank; instrument lists add symbol, name and ins_code. The exchange's own type names (PClosingTop, Block ...) work as list names too.",
        "notes": [
            "Rankings are computed by the exchange and refresh every few seconds in the session; outside it they show the last session.",
            "Prices and values are in rial; volume is in shares (contracts for derivatives).",
            "Derivatives share flow 3 between the Bourse and the Fara Bourse; the Fara Bourse lists carry the _fara suffix.",
            *NOT_AVAILABLE,
        ],
    }


@dataclass(frozen=True)
class TopListRequest:
    """A validated request: which list, which flow, how many rows. ``path`` is what to GET under the CDN root."""

    definition: ListDef
    flow: int | None
    site_type: str
    top: int  # the `top` URL parameter (0 = everything, for the industries list)
    limit: int  # rows to return

    @property
    def path(self) -> str:
        template, _ = _ENDPOINTS[self.definition.family]
        return template.format(type=self.site_type, flow=self.flow, top=self.top)

    @property
    def inner_key(self) -> str:
        return _ENDPOINTS[self.definition.family][1]


def resolve_top_list(list_name: str, flow: int | str | None = None, limit: int = DEFAULT_LIMIT) -> TopListRequest:
    """Check the arguments and name the request. Raises ``ValueError`` with the valid choices when something is off."""
    if is_catalogue(list_name):
        raise ValueError("list_name is required here; call with list_name='catalogue' to see the lists.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be a whole number between 1 and {MAX_LIMIT}.")
    wanted = parse_flow(flow)
    found = _INDEX.get(_norm(list_name))
    if not found:
        close = difflib.get_close_matches(_norm(list_name), list(_INDEX), n=3, cutoff=0.6)
        hints = ", ".join(dict.fromkeys(_INDEX[c][0][0].name for c in close))
        raise ValueError(f"Unknown list '{list_name}'." + (f" Did you mean: {hints}?" if hints else "") + " Call top_lists with list_name='catalogue' to see all lists.")
    definition, default_flow = next(((d, f) for d, f in found if wanted is None or wanted == f or wanted in d.flows), found[0])
    if wanted is None:
        wanted = default_flow
    if definition.family == FAMILY_SECTORS:
        if wanted not in (None, 1):
            raise ValueError(f"'{definition.name}' covers the Bourse only (flow 1), not flow {wanted}.")
        return TopListRequest(definition, None, "SectorTop", 0, limit)
    if wanted not in definition.flows:
        valid = ", ".join(f"{f} ({FLOW_TITLES.get(f, '?')})" for f in definition.flows)
        raise ValueError(f"'{definition.name}' is not published for flow {wanted}. Valid flows: {valid}.")
    return TopListRequest(definition, wanted, definition.site_type(wanted), limit, limit)


# ------------------------------------------------------------------------------------------------ rows


def _price(value: Any) -> float | None:
    """The feeds write 0 where a field does not apply, so 0 means 'not provided'."""
    number = _f(value)
    return number if number else None


def _identity(raw: dict, rank: int) -> dict[str, Any]:
    ins = raw.get("instrument") or {}
    code = raw.get("insCode") or ins.get("insCode")
    return {
        "rank": rank, "symbol": clean(ins.get("lVal18AFC")), "name": clean(ins.get("lVal30")),
        "ins_code": str(code) if code else None,
    }


def _trade_row(raw: dict, rank: int) -> dict[str, Any]:
    ins = raw.get("instrument") or {}
    yesterday, close, last = _price(raw.get("priceYesterday")), _price(raw.get("pClosing")), _price(raw.get("pDrCotVal"))
    shares = _price(ins.get("zTitad"))
    nav = _price(raw.get("pRedTran"))
    return {
        **_identity(raw, rank),
        "yesterday": yesterday, "close": close, "close_pct": pct_change(close, yesterday),
        "last": last, "last_pct": pct_change(last, yesterday), "last_vs_close_pct": pct_change(last, close),
        "low": _price(raw.get("priceMin")), "high": _price(raw.get("priceMax")),
        "trades": _i(raw.get("zTotTran")), "volume": _i(raw.get("qTotTran5J")), "value": _i(raw.get("qTotCap")),
        "market_cap": _i(close * shares) if close and shares else None,
        "nav": nav, "nav_premium_pct": pct_change(last, nav),
        "open_interest": _i(raw.get("mop")) or None, "notional_value": _i(raw.get("nvt")) or None,
    }


def _limits_row(raw: dict, rank: int, side: str) -> dict[str, Any]:
    bid = side == "buy"
    price, volume = _price(raw.get("pMeDem" if bid else "pMeOf")), _i(raw.get("qTitMeDem" if bid else "qTitMeOf")) or 0
    counter = _i(raw.get("qTitMeOf" if bid else "qTitMeDem")) or 0
    value = _i(raw.get("val")) or (_i(price * volume) if price and volume else None)
    return {
        **_identity(raw, rank),
        "side": side, "price": price, "volume": volume or None, "orders": _i(raw.get("zOrdMeDem" if bid else "zOrdMeOf")) or None,
        "value": value, "counter_volume": counter, "one_sided": bool(volume and not counter),
    }


def _cap_row(raw: dict, rank: int) -> dict[str, Any]:
    today, before = _price(raw.get("marketCapToday")), _price(raw.get("marketCapYesterday"))
    # the feed's `change` is unsigned in the "Btm" list (a fall of 487.5T rial is +487.5T), so the sign is recomputed
    change = today - before if today is not None and before is not None else _f(raw.get("change"))
    return {
        **_identity(raw, rank),
        "market_cap": _i(today), "market_cap_yesterday": _i(before), "change": _i(change), "change_pct": pct_change(today, before),
    }


_SECTOR_LEAD = re.compile(r"^\s*(\d{1,3})\s*[-–]?\s*(.+?)\s*$")
_SECTOR_TAIL = re.compile(r"^\s*(.+?)\s*[-–]?\s*(\d{1,3})\s*$")
_SECTOR_TOTAL = "شاخص صنعت"  # the exchange's own aggregate row of the industry index, not an industry


def split_sector(title: str | None) -> tuple[str | None, str | None]:
    """'27-فلزات اساسي' -> ('27', 'فلزات اساسی'); the code may also trail ('بيمه و بازنشسته66') or be missing."""
    text = clean(title)
    if not text:
        return None, None
    lead = _SECTOR_LEAD.match(text)
    if lead:
        return lead.group(1), lead.group(2)
    tail = _SECTOR_TAIL.match(text)
    if tail:
        return tail.group(2), tail.group(1)
    return None, text


def _sector_rows(rows: list[dict], limit: int) -> list[dict[str, Any]]:
    kept = [r for r in rows if clean(r.get("lVal30")) != _SECTOR_TOTAL]
    total_value = sum(_f(r.get("qTotCap")) or 0.0 for r in kept)
    out = []
    for rank, raw in enumerate(kept[:limit], start=1):
        code, name = split_sector(raw.get("lVal30"))
        value = _f(raw.get("qTotCap"))
        share = _safe_div(value, total_value)
        out.append({
            "rank": rank, "sector_code": code, "sector": name,
            "market_cap": _i(raw.get("marketCap")), "trades": _i(raw.get("zTotTran")), "volume": _i(raw.get("qTotTran5J")), "value": _i(value),
            "value_share_pct": None if share is None else round(share * 100, 2),
        })
    return out


def shape_top_list(request: TopListRequest, rows: list[dict] | None) -> dict:
    """Turn the raw rows of one list into stable keys. Rows keep the exchange's own order."""
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    definition = request.definition
    if definition.family == FAMILY_SECTORS:
        shaped = _sector_rows(rows, request.limit)
    elif definition.family == FAMILY_LIMITS:
        shaped = [_limits_row(r, i, definition.side or "buy") for i, r in enumerate(rows[: request.limit], start=1)]
    elif definition.family == FAMILY_CAP:
        shaped = [_cap_row(r, i) for i, r in enumerate(rows[: request.limit], start=1)]
    else:
        shaped = [_trade_row(r, i) for i, r in enumerate(rows[: request.limit], start=1)]
    keep = definition.columns
    shaped = [{c: row[c] for c in keep} for row in shaped]
    dates = [d for d in (_i(r.get("dEven")) for r in rows) if d]
    as_of = max(dates) if dates else None
    notes = [definition.note] if definition.note else []
    if not shaped:
        notes.append("The exchange returned no rows for this list (nothing qualifies right now, or the segment has no activity). That is not an error.")
    if definition.family == FAMILY_LIMITS:
        notes.append("Orders shown are the live best bid / ask; after the close they are the last orders of the session.")
    out: dict[str, Any] = {
        "list": definition.name, "title": definition.title_fa, "description": definition.title_en, "group": definition.group,
        "flow": request.flow, "market": flow_title(request.flow) or "بورس", "exchange_type": request.site_type,
        "sorted_by": definition.sort, "as_of": fmt_date(as_of), "as_of_jdate": jdate(as_of),
        "count": len(shaped), "rows": shaped,
        "units": {"prices": "rial", "value": "rial", "volume": "shares (contracts for derivatives)"},
    }
    if as_of is None:
        del out["as_of"], out["as_of_jdate"]
    if notes:
        out["notes"] = notes
    return out


def top_list(list_name: str | None, rows: list[dict] | None = None, *, flow: int | str | None = None, limit: int = DEFAULT_LIMIT) -> dict:
    """One-call convenience for tests and scripts: the catalogue when ``list_name`` asks for it, else the shaped list."""
    if is_catalogue(list_name):
        return catalogue(flow)
    return shape_top_list(resolve_top_list(str(list_name), flow, limit), rows)
