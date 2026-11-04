<div dir="rtl">

# منابع داده و رفتارهای غیرمنتظرهٔ شناخته‌شده

> ترجمهٔ فارسی [DATA_SOURCES.md](DATA_SOURCES.md). اگر دو متن با هم نخواندند، نسخهٔ انگلیسی مرجع است.

منبع‌های مورد استفاده عمومی و **غیررسمی** هستند و هیچ‌کدام تضمین مستندی دربارهٔ پایداری ندارند. همهٔ موارد زیر هنگام ساختن این پروژه روی سرورهای زنده مشاهده شده‌اند (2 تا 5 نوامبر 2026).

| منبع | آدرس پایه | کلید هر نماد | کاربرد |
|---|---|---|---|
| TSETMC API | `https://cdn.tsetmc.com/api` | `insCode` (رشتهٔ عددی) | قیمت‌ها، تاریخچه، عمق بازار، ریز معاملات، حقیقی/حقوقی، سهامداران، پیام‌ها، پیوست‌های کدال؛ فید کل بازار (حدود 3,700 نماد با عمق پنج‌سطحی)، اختیار و آتی، شاخص‌ها، صندوق‌ها، فهرست‌های برترینِ خود بورس، وضعیت‌های نظارتی و معاملاتی |
| TSE gateway | `https://webgw.tse.ir` | `instrumentId` (مثلاً `IRO1FOLD0001`) | جایگزین (fallback) و تکمیل‌کنندهٔ دیده‌بان بازار (582 سهم شامل نام صنعت و زیرصنعت، وضعیت و اثر بر شاخص)، پرچم‌های باز بودن بازار |
| جستجوی کدال | `https://search.codal.ir/api/search/v2/q` | `Symbol` | اطلاعیه‌ها همراه با لینک صفحه، PDF، اکسل و پیوست |
| IME و بورس انرژی ایران | `https://www.ime.co.ir`، `https://webapi.iee.ir` | نماد قرارداد، شناسهٔ حراج | `commodity_market`، `energy_market` (بخش مستقل در ادامه) |
| time.ir | `https://www.time.ir` | ندارد | تقویم تعطیلات رسمی که در `dates.py` تعبیه شده است (یک بار خوانده شده؛ هنگام اجرا فراخوانی نمی‌شود) |

`instrumentId` (در gateway) و `insCode` (در TSETMC) از طریق `GetInstrmentsHistoryInDay` که هر دو را دارد به هم وصل می‌شوند؛ فید دیده‌بان بازار هم هر دو را دارد (`insID`، `insCode`).

همهٔ درخواست‌ها به یک `User-Agent` شبیه مرورگر نیاز دارند؛ بدون آن TSETMC با 403 پاسخ می‌دهد.

## نقشهٔ endpointها

| ابزار | endpointها |
|---|---|
| `quote`, `symbol_overview` | `Instrument/GetInstrumentInfo`, `ClosingPrice/GetClosingPriceInfo` |
| `order_book` | `BestLimits/{ins}`؛ آستانه‌ها از `GetInstrumentInfo` |
| `order_book_history` | `BestLimits/{ins}/{date}`, `MarketData/GetStaticThreshold/{ins}/{date}` |
| `trades`, `trade_summary` | `Trade/GetTrade/{ins}` (آخرین روز)، `Trade/GetTradeHistory/{ins}/{date}/false`، جمع‌ها از `ClosingPrice/GetClosingPriceDailyList` |
| `price_history` | `ClosingPrice/GetClosingPriceDailyList/{ins}/0` |
| `real_legal_flow` | `ClientType/GetClientType/{ins}/1/0`، `ClientType/GetClientTypeHistory/{ins}` (همهٔ روزها در یک فراخوانی، مقادیر دقیق به ریال)، `.../{ins}/{date}` برای یک روز |
| `market_watch`, `top_movers`, `industry_summary` | `ClosingPrice/GetMarketWatch?market=0&industrialGroup=&showTraded=false&withBestLimits=true&hEven=0&RefID=0` (همهٔ نمادها با عمق پنج‌سطحی)، `StaticData/GetStaticData` (نام صنعت‌ها)؛ دیده‌بان gateway فقط به‌عنوان جایگزین و برای نام زیرصنعت‌ها و وضعیت |
| `top_movers` (real_*) | `ClientType/GetClientTypeAll`, `ClosingPrice/GetInstrmentsHistoryInDay/{date}`، فید دیده‌بان بازار |
| صف‌ها در `top_movers` | فید دیده‌بان بازار برای پیدا کردن نمادهای قفل‌شده روی سقف یا کف مجاز، و بعد `BestLimits/{ins}` برای اندازهٔ واقعی صف |
| `screen_stocks`, `screener_reference` | امروز: فید دیده‌بان بازار و `ClientType/GetClientTypeAll`؛ روزهای گذشته: `ClosingPrice/GetInstrmentsHistoryInDay/{date}`، برای هر روز معاملاتی یک درخواست برای کل بازار، تا 60 روز |
| `shareholders` | `Shareholder/GetInstrumentShareHolderLast/{ins}` |
| `shareholder_history` | `Shareholder/{ins}/{date}`، و برای یک سهامدار `Shareholder/GetShareHolderHistory/{ins}/{id}/{top}` |
| `shareholder_portfolio` | `Shareholder/GetShareHolderCompanyList/{holderId}` |
| `market_holder_moves` | `Shareholder/GetShareHolderChanges/false` |
| `corporate_actions` | `ClosingPrice/GetPriceAdjustList/{ins}`, `Instrument/GetInstrumentShareChange/{ins}` |
| `symbol_statistics` | `MarketData/GetInstrumentStatistic/{ins}` |
| `etf_nav` | `Fund/GetETFByInsCode/{ins}` |
| `indices`, `market_overview` | `Index/GetIndexB1LastAll/All/{flow}`, `MarketData/GetMarketOverview/{flow}` (`flow` 1 = بورس، 2 = فرابورس) |
| `option_chain` | `Instrument/GetInstrumentOptionMarketWatch/{flow}` |
| `futures_market` | `Instrument/GetInstrumentFutureMarketWatch/0` |
| `index_history` | `Index/GetIndexB2History/{ins}` (روزانه از 2008)، `Index/GetIndexB1LastDay/{ins}` (امروز، مسیر پنج‌دقیقه‌ای) |
| `index_constituents` | `ClosingPrice/GetIndexCompany/{ins}`, `Index/GetInstEffect/{date}/{flow}/{top}` (اثر بر حسب واحد شاخص) |
| `fund_ranking` | `Fund/GetFunds/{type}` |
| `top_lists` | `ClosingPrice/GetTradeTop/{kind}/{flow}/{top}`, `BestLimits/GetBestLimitsTop/{kind}/{flow}/{top}`, `ClosingPrice/GetMarketCap/{kind}/{flow}/{top}`, `MarketData/GetSectorTop/{top}` |
| `capital_calendar` | `Instrument/GetInstrumentShareChangeByFlow/{flow}/10`, `ClosingPrice/GetPriceAdjustByFlow/{flow}/{top}` |
| `trading_status` | `Supervision/GetSupervisionListBySourceID/{source}/{type}`, `Supervision/GetSupervisionByInsCode/{ins}`, `MarketData/GetInstrumentStateTop/{n}`, `MarketData/GetInstrumentStateAll/{ins}` |
| `commodity_market`, `energy_market` | سرویس‌های IME و بورس انرژی در بخش زیر |
| `market_status` | `MarketData/GetMarketOverview/{flow}`، `MarketDate` در gateway، `StaticData/GetTime`؛ تقویم تعطیلات داخل `dates.py` تعبیه شده است |
| `supervisor_messages` | `Msg/GetMsgByInsCode/{ins}`, `Msg/GetMsgByFlow/{flow}/{top}` |
| `codal_filings` | API جستجوی کدال |
| `codal_company` | `Codal/GetCodalPublisherBySymbol/{symbol}` |

## رفتارهای غیرمنتظره‌ای که پیدا کردیم و کاری که در برابرشان می‌کنیم

1. **`closingPriceInfo.priceChange` قابل اتکا نیست.** برای سهمی که با 120 ریال بالاتر از دیروز بسته شد، مقدارش `0.0` بود. ما تغییر قیمت را از `pDrCotVal` (آخرین معامله) / `pClosing` (قیمت پایانی) و `priceYesterday` دوباره حساب می‌کنیم.
2. **دو قیمت.** `pClosing` قیمت پایانی (وزنی) بورس است و `pDrCotVal` آخرین معامله. هر دو برگردانده می‌شوند (`last`، `close`).
3. **تاریخچهٔ عمق بازار یک فید تغییرات (delta) است.** هر `refID` فقط سطح‌هایی را فهرست می‌کند که تغییر کرده‌اند (1 تا 5 ردیف). ما با حمل سطح‌های تغییرنکرده به جلو، snapshotهای کامل 5‌سطحی را بازسازی می‌کنیم. رویدادها محدود به ساعت جلسه نیستند: سفارش‌هایی که پیش از بازگشایی (از حدود 06:00) و پس از بسته شدن (تا حدود 14:30) ثبت شده‌اند هم ذخیره می‌شوند؛ به همین دلیل پیش‌فرض `order_book_history` بازهٔ 08:30-12:35 است.
4. **تاریخچهٔ عمق بازار برای روز جاری ناقص است.** در روزی که اندازه گرفتیم، endpoint برای روز معاملاتی جاری حدود 09:02 متوقف شده بود، اما جلسهٔ کامل روز قبل را پوشش می‌داد. ما به‌جای وانمود کردن به کامل بودن، `events_span` و یک `warning` را در خروجی می‌آوریم.
5. **ریز معاملات کامل است.** `Trade/GetTradeHistory` و `GetTrade` برای فولاد در دو روز دقیقاً با جمع‌های خود بورس برابر بودند (6,819 و 15,643 معامله، 100% حجم). `trade_summary.completeness` این بررسی را در هر فراخوانی تکرار می‌کند.
6. **نام فیلدها بین endpointها فرق می‌کند.** تعدادها در `GetClientType` با نام `buy_CountI` و در `GetClientTypeHistory` با نام `buy_I_Count` می‌آیند؛ فقط نسخهٔ history مقدارها را به ریال دارد. ما هر دو را می‌پذیریم. به همین دلیل مقدارهای روز جاری در `real_legal_flow.latest_session` *تخمینی* هستند (حجم × VWAP) و با `value_estimated` علامت‌گذاری می‌شوند.
7. **`Shareholder/{ins}/{date}` هر سهامدار را با دو تاریخ برمی‌گرداند** (یک snapshot جاری و یک snapshot مجاور). `shareholders` از `GetInstrumentShareHolderLast` استفاده می‌کند (تمیز، سهامداران دارای 1% یا بیشتر)؛ `shareholder_history` ردیف‌های تاریخ‌دار را گروه‌بندی می‌کند و تفاوت‌ها را حساب می‌کند.
8. **endpoint مربوط به ETF با سهام ناسازگار است.** `GetETFByInsCode` برای نمادهایی که صندوق نیستند HTTP 500 برمی‌گرداند. `etf_nav` آن را به پاسخ روشنِ «صندوق نیست» تبدیل می‌کند.
9. **جستجو تقریبی (fuzzy) است.** `GetInstrumentSearch` برای هر عبارتی حدود 41 نتیجه برمی‌گرداند. ما تطابق دقیق نمادِ یکسان‌سازی‌شده را برمی‌داریم (ي/ك عربی و ی/ک فارسی برابر گرفته می‌شوند)؛ اگر نمادی در چند تابلو وجود داشته باشد، کمترین شناسهٔ `flow` را ترجیح می‌دهیم و در غیر این صورت با ارائهٔ پیشنهادها خطا می‌دهیم.
10. **یک ردیف دیده‌بان بازار نمی‌تواند صف را تأیید کند.** نمادی که روی سقف مجاز است و حجم فروش قابل‌مشاهده ندارد شبیه صف خرید به نظر می‌رسد، اما در بررسی ما روی دیده‌بان gateway، 85 نماد شبیه صف بودند در حالی که 83 مورد واقعی بودند، و فیلدهای بهترین سفارش خرید خارج از جلسه قابل اتکا نیستند. به همین دلیل `top_movers(kind="buy_queue")` هر نامزد قفل‌شده روی سقف یا کف مجاز را با عمق بازار واقعی‌اش تأیید می‌کند (برای هر نماد یک فراخوانی `BestLimits`، در روزی با حدود 200 نماد روی سقف مجاز حدود ده ثانیه).
11. **قیمت‌های تعدیل‌شده استنباط می‌شوند.** `GetPriceAdjustList` در TSETMC تعدیل‌های سود نقدی را پوشش می‌دهد اما بسیاری از افزایش سرمایه‌ها را ندارد (مثلاً فولاد 2026-03-30، از 1500bn به 1935bn سهم، ضریب 0.775). ما رویدادهای تعدیل را از خود سری استنباط می‌کنیم: در روز تعدیل (ex-date) مقدار `priceYesterday` دیگر با `pClosing` قبلی برابر نیست. تفاوت‌های کمتر از 0.1% گرد شدن به گام قیمت (tick) در نظر گرفته می‌شوند. ردیف‌های خیلی قدیمی (پیش از حدود 2014) گاهی این پیوستگی را ندارند.
12. **تاریخ‌ها.** `dEven` یک عدد صحیح میلادی با قالب `YYYYMMDD` است و `hEven` با قالب `HHMMSS` است (بدون صفر ابتدایی؛ پس `90013` یعنی 09:00:13). `GetChartData` از یک timestamp غیراستاندارد استفاده می‌کند، بنابراین از آن استفاده نمی‌کنیم.
13. **متن.** TSETMC حروف عربی (ي ك) را ذخیره می‌کند. ما متن برگردانده‌شده را به حروف فارسی یکسان‌سازی می‌کنیم.
14. **جدول پایان روزِ امروز در طول جلسه خالی است.** `GetInstrmentsHistoryInDay/{today}` تا پایان بازار چیزی برنمی‌گرداند و این هر join وابسته به آن را از کار می‌اندازد (نگاشت instrumentId به insCode برای صف‌ها و رتبه‌بندی‌های پول حقیقی). ما به‌جای آن این نگاشت را از جدیدترین روز منتشرشده می‌سازیم؛ شناسه‌ها ثابت‌اند.
15. **شلوغ بودن منبع بالادستی.** سرورهای بورس گاهی زیر فشار با 502/503 پاسخ می‌دهند. درخواست‌ها با backoff دوباره تلاش می‌شوند؛ شکست پایدار به‌صورت «سرور شلوغ» گزارش می‌شود، نه مشکل IP.
16. **کدال.** صفحه‌های مستندشدهٔ `codal.ir` قالب‌های JavaScript هستند؛ منبع کارآمد، API جستجوی عمومی است (`search.codal.ir/api/search/v2/q`). لینک نسبی PDF آن (`DownloadFile.aspx?...`) نسبت به ریشهٔ سایت حل می‌شود، نه نسبت به `/Reports/`.
17. **حجم پاسخ‌ها.** ریز معاملات یک روز حدود 3 MB، تاریخچهٔ عمق بازار 3 MB، پیام‌های ناظر برای یک نماد 3.5 MB و تاریخچهٔ کامل قیمت روزانه 1.5 MB است. پاسخ‌ها مدت کوتاهی کش می‌شوند و پیش از رسیدن به مدل خلاصه می‌شوند.
18. **دو فید دیده‌بان بازار.** gateway فهرستی از 582 سهم می‌دهد. `ClosingPrice/GetMarketWatch`، همان فیدی که جدول و کادر فیلتر خود tsetmc.com روی آن اجرا می‌شوند، حدود 3,700 نماد برمی‌گرداند (سهام، بازار پایه، صندوق‌ها، اوراق بدهی، حق تقدم، اختیار، آتی، کالا) همراه با عمق پنج‌سطحی در `blDs`، حجم مبنا `bv`، تعداد سهام `ztd`، NAV صندوق `pRedTran`، موقعیت‌های باز `buyOP`، کد نوع نماد `yVal`، تابلو `cGrValCot` و کد گروه صنعت `csv`. `pe` رشته یا null است و برای شرکت‌های زیان‌ده صفر یا منفی است که ما آن را «بدون P/E» گزارش می‌کنیم. ابزارهای کل بازار از همین فید استفاده می‌کنند؛ gateway به‌عنوان جایگزین و برای نام صنعت و زیرصنعت باقی می‌ماند.
19. **کد گروه صنعت در فید با صفر ابتدایی می‌آید.** `csv` از `01` تا `09` است، در حالی که جدول ثابت صنعت‌ها `1` تا `9` دارد؛ این کدها به‌صورت عدد مقایسه می‌شوند (وگرنه 40 ردیف از 3,680 ردیف صنعت خود را از دست می‌دادند).
20. **سفارش‌های خارج از دامنهٔ قیمتی روز معامله نمی‌شوند.** سفارش فروش بالاتر از سقف یا سفارش خرید پایین‌تر از کف می‌تواند در عمق بازار بنشیند اما هرگز اجرا نمی‌شود، پس صف را نمی‌شکند: صف خرید یعنی قیمت روی سقف است و هیچ سفارش فروشِ قابل‌معامله‌ای عرضه نشده است. تابلوهای F3، G3 و U3 (TAL) سقف و کف قیمتی برابر دارند و به همین دلیل منطق صف در آن‌ها بی‌معنی است.
21. **کل بازار برای یک روز در یک درخواست.** `GetInstrmentsHistoryInDay/{date}` حدود 0.9 MB است و فقط نمادهایی را دارد که معامله شده‌اند؛ نمادِ درج‌شده‌ای که در آن نیست در آن روز هیچ معامله‌ای نداشته است (اسکرینر از زمان درج نماد حجم صفر را می‌شمارد و روزهای پیش از درج را نامعلوم در نظر می‌گیرد). هر درخواست روزانه 0.1 تا 0.3 s طول می‌کشد.
22. **تاریخچهٔ حقیقی/حقوقی (client type) در یک فراخوانی.** `ClientType/GetClientTypeHistory/{ins}` بدون تاریخ همهٔ روزها را با مقادیر دقیق به ریال برمی‌گرداند؛ بنابراین `real_legal_flow(days=N)` یک درخواست لازم دارد، نه N درخواست.
23. **نمادها یکتا نیستند.** یک نماد می‌تواند به‌صورت چند رکورد وجود داشته باشد که قدیمی‌ها مرده‌اند؛ تطبیق با رکورد اشتباه باعث می‌شد حدود 5% نمادها با HTTP 500 شکست بخورند. resolver رکوردی را ترجیح می‌دهد که جدیدتر از همه معامله شده باشد.
24. **صفحه‌بندی کدال.** API جستجو اطلاعیه‌ها را در صفحه‌های 20‌تایی برمی‌گرداند. `codal_filings(title_contains=...)` عنوان‌ها را خودش فیلتر می‌کند: تا 8 صفحه می‌خواند و موارد منطبق را نگه می‌دارد (با یک صفحه بیشتر نتایج پیدا نمی‌شد).
25. **محدودیت نرخ درخواست برای هر میزبان جداست.** HTTP 429 آن میزبان را وارد یک دورهٔ سردشدن (cool-down) 60 ثانیه‌ای می‌کند و خطا به‌جای مقصر دانستن IP می‌گوید محدودیت نرخ درخواست اعمال شده است. درخواست به میزبان‌های دیگر ادامه می‌یابد.
26. **زنجیرهٔ تعدیل در روزهای بدون معامله پاره می‌شود.** زنجیرهٔ `priceYesterday` که برای استنباط تعدیل افزایش سرمایه به کار می‌رود (مورد 11) در روزهایی که نماد معامله نداشته به هم وصل نیست؛ تعدیل‌کننده روزهای بدون قیمت پایانی را رد می‌کند و روزهای معامله‌شده را از روی این فاصله به هم وصل می‌کند.
27. **رفتارهای غیرمنتظرهٔ تقویم.** بورس در روزهایی که تعطیل رسمی نیستند هم بسته می‌شود (مثلاً 4 تا 6 ژوئیه 2026). `market_status` تعطیلات رسمی را می‌شناسد و وقتی جدیدترین داده‌های خود بورس با تقویم نخواند همین را اعلام می‌کند؛ بخش بعدی را ببینید.
28. **چند مورد عجیب کوچک که در 5 نوامبر دیدیم.** `exchange_server_time` (`GetTime`) در قالب `MM/DD/YYYY` و به وقت UTC است؛ endpoint تاریخچهٔ سهامداران جدیدترین ردیف خود را با روز معاملاتی بعدی مهر می‌زند.

## تعطیلات رسمی (`market_status`)

بورس از شنبه تا چهارشنبه معامله می‌کند، مگر در تعطیلات رسمی. هیچ endpointی از بورس این تعطیلات را فهرست نمی‌کند؛ به همین دلیل `dates.py` دو جدول دارد: تعطیلات ثابت شمسی (نوروز 1 تا 4 فروردین، 12 و 13 فروردین، 14 و 15 خرداد، 22 بهمن، 29 اسفند) که برای هر سال معتبرند، و تقویم رسمی سال شمسی 1405 به‌صورتی که time.ir منتشر کرده است (در 5 نوامبر 2026 خوانده شد: 23 تعطیلی که در روز جمعه نمی‌افتند، از جمله تعطیلات مذهبی). تعطیلات مذهبی از ماه پیروی می‌کنند و سال‌به‌سال اعلام می‌شوند؛ بنابراین سالی که در جدول نیست فقط تعطیلات ثابت را می‌گیرد و خروجی این را می‌گوید. تست‌ها هر دو جدول را با تاریخچهٔ خود بورس مقایسه می‌کنند: هر روز شنبه تا چهارشنبه از 2019 به بعد که در تاریخچهٔ شاخص کل ردیفی ندارد (162 روز) در `tests/fixtures/exchange_closed_weekdays.json` ذخیره شده است؛ هر تعطیلی ثابت و هر تعطیلی منتشرشده‌ای که تا کنون در شنبه تا چهارشنبه افتاده جزو آن‌هاست؛ و تنها تعطیلی‌هایی که تقویم توضیح نمی‌دهد 4 تا 6 ژوئیه 2026 است که خود بورس تصمیم گرفته است.

## بورس‌های کالا و انرژی (IME، بورس انرژی ایران)

برای issue #9 در 5 نوامبر 2026 بررسی شد (داده‌های جلسهٔ 4 نوامبر، 1405/08/13)، از طریق یک پروکسی داخل ایران و **بدون حساب کاربری، کلید، کوکی، کپچا یا ترفند مربوط به نشست (session)**: هر endpoint زیر به یک `User-Agent` ساده شبیه مرورگر پاسخ داد. این دو بورس از طریق سایت‌های خودشان منتشر می‌کنند، نه از طریق TSETMC؛ بنابراین دو ابزار مستقیم آن‌ها را می‌خوانند: `commodity_market` (IME) و `energy_market` (بورس انرژی ایران). ابزارهای مالی *درج‌شدهٔ* آن‌ها (گواهی‌ها، سلف‌ها، صندوق‌ها، آتی‌ها) از قبل در فید TSETMC هستند؛ زیربخش آخر را ببینید.

| منبع | آدرس پایه | درخواست | کاربرد |
|---|---|---|---|
| سرویس‌های ASMX سایت IME | `https://www.ime.co.ir/SubSystems/IME/Services/Home/imedata.asmx/<Method>` | `POST` با بدنهٔ JSON و `Content-Type: application/json; charset=utf-8`؛ پاسخ به شکل `{"d": "<a JSON array as a string>"}` است | `commodity_market` |
| API وب بورس انرژی ایران | `https://webapi.iee.ir/api/<Controller>/<Action>?Lang=fa` | `GET`؛ پاسخ به شکل `{"results": [...], "pagedMetaData": [{"totalCount", "hasNext", ...}], "isSuccess", "isFailed", "errors"}` است | `energy_market` |
| API بخش `Energy` در TSETMC | `https://cdn.tsetmc.com/api/Energy/<Method>/...` | `GET` | بررسی شد، استفاده نمی‌شود (همان حراج‌ها، در ادامه ببینید) |

هر سه، سرویس‌هایی هستند که خود صفحه‌های این بورس‌ها فراخوانی می‌کنند (در صفحهٔ اصلی `ime.co.ir`، در React bundle سایت `iee.ir` و در bundle سایت `main.tsetmc.com` پیدا شدند). `robots.txt` آن‌ها را مجاز می‌داند (`ime.co.ir` فقط `/DownloadHandler.ashx` را ممنوع کرده و `iee.ir` هیچ چیز را). تاریخ‌ها در هر دو **رشتهٔ شمسی** هستند (`1405/08/13`)؛ پارامترهای IME حتی `GregorianFromDate`/`GregorianToDate` نام دارند و مقدار میلادی واقعی به HTTP 500 می‌انجامد. client تبدیل را انجام می‌دهد.

### IME: بازار فیزیکی (`www.ime.co.ir`)

| متد (بدنه، جز `"Language":8`) | خروجی | حجم / تأخیر | استفاده در |
|---|---|---|---|
| `GetAmareMoamelatList` `{"fari":false,"GregorianFromDate":"1405/08/13","GregorianToDate":"1405/08/13","MainCat":0,"Cat":0,"SubCat":0,"Producer":0}` | یک ردیف برای هر عرضه یا قرارداد، 34 فیلد (در ادامه) | 181 ردیف، 183 KB، 0.3 s برای یک جلسه؛ 1,184 ردیف، 1.2 MB، 0.7 s برای پنج جلسه؛ پنجشنبه: `[]` | `view="trades"` |
| `GetHomeFizikiWithDateGrid` `{"GregorianFromDate","GregorianToDate"}` | به تفکیک رینگ: `{"ID":1,"xRingName":"صنعتی","Value":109469008.0,"Volume":129433.0,"OfferVolume":295659.0}` | 3 ردیف | `view="summary"` |
| `GetHomeNamaWithDateGrid` (همان بدنه) | به تفکیک بازار: `{"name":"بازار فيزيکي","Id":"1","TradeValue":180697354.0,"TradeVolume":181729.0}` (فیزیکی، آتی، اختیار، مالی، گواهی) | 5 ردیف | `view="summary"` |
| `GetHajmArzeshMoamelatDateGrid` (همان بدنه) | یک ردیف برای هر جلسه: `{"TradeDate":"1405/08/13","TradeValue":180697354.0,"TradeVolume":181729.0}` | حدود 80 B برای هر روز | `view="summary"`، پیدا کردن آخرین جلسه |
| `GetHomeExchangeRateData` | نرخ دلار در صفحهٔ اصلی: `{"Tarikh":"1405/08/13","Nerkh":1878192.0,"Sharh":"دلار"}`، دو روز آخر | 150 B | `view="summary"` |
| `GetMainGroups`, `GetCatGroups` `{"MainCat":1}`, `GetSubCatGroups`, `GetProducers` | دیکشنری‌های فیلتر (`{"Name":"صنعتی","code":1}`) | کوچک | شناسهٔ گروه‌ها در `commodity.MAIN_GROUPS` ثابت‌نویسی (hard-code) شده است |
| `GetHomeSaderatiGridWithDate`, `GetHomeNesbateMoameleBeArzeFizikiChartData`, `GetHomeArzeTaghiratChartData` | ارزش و حجم تالار صادراتی (کیش)؛ جمع رینگ‌ها در یک بازه؛ حجم عرضه به تفکیک روز | کوچک | استفاده نمی‌شود |

فیلدهای `GetAmareMoamelatList` (همه نگه داشته می‌شوند): `GoodsName`، `Symbol` (`HAAL-PS10000-00`)، `ProducerName`، `ArzehKonandeh` (عرضه‌کننده)، `Talar` (تالار)، `ContractType` (`نقدی`، `سلف`، `نسیه`، هرکدام با نوع `(مچینگ)` هم)، `Tasvieh`، `PacketName`، `cBrokerSpcName`، `date`، `DeliveryDate`، `SettlementDate`، `Warehouse`، `Unit`، `Currency`، `Price` (قیمت پایانیِ میانگین وزنی؛ اگر معامله‌ای نشده باشد null)، `MinPrice`، `MaxPrice`، `ArzeBasePrice`، `arze` (حجم عرضه‌شده)، `taghaza` (تقاضا)، `Quantity` (حجم معامله‌شده)، `TotalPrice`، `Category`، `arzehPk`، به‌علاوهٔ `MinPrice1`، `Price1`، `arzeMinPrice`، `taghazavoroudi`، `taghazaMaxPrice`، `xTalarReportPK`، `bArzehRadifTarSarresid`، `ModeDescription`، `MethodDescription` که ابزارها از آن‌ها استفاده نمی‌کنند.

**واحدها** (IME برخی را اعلام می‌کند، بقیه استخراج و بررسی شده‌اند). `Quantity`، `arze` و `taghaza` بر حسب **تن** هستند: `Unit` در هر 1,184 ردیف پنج جلسه `تن` است. `TotalPrice` بر حسب **هزار ریال** است (عنوان ستون خود صفحه: «ارزش معامله (هزارریال)»). `Price` **ریال به ازای هر کیلوگرم** است: رابطهٔ `TotalPrice = Price x Quantity` در هر 1,045 ردیف معامله‌شده با دقت 2e-5 برقرار بود، که فقط وقتی ممکن است که تن × 1,000 kg × قیمت / 1,000 هزار ریال بدهد؛ بورس انرژی هم همین قرارداد را اعلام می‌کند (در ادامه). آمارهای تجمیعی **میلیون ریال** هستند (عنوان ستون‌ها «ارزش(میلیون ریال)») و حجم آن‌ها تن است: `OfferVolume` سه رینگ روی هم 414,056 t می‌شود، که همان تیتر خود IME در آن صبح است («۴۱۴ هزار تن محصول روی میز فروش می‌رود»).

رفتارهای غیرمنتظره: فهرست، بازار فرعی را شامل نمی‌شود (`"fari":true` آن را با مجموعه‌فیلدی کوچک‌تر برمی‌گرداند: بدون قیمت) و ارزش آن در 4 نوامبر به حدود 85% آمار تجمیعی رسید (153.8 در برابر 180.7 تریلیون ریال)، پس این دو هرگز با هم جمع زده نمی‌شوند؛ گروه‌های اصلی فهرست را دقیقاً افراز می‌کنند (181 ردیف = 129 ردیف در گروه 1 + 52 ردیف در گروه 3؛ گروه‌های 2، 4، 5، 6 و 7 آن روز خالی بودند)؛ `arze` برای قراردادهای مچینگ (`مچینگ`) برابر 0 است؛ عرضه‌های بدون معامله `Price` برابر null و `Quantity` برابر 0 دارند (139 ردیف از 1,184). صفحهٔ اصلی IME شبکه‌های (grid) مالی و آتی خود را هر 30 s به‌روز می‌کند؛ هیچ چیز در اینجا سریع‌تر از آن نیست.

### بورس انرژی ایران (`webapi.iee.ir`)

سایت `iee.ir` به `newsite.iee.ir` هدایت (redirect) می‌شود؛ میزبان API آن `webapi.iee.ir` است (گواهی `*.iee.ir`، معتبر تا 20 نوامبر 2026). نام‌های قدیمی‌تر کار نمی‌کنند: `irenex.ir` گواهی `*.iee.ir` را ارائه می‌دهد (تأیید TLS شکست می‌خورد: wrong principal) و در `/` پاسخ 404 می‌دهد، و `ienx.ir` در TLS handshake شکست می‌خورد.

| endpoint (روی همه `?Lang=fa`) | خروجی | حجم / تأخیر | استفاده در |
|---|---|---|---|
| `PhysicalMarket/GetTradesStatistics?PageNumber=1&PageSize=1000&FromDate=1405/08/13&ToDate=1405/08/13` | یک ردیف برای هر حراج همراه با نتیجهٔ آن، 32 فیلد: `auctionIdn`، `energySymbol`، `instrumentDisplayName`، `auctionDesc`، `targetMarketName`، `destination`، `supplierName`، `brokerName`، `tradeDateShamsi`، `auctionDateShamsi` (`1405/08/13 - 12:40`)، `totalValueRials` (رشته، `10,800,000,000`)، `totalTradedVolume`، `volumeUnitTitle`، `orderBuyTradedVolume`، `auctionVolume`، `basePrice`، `tradedAveragePrice`، `tradeMinPrice`، `tradeMaxPrice`، `priceUnitTitle`، `tradeTypeTitle`، `contractType`، `clearingType`، `kiloWattHours` ... همهٔ عددها رشته‌هایی با جداکنندهٔ هزارگان هستند. بر اساس تاریخ معامله فیلتر می‌کند؛ بنابراین سلفی که 12 آبان حراج شده اما 13 آبان معامله شده، در 13 آبان می‌آید. | 18 ردیف، 21 KB، 1.2 s؛ هفت روز: 117 ردیف، 136 KB، 1.6 s | `view="trades"` |
| `PowerMarket/GetPowerTradesStatistics` (همان query) | همان رکورد برای برق (`volumeUnitTitle` ظرفیت بر حسب kW است و `kiloWattHours` انرژی) | 7 ردیف در 13 روز، 0.5 s | `view="trades"` |
| `PhysicalMarket/GetPhysicalMarketOffersAuction?PageNumber=1&PageSize=50` | حراج‌های فیزیکی اعلام‌شده: `auctionIdn`، `instrumentDisplayName`، `auctionVolume` (`1,000 تن`)، `auctionVolumeTooltip`، `basePrice` (عبارتِ خود بورس)، `basePriceTooltip` (عدد)، `auctionDateShamsi`، `auctionTime`، `supplier`، `referencePrice`، `tradeType`، `targetMarketName`، `stepTitle` | 10 عرضه، 6 KB، 0.2 s | `view="offers"` |
| `PowerMarket/GetPowerMarketAuctionAnnouncements?PageNumber=1&PageSize=10` | اطلاعیه‌های حراج برق همراه با شرایط تحویل و پرداخت؛ **آرشیو همهٔ حراج‌ها از ابتدا** (9,626 رکورد، جدیدترین اول؛ `auctionState` برای حراج‌های برگزارشده `برگزار شده` و برای حراج‌های پیش رو خالی است) | 10 ردیف، 72 KB، 5 s (هزینه بیشتر ثابت است)؛ 40 ردیف، 252 KB، 4.3 s | `view="offers"` |
| `PhysicalMarket/GetMarketAuctionDetails/{auctionIdn}` (همتای `PowerMarket/` همین را برمی‌گرداند؛ شناسهٔ ناشناخته HTTP 400 است) | یک حراج: شرایط، `volumeUnitTitle`، `volumeUnitTitlePrice`، `convertPriceVolume`، `buyOrders` / `saleOrders` (سطح‌های قیمت با `totalQuantity`، `price`، `orderCount`) | 2 KB، 0.2 s | `view="auction"` |
| `PhysicalMarket/GetMarketAuctionDetailsTradeOnDay/{auctionIdn}` | معاملات انجام‌شده: `tradedQuantity`، `tradedPrice`، `tradedValue` (ریال)، `priceOnVolumeUnit` (`ریال/کیلوگرم`) | 0.6 KB برای هر 1 معامله | `view="auction"` |
| `Home/GetTodayMarketsValues`, `PhysicalMarket/GetPhysicalMarketAtAGlance`, `PowerMarket/GetPowerMarketAtAGlance` | وضعیت بازار (مقدار `بسته` یعنی بازار بسته است) و جمع‌های امروز؛ `tradedValue` بر حسب میلیون ریال است. در روزی که بازار بسته است صفر است | 0.4 تا 1.3 KB | `view="overview"` |

استفاده نمی‌شوند: `PhysicalMarket/GetPhysicalMarketAuctionAnnouncements` (25 s برای 3 ردیف) و حدود 100 endpoint دیگر که سایت فراخوانی می‌کند (درج‌ها و امیدنامه‌ها، اخبار، فهرست تولیدکنندگان B2B، `OilPrice/GetHydroPrices`، `Report/GetPowerMarketMonthlyPrice`، `DerivativeMarket/*`، آمار `OtherTradableSecurities/*`)؛ ابزارهای مشتقهٔ درج‌شده و گواهی‌ها از قبل در فید TSETMC هستند.

**واحدها**، که بورس در رکورد جزئیات صریحاً می‌نویسد (`volumeUnitTitlePrice` برابر `کیلوگرم`، `convertPriceVolume` برابر 1000، `priceOnVolumeUnit` برابر `ریال/کیلوگرم`) و روی هر ردیف 4 نوامبر و هفتهٔ پیش از آن با `totalValueRials` جور درمی‌آیند:

| واحد حجم | واحد قیمت | قیمت یعنی | ارزش (`totalValueRials`) = |
|---|---|---|---|
| تن (tonne) | ریال | ریال به ازای هر **کیلوگرم** | تن × 1,000 × قیمت (60 t با قیمت 180,000: 10,800,000,000) |
| تن | دلار | دلار آمریکا به ازای هر **تن** | تن × قیمت × نرخ دلار بورس (2,000 t با قیمت 598.4: 2,243,334,579,200 که از ضرب در نرخ 1,874,444 به دست می‌آید؛ این همان نرخی است که IME برای روز قبل، 1405/08/12، منتشر کرده بود) |
| مترمکعب | دلار | دلار آمریکا به ازای هر متر مکعب | حجم × قیمت × نرخ دلار |
| لیتر | ریال | ریال به ازای هر لیتر | لیتر × قیمت |
| تن | پریمیوم دلاری | پریمیوم (منفی = تخفیف) نسبت به قیمت مرجع | عدد خود بورس؛ از روی ردیف قابل محاسبه نیست |
| کیلووات در هر ساعت از دوره مصرف در دوره تحویل | ریال | ریال به ازای هر **kWh** | `kiloWattHours` × قیمت (9,000 kW برای یک هفتهٔ 168 ساعته = 1,512,000 kWh؛ × 4,500 = 6,804,000,000) |

18 حراج فیزیکی آن روز روی هم 22,620,322,449,686 ریال می‌شود (12 حراج با معامله، 6 حراج بدون معامله)، که همان عددی است که `energy_market` گزارش می‌کند.

### endpointهای `Energy` در TSETMC (بررسی شده، وصل نشده)

در bundle سایت `main.tsetmc.com` پیدا شدند (صفحه‌های «بورس انرژی»). این‌ها **همان حراج‌ها را با همان شناسه‌ها** توصیف می‌کنند (`idn` = `auctionIdn`: حراج 96520 در هر دو 60 t با قیمت 180,000 را نشان می‌دهد). به این دلیل وصل نشدند که API خود بورس انرژی غنی‌تر است (رینگ‌های فیزیکی، واحدها، معاملات به تفکیک روز) و یک میزبان هم برای مواجه شدن با محدودیت نرخ درخواست کافی است.

| endpoint | مشاهدات |
|---|---|
| `Energy/GetGetAuctionListItemByType/{active\|ready\|ended\|mazad}/{top}/{isDPE}` | `auctionListItem`؛ **فقط** `isDPE` برابر 2 (13 حراج `ended` کشف قیمت اوراق بدهی در 2019 تا 2021)، 4 (برق سبز، 5 مورد `ready`) و 5 (برق آزاد، 3 مورد `ready`) ردیف برگرداندند؛ مقدارهای 0، 1، 3، 6 تا 11 و -1 برای هر نوع خالی‌اند، پس رینگ‌های فیزیکی از این راه قابل فهرست کردن نیستند |
| `Energy/GetAuctionById/{id}` | 4 تا 10 KB؛ 56 فیلد از جمله `auctionVol`، `volUnitTitle`، `priceUnitTitle`، `baseVolUnitTitle` (`كيلوگرم`)، `stepTitle`؛ `idn` و `instrumentID` با مقدار 0 برمی‌گردند. برای حراج‌های رینگ فیزیکی که فهرست زیر نشان نمی‌دهد هم پاسخ می‌دهد (96520، نیتروژن مایع) |
| `Energy/GetAuctionOrderById/{id}/{A\|V}` | `A` = سفارش‌های خرید (عنوان صفحه: «سفارش خرید»)، `V` = سفارش‌های فروش: `[{"orderCount":3,"orderPrice":6.5,"orderQuantity":4000.0}]` |
| `Energy/GetAuctionTradeById/{id}`, `Energy/GetInstrumentTradeByAuctionId/{id}` | `[{"tradeDate":"2026-11-04T12:52:00.130","tradedPrice":180000.0,"tradedQuantity":60.0}]` |
| `Energy/GetAuctionOverview/0`, `Energy/GetPowerOverview/{60\|62\|64\|69}` | جمع حراج‌ها (`totalCount`، `totalValue`، در روزی که بازار بسته است همه 0)؛ جمع برق به تفکیک flow (`f60_MarketActivityQTotCap` برابر 476,929,008,000، `f60_MarketActivityZTotTran` برابر 6) و `marketStateTitle` برابر `بسته`؛ flowهای 6 و 71 با HTTP 500 پاسخ می‌دهند |
| `BestLimits/GetBestLimitsTopPower/{EnergyPowerBuy\|EnergyPowerSell}/{flow}/{top}/{loadType}` | سفارش‌های خرید و فروش برق (`pMeDem`، `qTitMeDem`، `title` برابر `بارپايه ماهانه 14050901`)؛ تنها فهرستی که `top_lists` هنوز آن را به‌عنوان وصل‌نشده فهرست می‌کند |
| `MarketData/GetContractBreakDownByFlow/{flow}` | flow را نادیده می‌گیرد: برای 6 و 7 یکسان، تفکیک بورس تهران را برمی‌گرداند. اینجا بی‌فایده است |

### آنچه TSETMC از قبل برای هر دو بورس دارد

`ClosingPrice/GetMarketWatch` (3,680 نماد در 5 نوامبر) تابلوهای معامله‌شونده در بورس را دارد: **flow 7** (111 ردیف: سلف‌های استاندارد `سلف` نوع 308، 38 ردیف؛ صندوق‌های کالایی نوع 380، 65 ردیف؛ گواهی‌های زعفران نوع 701، 8 ردیف) و **flow 6** (57 ردیف: سلف‌های موازی برق و هیدروکربن `سلف موازی` نوع 200، 32 ردیف؛ یک گواهی ظرفیت 201؛ صندوق‌های انرژی 315؛ محصولات بارپایهٔ روزانه/هفتگی/ماهانه 801 تا 804). `market_watch(security_type="commodity"|"energy")` و `top_lists` (گروه‌های `commodity` و `energy`، flowهای 6، 7، 60، 64، 67، 68، 69) به آن‌ها دسترسی دارند؛ دو ابزار جدید آن‌ها را تکرار نمی‌کنند.

### امتحان شده و استفاده نشده

| مورد | نتیجه |
|---|---|
| `irenex.ir`, `ienx.ir` | TLS با خطای wrong principal / شکست handshake؛ 404 در `/` (بالا را ببینید) |
| `ime.co.ir/.../MarketTotal.asmx` (`auction-total-report.html`) | JSON همراه با جدول‌های **HTML** تعبیه‌شده و **داده‌های کهنه** برمی‌گرداند (با تاریخ 1403/05/03، دو سال قدیمی) |
| `GetHomeMaliGrid`, `GetHomeAtiGrid` (شبکه‌های مالی و آتی IME) | هنگام آزمایش `[]` بود (5 نوامبر، روزی که بازار بسته بود) |
| `GetHomeFizikiContractChartData` | با آرگومان‌هایی که صفحه می‌سازد HTTP 500 می‌دهد |
| `gold.ime.co.ir`, `silver.ime.co.ir`, `cdc.ime.co.ir` (پورتال‌های گواهی) | اپلیکیشن‌های تک‌صفحه‌ای (پوستهٔ 2.6 KB)؛ بیشتر بررسی نشدند |
| `GetAmareMoamelatList` با `"fari":true` | بازار فرعی: بدون قیمت، در ابزار ارائه نمی‌شود |

### تناوب به‌روزرسانی، ساعت‌ها و محدودیت‌های مشاهده‌شده

IME و بورس انرژی پس از پایان جلسه منتشر می‌کنند؛ هر دو پنجشنبه و جمعه بسته‌اند (فهرست IME برای پنجشنبه 1405/08/14 برابر `[]` است، نمای کلی بورس انرژی `بسته` می‌گوید و صفر نشان می‌دهد)، و عرضه‌های بعدی که پنجشنبه اعلام می‌شوند برای شنبه هستند. سایت‌ها جدول‌های خود را هر 30 s (شبکه‌های مالی و آتی IME)، هر 1.5 s (ویجت‌های نمای کلی بورس انرژی) و هر 2 تا 4 دقیقه (صفحه‌های انرژی TSETMC) به‌صورت دوره‌ای (poll) از سرور می‌گیرند، به همین دلیل ابزارها 30 s تا 2 دقیقه کش می‌کنند. حدود 150 درخواست API به این سه میزبان (یکی پس از دیگری، با فاصلهٔ 1 تا 2 s؛ به‌علاوهٔ حدود 160 فایل اسکریپت ثابت سایت‌ها) نه HTTP 429 تولید کرد و نه 403؛ مدیریت موجود client (تلاش مجدد با back-off، دورهٔ سردشدن 60 s برای هر میزبان پس از 429) بدون تغییر اعمال می‌شود. کندترین فراخوانی‌ها اطلاعیه‌های برق بورس انرژی (حدود 5 s) و اطلاعیه‌های فیزیکی آن (25 s، استفاده نمی‌شود) هستند.

## هنوز پوشش داده نمی‌شود

یونانی‌های اختیار (Option Greeks) و نوسان ضمنی (`option_chain` فقط moneyness، ارزش ذاتی و ارزش زمانی را می‌دهد)، وزن شاخص‌ها (بورس هیچ‌کدام را منتشر نمی‌کند؛ `index_constituents` به‌جای آن اثر هر سهم را بر حسب واحد شاخص می‌دهد)، جدول تعطیلات سال شمسی 1406 و هر تعطیلی که بورس بدون اطلاع قبلی تصمیم بگیرد، بازار فرعی IME (`"fari":true`) و پورتال‌های طلا، نقره و گواهی آن، endpointهای حراج `Energy` در TSETMC و سفارش‌های خرید و فروش برق (`GetBestLimitsTopPower`)، و آمار مشتقه و گواهی در بورس انرژی (ابزارهای آن‌ها در `top_lists` هستند).

</div>
