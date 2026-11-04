"""Iran Energy Exchange shaping: price and volume units, offers, one auction and the overview, against responses recorded on 2026-11-05."""

from __future__ import annotations

import datetime as dt

import pytest
from conftest import load

from iran_bourse_mcp import energy as E

SESSION = 20261104  # Wednesday 1405/08/13


def physical() -> list[dict]:
    return load("energy_iee_physical_trades")["results"]


def power() -> list[dict]:
    return load("energy_iee_power_trades")["results"]


def request(**kwargs):
    base = {
        "view": "trades",
        "market": None,
        "date": None,
        "to_date_": None,
        "product": None,
        "auction_id": None,
        "traded_only": True,
        "sort_by": None,
        "limit": None,
    }
    base.update(kwargs)
    return E.plan(**base)


def trades(raw_by_market=None, start=SESSION, end=SESSION, **kwargs) -> dict:
    return E.shape_trades(
        raw_by_market or {"physical": physical()}, request(**kwargs), start, end, resolved=False
    )


def row(out: dict, auction_id: int) -> dict:
    return next(r for r in out["rows"] if r["auction_id"] == auction_id)


# ------------------------------------------------------------------------------------ parsing


def test_number_parsing():
    assert E.number("3,818,790,300,000") == 3_818_790_300_000.0
    assert E.number("-160") == -160.0 and E.number("598.4") == 598.4 and E.number("۱٬۵۰۰") == 1500.0
    assert (
        E.number(7) == 7.0
        and E.number(None) is None
        and E.number("") is None
        and E.number("n/a") is None
        and E.number(True) is None
    )
    assert E.amount_with_unit("1,000 تن") == (1000.0, "تن")
    assert E.amount_with_unit("100 تن") == (100.0, "تن")
    assert E.amount_with_unit("0 پریمیوم ریالی") == (0.0, "پریمیوم ریالی")
    assert E.amount_with_unit(None) == (None, None)


def test_price_basis_covers_each_verified_combination():
    assert E.price_basis("تن", "ریال") == ("IRR", "rial per kilogram")
    assert E.price_basis(
        "تن", "دلار(مرکز مبادله- مطابق مکانیزم مصوب هیئت مدیره بورس انرژی ایران)"
    ) == ("USD", "US dollars per tonne")
    assert E.price_basis(
        "مترمکعب", "دلار(مرکز مبادله- مطابق مکانیزم مصوب هیئت مدیره بورس انرژی ایران)"
    ) == ("USD", "US dollars per cubic meter")
    assert E.price_basis("لیتر", "ریال") == ("IRR", "rial per liter")
    assert E.price_basis(E.POWER_UNIT, "ریال") == ("IRR", "rial per kWh")
    assert E.price_basis("تن", "پریمیوم دلاری(مرکز مبادله)")[0] == "USD premium"
    assert E.price_basis(E.POWER_UNIT, "پریمیوم ریالی")[0] == "IRR premium"
    assert E.price_basis("عدد", "ریال") == ("IRR", None) and E.price_basis(None, None) == (
        None,
        None,
    )  # an unverified unit is not guessed


# ------------------------------------------------------------------------------------ rows


def test_rial_per_kilogram_auction():
    r = row(trades(limit=100), 96520)  # liquid nitrogen: 60 t at 180,000 rial/kg
    assert (r["product"], r["ring"], r["contract"], r["trade_type"]) == (
        "نیتروژن مایع",
        "داخلی",
        "نقدی",
        "طول بازار",
    )
    assert (
        r["volume_unit"] == "تن" and r["volume_unit_en"] == "tonne" and r["traded_volume"] == 60.0
    )
    assert r["offered_volume"] == 100.0 and r["demand_volume"] == 60.0 and r["trades"] == 1
    assert (
        r["avg_price"] == r["base_price"] == 180_000.0
        and r["price_basis"] == "rial per kilogram"
        and r["price_currency"] == "IRR"
    )
    assert r["value_rial"] == 10_800_000_000 == round(60 * 1000 * 180_000)
    assert (
        r["trade_date"] == "2026-11-04"
        and r["auction_time"] == "12:40"
        and r["auction_id"] == 96520
    )
    assert r["symbol"] == "DLNPFCABEX0050823" and r["kwh"] is None


def test_every_rial_per_kilogram_row_reconciles_with_the_exchanges_own_value():
    kilo = [r for r in trades(limit=100)["rows"] if r["price_basis"] == "rial per kilogram"]
    assert len(kilo) == 10
    for r in kilo:  # the average price is rounded to the rial, and an auction can trade at two neighbouring prices (96516: 1,659,833 and 1,659,834)
        assert r["traded_volume"] * 1000 * r["avg_price"] == pytest.approx(
            r["value_rial"], rel=1e-6
        ), r["auction_id"]


def test_dollar_auction_value_uses_the_dollar_rate_of_the_day():
    r = row(
        trades(limit=100), 96511
    )  # liquefied gas for export: 2,000 t at 598.4 US dollars a tonne
    assert (
        r["price_currency"] == "USD"
        and r["price_basis"] == "US dollars per tonne"
        and r["avg_price"] == 598.4
    )
    assert r["value_rial"] == 2_243_334_579_200
    assert r["value_rial"] / (2000 * 598.4) == pytest.approx(
        1_874_444, abs=0.5
    )  # the exchange's dollar rate of 2026-11-03
    assert r["ring"] == "بین الملل" and r["destination"]


def test_cubic_meter_forward_settled_a_day_after_its_auction():
    r = row(
        trades(limit=100), 96488
    )  # auctioned on 1405/08/12, traded on 1405/08/13: the row's date is the trade date
    assert (
        r["volume_unit"] == "مترمکعب"
        and r["price_basis"] == "US dollars per cubic meter"
        and r["contract"] == "سلف"
    )
    assert (
        r["traded_volume"] == 510.0
        and r["value_rial"] == 987_656_727_486
        and r["avg_price"] == 1033.15
    )
    assert r["trade_date"] == "2026-11-04"
    assert (
        trades(start=20261103, end=20261103)["rows"] == []
    )  # filtered on the trade date, not the auction date


def test_premium_auction_is_not_a_price():
    r = row(
        trades(traded_only=False, limit=100), 96523
    )  # liquefied gas premium auction that found no buyer
    assert (
        r["price_currency"] == "USD premium"
        and "premium" in r["price_basis"]
        and r["traded_volume"] == 0.0
        and r["value_rial"] == 0
    )
    assert r["base_price"] == -160.0 and r["contract"] == "پریمیوم"


def test_electricity_contract_is_kilowatts_of_capacity_with_a_kwh_figure():
    out = E.shape_trades(
        {"power": power()}, request(market="power"), 20261101, 20261101, resolved=False
    )
    r = row(out, 96418)
    assert (
        r["volume_unit"] == E.POWER_UNIT
        and r["volume_unit_en"] == "kW of capacity over the delivery period"
    )
    assert r["traded_volume"] == 9000.0 and r["kwh"] == 1_512_000.0  # 9,000 kW for a 168-hour week
    assert (
        r["avg_price"] == 4500.0
        and r["price_basis"] == "rial per kWh"
        and r["board"] == "تابلو برق"
    )
    assert r["value_rial"] == 6_804_000_000 == round(r["kwh"] * r["avg_price"])


# ------------------------------------------------------------------------------------ totals and filters


def test_totals_never_add_different_units():
    out = trades(limit=100)
    assert out["totals"]["auctions"] == out["totals"]["traded_auctions"] == 12
    assert out["totals"]["volume_by_unit"] == {
        "تن": 13143.0,
        "مترمکعب": 510.0,
    }  # tonnes and cubic meters stay apart
    assert out["totals"]["value_rial"] == sum(r["value_rial"] for r in out["rows"])
    assert out["by_market"] == {
        "physical": {
            "auctions": 12,
            "traded_auctions": 12,
            "value_rial": out["totals"]["value_rial"],
        }
    }
    assert (
        out["top_products"][0]["product"].startswith("برش کربنی")
        and out["top_products"][0]["volume_unit"] == "تن"
    )
    assert (
        out["top_products"][0]["traded_volume"] == 2000.0
        and out["top_products"][0]["value_rial"] == 5_430_004_000_000
    )


def test_the_exchanges_day_total_is_reproduced_exactly():
    everything = trades(traded_only=False)
    assert everything["totals"]["auctions"] == 18 and everything["totals"]["traded_auctions"] == 12
    assert (
        everything["totals"]["value_rial"] == 22_620_322_449_686
    )  # the sum of the 18 totalValueRials, unchanged
    assert (
        sum(r["value_rial"] for r in trades(traded_only=False, limit=100)["rows"])
        == 22_620_322_449_686
    )


def test_untraded_auctions_hidden_unless_asked_and_product_filter_works():
    assert all(r["traded_volume"] > 0 for r in trades(limit=100)["rows"])
    assert [r["auction_id"] for r in trades(product="نیتروژن")["rows"]] == [96520]
    assert (
        trades(product="شازند", limit=100)["totals"]["auctions"] == 5
    )  # CSO, hexane, PGH, LCO and solvent 402 of Shazand
    assert trades(product="هیچ")["rows"] == []


def test_rows_sort_by_value_volume_name_or_time():
    assert [r["auction_id"] for r in trades(limit=2)["rows"]] == [
        96517,
        96515,
    ]  # 5.43 and 4.54 trillion rial
    by_volume = trades(sort_by="volume", limit=1)["rows"][0]
    assert by_volume["auction_id"] == 96519 and by_volume["traded_volume"] == 3900.0
    by_time = trades(sort_by="time", limit=100)["rows"]
    assert by_time[0]["auction_time"] == "14:20" and [r["auction_time"] for r in by_time] == sorted(
        (r["auction_time"] for r in by_time), reverse=True
    )
    names = [r["product"] for r in trades(sort_by="name", limit=100)["rows"]]
    assert names == sorted(names, key=lambda n: E.match_key(n))


def test_a_market_without_auctions_that_day_is_named():
    out = trades(raw_by_market={"physical": physical(), "power": power()}, limit=100)
    assert out["markets"] == ["physical", "power"] and "power" not in out["by_market"]
    assert any("No power auctions" in n for n in out["notes"])
    empty = trades(raw_by_market={"physical": [], "power": []}, start=20261105, end=20261105)
    assert empty["rows"] == [] and any("Saturday to Wednesday" in n for n in empty["notes"])
    assert any(
        "only the first page" in n
        for n in E.shape_trades(
            {"physical": physical()},
            request(),
            SESSION,
            SESSION,
            resolved=False,
            truncated=["physical"],
        )["notes"]
    )


def test_latest_day_prefers_a_day_that_traded():
    assert E.latest_day(physical()) == SESSION and E.latest_day(power()) == 20261101
    announced_only = [{"tradeDateShamsi": "1405/08/14", "totalTradedVolume": "0"}, *physical()]
    assert (
        E.latest_day(announced_only) == SESSION
    )  # a session that has only announced its auctions must not hide the last finished one
    assert E.latest_day([{"tradeDateShamsi": "1405/08/14", "totalTradedVolume": "0"}]) == 20261105
    assert E.latest_day([]) is None


def test_recent_window_is_jalali():
    assert E.recent_window(dt.date(2026, 11, 5)) == ("1405/08/08", "1405/08/14")


# ------------------------------------------------------------------------------------ offers


def offers_raw() -> dict:
    return {
        "physical": load("energy_iee_physical_offers")["results"],
        "power": load("energy_iee_power_offers")["results"],
    }


def test_physical_offers_carry_numbers_and_the_exchanges_wording():
    out = E.shape_offers(
        {"physical": offers_raw()["physical"]}, request(view="offers", market="physical")
    )
    assert out["announced"] == {"physical": 4} and out["returned"] == 4
    first = out["rows"][0]
    assert (
        first["auction_id"] == 96551
        and first["product"] == "گاز مایع"
        and first["ring"] == "بین الملل"
    )
    assert (
        first["offered_volume"] == 1000.0
        and first["volume_unit"] == "تن"
        and first["volume_unit_en"] == "tonne"
    )
    assert (
        first["base_price"] == -160.0
        and "پریمیوم" in first["base_price_text"]
        and first["reference_price"] == 750.0
    )
    assert (first["date"], first["date_jalali"], first["time"], first["status"]) == (
        "2026-11-08",
        "1405/08/17",
        "14:00",
        "آماده عرضه",
    )
    assert [r["time"] for r in out["rows"]] == ["14:00", "14:20", "14:40", "15:00"]  # soonest first


def test_held_electricity_announcements_are_dropped_and_the_rest_keep_their_terms():
    out = E.shape_offers(
        {"power": offers_raw()["power"]}, request(view="offers", market="power"), more=["power"]
    )
    assert out["announced"] == {"power": 3} and [r["auction_id"] for r in out["rows"]] == [
        96537,
        96538,
        96539,
    ]  # soonest first
    green = out["rows"][-1]
    assert (green["product"], green["market"], green["trade_type"], green["offered_volume"]) == (
        "برق سبز",
        "power",
        "کشف پریمیوم",
        660.0,
    )
    assert (
        green["volume_unit"] == E.POWER_UNIT
        and green["symbol"] == "DGELFPRB00M050901"
        and green["delivery_terms"] == "1405/09/01"
    )
    assert green["date"] == "2026-11-07" and green["time"] == "11:50"
    assert any("may have announced more" in n for n in out["notes"])
    assert E.is_held(offers_raw()["power"][-1]) and not E.is_held(offers_raw()["power"][0])


def test_offers_filter_and_empty_notes():
    green = E.shape_offers(offers_raw(), request(view="offers", product="برق سبز"))
    assert [r["market"] for r in green["rows"]] == ["power"] * 3 and green["announced"] == {
        "physical": 4,
        "power": 3,
    }
    nothing = E.shape_offers(
        {"physical": offers_raw()["physical"]}, request(view="offers", product="نیتروژن")
    )
    assert nothing["rows"] == [] and any("none matches" in n for n in nothing["notes"])
    empty = E.shape_offers({"power": []}, request(view="offers", market="power"))
    assert empty["rows"] == [] and any("no announced auctions" in n for n in empty["notes"])


# ------------------------------------------------------------------------------------ one auction


def test_auction_detail_states_units_orders_and_trades():
    fx = load("energy_iee_auction")
    out = E.shape_auction(fx["detail"]["results"][0], fx["trades"]["results"])
    assert (out["symbol"], out["product"], out["status"], out["date"], out["time"]) == (
        "DSOSZCABEX0050818",
        "سی اس او",
        "توقف مازاد عرضه",
        "2026-11-04",
        "12:20",
    )
    assert (
        out["units"]["volume"] == "تن"
        and out["units"]["price_basis"] == "rial per kilogram"
        and out["units"]["price_per"] == "کیلوگرم"
    )
    assert (
        out["units"]["volume_to_price_unit"] == 1000.0
        and out["units"]["note"] == "1 تن = 1000 کیلوگرم"
    )
    assert (out["offered_volume"], out["minimum_purchase"], out["lot_size"], out["base_price"]) == (
        7000.0,
        200.0,
        100.0,
        979_177.0,
    )
    assert out["buy_orders"] == [{"price": 979_177.0, "volume": 3900.0, "orders": 4}]
    assert out["sell_orders"] == [{"price": 979_177.0, "volume": 7000.0, "orders": 1}]
    assert out["demand_volume"] == 3900.0 and out["supply_volume"] == 7000.0
    assert out["totals"] == {"trades": 4, "volume": 3900.0, "value_rial": 3_818_790_300_000}
    assert [t["volume"] for t in out["trades"]] == [500.0, 200.0, 200.0, 3000.0] and out["trades"][
        0
    ]["price_per"] == "ریال/کیلوگرم"
    assert out["totals"]["value_rial"] == round(out["totals"]["volume"] * 1000 * 979_177)


def test_auction_without_trades_still_shapes():
    detail = {
        **load("energy_iee_auction")["detail"]["results"][0],
        "buyOrders": None,
        "saleOrders": [],
    }
    out = E.shape_auction(detail, [])
    assert (
        out["buy_orders"] == []
        and out["trades"] == []
        and out["totals"] == {"trades": 0, "volume": 0, "value_rial": 0}
    )


# ------------------------------------------------------------------------------------ overview


def test_overview_reports_state_and_converts_million_rial():
    fx = load("energy_iee_overview")
    out = E.shape_overview(
        fx["today"]["results"], fx["physical"]["results"], fx["power"]["results"]
    )
    assert out["physical_market"]["state"] == {
        "all_rings": "بسته",
        "internal_ring": "بسته",
        "international_ring": "بسته",
    }
    assert out["power_market"] == {"state": "بسته", "trades_today": 0}
    assert [m["market"] for m in out["traded_today"]] == [
        "بازار فیزیکی",
        "بازار برق",
        "بازار مشتقه",
        "سایر اوراق",
    ]
    busy = E.shape_overview(
        [
            {
                "marketSummaryType": 0,
                "marketName": "بازار فیزیکی",
                "tradedValue": 1.5,
                "tradedNo": 3,
                "percentage": 100,
            }
        ],
        [],
        [],
    )
    assert (
        busy["traded_today"][0]["traded_value_rial"] == 1_500_000
        and busy["traded_today"][0]["trades"] == 3
    )
    assert busy["physical_market"]["state"] == {
        "all_rings": None,
        "internal_ring": None,
        "international_ring": None,
    }


# ------------------------------------------------------------------------------------ arguments


def test_plan_defaults_aliases_and_markets():
    req = request()
    assert (req.view, req.markets, req.start, req.end, req.sort_by, req.limit, req.traded_only) == (
        "trades",
        ("physical", "power"),
        None,
        None,
        "value",
        20,
        True,
    )
    assert (
        request(view="results").view == "trades"
        and request(view="announcements").view == "offers"
        and request(view="status").view == "overview"
    )
    assert (
        request(market="electricity").markets == ("power",)
        and request(market="برق").markets == ("power",)
        and request(market="Oil").markets == ("physical",)
    )
    assert request(market="all").markets == ("physical", "power")
    assert request(view="auction", auction_id=96519).auction_id == 96519
    assert request(date="1405/08/13", to_date_="1405/08/15").end == 20261106


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"view": "chart"}, "view must be"),
        ({"market": "coal"}, "market must be"),
        ({"to_date_": "2026-11-04"}, "needs date"),
        ({"date": "2026-11-04", "to_date_": "2026-11-01"}, "before date"),
        ({"date": "2026-10-01", "to_date_": "2026-11-04"}, "at most 10 days"),
        ({"view": "auction"}, "needs auction_id"),
        ({"view": "auction", "auction_id": 0}, "needs auction_id"),
        ({"sort_by": "colour"}, "sort_by must be"),
        ({"limit": 0}, "limit must be"),
        ({"limit": 101}, "limit must be"),
        ({"date": "soon"}, "Cannot parse date"),
    ],
)
def test_plan_rejects_bad_arguments_with_advice(kwargs, message):
    with pytest.raises(ValueError, match=message):
        request(**kwargs)
