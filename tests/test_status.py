"""Trading status: supervision lists, state log and symbol history against payloads recorded live on 2026-11-04."""

from __future__ import annotations

import pytest

from iran_bourse_mcp import status as S


def lists_for(fx, **named):
    """{(source, listType): rows} from fixtures: lists_for(fx, a=((1, 3), 'status_supervision_1_3'))"""
    return {pair: fx(name)["supervision"] for pair, name in named.values()}


@pytest.fixture()
def suspended(fx):
    return lists_for(fx, bourse=((1, 3), "status_supervision_1_3"), fara=((2, 3), "status_supervision_2_3"))


# ------------------------------------------------------------------------------------------- plan


def test_plan_names_what_to_download():
    assert S.plan_trading_status("suspended").supervision_lists == ((1, 3), (2, 3))
    assert S.plan_trading_status("suspended", "bourse").supervision_lists == ((1, 3),)
    assert S.plan_trading_status("supervision", "Fara").supervision_lists == ((2, 1), (2, 2))
    assert S.plan_trading_status("supervision", None, "دانا", 5).supervision_lists == ((1, 1), (1, 2), (2, 1), (2, 2))
    state = S.plan_trading_status("state_changes", None, None, 10)
    assert (state.state_top, state.supervision_lists, state.limit) == (200, (), 10)  # a small limit still reads 200 records
    assert S.plan_trading_status("state_changes", None, None, 250).state_top == 250
    history = S.plan_trading_status("symbol_history", symbol="  فولاد ")
    assert (history.symbol, history.state_top, history.supervision_lists) == ("فولاد", None, ())
    assert [S.parse_sources(m) for m in (None, "", "both", "ALL", "bourse", " Fara ", "ifb", 1, 2)] == [(1, 2), (1, 2), (1, 2), (1, 2), (1,), (2,), (2,), (1,), (2,)]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("halted",), "kind must be one of suspended, supervision, state_changes, symbol_history"),
        (("symbol_history",), "symbol is required for kind='symbol_history'"),
        (("state_changes", None, "فولاد"), "use kind='symbol_history' for one symbol"),
        (("suspended", "mars"), "market 'mars' is not recognised"),
        (("suspended", 3), "market '3' is not recognised"),
        (("suspended", None, None, 0), "limit must be a whole number between 1 and 300"),
        (("suspended", None, None, 301), "limit must be"),
        (("suspended", None, None, True), "limit must be"),
    ],
)
def test_plan_errors_tell_the_agent_what_to_do(args, message):
    with pytest.raises(ValueError, match=message):
        S.plan_trading_status(*args)


# ------------------------------------------------------------------------------------------- text


def test_reasons_become_plain_persian_lines():
    assert S.split_reasons("عدم ارائه گزارش<br>بررسی وضعیت<br>") == ["عدم ارائه گزارش", "بررسی وضعیت"]
    assert S.split_reasons("<br>نیاز به بررسی") == ["نیاز به بررسی"]  # the Fara Bourse lists start with a break
    assert S.split_reasons("a<BR/>b<br />c <b>bold</b>&amp;d<br>a") == ["a", "b", "c bold &d"]  # tags dropped, entities decoded, duplicates folded
    assert S.split_reasons("معاملات در بازار عادي<br>  كتاب ") == ["معاملات در بازار عادی", "کتاب"]  # Arabic letters become Persian
    assert S.split_reasons("") == S.split_reasons(None) == S.split_reasons("<br><br>") == []


# ----------------------------------------------------------------------------------- suspended


def test_suspended_symbols_of_both_markets(suspended):
    out = S.shape_supervision(suspended, kind="suspended", limit=50)
    assert out["kind"] == "suspended" and out["total"] == out["count"] == 6
    assert out["summary"] == {"بورس": {"suspended": 4}, "فرابورس": {"suspended": 2}}
    assert out["meaning"].keys() == {"suspended"} and "halted" in out["meaning"]["suspended"]
    assert [r["symbol"] for r in out["rows"]] == ["دانا", "زکوثر", "وآداک", "وسخراش", "وسرضوی", "کهرام"]  # undated rows run A-Z
    dana = out["rows"][0]
    assert (dana["name"], dana["ins_code"], dana["market"]) == ("بیمه دانا", "48511238766369097", "بورس")
    assert (dana["status"], dana["status_title"]) == ("suspended", "تعلیق شده") and dana["since"] is None and dana["extra"] is None
    assert dana["reasons"] == ["بررسی وضعیت شفافیت اطلاعاتی ناشر"]
    assert len(out["rows"][1]["reasons"]) == 4  # four <br> separated lines in the raw text
    assert out["rows"][4]["reasons"] == ["عدم ارائه گزارش فعالیت ماهانه اردیبهشت ماه", "بررسی وضعیت شفافیت اطلاعاتی ناشر"]
    fara = out["rows"][5]
    assert (fara["symbol"], fara["market"]) == ("کهرام", "فرابورس") and fara["reasons"][0].startswith("ظنّ وقوع جرائم موضوع ماده 46")
    assert fara["reasons"][0].endswith("در بازار عادی")
    assert "carry no date" in out["notes"][0]


def test_one_symbol_is_found_whatever_the_letters(suspended):
    out = S.shape_supervision(suspended, kind="suspended", symbol="وسرضوي")
    assert out["total"] == 1 and out["rows"][0]["symbol"] == "وسرضوی"
    missing = S.shape_supervision(suspended, kind="suspended", symbol="فولاد")
    assert missing["rows"] == [] and missing["total"] == 0 and "'فولاد' is not on the suspended lists" in missing["notes"][0]
    one = S.shape_supervision({(1, 3): suspended[(1, 3)]}, kind="suspended", symbol="فولاد")
    assert "of this market" in one["notes"][0]


def test_limit_and_empty_lists(fx, suspended):
    out = S.shape_supervision(suspended, kind="suspended", limit=2)
    assert out["count"] == 2 and out["total"] == 6 and any("4 more rows" in n for n in out["notes"])
    empty = S.shape_supervision({(1, 2): fx("status_supervision_1_2")["supervision"]}, kind="supervision")
    assert empty["rows"] == [] and empty["summary"] == {} and empty["notes"] == ["No symbols on this list right now."]


# --------------------------------------------------------------------------------- supervision


def test_supervision_lists_keep_their_status_and_take_dates_from_the_gateway(fx):
    lists = lists_for(fx, a=((1, 1), "status_supervision_1_1"), b=((2, 1), "status_supervision_2_1"))
    plain = S.shape_supervision(lists, kind="supervision", limit=50)
    assert plain["total"] == 6 and plain["summary"] == {"بورس": {"subject_to_suspension": 3}, "فرابورس": {"subject_to_suspension": 3}}
    assert {r["status_title"] for r in plain["rows"]} == {"مشمول فرآیند تعلیق"} and all(r["since"] is None for r in plain["rows"])
    assert "still trades" in plain["meaning"]["subject_to_suspension"]
    zparse = next(r for r in plain["rows"] if r["symbol"] == "زپارس")
    assert len(zparse["reasons"]) == 2 and zparse["reasons"][0].startswith("عدم ارائه صورتهای مالی میاندوره ای 6 ماهه")
    dated = S.shape_supervision(lists, kind="supervision", limit=50, company_states=fx("status_company_state"))
    first = dated["rows"][0]
    assert (first["symbol"], first["since"], first["since_jdate"], first["market"]) == ("سیدکو", "2026-11-03", "1405/08/12", "بورس")  # 1405/08/12
    assert sum(1 for r in dated["rows"] if r["since"]) == 1  # the gateway lists Bourse companies only, and only this one is in the fixture
    assert [r["symbol"] for r in dated["rows"][1:4]] == sorted(r["symbol"] for r in dated["rows"][1:4])
    assert not any("carry no date" in n for n in dated.get("notes", []))


def test_company_states_parse_the_symbol_out_of_the_name(fx):
    since = S._company_since(fx("status_company_state"))
    assert since == {"سیدکو": 20261103, "رمپنا": 20261103, "شیران": 20261031}  # 1405/08/12, 1405/08/12, 1405/08/09
    rows = [{"nam": "فولاد(فولاد مبارکه)", "lastdatechange": "1405/13/45"}, {"nam": "x(y)", "lastdatechange": ""}, {"nam": "ب(پ)", "kodenamaddarsamane": "كد", "lastdatechange": "1405/08/01"}, {}]
    assert S._company_since(rows) == {"کد": 20261023} and S._company_since(None) == {}


# ---------------------------------------------------------------------------------- state log


def test_state_codes_are_the_exchanges_own(fx):
    assert set(S.STATE_CODES) == {"A", "AR", "AS", "AG", "I", "IR", "IS"}
    for fixture in ("status_state_top", "status_state_all"):
        for raw in fx(fixture)["instrumentState"]:
            info = S.state_info(raw["cEtaval"], raw["cEtavalTitle"])
            assert info.title == raw["cEtavalTitle"] and info.category != "unknown"
    assert [S.STATE_CODES[c].category for c in ("A", "AR", "AS", "AG", "I", "IR", "IS")] == ["open", "reserved", "stopped", "blocked", "closed", "reserved", "stopped"]
    assert [c for c, i in S.STATE_CODES.items() if i.matching] == ["A"] and [c for c, i in S.STATE_CODES.items() if i.orders] == ["A", "AR", "AS", "AG"]
    odd = S.state_info("ZZ", "عجیب")
    assert (odd.title, odd.category, odd.orders, odd.matching) == ("عجیب", "unknown", False, False) and "ZZ" in odd.meaning
    assert S.state_info(None).title == "?" and S.state_info(" a ").category == "open"


def test_state_change_log(fx):
    out = S.shape_state_changes(fx("status_state_top")["instrumentState"], limit=3)
    assert (out["records_read"], out["symbols_in_sample"], out["count"]) == (14, 5, 3)
    first, second, third = out["rows"]
    assert (first["symbol"], first["name"], first["date"], first["jdate"], first["time"]) == ("ثنوسا", "نوسازی‌وساختمان‌تهران‌", "2026-11-04", "1405/08/13", "18:45:44")
    assert (first["state"], first["state_title"], first["category"], first["orders_accepted"], first["trading"]) == ("IS", "ممنوع-متوقف", "stopped", False, False)
    assert (second["state"], second["category"]) == ("I", "closed")  # two records in the same second keep the exchange's order
    assert (third["symbol"], third["time"], third["state"], third["category"], third["orders_accepted"]) == ("زعف0610پ19", "18:17:10", "AR", "reserved", True)
    sample = out["sample"]
    assert (sample["from"], sample["to"]) == ("2026-11-04", "2026-11-04")
    assert sample["records_by_state"] == {"A": 5, "AR": 4, "I": 3, "IS": 1, "AS": 1}  # 14 records
    assert sample["latest_state_by_symbol"] == {"AR": 2, "A": 2, "IS": 1}  # newest record of each of the 5 symbols
    assert set(out["state_codes"]) == {"A", "AR", "AS", "I", "IS"} and out["state_codes"]["AS"].startswith("مجاز-متوقف: Stopped")
    assert any("no market field" in n for n in out["notes"])
    assert len(S.shape_state_changes(fx("status_state_top")["instrumentState"], limit=99)["rows"]) == 14


def test_state_log_is_sorted_even_when_the_exchange_is_not(fx):
    rows = list(reversed(fx("status_state_top")["instrumentState"]))
    out = S.shape_state_changes(rows, limit=14)
    stamps = [(r["date"], r["time"]) for r in out["rows"]]
    assert stamps == sorted(stamps, reverse=True) and stamps[0] == ("2026-11-04", "18:45:44")
    empty = S.shape_state_changes(None)
    assert empty["rows"] == [] and empty["sample"]["from"] is None and "no state records" in empty["notes"][-1]


# -------------------------------------------------------------------------------- symbol history


def test_symbol_history_with_its_supervision_record(fx):
    record = fx("status_supervision_record")["supervision"]
    out = S.shape_symbol_history(fx("status_state_all")["instrumentState"], instrument={"symbol": "دانا"}, supervision=record, limit=5)
    assert (out["records"], out["count"], out["first_record"]) == (14, 5, "2026-08-17")
    current = out["current"]
    assert (current["date"], current["time"], current["state"], current["category"], current["trading"]) == ("2026-10-03", "11:10:01", "IS", "stopped", False)
    assert "halted symbol" in current["meaning"]
    assert [(h["time"], h["state"]) for h in out["history"]] == [("11:10:01", "IS"), ("11:10:01", "IR"), ("10:41:57", "AR"), ("10:41:56", "IR"), ("09:41:36", "IS")]
    assert out["records_by_state"] == {"IR": 4, "IS": 3, "AR": 3, "A": 2, "I": 2}  # 14 records
    assert out["instrument"] == {"symbol": "دانا"}
    assert out["supervision"] == {
        "status": "suspended", "status_title": "تعلیق شده", "meaning": S.SUPERVISION_LISTS[3][2],
        "reasons": ["بررسی وضعیت شفافیت اطلاعاتی ناشر"], "since": "2026-10-05", "since_jdate": "1405/07/13",
    }
    assert "supervision" not in S.shape_symbol_history(fx("status_state_all")["instrumentState"], limit=1)
    assert S.shape_symbol_history(fx("status_state_all")["instrumentState"], limit=1)["count"] == 1


def test_supervision_record_of_a_clean_symbol_and_of_nothing(fx):
    clean = S.shape_supervision_record(fx("status_supervision_record_clean")["supervision"])
    assert clean == {"status": "none", "status_title": None, "reasons": [], "since": None, "since_jdate": None}
    assert S.shape_supervision_record(None) is None and S.shape_supervision_record([]) is None
    warned = S.shape_supervision_record({"underSupervision": 1, "reasons": "a<br>b<br>", "insertionDateTime": "0001-01-01T00:00:00", "underSupervisionTitle": ""})
    assert warned["status"] == "subject_to_suspension" and warned["since"] is None and warned["status_title"] == "مشمول فرآیند تعلیق"
    assert warned["reasons"] == ["a", "b"]


def test_symbol_without_state_records():
    out = S.shape_symbol_history([], instrument={"symbol": "نو"})
    assert out["records"] == 0 and out["history"] == [] and "current" not in out and "no state records" in out["notes"][-1]
    assert S.shape_symbol_history(None)["records"] == 0
