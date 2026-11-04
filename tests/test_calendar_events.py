"""Corporate-action calendar: payloads recorded live on 2026-11-04 (reference 'today'), plus edge rows built from them."""

from __future__ import annotations

import datetime as dt

import pytest

from iran_bourse_mcp import calendar_events as C

TODAY = dt.date(2026, 11, 4)  # a Wednesday; the market was closed and the day's data existed


@pytest.fixture()
def sc(fx):
    return fx("calendar_share_changes")["instrumentShareChange"]


@pytest.fixture()
def pa(fx):
    return fx("calendar_price_adjust")["priceAdjust"]


def cal(sc, pa=None, **kw):
    kw.setdefault("today", TODAY)
    return C.capital_calendar(sc, pa, **kw)


def keys(out):
    return [(e["date"], e["symbol"], e["kind"]) for e in out["events"]]


def share_row(code, day, old, new, symbol="سهم"):
    return {"idn": 0, "insCode": code, "dEven": day, "numberOfShareNew": new, "numberOfShareOld": old, "lVal30": "شرکت " + symbol, "lVal18AFC": symbol}


# ------------------------------------------------------------------------------------------ upcoming


def test_upcoming_is_strictly_after_today(sc, pa):
    out = cal(sc, pa, direction="upcoming", days=30)
    assert out["window"] == {"from": "2026-11-05", "to": "2026-12-04"} and out["today"] == "2026-11-04" and out["today_jdate"] == "1405/08/13"
    assert (out["count"], out["total_in_window"], out["counts"]) == (1, 1, {"capital_increase": 1})
    event = out["events"][0]
    assert (event["date"], event["jdate"], event["days_from_today"], event["status"]) == ("2026-11-07", "1405/08/16", 3, "upcoming")
    assert (event["symbol"], event["name"], event["market"], event["flow"]) == ("لبوتان", "گروه‌صنعتی‌بوتان‌", "بورس", 1)
    assert (event["shares_before"], event["shares_after"], event["added_shares"]) == (14_267_348_000, 26_000_000_000, 11_732_652_000)
    assert event["increase_pct"] == 82.23 and event["ratio"] == 1.8223  # 11,732,652,000 / 14,267,348,000 ; 26e9 / 14,267,348,000
    assert event["label"] == "capital increase (افزایش سرمایه) +82.23%: 14,267,348,000 -> 26,000,000,000 shares"
    assert out["coverage"] == {"share_changes_latest": "2026-11-07", "price_adjustments_from": "2018-07-24", "price_adjustments_to": "2026-10-24"}
    assert any("Codal" in n for n in out["notes"]) and any("few days ahead" in n for n in out["notes"])
    assert cal(sc, pa, direction="upcoming", days=2)["events"] == []  # 11-07 is 3 days away
    assert cal(sc, pa, direction="upcoming", days=3)["count"] == 1


def test_an_empty_window_says_so(sc):
    out = cal(sc, None, direction="upcoming", days=1, kind="capital_increase")
    assert out["events"] == [] and out["total_in_window"] == 0 and any("No events" in n for n in out["notes"])
    assert cal(None, None)["events"] == [] and cal([], [])["counts"] == {}


# -------------------------------------------------------------------------------------------- recent


def test_recent_includes_today_and_runs_newest_first(sc, pa):
    out = cal(sc, pa, direction="recent", days=30)
    assert out["window"] == {"from": "2026-10-05", "to": "2026-11-04"}
    # newest day first, symbols A-Z within a day
    assert [(e["date"], e["symbol"]) for e in out["events"]] == [
        ("2026-11-04", "دفرا"), ("2026-11-04", "فاما"), ("2026-11-04", "چاپ"), ("2026-10-26", "ولپارس"),
        ("2026-10-24", "شستا"), ("2026-10-24", "غچین"), ("2026-10-21", "تپمپی"), ("2026-10-18", "کهمدا"),
    ]
    assert out["counts"] == {"capital_increase": 4, "price_adjustment": 4}
    today_events = [e for e in out["events"] if e["status"] == "today"]
    assert len(today_events) == 3 and all(e["days_from_today"] == 0 for e in today_events)
    first, second, third = today_events
    assert (first["increase_pct"], first["ratio"], first["added_shares"]) == (100.0, 2.0, 7_000_000_000)  # 7e9 -> 14e9
    assert (second["increase_pct"], second["ratio"]) == (38.4, 1.384)  # 4.8e9 / 12.5e9
    assert (third["increase_pct"], third["ratio"]) == (78.57, 1.7857)  # 4.4e9 / 5.6e9
    assert out["events"][3]["days_from_today"] == -9 and out["events"][3]["status"] == "past" and out["events"][3]["increase_pct"] == 17.5


def test_price_adjustment_numbers(sc, pa):
    out = cal(sc, pa, direction="recent", days=30, kind="price_adjustment")
    assert out["counts"] == {"price_adjustment": 4} and out["hidden_roundtrip_rows"] == 0
    gchin = next(e for e in out["events"] if e["symbol"] == "غچین")
    assert gchin["ins_code"] == "44850033148208596"  # the symbol sits in `instrument`: the top-level insCode of this feed is 0
    assert (gchin["price_before"], gchin["price_after"]) == (5730, 5600)
    assert gchin["factor"] == 0.977312 and gchin["adjustment_pct"] == -2.27  # 5600 / 5730 ; -130 / 5730
    assert gchin["label"] == "price adjustment (تعدیل قیمت) -2.27%: reference price cut, 5,730 -> 5,600 rial"
    assert next(e for e in out["events"] if e["symbol"] == "شستا")["adjustment_pct"] == -5.71  # -210 / 3680
    assert "flag" not in gchin and "share_count" not in gchin


def test_same_day_adjustments_chain_and_extreme_factors_are_flagged(pa):
    chained = cal(None, pa, kind="price_adjustment", direction="recent", days=3, today=dt.date(2020, 6, 24))
    assert [(e["symbol"], e["price_before"], e["price_after"]) for e in chained["events"]] == [("دالبر", 16950, 15740), ("دالبر", 31960, 16950)]
    assert [(e["factor"], e["adjustment_pct"]) for e in chained["events"]] == [(0.928614, -7.14), (0.53035, -46.96)]  # 15740 / 16950, 16950 / 31960
    glitch = cal(None, pa, kind="price_adjustment", direction="recent", days=3, today=dt.date(2018, 7, 26))
    low, high = glitch["events"]  # 2018-07-25 then 2018-07-24: prices of دانا that were rescaled by a million
    assert (low["date"], low["factor"], low["adjustment_pct"]) == ("2018-07-25", 3e-06, -100.0)
    assert high["factor"] == 456134.555208 and high["adjustment_pct"] > 4e7
    assert low["flag"].startswith("extreme_factor") and high["flag"].startswith("extreme_factor")


# ------------------------------------------------------------------- the paired share-count rows


def test_temporary_reductions_are_folded_into_the_price_adjustment(sc, pa):
    out = cal(sc, pa, direction="recent", days=120)
    assert out["counts"] == {"capital_increase": 4, "price_adjustment": 6}
    assert out["hidden_roundtrip_rows"] == 4 and not any(e["kind"] == "capital_decrease" for e in out["events"])
    assert any("4 paired share-count rows" in n for n in out["notes"])
    karazi = next(e for e in out["events"] if e["symbol"] == "کرازی")
    assert (karazi["date"], karazi["price_before"], karazi["price_after"], karazi["adjustment_pct"]) == ("2026-07-25", 914, 879, -3.83)  # -35 / 914
    assert karazi["share_count"] == {"temporarily": 42_750_000_000, "before_and_after": 49_100_000_000, "restored_on": "2026-07-27"}
    tasiko = next(e for e in out["events"] if e["symbol"] == "تاصیکو")
    assert tasiko["share_count"]["restored_on"] == "2026-09-16" and tasiko["adjustment_pct"] == -3.51  # -480 / 13690


def test_roundtrip_rows_can_be_asked_for(sc):
    out = cal(sc, None, direction="recent", days=120, kind="share_count_roundtrip")
    assert [(e["date"], e["symbol"], e["part"]) for e in out["events"]] == [
        ("2026-09-16", "تاصیکو", "restoration"), ("2026-09-14", "تاصیکو", "temporary_reduction"),
        ("2026-07-27", "کرازی", "restoration"), ("2026-07-25", "کرازی", "temporary_reduction"),
    ]
    assert out["events"][1]["label"] == "share count temporarily back to 67,500,000,000 (restored 2026-09-16)"
    assert out["events"][0]["label"] == "share count restored to 95,500,000,000 after the temporary reduction of 2026-09-14"
    assert out["events"][1]["partner_date"] == "2026-09-16" and "hidden_roundtrip_rows" not in out
    # the original increases that preceded the pairs are ordinary capital increases
    earlier = cal(sc, None, direction="recent", days=300, kind="capital_increase", limit=100)
    assert [(e["date"], e["symbol"], e["increase_pct"]) for e in earlier["events"] if e["symbol"] in ("کرازی", "تاصیکو")] == [
        ("2026-04-22", "کرازی", 14.85),  # 6.35e9 / 42.75e9
        ("2026-03-30", "تاصیکو", 41.48),  # 28e9 / 67.5e9
    ]


def test_roundtrip_detection_rules():
    rows = [
        share_row("1", 20260101, 100.0, 150.0), share_row("1", 20260201, 150.0, 100.0), share_row("1", 20260204, 100.0, 150.0),  # a pair
        share_row("2", 20260201, 150.0, 100.0), share_row("2", 20260215, 100.0, 150.0),  # restored after 14 days: two real events
        share_row("3", 20260201, 150.0, 100.0), share_row("3", 20260203, 100.0, 140.0),  # restored to a different count
        share_row("4", 20260201, 150.0, 100.0), share_row("4", 20260203, 100.0, 150.7),  # within 1 %: still a pair
        share_row("5", 20260201, 1000.0, 1000.0), share_row("5", 20261340, 1.0, 2.0), share_row("5", 0, 1.0, 2.0),  # no change / impossible / missing date
        {"insCode": "6", "dEven": 20260201, "numberOfShareOld": None, "numberOfShareNew": 5.0, "lVal18AFC": "x"},
    ]
    out = cal(rows, None, direction="recent", days=100, today=dt.date(2026, 3, 1), limit=50)
    by_code = {}
    for e in out["events"]:
        by_code.setdefault(e["ins_code"], []).append((e["date"], e["kind"]))
    assert by_code["1"] == [("2026-01-01", "capital_increase")]  # the original increase stays; only the pair is hidden
    assert "4" not in by_code and "5" not in by_code and "6" not in by_code
    assert sorted(by_code["2"]) == [("2026-02-01", "capital_decrease"), ("2026-02-15", "capital_increase")]
    assert sorted(by_code["3"]) == [("2026-02-01", "capital_decrease"), ("2026-02-03", "capital_increase")]
    assert out["hidden_roundtrip_rows"] == 4
    shrink = next(e for e in out["events"] if e["ins_code"] == "2" and e["kind"] == "capital_decrease")
    assert (shrink["removed_shares"], shrink["change_pct"], shrink["ratio"]) == (50, -33.33, 0.6667)  # 150 -> 100


def test_genuine_decreases_and_rights_symbols(fx, sc):
    out = cal(sc, None, direction="recent", days=30, today="2012-06-01")  # a string date is accepted; so is a Jalali one
    assert cal(sc, None, direction="recent", days=30, today="1391/03/12")["events"] == out["events"]
    (event,) = out["events"]
    assert (event["kind"], event["symbol"], event["date"]) == ("capital_decrease", "رمپنا", "2012-05-22")
    assert (event["removed_shares"], event["change_pct"], event["ratio"]) == (24_896_237, -0.25, 0.9975)  # 24,896,237 / 1e10
    assert event["label"] == "capital decrease (کاهش سرمایه) -0.25%: 10,000,000,000 -> 9,975,103,763 shares"
    gone = cal(sc, None, direction="recent", days=5, today=dt.date(2015, 6, 15), kind="rights_symbol")["events"]
    assert [(e["symbol"], e["change"], e["rights_count"]) for e in gone] == [("پاساح", "removed", 220_000_000)]
    assert gone[0]["label"] == "rights instrument (حق تقدم) removed, 220,000,000 rights before" and "increase_pct" not in gone[0]
    base = fx("calendar_share_changes_base")["instrumentShareChange"]
    listed = cal({4: base}, None, flow=4, direction="recent", days=5, today=dt.date(2026, 7, 20))
    assert [(e["symbol"], e["kind"], e["change"], e["rights_count"], e["market"]) for e in listed["events"]] == [("وآتوسح", "rights_symbol", "listed", 1_800_000_000, "فرابورس - بازار پایه")]
    assert listed["events"][0]["label"] == "rights instrument (حق تقدم) listed: 1,800,000,000 rights"


# -------------------------------------------------------------------------------------------- flows


def test_all_flows_are_merged_and_labelled(fx, sc, pa):
    shares = {1: sc, 2: fx("calendar_share_changes_fara")["instrumentShareChange"], 4: fx("calendar_share_changes_base")["instrumentShareChange"]}
    adjusts = {1: pa, 2: fx("calendar_price_adjust_fara")["priceAdjust"]}
    out = cal(shares, adjusts, flow="all", direction="recent", days=3, limit=100)
    assert out["flows"] == {"1": "بورس", "2": "فرابورس", "4": "فرابورس - بازار پایه"}
    assert out["counts"] == {"capital_increase": 7, "price_adjustment": 1}
    assert {(e["market"], e["symbol"]) for e in out["events"] if e["date"] == "2026-11-04"} == {
        ("بورس", "دفرا"), ("بورس", "فاما"), ("بورس", "چاپ"), ("فرابورس", "تجلی"), ("فرابورس", "بمان")}
    fara = next(e for e in out["events"] if e["symbol"] == "تجلی" and e["kind"] == "capital_increase")
    assert (fara["increase_pct"], fara["added_shares"], fara["flow"]) == (42.41, 50_000_000_000, 2)  # 50e9 / 117.9e9 = 0.42409
    only_fara = cal({2: shares[2]}, {2: adjusts[2]}, flow="fara", direction="recent", days=3)
    assert {e["flow"] for e in only_fara["events"]} == {2} and only_fara["flows"] == {"2": "فرابورس"}
    with pytest.raises(ValueError, match="mapping when several flows"):
        cal(sc, None, flow="all")
    assert [C.parse_flows(f) for f in (None, 1, "bourse", "Fara", "ifb", "base", "fara-base", "4", "all", "ALL")] == [[1], [1], [1], [2], [2], [4], [4], [4], [1, 2, 4], [1, 2, 4]]
    for bad in (3, "derivatives", 7, True, "x"):
        with pytest.raises(ValueError, match="no corporate-action data|flow must be"):
            C.parse_flows(bad)


def test_flow_labels_come_from_the_mapping_not_the_rows(sc):
    out = cal({2: sc}, None, flow=2, direction="upcoming", days=30)  # the caller says these rows belong to flow 2
    assert out["events"][0]["market"] == "فرابورس" and out["events"][0]["flow"] == 2


# ------------------------------------------------------------------------- limits, coverage, errors


def test_limit_and_truncation_notes(fx, sc, pa):
    out = cal(sc, pa, direction="recent", days=30, limit=3)
    assert (out["count"], out["total_in_window"], len(out["events"])) == (3, 8, 3) and any("5 more events" in n for n in out["notes"])
    fara_pa = fx("calendar_price_adjust_fara")["priceAdjust"]
    cut = cal(None, {2: fara_pa}, flow=2, kind="price_adjustment", direction="recent", days=30, adjustments_top=3)
    assert any("read back to 2026-10-19 only (newest 3)" in n for n in cut["notes"])
    assert not any("read back" in n for n in cal(None, {2: fara_pa}, flow=2, kind="price_adjustment", days=30, direction="recent", adjustments_top=100)["notes"])
    assert not any("read back" in n for n in cal(None, {2: fara_pa}, flow=2, kind="price_adjustment", days=10, direction="recent", adjustments_top=3)["notes"])  # window starts after the oldest row


def test_helpers():
    assert C.sources_needed("capital_increase") == (True, False) and C.sources_needed("all") == (True, True) and C.sources_needed("price_adjustment") == (True, True)
    assert C.sources_needed("all", "upcoming") == (True, False)  # price adjustments are never dated in the future
    assert C.sources_needed("all", "recent") == (True, True)
    C.check_arguments("recent", "all", 30, 50)
    with pytest.raises(ValueError, match="days must be"):
        C.check_arguments("recent", "all", 0, 50)
    assert [C.adjustment_fetch_size(d) for d in (1, 30, 90, 366, 1000)] == [100, 300, 900, 3660, 5000]
    with pytest.raises(ValueError, match="kind must be"):
        C.sources_needed("dividends")


def test_default_today_is_the_tehran_date(monkeypatch, sc):
    monkeypatch.setattr(C, "tehran_now", lambda: dt.datetime(2026, 11, 4, 23, 40))
    out = C.capital_calendar(sc, None, direction="recent", days=1)
    assert out["today"] == "2026-11-04" and out["total_in_window"] == 3
    assert C._as_date(dt.datetime(2026, 1, 2, 3, 4)) == dt.date(2026, 1, 2) and C._as_date(20261104) == TODAY


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"direction": "soon"}, "direction must be one of upcoming, recent, all"),
        ({"kind": "dividends"}, "kind must be one of"),
        ({"days": 0}, "days must be a whole number between 1 and 366"),
        ({"days": 400}, "days must be"),
        ({"days": True}, "days must be"),
        ({"limit": 0}, "limit must be a whole number between 1 and 500"),
        ({"limit": "5"}, "limit must be"),
        ({"flow": 9}, "no corporate-action data"),
        ({"today": "not a date"}, "Cannot parse date"),
    ],
)
def test_bad_arguments_raise_value_errors_with_advice(sc, kw, message):
    with pytest.raises(ValueError, match=message):
        C.capital_calendar(sc, None, **{"today": TODAY, **kw})
