"""Fund registry: type names, row shaping and ranking.

The fixture holds 26 real funds recorded from Fund/GetFunds on 2026-11-04: a young fund whose longer returns are 0.0 in the
registry, an older fund with a 0.0 one-year return, a fund with zero net assets and a 2021 NAV date, a fund with an
investor mix, the largest fixed-income fund, the top one-year performers (market-maker funds) and more, across 12 types.
"""

from __future__ import annotations

import pytest

from iran_bourse_mcp import funds as fd

ALL_IDS = [4, 5, 6, 7, 11, 12, 13, 16, 17, 18, 21, 22, 23, 24, 25]


@pytest.fixture()
def sample(fx):
    return {int(t): payload["funds"] for t, payload in fx("funds_registry_sample").items()}


def regs(result):
    return [f["reg_no"] for f in result["funds"]]


def by_reg(result):
    return {f["reg_no"]: f for f in result["funds"]}


# ------------------------------------------------------------------------------------ type names


@pytest.mark.parametrize(
    ("query", "ids"),
    [
        (None, ALL_IDS), ("all", ALL_IDS), ("همه", ALL_IDS), ("", ALL_IDS),
        ("fixed_income", [4]), ("Fixed Income", [4]), ("fixed-income", [4]), ("درآمد ثابت", [4]), ("ثابت", [4]), ("4", [4]), (4, [4]),
        ("gold", [5]), ("commodity", [5]), ("کالایی", [5]),
        ("equity", [6, 21, 22, 23]), ("سهام", [6, 21, 22, 23]), ("در سهام", [6]), ("equity_general", [6]),
        ("mixed", [7]), ("مختلط", [7]), ("market_maker", [11]), ("بازارگردانی", [11]), ("venture", [12]), ("project", [13]),
        ("private", [16]), ("fund_of_funds", [17]), ("real_estate", [18]), ("املاک", [18]),
        ("sector", [21]), ("بخشی", [21]), ("leveraged", [22]), ("اهرمی", [22]), ("index", [23]), ("شاخصی", [23]),
        ("principal_protected", [24]), ("تضمین", [24]), ("pension", [25]), ("بازنشستگی تکمیلی", [25]),
        ("mixed,gold", [5, 7]), ("مختلط، جسورانه", [7, 12]), ("equity,mixed", [6, 7, 21, 22, 23]), ("6, 6", [6]),
    ],
)
def test_fund_type_names_in_english_and_persian(query, ids):
    assert fd.resolve_fund_types(query) == ids


@pytest.mark.parametrize(
    ("query", "needle"),
    [("xyz", "not recognised"), ("0", "unknown fund type id 0"), ("1", "unknown fund type id 1"), ("99", "unknown fund type id 99"),
     ("14", "has no funds"), ("19", "has no funds"), ("ب", "not recognised")],
)
def test_unknown_fund_types_say_what_is_valid(query, needle):
    with pytest.raises(ValueError, match=needle):
        fd.resolve_fund_types(query)


def test_error_lists_every_valid_type():
    with pytest.raises(ValueError) as exc:
        fd.resolve_fund_types("bitcoin")
    assert all(t["key"] in str(exc.value) for t in fd.type_catalogue())


def test_type_catalogue_matches_the_exchange_ids():
    catalogue = {t["id"]: t for t in fd.type_catalogue()}
    assert list(catalogue) == ALL_IDS and catalogue[4]["name"] == "درآمد ثابت" and catalogue[11]["key"] == "market_maker"
    assert catalogue[23]["official_name"] == "در سهام-شاخصی"


@pytest.mark.parametrize(
    ("query", "key"),
    [("return_1y", "return_1y"), ("1y", "return_1y"), ("Year", "return_1y"), ("1m", "return_1m"), ("3m", "return_3m"), ("week", "return_1w"),
     ("since inception", "return_since_inception"), ("size", "net_assets"), ("AUM", "net_assets"), ("nav", "nav"), (None, "return_1y")],
)
def test_sort_names_and_aliases(query, key):
    assert fd.resolve_sort(query) == key


def test_unknown_sort_lists_choices():
    with pytest.raises(ValueError, match="sort_by must be one of return_1d"):
        fd.resolve_sort("sharpe")


# ------------------------------------------------------------------------------------ one fund


def test_young_fund_has_null_returns_for_horizons_it_has_not_reached(sample):
    row = by_reg(fd.shape_fund_ranking({4: sample[4]}, limit=50))[12551]  # started 2026-09-01, NAV of 2026-11-03: 63 days
    assert row["age_days"] == 63 and row["nav_date"] == "2026-11-03" and row["type"] == "fixed_income"
    assert row["returns_pct"] == {"1d": -0.15, "1w": 0.15, "1m": 1.95, "3m": None, "6m": None, "1y": None, "since_inception": 6.98}
    assert (row["net_assets"], row["units"]) == (42792577500740, 4000000000)
    # net assets = redemption NAV x units: 10698 x 4,000,000,000 = 42,792,000,000,000 (the registry rounds NAV to whole rial)
    assert abs(row["net_assets"] / (row["nav_redemption"] * row["units"]) - 1) < 1e-4
    assert (row["nav_redemption"], row["nav_issue"], row["nav_statistical"]) == (10698.0, 10704.0, 10698.0)
    assert row["portfolio_pct"] == {"stock": 0.88, "bond": 14.45, "deposit": 71.86, "other": 13.21}  # cash equals deposit and is left out
    assert row["manager"] == "سبد گردان هامون ایرانیان"


def test_a_three_day_old_fund_has_no_one_week_return_either(sample):
    row = by_reg(fd.shape_fund_ranking({6: sample[6]}, limit=50))[12598]  # started 2026-10-31
    assert row["age_days"] == 3
    assert row["returns_pct"] == {"1d": -0.01, "1w": None, "1m": None, "3m": None, "6m": None, "1y": None, "since_inception": -0.02}


def test_zero_over_a_long_horizon_is_not_published_but_one_day_zero_is_kept(sample):
    row = by_reg(fd.shape_fund_ranking({5: sample[5]}, limit=50))[12332]  # older than a year, registry says 0.0 for 3m/6m/1y/inception
    assert row["age_days"] > 365
    assert row["returns_pct"] == {"1d": 0.0, "1w": -8.15, "1m": -16.145, "3m": None, "6m": None, "1y": None, "since_inception": None}


def test_zero_net_assets_and_units_become_null(sample):
    rows = by_reg(fd.shape_fund_ranking({4: sample[4], 7: sample[7]}, limit=50))
    assert rows[11583]["net_assets"] is None and rows[11583]["units"] is None and rows[11583]["nav_date"] == "2021-09-22"
    assert rows[11691]["units"] is None and rows[11691]["net_assets"] == 149963581  # one without units, one with


def test_name_drops_stray_marker_but_keeps_the_published_words(sample):
    row = by_reg(fd.shape_fund_ranking({25: sample[25]}))[12352]  # published as '>صندوق سرمایه‌گذاری بازنشستگی تکمیلی ...'
    assert not row["name"].startswith(">") and row["name"].startswith("صندوق")
    assert row["type"] == "supplementary_pension"


def test_investor_mix_appears_only_where_published(sample):
    rows = by_reg(fd.shape_fund_ranking({4: sample[4]}, limit=50))
    assert rows[14052959]["investors"] == {"retail_pct": 0.01, "institutional_pct": 99.99, "retail_count": 1, "institutional_count": 1}
    for reg in (12551, 11277, 11405):
        assert "investors" not in rows[reg] and "estimated_yield_pct" not in rows[reg] and "market_maker" not in rows[reg]


def test_cash_is_kept_when_it_differs_from_deposit_and_mix_is_null_when_empty():
    raw = {"regNo": 1.0, "mfName": "الف", "recordDate": "2026-11-03T00:00:00", "initiationDate": "2020-01-01T00:00:00", "portfolioStock": 10.0,
           "portfolioBond": 0.0, "portfolioDeposit": 20.0, "portfolioCash": 25.0, "portfolioOther": 0.0}
    assert fd.shape_fund(raw, 4)["portfolio_pct"] == {"stock": 10.0, "bond": 0.0, "deposit": 20.0, "cash": 25.0, "other": 0.0}
    assert fd.shape_fund({**raw, "portfolioStock": 0.0, "portfolioDeposit": 0.0, "portfolioCash": 0.0}, 4)["portfolio_pct"] is None


def test_full_detail_adds_the_rest(sample):
    row = by_reg(fd.shape_fund_ranking({4: sample[4]}, limit=50, detail="full"))[12551]
    assert row["type_name"] == "درآمد ثابت" and row["jdate"] == "1405/08/12" and row["initiation_date"] == "2026-09-01"
    assert row["top5_holdings_pct"] == 0.73 and row["custodian"].startswith("موسسه حسابرسی") and row["guarantor"] is None  # '----' means none
    assert row["investment_manager"] == "سبد گردان هامون ایرانیان" and row["website"] is None
    assert row["portfolio_pct"]["cash"] == 71.86  # nothing is left out in the full view
    assert (row["investors"], row["estimated_yield_pct"], row["guaranteed_yield_pct"], row["market_maker"]) == (None, None, None, None)


def test_published_yield_and_market_maker_show_up_when_present():
    raw = {"regNo": 2.0, "mfName": "ب", "recordDate": "2026-11-03T00:00:00", "initiationDate": "2020-01-01T00:00:00", "estimatedEarningRate": 23.5,
           "guaranteedEarningRate": 20.0, "marketMaker": "بازارگردان نمونه"}
    row = fd.shape_fund(raw, 4)
    assert (row["estimated_yield_pct"], row["guaranteed_yield_pct"], row["market_maker"]) == (23.5, 20.0, "بازارگردان نمونه")


# ------------------------------------------------------------------------------------ ranking


def test_default_ranking_is_one_year_return_with_missing_values_last(sample):
    result = fd.shape_fund_ranking(sample, limit=30)
    assert result["sorted_by"] == "return_1y" and result["descending"] is True
    ranked = regs(result)
    assert ranked[:8] == [11711, 11759, 12047, 12150, 12352, 11312, 12061, 12356]
    assert [f["returns_pct"]["1y"] for f in result["funds"][:4]] == [668.27, 469.67, 460.75, 197.6]
    assert all(f["returns_pct"]["1y"] is None for f in result["funds"][20:]) and result["returned"] == 26
    assert set(ranked[20:]) == {12551, 11405, 14052959, 12332, 12601, 12598}  # 20 funds publish a 1y return, 6 do not


def test_ascending_order_and_missing_values_stay_last(sample):
    result = fd.shape_fund_ranking(sample, descending=False, limit=3)
    assert regs(result) == [11583, 11691, 11540]  # -62.923, 2.133, 4.253
    assert fd.shape_fund_ranking(sample, descending=False, limit=26)["funds"][-1]["returns_pct"]["1y"] is None


def test_other_return_horizons_and_size(sample):
    assert regs(fd.shape_fund_ranking(sample, sort_by="1m", limit=4)) == [11921, 12061, 11759, 12072]  # 44.347, 7.14, 5.02, 4.52
    assert regs(fd.shape_fund_ranking(sample, sort_by="size", limit=4)) == [11277, 11405, 12356, 11759]
    # age is NAV date minus start date: 4444 days (started 2014-09-03), 4229 (2015-04-06), 3884 (started 2016-02-17, NAV of 2026-10-06)
    assert regs(fd.shape_fund_ranking(sample, sort_by="oldest", limit=3)) == [11277, 11312, 11405]
    assert fd.shape_fund_ranking(sample, sort_by="net_assets", limit=1)["funds"][0]["net_assets"] == 1584651219647464


def test_min_net_assets_filters_in_rial_and_drops_funds_without_a_figure(sample):
    result = fd.shape_fund_ranking(sample, min_net_assets=1e13, limit=50)  # 10 trillion rial = 1 trillion toman
    assert result["universe"]["matched"] == 15 and result["universe"]["funds"] == 26
    assert set(regs(result)) == {11277, 11312, 11359, 11405, 11540, 11711, 11729, 11759, 11920, 12057, 12150, 12352, 12356, 12551, 12601}
    assert result["universe"]["total_net_assets"] == 2392896737206241
    assert result["min_net_assets"] == 1e13
    assert 11583 not in regs(fd.shape_fund_ranking(sample, min_net_assets=1, limit=50))  # zero net assets
    assert 11583 in regs(fd.shape_fund_ranking(sample, limit=50))


def test_summary_counts_stale_navs(sample):
    result = fd.shape_fund_ranking(sample, limit=50)
    u = result["universe"]
    # newest NAV is 2026-11-03; older than 2026-10-27 is stale: 11405 (10-06), 11540 (10-24), 11691 (2023), 11583 (2021), 14052959 (2020)
    assert u["latest_nav_date"] == "2026-11-03" and u["stale_nav_funds"] == 5
    assert {f["reg_no"] for f in result["funds"] if f.get("stale")} == {11405, 11540, 11691, 11583, 14052959}
    assert u["total_net_assets"] == 2410315988682056
    assert fd.shape_fund_ranking(sample, min_net_assets=1e13, limit=50)["universe"]["stale_nav_funds"] == 2  # 11405 and 11540


def test_type_filter_through_the_resolver(sample):
    ids = fd.resolve_fund_types("equity")  # 6, 21, 22, 23; the fixture has no leveraged fund
    result = fd.shape_fund_ranking({i: sample[i] for i in ids if i in sample}, limit=10)
    assert regs(result) == [12150, 11312, 12061, 11454, 11729, 12598]  # 197.6, 139.928, 139.44, 128.627, 85.015, and the 3-day-old fund last
    assert [(t["id"], t["key"], t["funds"], t["matched"]) for t in result["types"]] == [
        (6, "equity_general", 4, 4), (21, "sector_equity", 1, 1), (23, "index_equity", 1, 1)
    ]


def test_types_header_counts_every_type_and_what_survived_the_filter(sample):
    result = fd.shape_fund_ranking(sample, min_net_assets=1e13)
    counts = {t["id"]: (t["funds"], t["matched"]) for t in result["types"]}
    assert counts == {4: (6, 4), 5: (3, 2), 6: (4, 1), 7: (2, 0), 11: (4, 3), 12: (1, 0), 13: (1, 1), 17: (1, 1), 21: (1, 1), 23: (1, 1), 24: (1, 0), 25: (1, 1)}
    assert sum(f for f, _ in counts.values()) == 26 and sum(m for _, m in counts.values()) == 15


def test_a_fund_listed_under_two_types_counts_once(sample):
    result = fd.shape_fund_ranking({4: sample[4], 7: sample[4] + sample[7]}, limit=50)
    assert result["universe"]["funds"] == 8 and len(set(regs(result))) == 8
    assert {t["id"]: t["funds"] for t in result["types"]} == {4: 6, 7: 2}


def test_limit_and_empty_types(sample):
    assert fd.shape_fund_ranking(sample, limit=3)["returned"] == 3
    assert fd.shape_fund_ranking(sample, limit=0)["returned"] == 1
    assert fd.shape_fund_ranking(sample, limit=9999)["returned"] == 26
    empty = fd.shape_fund_ranking({14: [], 4: None})
    assert empty["funds"] == [] and empty["universe"]["funds"] == 0 and empty["universe"]["latest_nav_date"] is None
    assert [t["funds"] for t in empty["types"]] == [0, 0]


def test_notes_explain_published_versus_derived_and_how_to_find_the_symbol(sample):
    note = fd.shape_fund_ranking(sample)["note"]
    assert "Derived here: age_days" in note and "search_symbol" in note and "etf_nav" in note and "not annualised" in note
    assert "Market-maker" in note  # one-year ranking warns about extreme market-maker returns
    assert "Market-maker" not in fd.shape_fund_ranking(sample, sort_by="size")["note"]


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [({"sort_by": "sharpe"}, "sort_by must be one of"), ({"detail": "all"}, "detail must be"), ({"min_net_assets": -1}, "cannot be negative"),
     ({"min_net_assets": "lots"}, "must be a number in rial"), ({"limit": "ten"}, "limit must be a whole number")],
)
def test_bad_ranking_arguments(sample, kwargs, needle):
    with pytest.raises(ValueError, match=needle):
        fd.shape_fund_ranking(sample, **kwargs)
