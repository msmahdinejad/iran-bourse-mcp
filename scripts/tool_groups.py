"""One place that says how the tools are grouped and described, for docs/TOOLS.md and the website."""

from __future__ import annotations

GROUPS = {
    "Market": ["market_status", "market_overview", "indices", "market_watch", "top_movers", "industry_summary", "index_contributors", "market_snapshot", "market_holder_moves", "supervisor_messages"],
    "Screener": ["screen_stocks", "screener_reference"],
    "Indices and funds": ["index_history", "index_constituents", "fund_ranking"],
    "Derivatives": ["option_chain", "futures_market"],
    "Commodity and energy exchanges": ["commodity_market", "energy_market"],
    "Lists, calendar and status": ["top_lists", "capital_calendar", "trading_status"],
    "Symbol": ["search_symbol", "symbol_overview", "quote", "order_book", "order_book_history", "trades", "trade_summary", "price_history", "real_legal_flow", "shareholders", "shareholder_history", "shareholder_portfolio", "corporate_actions", "symbol_statistics", "etf_nav"],
    "Codal": ["codal_filings", "codal_company"],
    "Help": ["glossary"],
}

# Persian one-liners for the website's tool explorer
FA = {
    "market_status": "وضعیت بازار", "market_overview": "نمای کلی بازار", "indices": "شاخص‌ها و شاخص صنایع",
    "market_watch": "دیده‌بان کل بازار (سهام، صندوق، اوراق، اختیار، آتی)", "top_movers": "بیشترین رشد/ریزش، صف خرید و فروش، ورود پول حقیقی",
    "industry_summary": "خلاصه گروه‌های صنعتی و ورود پول حقیقی هر صنعت", "index_contributors": "بیشترین تأثیر بر شاخص", "market_snapshot": "جدول پایان روز کل بازار",
    "market_holder_moves": "جابه‌جایی سهامداران عمده", "supervisor_messages": "پیام ناظر", "search_symbol": "جستجوی نماد",
    "screen_stocks": "اسکرینر و فیلتر نویس: شرط بنویس، نمادهای رد شده را بگیر", "screener_reference": "راهنمای فیلتر: فیلدها، توابع و فیلترهای آماده",
    "index_history": "تاریخچه و روند لحظه‌ای هر شاخص", "index_constituents": "اعضای شاخص و تأثیر هر نماد", "fund_ranking": "رتبه‌بندی و مقایسهٔ صندوق‌های سرمایه‌گذاری",
    "option_chain": "زنجیرهٔ اختیار معامله: خرید و فروش هر قیمت اعمال", "futures_market": "قراردادهای آتی و پایه (basis)",
    "commodity_market": "بورس کالا: معاملات و عرضه‌های بازار فیزیکی، آمار تالارها و نرخ دلار",
    "energy_market": "بورس انرژی: نتیجه عرضه‌ها، برق و فرآورده‌های نفتی، عرضه‌های اعلام‌شده و دفتر سفارش هر عرضه",
    "top_lists": "فهرست‌های رسمی برترین‌ها", "capital_calendar": "تقویم افزایش سرمایه و تعدیل قیمت", "trading_status": "نمادهای متوقف، تحت نظارت و تغییر وضعیت",
    "symbol_overview": "پرونده کامل نماد در یک فراخوانی", "quote": "قیمت لحظه‌ای با درصد تغییر درست", "order_book": "عمق بازار و صف",
    "order_book_history": "تاریخچه عمق بازار و بازه‌های صف", "trades": "ریز معاملات", "trade_summary": "خلاصه ریز معاملات، VWAP و بزرگ‌ترین معاملات",
    "price_history": "تاریخچه قیمت (تعدیل‌شده)", "real_legal_flow": "حقیقی و حقوقی، سرانه و قدرت خریدار", "shareholders": "سهامداران عمده",
    "shareholder_history": "تاریخچه سهامداران و موقعیت هر سهامدار در طول زمان", "shareholder_portfolio": "پرتفوی یک سهامدار", "corporate_actions": "افزایش سرمایه و تعدیل",
    "symbol_statistics": "آمارهای نماد", "etf_nav": "حباب صندوق نسبت به NAV", "codal_filings": "اطلاعیه‌های کدال با لینک PDF و اکسل",
    "codal_company": "اطلاعات ناشر کدال", "glossary": "واژه‌نامه بازار",
}
