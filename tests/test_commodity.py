"""Iran Mercantile Exchange shaping: units, filters, roll-ups and argument checks, against responses recorded on 2026-11-05."""

from __future__ import annotations

import datetime as dt
import json

import pytest
from conftest import load

from iran_bourse_mcp import commodity as C
from iran_bourse_mcp.text import match_key

SESSION = 20261104  # Wednesday 1405/08/13, the recorded session


def trades_raw() -> list[dict]:
    return json.loads(load("commodity_ime_trades")["d"])


def rollup(name: str) -> list[dict]:
    return json.loads(load("commodity_ime_rollups")[name]["d"])


def request(**kwargs):
    base = {
        "view": "trades",
        "date": None,
        "to_date_": None,
        "group": None,
        "product": None,
        "traded_only": True,
        "sort_by": None,
        "limit": None,
    }
    base.update(kwargs)
    return C.plan(**base)


def shaped(**kwargs) -> dict:
    return C.shape_trades(trades_raw(), request(**kwargs), SESSION, SESSION, resolved=False)


def row_of(out: dict, symbol: str) -> dict:
    return next(r for r in out["rows"] if r["symbol"] == symbol)


# ------------------------------------------------------------------------------------ one row


def test_trade_row_names_its_units_and_converts_the_value():
    out = shaped(limit=100)
    copper = row_of(out, "SRBK-CR08AB-00")  # copper wire rod, a cash matching contract
    assert copper["product"] == "مس مفتول" and copper["matching"] is True
    assert copper["volume_tons"] == 230.0
    assert (
        copper["price_rial_per_kg"] == 33_300_441.0
        and copper["price_low_rial_per_kg"] == copper["price_high_rial_per_kg"] == 33_300_441.0
    )
    assert copper["value_rial"] == 7_659_101_430_000  # the exchange's 7,659,101,430 thousand rial
    assert copper["date"] == "2026-11-04" and copper["date_jalali"] == "1405/08/13"
    assert (
        copper["delivery_date"] == "2026-11-10" and copper["delivery_date_jalali"] == "1405/08/19"
    )
    assert (
        copper["offered_tons"] == 0.0 and copper["demand_tons"] == 230.0
    )  # matching contracts have no fixed offer
    assert copper["unit"] == "تن"


def test_value_is_price_per_kg_times_tons_times_1000_on_every_traded_row():
    traded = [r for r in shaped(limit=100)["rows"] if r["volume_tons"] > 0]
    assert len(traded) == 9
    for r in traded:
        assert (
            abs(r["price_rial_per_kg"] * r["volume_tons"] * 1000 - r["value_rial"])
            / r["value_rial"]
            < 1e-4
        ), r["symbol"]


def test_offers_that_did_not_trade_have_no_prices_and_are_hidden_by_default():
    assert all(r["volume_tons"] > 0 for r in shaped(limit=100)["rows"])
    out = shaped(traded_only=False, limit=100)
    idle = row_of(out, "SPSG-HREENNA3B-00")
    assert (
        idle["volume_tons"] == 0 and idle["price_rial_per_kg"] is None and idle["value_rial"] == 0
    )
    assert (
        idle["offered_tons"] == 216.0
        and idle["demand_tons"] == 192.0
        and idle["base_price_rial_per_kg"] is not None
    )
    assert out["totals"]["rows"] == 11 and out["totals"]["traded_rows"] == 9


# ------------------------------------------------------------------------------------ totals, roll-ups, ranking


def test_totals_are_over_the_traded_rows_and_split_by_hall_and_contract():
    out = shaped(limit=100)
    raw = [r for r in trades_raw() if r["Quantity"] > 0]
    assert out["totals"]["rows"] == out["totals"]["traded_rows"] == 9
    assert out["totals"]["value_rial"] == round(sum(r["TotalPrice"] for r in raw) * 1000)
    assert out["totals"]["volume_tons"] == round(sum(r["Quantity"] for r in raw), 3)
    assert [h["hall"] for h in out["by_hall"]] == [
        "تالار صنعتی و معدنی",
        "تالار پتروشیمی و فرآورده های نفتی",
        "تالار سیمان",
    ]
    assert sum(h["value_rial"] for h in out["by_hall"]) == out["totals"]["value_rial"]
    assert {c["contract"] for c in out["by_contract"]} == {
        "نقدی",
        "سلف",
        "نقدی (مچینگ)",
        "سلف (مچینگ)",
    }
    top = out["top_products"][0]
    assert (
        top["product"] == "مس مفتول" and top["avg_price_rial_per_kg"] == 33_300_441.0
    )  # value / kilograms
    assert out["units"] == {"volume": "tons (تن)", "price": "rial per kilogram", "value": "rial"}


def test_rows_are_ranked_and_cut_to_the_limit():
    out = shaped(limit=3)
    assert out["returned"] == 3 and out["sorted_by"] == "value desc"
    values = [r["value_rial"] for r in out["rows"]]
    assert values == sorted(values, reverse=True)
    assert [r["symbol"] for r in out["rows"]][0] == "SRBK-CR08AB-00"
    by_price = shaped(sort_by="price", limit=2)
    assert (
        by_price["rows"][0]["price_rial_per_kg"] == 33_300_441.0
        and by_price["sorted_by"] == "price desc"
    )
    by_name = shaped(sort_by="name", limit=100)
    keys = [match_key(r["product"]) for r in by_name["rows"]]
    assert by_name["sorted_by"] == "name asc" and keys == sorted(keys)


def test_product_filter_matches_name_symbol_and_producer_and_both_letter_forms():
    assert {r["product"] for r in shaped(product="میلگرد", limit=100)["rows"]} == {
        "میلگرد 14تا20-A3",
        "میلگرد 18 و 20 - A3",
    }
    assert [r["symbol"] for r in shaped(product="arco", limit=100)["rows"]] == [
        "ARCO-CASOALB-00"
    ]  # symbol, case-insensitive
    assert shaped(product="اروند")["totals"]["rows"] == 1  # producer
    assert shaped(product="سيمان")["totals"]["rows"] == 2  # an Arabic ي finds the Persian ی
    nothing = shaped(product="طلا")
    assert nothing["rows"] == [] and any("none passed" in n for n in nothing["notes"])


def test_an_empty_session_says_why():
    out = C.shape_trades(
        json.loads(load("commodity_ime_rollups")["thursday"]["d"]),
        request(),
        20261105,
        20261105,
        resolved=False,
    )
    assert out["rows"] == [] and out["totals"]["rows"] == 0 and out["by_hall"] == []
    assert any("Saturday to Wednesday" in n for n in out["notes"])


def test_a_row_in_another_unit_is_flagged():
    raw = trades_raw()
    raw[0]["Unit"] = "عدد"
    out = C.shape_trades(raw, request(), SESSION, SESSION, resolved=False)
    assert any("another volume unit (عدد)" in n for n in out["notes"])


def test_range_output_names_both_ends():
    out = C.shape_trades(trades_raw(), request(), 20261101, SESSION, resolved=False)
    assert out["date_from"] == "2026-11-01" and out["date_to"] == "2026-11-04" and "date" not in out
    assert out["date_to_jalali"] == "1405/08/13"


# ------------------------------------------------------------------------------------ roll-ups


def test_summary_converts_million_rial_and_keeps_tons():
    out = C.shape_summary(
        rollup("rings"),
        rollup("markets"),
        rollup("daily"),
        rollup("usd"),
        SESSION,
        SESSION,
        resolved=True,
    )
    industrial = out["physical_rings"][0]
    assert industrial["ring"] == "صنعتی" and industrial["value_rial"] == 109_469_008 * 1_000_000
    assert (
        industrial["traded_tons"] == 129_433.0
        and industrial["offered_tons"] == 295_659.0
        and industrial["traded_to_offered_pct"] == 43.8
    )
    assert out["physical_total"] == {
        "value_rial": 180_697_354 * 1_000_000,
        "traded_tons": 181_729.0,
        "offered_tons": 414_056.0,
    }  # IME's own headline: 414 thousand tons on offer
    physical = next(m for m in out["markets"] if m["market"] == "بازار فیزیکی")
    assert (
        physical["value_rial"] == out["physical_total"]["value_rial"]
    )  # the two roll-ups agree with each other
    assert next(m for m in out["markets"] if m["market"] == "بازار آتی")["value_rial"] is None
    assert (
        out["usd_rate"]["rial_per_usd"] == 1_878_192.0 and out["usd_rate"]["date"] == "2026-11-04"
    )
    assert out["units"]["ring_and_daily_volume"] == "tons (تن)" and out["latest_session"] is True


def test_summary_series_is_oldest_first_and_has_no_thursday():
    out = C.shape_summary(
        rollup("rings"),
        rollup("markets"),
        rollup("daily"),
        rollup("usd"),
        SESSION,
        SESSION,
        resolved=True,
    )
    dates = [d["date"] for d in out["daily"]]
    assert dates == sorted(dates) and dates[-1] == "2026-11-04" and "2026-11-05" not in dates
    assert out["daily"][-1] == {
        "date": "2026-11-04",
        "date_jalali": "1405/08/13",
        "value_rial": 180_697_354 * 1_000_000,
        "volume_tons": 181_729.0,
    }


def test_summary_without_data_says_why():
    out = C.shape_summary([], [], [], [], 20261105, 20261105, resolved=False)
    assert (
        out["physical_rings"] == []
        and out["usd_rate"] is None
        and out["physical_total"]["value_rial"] == 0
    )
    assert any("Saturday to Wednesday" in n for n in out["notes"])


# ------------------------------------------------------------------------------------ latest session and windows


def test_latest_session_is_the_newest_day_with_traded_value():
    daily = rollup("daily")
    assert C.latest_session(daily) == SESSION
    assert C.latest_session(daily, upto=20261103) == 20261103
    assert (
        C.latest_session(
            [
                {"TradeDate": "1405/08/14", "TradeValue": 0.0},
                {"TradeDate": "bad", "TradeValue": 5.0},
            ]
        )
        is None
    )
    assert [r["TradeDate"] for r in C.daily_upto(daily, 20261031)][-1] == "1405/08/09"


def test_windows_are_jalali_strings():
    assert C.recent_window(dt.date(2026, 11, 5)) == ("1405/08/01", "1405/08/14")
    assert C.chart_window(SESSION) == ("1405/08/04", "1405/08/13")


# ------------------------------------------------------------------------------------ arguments


def test_plan_defaults_and_group_words():
    req = request()
    assert (
        req.view,
        req.start,
        req.end,
        req.main_cat,
        req.sort_by,
        req.limit,
        req.traded_only,
    ) == ("trades", None, None, 0, "value", 20, True)
    assert (
        request(date="2026-11-04").start == SESSION
        and request(date="1405/08/13", to_date_="1405/08/15").end == 20261106
    )
    assert request(view="overview").view == "summary" and request(view="offers").view == "trades"
    for given, expected in (
        ("steel", 1),
        ("صنعتی", 1),
        ("3", 3),
        (4, 4),
        ("پتروشیمی", 3),
        ("فرآورده های نفتی", 5),
        ("oil products", 5),
        ("all", 0),
        (None, 0),
    ):
        assert C.parse_group(given) == expected, given


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"view": "chart"}, "view must be"),
        ({"to_date_": "2026-11-04"}, "needs date"),
        ({"date": "2026-11-04", "to_date_": "2026-11-01"}, "before date"),
        ({"date": "2026-10-01", "to_date_": "2026-11-04"}, "at most 7 days"),
        ({"sort_by": "colour"}, "sort_by must be"),
        ({"limit": 0}, "limit must be"),
        ({"limit": 500}, "limit must be"),
        ({"group": "نفتی"}, "ambiguous"),
        ({"group": "7"}, "Unknown or ambiguous"),
        ({"date": "yesterday"}, "Cannot parse date"),
    ],
)
def test_plan_rejects_bad_arguments_with_advice(kwargs, message):
    with pytest.raises(ValueError, match=message):
        request(**kwargs)


def test_summary_accepts_a_long_range_but_trades_does_not():
    assert request(view="summary", date="2026-01-01", to_date_="2026-11-04").view == "summary"
    with pytest.raises(ValueError, match="at most 366"):
        request(view="summary", date="2025-01-01", to_date_="2026-11-04")
