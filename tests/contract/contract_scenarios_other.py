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
