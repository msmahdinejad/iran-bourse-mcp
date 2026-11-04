"""Official top lists: catalogue, request resolution and row shaping against payloads recorded live on 2026-11-04."""

from __future__ import annotations

import copy

import pytest

from iran_bourse_mcp import toplists as T


def rows_of(fx, name, key):
    return fx(name)[key]


def shaped(fx, fixture, key, list_name, flow=None, limit=20):
    return T.shape_top_list(T.resolve_top_list(list_name, flow, limit), rows_of(fx, fixture, key))


# ------------------------------------------------------------------------------------------ catalogue


def test_catalogue_is_consistent():
    names = [d.name for d in T.CATALOGUE]
    assert len(names) == len(set(names)) >= 60
    for d in T.CATALOGUE:
        assert d.family in (T.FAMILY_TRADE, T.FAMILY_LIMITS, T.FAMILY_CAP, T.FAMILY_SECTORS), d.name
        assert len(set(d.flows)) == len(d.flows), d.name
        assert d.title_fa and d.title_en and d.columns[0] == "rank", d.name
        assert (d.side is not None) == (d.family == T.FAMILY_LIMITS), d.name
        assert d.sort is None or d.sort.split()[0] in d.columns, d.name
    # every (list, flow) pair resolves to its own URL, and every exchange type name maps back to a list
    seen = set()
    for d in T.CATALOGUE:
        for flow in d.flows if d.family != T.FAMILY_SECTORS else (None,):
            request = T.resolve_top_list(d.name, flow, 5)
            assert request.definition is d and request.path not in seen
            seen.add(request.path)
            assert T.resolve_top_list(request.site_type, flow, 5).definition is d


def test_catalogue_output_and_filters():
    full = T.catalogue()
    assert full["count"] == len(T.CATALOGUE) and full["lists"][0]["name"] == "most_active"
    gainers = next(e for e in full["lists"] if e["name"] == "price_gainers")
    assert gainers["flows"] == [1, 2, 11, 12] and gainers["default_flow"] == 1 and gainers["sorted_by"] == "close_pct desc"
    assert "rank" not in gainers["columns"] and "close_pct" in gainers["columns"]
    assert full["flows"]["27"].endswith("(P1)") and full["flows"]["11"] == "بازار اول بورس"
    assert any("HTTP 500" in n for n in full["notes"])
    derivatives = T.catalogue(flow="derivatives", group="queues")
    assert {e["name"] for e in derivatives["lists"]} >= {"option_bids", "option_asks", "debt_bids_fara"}
    assert all(3 in e["flows"] and e["group"] == "queues" for e in derivatives["lists"])
    assert {e["name"] for e in T.catalogue(flow=12)["lists"]} == {"most_active", "top_value", "top_volume", "price_gainers", "price_losers", "last_above_close", "rights", "block_trades", "closing_price_only"}
    with pytest.raises(ValueError, match="Unknown group"):
        T.catalogue(group="nope")
    with pytest.raises(ValueError, match="No list answers for flow 99"):
        T.catalogue(flow=99)


def test_top_list_convenience_returns_the_catalogue_when_asked(fx):
    for asked in (None, "", "catalogue", "Catalog", "lists", "help"):
        assert T.is_catalogue(asked) and T.top_list(asked)["count"] == len(T.CATALOGUE)
    assert not T.is_catalogue("rights") and not T.is_catalogue("Top")
    assert T.top_list("catalogue", flow=2)["count"] < len(T.CATALOGUE)
    out = T.top_list("rights", rows_of(fx, "toplists_trade_gainers", "tradeTop"), flow=1, limit=2)
    assert out["list"] == "rights" and out["count"] == 2


# ------------------------------------------------------------------------------------------- requests


@pytest.mark.parametrize(
    ("name", "flow", "limit", "path", "key"),
    [
        ("price_gainers", None, 20, "/ClosingPrice/GetTradeTop/PClosingTop/1/20", "tradeTop"),
        ("PClosingTop", 11, 5, "/ClosingPrice/GetTradeTop/PClosingTop/11/5", "tradeTop"),
        ("gainers", "fara", 7, "/ClosingPrice/GetTradeTop/PClosingTop/2/7", "tradeTop"),
        ("block_trades", 2, 10, "/ClosingPrice/GetTradeTop/BlockOTC/2/10", "tradeTop"),
        ("block", 1, 10, "/ClosingPrice/GetTradeTop/Block/1/10", "tradeTop"),
        ("BlockOTC", None, 10, "/ClosingPrice/GetTradeTop/BlockOTC/2/10", "tradeTop"),
        ("tal", "2", 3, "/ClosingPrice/GetTradeTop/TALOTC/2/3", "tradeTop"),
        ("option_open_interest", "derivatives", 15, "/ClosingPrice/GetTradeTop/OptionOP/3/15", "tradeTop"),
        ("most_active", 29, 5, "/ClosingPrice/GetTradeTop/MostVisited/29/5", "tradeTop"),
        ("largest_bids", None, 8, "/BestLimits/GetBestLimitsTop/Buy/1/8", "bestLimitsTop"),
        ("Sell", "fara", 8, "/BestLimits/GetBestLimitsTop/Sell/2/8", "bestLimitsTop"),
        ("option_bids", None, 8, "/BestLimits/GetBestLimitsTop/OptionBuy/3/8", "bestLimitsTop"),
        ("market_cap_losers", 2, 4, "/ClosingPrice/GetMarketCap/Btm/2/4", "marketCap"),
        ("Top", 1, 4, "/ClosingPrice/GetMarketCap/Top/1/4", "marketCap"),
        ("sectors", None, 12, "/MarketData/GetSectorTop/0", "sectorTop"),
    ],
)
def test_requests_name_the_exchange_url(name, flow, limit, path, key):
    request = T.resolve_top_list(name, flow, limit)
    assert (request.path, request.inner_key, request.limit) == (path, key, limit)


def test_request_errors_tell_the_agent_what_to_do():
    with pytest.raises(ValueError, match="Valid flows: 1 \\(بورس\\), 2 \\(فرابورس\\), 11 .*12 "):
        T.resolve_top_list("rights", 3)
    with pytest.raises(ValueError, match="Did you mean: price_gainers"):
        T.resolve_top_list("pricegainer")
    with pytest.raises(ValueError, match="Call top_lists with list_name='catalogue'"):
        T.resolve_top_list("zzz")
    with pytest.raises(ValueError, match="Unknown flow 'mars'"):
        T.resolve_top_list("rights", "mars")
    with pytest.raises(ValueError, match="Bourse only"):
        T.resolve_top_list("sectors", 2)
    for bad in (0, 301, -1, True, "5"):
        with pytest.raises(ValueError, match="limit must be"):
            T.resolve_top_list("rights", 1, bad)
    with pytest.raises(ValueError, match="list_name is required"):
        T.resolve_top_list("catalogue")
    with pytest.raises(ValueError, match="flow must be a number"):
        T.parse_flow(True)
    assert T.parse_flow(" Bourse ") == 1 and T.parse_flow("12") == 12 and T.parse_flow("") is None


# ----------------------------------------------------------------------------------------- trade rows


def test_gainers_recompute_percentages_from_prices(fx):
    out = shaped(fx, "toplists_trade_gainers", "tradeTop", "price_gainers", 1, 3)
    assert out["list"] == "price_gainers" and out["flow"] == 1 and out["market"] == "بورس" and out["exchange_type"] == "PClosingTop"
    assert out["sorted_by"] == "close_pct desc" and out["as_of"] == "2026-11-04" and out["as_of_jdate"] == "1405/08/13"
    assert out["count"] == 3 and [r["rank"] for r in out["rows"]] == [1, 2, 3]  # the limit cuts the 4 recorded rows
    first, second = out["rows"][0], out["rows"][1]
    assert list(first) == list(T.COLS_MOVERS)
    assert first["symbol"] == "لوتوس" and first["name"] == "تامین سرمایه لوتوس پارسیان"  # Arabic ي to Persian ی
    assert first["ins_code"] == "59142194115401696"
    assert first["yesterday"] == 4000 and first["close"] == 4120 and first["last"] == 4120
    assert first["close_pct"] == 3.0  # (4120 - 4000) / 4000
    assert second["close_pct"] == 3.0 and second["last_pct"] == 3.0  # 2960 / 98700 = 2.999 %
    assert first["low"] == 4000 and first["high"] == 4120
    assert (first["trades"], first["volume"], first["value"]) == (403, 29123528, 119902840040)
    assert "market_cap" not in first and "nav" not in first
    assert out["units"]["prices"] == "rial" and "notes" not in out


def test_value_leaders_have_no_day_prices_but_a_market_cap(fx):
    out = shaped(fx, "toplists_trade_value", "tradeTop", "top_value")
    assert list(out["rows"][0]) == list(T.COLS_RANKED) and "as_of" not in out  # dEven is 0 in this list
    fund, _, share = out["rows"]
    assert fund["symbol"] == "سپر" and fund["close"] == 48936 and fund["trades"] == 3241
    assert fund["market_cap"] == 685_104_000_000_000  # 48,936 x 14,000,000,000 units
    assert share["market_cap"] == 41_889_600_000_000_000  # 29,090 x 1.44e12 shares, equal to the exchange's own cap list
    assert out["notes"] == ["The exchange sends only the close, counts and market value for this list (no last price or day range)."]


def test_last_price_gap_lists(fx):
    out = shaped(fx, "toplists_trade_two_price", "tradeTop", "last_above_close", 1)
    gap, _, flat = out["rows"]
    assert list(gap) == list(T.COLS_GAP)
    assert gap["symbol"] == "خپویش" and (gap["yesterday"], gap["close"], gap["last"]) == (6780, 6650, 6900)
    assert gap["last_vs_close_pct"] == 3.76  # 250 / 6650
    assert gap["last_pct"] == 1.77 and "close_pct" not in gap  # 120 / 6780
    assert flat["last_vs_close_pct"] == 2.93 and flat["close"] == flat["yesterday"] == 9220  # 270 / 9220


def test_block_etf_option_and_energy_rows(fx):
    block = shaped(fx, "toplists_trade_block", "tradeTop", "block_trades", 1)["rows"]
    assert block[0]["symbol"] == "وبوعلی4" and block[0]["close_pct"] == 62.6  # (6000 - 3690) / 3690
    assert (block[0]["trades"], block[0]["volume"], block[0]["value"]) == (1, 360_000_000, 2_160_000_000_000)  # 360M x 6,000 rial
    etf = shaped(fx, "toplists_trade_etf", "tradeTop", "etf_trades", 1)["rows"]
    assert list(etf[0]) == list(T.COLS_FUND)
    assert (etf[0]["nav"], etf[0]["nav_premium_pct"]) == (48970, 0.0)  # 48,971 vs 48,970
    assert etf[1]["nav_premium_pct"] == 0.1  # 57 / 56,464
    assert etf[2]["nav_premium_pct"] == -32.03  # (541,900 - 797,269) / 797,269: a sector fund far under its NAV
    option, put = shaped(fx, "toplists_trade_options", "tradeTop", "option_calls", 3)["rows"][:2]
    assert list(option) == list(T.COLS_OPTION)
    assert option["open_interest"] == 820_084 and option["notional_value"] == 89_515_270_720_000
    assert (option["close_pct"], option["last_pct"]) == (30.82, 68.49)  # 45 / 146 and 100 / 146
    assert "last_vs_close_pct" not in option and option["symbol"] == "ضستا8059"
    assert (put["close_pct"], put["last_pct"]) == (-33.33, -66.67)  # 2 vs 3 and 1 vs 3 on an option that costs 3 rial
    energy = shaped(fx, "toplists_trade_energy", "tradeTop", "energy_futures", 67)
    row = energy["rows"][0]
    assert row["symbol"] == "جمیعا511" and row["close"] == row["yesterday"] == 85 and row["close_pct"] == 0.0
    assert row["last"] is None and row["low"] is None and row["high"] is None and (row["trades"], row["volume"], row["value"]) == (0, 0, 0)
    assert "as_of" not in energy and energy["flow"] == 67 and energy["market"] == "آتی انرژی"


def test_empty_list_is_not_an_error(fx):
    out = shaped(fx, "toplists_trade_empty", "tradeTop", "new_instruments", 1)
    assert out["count"] == 0 and out["rows"] == [] and "not an error" in out["notes"][-1] and "as_of" not in out
    assert T.shape_top_list(T.resolve_top_list("rights", 1, 5), None)["rows"] == []


# -------------------------------------------------------------------------------------- limits, caps


def test_largest_bids_and_asks(fx):
    bids = shaped(fx, "toplists_limits_buy", "bestLimitsTop", "largest_bids", 1)
    assert list(bids["rows"][0]) == list(T.COLS_LIMITS) and bids["sorted_by"] == "value desc"
    first = bids["rows"][0]
    assert (first["symbol"], first["side"], first["price"], first["volume"], first["orders"]) == ("آفاق", "buy", 12382, 2_001_637_036, 3)
    assert first["value"] == 24_784_269_779_752 == 2_001_637_036 * 12_382  # the exchange's `val` equals price x volume
    assert first["counter_volume"] == 0 and first["one_sided"] is True
    assert any("last orders of the session" in n for n in bids["notes"]) and "as_of" not in bids
    asks = shaped(fx, "toplists_limits_sell", "bestLimitsTop", "largest_asks", 1)["rows"]
    assert (asks[0]["symbol"], asks[0]["side"], asks[0]["price"], asks[0]["volume"], asks[0]["orders"]) == ("تداوم", "sell", 27592, 179_722_659, 1)
    assert asks[0]["value"] == 4_958_907_607_128 == 179_722_659 * 27_592


def test_limits_edge_cases(fx):
    rows = copy.deepcopy(rows_of(fx, "toplists_limits_buy", "bestLimitsTop"))
    rows[0]["val"] = 0  # value missing: price x volume stands in
    rows[1]["pMeOf"], rows[1]["qTitMeOf"] = 20535.0, 1500  # somebody offers: not a queue
    rows[2]["qTitMeDem"], rows[2]["zOrdMeDem"] = None, None
    out = T.shape_top_list(T.resolve_top_list("largest_bids", 1, 5), rows)["rows"]
    assert out[0]["value"] == 24_784_269_779_752  # 2,001,637,036 x 12,382 recomputed
    assert out[1]["counter_volume"] == 1500 and out[1]["one_sided"] is False
    assert out[2]["volume"] is None and out[2]["orders"] is None and out[2]["one_sided"] is False


def test_market_cap_lists_sign_the_change(fx):
    gainers = shaped(fx, "toplists_cap_top", "marketCap", "market_cap_gainers", 1)["rows"]
    assert list(gainers[0]) == list(T.COLS_CAP)
    top = gainers[0]
    assert top["symbol"] == "فملی" and top["market_cap"] == 41_889_600_000_000_000 and top["market_cap_yesterday"] == 40_795_200_000_000_000
    assert top["change"] == 1_094_400_000_000_000 and top["change_pct"] == 2.68  # 1.0944e15 / 4.07952e16
    losers = shaped(fx, "toplists_cap_btm", "marketCap", "market_cap_losers", 1)
    assert losers["sorted_by"] == "change asc"
    fars = losers["rows"][0]
    # the exchange sends +487.5T for a fall in the "Btm" list; the sign comes back from today - yesterday
    assert fars["change"] == -487_500_000_000_000 == 17_737_500_000_000_000 - 18_225_000_000_000_000
    assert fars["change_pct"] == -2.67  # 487.5T / 18,225T
    assert [r["change"] < 0 for r in losers["rows"]] == [True, True, True]


# ------------------------------------------------------------------------------------------ sectors


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("27-فلزات اساسي", ("27", "فلزات اساسی")),
        ("47خرده فروشي به جز وسايل نقليه", ("47", "خرده فروشی به جز وسایل نقلیه")),
        ("بيمه و بازنشسته66", ("66", "بیمه و بازنشسته")),
        ("استخراج نفت جزكشف11", ("11", "استخراج نفت جزکشف")),
        ("بانکها", (None, "بانکها")),
        ("", (None, None)),
        (None, (None, None)),
    ],
)
def test_sector_titles_split_into_code_and_name(title, expected):
    assert T.split_sector(title) == expected


def test_sectors_by_value(fx):
    out = shaped(fx, "toplists_sectors", "sectorTop", "sectors", limit=3)
    assert out["flow"] is None and out["market"] == "بورس" and out["count"] == 3 and out["exchange_type"] == "SectorTop"
    assert list(out["rows"][0]) == list(T.COLS_SECTOR)
    first = out["rows"][0]
    assert (first["rank"], first["sector_code"], first["sector"]) == (1, "27", "فلزات اساسی")
    assert (first["trades"], first["volume"], first["value"]) == (101_546, 5_516_347_380, 43_749_426_093_532)
    assert first["market_cap"] == pytest.approx(5.915923862414923e16)
    # the 7 industries of the fixture trade 96,161,109,078,652 rial together (the "شاخص صنعت" aggregate row is left out)
    assert first["value_share_pct"] == 45.5  # 43,749,426,093,532 / 96,161,109,078,652
    assert out["rows"][1]["value_share_pct"] == 29.23  # 28,112,499,632,400 / 96,161,109,078,652 = 0.292348
    everything = shaped(fx, "toplists_sectors", "sectorTop", "sectors", limit=50)
    assert everything["count"] == 7 and "شاخص صنعت" not in {r["sector"] for r in everything["rows"]}
    assert round(sum(r["value_share_pct"] for r in everything["rows"]), 1) == 100.0
    assert [r["sector_code"] for r in everything["rows"][-3:]] == ["47", "26", "66"]


# ------------------------------------------------------------------------------------- robustness


def test_every_list_survives_junk_rows():
    junk = [None, 5, {}, {"instrument": None}, {"instrument": {}, "pClosing": "x", "zTotTran": None, "marketCapToday": "?", "lVal30": None}]
    for d in T.CATALOGUE:
        flow = d.flows[0] if d.family != T.FAMILY_SECTORS else None
        out = T.shape_top_list(T.resolve_top_list(d.name, flow, 10), junk)
        assert out["list"] == d.name
        for row in out["rows"]:
            assert tuple(row) == tuple(c for c in d.columns)


def test_catalogue_columns_mirror_the_rows(fx):
    samples = {
        "price_gainers": ("toplists_trade_gainers", "tradeTop"), "largest_bids": ("toplists_limits_buy", "bestLimitsTop"),
        "market_cap_gainers": ("toplists_cap_top", "marketCap"), "sectors_by_value": ("toplists_sectors", "sectorTop"),
    }
    listed = {e["name"]: e for e in T.catalogue()["lists"]}
    for name, (fixture, key) in samples.items():
        keys = list(shaped(fx, fixture, key, name)["rows"][0])
        # the catalogue lists every column but the identity ones (rank, symbol, name, ins_code)
        assert listed[name]["columns"] == [c for c in keys if c not in ("rank", "symbol", "name", "ins_code")]
