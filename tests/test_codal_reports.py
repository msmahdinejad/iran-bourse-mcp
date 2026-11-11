"""Codal letter pages -> tables, statement items, ratios and monthly sales (recorded فولاد pages, 1405)."""

from __future__ import annotations

from pathlib import Path

import pytest

from iran_bourse_mcp import codal_reports as cr

CODAL = Path(__file__).parent / "fixtures" / "codal"


def page(name: str) -> str:
    return (CODAL / f"{name}.html").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("raw", "want"),
    [("2509422184", 2509422184), ("-1759586964", -1759586964), ("(1,234)", -1234), ("67.68", 67.68), ("۱۲۳", 123),
     ("--", None), ("", None), ("هزار تن", None), (None, None), ("3384.6800000000003", 3384.68)],
)
def test_number(raw, want):
    assert cr.number(raw) == pytest.approx(want) if want is not None else cr.number(raw) is None


def test_key_ignores_letter_forms_spaces_and_joiners():
    assert cr.key("سود(زيان) پايه هر سهم:") == cr.key("سود (زیان)‌پایه هر سهم")
    assert cr.key("هزينه‏ هاى مالى") == "هزینههایمالی"


def test_income_statement_items_and_columns():
    html = page("statement_income")
    ds = cr.datasource(html)
    assert cr.meta(ds)["period_end"] == "1405/06/31" and cr.meta(ds)["period_months"] == 6
    g = cr.grids(ds)[0]
    st = cr.statement(g, "income", ds["yearEndToDate"])
    assert st["columns"]["current"].startswith("دوره منتهی به 1405/06/31")
    assert "1404/06/31" in st["columns"]["previous"] and "1404/12/29" in st["columns"]["last_year"]
    it = st["items"]
    assert it["revenue"] == {"current": 2509422184, "previous": 1608734238, "last_year": 3668860246}
    assert it["gross_profit"]["current"] == 749835220
    assert it["operating_profit"]["current"] == 679984579
    assert it["net_profit"]["current"] == 591629286
    assert it["eps"]["current"] == 308  # the total row, not the «سود(زیان) پایه هر سهم:» heading above it
    assert it["capital"]["current"] == 1935000000


def test_trailing_twelve_months_and_ratios():
    ds = cr.datasource(page("statement_income"))
    st = cr.statement(cr.grids(ds)[0], "income", ds["yearEndToDate"])
    # last full year + this half - the same half last year
    assert cr.ttm(st["items"], "revenue", 6) == 3668860246 + 2509422184 - 1608734238
    r = cr.ratios(st, {"items": {}}, {"items": {}}, 6)
    assert r["gross_margin_pct"] == round(749835220 / 2509422184 * 100, 1)
    assert r["revenue_growth_pct"] == 56.0
    assert "roe_ttm_pct" not in r  # no balance sheet given


def test_monthly_report_totals_and_products():
    ds = cr.datasource(page("monthly"))
    m = cr.monthly(ds)
    assert m["month_end"] == "1405/07/30"
    assert m["month_sales"] == 662639489
    assert m["ytd_sales"] == 3172061674 and m["ytd_sales_last_year"] == 1892095932
    assert m["ytd_growth_pct"] == 67.6
    cold = next(p for p in m["products"] if p["product"] == "محصولات سرد" and p["section"] == "فروش داخلی")
    assert cold["month_amount"] == 137852891 and cold["month_sales_qty"] == 123 and cold["unit"] == "هزار تن"
    assert m["subtotals"]["جمع فروش صادراتی"]["month_amount"] == 37517412


def test_grid_headers_combine_spans_and_drop_hidden_rows():
    g = next(t for t in cr.grids(cr.datasource(page("monthly"))) if t["code"] == 1197)
    assert any(c.startswith("دوره یک ماهه منتهی به 1405/07/30 | مبلغ فروش") for c in g["columns"])
    assert all(r["label"] or any(v is not None for v in r["values"]) for r in g["rows"])


def test_sheet_list_and_picking_on_a_page_that_opens_on_the_auditor_report():
    html = page("auditor_sheet")
    assert cr.datasource(html) is None
    opts = cr.sheets(html)
    assert cr.pick_sheet(opts, "income") == 1  # not «صورت سود و زیان جامع»
    assert cr.pick_sheet(opts, "balance") == 0
    assert cr.pick_sheet(opts, "cashflow") == 9
    text, cut = cr.visible_text(html)
    assert "صنایع نیرو و انرژی پاک فولاد" in text and not cut


def test_unit_multiplier():
    assert cr.unit_multiplier("کليه مبالغ به ميليون ريال است") == 1_000_000
    assert cr.unit_multiplier("مبالغ به هزار ریال") == 1_000


def test_slim_page_keeps_what_the_parser_reads():
    html = page("statement_income")
    again = cr.slim_page(html)
    assert cr.grids(cr.datasource(again)) == cr.grids(cr.datasource(html))
    assert cr.sheets(again) == cr.sheets(html)


BANK_COLUMNS = ["دوره منتهی به 1405/06/31 | حسابرسی نشده", "تجدید ارائه شده 1404/06/31 | حسابرسی نشده", "تجدید ارائه شده 1404/12/29", "درصد تغییرات"]


def bank_grid(rows):
    return {"columns": BANK_COLUMNS, "rows": [{"label": lab, "values": vals} for lab, vals in rows]}


def test_bank_income_statement_items_and_eps_fallback():
    # بانک ملت, 1405/06/31 (template «بانک- بورسی - V6»): the full-year column is left 0 and «پایه هر سهم» is 0
    g = bank_grid([
        ("درآمد تسهیلات اعطایی", [1835435722, 1100000000, 0, 66]),
        ("درآمد عملیاتی", [2150761533, 1325688483, 0, 62]),
        ("هزینه سود سپرده‌ها", [-1220160496, -800000000, 0, 52]),
        ("سود(زیان) ناخالص", [930601037, 525688483, 0, 77]),
        ("درآمد کارمزد", [264372382, 200000000, 0, 32]),
        ("هزینه های اداری و عمومی", [-707453017, -500000000, 0, 41]),
        ("هزینه مطالبات مشکوک الوصول", [-43432141, -30000000, 0, 44]),
        ("سود(زیان) عملیاتی", [1271936747, 700000000, 0, 81]),
        ("هزینه مالیات بر درآمد", [-87428386, -50000000, 0, 74]),
        ("سود(زیان)خالص", [1025278132, 525848988, 0, 95]),
        ("سود(زیان) پایه هر سهم (ریال)", [0, 0, 0, None]),
        ("سود (زیان) خالص هر سهم– ریال", [303, 155, 0, 95]),
        ("سرمایه", [3382000000, 3382000000, 0, 0]),
    ])
    st = cr.statement(g, "income", "1405/12/29")
    it = st["items"]
    assert st["layout"] == "bank" and not {"cost_of_revenue", "selling_admin_expenses", "eps"} & set(st["missing"])
    assert it["cost_of_revenue"]["current"] == -1220160496 and it["selling_admin_expenses"]["current"] == -707453017
    assert it["loan_interest_income"]["current"] == 1835435722 and it["fee_income"]["current"] == 264372382
    assert it["eps"] == {"current": 303, "previous": 155, "last_year": 0} and st["notes"]
    assert cr.ttm(it, "net_profit", 6) is None  # a 0 full-year column is missing, not zero profit
    it["net_profit"]["last_year"] = 1200000000
    assert cr.ttm(it, "net_profit", 6) == 1200000000 + 1025278132 - 525848988


def test_bank_balance_sheet_sums_loans_and_skips_the_current_split():
    g = bank_grid([
        ("موجودی نقد", [3536996227, 2718638069, 0, None]),
        ("تسهیلات اعطایی و مطالبات از اشخاص دولتی", [28271151298, 1, 0, None]),
        ("تسهیلات اعطایی و مطالبات از اشخاص غیر دولتی", [16938083501, 1, 0, None]),
        ("سپرده قانونی", [3209073832, 1, 0, None]),
        ("جمع دارایی‌ها", [59110304681, 1, 0, None]),
        ("سپرده‌های مشتریان", [27590264476, 1, 0, None]),
        ("بدهی به بانکها و موسسات اعتباری غیر بانکی", [8454139269, 1, 0, None]),
        ("جمع بدهی‌ها", [52628589262, 1, 0, None]),
        ("سرمایه", [3382000000, 1, 0, None]),
        ("سود (زیان) انباشته", [2021921399, 1, 0, None]),
        ("جمع حقوق مالکانه", [6481715419, 1, 0, None]),
    ])
    st = cr.statement(g, "balance", "1405/12/29")
    assert st["layout"] == "bank"
    assert st["items"]["loans"]["current"] == 28271151298 + 16938083501
    assert "current_assets" not in st["missing"] and "inventory" not in st["missing"]
    r = cr.ratios({"items": {}}, st, {"items": {}}, 6)
    assert r["loans_to_deposits_pct"] == round((28271151298 + 16938083501) / 27590264476 * 100, 1)
    assert r["equity_to_assets_pct"] == round(6481715419 / 59110304681 * 100, 1)


def test_bank_cash_flow_labels():
    g = bank_grid([
        ("جریان ‌خالص ‌ورود‌ (خروج) ‌نقد حاصل از فعالیت‌های ‌عملیاتی", [386206543, 1, 1, None]),
        ("پرداخت های نقدی برای تحصیل دارایی ثابت مشهود", [-43082895, 1, 1, None]),
        ("جریان خالص ورود(خروج) نقد ناشی از فعالیت های تامین مالی", [-141868091, 1, 1, None]),
    ])
    it = cr.statement(g, "cashflow", "1405/12/29")["items"]
    assert it["capex"]["current"] == -43082895 and it["financing_cash_flow"]["current"] == -141868091


def test_bank_monthly_report():
    # بانک ملت, month ending 1405/07/30 (template «گزارش فعالیت ماهانه بانک- V4»): no production-and-sales table
    m = cr.monthly(cr.datasource(page("bank_monthly")))
    assert m["template"] == "bank" and m["month_end"] == "1405/07/30"
    assert m["month_sales"] == 311887001 + 17451513 + 24244406 + 10001216 + 62474312
    assert m["ytd_sales"] == 2128753985 + 202946805 + 162154589 + 10559307 + 415038703
    b = m["bank"]
    assert (b["loans_end"], b["deposits_end"]) == (53299293375, 28648495309)
    assert (b["loan_interest_month"], b["deposit_interest_month"], b["net_interest_month"]) == (311887001, 201896614, 311887001 - 201896614)
    assert b["loans_granted_month"] == 6586648674
    assert [p["item"] for p in m["products"]][0] == "درآمد تسهیلات اعطایی"


def test_monthly_report_without_a_known_layout_returns_its_tables():
    ds = cr.datasource(page("monthly"))
    for sheet in ds["sheets"]:
        for t in sheet["tables"]:
            t["title_Fa"] = "درآمد"  # a sales-like title, but none of the production-and-sales columns
            for c in t["cells"]:
                if isinstance(c.get("value"), str) and "یک ماهه" in c["value"]:
                    c["value"] = c["value"].replace("یک ماهه", "")
    m = cr.monthly(ds)
    assert "tables" in m and "month_sales" not in m


def test_side_by_side_balance_sheet_of_an_insurer():
    # بیمه البرز, 1405/06/31 (template «بیمه- بورسی - V3»): assets on the left, liabilities and equity on the right of one table
    cols = ["پایان عملکرد واقعی منتهی به 1405/06/31", "(تجدیدارائه‌شده) 1404/12/29", "درصد تغییرات", "",
            "پایان عملکرد واقعی منتهی به 1405/06/31", "(تجدیدارائه‌شده) 1404/12/29", "درصد تغییرات"]
    rows = [
        ("دارایی‌ها", [None, None, None, "بدهی‌ها", None, None, None]),
        ("موجودی نقد", [65667040, 42269588, 55, "بدهی به بیمه‌گذاران و نمایندگان", 32990208, 20420652, 62]),
        ("مطالبات از بیمه‌گذاران و نمایندگان", [455074490, 272010875, 67, "ذخیره خسارت معوق", 136095212, 92354589, 47]),
        ("دارایی‌های ثابت مشهود", [45503370, 38558577, 18, "ذخیره حق بیمه عاید نشده", 382014413, 216621788, 76]),
        (None, [None, None, None, "سایر ذخایر فنی", 52984300, 35825756, 48]),
        (None, [None, None, None, "جمع بدهی ها", 797891449, 518432546, 54]),
        (None, [None, None, None, "سرمایه", 81807822, 70000000, 17]),
        (None, [None, None, None, "جمع حقوق مالکانه", 230269171, 178041126, 29]),
        ("جمع دارایی‌ها", [1028160620, 696473672, 48, "جمع بدهی‌ها و حقوق مالکانه", 1028160620, 696473672, None]),
    ]
    g = {"columns": cols, "rows": [{"label": lab, "values": vals} for lab, vals in rows]}
    left, right = cr.halves(g)
    assert left["columns"] == cols[:3] and right["columns"] == cols[4:]
    st = cr.statement(g, "balance", "1405/12/29")
    it = st["items"]
    assert st["layout"] == "insurer" and st["missing"] == ["retained_earnings"]  # not in this cut-down table
    assert it["total_assets"] == {"current": 1028160620, "last_year": 696473672}  # the year-end column
    assert it["total_liabilities"]["current"] == 797891449 and it["equity"]["current"] == 230269171
    assert it["technical_reserves"]["current"] == 136095212 + 382014413 + 52984300


def test_insurer_income_items_and_loss_ratio():
    g = bank_grid([
        ("درآمد حق بیمه ناخالص", [320924697, 162962285, 382494004, 97]),
        ("حق بیمه خالص (سهم نگهداری)", [286569426, 147499819, 344757117, 94]),
        ("درآمدهای بیمه ای", [337213222, 164121195, 395948111, 105]),
        ("خسارت و مزایای پرداختی خالص", [-221277884, -105078384, -279315538, 111]),
        ("سود (زیان) ناخالص فعالیتهای بیمه ای", [69628905, 36310652, 67922384, 92]),
        ("سود (زیان) خالص", [62044983, 28237698, 61990476, 120]),
    ])
    st = cr.statement(g, "income", "1405/12/29")
    assert st["layout"] == "insurer" and "cost_of_revenue" not in st["missing"]
    assert st["items"]["revenue"]["current"] == 337213222 and st["items"]["gross_profit"]["current"] == 69628905
    r = cr.ratios(st, {"items": {}}, {"items": {}}, 6)
    assert r["loss_ratio_pct"] == round(221277884 / 286569426 * 100, 1)


def test_a_unit_cell_in_the_first_value_column_is_not_a_second_half():
    g = {"columns": ["a 1405/06/31", "b 1404/12/29"], "rows": [{"label": "دارایی ها", "values": ["میلیون ریال", None]},
                                                            {"label": "جمع دارایی‌ها", "values": [10, 9]}]}
    assert cr.halves(g) == [g]
