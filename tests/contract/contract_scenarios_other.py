"""Contract scenarios: Codal and the glossary."""

from __future__ import annotations

from contract_helpers import assert_keys, clean
from contract_replay import scenario

from iran_bourse_mcp.text import ascii_digits

CODAL = "https://codal.ir"


@scenario("codal_filings", "codal_filings", codal=True, symbol="فولاد", limit=5)
def _codal_filings(run):
    out, raw = run.out, run.rec.body("search.codal.ir")
    assert_keys(out, "total_matches pages page returned filings note")
    assert (out["total_matches"], out["pages"], out["page"], out["returned"]) == (
        raw["Total"],
        raw["Page"],
        1,
        5,
    )
    assert "Jalali" in out["note"]
    for filing, letter in zip(out["filings"], raw["Letters"], strict=False):
        assert_keys(
            filing,
            "tracing_no symbol company title letter_code published sent under_supervision is_estimate has links",
        )
        assert (filing["tracing_no"], filing["symbol"], filing["company"]) == (
            letter["TracingNo"],
            clean(letter["Symbol"]),
            clean(letter["CompanyName"]),
        )
        assert (filing["title"], filing["letter_code"]) == (
            clean(letter["Title"]),
            clean(letter["LetterCode"]),
        )
        assert (filing["published"], filing["sent"]) == (
            ascii_digits(letter["PublishDateTime"]),
            ascii_digits(letter["SentDateTime"]),
        )  # Jalali, as shown on Codal
        assert filing["has"] == {
            "html": letter["HasHtml"],
            "pdf": letter["HasPdf"],
            "excel": letter["HasExcel"],
            "xbrl": letter["HasXbrl"],
            "attachment": letter["HasAttachment"],
        }
        assert_keys(filing["links"], "page pdf excel attachments")
        links = filing["links"]
        assert links["page"] == CODAL + letter["Url"]
        assert (links["pdf"] is not None) == letter["HasPdf"] and (
            links["excel"] is not None
        ) == letter["HasExcel"]  # only links that exist
        assert (links["attachments"] is not None) == letter["HasAttachment"]
        for link in links.values():
            assert link is None or link.startswith(("https://codal.ir/", "https://excel.codal.ir/"))


@scenario("codal_company", "codal_company", symbol="فولاد")
def _codal_company(run):
    out, raw = run.out, run.rec.body("GetCodalPublisherBySymbol")["codalPublisher"]
    assert_keys(out, "instrument available name isic ceo address phone fax activity")
    assert out["available"] is True and out["instrument"]["symbol"] == "فولاد"
    assert (out["name"], out["isic"], out["ceo"]) == (
        clean(raw["name"]),
        raw["isic"],
        clean(raw["executiveManager"]),
    )
    assert (out["address"], out["phone"], out["fax"], out["activity"]) == (
        clean(raw["address"]),
        raw["telNo"],
        raw["faxNo"],
        clean(raw["activitySubject"]),
    )


@scenario("glossary", "glossary", term="صف خرید")
def _glossary(run):
    out = run.out
    assert not run.rec.items  # the glossary is built into the server
    assert_keys(out, "query matches hint")
    assert out["query"] == "صف خرید" and out["hint"] is None
    assert set(out["matches"]) == {"صف خرید"}
    entry = out["matches"]["صف خرید"]
    assert_keys(entry, "en meaning")
    assert entry["en"] == "buy queue" and "upper limit" in entry["meaning"]


# ----------------------------------------------------------------------------- Codal letter contents
def _datasource_of(run, fragment: str) -> dict:
    """The datasource JSON inside a recorded Codal page, read independently of codal_reports."""
    import json

    text = run.rec.get(fragment).text
    start = text.index("var datasource = ") + len("var datasource = ")
    return json.JSONDecoder().raw_decode(text, start)[0]


def _cell(ds: dict, label: str, column: int = 2):
    """Value in `column` of the first body row whose first cell starts with `label` (spaces, ZWNJ and letter forms ignored)."""
    import re

    norm = lambda s: re.sub(r"[\s\u200c\u200f:]", "", (s or "").replace("ي", "ی").replace("ك", "ک"))  # noqa: E731
    for sheet in ds["sheets"]:
        for table in sheet["tables"]:
            rows: dict[int, dict[int, str]] = {}
            for c in table["cells"]:
                rows.setdefault(c["rowSequence"], {})[c["columnSequence"]] = c["value"]
            for seq in sorted(rows):
                if norm(rows[seq].get(1)) == norm(label) and (rows[seq].get(column) or "").lstrip("-").isdigit():
                    return int(rows[seq][column])
    raise AssertionError(f"no row {label!r}")


@scenario("codal_letter", "codal_letter", codal=True, tracing_no=1612323)
def _codal_letter(run):
    out = run.out
    assert_keys(out, "tracing_no symbol company title letter_code published sent under_supervision is_estimate has links report sheets sheet unit_note listed_capital_million_rial tables key_items note")
    assert out["tracing_no"] == 1612323 and out["symbol"] == "فولاد"
    assert out["report"]["period_end"] == "1405/06/31" and out["report"]["period_months"] == 6
    assert {"sheet": 0, "name": "صورت وضعیت مالی"} in out["sheets"] and out["sheet"] == 1
    ds = _datasource_of(run, "codal.ir/Reports/Decision.aspx")
    items = out["key_items"]["items"]
    assert items["revenue"]["current"] == _cell(ds, "درآمدهاي عملياتي")
    assert items["net_profit"]["current"] == _cell(ds, "سود(زيان) خالص")
    assert items["eps"]["current"] == _cell(ds, "سود(زيان) پايه هر سهم")
    assert out["tables"][0]["columns"][0].startswith("دوره منتهی به 1405/06/31")


@scenario("financial_statements", "financial_statements", codal=True, symbol="فولاد")
def _financial_statements(run):
    out = run.out
    assert_keys(out, "instrument latest units note")
    latest = out["latest"]
    assert_keys(latest, "letter report income balance cashflow ratios")
    assert "تلفیقی" not in latest["letter"]["title"] and "(شرکت" not in latest["letter"]["title"]  # own, not group or subsidiary
    inc, bal, cf = latest["income"]["items"], latest["balance"]["items"], latest["cashflow"]["items"]
    for item in (inc["revenue"], inc["net_profit"]):
        assert set(item) == {"current", "previous", "last_year"}
    # the balance sheet balances, and the ratios follow from the items
    assert bal["total_assets"]["current"] == bal["total_liabilities"]["current"] + bal["equity"]["current"]
    r = latest["ratios"]
    assert r["net_margin_pct"] == round(inc["net_profit"]["current"] / inc["revenue"]["current"] * 100, 1)
    assert r["revenue_ttm"] == inc["revenue"]["last_year"] + inc["revenue"]["current"] - inc["revenue"]["previous"]
    assert r["free_cash_flow"] == cf["operating_cash_flow"]["current"] + cf["capex"]["current"]
    assert r["debt_ratio_pct"] == round(bal["total_liabilities"]["current"] / bal["total_assets"]["current"] * 100, 1)


@scenario("monthly_activity", "monthly_activity", codal=True, symbol="فولاد", months=2)
def _monthly_activity(run):
    out = run.out
    assert_keys(out, "instrument reports units note")
    newest, older = out["reports"]
    assert newest["month_end"] > older["month_end"]
    assert "products" in newest and "products" not in older
    assert newest["month_change_pct"] == round((newest["month_sales"] - older["month_sales"]) / older["month_sales"] * 100, 1)
    assert newest["ytd_growth_pct"] == round((newest["ytd_sales"] - newest["ytd_sales_last_year"]) / newest["ytd_sales_last_year"] * 100, 1)
    assert sum(p.get("month_amount", 0) for p in newest["products"]) >= newest["month_sales"] * 0.5


@scenario("fundamentals", "fundamentals", codal=True, symbol="فولاد")
def _fundamentals(run):
    out = run.out
    assert_keys(out, "instrument market latest_statement profitability balance_sheet valuation monthly_sales units")
    m, v = out["market"], out["valuation"]
    assert m["market_cap"] == int(m["price"] * m["shares_outstanding"])  # the same price as the ratios
    assert v["pe_ttm_estimated"] == round(m["price"] / v["eps_ttm_estimated"], 2)
    # the computed trailing EPS lands close to the exchange's own EPS for a company that has published its statements
    assert abs(v["eps_ttm_estimated"] - m["exchange_eps"]) / m["exchange_eps"] < 0.15
    assert "estimated" in v["note"] or "not published" in v["note"]
