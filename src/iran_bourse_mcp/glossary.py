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
