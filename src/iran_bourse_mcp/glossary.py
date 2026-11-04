"""Persian market vocabulary, so an agent can interpret the data and the user's questions."""

from __future__ import annotations

from .text import match_key

TERMS: dict[str, dict[str, str]] = {
    "صف خرید": {
        "en": "buy queue",
        "meaning": "The price is locked at the daily upper limit and nobody offers shares for sale; buyers queue up. The queue size is the buy volume waiting at that price.",
    },
    "صف فروش": {
        "en": "sell queue",
        "meaning": "The price is locked at the daily lower limit and nobody bids; sellers queue up.",
    },
    "حقیقی": {"en": "real (natural) persons", "meaning": "Individual investors, as opposed to institutions (حقوقی)."},
    "حقوقی": {"en": "legal entities", "meaning": "Institutional investors: companies, funds, banks."},
    "ورود پول حقیقی": {
        "en": "real-person money inflow",
        "meaning": "Value bought by real persons minus value sold by real persons. Positive means individuals are net buyers (institutions are net sellers).",
    },
    "سرانه خرید": {"en": "per-capita buy", "meaning": "Average value (or volume) bought per real-person buyer."},
    "قدرت خریدار": {
        "en": "buyer power (real)",
        "meaning": "Per-capita buy divided by per-capita sell for real persons. Above 1: the average buyer is larger than the average seller, often read as accumulation.",
    },
    "قیمت پایانی": {"en": "closing price", "meaning": "Volume-weighted average price of the last trading period, used by the exchange as the day's closing price."},
    "آخرین معامله": {"en": "last trade price", "meaning": "Price of the very last trade. Differs from the closing price."},
    "دامنه نوسان": {"en": "daily price limit", "meaning": "Allowed range around the reference price (typically ±3% to ±5% for stocks, other for funds). price_limits.upper/lower."},
    "حجم مبنا": {
        "en": "base volume",
        "meaning": "The exchange's reference volume for a symbol, used to size order and price rules. Nearly every symbol reports 1, so 'volume above base volume' only means 'traded at all'.",
    },
    "P/E": {"en": "price to earnings", "meaning": "Closing price divided by earnings per share (EPS). Missing for loss-making companies; compare within an industry, not across them."},
    "NAV": {
        "en": "net asset value (funds)",
        "meaning": "Per-unit redemption value of a fund (قیمت ابطال). A fund trading below its NAV is at a discount, above it at a premium (حباب).",
    },
    "حباب": {"en": "premium over NAV", "meaning": "For funds: (market price / NAV - 1) x 100. Positive means the units trade above their redemption value; negative means a discount."},
    "TAL": {
        "en": "closing-price (TAL) segment",
        "meaning": "Symbols ending in a digit such as 3 that trade only at the closing price. Their daily limits are equal, so limit and queue logic does not apply; the exchange's own tables hide them by default.",
    },
    "قیمت مجاز": {"en": "allowed price band", "meaning": "Same as the daily price limit for the day."},
    "تعدیل قیمت": {"en": "price adjustment", "meaning": "Base price change on the ex-date of a capital increase or dividend. Use adjusted=true in price_history for continuous series."},
    "سهامدار عمده": {"en": "major shareholder", "meaning": "Holder with roughly 1% or more of the shares, as listed by TSETMC."},
    "ریز معاملات": {"en": "tick-by-tick trades", "meaning": "Every executed trade with time, price and volume. Buyer/seller identity is not published."},
    "عمق بازار": {"en": "order book depth", "meaning": "The 5 best bid and ask levels (price, volume, number of orders)."},
    "صدور / ابطال": {"en": "NAV issue / redemption", "meaning": "Unit issue and redemption prices of a fund; compare with the market price for premium/discount."},
    "EPS": {"en": "earnings per share", "meaning": "Exchange-estimated earnings per share. P/E here = last price / EPS."},
    "شاخص کل": {"en": "TEDPIX / total index", "meaning": "Cap-weighted index of the Tehran Stock Exchange."},
    "شاخص هم‌وزن": {"en": "equal-weight index", "meaning": "Index where every stock has the same weight; reflects the typical stock better than the total index."},
    "توقف نماد": {"en": "trading halt", "meaning": "Symbol status other than 'مجاز' (allowed) means halted/restricted. See status.title."},
    "کدال": {"en": "Codal", "meaning": "The official disclosure system where listed companies file financial statements and notices."},
    "ناظر بازار": {"en": "market supervisor", "meaning": "Official messages from the exchange supervisor about symbols (restrictions, notices)."},
    "بازار اول / دوم": {"en": "first / second board", "meaning": "Board (تابلو) classification of listed companies; see board in the identity."},
    "ریال": {"en": "Rial", "meaning": "All prices and values returned by this server are in Rial (1 Toman = 10 Rial)."},
    "بورس کالا": {
        "en": "Iran Mercantile Exchange (IME)",
        "meaning": "The commodity exchange: steel, copper, aluminium, cement, petrochemicals, oil products and agricultural goods are traded physically in halls (تالار), next to gold and saffron certificates, standard forwards, commodity funds and futures. commodity_market reads its physical market; the listed instruments are in top_lists (commodity group).",
    },
    "بورس انرژی": {
        "en": "Iran Energy Exchange (IRENEX)",
        "meaning": "The exchange for oil, gas and petrochemical products and for electricity, traded by auction. energy_market reads its auctions; the listed instruments (electricity forwards, capacity and energy-saving certificates, energy futures) are in top_lists (energy group).",
    },
    "گواهی سپرده کالایی": {
        "en": "commodity deposit certificate",
        "meaning": "A tradable receipt for a commodity held in an accredited warehouse (gold, silver, saffron, cement, steel, agricultural goods). It trades like a share, in rial per certificate, and its holder can take delivery (تحویل) of the goods. See top_lists (commodity_certificates) and market_watch with security_type='commodity'.",
    },
    "نقدی / سلف / نسیه": {
        "en": "cash / forward / credit (contract types)",
        "meaning": "The contract type of a commodity trade: نقدی is paid and delivered within days, سلف (salaf, forward) is paid now for delivery on a later date, نسیه is delivered now and paid later. «سلف موازی استاندارد» are standardised forwards listed as tradable symbols (top_lists: standard_salaf).",
    },
    "مچینگ": {
        "en": "matching contract",
        "meaning": "A deal where a buyer's and a seller's orders were matched against each other (contract types «نقدی (مچینگ)» and «سلف (مچینگ)» on the IME) rather than bought from a fixed offer. commodity_market shows offered_tons 0 for them.",
    },
    "عرضه": {
        "en": "offer / auction",
        "meaning": "A seller's offer of a volume at a base price (قیمت پایه) in a hall or ring. On the Energy Exchange every offer is an auction with an id (auction_id); it ends in trades or in «توقف مازاد عرضه» (halted on surplus supply).",
    },
    "تقاضا": {
        "en": "demand",
        "meaning": "The volume buyers ordered (demand_tons / demand_volume). Demand above the offered volume (عرضه) means the offer was oversubscribed.",
    },
    "تحویل": {
        "en": "delivery",
        "meaning": "When and where the goods are handed over (delivery_date, delivery_place). For electricity the delivery period (daily, weekly, monthly) fixes the hours the contract covers, so kwh = kW of capacity x hours.",
    },
    "قرارداد آتی": {
        "en": "futures contract",
        "meaning": "An agreement to buy or sell an underlying at a fixed price on a later date, settled daily through the clearing house. futures_market covers the Tehran derivatives market; the energy futures of the Energy Exchange are in top_lists (energy_futures).",
    },
    "کشف پریمیوم": {
        "en": "premium discovery",
        "meaning": "An auction where buyers bid a premium (or a discount, when negative) over the exchange's reference price instead of a price. In energy_market the avg_price of such a row is the premium, not a price; price_basis says so.",
    },
    "بار پایه": {
        "en": "base-load electricity",
        "meaning": "An electricity contract for a constant capacity (kW) in every hour of the delivery period. The volume is kW of capacity over the delivery period, not energy; energy_market gives the energy as kwh.",
    },
    "برق سبز / برق آزاد": {
        "en": "green / free-market electricity",
        "meaning": "Two electricity markets of the Energy Exchange: green electricity (برق سبز) from renewable plants, and free-market electricity (برق آزاد), priced by the auction instead of a regulated tariff. Both are auctions with an auction_id in energy_market.",
    },
}


def lookup(term: str | None = None) -> dict:
    if not term:
        return {"terms": {k: v["en"] for k, v in TERMS.items()}}
    key = match_key(term)
    hits = {
        k: v
        for k, v in TERMS.items()
        if key in match_key(k) or key in v["en"].casefold().replace(" ", "")
    }
    return {"query": term, "matches": hits or None, "hint": None if hits else "No match; call glossary without arguments to list terms."}
