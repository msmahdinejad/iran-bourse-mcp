"""Contract scenarios: the Iran Mercantile Exchange (commodity_market) and the Iran Energy Exchange (energy_market).

Both exchanges are read from their own sites, not from TSETMC. The IME's services are POSTed with a JSON body, which
the recordings keep and the replay matches. Checks compare the output with the recorded payload, as elsewhere; exact
numbers are pinned only for the session of Wednesday 2026-11-04 (1405/08/13), which is history and cannot change.
Offers and the overview are "now" data and are checked against whatever was recorded.
"""

from __future__ import annotations

import json
from math import isclose

import httpx
from contract_helpers import assert_keys, clean, descending, is_jdate, iso, one
from contract_replay import scenario

from iran_bourse_mcp.dates import parse_date

DAY = "2026-11-04"  # the pinned session, Wednesday 1405/08/13
JDAY = "1405/08/13"

TRADE_ROW = (
    "symbol product producer supplier hall contract matching settlement packaging broker date date_jalali "
    "delivery_date delivery_date_jalali delivery_place unit volume_tons price_rial_per_kg price_low_rial_per_kg "
    "price_high_rial_per_kg base_price_rial_per_kg offered_tons demand_tons value_rial offer_id category_code"
)
ENERGY_ROW = (
    "auction_id symbol market board product description ring destination supplier producer broker trade_date "
    "trade_date_jalali auction_time trade_type contract clearing volume_unit volume_unit_en traded_volume "
    "offered_volume demand_volume trades price_currency price_basis price_unit base_price avg_price low_price "
    "high_price value_rial kwh"
)
OFFER_ROW = (
    "auction_id symbol market product description ring supplier producer broker date date_jalali time trade_type "
    "status offered_volume volume_unit volume_unit_en base_price base_price_text reference_price minimum_purchase "
    "maximum_purchase delivery_terms delivery_place"
)
POWER_UNIT = "کیلووات در هر ساعت از دوره مصرف در دوره تحویل"
PRICE_BASIS = {  # (volume unit, price unit) -> what the price is, for the combinations seen in the exchange's data
    ("تن", "ریال"): "rial per kilogram",
    ("لیتر", "ریال"): "rial per liter",
    (POWER_UNIT, "ریال"): "rial per kWh",
}


# ----------------------------------------------------------------------------- helpers
def ime_rows(run, fragment: str) -> list[dict]:
    """An ASMX answer is ``{"d": "<JSON array as a string>"}``."""
    return json.loads(run.rec.body(fragment)["d"])


def num(text) -> float:
    """The Energy Exchange sends numbers as strings with thousands separators."""
    return float(str(text).replace(",", ""))


def jalali_iso(jalali: str) -> str:
    return iso(parse_date(jalali))


def query(run, fragment: str) -> dict:
    return dict(httpx.URL(run.rec.get(fragment).url).params)


def rolled_up(rows: list[dict], key: str) -> dict:
    """Rows, traded rows, tons and rial per ``key`` (a row field name of the shaped rows), in the order the rows come."""
    out: dict = {}
    for row in rows:
        entry = out.setdefault(
            row[key], {"rows": 0, "traded_rows": 0, "volume_tons": 0.0, "value_rial": 0}
        )
        entry["rows"] += 1
        entry["traded_rows"] += 1 if row["Quantity"] > 0 else 0
        entry["volume_tons"] += row["Quantity"]
        entry["value_rial"] += round(row["TotalPrice"] * 1000)
    return {name: {**e, "volume_tons": round(e["volume_tons"], 3)} for name, e in out.items()}


# ----------------------------------------------------------------------------- IME: physical market
@scenario("commodity_trades", "commodity_market", view="trades", date=DAY, limit=10)
def _commodity_trades(run):
    out = run.out
    sent = run.rec.get("GetAmareMoamelatList").request_body
    assert sent == {
        "Language": 8,
        "fari": False,
        "GregorianFromDate": JDAY,  # Jalali on the wire, whatever the parameter is called
        "GregorianToDate": JDAY,
        "MainCat": 0,
        "Cat": 0,
        "SubCat": 0,
        "Producer": 0,
    }
    raw = ime_rows(run, "GetAmareMoamelatList")
    traded = [r for r in raw if r["Quantity"] > 0]
    assert len(raw) >= 20 and len(traded) >= 10
    assert {r["Unit"] for r in raw} == {"تن"} and {r["Currency"] for r in raw} == {
        "ریال"
    }  # the units the labels promise

    assert_keys(
        out,
        "market view date date_jalali latest_session units filters totals by_hall by_contract top_products sorted_by returned rows notes",
    )
    assert (out["view"], out["date"], out["date_jalali"], out["latest_session"]) == (
        "trades",
        DAY,
        JDAY,
        False,
    )
    assert out["units"] == {"volume": "tons (تن)", "price": "rial per kilogram", "value": "rial"}
    assert out["filters"] == {"group": None, "product": None, "traded_only": True}

    # totals, per hall and per contract type are over the traded rows, in rial (the exchange's thousand rial x 1,000)
    shaped = [
        {**r, "Talar": clean(r["Talar"]), "ContractType": clean(r["ContractType"])} for r in traded
    ]
    assert_keys(out["totals"], "rows traded_rows volume_tons value_rial offered_tons demand_tons")
    assert out["totals"] == {
        "rows": len(traded),
        "traded_rows": len(traded),
        "volume_tons": round(sum(r["Quantity"] for r in traded), 3),
        "value_rial": sum(round(r["TotalPrice"] * 1000) for r in traded),
        "offered_tons": round(sum(r["arze"] or 0 for r in traded), 3),
        "demand_tons": round(sum(r["taghaza"] or 0 for r in traded), 3),
    }
    for key, field in (("by_hall", "Talar"), ("by_contract", "ContractType")):
        expected = rolled_up(shaped, field)
        name = "hall" if key == "by_hall" else "contract"
        assert [e[name] for e in out[key]] == sorted(
            expected, key=lambda n: -expected[n]["value_rial"]
        )
        for entry in out[key]:
            assert_keys(entry, f"{name} rows traded_rows volume_tons value_rial")
            assert {k: v for k, v in entry.items() if k != name} == expected[entry[name]]
        assert sum(e["value_rial"] for e in out[key]) == out["totals"]["value_rial"]
    assert {h["hall"] for h in out["by_hall"]} == {clean(r["Talar"]) for r in traded}
    products = rolled_up([{**r, "GoodsName": clean(r["GoodsName"])} for r in traded], "GoodsName")
    assert [p["product"] for p in out["top_products"]] == sorted(
        products, key=lambda n: -products[n]["value_rial"]
    )[:10]
    for entry in out["top_products"]:
        assert_keys(entry, "product rows traded_rows volume_tons value_rial avg_price_rial_per_kg")
        mine = products[entry["product"]]
        assert (entry["rows"], entry["volume_tons"], entry["value_rial"]) == (
            mine["rows"],
            mine["volume_tons"],
            mine["value_rial"],
        )
        assert entry["avg_price_rial_per_kg"] == round(
            mine["value_rial"] / (mine["volume_tons"] * 1000), 1
        )  # derived

    # the ranked rows
    assert out["sorted_by"] == "value desc" and out["returned"] == len(out["rows"]) == 10
    assert descending(r["value_rial"] for r in out["rows"])
    by_offer = {str(r["arzehPk"]): r for r in raw}
    assert len(by_offer) == len(raw)  # the offer id identifies a row
    for row in out["rows"]:
        assert_keys(row, TRADE_ROW)
        r = by_offer[row["offer_id"]]
        assert (row["symbol"], row["product"], row["producer"], row["supplier"]) == (
            clean(r["Symbol"]),
            clean(r["GoodsName"]),
            clean(r["ProducerName"]),
            clean(r["ArzehKonandeh"]),
        )
        assert (
            row["hall"],
            row["contract"],
            row["settlement"],
            row["packaging"],
            row["broker"],
        ) == (
            clean(r["Talar"]),
            clean(r["ContractType"]),
            clean(r["Tasvieh"]),
            clean(r["PacketName"]),
            clean(r["cBrokerSpcName"]),
        )
        assert row["matching"] is ("مچینگ" in clean(r["ContractType"]))
        assert (row["date"], row["date_jalali"]) == (DAY, JDAY)
        assert (
            is_jdate(row["delivery_date_jalali"])
            and row["delivery_date_jalali"] == r["DeliveryDate"]
        )
        assert row["delivery_date"] == jalali_iso(r["DeliveryDate"]) and row[
            "delivery_place"
        ] == clean(r["Warehouse"])
        assert (row["unit"], row["volume_tons"]) == ("تن", r["Quantity"])
        assert (
            row["price_rial_per_kg"],
            row["price_low_rial_per_kg"],
            row["price_high_rial_per_kg"],
        ) == (r["Price"], r["MinPrice"], r["MaxPrice"])
        assert row["base_price_rial_per_kg"] == r["ArzeBasePrice"]
        assert (row["offered_tons"], row["demand_tons"]) == (r["arze"], r["taghaza"])
        assert row["value_rial"] == round(r["TotalPrice"] * 1000)  # thousand rial -> rial
        assert isclose(
            row["price_rial_per_kg"] * row["volume_tons"] * 1000, row["value_rial"], rel_tol=1e-4
        )  # rial/kg x tons x 1,000 kg
        assert row["category_code"] == clean(r["Category"])
    assert any("rial per kilogram" in n for n in out["notes"]) and any(
        "sub-market" in n for n in out["notes"]
    )

    # the session of 2026-11-04 is history: its biggest deal, to the rial
    copper = one(out["rows"], lambda r: r["symbol"] == "SRBK-CR08AB-00", "copper wire rod deal")
    assert out["rows"][0] is copper
    assert (copper["product"], copper["contract"], copper["matching"], copper["broker"]) == (
        "مس مفتول",
        "نقدی (مچینگ)",
        True,
        "فارابی",
    )
    assert (copper["volume_tons"], copper["price_rial_per_kg"], copper["value_rial"]) == (
        230.0,
        33_300_441.0,
        7_659_101_430_000,
    )
    assert (copper["delivery_date"], copper["offered_tons"], copper["demand_tons"]) == (
        "2026-11-10",
        0.0,
        230.0,
    )


def check_summary(run, *, first: str, last: str, window_first: str) -> dict:
    """The checks every summary shares: request bodies, conversions to rial, the rings and markets, the series and the dollar rate."""
    out = run.out
    window = {
        "GregorianFromDate": window_first,
        "GregorianToDate": last,
    }  # the sessions the series covers
    for fragment, sent in (
        ("GetHomeFizikiWithDateGrid", {"GregorianFromDate": first, "GregorianToDate": last}),
        ("GetHomeNamaWithDateGrid", {"GregorianFromDate": first, "GregorianToDate": last}),
        ("GetHajmArzeshMoamelatDateGrid", window),
        ("GetHomeExchangeRateData", {}),
    ):
        assert run.rec.get(fragment).request_body == {"Language": 8, **sent}
    rings, markets = (
        ime_rows(run, "GetHomeFizikiWithDateGrid"),
        ime_rows(run, "GetHomeNamaWithDateGrid"),
    )
    daily, usd = (
        ime_rows(run, "GetHajmArzeshMoamelatDateGrid"),
        ime_rows(run, "GetHomeExchangeRateData"),
    )

    dates = (
        "date date_jalali" if first == last else "date_from date_to date_from_jalali date_to_jalali"
    )
    assert_keys(
        out,
        f"market view {dates} latest_session units physical_rings physical_total markets daily usd_rate notes",
    )
    assert out["view"] == "summary" and out["latest_session"] is False
    assert out["units"] == {
        "value": "rial",
        "ring_and_daily_volume": "tons (تن)",
        "market_volume": "the market's own unit, as published",
    }

    # rings: the exchange's million rial -> rial, volumes are tons
    assert [r["ring_id"] for r in out["physical_rings"]] == [r["ID"] for r in rings]
    for row, r in zip(out["physical_rings"], rings, strict=True):
        assert_keys(row, "ring_id ring value_rial traded_tons offered_tons traded_to_offered_pct")
        assert (row["ring"], row["value_rial"]) == (
            clean(r["xRingName"]),
            round(r["Value"] * 1_000_000),
        )
        assert (row["traded_tons"], row["offered_tons"]) == (r["Volume"], r["OfferVolume"])
        assert row["traded_to_offered_pct"] == round(r["Volume"] / r["OfferVolume"] * 100, 1)
    total = out["physical_total"]
    assert_keys(total, "value_rial traded_tons offered_tons")
    assert total["value_rial"] == sum(row["value_rial"] for row in out["physical_rings"])
    assert (total["traded_tons"], total["offered_tons"]) == (
        sum(r["Volume"] for r in rings),
        sum(r["OfferVolume"] for r in rings),
    )

    # markets: the physical market's value is the rings' sum
    assert [m["market_id"] for m in out["markets"]] == [int(m["Id"]) for m in markets]
    for row, m in zip(out["markets"], markets, strict=True):
        assert_keys(row, "market_id market value_rial volume")
        assert row["market"] == clean(m["name"]) and row["volume"] == m["TradeVolume"]
        assert row["value_rial"] == (
            None if m["TradeValue"] is None else round(m["TradeValue"] * 1_000_000)
        )
    physical = one(out["markets"], lambda m: m["market_id"] == 1, "physical market")
    assert (
        physical["value_rial"] == total["value_rial"] and physical["volume"] == total["traded_tons"]
    )

    # one row per session of the window, oldest first, none for the closed Thursday and Friday
    assert [d["date_jalali"] for d in out["daily"]] == sorted(r["TradeDate"] for r in daily)
    assert all(window_first <= d["date_jalali"] <= last for d in out["daily"])
    for row in out["daily"]:
        assert_keys(row, "date date_jalali value_rial volume_tons")
        r = one(daily, lambda r, row=row: r["TradeDate"] == row["date_jalali"], "session")
        assert (row["date"], row["value_rial"], row["volume_tons"]) == (
            jalali_iso(r["TradeDate"]),
            round(r["TradeValue"] * 1_000_000),
            r["TradeVolume"],
        )

    # IME's dollar rate: the newest of the days it returns (it is "now" data)
    newest = max(usd, key=lambda u: u["Tarikh"])
    assert_keys(out["usd_rate"], "date date_jalali rial_per_usd note")
    assert (
        out["usd_rate"]["date_jalali"] == newest["Tarikh"]
        and out["usd_rate"]["rial_per_usd"] == newest["Nerkh"]
    )
    assert out["usd_rate"]["date"] == jalali_iso(newest["Tarikh"]) and newest["Sharh"] == "دلار"
    assert any("the exchange publishes million rial" in n for n in out["notes"])
    return {"rings": rings, "daily": daily}


@scenario("commodity_summary", "commodity_market", view="summary", date=DAY)
def _commodity_summary(run):
    out = run.out
    check_summary(
        run, first=JDAY, last=JDAY, window_first="1405/08/04"
    )  # a single day shows the ten sessions up to it
    assert (out["date"], out["date_jalali"]) == (DAY, JDAY)
    assert len(out["daily"]) >= 5 and "2026-10-29" not in {
        d["date"] for d in out["daily"]
    }  # Thursday 1405/08/07
    # the session is history: IME's own numbers, and the headline of that morning («۴۱۴ هزار تن محصول روی میز فروش می‌رود»)
    assert out["physical_total"] == {
        "value_rial": 180_697_354 * 1_000_000,
        "traded_tons": 181_729.0,
        "offered_tons": 414_056.0,
    }
    assert out["daily"][-1] == {
        "date": DAY,
        "date_jalali": JDAY,
        "value_rial": 180_697_354 * 1_000_000,
        "volume_tons": 181_729.0,
    }


@scenario(
    "commodity_summary_range", "commodity_market", view="summary", date="1405/08/12", to_date=DAY
)
def _commodity_summary_range(run):
    out = run.out  # two sessions, the first given in Jalali and the last in Gregorian: both ends reach the wire as Jalali
    check_summary(run, first="1405/08/12", last=JDAY, window_first="1405/08/12")
    assert (out["date_from"], out["date_to"], out["date_from_jalali"], out["date_to_jalali"]) == (
        "2026-11-03",
        DAY,
        "1405/08/12",
        JDAY,
    )
    assert [d["date_jalali"] for d in out["daily"]] == [
        "1405/08/12",
        JDAY,
    ]  # the series is the range itself, not ten sessions
    wednesday, tuesday = out["daily"][-1], out["daily"][0]
    assert (
        wednesday["value_rial"] == 180_697_354 * 1_000_000
        and tuesday["value_rial"] == 240_972_231 * 1_000_000
    )
    # the roll-up of the range is the two sessions together
    assert out["physical_total"]["value_rial"] == wednesday["value_rial"] + tuesday["value_rial"]
    assert (
        out["physical_total"]["traded_tons"]
        == wednesday["volume_tons"] + tuesday["volume_tons"]
        == 181_729.0 + 384_753.0
    )


# ----------------------------------------------------------------------------- Iran Energy Exchange
@scenario("energy_trades", "energy_market", view="trades", date=DAY, limit=10)
def _energy_trades(run):
    out = run.out
    expected_query = {
        "Lang": "fa",
        "PageNumber": "1",
        "PageSize": "1000",
        "FromDate": JDAY,
        "ToDate": JDAY,
    }
    assert (
        query(run, "GetTradesStatistics")
        == expected_query
        == query(run, "GetPowerTradesStatistics")
    )
    physical_env, power_env = (
        run.rec.body("GetTradesStatistics"),
        run.rec.body("GetPowerTradesStatistics"),
    )
    assert (
        physical_env["isSuccess"] is True and physical_env["pagedMetaData"][0]["hasNext"] is False
    )  # the day fits one page
    raw = [r for r in physical_env["results"] if r["tradeDateShamsi"] == JDAY]
    traded = [r for r in raw if num(r["totalTradedVolume"]) > 0]
    assert len(raw) == len(physical_env["results"]) >= 10 and len(traded) >= 5

    assert_keys(
        out,
        "exchange view date date_jalali latest_session markets filters totals by_market top_products sorted_by returned rows notes",
    )
    assert (out["view"], out["date"], out["date_jalali"], out["latest_session"]) == (
        "trades",
        DAY,
        JDAY,
        False,
    )
    assert out["markets"] == ["physical", "power"] and out["filters"] == {
        "product": None,
        "traded_only": True,
    }
    assert out["sorted_by"] == "value" and out["returned"] == len(out["rows"]) == 10

    # totals are the exchange's rial figures; volumes of different units are kept apart
    assert_keys(out["totals"], "auctions traded_auctions value_rial volume_by_unit")
    volume_by_unit: dict[str, float] = {}
    for r in traded:
        unit = clean(r["volumeUnitTitle"])
        volume_by_unit[unit] = volume_by_unit.get(unit, 0.0) + num(r["totalTradedVolume"])
    assert out["totals"] == {
        "auctions": len(traded),
        "traded_auctions": len(traded),
        "value_rial": sum(int(num(r["totalValueRials"])) for r in traded),
        "volume_by_unit": {u: round(v, 3) for u, v in volume_by_unit.items()},
    }
    assert len(out["totals"]["volume_by_unit"]) >= 2  # tonnes and cubic meters stay apart
    # the physical market is the only one with auctions that day; the tool says so
    assert not power_env["results"] and set(out["by_market"]) == {"physical"}
    assert_keys(out["by_market"]["physical"], "auctions traded_auctions value_rial")
    assert out["by_market"]["physical"]["value_rial"] == out["totals"]["value_rial"]
    assert any("No power auctions" in n for n in out["notes"])
    for entry in out["top_products"]:
        assert_keys(entry, "product volume_unit auctions traded_volume value_rial")
    assert descending(p["value_rial"] for p in out["top_products"])

    # the ranked rows against the exchange's strings
    assert descending(r["value_rial"] for r in out["rows"])
    by_id = {r["auctionIdn"]: r for r in raw}
    for row in out["rows"]:
        assert_keys(row, ENERGY_ROW)
        r = by_id[row["auction_id"]]
        assert (row["symbol"], row["product"], row["supplier"], row["broker"], row["ring"]) == (
            clean(r["energySymbol"]),
            clean(r["instrumentDisplayName"]),
            clean(r["supplierName"]),
            clean(r["brokerName"]),
            clean(r["targetMarketName"]),
        )
        assert (row["market"], row["trade_date"], row["trade_date_jalali"]) == (
            "physical",
            DAY,
            JDAY,
        )
        hour, minute = r["auctionDateShamsi"].split(" - ")[1].split(":")  # «1405/08/13 - 15:0»
        assert row["auction_time"] == f"{int(hour):02d}:{int(minute):02d}"
        assert (row["volume_unit"], row["traded_volume"]) == (
            clean(r["volumeUnitTitle"]),
            num(r["totalTradedVolume"]),
        )
        assert (row["offered_volume"], row["demand_volume"], row["trades"]) == (
            num(r["auctionVolume"]),
            num(r["orderBuyTradedVolume"]),
            int(num(r["tradeNo"])),
        )
        assert (row["base_price"], row["avg_price"], row["low_price"], row["high_price"]) == (
            num(r["basePrice"]),
            num(r["tradedAveragePrice"]),
            num(r["tradeMinPrice"]),
            num(r["tradeMaxPrice"]),
        )
        assert row["value_rial"] == int(num(r["totalValueRials"])) and row["price_unit"] == clean(
            r["priceUnitTitle"]
        )
        assert row["kwh"] is None  # physical products carry no kWh
        basis = PRICE_BASIS.get((row["volume_unit"], row["price_unit"]))
        if basis:  # the units the labels promise, reconciled with the exchange's own value
            assert row["price_basis"] == basis and row["price_currency"] == "IRR"
        if basis == "rial per kilogram":
            assert isclose(
                row["traded_volume"] * 1000 * row["avg_price"], row["value_rial"], rel_tol=1e-6
            )
        if basis == "rial per liter":
            assert isclose(row["traded_volume"] * row["avg_price"], row["value_rial"], rel_tol=1e-6)

    # the session is history: the exchange's day, to the rial
    assert out["totals"]["auctions"] == out["totals"]["traded_auctions"] == 12
    assert out["totals"]["value_rial"] == 22_620_322_449_686
    assert out["totals"]["volume_by_unit"] == {"تن": 13143.0, "مترمکعب": 510.0}
    top = out["rows"][0]
    assert (top["auction_id"], top["product"], top["traded_volume"], top["value_rial"]) == (
        96517,
        "برش کربنی هیدروکربور هیدروژنه شده با درجه مرغوبیت ON (PGH)",
        2000.0,
        5_430_004_000_000,
    )
    assert (top["price_basis"], top["avg_price"], top["ring"], top["auction_time"]) == (
        "rial per kilogram",
        2_715_002.0,
        "داخلی",
        "12:50",
    )
    dollar = one(
        out["rows"], lambda r: r["auction_id"] == 96511, "liquefied gas for export"
    )  # priced in US dollars per tonne
    assert (
        dollar["price_currency"],
        dollar["price_basis"],
        dollar["avg_price"],
        dollar["value_rial"],
    ) == ("USD", "US dollars per tonne", 598.4, 2_243_334_579_200)
    assert (
        round(dollar["value_rial"] / (dollar["traded_volume"] * dollar["avg_price"])) == 1_874_444
    )  # the exchange's dollar rate


@scenario("energy_offers", "energy_market", view="offers")
def _energy_offers(run):
    out = run.out
    assert query(run, "GetPhysicalMarketOffersAuction") == {
        "Lang": "fa",
        "PageNumber": "1",
        "PageSize": "50",
    }
    assert query(run, "GetPowerMarketAuctionAnnouncements") == {
        "Lang": "fa",
        "PageNumber": "1",
        "PageSize": "20",
    }
    physical_env, power_env = (
        run.rec.body("GetPhysicalMarketOffersAuction"),
        run.rec.body("GetPowerMarketAuctionAnnouncements"),
    )
    physical = physical_env["results"]
    power = [
        r for r in power_env["results"] if not clean(r["auctionState"])
    ]  # the archive also lists every held auction
    held = [r for r in power_env["results"] if clean(r["auctionState"])]
    assert (
        power and held and all(clean(r["auctionState"]) == "برگزار شده" for r in held)
    )  # the archive must reach past the coming sessions

    assert_keys(out, "exchange view markets filters announced returned rows notes")
    assert (out["view"], out["markets"], out["filters"]) == (
        "offers",
        ["physical", "power"],
        {"product": None},
    )
    assert out["announced"] == {"physical": len(physical), "power": len(power)}
    assert out["returned"] == len(out["rows"]) == min(20, len(physical) + len(power))
    keyed = [(r["date"] or "9999", r["time"] or "", r["auction_id"]) for r in out["rows"]]
    assert keyed == sorted(keyed)  # soonest first
    by_id = {("physical", r["auctionIdn"]): r for r in physical} | {
        ("power", r["auctionIdn"]): r for r in power
    }
    assert len(by_id) == len(physical) + len(power)
    held_ids = {r["auctionIdn"] for r in held}
    for row in out["rows"]:
        assert_keys(row, OFFER_ROW)
        assert row["auction_id"] not in held_ids and row["status"] != "برگزار شده"
        r = by_id[(row["market"], row["auction_id"])]
        assert row["product"] == clean(r["instrumentDisplayName"]) and row["supplier"] == clean(
            r["supplier"]
        )
        assert row["date_jalali"] == r["auctionDateShamsi"].split(" ")[0] and is_jdate(
            row["date_jalali"]
        )
        assert row["date"] == jalali_iso(row["date_jalali"]) and row["time"] == r["auctionTime"][:5]
        assert row["offered_volume"] == num(r["auctionVolumeTooltip"]) and row[
            "trade_type"
        ] == clean(r["tradeType"])
        assert row["reference_price"] == num(r["referencePrice"])
        assert row["ring"] == clean(r["targetMarketName"])
        if row["market"] == "physical":
            assert row["volume_unit"] == clean(r["auctionVolume"].split(" ", 1)[1])  # «1,000 تن»
            assert row["base_price"] == num(r["basePriceTooltip"]) and row["status"] == clean(
                r["stepTitle"]
            )
            assert row["symbol"] is None  # the physical offers carry no trading symbol
        else:
            assert row["volume_unit"] == POWER_UNIT == clean(r["volumeUnitTitle"])
            assert row["volume_unit_en"] == "kW of capacity over the delivery period" and row[
                "symbol"
            ] == clean(r["energySymbol"])
            assert row["delivery_terms"] == clean(r["termsOfDelivery"]) and row[
                "base_price_text"
            ] == clean(r["basePrice"])
    # the electricity page is all coming sessions followed by held ones, so nothing more is claimed to be missing
    more = physical_env["pagedMetaData"][0]["hasNext"]
    assert any("may have announced more" in n for n in out["notes"]) is more
    assert any("held are left out" in n for n in out["notes"])


@scenario("energy_auction", "energy_market", view="auction", auction_id=96519)
def _energy_auction(run):
    out = run.out
    detail_env, trades_env = (
        run.rec.body("GetMarketAuctionDetails/96519"),
        run.rec.body("TradeOnDay/96519"),
    )
    detail, trades = one(detail_env["results"], lambda r: True, "auction"), trades_env["results"]
    assert_keys(
        out,
        "exchange view symbol product description producer status date_jalali date time trade_type units price_currency "
        "offered_volume maximum_purchase minimum_purchase minimum_for_price_discovery lot_size base_price reference_price "
        "delivery clearing destination payment_terms buy_orders sell_orders demand_volume supply_volume trades totals notes",
    )
    assert (out["view"], out["symbol"], out["product"]) == (
        "auction",
        clean(detail["energySymbol"]),
        clean(detail["instrumentDisplayName"]),
    )
    assert (out["description"], out["producer"], out["status"]) == (
        clean(detail["auctionDesc"]),
        clean(detail["producerName"]),
        clean(detail["stepTitle"]),
    )
    assert (out["date_jalali"], out["date"], out["trade_type"]) == (
        detail["auctionDate"],
        jalali_iso(detail["auctionDate"]),
        clean(detail["tradeTypeTitle"]),
    )
    assert out["time"] == detail["auctionTime"][:5]

    # the units are the exchange's own, and the tool says what the price is
    assert_keys(
        out["units"], "volume volume_en price price_basis price_per volume_to_price_unit note"
    )
    assert out["units"] == {
        "volume": "تن",
        "volume_en": "tonne",
        "price": "ریال",
        "price_basis": "rial per kilogram",
        "price_per": "کیلوگرم",
        "volume_to_price_unit": 1000.0,
        "note": "1 تن = 1000 کیلوگرم",
    }
    assert (
        detail["volumeUnitTitle"],
        detail["priceUnitTitle"],
        detail["volumeUnitTitlePrice"],
        detail["convertPriceVolume"],
    ) == ("تن", "ریال", "کیلوگرم", 1000)
    assert all(
        t["priceOnVolumeUnit"] == "ریال/کیلوگرم" and t["volumeUnitTitle"] == "تن" for t in trades
    )
    assert out["price_currency"] == "IRR"
    assert_keys(out["delivery"], "place period")
    assert (out["clearing"], out["destination"], out["payment_terms"]) == (
        clean(detail["clearingType"]),
        clean(detail["destination"]),
        clean(detail["termsOfPayment"]),
    )

    # order levels and trades
    assert out["buy_orders"] == [
        {
            "price": float(o["price"]),
            "volume": float(o["totalQuantity"]),
            "orders": int(o["orderCount"]),
        }
        for o in detail["buyOrders"]
    ]
    assert out["sell_orders"] == [
        {
            "price": float(o["price"]),
            "volume": float(o["totalQuantity"]),
            "orders": int(o["orderCount"]),
        }
        for o in detail["saleOrders"]
    ]
    assert out["demand_volume"] == sum(o["totalQuantity"] for o in detail["buyOrders"])
    assert out["supply_volume"] == sum(o["totalQuantity"] for o in detail["saleOrders"])
    assert len(out["trades"]) == len(trades)
    for row, t in zip(out["trades"], trades, strict=True):
        assert_keys(row, "date volume price value_rial price_per")
        assert (row["date"], row["volume"], row["price"], row["value_rial"], row["price_per"]) == (
            jalali_iso(t["tradeDateShamsi"]),
            float(t["tradedQuantity"]),
            float(t["tradedPrice"]),
            int(t["tradedValue"]),
            t["priceOnVolumeUnit"],
        )
        assert row["value_rial"] == round(
            row["volume"] * 1000 * row["price"]
        )  # tons x 1,000 kg x rial/kg
    assert_keys(out["totals"], "trades volume value_rial")
    assert out["totals"] == {
        "trades": len(trades),
        "volume": sum(t["tradedQuantity"] for t in trades),
        "value_rial": sum(t["tradedValue"] for t in trades),
    }

    # the auction is history: CSO of Shazand on 2026-11-04, 3,900 t of 7,000 t offered
    assert (out["symbol"], out["product"], out["status"], out["date"], out["time"]) == (
        "DSOSZCABEX0050818",
        "سی اس او",
        "توقف مازاد عرضه",
        DAY,
        "12:20",
    )
    assert (
        out["offered_volume"],
        out["maximum_purchase"],
        out["minimum_purchase"],
        out["lot_size"],
        out["base_price"],
    ) == (7000.0, 7000.0, 200.0, 100.0, 979_177.0)
    assert out["buy_orders"] == [{"price": 979_177.0, "volume": 3900.0, "orders": 4}]
    assert out["sell_orders"] == [{"price": 979_177.0, "volume": 7000.0, "orders": 1}]
    assert out["totals"] == {"trades": 4, "volume": 3900.0, "value_rial": 3_818_790_300_000}
    assert [t["volume"] for t in out["trades"]] == [500.0, 200.0, 200.0, 3000.0]


@scenario("energy_overview", "energy_market", view="overview")
def _energy_overview(run):
    out = run.out
    today = run.rec.body("GetTodayMarketsValues")["results"]
    physical = one(
        run.rec.body("GetPhysicalMarketAtAGlance")["results"], lambda r: True, "physical glance"
    )
    power = one(run.rec.body("GetPowerMarketAtAGlance")["results"], lambda r: True, "power glance")
    assert_keys(out, "exchange view physical_market power_market traded_today notes")
    assert out["view"] == "overview"
    assert_keys(out["physical_market"], "state trades_today")
    assert_keys(out["physical_market"]["state"], "all_rings internal_ring international_ring")
    rings = {
        "all_rings": "allRings",
        "internal_ring": "internalRing",
        "international_ring": "internationalRing",
    }
    assert out["physical_market"]["state"] == {
        name: clean(physical[key]["marketState"]) for name, key in rings.items()
    }
    assert out["physical_market"]["trades_today"] == int(
        num(physical["allRings"]["totalTradesCount"])
    )
    assert_keys(out["power_market"], "state trades_today")
    assert (out["power_market"]["state"], out["power_market"]["trades_today"]) == (
        clean(power["marketState"]),
        int(num(power["totalTradesCount"])),
    )
    assert (
        out["physical_market"]["state"]["all_rings"] and out["power_market"]["state"]
    )  # «باز» or «بسته»
    # today's traded value: the exchange publishes million rial
    assert len(out["traded_today"]) == len(today) == 4
    for row, m in zip(out["traded_today"], today, strict=True):
        assert_keys(row, "market_id market traded_value_rial trades")
        assert (row["market_id"], row["market"], row["trades"]) == (
            m["marketSummaryType"],
            clean(m["marketName"]),
            int(m["tradedNo"]),
        )
        assert row["traded_value_rial"] == round(m["tradedValue"] * 1_000_000)
    assert {m["market"] for m in out["traded_today"]} == {
        "بازار فیزیکی",
        "بازار برق",
        "بازار مشتقه",
        "سایر اوراق",
    }
    assert any("million rial" in n for n in out["notes"])
