"""Options and futures: chain shaping, derived values (hand-checked), filters, summary mode and error messages.

``derivatives_option_watch.json`` holds 26 real rows of ``GetInstrumentOptionMarketWatch/0`` recorded on 2026-11-04 after
the close: اهرم (a Bourse ETF) on two expiries, شستا on the day it expires (and one expiry later), and فرابورس (a Fara
Bourse share whose contract size is 1,254) with untraded and dead legs. ``derivatives_future_watch.json`` is the whole
``GetInstrumentFutureMarketWatch/0`` feed (16 contracts).
"""

from __future__ import annotations

import copy
import json

import pytest

from iran_bourse_mcp import derivatives as D

AHRM, SHASTA, FARA = "اهرم", "شستا", "فرابورس"


@pytest.fixture()
def opts(fx):
    return fx("derivatives_option_watch")


@pytest.fixture()
def futs(fx):
    return fx("derivatives_future_watch")


def group(result, index=0):
    return result["groups"][index]


def strike_row(grp, strike):
    return next(s for s in grp["strikes"] if s["strike"] == strike)


def raw_row(rows, symbol):
    return next(r for r in rows if symbol in (r["lVal18AFC_C"], r["lVal18AFC_P"]))


def brute_force_payout(strikes, size):
    """Smallest summed intrinsic value over *every* integer settlement price, to check the 'minimum is at a strike' claim."""
    lo, hi = min(k for k, _, _ in strikes) - 5, max(k for k, _, _ in strikes) + 5
    return min(sum(c * max(s - k, 0) + p * max(k - s, 0) for k, c, p in strikes) * size for s in range(lo, hi + 1))


# ------------------------------------------------------------------------------ fixtures are what they claim to be


def test_fixture_covers_the_edge_cases_the_tests_rely_on(opts, futs):
    assert len(opts) == 26 and len(futs) == 16
    assert {r["lval30_UA"] for r in opts} == {AHRM, SHASTA, FARA}
    assert any(r["remainedDay"] == 0 for r in opts)  # an expiring-today contract
    assert any(r["contractSize"] == 1254 for r in opts)
    # the feed repeats an old price on legs without trades: that is what the module must not show
    stale = [r for r in opts if r["zTotTran_C"] == 0 and r["pClosing_C"] > 0]
    assert stale and all(r["qTotTran5J_C"] == 0 for r in stale)
    assert any(r["pMeDem_P"] == 0 and r["pMeOf_P"] > 0 for r in opts)  # an ask without a bid
    assert any(r["pMeDem_C"] == 0 and r["pMeOf_C"] == 0 for r in opts)  # no quotes at all


# ------------------------------------------------------------------------------ derived values, hand-checked


def test_itm_call_arithmetic(opts):
    """ضهرم8029: strike 50,000, underlying closed at 74,054, the call closed at 25,128 (bid 25,764 / ask 27,999)."""
    leg = strike_row(group(D.option_chain(opts, AHRM)), 50000)["call"]
    assert leg["symbol"] == "ضهرم8029"
    assert (leg["last"], leg["close"]) == (26800, 25128)
    assert leg["close_pct"] == 8.34  # 25,128 against yesterday's 23,193
    assert leg["derived"]["moneyness"] == "ITM"
    assert leg["derived"]["intrinsic"] == 24054  # 74,054 - 50,000
    assert leg["derived"]["time_value"] == 1074  # 25,128 - 24,054
    assert leg["derived"]["breakeven"] == 75128  # 50,000 + 25,128
    assert leg["derived"]["breakeven_pct"] == 1.45  # 75,128 / 74,054 - 1
    assert leg["derived"]["spread_pct"] == 8.31  # (27,999 - 25,764) / 26,881.5
    assert (leg["volume"], leg["trades"], leg["open_interest"]) == (6736, 494, 73697)
    assert leg["value"] == 169260763000  # rial of premium: contracts x size x price


def test_otm_put_and_itm_put_arithmetic(opts):
    row50 = strike_row(group(D.option_chain(opts, AHRM)), 50000)["put"]  # طهرم8029, OTM: nothing but time value
    assert row50["derived"]["moneyness"] == "OTM"
    assert row50["derived"]["intrinsic"] == 0
    assert row50["derived"]["time_value"] == 96
    assert row50["derived"]["breakeven"] == 49904  # 50,000 - 96
    assert row50["derived"]["breakeven_pct"] == -32.61
    assert row50["derived"]["spread_pct"] == 21.23  # 19 / 89.5
    put80 = strike_row(group(D.option_chain(opts, AHRM)), 80000)["put"]  # طهرم8034, ITM
    assert put80["derived"] == {
        "moneyness": "ITM", "intrinsic": 5946, "time_value": 1506, "breakeven": 72548, "breakeven_pct": -2.03, "spread_pct": 4.26,
    }


def test_group_header_spot_and_days(opts):
    g = group(D.option_chain(opts, AHRM))
    assert (g["expiry"], g["expiry_jalali"], g["days_to_expiry"], g["expires_today"], g["contract_size"]) == ("2026-11-18", "1405/08/27", 14, False, 1000)
    assert g["spot"] == {"close": 74054, "last": 74063, "yesterday": 71215, "close_pct": 3.99}
    assert (g["strikes_total"], g["strikes_matched"], g["truncated"]) == (7, 7, False)
    assert g["derived"]["atm_strike"] == 74000  # nearest listed strike to 74,054
    atm = [s for s in g["strikes"] if s.get("atm")]
    assert [s["strike"] for s in atm] == [74000]
    assert strike_row(g, 74000)["strike_vs_spot_pct"] == -0.07
    assert strike_row(g, 50000)["strike_vs_spot_pct"] == -32.48


def test_moneyness_follows_the_exchange_rule_and_flips_between_call_and_put(opts):
    g = group(D.option_chain(opts, AHRM))
    for strike, call, put in [(30000, "ITM", "OTM"), (74000, "ITM", "OTM"), (80000, "OTM", "ITM"), (100000, "OTM", "ITM")]:
        row = strike_row(g, strike)
        assert (row["call"]["derived"]["moneyness"], row["put"]["derived"]["moneyness"]) == (call, put)


def test_strike_equal_to_spot_is_atm_with_zero_intrinsic(opts):
    rows = copy.deepcopy(opts)
    for r in rows:
        if r["lval30_UA"] == AHRM:
            r["pClosing_UA"] = 74000
    row = strike_row(group(D.option_chain(rows, AHRM)), 74000)
    assert row["call"]["derived"]["moneyness"] == "ATM" and row["put"]["derived"]["moneyness"] == "ATM"
    assert row["call"]["derived"]["intrinsic"] == 0 and row["put"]["derived"]["intrinsic"] == 0


def test_time_value_can_be_negative_and_is_not_hidden(opts):
    """شستا 1390 call on its expiry day closed at 1,812 against an intrinsic value of 1,870: shown as it is."""
    leg = strike_row(group(D.option_chain(opts, SHASTA, limit=20)), 1390)["call"]
    assert leg["close"] == 1812 and leg["derived"]["intrinsic"] == 1870
    assert leg["derived"]["time_value"] == -58


# ------------------------------------------------------------------------------ no trades, no quotes, no price


def test_leg_without_trades_has_no_prices_even_though_the_feed_repeats_one(opts):
    """فرابورس 5185 call: 0 trades today although the feed carries an old close and last; bid 660 / ask 2,000 are real quotes."""
    raw = raw_row(opts, "ضفرابورس931")
    assert raw["pClosing_C"] > 0 and raw["zTotTran_C"] == 0
    leg = strike_row(group(D.option_chain(opts, FARA)), 5185)["call"]
    assert (leg["last"], leg["close"], leg["close_pct"]) == (None, None, None)
    assert (leg["bid"], leg["bid_qty"], leg["ask"], leg["ask_qty"]) == (660, 28, 2000, 2)
    assert (leg["volume"], leg["trades"], leg["value"], leg["open_interest"]) == (0, 0, 0, 391)
    assert leg["derived"]["moneyness"] == "ITM"
    assert leg["derived"]["intrinsic"] == 375  # 5,560 - 5,185 needs no trade
    assert leg["derived"]["time_value"] is None and leg["derived"]["breakeven"] is None and leg["derived"]["breakeven_pct"] is None
    assert leg["derived"]["spread_pct"] == 100.75  # quotes exist, so the spread does too


def test_ask_without_bid_has_no_spread(opts):
    put = strike_row(group(D.option_chain(opts, SHASTA, limit=20)), 1390)["put"]  # bid 0, ask 2 (qty 4,000)
    assert put["bid"] is None and put["bid_qty"] is None
    assert (put["ask"], put["ask_qty"]) == (2, 4000)
    assert put["derived"]["spread_pct"] is None


def test_dead_leg_is_collapsed_to_symbol_and_flag(opts):
    """طفرابورس932: no trades, no open interest, no bid, no ask. Intrinsic value still needs only the strike and the spot."""
    row = strike_row(group(D.option_chain(opts, FARA)), 5584)
    assert row["put"] == {"symbol": "طفرابورس932", "active": False, "derived": {"moneyness": "ITM", "intrinsic": 24}}
    assert row["call"]["open_interest"] == 1496  # its call is alive without a trade


def test_contract_size_other_than_1000_is_reported_and_used_in_max_pain(opts):
    g = group(D.option_chain(opts, FARA))
    assert g["contract_size"] == 1254
    # calls only: nothing is owed at or below the lowest strike
    assert g["derived"]["max_pain_estimate"] == {"strike": 4388, "payout_rial": 0}
    assert g["derived"]["max_oi_strike"]["put"] is None


def test_no_underlying_price_means_no_moneyness_and_no_derived_numbers(opts):
    rows = copy.deepcopy(opts)
    for r in rows:
        if r["lval30_UA"] == AHRM:
            r["pClosing_UA"] = r["pDrCotVal_UA"] = 0
    g = group(D.option_chain(rows, AHRM))
    leg = strike_row(g, 50000)["call"]
    assert leg["derived"]["moneyness"] is None and leg["derived"]["intrinsic"] is None and leg["derived"]["time_value"] is None
    assert leg["derived"]["breakeven"] == 75128 and leg["derived"]["breakeven_pct"] is None
    assert g["derived"]["atm_strike"] is None and strike_row(g, 50000)["strike_vs_spot_pct"] is None
    assert not any(s.get("atm") for s in g["strikes"])
    # moneyness filters cannot match anything without a spot
    assert D.option_chain(rows, AHRM, moneyness="itm")["groups"][0]["strikes"] == []


def test_spot_falls_back_to_the_last_price_when_the_underlying_has_no_close(opts):
    rows = copy.deepcopy(opts)
    for r in rows:
        if r["lval30_UA"] == AHRM:
            r["pClosing_UA"] = 0
    g = group(D.option_chain(rows, AHRM))
    assert strike_row(g, 50000)["call"]["derived"]["intrinsic"] == 24063  # 74,063 - 50,000
    assert g["spot"]["close"] is None and g["spot"]["last"] == 74063


# ------------------------------------------------------------------------------ expiry-day contract


def test_expiring_today_is_the_nearest_expiry_and_the_others_are_listed(opts):
    result = D.option_chain(opts, SHASTA, limit=20)
    g = group(result)
    assert (g["expiry"], g["expiry_jalali"], g["days_to_expiry"], g["expires_today"]) == ("2026-11-04", "1405/08/13", 0, True)
    assert result["other_expiries"] == [
        {"expiry": "2026-12-02", "expiry_jalali": "1405/09/11", "days_to_expiry": 28, "strikes": 4, "open_interest": 5098684},
    ]


# ------------------------------------------------------------------------------ group totals, ratios, max pain


def test_group_totals_and_put_call_ratios(opts):
    g = group(D.option_chain(opts, AHRM))
    assert g["totals"] == {
        "call_volume": 1771122, "put_volume": 281328, "call_value": 7885388844000, "put_value": 611557384000,
        "call_open_interest": 1872466, "put_open_interest": 626316,
    }
    assert g["derived"]["put_call_oi_ratio"] == 0.334  # 626,316 / 1,872,466
    assert g["derived"]["put_call_volume_ratio"] == 0.159  # 281,328 / 1,771,122


def test_ratio_is_none_when_the_denominator_is_zero(opts):
    rows = copy.deepcopy(opts)
    for r in rows:
        if r["lval30_UA"] == FARA:
            r["oP_C"] = r["yesterdayOP_C"] = r["qTotTran5J_C"] = 0
    g = group(D.option_chain(rows, FARA))
    assert g["derived"]["put_call_oi_ratio"] is None and g["derived"]["put_call_volume_ratio"] is None
    assert g["derived"]["max_pain_estimate"] is None  # no open interest at all
    assert g["derived"]["max_oi_strike"] == {"call": None, "put": None}


def test_max_oi_strike(opts):
    derived = group(D.option_chain(opts, AHRM))["derived"]
    assert derived["max_oi_strike"] == {"call": {"strike": 80000, "open_interest": 768877}, "put": {"strike": 62000, "open_interest": 347659}}


@pytest.mark.parametrize(("name", "expiry"), [(AHRM, "2026-11-18"), (AHRM, "2027-01-20"), (SHASTA, "2026-11-04"), (SHASTA, "2026-12-02"), (FARA, "2026-12-20")])
def test_max_pain_is_the_global_minimum_of_the_summed_intrinsic_value(opts, name, expiry):
    result = D.option_chain(opts, name, expiry)
    pain = group(result)["derived"]["max_pain_estimate"]
    raw = [r for r in opts if r["lval30_UA"] == name and r["endDate"] == expiry.replace("-", "")]
    book = [(r["strikePrice"], r["oP_C"], r["oP_P"]) for r in raw]
    assert pain["payout_rial"] == brute_force_payout(book, raw[0]["contractSize"])
    assert pain["strike"] in {k for k, _, _ in book}


def test_max_pain_known_values(opts):
    assert group(D.option_chain(opts, AHRM))["derived"]["max_pain_estimate"] == {"strike": 62000, "payout_rial": 3387226000000}
    assert group(D.option_chain(opts, SHASTA))["derived"]["max_pain_estimate"] == {"strike": 3040, "payout_rial": 452221950000}


def test_max_pain_tie_goes_to_the_strike_nearest_the_spot():
    def book(strike, calls, puts):
        return {"strike": strike, "C": {"open_interest": calls}, "P": {"open_interest": puts}}

    # settling at 100: the 100-call pays nothing and the 200-put pays 5 x 100; settling at 200: the 100-call pays 5 x 100. A tie.
    tied = [book(100, 5, 0), book(200, 0, 5)]
    assert D.max_pain_estimate(tied, 1, 190) == {"strike": 200, "payout_rial": 500}
    assert D.max_pain_estimate(tied, 1, 110) == {"strike": 100, "payout_rial": 500}
    assert D.max_pain_estimate(tied, 1000, 110) == {"strike": 100, "payout_rial": 500_000}  # contract size multiplies
    assert D.max_pain_estimate([book(100, 0, 0)], 1, 100) is None


# ------------------------------------------------------------------------------ underlying and expiry arguments


def test_underlying_by_exact_name_fragment_ins_code_and_option_symbol(opts):
    assert D.option_chain(opts, AHRM)["underlying"] == AHRM
    assert D.option_chain(opts, "ستا")["underlying"] == SHASTA  # fragment of شستا
    assert D.option_chain(opts, "17914401175772326")["underlying"] == AHRM  # insCode
    by_symbol = D.option_chain(opts, "ضهرم1038")  # a call on اهرم expiring 2027-01-20: that expiry is the default
    assert by_symbol["underlying"] == AHRM and group(by_symbol)["expiry"] == "2027-01-20"
    assert group(D.option_chain(opts, "ضهرم1038", "nearest"))["expiry"] == "2026-11-18"  # an explicit expiry wins over the symbol
    put_code = raw_row(opts, "طهرم1038")["insCode_P"]
    assert group(D.option_chain(opts, put_code))["expiry"] == "2027-01-20"  # the insCode of a put leg works as well


def test_persian_and_arabic_letters_and_spaces_match_the_same_underlying(opts):
    rows = copy.deepcopy(opts)
    for r in rows:
        if r["lval30_UA"] == AHRM:
            r["lval30_UA"] = "جوانه كوچك"  # the feed uses Arabic ك
    for query in ("جوانه کوچک", "جوانه كوچك", "جوانهکوچک", "کوچک"):
        result = D.option_chain(rows, query)
        assert result["underlying"] == "جوانه کوچک"  # returned with Persian letters


def test_ambiguous_fragment_is_an_error_that_lists_candidates(opts):
    with pytest.raises(ValueError, match=r"'ا' matches 3 underlyings \(اهرم, شستا, فرابورس\)\. Be more specific"):
        D.option_chain(opts, "ا")


def test_unknown_underlying_lists_what_exists(opts):
    with pytest.raises(ValueError) as err:
        D.option_chain(opts, "فولاد")
    message = str(err.value)
    assert "'فولاد'" in message and "اهرم, شستا, فرابورس" in message and "(3)" in message


@pytest.mark.parametrize("expiry", ["2026-11-18", "20261118", "1405/08/27", "14050827", "۱۴۰۵/۰۸/۲۷"])
def test_expiry_accepts_gregorian_and_jalali_dates(opts, expiry):
    assert group(D.option_chain(opts, AHRM, expiry))["expiry"] == "2026-11-18"


def test_expiry_nearest_is_the_default_and_all_gives_every_group(opts):
    assert group(D.option_chain(opts, AHRM, "nearest"))["expiry"] == group(D.option_chain(opts, AHRM))["expiry"] == "2026-11-18"
    result = D.option_chain(opts, AHRM, "all")
    assert [g["expiry"] for g in result["groups"]] == ["2026-11-18", "2027-01-20"]
    assert "other_expiries" not in result


def test_unlisted_expiry_is_an_error_that_lists_the_listed_ones(opts):
    with pytest.raises(ValueError) as err:
        D.option_chain(opts, AHRM, "2026-11-19")
    message = str(err.value)
    assert "اهرم has no option expiring 2026-11-19 (1405/08/28)" in message
    assert "2026-11-18 (1405/08/27)" in message and "2027-01-20 (1405/10/30)" in message


@pytest.mark.parametrize("expiry", ["next month", "1405/13/40", "2026-02-30", "tomorrow"])
def test_unreadable_expiry_says_how_to_write_one(opts, expiry):
    with pytest.raises(ValueError, match=r"is not 'nearest', 'all' or a date\. Use 2026-11-18 or 20261118 \(Gregorian\) or 1405/08/27 \(Jalali\)"):
        D.option_chain(opts, AHRM, expiry)


# ------------------------------------------------------------------------------ filters


def test_option_type_filter_keeps_one_side(opts):
    calls = group(D.option_chain(opts, AHRM, option_type="call"))["strikes"]
    assert calls and all(set(s) >= {"call"} and "put" not in s for s in calls)
    puts = D.option_chain(opts, AHRM, option_type="PUT")  # case-insensitive
    assert all("call" not in s and "put" in s for s in group(puts)["strikes"])
    assert puts["filters"] == {"option_type": "put"}
    for word in ("both", "all", None):
        assert all({"call", "put"} <= set(s) for s in group(D.option_chain(opts, AHRM, option_type=word))["strikes"])
    assert all("call" in s and "put" not in s for s in group(D.option_chain(opts, AHRM, option_type="خرید"))["strikes"])


def test_moneyness_itm_keeps_itm_legs_only(opts):
    g = group(D.option_chain(opts, AHRM, moneyness="itm"))
    for row in g["strikes"]:
        for side in ("call", "put"):
            if side in row:
                assert row[side]["derived"]["moneyness"] == "ITM"
    row74, row80 = strike_row(g, 74000), strike_row(g, 80000)
    assert "call" in row74 and "put" not in row74  # at 74,000 only the call is in the money
    assert "put" in row80 and "call" not in row80


def test_moneyness_otm_and_atm(opts):
    g = group(D.option_chain(opts, AHRM, moneyness="otm", option_type="call"))
    assert [s["strike"] for s in g["strikes"]] == [80000, 100000]
    atm = group(D.option_chain(opts, AHRM, moneyness="ATM"))
    assert [s["strike"] for s in atm["strikes"]] == [74000] and set(atm["strikes"][0]) >= {"call", "put", "atm"}
    # filters never change the group totals
    assert atm["totals"] == group(D.option_chain(opts, AHRM))["totals"]


def test_min_volume_and_min_open_interest_filter_legs(opts):
    g = group(D.option_chain(opts, AHRM, min_volume=100000))
    assert {s["strike"] for s in g["strikes"]} == {62000, 74000, 80000, 100000}
    assert "put" in strike_row(g, 62000) and "put" not in strike_row(g, 74000)  # put 74,000 traded 59,350 only
    assert g["strikes_matched"] == 4 and g["strikes_total"] == 7
    g = group(D.option_chain(opts, AHRM, min_open_interest=500000))
    assert [s["strike"] for s in g["strikes"]] == [80000]
    assert list(g["strikes"][0]) == ["strike", "strike_vs_spot_pct", "call"]  # its put has 53,426 open contracts


def test_strike_window_is_a_percentage_of_the_spot(opts):
    strikes = lambda pct: [s["strike"] for s in group(D.option_chain(opts, AHRM, strike_window_pct=pct))["strikes"]]  # noqa: E731
    assert strikes(10) == [74000, 80000]  # 80,000 is 8.03% above 74,054
    assert strikes(7) == [74000]
    assert strikes(20) == [62000, 74000, 80000]


def test_combined_filters_and_filter_echo(opts):
    result = D.option_chain(opts, AHRM, option_type="call", moneyness="itm", min_volume=1000, min_open_interest=10, strike_window_pct=30)
    assert result["filters"] == {"option_type": "call", "moneyness": "itm", "min_volume": 1000, "min_open_interest": 10, "strike_window_pct": 30}
    assert [s["strike"] for s in group(result)["strikes"]] == [62000, 74000]
    assert "filters" not in D.option_chain(opts, AHRM)


def test_no_match_says_so(opts):
    result = D.option_chain(opts, AHRM, min_volume=10**9)
    assert group(result)["strikes"] == [] and "No strike matches" in result["note"]


# ------------------------------------------------------------------------------ sorting and limits


def test_default_order_is_by_strike(opts):
    assert [s["strike"] for s in group(D.option_chain(opts, AHRM))["strikes"]] == [30000, 38000, 50000, 62000, 74000, 80000, 100000]


def test_sort_by_volume_open_interest_value_and_distance(opts):
    by = lambda key: [s["strike"] for s in group(D.option_chain(opts, AHRM, sort_by=key))["strikes"]]  # noqa: E731
    assert by("volume") == [80000, 74000, 62000, 100000, 50000, 30000, 38000]  # call + put contracts traded
    assert by("open_interest")[:3] == [80000, 62000, 74000]  # 822,303 / 625,433 / 474,876 open contracts
    assert by("value")[:3] == [80000, 74000, 62000]
    assert by("distance") == [74000, 80000, 62000, 50000, 100000, 38000, 30000]


def test_limit_keeps_the_strikes_nearest_the_spot_and_flags_truncation(opts):
    g = group(D.option_chain(opts, AHRM, limit=3))
    assert [s["strike"] for s in g["strikes"]] == [62000, 74000, 80000]  # still shown in strike order
    assert (g["strikes_total"], g["strikes_matched"], g["truncated"]) == (7, 7, True)


def test_limit_with_sort_by_volume_keeps_the_most_traded_strikes(opts):
    g = group(D.option_chain(opts, AHRM, limit=2, sort_by="volume"))
    assert [s["strike"] for s in g["strikes"]] == [80000, 74000]  # shown by volume
    assert g["truncated"] is True


def test_limit_is_shared_between_expiries(opts):
    result = D.option_chain(opts, AHRM, "all", limit=4)
    assert [len(g["strikes"]) for g in result["groups"]] == [2, 2]
    assert [g["truncated"] for g in result["groups"]] == [True, True]


def test_limit_is_clamped(opts):
    assert len(group(D.option_chain(opts, SHASTA, limit=0))["strikes"]) == 1
    assert len(group(D.option_chain(opts, SHASTA, limit=10_000))["strikes"]) == 7  # all there are
    assert D.MAX_STRIKES == 60


def test_default_call_stays_small_even_for_a_long_chain(opts):
    """A chain of 40 strikes still returns at most 15 rows. Characters / 3 is a conservative proxy for tokens (budget: well under 6k)."""
    base = [r for r in opts if r["lval30_UA"] == AHRM and r["endDate"] == "20261118"]
    long_chain = []
    for i in range(40):
        row = copy.deepcopy(base[i % len(base)])
        row["strikePrice"] = 20000 + 2000 * i
        row["lVal18AFC_C"], row["lVal18AFC_P"] = f"ضهرم{9000 + i}", f"طهرم{9000 + i}"
        long_chain.append(row)
    result = D.option_chain(long_chain, AHRM)
    g = group(result)
    assert (len(g["strikes"]), g["strikes_total"], g["strikes_matched"], g["truncated"]) == (D.DEFAULT_STRIKES, 40, 40, True)
    spot = g["spot"]["close"]
    nearest = sorted(range(40), key=lambda i: abs(20000 + 2000 * i - spot))[: D.DEFAULT_STRIKES]
    assert [s["strike"] for s in g["strikes"]] == sorted(20000 + 2000 * i for i in nearest)
    assert len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) < 16_000
    assert len(json.dumps(D.option_chain(long_chain, AHRM, "all", limit=D.MAX_STRIKES), ensure_ascii=False, separators=(",", ":"))) < 45_000


# ------------------------------------------------------------------------------ underlyings summary


def test_summary_mode_lists_underlyings_with_expiries_open_interest_and_volume(opts):
    result = D.option_chain(opts)
    assert result["mode"] == "underlyings" and result["underlyings_total"] == 3 and result["market"] == "all"
    assert result["expiries_listed"] == ["2026-11-04", "2026-11-18", "2026-12-02", "2026-12-20", "2027-01-20"]
    assert [u["underlying"] for u in result["underlyings"]] == [SHASTA, AHRM, FARA]  # most open interest first
    shasta = result["underlyings"][0]
    assert shasta == {
        "underlying": SHASTA, "underlying_ins_code": "2400322364771558", "spot_close": 3260, "expiries": 2,
        "nearest_expiry": "2026-11-04", "nearest_expiry_jalali": "1405/08/13", "days_to_nearest_expiry": 0, "strikes": 11,
        "open_interest": 14295137 + 2653560 + 4643503 + 455181, "put_call_oi_ratio": 0.164,  # (2,653,560 + 455,181) / (14,295,137 + 4,643,503)
        "volume": 47291096 + 20107765 + 5242720 + 494974, "value": 5488034719000 + 1164882897000 + 932720511000 + 60637840000,
    }
    ahrm = result["underlyings"][1]
    assert (ahrm["expiries"], ahrm["strikes"], ahrm["open_interest"]) == (2, 10, 1872466 + 626316 + 421 + 1)


def test_summary_sort_and_limit(opts):
    assert [u["underlying"] for u in D.option_chain(opts, sort_by="name")["underlyings"]] == [AHRM, SHASTA, FARA]
    assert [u["underlying"] for u in D.option_chain(opts, sort_by="volume")["underlyings"]][0] == SHASTA
    assert [u["underlying"] for u in D.option_chain(opts, sort_by="expiry")["underlyings"]][0] == SHASTA  # expires today
    result = D.option_chain(opts, limit=2)
    assert len(result["underlyings"]) == 2 and result["underlyings_total"] == 3


def test_summary_can_be_narrowed_to_an_expiry(opts):
    nearest = D.option_chain(opts, expiry="nearest")["underlyings"]
    assert {u["underlying"]: (u["expiries"], u["nearest_expiry"]) for u in nearest} == {
        SHASTA: (1, "2026-11-04"), AHRM: (1, "2026-11-18"), FARA: (1, "2026-12-20"),
    }
    on_date = D.option_chain(opts, expiry="1405/09/11")  # 2026-12-02: only شستا
    assert [u["underlying"] for u in on_date["underlyings"]] == [SHASTA]
    assert on_date["underlyings"][0]["strikes"] == 4
    missing = D.option_chain(opts, expiry="2026-12-03")
    assert missing["underlyings"] == [] and "No option expires 2026-12-03" in missing["note"] and missing["expiries_listed"]


def test_leg_filters_need_an_underlying(opts):
    for kwargs in ({"option_type": "call"}, {"moneyness": "itm"}, {"min_volume": 5}, {"min_open_interest": 5}, {"strike_window_pct": 10}):
        with pytest.raises(ValueError, match="pass underlying"):
            D.option_chain(opts, **kwargs)


# ------------------------------------------------------------------------------ market, validation and empty input


def test_option_flow_words():
    assert [D.option_flow(w) for w in (None, "", "all", "both")] == [0, 0, 0, 0]
    assert [D.option_flow(w) for w in ("bourse", "Bourse", " BOURSE ")] == [1, 1, 1]
    assert [D.option_flow(w) for w in ("fara", "fara-bourse", "ifb")] == [2, 2, 2]
    with pytest.raises(ValueError, match="market must be 'bourse', 'fara' or omitted"):
        D.option_flow("tehran")


def test_market_label_is_echoed(opts):
    assert D.option_chain(opts, AHRM, market="bourse")["market"] == "bourse"
    assert D.option_chain(opts, market="fara")["market"] == "fara"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"option_type": "straddle"}, "option_type 'straddle' is not recognised. Use 'call', 'put' or 'both'"),
        ({"moneyness": "deep"}, "moneyness 'deep' is not recognised. Use 'itm'"),
        ({"sort_by": "delta"}, "sort_by must be one of strike, distance, volume, open_interest, value."),
        ({"min_volume": -1}, "min_volume and min_open_interest must be 0 or more."),
        ({"strike_window_pct": 0}, "strike_window_pct must be above 0"),
        ({"market": "mars"}, "market must be 'bourse', 'fara' or omitted"),
    ],
)
def test_bad_arguments_are_actionable(opts, kwargs, message):
    with pytest.raises(ValueError, match=message):
        D.option_chain(opts, AHRM, **kwargs)


def test_summary_rejects_chain_only_sort_keys(opts):
    with pytest.raises(ValueError, match="sort_by must be one of open_interest, volume, value, name, expiry."):
        D.option_chain(opts, sort_by="strike")


def test_empty_underlying_string_is_the_summary(opts):
    assert D.option_chain(opts, "  ")["mode"] == "underlyings"


def test_empty_feed_is_a_note_not_a_crash():
    assert D.option_chain([])["underlyings"] == [] and "no options" in D.option_chain([])["note"]
    assert D.option_chain(None, AHRM)["groups"] == []
    assert D.option_chain([{"strikePrice": 0}, "junk", {}], AHRM)["groups"] == []  # rows without strike/expiry/underlying are skipped


# ------------------------------------------------------------------------------ futures


def test_futures_default_order_and_shape(futs):
    result = D.futures_market(futs)
    assert (result["total_contracts"], result["matched"], result["returned"], result["sorted_by"]) == (16, 16, 16, "expiry")
    contracts = result["contracts"]
    assert [c["days_to_expiry"] for c in contracts] == sorted(c["days_to_expiry"] for c in contracts)
    assert contracts[0]["symbol"] == "جستا0508" and contracts[0]["expiry"] == "2026-11-04" and contracts[0]["days_to_expiry"] == 0
    assert all("_end" not in c for c in contracts)
    assert len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) < 14_000


def test_basis_arithmetic_for_a_traded_contract(futs):
    """جهرم0508: closed at 76,571 against اهرم's 74,054, 14 days to expiry."""
    contract = next(c for c in D.futures_market(futs, AHRM)["contracts"] if c["symbol"] == "جهرم0508")
    assert (contract["last"], contract["close"], contract["yesterday"], contract["close_pct"]) == (76571, 76571, 73900, 3.61)
    assert (contract["underlying_close"], contract["days_to_expiry"], contract["expiry_jalali"]) == (74054, 14, "1405/08/27")
    assert contract["derived"] == {"basis": 2517, "basis_pct": 3.4, "annualized_basis_pct_estimate": 88.61}  # 3.3989% x 365 / 14
    assert (contract["volume"], contract["trades"], contract["value"]) == (10, 1, 765710000)  # 10 contracts x 1,000 x 76,571
    assert (contract["bid"], contract["bid_qty"], contract["ask"], contract["ask_qty"]) == (76572, 1223, 77341, 1086)
    assert contract["open_interest"] == 4755 and contract["contract_size"] == 1000


def test_basis_is_none_without_a_trade_today(futs):
    """جستا0508 expires today and did not trade: the feed's close/last are old prices and must not enter a basis."""
    raw = next(r for r in futs if r["lVal18AFC"] == "جستا0508")
    assert raw["pClosing"] > 0 and raw["zTotTran"] == 0
    contract = D.futures_market(futs, SHASTA)["contracts"][0]
    assert contract["symbol"] == "جستا0508"
    assert (contract["last"], contract["close"], contract["close_pct"]) == (None, None, None)
    assert contract["derived"] == {"basis": None, "basis_pct": None, "annualized_basis_pct_estimate": None}
    assert contract["yesterday"] == 3212 and contract["open_interest"] == 375


def test_annualized_basis_is_none_on_the_expiry_day_and_present_the_day_before(futs):
    rows = copy.deepcopy(futs)
    row = next(r for r in rows if r["lVal18AFC"] == "جملت0508")  # traded: close 1,440 vs 1,424
    row["remainedDay"] = 0
    contract = next(c for c in D.futures_market(rows, "وبملت")["contracts"] if c["symbol"] == "جملت0508")
    assert contract["derived"]["basis"] == 16 and contract["derived"]["annualized_basis_pct_estimate"] is None
    row["remainedDay"] = 1
    contract = next(c for c in D.futures_market(rows, "وبملت")["contracts"] if c["symbol"] == "جملت0508")
    assert contract["derived"]["annualized_basis_pct_estimate"] == 410.11  # 1.1236% x 365


def test_open_interest_change_only_when_yesterdays_figure_is_published(futs):
    assert all(c["open_interest_change"] is None for c in D.futures_market(futs)["contracts"])  # the feed sends 0 for all 16
    rows = copy.deepcopy(futs)
    next(r for r in rows if r["lVal18AFC"] == "جهرم0508")["yesterdayMOP"] = 4000
    contract = next(c for c in D.futures_market(rows, AHRM)["contracts"] if c["symbol"] == "جهرم0508")
    assert contract["open_interest"] == 4755 and contract["open_interest_change"] == 755


def test_futures_filter_by_underlying_fragment_and_symbol(futs):
    contracts = D.futures_market(futs, AHRM)
    assert (contracts["matched"], contracts["total_contracts"]) == (3, 16)
    assert [c["expiry"] for c in contracts["contracts"]] == ["2026-11-18", "2026-12-16", "2027-01-20"]
    assert {c["underlying"] for c in D.futures_market(futs, "جشنا0508")["contracts"]} == {"شپنا"}  # the contract's own symbol
    assert D.futures_market(futs, "ستا")["matched"] == 3  # شستا


def test_futures_unknown_underlying_lists_what_exists(futs):
    with pytest.raises(ValueError) as err:
        D.futures_market(futs, "فولاد")
    message = str(err.value)
    assert "No futures contract matches 'فولاد'" in message and "اهرم" in message and "خودرو" in message


def test_futures_sorting_and_limit(futs):
    by_oi = D.futures_market(futs, sort_by="open_interest")["contracts"]
    assert [c["open_interest"] for c in by_oi] == sorted((c["open_interest"] for c in by_oi), reverse=True)
    assert by_oi[0]["symbol"] == "جهرم0508"
    asc = D.futures_market(futs, sort_by="open_interest", descending=False)["contracts"]
    assert asc[0]["open_interest"] == min(c["open_interest"] for c in asc)
    by_basis = D.futures_market(futs, sort_by="basis_pct")["contracts"]
    traded = [c["derived"]["basis_pct"] for c in by_basis if c["derived"]["basis_pct"] is not None]
    assert traded == sorted(traded, reverse=True) and traded[0] == 7.79  # جهرم0510
    assert all(c["derived"]["basis_pct"] is None for c in by_basis[len(traded):])  # contracts without a trade come last
    by_underlying = D.futures_market(futs, sort_by="underlying")["contracts"]
    assert [c["underlying"] for c in by_underlying][:3] == ["اهرم", "اهرم", "اهرم"]
    limited = D.futures_market(futs, limit=4)
    assert (limited["matched"], limited["returned"]) == (16, 4)
    assert D.futures_market(futs, limit=0)["returned"] == 1


def test_futures_bad_sort_and_empty_feed(futs):
    with pytest.raises(ValueError, match="sort_by must be one of expiry, underlying, open_interest, volume, value, basis_pct."):
        D.futures_market(futs, sort_by="delta")
    empty = D.futures_market([])
    assert empty["contracts"] == [] and "no futures" in empty["note"]
    assert D.futures_market(None)["total_contracts"] == 0


def test_every_derived_label_is_in_a_derived_key_or_named_as_an_estimate(opts, futs):
    chain = D.option_chain(opts, AHRM)
    leg = strike_row(group(chain), 50000)["call"]
    assert set(leg["derived"]) == {"moneyness", "intrinsic", "time_value", "breakeven", "breakeven_pct", "spread_pct"}
    assert "max_pain_estimate" in group(chain)["derived"]
    assert "annualized_basis_pct_estimate" in D.futures_market(futs)["contracts"][0]["derived"]


def test_the_raw_rows_are_not_modified(opts, futs):
    """The HTTP layer caches the parsed JSON and hands the same objects to every call."""
    before_opts, before_futs = copy.deepcopy(opts), copy.deepcopy(futs)
    D.option_chain(opts)
    D.option_chain(opts, AHRM, "all", option_type="put", moneyness="itm", sort_by="volume", limit=3)
    D.futures_market(futs, AHRM, sort_by="basis_pct")
    assert opts == before_opts and futs == before_futs


def test_output_does_not_depend_on_the_order_of_the_feed_rows(opts, futs):
    """The exchange returns the same rows in a different order on every call (seen live): everything is sorted explicitly."""
    for call in (
        lambda rows, _: D.option_chain(rows),
        lambda rows, _: D.option_chain(rows, AHRM, "all", limit=40),
        lambda rows, _: D.option_chain(rows, SHASTA, sort_by="volume"),
        lambda _, rows: D.futures_market(rows),
        lambda _, rows: D.futures_market(rows, sort_by="open_interest"),
    ):
        assert call(opts, futs) == call(list(reversed(opts)), list(reversed(futs)))
