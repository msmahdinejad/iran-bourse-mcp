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
