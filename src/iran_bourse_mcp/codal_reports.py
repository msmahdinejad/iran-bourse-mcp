"""Pure parsing of Codal letter pages (codal.ir/Reports/Decision.aspx) into tables, statements and monthly activity.

A structured Codal letter (financial statements, monthly activity reports, ...) is an ASP.NET page that carries its
whole content as JSON in ``var datasource = {...}``: one sheet per page (other sheets are other ``sheetId`` URLs,
listed in the ``ddlTable`` drop-down), each sheet a list of tables, each table a flat list of cells with
``rowSequence``/``columnSequence``/``colSpan``/``cellGroupName`` (Header or Body) and a string ``value``.
Plain letters (meeting decisions, explanations, notices) have no datasource and are read as visible text.

Everything here is pure (no I/O) so it is tested against recorded pages.
"""

from __future__ import annotations

import json
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any

# ------------------------------------------------------------------------------ text helpers

_ZW = dict.fromkeys(map(ord, "‌‍‎‏­ـًٌٍَُِّْٰٔ"), None)
_LETTERS = str.maketrans({"ي": "ی", "ك": "ک", "ى": "ی", "ة": "ه", "ۀ": "ه", "أ": "ا", "إ": "ا", "ؤ": "و"})
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def tidy(s: Any) -> str:
    """Human text: Arabic letters to Persian, digits to ASCII, collapsed spaces."""
    if s is None:
        return ""
    s = unescape(str(s)).translate(_LETTERS).translate(_DIGITS).replace("­", "")
    return re.sub(r"\s+", " ", s).strip()


def key(s: Any) -> str:
    """Matching key: tidy text without spaces, joiners, diacritics or a trailing colon."""
    return re.sub(r"[\s:：]+", "", tidy(s).translate(_ZW)).rstrip(".")


def number(v: Any) -> float | int | None:
    """Codal cell value -> number. '--', '' and text give None; '(123)' is negative; integers stay int."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    t = tidy(v)
    if not t or not re.fullmatch(r"[\d,٬.()/\-+ ]+", t):
        return None
    s = t.replace(",", "").replace("٬", "").replace("/", ".").replace(" ", "")
    if s in {"-", "--", "."}:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        f = float(s)
    except ValueError:
        return None
    f = -f if neg else f
    return int(f) if f.is_integer() and abs(f) < 1e18 else round(f, 6)


# ------------------------------------------------------------------------------ the page


def datasource(html: str) -> dict | None:
    i = html.find("var datasource = ")
    if i < 0:
        return None
    try:
        d, _ = json.JSONDecoder().raw_decode(html, i + len("var datasource = "))
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def sheets(html: str) -> list[dict]:
    m = re.search(r'<select[^>]*name="ctl00\$ddlTable".*?</select>', html, re.S)
    if not m:
        return []
    return [{"sheet": int(v), "name": tidy(n)} for v, n in re.findall(r'<option[^>]*value="(-?\d+)"[^>]*>([^<]*)', m[0])]


def selected_sheet(html: str) -> int | None:
    m = re.search(r'<option[^>]*selected="selected"[^>]*value="(-?\d+)"', html) or re.search(
        r'<option[^>]*value="(-?\d+)"[^>]*selected="selected"', html
    )
    return int(m[1]) if m else None


def label(html: str, element_id: str) -> str | None:
    m = re.search(rf'id="{element_id}"[^>]*>([^<]*)<', html)
    if not m:
        return None
    return tidy(m[1]) or None


class _Text(HTMLParser):
    SKIP = {"script", "style", "head", "select", "option", "noscript"}
    BREAK = {"p", "div", "br", "tr", "li", "table", "h1", "h2", "h3", "h4", "td"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BREAK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def visible_text(html: str, limit: int = 12000) -> tuple[str, bool]:
    """The readable text of a plain letter, ASP.NET form noise removed; (text, truncated)."""
    body = html.find("<body")
    p = _Text()
    p.feed(html[body:] if body >= 0 else html)
    lines = [tidy(x) for x in "".join(p.parts).split("\n")]
    noise = re.compile(r"^(چاپ|بازگشت|صفحه اصلی|ورود|انتخاب گزارش|نمایش)$")
    text = "\n".join(x for x in lines if x and not noise.match(x))
    return (text, False) if len(text) <= limit else (text[:limit], True)


# ------------------------------------------------------------------------------ tables


def _rows(table: dict) -> dict[int, list[dict]]:
    rows: dict[int, list[dict]] = {}
    for c in table.get("cells") or []:
        if isinstance(c, dict):
            rows.setdefault(c.get("rowSequence") or 0, []).append(c)
    for r in rows.values():
        r.sort(key=lambda c: c.get("columnSequence") or 0)
    return rows


def grid(table: dict) -> dict:
    """One Codal table as columns + rows.

    Header rows (possibly two, with column spans) become one label per column, e.g. ``دوره یک ماهه منتهی به
    1405/07/30 | مبلغ فروش (میلیون ریال)``. Body rows become ``{"label", "values"}`` with numbers parsed; rows the
    page hides (every cell invisible) are dropped.
    """
    rows = _rows(table)
    width = 0
    for cells in rows.values():
        width = max(width, max(((c.get("columnSequence") or 1) + (c.get("colSpan") or 1) - 1) for c in cells))
    headers: list[list[str]] = []
    body: list[list[dict]] = []
    for seq in sorted(rows):
        cells = rows[seq]
        if cells[0].get("cellGroupName") == "Header":
            line = [""] * width
            for c in cells:
                start, span = (c.get("columnSequence") or 1) - 1, c.get("colSpan") or 1
                for k in range(start, min(width, start + span)):
                    line[k] = tidy(c.get("value"))
            headers.append(line)
        elif any(c.get("isVisible", True) for c in cells):
            body.append(cells)
    columns = []
    for k in range(width):
        parts = []
        for line in headers:
            if line[k] and line[k] not in parts:
                parts.append(line[k])
        columns.append(" | ".join(parts))
    out_rows = []
    for cells in body:
        values: list[Any] = [None] * width
        for c in cells:
            k = (c.get("columnSequence") or 1) - 1
            if 0 <= k < width:
                raw = tidy(c.get("value"))
                n = number(raw)
                values[k] = n if n is not None else (raw or None)
        lab = values[0] if isinstance(values[0], str) else None
        if lab is None and not any(v is not None for v in values[1:]):
            continue
        out_rows.append({"label": lab, "values": values[1:]})
    return {
        "title": tidy(table.get("title_Fa")) or None,
        "title_en": tidy(table.get("title_En")) or None,
        "code": table.get("code"),
        "unit_note": tidy(table.get("description")) or None,
        "columns": columns[1:],
        "rows": out_rows,
    }


def grids(ds: dict) -> list[dict]:
    out = []
    for sheet in ds.get("sheets") or []:
        for t in sheet.get("tables") or []:
            g = grid(t)
            if g["rows"]:
                out.append(g)
    return out


def meta(ds: dict) -> dict:
    return {
        "report": tidy(ds.get("title_Fa")) or None,
        "report_en": tidy(ds.get("title_En")) or None,
        "period_months": ds.get("period"),
        "period_end": tidy(ds.get("periodEndToDate")) or None,
        "fiscal_year_end": tidy(ds.get("yearEndToDate")) or None,
        "audited": ds.get("isAudited"),
        "consolidated": ds.get("isConsolidated"),
        "published": tidy(ds.get("publishDateTime")) or None,
        "tracing_no": ds.get("tracingNo"),
    }


def unit_multiplier(note: str | None) -> int:
    """'کليه مبالغ به ميليون ريال است' -> 1_000_000 (to Rial)."""
    k = key(note or "")
    if "میلیاردریال" in k:
        return 1_000_000_000
    if "میلیونریال" in k:
        return 1_000_000
    if "هزارریال" in k:
        return 1_000
    return 1_000_000 if not k else 1


# ------------------------------------------------------------------------------ financial statements

# concept -> label patterns (keys, see key()); "=" means the label must equal it, otherwise it must start with it
INCOME = {
    "revenue": ["=درآمدهایعملیاتی", "=درآمدعملیاتی", "=فروشخالص", "=فروشخالصودرآمدارائهخدمات", "=جمعدرآمدهایعملیاتی", "=جمعدرآمدها"],
    "cost_of_revenue": ["بهایتمامشدهدرآمدهایعملیاتی", "بهایتمامشدهدرآمد", "=بهایتمامشدهکالایفروشرفته", "بهایتمامشده"],
    "gross_profit": ["=سود(زیان)ناخالص"],
    "selling_admin_expenses": ["هزینههایفروش،اداریوعمومی", "هزینههایفروشاداریوعمومی"],
    "operating_profit": ["=سود(زیان)عملیاتی"],
    "finance_costs": ["=هزینههایمالی"],
    "pretax_profit": ["سود(زیان)عملیاتدرحالتداومقبلازمالیات", "=سود(زیان)قبلازمالیات"],
    "net_profit": ["=سود(زیان)خالص"],
    "eps": ["=سود(زیان)پایههرسهم"],
    "eps_operating": ["=عملیاتی(ریال)"],
    "net_profit_per_share": ["=سود(زیان)خالصهرسهم–ریال", "=سود(زیان)خالصهرسهم-ریال"],
    "capital": ["=سرمایه"],
}
BALANCE = {
    "total_assets": ["=جمعداراییها"],
    "current_assets": ["=جمعداراییهایجاری"],
    "non_current_assets": ["=جمعداراییهایغیرجاری"],
    "fixed_assets": ["=داراییهایثابتمشهود"],
    "cash": ["=موجودینقد"],
    "short_term_investments": ["=سرمایهگذاریهایکوتاهمدت"],
    "trade_receivables": ["دریافتنیهایتجاری"],
    "inventory": ["=موجودیموادوکالا"],
    "total_liabilities": ["=جمعبدهیها"],
    "current_liabilities": ["=جمعبدهیهایجاری"],
    "borrowings_current": ["=تسهیلاتمالی"],
    "borrowings_long_term": ["=تسهیلاتمالیبلندمدت"],
    "equity": ["=جمعحقوقمالکانه", "=جمعحقوقصاحبانسهام"],
    "capital": ["=سرمایه"],
    "retained_earnings": ["=سود(زیان)انباشته"],
}
CASH_FLOW = {
    "operating_cash_flow": ["جریانخالصورود(خروج)نقدحاصلازفعالیتهایعملیاتی"],
    "investing_cash_flow": ["جریانخالصورود(خروج)نقدحاصلازفعالیتهایسرمایهگذاری"],
    "financing_cash_flow": ["جریانخالصورود(خروج)نقدحاصلازفعالیتهایتامینمالی"],
    "capex": ["پرداختهاینقدیبرایخریدداراییهایثابتمشهود"],
    "dividends_paid": ["پرداختهاینقدیبابتسودسهام"],
    "cash_at_end": ["ماندهموجودینقددرپایان"],
}
KINDS = {"income": INCOME, "balance": BALANCE, "cashflow": CASH_FLOW}
SHEET_NAMES = {  # sheet drop-down names, matched with key()
    "income": ["صورتسودوزیان", "سودوزیان"],
    "balance": ["صورتوضعیتمالی", "ترازنامه"],
    "cashflow": ["صورتجریانهاینقدی", "جریانوجوهنقد"],
}


def pick_sheet(options: list[dict], kind: str) -> int | None:
    for want in SHEET_NAMES[kind]:
        for o in options:
            k = key(o["name"])
            if k.startswith(want) and "جامع" not in k and "تلفیقی" not in k:
                return o["sheet"]
    return None


def _match(lab: str, patterns: list[str]) -> bool:
    k = key(lab)
    return any((k == p[1:]) if p.startswith("=") else k.startswith(p) for p in patterns)


def _columns_roles(columns: list[str], fiscal_year_end: str | None = None) -> dict[str, int]:
    """Which value column is this period, the same period last year and the last full fiscal year.

    Decided by the dates in the headers: the first dated column is this period; a column ending on the same month and
    day a year earlier is the same period last year; a column ending on the fiscal year-end day is the last full year.
    Change-% columns are skipped.
    """
    dated = []
    for i, c in enumerate(columns):
        k = key(c)
        d = re.search(r"\d{4}/\d{2}/\d{2}", c or "")
        if c and "درصد" not in k and d:
            dated.append((i, d[0]))
    roles: dict[str, int] = {}
    if not dated:
        plain = [i for i, c in enumerate(columns) if c and "درصد" not in key(c)]
        return {"current": plain[0]} if plain else {}
    cur_i, cur_d = dated[0]
    roles["current"] = cur_i
    fy_md = (fiscal_year_end or "")[5:]
    for i, d in dated[1:]:
        if d[5:] == cur_d[5:] and "previous" not in roles:
            roles["previous"] = i
        elif fy_md and d[5:] == fy_md and "last_year" not in roles:
            roles["last_year"] = i
    return roles


def statement(g: dict, kind: str, fiscal_year_end: str | None = None) -> dict:
    """Key items of one statement table: {concept: {current, previous, last_year}} plus the column labels used."""
    concepts = KINDS[kind]
    roles = _columns_roles(g["columns"], fiscal_year_end)
    items: dict[str, dict] = {}
    for row in g["rows"]:
        lab = row["label"]
        if not lab:
            continue
        for concept, patterns in concepts.items():
            if concept in items or not _match(lab, patterns):
                continue
            vals = {r: row["values"][i] for r, i in roles.items() if i < len(row["values"]) and isinstance(row["values"][i], (int, float))}
            if vals:
                items[concept] = vals
    return {
        "items": items,
        "columns": {r: g["columns"][i] for r, i in roles.items()},
        "unit": g.get("unit_note"),
        "missing": [c for c in concepts if c not in items],
    }


def _div(a, b):
    return None if a is None or not b else a / b


def _pct(a, b, digits=1):
    v = _div(a, b)
    return None if v is None else round(v * 100, digits)


def ttm(items: dict, concept: str, period_months: int | None) -> float | None:
    """Trailing twelve months from an interim statement: last full year + this period − same period last year."""
    v = items.get(concept) or {}
    if period_months == 12:
        return v.get("current")
    if None in (v.get("current"), v.get("previous"), v.get("last_year")):
        return None
    return v["last_year"] + v["current"] - v["previous"]


def ratios(income: dict, balance: dict, cash: dict, period_months: int | None) -> dict:
    """Margins, returns and leverage from the key items (ratios in %, returns on trailing twelve months)."""
    inc, bal, cf = income.get("items", {}), balance.get("items", {}), cash.get("items", {})
    cur = lambda d, k: (d.get(k) or {}).get("current")  # noqa: E731
    rev, ni = cur(inc, "revenue"), cur(inc, "net_profit")
    rev_ttm, ni_ttm = ttm(inc, "revenue", period_months), ttm(inc, "net_profit", period_months)
    eq, ta = cur(bal, "equity"), cur(bal, "total_assets")
    debt = sum(x for x in (cur(bal, "borrowings_current"), cur(bal, "borrowings_long_term")) if x)
    ocf, capex = cur(cf, "operating_cash_flow"), cur(cf, "capex")
    out = {
        "gross_margin_pct": _pct(cur(inc, "gross_profit"), rev),
        "operating_margin_pct": _pct(cur(inc, "operating_profit"), rev),
        "net_margin_pct": _pct(ni, rev),
        "revenue_growth_pct": _pct((cur(inc, "revenue") or 0) - ((inc.get("revenue") or {}).get("previous") or 0), (inc.get("revenue") or {}).get("previous")) if (inc.get("revenue") or {}).get("previous") else None,
        "net_profit_growth_pct": _pct((ni or 0) - ((inc.get("net_profit") or {}).get("previous") or 0), abs((inc.get("net_profit") or {}).get("previous") or 0)) if (inc.get("net_profit") or {}).get("previous") else None,
        "roe_ttm_pct": _pct(ni_ttm, eq),
        "roa_ttm_pct": _pct(ni_ttm, ta),
        "current_ratio": round(_div(cur(bal, "current_assets"), cur(bal, "current_liabilities")), 2) if _div(cur(bal, "current_assets"), cur(bal, "current_liabilities")) is not None else None,
        "debt_ratio_pct": _pct(cur(bal, "total_liabilities"), ta),
        "liabilities_to_equity": round(_div(cur(bal, "total_liabilities"), eq), 2) if _div(cur(bal, "total_liabilities"), eq) is not None else None,
        "financial_debt_to_equity": round(_div(debt, eq), 2) if debt and eq else None,
        "free_cash_flow": (ocf + capex) if ocf is not None and capex is not None else None,
        "revenue_ttm": rev_ttm,
        "net_profit_ttm": ni_ttm,
    }
    return {k: v for k, v in out.items() if v is not None}


# ------------------------------------------------------------------------------ monthly activity


def _sales_table(gs: list[dict]) -> dict | None:
    for want in ("تولیدوفروش", "فروش", "درآمد"):
        for g in gs:
            if want in key(g.get("title") or ""):
                return g
    return None


def _col(columns: list[str], group: str, sub: str, after: int = -1) -> int | None:
    for i, c in enumerate(columns):
        if i <= after:
            continue
        parts = [key(p) for p in c.split("|")]
        if len(parts) >= 2 and group in parts[0] and sub in parts[-1]:
            return i
    return None


def monthly(ds: dict) -> dict:
    """A monthly activity report (ن-۳۰): month and year-to-date sales by product, with totals.

    Production templates name their column groups 'دوره یک ماهه منتهی به ...' (the month) and 'از ابتدای سال مالی
    تا تاریخ ...' (year to date, this year and the same span last year); amounts are million Rial.
    """
    gs = grids(ds)
    g = _sales_table(gs)
    out: dict[str, Any] = {**meta(ds)}
    if not g:
        out["tables"] = gs
        out["note"] = "No production-and-sales table in this report template; the tables are returned as they are."
        return out
    cols = g["columns"]
    m_amt = _col(cols, "یکماهه", "مبلغ")
    month_group = cols[m_amt].split("|")[0] if m_amt is not None else ""
    end = re.search(r"\d{4}/\d{2}/\d{2}", month_group)
    end_date = end[0] if end else out.get("period_end")
    ytd_amt = ytd_prev_amt = None
    for i, c in enumerate(cols):
        head = c.split("|")[0]
        if "ازابتدایسالمالی" in key(head) and "مبلغ" in key(c.split("|")[-1]) and "اصلاح" not in key(head):
            d = re.search(r"\d{4}/\d{2}/\d{2}", head)
            if d and end_date and d[0] == end_date:
                ytd_amt = i
            elif d and end_date and d[0][:4] < end_date[:4]:
                ytd_prev_amt = i
    m_prod, m_qty, m_rate = _col(cols, "یکماهه", "تولید"), _col(cols, "یکماهه", "تعدادفروش"), _col(cols, "یکماهه", "نرخ")
    val = lambda row, i: (row["values"][i] if i is not None and i < len(row["values"]) and isinstance(row["values"][i], (int, float)) else None)  # noqa: E731
    products, section, totals = [], None, {}
    for row in g["rows"]:
        lab = row["label"] or ""
        k = key(lab)
        unit = row["values"][0] if row["values"] and isinstance(row["values"][0], str) else None
        if lab.endswith(":"):
            section = lab.rstrip(":").strip()
            continue
        if k.startswith("جمع"):
            totals[lab] = {"month_amount": val(row, m_amt), "ytd_amount": val(row, ytd_amt), "ytd_last_year_amount": val(row, ytd_prev_amt)}
            continue
        if not lab or unit is None:
            continue
        p = {
            "product": lab,
            "unit": tidy(unit),
            "section": section,
            "month_production": val(row, m_prod),
            "month_sales_qty": val(row, m_qty),
            "month_rate_rial": val(row, m_rate),
            "month_amount": val(row, m_amt),
            "ytd_amount": val(row, ytd_amt),
            "ytd_last_year_amount": val(row, ytd_prev_amt),
        }
        if any(p[x] for x in ("month_production", "month_sales_qty", "month_amount", "ytd_amount")):
            products.append({k2: v for k2, v in p.items() if v is not None})
    grand = totals.get("جمع") or (list(totals.values())[-1] if totals else {})
    out.update(
        {
            "month_end": end_date,
            "unit": g.get("unit_note") or "million rial",
            "month_sales": grand.get("month_amount"),
            "ytd_sales": grand.get("ytd_amount"),
            "ytd_sales_last_year": grand.get("ytd_last_year_amount"),
            "ytd_growth_pct": _pct((grand.get("ytd_amount") or 0) - (grand.get("ytd_last_year_amount") or 0), grand.get("ytd_last_year_amount")) if grand.get("ytd_last_year_amount") else None,
            "subtotals": {k2: {x: y for x, y in v.items() if y is not None} for k2, v in totals.items() if k2 != "جمع"},
            "products": products,
        }
    )
    return {k2: v for k2, v in out.items() if v not in (None, {}, [])}


# ------------------------------------------------------------------------------ recording support


CELL_KEYS = ("cellGroupName", "rowSequence", "columnSequence", "colSpan", "isVisible", "value")


def slim_page(html: str) -> str:
    """A Codal letter page cut down to what this module reads (for lean test recordings): the datasource with only
    the cell fields used, the sheet drop-down and the unit / capital labels. Plain-text letters keep their body text."""
    ds = datasource(html)
    select = re.search(r'<select[^>]*name="ctl00\$ddlTable".*?</select>', html, re.S)
    if ds is None:
        text, _ = visible_text(html, limit=20000)
        lines = "".join(f"<p>{line}</p>" for line in text.split("\n"))
        return "<html><body>" + (select[0] if select else "") + lines + "</body></html>"
    for sheet in ds.get("sheets") or []:
        for t in sheet.get("tables") or []:
            t["cells"] = [{k: c.get(k) for k in CELL_KEYS} for c in t.get("cells") or [] if isinstance(c, dict)]
    labels = "".join(
        m[0] for m in re.finditer(r'<[^>]+id="ctl00_(?:pPriceNote|lblListedCapital)"[^>]*>[^<]*<', html)
    )
    return (
        "<html><body>"
        + (select[0] if select else "")
        + labels
        + "<script>var datasource = "
        + json.dumps(ds, ensure_ascii=False, separators=(",", ":"))
        + ";</script></body></html>"
    )
