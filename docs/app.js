/* iran-bourse-mcp site. No dependencies. All numbers come from data.js (generated from the repo). */
(function () {
  "use strict";
  var D = window.SITE_DATA || { tools: [], clients: [], snapshot: {} };
  var SNAP = D.snapshot || {};
  var GIT = "git+https://github.com/msmahdinejad/iran-bourse-mcp";
  var reduceMotion = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var esc = function (s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }

  /* ------------------------------------------------------------------ i18n */
  var T = {
    en: {
      "nav.why": "Why", "nav.screener": "Screener",
      "scr.eyebrow": "New: stock screener", "scr.h2": "The filter box of tsetmc.com, written by your agent.",
      "scr.lead": "Say what you want in plain words. The agent writes a short condition and gets back only the stocks that pass it right now, with the evidence for each hit.", "scr.you": "You",
      "scr.q": "Stocks trading over twice their 20-day average volume, up more than 1% yesterday, positive today, and over 5 billion rial traded.",
      "scr.c1.h": "Today and 60 days back", "scr.c1.p": "Live values, yesterday (close[1]), averages (avg(volume, 20)), streaks (all(close_pct > 0, 3)) and highs over any window, adjusted for capital increases.",
      "scr.c2.h": "3,700 instruments, real money, order book", "scr.c2.p": "Shares, funds, bonds, options and futures from the exchange's own feed, with real vs legal flow, a five-level book, base volume and fund NAV.",
      "scr.c3.h": "Safe, and it explains itself", "scr.c3.p": "Conditions are parsed, never executed. Mistakes come back with suggestions, 15 presets are built in, and every hit shows the numbers behind it.",
      "scr.link": "Read the screener guide: every field, function and preset.", "scr.col.symbol": "Symbol", "scr.col.y": "Yesterday", "scr.col.t": "Today", "scr.col.v": "Volume vs 20-day avg", "scr.col.val": "Value (bn rial)", "nav.bench": "Benchmarks", "nav.install": "Install", "nav.tools": "Tools", "nav.faq": "FAQ",
      "copy": "Copy", "copied": "Copied", "replay": "Replay", "works": "Works with",
      "hero.eyebrow": "Model Context Protocol · open source · MIT",
      "hero.h1": "Your AI agent, on the <em>Tehran Stock Exchange.</em>",
      "hero.lead": "40 read-only tools that hand any agent the quotes, order book, tick-by-tick trades, real vs legal money flow, shareholders, a stock screener, options, indices, funds and Codal filings of TSETMC. Clean, labelled, and ready to reason about.",
      "hero.cta1": "Connect your agent", "hero.cta2": "See the numbers",
      "panel.vwap": "VWAP", "panel.ticks": "Ticks", "panel.power": "Buyer power",
      "why.eyebrow": "The problem", "why.h2": "An agent with a browser still cannot read this market.",
      "why.lead": "We tested it. The market's data exists, but it is hidden behind JavaScript, written in codes, and shipped in megabytes.",
      "why.c1.h": "The site is an empty shell", "why.c1.p": "Fetching a symbol page from tsetmc.com returns a title and nothing else. Codal's report list comes back as unrendered template placeholders.",
      "why.c2.h": "The hidden API speaks in codes", "why.c2.p": "The JSON endpoints that hold the data use cryptic names and have traps. The exchange's own change field said zero for a stock that rose 120 rial.",
      "why.c3.h": "One day of ticks is 3 MB", "why.c3.p": "Order-book history is a delta feed that must be reassembled, shareholder rows come back twice, and a symbol's messages weigh 3.5 MB. None of it fits a context window.",
      "cmp.eyebrow": "Same question, two agents", "cmp.h2": "“Did Foolad move today?”",
      "cmp.without": "Without MCP · agent with a browser", "cmp.with": "With iran-bourse-mcp",
      "cmp.note": "Outputs shown are real, captured on 2026-11-03. The browser-only agent cannot even find the data; an agent that guesses the hidden endpoint can be misled by its fields.",
      "bench.eyebrow": "Measured, not claimed", "bench.h2": "Fewer tokens, fewer requests, right answers.",
      "bench.lead": "Everyday tasks, run against the live exchange. The raw route is the best case for an agent that already knows the hidden endpoints.",
      "bench.tok.h": "Tokens the model must read", "bench.tok.sub": "Log scale. Raw JSON payload vs the MCP response.",
      "bench.time.h": "Wall-clock time to the data", "bench.time.sub": "Seconds. Sequential raw requests vs one tool call. Single-endpoint tasks take about as long either way.",
      "bench.req.h": "HTTP requests the agent must make", "bench.req.sub": "Log scale. MCP always needs one call.",
      "bench.acc.h": "Agent trials: accuracy", "bench.agents.h": "Agent trials: cost of getting the answer",
      "bench.traps.h": "Traps in the raw data that give confident wrong answers", "bench.traps.sub": "Each was found on the live endpoints and is handled by the server.",
      "inst.eyebrow": "Install", "inst.h2": "Three steps. Any agent.",
      "inst.lead": "One server, every client that speaks MCP. Pick yours below, or use the shell command if your agent has no MCP support.",
      "inst.s1": "1 · Get uv", "inst.s1p": "uv runs the server without a manual install.",
      "inst.s2": "2 · Check access", "inst.s2p": "From a machine in Iran, confirm TSETMC and Codal answer.",
      "inst.s3": "3 · Connect", "inst.s3p": "Choose your agent. Some have a one-click link or an auto-installer.",
      "ex.eyebrow": "Ask in Persian", "ex.h2": "Questions that used to take an analyst an hour.",
      "tools.eyebrow": "40 tools", "tools.h2": "Everything TSETMC shows, and what it hides.", "tools.lead": "Every tool is read-only, returns units explicitly, and labels anything it derives.",
      "how.eyebrow": "How it works", "how.h2": "One pure core, three public sources.", "how.lead": "Transformation logic is separate from I/O, so every number can be tested offline against recorded real data. Facts are returned as published; derived numbers are labelled.",
      "trust.eyebrow": "Built to be trusted", "trust.h2": "Correctness first, then convenience.",
      "faq.h2": "Questions, answered.", "final.h2": "Give your agent the market.", "final.lead": "Free, open source, read-only. Star it if it saves you an afternoon.", "final.issue": "Report an issue",
      "foot.tools": "Tool reference", "foot.data": "Data notes", "foot.contrib": "Contributing",
      "foot.disc": "Unofficial. Not affiliated with TSETMC, the Tehran Stock Exchange, Fara Bourse or Codal. Information only, not investment advice. Market data belongs to its owners."
    },
    fa: {
      "nav.why": "چرا", "nav.screener": "اسکرینر",
      "scr.eyebrow": "جدید: اسکرینر سهام", "scr.h2": "فیلتر نویسیِ سایت tsetmc، این بار توسط ایجنتِ شما.",
      "scr.lead": "به زبان ساده بگویید چه می‌خواهید. ایجنت یک شرط کوتاه می‌نویسد و فقط سهم‌هایی را می‌گیرد که همین لحظه از آن رد می‌شوند، همراه با شاهد هر نتیجه.", "scr.you": "شما",
      "scr.q": "سهم‌هایی که حجمشان از دو برابر میانگین ۲۰ روزه بیشتر است، دیروز بیش از ۱٪ رشد کرده‌اند، امروز مثبت‌اند و ارزش معاملاتشان بالای ۵ میلیارد ریال است.",
      "scr.c1.h": "امروز و تا ۶۰ روز قبل", "scr.c1.p": "مقدار لحظه‌ای، دیروز (close[1])، میانگین‌ها (avg(volume, 20))، روند متوالی (all(close_pct > 0, 3)) و سقف و کف هر بازه، تعدیل‌شده برای افزایش سرمایه.",
      "scr.c2.h": "۳٬۷۰۰ نماد، پول حقیقی، عمق بازار", "scr.c2.p": "سهام، صندوق، اوراق، اختیار و آتی از فید خودِ بورس، همراه با حقیقی/حقوقی، عمق ۵ سطری، حجم مبنا و NAV صندوق.",
      "scr.c3.h": "امن، و خودش را توضیح می‌دهد", "scr.c3.p": "شرط‌ها فقط تحلیل می‌شوند و هرگز اجرا نمی‌شوند. خطا با پیشنهاد اصلاح برمی‌گردد، ۱۵ فیلتر آماده دارد و هر نتیجه اعدادِ پشتش را نشان می‌دهد.",
      "scr.link": "راهنمای اسکرینر: همه‌ی فیلدها، توابع و فیلترهای آماده.", "scr.col.symbol": "نماد", "scr.col.y": "دیروز", "scr.col.t": "امروز", "scr.col.v": "حجم نسبت به میانگین ۲۰ روزه", "scr.col.val": "ارزش (میلیارد ریال)", "nav.bench": "بنچمارک", "nav.install": "نصب", "nav.tools": "ابزارها", "nav.faq": "سؤالات",
      "copy": "کپی", "copied": "کپی شد", "replay": "پخش دوباره", "works": "سازگار با",
      "hero.eyebrow": "Model Context Protocol · متن‌باز · MIT",
      "hero.h1": "ایجنت هوش مصنوعی‌تان، روی <em>بورس تهران.</em>",
      "hero.lead": "۴۰ ابزار فقط‌خواندنی که قیمت، عمق بازار، ریز معاملات، ورود و خروج پول حقیقی و حقوقی، سهامداران عمده، اسکرینر و فیلتر نویس، اختیار معامله، شاخص‌ها، صندوق‌ها و اطلاعیه‌های کدال را به هر ایجنتی می‌دهد. تمیز، برچسب‌دار و آماده‌ی تحلیل.",
      "hero.cta1": "ایجنتم را وصل کن", "hero.cta2": "عددها را ببین",
      "panel.vwap": "میانگین وزنی", "panel.ticks": "معاملات", "panel.power": "قدرت خریدار",
      "why.eyebrow": "مسئله", "why.h2": "ایجنتی که فقط مرورگر دارد هنوز نمی‌تواند این بازار را بخواند.",
      "why.lead": "تست کردیم. داده هست، ولی پشت جاوااسکریپت پنهان است، با کد نوشته شده و در حجم مگابایتی می‌آید.",
      "why.c1.h": "سایت یک پوسته‌ی خالی است", "why.c1.p": "صفحه‌ی نماد در tsetmc.com فقط یک عنوان برمی‌گرداند. لیست گزارش‌های کدال هم با قالب‌های رندرنشده می‌آید.",
      "why.c2.h": "API پنهان با کد حرف می‌زند", "why.c2.p": "endpoint های JSON که داده را دارند اسم‌های رمزی دارند و تله دارند. فیلد تغییر قیمتِ خودِ بورس برای سهمی که ۱۲۰ ریال بالا رفته بود صفر بود.",
      "why.c3.h": "ریز معاملات یک روز ۳ مگابایت است", "why.c3.p": "تاریخچه‌ی عمق بازار «تغییرات» است و باید بازسازی شود، ردیف سهامداران دوبار می‌آید و پیام‌های یک نماد ۳٫۵ مگابایت است. هیچ‌کدام در context ایجنت جا نمی‌شود.",
      "cmp.eyebrow": "یک سؤال، دو ایجنت", "cmp.h2": "«فولاد امروز تکان خورد؟»",
      "cmp.without": "بدون MCP · ایجنت با مرورگر", "cmp.with": "با iran-bourse-mcp",
      "cmp.note": "خروجی‌ها واقعی‌اند و ۱۲ آبان ۱۴۰۵ ضبط شده‌اند. ایجنتِ فقط‌مرورگر حتی داده را پیدا نمی‌کند؛ ایجنتی که endpoint پنهان را حدس بزند هم با فیلدهایش گمراه می‌شود.",
      "bench.eyebrow": "اندازه‌گیری‌شده، نه ادعا", "bench.h2": "توکن کمتر، درخواست کمتر، جواب درست.",
      "bench.lead": "کارهای روزمره روی بورس واقعی اجرا شد. مسیر خام بهترین حالت ممکن برای ایجنتی است که endpoint های پنهان را از قبل می‌شناسد.",
      "bench.tok.h": "توکنی که مدل باید بخواند", "bench.tok.sub": "مقیاس لگاریتمی. حجم JSON خام در برابر پاسخ MCP.",
      "bench.time.h": "زمان رسیدن به داده", "bench.time.sub": "ثانیه. درخواست‌های متوالی خام در برابر یک فراخوانی ابزار. کارهای تک‌endpoint در هر دو حالت زمان مشابهی دارند.",
      "bench.req.h": "درخواست HTTP لازم", "bench.req.sub": "مقیاس لگاریتمی. با MCP همیشه یک فراخوانی کافی است.",
      "bench.acc.h": "آزمون ایجنت‌ها: دقت", "bench.agents.h": "آزمون ایجنت‌ها: هزینه رسیدن به جواب",
      "bench.traps.h": "تله‌های داده‌ی خام که جواب غلطِ مطمئن می‌دهند", "bench.traps.sub": "همه روی endpoint های زنده پیدا شدند و سرور آن‌ها را مدیریت می‌کند.",
      "inst.eyebrow": "نصب", "inst.h2": "سه قدم. هر ایجنتی.",
      "inst.lead": "یک سرور، برای هر کلاینتی که MCP بلد است. ایجنتتان را انتخاب کنید، یا اگر MCP ندارد از دستور شل استفاده کنید.",
      "inst.s1": "۱ · نصب uv", "inst.s1p": "uv سرور را بدون نصب دستی اجرا می‌کند.",
      "inst.s2": "۲ · بررسی دسترسی", "inst.s2p": "از سیستمی داخل ایران بررسی کنید TSETMC و کدال جواب می‌دهند.",
      "inst.s3": "۳ · اتصال", "inst.s3p": "ایجنتتان را انتخاب کنید. بعضی لینک یک‌کلیکی یا نصب‌کننده‌ی خودکار دارند.",
      "ex.eyebrow": "فارسی بپرسید", "ex.h2": "سؤال‌هایی که قبلاً یک ساعت از وقت تحلیلگر می‌گرفت.",
      "tools.eyebrow": "۴۰ ابزار", "tools.h2": "هرچه TSETMC نشان می‌دهد، و هرچه پنهان می‌کند.", "tools.lead": "همه‌ی ابزارها فقط‌خواندنی‌اند، واحد را صریح می‌گویند و هر چیز محاسبه‌شده را برچسب می‌زنند.",
      "how.eyebrow": "چطور کار می‌کند", "how.h2": "یک هسته‌ی خالص، سه منبع عمومی.", "how.lead": "منطق تبدیل داده از I/O جداست، پس هر عدد را می‌شود آفلاین روی داده‌ی واقعی ضبط‌شده تست کرد. واقعیت‌ها همان‌طور که منتشر شده‌اند برمی‌گردند و عددهای محاسبه‌شده برچسب دارند.",
      "trust.eyebrow": "ساخته‌شده برای اعتماد", "trust.h2": "اول درستی، بعد راحتی.",
      "faq.h2": "پرسش‌ها و پاسخ‌ها.", "final.h2": "بازار را به ایجنتتان بدهید.", "final.lead": "رایگان، متن‌باز، فقط‌خواندنی. اگر یک بعدازظهر از وقتتان را نجات داد، ستاره بدهید.", "final.issue": "گزارش مشکل",
      "foot.tools": "مرجع ابزارها", "foot.data": "نکات داده", "foot.contrib": "مشارکت",
      "foot.disc": "غیررسمی است و هیچ ارتباطی با TSETMC، بورس تهران، فرابورس یا کدال ندارد. فقط اطلاعات است و توصیه سرمایه‌گذاری نیست. داده‌ی بازار متعلق به صاحبان آن است."
    }
  };
  var lang = store("lang") || ((navigator.language || "en").toLowerCase().indexOf("fa") === 0 ? "fa" : "en");
  var t = function (k) { return (T[lang] && T[lang][k]) || T.en[k] || k; };
  // data stays in Latin digits in both languages: monospaced fonts have no Persian digits and traders read prices that way
  var nf = function (n, d) { return Number(n).toLocaleString("en-US", { maximumFractionDigits: d == null ? 0 : d }); };

  function applyLang() {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "fa" ? "rtl" : "ltr";
    $$("[data-i18n]").forEach(function (el) { el.textContent = t(el.getAttribute("data-i18n")); });
    $$("[data-i18n-html]").forEach(function (el) { el.innerHTML = t(el.getAttribute("data-i18n-html")); });
    $("#lang").textContent = lang === "fa" ? "English" : "فارسی";
    var s = $("#tool-search"); if (s) s.placeholder = lang === "fa" ? "جستجوی ابزار: عمق بازار، صف، کدال…" : "Search tools: order book, queue, codal…";
    renderAll();
  }

  /* ------------------------------------------------------------------ theme */
  function applyTheme(mode) {
    if (mode === "light" || mode === "dark") document.documentElement.setAttribute("data-theme", mode);
    else document.documentElement.removeAttribute("data-theme");
  }
  var themeMode = store("theme") || "";
  applyTheme(themeMode);
  $("#theme").addEventListener("click", function () {
    var current = themeMode || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    themeMode = current === "dark" ? "light" : "dark";
    store("theme", themeMode); applyTheme(themeMode);
  });
  $("#lang").addEventListener("click", function () { lang = lang === "fa" ? "en" : "fa"; store("lang", lang); applyLang(); });

  /* ------------------------------------------------------------------ copy */
  function copyText(text, btn) {
    var done = function () { if (!btn) return; var o = btn.textContent; btn.textContent = t("copied"); btn.classList.add("done"); setTimeout(function () { btn.textContent = o === t("copied") ? t("copy") : o; btn.classList.remove("done"); }, 1400); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, function () { fallbackCopy(text); done(); });
    else { fallbackCopy(text); done(); }
  }
  function fallbackCopy(text) { var ta = document.createElement("textarea"); ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0"; document.body.appendChild(ta); ta.select(); try { document.execCommand("copy"); } catch (e) { } document.body.removeChild(ta); }
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-copy-target]");
    if (b) { var el = document.getElementById(b.getAttribute("data-copy-target")); copyText((el.textContent || "").replace(/^\$\s*/, ""), b); return; }
    var c = e.target.closest("[data-copy-pre]");
    if (c) { copyText(c.parentElement.querySelector("pre").textContent, c); }
  });

  /* ------------------------------------------------------------------ hero */
  function renderTape() {
    var tape = SNAP.tape || [];
    var item = function (r) { var cls = r.pct >= 0 ? "up" : "down"; return '<span class="tape-item"><b>' + esc(r.symbol) + "</b><span>" + nf(r.last) + '</span><span class="' + cls + '">' + (r.pct >= 0 ? "+" : "") + r.pct.toFixed(2) + "%</span></span>"; };
    var html = tape.map(item).join("");
    $("#tape").innerHTML = html + html;
  }
  function renderWorks() {
    var el = $("#works"); var names = (D.clients || []).filter(function (c) { return c.id !== "generic"; }).map(function (c) { return c.label; });
    el.innerHTML = '<span>' + esc(t("works")) + "</span>" + names.slice(0, 9).map(function (n) { return '<span class="chip">' + esc(n) + "</span>"; }).join("") + '<span class="chip">+' + (names.length - 9) + "</span>";
  }
  var ladderTimer;
  function renderPanel() {
    var f = SNAP.foolad; if (!f) return;
    var q = f.quote, ob = f.order_book;
    $("#p-name").textContent = (f.identity && f.identity.name_en) || "";
    $("#p-price").textContent = nf(q.last.price);
    var pct = q.last.change_pct; var b = $("#p-pct"); b.textContent = (pct >= 0 ? "+" : "") + pct.toFixed(2) + "%"; b.classList.toggle("neg", pct < 0);
    $("#p-state").textContent = lang === "fa" ? "تصویر لحظه‌ای" : "snapshot";
    $("#p-vwap").textContent = nf(q.vwap, 1);
    var ts = f.trade_summary; $("#p-ticks").textContent = nf(ts.summary.ticks);
    var rl = f.real_legal; $("#p-power").textContent = rl && rl.real_buyer_power != null ? rl.real_buyer_power.toFixed(2) : "—";
    $("#p-snap").textContent = (lang === "fa" ? "داده‌ی واقعی · " : "Real data · ") + (SNAP.captured_at_utc || "");
    var asks = (ob.asks || []).slice(0, 5).reverse(), bids = (ob.bids || []).slice(0, 5);
    var all = asks.concat(bids); var max = Math.log10(Math.max.apply(null, all.map(function (x) { return x.volume; })) + 10);
    var row = function (x, kind) { return '<div class="lvl ' + kind + '"><span class="px">' + nf(x.price) + '</span><span><span class="bar" data-v="' + x.volume + '" style="display:block;width:' + Math.max(4, Math.log10(x.volume + 10) / max * 100).toFixed(1) + '%"></span></span><span class="vol">' + nf(x.volume) + "</span></div>"; };
    $("#ladder").innerHTML = asks.map(function (x) { return row(x, "ask"); }).join("") + '<div class="mid"></div>' + bids.map(function (x) { return row(x, "bid"); }).join("");
    clearInterval(ladderTimer);
    if (!reduceMotion) ladderTimer = setInterval(function () {
      $$("#ladder .bar").forEach(function (bar) { var v = Number(bar.getAttribute("data-v")) * (0.7 + Math.random() * 0.6); bar.style.width = Math.max(4, Math.min(100, Math.log10(v + 10) / max * 100)).toFixed(1) + "%"; });
    }, 1700);
  }
  function renderStats() {
    var tools = (D.tools || []).length, clients = (D.clients || []).filter(function (c) { return c.id !== "generic"; }).length;
    var cov = f_cov();
    var cells = [[nf(tools), lang === "fa" ? "ابزار فقط‌خواندنی" : "read-only tools"], [nf(clients), lang === "fa" ? "ایجنت و IDE، به‌علاوه هر کلاینت MCP" : "agents and IDEs, plus any MCP client"], [cov, lang === "fa" ? "پوشش ریز معاملات نسبت به آمار رسمی" : "tick coverage vs official totals"], [nf(D.tests || 107), lang === "fa" ? "تست آفلاین، دو نسل MCP SDK" : "offline tests, two MCP SDK generations"]];
    $("#stats").innerHTML = cells.map(function (c) { return "<div><b>" + esc(c[0]) + "</b><span>" + esc(c[1]) + "</span></div>"; }).join("");
  }
  function f_cov() { try { return SNAP.foolad.trade_summary.completeness.volume_coverage_pct.toFixed(0) + "%"; } catch (e) { return "100%"; } }

  /* ------------------------------------------------------------------ terminals */
  var TERMS = {
    "t-bad": [
      ["p", "$ "], ["", "fetch https://tsetmc.com/instInfo/46348559193224090\n"],
      ["no", "→ 200 · 38 chars: \".:TSETMC:. :: مدیریت فناوری بورس تهران\"\n"], ["dim", "  (a JavaScript shell: no price, no volume)\n\n"],
      ["p", "$ "], ["", "fetch https://www.codal.ir/ReportList.aspx?Symbol=فولاد\n"],
      ["no", "→ {{::letter.Title}}   {{::letter.PublishDateTime}}\n\n"],
      ["p", "$ "], ["", "curl cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceInfo/4634…\n"],
      ["", "→ \"priceChange\": "], ["no", "0.0"], ["", ", \"pClosing\": 4210.0, \"priceYesterday\": 4090.0\n\n"],
      ["", "taking the field at face value: \"Foolad did not move today.\"  "], ["no", "✗ wrong (+120 rial, +2.93%)"]
    ],
    "t-good": [
      ["p", "> "], ["", "quote(symbol=\"فولاد\")\n"],
      ["ok", "→ last 4,210 (+2.93%) · at the upper price limit\n"], ["dim", "  vwap 4,208.49 · volume 646,253,701 · P/E 6.08\n\n"],
      ["p", "> "], ["", "trade_summary(symbol=\"فولاد\", date=\"2026-11-02\")\n"],
      ["ok", "→ 15,643 ticks · coverage 100.0% of official volume\n"], ["dim", "  biggest trade 09:11:28 · 299,880 sh · point of control 4,210\n\n"],
      ["p", "> "], ["", "order_book(symbol=\"فولاد\")\n"],
      ["ok", "→ buy queue 189,651,617 sh · 1,345 orders\n\n"],
      ["", "reading: \"Foolad is up 2.93% and locked at its price ceiling.\"  "], ["ok", "✓"]
    ]
  };
  var typing = {};
  function typeInto(id, instant) {
    var el = document.getElementById(id), parts = TERMS[id]; if (!el) return;
    clearTimeout(typing[id]);
    var full = function () { el.innerHTML = parts.map(function (p) { return p[0] ? '<span class="' + p[0] + '">' + esc(p[1]) + "</span>" : esc(p[1]); }).join(""); };
    if (instant || reduceMotion) { full(); return; }
    var i = 0, c = 0, html = "";
    (function step() {
      if (i >= parts.length) { full(); return; }
      var p = parts[i], chunk = p[1].slice(0, c + 3); c += 3;
      var cur = parts.slice(0, i).map(function (x) { return x[0] ? '<span class="' + x[0] + '">' + esc(x[1]) + "</span>" : esc(x[1]); }).join("");
      el.innerHTML = cur + (p[0] ? '<span class="' + p[0] + '">' + esc(chunk) + "</span>" : esc(chunk));
      if (chunk.length >= p[1].length) { i++; c = 0; }
      typing[id] = setTimeout(step, 14);
    })();
  }
  function initTerminals() {
    typeInto("t-bad", true); typeInto("t-good", true);
    var seen = false;
    if ("IntersectionObserver" in window) new IntersectionObserver(function (es, o) { es.forEach(function (e) { if (e.isIntersecting && !seen) { seen = true; typeInto("t-bad"); setTimeout(function () { typeInto("t-good"); }, 900); o.disconnect(); } }); }, { threshold: 0.35 }).observe($("#compare .versus"));
    $$("[data-replay]").forEach(function (b) { b.addEventListener("click", function () { typeInto(b.getAttribute("data-replay")); }); });
  }

  /* ------------------------------------------------------------------ charts */
  var SERIES = { raw: { key: "raw", c: "var(--s2)", en: "Raw API route", fa: "مسیر خام API" }, mcp: { key: "mcp", c: "var(--s1)", en: "iran-bourse-mcp", fa: "iran-bourse-mcp" } };
  var TASKS_FA = { quote: "قیمت لحظه‌ای", order_book: "عمق بازار و صف", trade_summary: "خلاصه ریز معاملات یک روز", real_legal_14d: "حقیقی/حقوقی ۱۰ روز", real_legal_10d: "حقیقی/حقوقی ۱۰ روز", shareholders: "سهامداران عمده", buy_queues: "رتبه‌بندی صف‌های خرید بازار", codal_5: "۵ اطلاعیه کدال", price_history_1y: "قیمت یک‌ساله تعدیل‌شده", screen_surge: "اسکرین کل بازار (حجم، روند دیروز)" };
  var TASKS_EN = { quote: "Live quote", order_book: "Order book + queue", trade_summary: "One day of ticks", real_legal_10d: "Real/legal flow, 10 days", shareholders: "Major shareholders", buy_queues: "Market-wide buy queues", codal_5: "Latest 5 Codal filings", price_history_1y: "1 year adjusted prices", screen_surge: "Market-wide screen (volume, yesterday's trend)" };
  var tip = $("#tip");
  function showTip(e, html) { tip.innerHTML = html; tip.hidden = false; var x = Math.min(e.clientX + 14, innerWidth - 280), y = e.clientY + 16; tip.style.left = x + "px"; tip.style.top = y + "px"; }
  function hideTip() { tip.hidden = true; }

  function hbar(cfg) {
    var host = document.getElementById(cfg.chart);
    var W = Math.max(300, Math.min(760, host.clientWidth || 720)), narrow = W < 520;
    var labelW = narrow ? 0 : 178, x0 = narrow ? 6 : labelW + 12, x1 = W - (narrow ? 50 : 76), head = narrow ? 18 : 0;
    var rowH = head + 22 + cfg.series.length * 16, top = 6, H = top + cfg.cats.length * rowH + 28;
    var all = []; cfg.cats.forEach(function (c) { cfg.series.forEach(function (s) { var v = cfg.values[c.id] && cfg.values[c.id][s.key]; if (v != null) all.push(v); }); });
    var sx, ticks = [];
    if (cfg.scale === "log") {
      var lowV = cfg.domainMin || Math.min.apply(null, all) * 0.8, highV = Math.max.apply(null, all) * 1.25;
      var lo = Math.log10(lowV), hi = Math.log10(highV);
      for (var p = Math.ceil(lo); p <= Math.floor(hi); p++) ticks.push(Math.pow(10, p));
      sx = function (v) { return x0 + (Math.log10(Math.max(v, lowV)) - lo) / (hi - lo) * (x1 - x0); };
    } else {
      var max = Math.max.apply(null, all) * 1.08, step = niceStep(max / 4);
      for (var q = 0; q <= max; q += step) ticks.push(q);
      sx = function (v) { return x0 + v / ticks[ticks.length - 1] * (x1 - x0); };
    }
    var s = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="' + esc(cfg.aria) + '">';
    ticks.forEach(function (tv) { var x = sx(tv); s += '<line class="gridline" x1="' + x + '" x2="' + x + '" y1="' + top + '" y2="' + (H - 24) + '"/><text class="tick" x="' + x + '" y="' + (H - 8) + '" text-anchor="middle">' + cfg.tick(tv) + "</text>"; });
    cfg.cats.forEach(function (c, i) {
      var y = top + i * rowH + 6;
      if (narrow) s += '<text x="' + x0 + '" y="' + (y + 11) + '" font-size="12.5">' + esc(c.label) + "</text>";
      else s += '<text x="' + labelW + '" y="' + (y + (cfg.series.length * 16) / 2 + 3) + '" text-anchor="end" font-size="13">' + esc(c.label) + "</text>";
      cfg.series.forEach(function (se, j) {
        var v = cfg.values[c.id] && cfg.values[c.id][se.key]; if (v == null) return;
        var by = y + head + j * 16, w = Math.max(2, sx(v) - x0), r = Math.min(4, w / 2);
        var path = "M" + x0 + " " + by + "h" + (w - r) + "a" + r + " " + r + " 0 0 1 " + r + " " + r + "v" + (14 - 2 * r) + "a" + r + " " + r + " 0 0 1 -" + r + " " + r + "h-" + (w - r) + "z";
        s += '<path class="bar" d="' + path + '" fill="' + se.c + '" data-tip="' + esc(cfg.tip(c, se, v)) + '"/>';
        s += '<text class="val" x="' + (x0 + w + 6) + '" y="' + (by + 11) + '">' + cfg.fmt(v) + "</text>";
      });
    });
    s += "</svg>";
    var legend = cfg.series.map(function (se) { return '<span><i style="background:' + se.c + '"></i>' + esc(se.name) + "</span>"; }).join("");
    var table = '<details class="tbl"><summary>' + (lang === "fa" ? "نمایش جدول" : "View as table") + '</summary><div class="table-wrap"><table><thead><tr><th></th>' + cfg.series.map(function (se) { return "<th>" + esc(se.name) + "</th>"; }).join("") + "</tr></thead><tbody>" +
      cfg.cats.map(function (c) { return "<tr><td>" + esc(c.label) + "</td>" + cfg.series.map(function (se) { var v = cfg.values[c.id] && cfg.values[c.id][se.key]; return '<td class="num">' + (v == null ? "—" : cfg.fmt(v)) + "</td>"; }).join("") + "</tr>"; }).join("") + "</tbody></table></div></details>";
    host.innerHTML = s + table;
    document.getElementById(cfg.legend).innerHTML = legend;
    $$("#" + cfg.chart + " .bar").forEach(function (b) { b.addEventListener("mousemove", function (e) { showTip(e, b.getAttribute("data-tip")); }); b.addEventListener("mouseleave", hideTip); });
  }
  function niceStep(x) { var p = Math.pow(10, Math.floor(Math.log10(x))), n = x / p; return (n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10) * p; }
  var compact = function (v) { return v >= 1e6 ? (v / 1e6).toFixed(v % 1e6 ? 1 : 0) + "M" : v >= 1e3 ? (v / 1e3).toFixed(v % 1e3 ? 1 : 0) + "K" : String(v); };

  function renderBench() {
    var dp = D.bench_data_plane;
    var wrap = $("#benchmarks");
    if (!dp) { wrap.style.display = "none"; return; }
    var names = lang === "fa" ? TASKS_FA : TASKS_EN;
    var cats = dp.tasks.map(function (x) { return { id: x.id, label: names[x.id] || x.title }; });
    var mk = function (field) { var v = {}; dp.tasks.forEach(function (x) { v[x.id] = { raw: x.raw[field], mcp: x.mcp[field] }; }); return v; };
    var series = [{ key: "raw", name: SERIES.raw[lang], c: SERIES.raw.c }, { key: "mcp", name: SERIES.mcp[lang], c: SERIES.mcp.c }];
    var ratio = function (x, f) { return x.raw[f] / Math.max(x.mcp[f], 1e-9); };
    hbar({ chart: "ch-tok", legend: "lg-tok", cats: cats, series: series, values: mk("tokens"), scale: "log", aria: "Tokens per task", fmt: function (v) { return compact(Math.round(v)); }, tick: compact,
      tip: function (c, se, v) { var x = dp.tasks.filter(function (k) { return k.id === c.id; })[0]; return "<b>" + esc(c.label) + "</b><br>" + esc(se.name) + ": " + nf(v) + " tokens" + (se.key === "mcp" ? "<br>÷" + nf(ratio(x, "tokens"), 0) + (lang === "fa" ? " کمتر" : " fewer") : ""); } });
    hbar({ chart: "ch-time", legend: "lg-time", cats: cats, series: series, values: mk("seconds"), scale: "linear", aria: "Seconds per task", fmt: function (v) { return v.toFixed(1) + "s"; }, tick: function (v) { return v + "s"; },
      tip: function (c, se, v) { return "<b>" + esc(c.label) + "</b><br>" + esc(se.name) + ": " + v.toFixed(2) + " s"; } });
    hbar({ chart: "ch-req", legend: "lg-req", cats: cats, series: series, values: mk("requests"), scale: "log", domainMin: 0.5, aria: "Requests per task", fmt: function (v) { return nf(v); }, tick: function (v) { return v; },
      tip: function (c, se, v) { return "<b>" + esc(c.label) + "</b><br>" + esc(se.name) + ": " + nf(v) + " HTTP requests"; } });

    // traps
    var TRAP = {
      price_change_field: ["The exchange's change field", "فیلد تغییر قیمتِ خودِ بورس"], shareholder_rows_doubled: ["Shareholder rows (dated endpoint)", "ردیف سهامداران (endpoint تاریخی)"],
      client_type_field_names: ["Real-buyer count key on history rows", "کلید تعداد خریدار حقیقی در ردیف‌های تاریخی"], queue_false_positives: ["Buy queues guessed from market watch alone", "صف خرید حدس‌زده فقط از دیده‌بان"],
      arabic_letters: ["Matching Persian input to Arabic letters", "تطبیق ورودی فارسی با حروف عربی"]
    };
    $("#traps").innerHTML = (dp.traps || []).map(function (x) {
      var nm = (TRAP[x.id] || [x.what, x.what])[lang === "fa" ? 1 : 0];
      return '<div class="trap"><div><span class="k">' + (lang === "fa" ? "تله" : "Trap") + "</span>" + esc(nm) + '</div><div><span class="k">' + (lang === "fa" ? "خواندن ساده" : "Naive reading") + '</span><span class="wrong">' + esc(JSON.stringify(x.naive_reading)) + '</span></div><div><span class="k">' + (lang === "fa" ? "مقدار درست" : "Correct") + '</span><span class="right">' + esc(JSON.stringify(x.correct)) + "</span></div></div>";
    }).join("");

    // agents
    var ag = D.bench_agents;
    var accCard = $("#ch-acc").closest(".chart-card"), agCard = $("#agent-table").closest(".chart-card");
    if (!ag) { accCard.style.display = "none"; agCard.style.display = "none"; }
    else {
      accCard.style.display = ""; agCard.style.display = "";
      var armDefs = [{ key: "browser", c: "var(--s3)" }, { key: "shell", c: "var(--s2)" }, { key: "mcp", c: "var(--s1)" }];
      var arms = armDefs.filter(function (a) { return ag.arms && ag.arms[a.key]; });
      var tasks = Object.keys(ag.arms[arms[0].key].runs);
      var aseries = arms.map(function (a) { return { key: a.key, name: ag.arms[a.key]["label_" + lang] || ag.arms[a.key].label_en, c: a.c }; });
      var avals = {}; tasks.forEach(function (id) { avals[id] = {}; arms.forEach(function (a) { var r = ag.arms[a.key].runs[id]; avals[id][a.key] = r ? Math.max(r.score * 100, 0) : 0; }); });
      var tnames = {}; (ag.tasks || []).forEach(function (x) { tnames[x.id] = lang === "fa" ? x.title_fa : x.title_en; });
      hbar({ chart: "ch-acc", legend: "lg-acc", cats: tasks.map(function (id) { return { id: id, label: tnames[id] || id }; }), series: aseries, values: avals, scale: "linear", aria: "Accuracy per task", fmt: function (v) { return Math.round(v) + "%"; }, tick: function (v) { return v + "%"; },
        tip: function (c, se, v) { return "<b>" + esc(c.label) + "</b><br>" + esc(se.name) + ": " + Math.round(v) + "% " + (lang === "fa" ? "فیلدهای درست" : "of fields correct"); } });
      $("#acc-sub").textContent = (lang === "fa" ? "درصد فیلدهای درست، نسبت به حقیقت مستقل. " : "Share of fields correct against independent ground truth. ") + (ag.model || "") + (ag.date ? " · " + ag.date : "");
      $("#agents-sub").textContent = (lang === "fa" ? "میانگین هر کار؛ توکن خالص یعنی منهای سربار ثابت هر ایجنت. " : "Mean per task, same tasks for every agent. Net tokens exclude each agent type's fixed harness overhead. ") + (ag.note || "");
      var rows = arms.map(function (a) {
        var arm = ag.arms[a.key], rs = tasks.map(function (id) { return arm.runs[id]; }).filter(Boolean), mean = function (f) { return rs.reduce(function (s, r) { return s + (r[f] || 0); }, 0) / rs.length; };
        return { label: arm["label_" + lang] || arm.label_en, c: a.c, acc: mean("score") * 100, tok: mean("net_tokens"), sec: mean("seconds"), calls: mean("tool_uses"), ok: rs.filter(function (r) { return r.answered; }).length, n: rs.length };
      });
      var maxTok = Math.max.apply(null, rows.map(function (r) { return r.tok; }));
      $("#agent-table").innerHTML = "<thead><tr><th>" + (lang === "fa" ? "ایجنت" : "Agent") + "</th><th>" + (lang === "fa" ? "دقت" : "Accuracy") + "</th><th>" + (lang === "fa" ? "توکن خالص (میانگین)" : "Net tokens (mean)") + "</th><th>" + (lang === "fa" ? "زمان" : "Time") + "</th><th>" + (lang === "fa" ? "فراخوانی ابزار" : "Tool calls") + "</th><th>" + (lang === "fa" ? "پاسخ‌داده" : "Answered") + "</th></tr></thead><tbody>" +
        rows.map(function (r) { return '<tr><td><i class="hbar" style="width:12px;height:12px;background:' + r.c + '"></i>' + esc(r.label) + '</td><td class="num">' + Math.round(r.acc) + '%</td><td class="num bar-cell"><i class="hbar" style="width:' + Math.max(4, r.tok / maxTok * 90) + 'px;background:' + r.c + '"></i>' + nf(r.tok) + '</td><td class="num">' + r.sec.toFixed(0) + "s</td><td class=\"num\">" + r.calls.toFixed(1) + '</td><td class="num">' + r.ok + "/" + r.n + "</td></tr>"; }).join("") + "</tbody>";
    }
    $("#bench-note").textContent = (lang === "fa" ? "روش‌شناسی: " : "Method: ") + (lang === "fa"
      ? "توکن‌ها با o200k_base تخمین زده شده‌اند (تقریبی؛ نسبت‌ها مهم‌اند). زمان‌ها از یک اتصال و یک روز اندازه‌گیری شده‌اند. آزمون ایجنت‌ها کوچک است و یک مدل دارد، پس شاخص است نه نتیجه‌ی آماری. اسکریپت‌ها در پوشه benchmarks مخزن هستند و قابل تکرارند."
      : "tokens are estimated with tiktoken o200k_base (a proxy; the ratios matter). Timings are from one connection on one day. The agent trials are small and use one model, so they are indicative, not statistical. Every script is in the repo's benchmarks folder and can be re-run.") + (dp.generated ? " · " + dp.generated : "");
  }

  /* ------------------------------------------------------------------ install */
  var FRAMEWORKS = (D.frameworks || []).map(function (f) { return { id: f.id, label: f.label, group: "framework", snippet: f.snippet }; });
  var selectedClient = "claude-code";
  var GROUP_LABEL = { cli: ["Terminal agents", "ایجنت‌های ترمینال"], ide: ["IDEs and editors", "IDE و ویرایشگرها"], desktop: ["Desktop apps", "اپ‌های دسکتاپ"], framework: ["Frameworks and shell", "فریم‌ورک و شل"] };
  function allClients() { return (D.clients || []).filter(function (c) { return c.id !== "generic"; }).concat(FRAMEWORKS, (D.clients || []).filter(function (c) { return c.id === "generic"; })); }
  function renderInstall() {
    var list = allClients(), order = ["cli", "desktop", "ide", "framework"], html = "";
    order.forEach(function (g) {
      html += '<div class="group">' + esc(GROUP_LABEL[g][lang === "fa" ? 1 : 0]) + "</div>";
      list.filter(function (c) { return c.group === g; }).forEach(function (c) { html += '<button class="client-btn" role="tab" type="button" data-client="' + c.id + '" aria-selected="' + (c.id === selectedClient) + '">' + esc(c.label) + (c.oneclick && (c.oneclick.cursor || c.oneclick.vscode || c.oneclick.goose) ? "<small>1-click</small>" : c.auto ? "<small>auto</small>" : "") + "</button>"; });
    });
    $("#clients").innerHTML = html;
    $$("#clients .client-btn").forEach(function (b) { b.addEventListener("click", function () { selectedClient = b.getAttribute("data-client"); renderInstall(); }); });
    var c = list.filter(function (x) { return x.id === selectedClient; })[0] || list[0];
    var pane = '<h3>' + esc(c.label) + "</h3>";
    if (c.note) pane += '<p style="color:var(--ink-2);margin:6px 0 0">' + esc(c.note) + "</p>";
    var buttons = "";
    if (c.oneclick) {
      if (c.oneclick.cursor) buttons += '<a class="btn btn-primary" href="' + esc(c.oneclick.cursor) + '">' + (lang === "fa" ? "نصب یک‌کلیکی در Cursor" : "One-click install in Cursor") + "</a>";
      if (c.oneclick.vscode) buttons += '<a class="btn btn-primary" href="' + esc(c.oneclick.vscode) + '">' + (lang === "fa" ? "نصب یک‌کلیکی در VS Code" : "One-click install in VS Code") + "</a>";
      if (c.oneclick.goose) buttons += '<a class="btn btn-primary" href="' + esc(c.oneclick.goose) + '">' + (lang === "fa" ? "نصب یک‌کلیکی در Goose" : "One-click install in Goose") + "</a>";
    }
    if (c.docs) buttons += '<a class="btn btn-ghost" href="' + esc(c.docs) + '" target="_blank" rel="noopener">' + (lang === "fa" ? "مستندات " : "Docs for ") + esc(c.label) + "</a>";
    if (buttons) pane += '<div class="row">' + buttons + "</div>";
    pane += '<div class="code"><pre>' + esc(c.snippet) + '</pre><button class="copy" type="button" data-copy-pre>' + t("copy") + "</button></div>";
    if (c.auto) pane += '<p style="margin:16px 0 6px;color:var(--ink-2);font-size:14.5px">' + (lang === "fa" ? "یا بگذارید خودش در فایل تنظیمات اضافه شود (با پشتیبان‌گیری):" : "Or let it edit the config for you (makes a backup first):") + '</p><div class="code"><pre>uvx --from ' + GIT + " iran-bourse-mcp install " + c.id + '</pre><button class="copy" type="button" data-copy-pre>' + t("copy") + "</button></div>";
    $("#pane").innerHTML = pane;
  }

  /* ------------------------------------------------------------------ examples / tools / trust / faq */
  var EXAMPLES = [
    { q: "وضعیت فولاد رو کامل بررسی کن: صف، ورود پول حقیقی، سهامداران عمده و آخرین اطلاعیه‌های کدال", tools: ["symbol_overview", "real_legal_flow", "shareholders", "codal_filings"], en: "A full dossier in four calls.", fa: "پرونده کامل در چهار فراخوانی." },
    { q: "امروز کدوم سهم‌ها صف خرید قوی دارن و پول حقیقی وارد شده؟", tools: ["top_movers"], en: "Queues are confirmed against the real order book, not guessed.", fa: "صف‌ها با عمق بازار واقعی تأیید می‌شوند، نه حدس." },
    { q: "ریز معاملات فولاد دیروز رو خلاصه کن و بزرگ‌ترین معامله‌ها رو نشون بده", tools: ["trade_summary", "trades"], en: "15,643 ticks become one page, with a coverage check.", fa: "۱۵٬۶۴۳ معامله می‌شود یک صفحه، همراه با بررسی کامل بودن." },
    { q: "صف خرید خودرو از چه ساعتی شکل گرفت و چقدر بزرگ شد؟", tools: ["order_book_history"], en: "Queue episodes rebuilt from every order-book event.", fa: "بازه‌های صف از روی تک‌تک رویدادهای عمق بازار." },
    { q: "سهامدار عمده شستا چه سهم‌های دیگه‌ای داره؟", tools: ["shareholders", "shareholder_portfolio"], en: "Follow a holder across the whole market.", fa: "پیگیری یک سهامدار در کل بازار." },
    { q: "حباب صندوق اهرم نسبت به NAV چقدره؟", tools: ["etf_nav"], en: "Premium to issue and redemption NAV.", fa: "حباب نسبت به NAV صدور و ابطال." }
  ];
  function renderExamples() { $("#examples-grid").innerHTML = EXAMPLES.map(function (e) { return '<article class="ex"><q>' + esc(e.q) + "</q><p>" + esc(lang === "fa" ? e.fa : e.en) + '</p><div class="tools">' + e.tools.map(function (x) { return "<span>" + x + "</span>"; }).join("") + "</div></article>"; }).join(""); }

  var toolGroup = "All", toolQuery = "";
  function renderTools() {
    var groups = ["All", "Market", "Symbol", "Codal", "Help"], gl = { All: ["All", "همه"], Market: ["Market", "بازار"], Symbol: ["Symbol", "نماد"], Codal: ["Codal", "کدال"], Help: ["Help", "راهنما"] };
    $("#tool-groups").innerHTML = groups.map(function (g) { return '<button type="button" data-g="' + g + '" aria-pressed="' + (g === toolGroup) + '">' + gl[g][lang === "fa" ? 1 : 0] + "</button>"; }).join("");
    $$("#tool-groups button").forEach(function (b) { b.addEventListener("click", function () { toolGroup = b.getAttribute("data-g"); renderTools(); }); });
    var q = toolQuery.toLowerCase();
    var list = (D.tools || []).filter(function (x) { return (toolGroup === "All" || x.group === toolGroup) && (!q || (x.name + " " + x.description + " " + x.fa).toLowerCase().indexOf(q) >= 0); });
    $("#tools-grid").innerHTML = list.map(function (x) {
      var d = lang === "fa" ? x.fa : x.description.split(". ")[0].replace(/\.$/, "");
      return '<details class="tool"><summary><div class="n"><span>' + x.name + "</span><small>" + x.group + '</small></div><p class="d">' + esc(d) + '</p></summary><ul class="params">' + (x.params.length ? x.params.map(function (p) { return "<li><b>" + p.name + "</b>" + (p.required ? " <i>*</i>" : "") + (p.description ? " — " + esc(p.description) : "") + "</li>"; }).join("") : "<li>no parameters</li>") + "</ul></details>";
    }).join("") || '<p class="note">—</p>';
  }
  $("#tool-search").addEventListener("input", function (e) { toolQuery = e.target.value; renderTools(); });

  var FACTS = [
    ["100%", { en: ["Ticks are complete", "For Foolad, 6,819 ticks of 3 Nov and 15,643 of 2 Nov matched the exchange's own daily totals at 100% of volume and count. Every trade_summary repeats that check."], fa: ["ریز معاملات کامل است", "برای فولاد، ۶٬۸۱۹ معامله‌ی ۱۲ آبان و ۱۵٬۶۴۳ معامله‌ی ۱۱ آبان با مجموع رسمی بورس در ۱۰۰٪ حجم و تعداد برابر بود. هر trade_summary همین بررسی را تکرار می‌کند."] }],
    ["RO", { en: ["Read-only by design", "No tool places, changes or cancels an order, and none handles credentials. Every tool is annotated read-only."], fa: ["فقط‌خواندنی از پایه", "هیچ ابزاری سفارش ثبت، ویرایش یا لغو نمی‌کند و هیچ‌کدام با رمز و اعتبارنامه کار ندارد. همه‌ی ابزارها فقط‌خواندنی علامت خورده‌اند."] }],
    ["≈", { en: ["Facts and estimates are separate", "Anything the exchange does not publish (tick-rule pressure, adjusted prices, same-day money value) is labelled estimate or estimated."], fa: ["واقعیت و تخمین جدا هستند", "هر چیزی که بورس منتشر نمی‌کند (فشار tick rule، قیمت تعدیل‌شده، ارزش پول روز جاری) برچسب estimate دارد."] }],
    ["✓", { en: ["Tested against real data", "Recorded real fixtures, a live smoke test of every tool, and an end-to-end MCP handshake. CI runs Python 3.10 to 3.13 on both MCP SDK generations."], fa: ["تست‌شده با داده واقعی", "داده‌ی واقعی ضبط‌شده، تست زنده‌ی همه‌ی ابزارها و تست کامل پروتکل MCP. CI روی پایتون ۳٫۱۰ تا ۳٫۱۳ و هر دو نسل MCP SDK اجرا می‌شود."] }],
    ["!", { en: ["Honest about gaps", "Order-book history for the current trading day can be partial and the tool says so. Quirks and limits are documented, not hidden."], fa: ["صادق درباره کمبودها", "تاریخچه عمق بازار برای روز جاری ممکن است ناقص باشد و ابزار این را می‌گوید. ویژگی‌ها و محدودیت‌ها مستند شده‌اند، نه پنهان."] }],
    ["فا", { en: ["Persian-native", "ی/ي and ک/ك are interchangeable, dates accept Jalali, output is normalised to Persian letters, and a glossary explains صف، سرانه، قدرت خریدار."], fa: ["بومی فارسی", "ی/ي و ک/ك یکسان‌اند، تاریخ شمسی پذیرفته می‌شود، خروجی با حروف فارسی نرمال می‌شود و واژه‌نامه صف، سرانه و قدرت خریدار را توضیح می‌دهد."] }]
  ];
  function renderTrust() { $("#trust-grid").innerHTML = FACTS.map(function (f) { var c = f[1][lang]; return '<div class="fact"><div class="ic">' + f[0] + "</div><div><h3>" + esc(c[0]) + "</h3><p>" + esc(c[1]) + "</p></div></div>"; }).join(""); }

  var FAQ = [
    { q: ["Do I need an Iranian IP address?", "آیا IP ایران لازم است؟"], a: ["Usually yes. TSETMC and Codal are built for Iranian users and often refuse foreign or VPN addresses. Run the server on a machine in Iran, set IRAN_BOURSE_PROXY to an in-Iran proxy, or run it on an Iranian server and connect over HTTP through an SSH tunnel. The doctor command tells you what is reachable.", "معمولاً بله. TSETMC و کدال برای کاربر ایرانی ساخته شده‌اند و اغلب IP خارجی و VPN را رد می‌کنند. سرور را روی سیستمی داخل ایران اجرا کنید، IRAN_BOURSE_PROXY را روی یک پراکسی داخل ایران بگذارید، یا روی سرور ایرانی اجرا کنید و با تونل SSH و HTTP وصل شوید. دستور doctor می‌گوید چه چیزی در دسترس است."] },
    { q: ["Is this an official tool?", "آیا رسمی است؟"], a: ["No. It is an independent open-source project using public endpoints. It is not affiliated with TSETMC, the Tehran Stock Exchange, Fara Bourse or Codal.", "نه. پروژه‌ای مستقل و متن‌باز است که از endpoint های عمومی استفاده می‌کند و هیچ ارتباطی با TSETMC، بورس تهران، فرابورس یا کدال ندارد."] },
    { q: ["Can it place orders or trade?", "آیا می‌تواند سفارش ثبت کند؟"], a: ["No, by design. There is no login, no credentials and no order tool. It only reads public market data.", "نه، عمداً. نه ورود به حساب دارد، نه رمز، نه ابزار سفارش. فقط داده‌ی عمومی بازار را می‌خواند."] },
    { q: ["Which agents work with it?", "با کدام ایجنت‌ها کار می‌کند؟"], a: ["Any MCP client over stdio or HTTP: Claude Code and Desktop, Codex, Gemini CLI, Cursor, VS Code, Windsurf, Cline, Zed, Goose, OpenCode, Kiro, Qwen Code, JetBrains, Amp and more. Agents without MCP can use the shell command (iran-bourse-mcp call), and Python frameworks can attach it as a stdio server.", "هر کلاینت MCP با stdio یا HTTP: Claude Code و Desktop، Codex، Gemini CLI، Cursor، VS Code، Windsurf، Cline، Zed، Goose، OpenCode، Kiro، Qwen Code، JetBrains، Amp و بقیه. ایجنت‌های بدون MCP می‌توانند از دستور شل (iran-bourse-mcp call) استفاده کنند و فریم‌ورک‌های پایتون آن را به‌صورت سرور stdio وصل می‌کنند."] },
    { q: ["How fresh is the data?", "داده چقدر تازه است؟"], a: ["Live during the session (Saturday to Wednesday, 09:00 to 12:30 Tehran time), cached for a few seconds. Outside the session you get the last session. Order-book history for the current day may be partial until the day ends.", "در ساعت بازار (شنبه تا چهارشنبه، ۰۹:۰۰ تا ۱۲:۳۰) زنده است و چند ثانیه کش می‌شود. خارج از ساعت بازار آخرین جلسه را می‌دهد. تاریخچه عمق بازار برای روز جاری ممکن است تا پایان روز ناقص باشد."] },
    { q: ["Is the data complete and correct?", "آیا داده کامل و درست است؟"], a: ["Tick data matched the exchange's totals exactly in our checks, and the traps we found in the raw JSON are handled. The endpoints are unofficial and can change without notice, so the repo ships a live smoke test and documents every quirk.", "در بررسی‌های ما ریز معاملات دقیقاً با مجموع رسمی بورس برابر بود و تله‌های JSON خام مدیریت شده‌اند. endpoint ها غیررسمی‌اند و ممکن است بدون اطلاع عوض شوند؛ برای همین مخزن تست زنده دارد و همه‌ی ویژگی‌ها را مستند کرده است."] },
    { q: ["Does it cost anything? Are there rate limits?", "هزینه یا محدودیت دارد؟"], a: ["It is free and MIT-licensed. The server caches briefly and keeps at most six requests in flight to stay polite to the exchange's servers.", "رایگان و با مجوز MIT است. سرور کوتاه‌مدت کش می‌کند و حداکثر شش درخواست هم‌زمان می‌زند تا به سرورهای بورس فشار نیاورد."] },
    { q: ["How can I contribute?", "چطور مشارکت کنم؟"], a: ["Open an issue with the output of iran-bourse-mcp doctor, or send a pull request. The contributing guide explains the rules: pure logic with tests, estimates labelled, read-only forever.", "یک issue با خروجی iran-bourse-mcp doctor باز کنید یا pull request بفرستید. راهنمای مشارکت قوانین را توضیح می‌دهد: منطق خالص همراه تست، تخمین‌ها برچسب‌دار، و همیشه فقط‌خواندنی."] }
  ];
  function renderFaq() { $("#faq-list").innerHTML = FAQ.map(function (f, i) { return "<details" + (i === 0 ? " open" : "") + "><summary>" + esc(f.q[lang === "fa" ? 1 : 0]) + "</summary><p>" + esc(f.a[lang === "fa" ? 1 : 0]) + "</p></details>"; }).join(""); }

  var resizeTimer;
  window.addEventListener("resize", function () { clearTimeout(resizeTimer); resizeTimer = setTimeout(renderBench, 180); });

  /* ------------------------------------------------------------------ boot */
  function renderScreener() {
    var s = SNAP.screener;
    var sec = $("#screener");
    if (!s || !s.rows || !s.rows.length) { if (sec) sec.style.display = "none"; return; }
    sec.style.display = "";
    $("#scr-q").textContent = (T[lang] || T.en)["scr.q"];
    $("#scr-filter").textContent = 'screen_stocks(filter="' + s.filter.replace(/^\(|\)$/g, "").replace(/5000000000\.0/, "5B") + '")';
    $("#scr-meta").textContent = nf(s.matched) + " / " + nf(s.universe) + " stocks \u00b7 " + s.history_days + " trading days \u00b7 " + s.seconds + " s \u00b7 " + s.jdate;
    var t = function (k) { return (T[lang] || T.en)[k]; };
    var pct = function (v) { return '<span class="' + (v >= 0 ? "up" : "") + '">' + (v >= 0 ? "+" : "") + nf(v, 2) + "%</span>"; };
    $("#scr-table").innerHTML = "<thead><tr><th>" + t("scr.col.symbol") + "</th><th>" + t("scr.col.y") + "</th><th>" + t("scr.col.t") + "</th><th>" + t("scr.col.v") + "</th><th>" + t("scr.col.val") + "</th></tr></thead><tbody>" +
      s.rows.map(function (r) { return "<tr><td>" + esc(r.symbol) + '</td><td class="num">' + pct(r.yesterday_pct) + '</td><td class="num">' + pct(r.today_pct) + '</td><td class="num">' + nf(r.volume_x, 1) + '\u00d7</td><td class="num">' + nf(r.value_billion_rial, 0) + "</td></tr>"; }).join("") + "</tbody>";
  }
  function renderAll() { renderTape(); renderWorks(); renderPanel(); renderStats(); renderBench(); renderScreener(); renderInstall(); renderExamples(); renderTools(); renderTrust(); renderFaq(); typeInto("t-bad", true); typeInto("t-good", true); $("#ver").textContent = "v" + (D.version || "0.1.0"); }
  applyLang();
  initTerminals();
  fetch("https://api.github.com/repos/msmahdinejad/iran-bourse-mcp").then(function (r) { return r.ok ? r.json() : null; }).then(function (j) { if (j && typeof j.stargazers_count === "number") $("#stars").textContent = "★ " + j.stargazers_count; }).catch(function () { });
})();
