"""Index tools: resolving a name, daily history, today's path and member stocks.

Fixtures are trimmed real responses recorded on 2026-11-04 (index lists, the total index's daily history around Nowruz 2025,
the 2025-06 market closure, the 2020-06-02 slipped-digit row, today's 5-minute path, 12 members and the effect table).
Expected numbers are worked out by hand in the comments.
"""

from __future__ import annotations

import statistics

import pytest

from iran_bourse_mcp import indices as ix

TOTAL = "32097828799138957"
FARA_TOTAL = "43685683301327984"


@pytest.fixture()
def lists(fx):
    return fx("indices_list_flow1")["indexB1"], fx("indices_list_flow2")["indexB1"]


@pytest.fixture()
def total(lists):
    return ix.resolve_index("شاخص کل", *lists)


@pytest.fixture()
def history(fx):
    return fx("indices_history_total")["indexB2"]


def row(deven, close, low=None, high=None):
    return {"dEven": deven, "xNivInuClMresIbs": close, "xNivInuPbMresIbs": low or close, "xNivInuPhMresIbs": high or close}


# ------------------------------------------------------------------------------------ resolving an index


def test_total_index_matches_with_either_letter_variant_and_english_alias(lists):
    for query in ("شاخص کل", "شاخص كل", "  شاخص  کل ", "total", "TEDPIX", TOTAL):
        entry = ix.resolve_index(query, *lists)
        assert entry["ins_code"] == TOTAL and entry["market"] == "bourse" and entry["flow"] == 1
        assert entry["is_market_total"] is True
    assert entry["market_total_change"] == 88137.76  # the list's published indexChange of the total index


@pytest.mark.parametrize(
    ("query", "ins_code", "market"),
    [
        ("شاخص کل (هم وزن)", "67130298613737946", "bourse"),
        ("شاخص کل هم وزن", "67130298613737946", "bourse"),
        ("equal weight", "67130298613737946", "bourse"),
        ("فلزات", "32453344048876642", "bourse"),
        ("فلزات اساسی", "32453344048876642", "bourse"),
        ("27", "32453344048876642", "bourse"),  # the exchange's industry code
        ("بانک", "72002976013856737", "bourse"),
        ("خودرو", "20213770409093165", "bourse"),
        ("fara", FARA_TOTAL, "fara"),
        ("شاخص کل فرابورس", FARA_TOTAL, "fara"),
        ("شاخص آزاد شناور", "49579049405614711", "bourse"),
    ],
)
def test_resolves_names_aliases_and_industry_codes(lists, query, ins_code, market):
    entry = ix.resolve_index(query, *lists)
    assert (entry["ins_code"], entry["market"]) == (ins_code, market)


def test_fara_total_knows_its_own_market_change(lists):
    entry = ix.resolve_index("fara", *lists)
    assert entry["flow"] == 2 and entry["is_market_total"] and entry["market_total_change"] == 294.13


def test_ambiguous_fragment_lists_candidates_instead_of_guessing(lists):
    with pytest.raises(ValueError) as exc:
        ix.resolve_index("هم وزن", *lists)
    message = str(exc.value)
    assert "matches 4 indices" in message
    for ins_code in ("8384385859414435", "67130298613737946", "24779787662870476", "3454456635278563"):
        assert ins_code in message


def test_two_industries_with_the_same_name_are_told_apart_by_code(lists):
    with pytest.raises(ValueError) as exc:
        ix.resolve_index("حمل و نقل", *lists)
    assert "code 35" in str(exc.value) and "code 60" in str(exc.value)
    assert ix.resolve_index("60", *lists)["ins_code"] == "24187097921483699"


def test_a_name_shared_by_both_markets_is_ambiguous(lists):
    with pytest.raises(ValueError, match="bourse.*fara|fara.*bourse"):
        ix.resolve_index("بازار اول", *lists)


@pytest.mark.parametrize(("query", "needle"), [("xyz", "No index matches"), ("", "index is required"), (None, "index is required"), ("99999999999", "not in the index list")])
def test_unknown_or_missing_index_explains_what_to_do(lists, query, needle):
    with pytest.raises(ValueError, match=needle):
        ix.resolve_index(query, *lists)


def test_empty_catalogue_is_reported():
    with pytest.raises(ValueError, match="empty"):
        ix.resolve_index("شاخص کل", [], [])


# ------------------------------------------------------------------------------------ daily history


def test_history_arithmetic_on_a_hand_checkable_series(total):
    # 100 -> 110 (+10%) -> 99 (-10%) -> 108.9 (+10%) -> 119.79 (+10%)
    rows = [row(20260103, 100.0), row(20260104, 110.0), row(20260105, 99.0), row(20260106, 108.9), row(20260107, 119.79)]
    result = ix.shape_index_history(rows, total, granularity="daily")
    assert [r["change_pct"] for r in result["rows"]] == [None, 10.0, -10.0, 10.0, 10.0]
    s = result["summary"]
    assert (s["from"]["value"], s["to"]["value"], s["trading_days"]) == (100.0, 119.79, 5)
    assert s["change_points"] == 19.79 and s["change_pct"] == 19.79  # 119.79 / 100 - 1
    assert s["highest_close"] == {"date": "2026-01-07", "jdate": "1404/10/17", "value": 119.79}
    assert s["lowest_close"]["value"] == 99.0
    # peak 110 on the 4th, trough 99 on the 5th: 99 / 110 - 1 = -10%, later closes pass 110 again
    assert s["max_drawdown"] == {
        "pct": -10.0, "peak": {"date": "2026-01-04", "jdate": "1404/10/14", "value": 110.0},
        "trough": {"date": "2026-01-05", "jdate": "1404/10/15", "value": 99.0}, "recovered": True,
    }
    assert (s["up_days"], s["down_days"], s["flat_days"]) == (3, 1, 0)  # four changes: the first row has nothing before it
    assert s["best_day"]["change_pct"] == 10.0 and s["worst_day"] == {"date": "2026-01-05", "change_pct": -10.0}
    # changes +10, -10, +10, +10 -> mean 5, deviations 5, -15, 5, 5 -> squares 25 + 225 + 25 + 25 = 300; / (4 - 1) = 100; sqrt = 10
    vol = s["volatility_estimate"]
    assert vol["daily_stdev_pct"] == 10.0 and vol["annualized_pct"] == 154.92  # 10 * sqrt(240)
    assert "ESTIMATE" in vol["method"]


def test_first_change_uses_the_close_before_the_range(total):
    rows = [row(20260103, 100.0), row(20260104, 110.0), row(20260105, 99.0)]
    result = ix.shape_index_history(rows, total, from_date="2026-01-04", granularity="daily")
    assert [r["date"] for r in result["rows"]] == ["2026-01-04", "2026-01-05"]
    assert [r["change_pct"] for r in result["rows"]] == [10.0, -10.0]  # 110 / 100 - 1 although 100 is outside the range
    assert result["summary"]["change_pct"] == -10.0  # first row in range (110) to the last (99)
    assert result["summary"]["up_days"] == 1 and result["summary"]["down_days"] == 1


def test_real_range_summary(total, history):
    result = ix.shape_index_history(history, total)
    assert result["granularity"] == "daily" and result["returned"] == result["rows_in_range"] == 62 and not result["truncated"]
    assert result["data_available"] == {"from": "2025-02-02", "to": "2025-05-11", "rows": 62}
    s = result["summary"]
    assert (s["from"]["date"], s["from"]["value"], s["to"]["date"], s["to"]["value"]) == ("2025-02-02", 2776828.5, "2025-05-11", 3091092.3)
    assert s["change_points"] == 314263.8  # 3091092.3 - 2776828.5
    assert s["change_pct"] == 11.32  # 314263.8 / 2776828.5 = 11.317%
    assert (s["highest_close"]["value"], s["highest_close"]["date"]) == (3178649.0, "2025-04-30")
    assert (s["lowest_close"]["value"], s["lowest_close"]["date"]) == (2678885.2, "2025-02-16")
    assert (s["intraday_high"]["value"], s["intraday_low"]["value"]) == (3178649.0, 2678170.0)  # high 3178640 is widened to its close
    assert s["max_drawdown"]["pct"] == -6.35  # 2688503.5 (03-11) / 2870947.6 (03-02) - 1
    assert (s["max_drawdown"]["peak"]["date"], s["max_drawdown"]["trough"]["date"]) == ("2025-03-02", "2025-03-11")
    assert s["max_drawdown"]["recovered"] is True
    assert (s["up_days"], s["down_days"], s["flat_days"], s["trading_days"], s["flat_run_days"]) == (37, 23, 1, 62, 0)
    assert s["best_day"] == {"date": "2025-04-13", "change_pct": 2.21} and s["worst_day"] == {"date": "2025-02-15", "change_pct": -2.08}
    closes = [r["xNivInuClMresIbs"] for r in history]
    moves = [(b / a - 1) * 100 for a, b in zip(closes, closes[1:], strict=False)]
    assert s["volatility_estimate"]["daily_stdev_pct"] == round(statistics.stdev(moves), 2) == 1.16
    assert s["volatility_estimate"]["annualized_pct"] == 17.93  # 1.1576 * sqrt(240)
    assert result["units"] == "index points (not rial)" and result["index"]["ins_code"] == TOTAL


def test_a_gap_over_nowruz_is_one_change_not_filled_in(total, history):
    rows = ix.shape_index_history(history, total)["rows"]
    dates = [r["date"] for r in rows]
    assert dates[dates.index("2025-03-18") + 1] == "2025-03-25"  # no rows for the holiday week
    after = next(r for r in rows if r["date"] == "2025-03-25")
    assert after["jdate"] == "1404/01/05"
    assert after["change_pct"] == 1.13  # 2740716.2 / 2710088.1 - 1 = 1.130%, spanning the week-long closure


def test_dates_accept_gregorian_and_jalali_and_the_bounds_are_inclusive(total, history):
    for start in ("2025-03-25", "20250325", "1404/01/05", "14040105", "۱۴۰۴/۰۱/۰۵"):
        result = ix.shape_index_history(history, total, from_date=start, to_date="2025-04-05")
        assert [r["date"] for r in result["rows"]][:1] == ["2025-03-25"], start
        assert result["rows"][-1]["date"] == "2025-04-05"
    assert result["rows"][0]["change_pct"] == 1.13  # against 03-18, outside the range
    assert [r["date"] for r in result["rows"]] == ["2025-03-25", "2025-03-26", "2025-03-29", "2025-03-30", "2025-04-05"]


def test_weekly_buckets_follow_saturday_weeks(total, history):
    result = ix.shape_index_history(history, total, granularity="weekly")
    assert result["granularity"] == "weekly" and result["returned"] == 15 and result["summary"]["trading_days"] == 62
    week = next(r for r in result["rows"] if r["date"] == "2025-03-30")  # Saturday 03-29 and Sunday 03-30 are the whole week in the data
    assert (week["close"], week["days"], week["low"], week["high"]) == (2810706.8, 2, 2764860.0, 2810706.8)  # high 2810700 widened to the close
    assert week["change_pct"] == 1.61  # 2810706.8 / 2766290.4 (Wed 03-26, the previous week) - 1
    assert sum(r["days"] for r in result["rows"]) == 62


def test_monthly_buckets_are_jalali_months(total, history):
    result = ix.shape_index_history(history, total, granularity="monthly")
    assert [(r["jdate"], r["days"]) for r in result["rows"]] == [("1403/11/30", 11), ("1403/12/28", 20), ("1404/01/31", 16), ("1404/02/21", 15)]
    assert [r["close"] for r in result["rows"]] == [2719338.7, 2710088.1, 3077923.9, 3091092.3]
    assert [r["change_pct"] for r in result["rows"]] == [None, -0.34, 13.57, 0.43]  # e.g. 3077923.9 / 2710088.1 - 1 = 13.57%
    assert result["rows"][1]["low"] == 2678170.0 and result["rows"][1]["high"] == 2875900.0  # extremes inside the month


def test_auto_picks_the_finest_granularity_that_fits_the_limit(total, history):
    picked = {limit: ix.shape_index_history(history, total, limit=limit)["granularity"] for limit in (120, 62, 61, 15, 14, 4, 3, 2, 1)}
    assert picked == {120: "daily", 62: "daily", 61: "weekly", 15: "weekly", 14: "monthly", 4: "monthly", 3: "quarterly", 2: "quarterly", 1: "yearly"}
    narrow = ix.shape_index_history(history, total, limit=1)
    assert narrow["returned"] == 1 and narrow["truncated"] and narrow["rows"][0]["date"] == "2025-05-11"


def test_fixed_granularity_over_the_cap_keeps_the_newest_rows_and_says_where_to_continue(total, history):
    result = ix.shape_index_history(history, total, granularity="daily", limit=10)
    assert [r["date"] for r in result["rows"]][0] == "2025-04-28" and result["returned"] == 10 and result["truncated"]
    assert result["rows_in_range"] == 62 and result["next_to_date"] == "2025-04-27"
    assert result["summary"]["trading_days"] == 62  # the summary covers the whole range, not only the rows shown
    assert "to_date" in result["note"]
    earlier = ix.shape_index_history(history, total, granularity="daily", limit=10, to_date=result["next_to_date"])
    assert earlier["rows"][-1]["date"] == "2025-04-27"


def test_next_to_date_for_resampled_rows_starts_before_the_oldest_bucket(total, history):
    result = ix.shape_index_history(history, total, granularity="weekly", limit=3)
    assert [r["date"] for r in result["rows"]] == ["2025-04-30", "2025-05-07", "2025-05-11"]  # Saturday-start weeks of 04-26, 05-03 and 05-10
    assert result["truncated"] and result["next_to_date"] == "2025-04-25"  # the day before the first row of the oldest bucket shown (Sat 04-26)
    earlier = ix.shape_index_history(history, total, granularity="weekly", limit=3, to_date=result["next_to_date"])
    assert [r["date"] for r in earlier["rows"]] == ["2025-04-09", "2025-04-16", "2025-04-23"]  # no overlap with the rows already seen


def test_limit_is_clamped(total, history):
    assert ix.shape_index_history(history, total, granularity="daily", limit=0)["returned"] == 1
    assert ix.shape_index_history(history, total, granularity="daily", limit=10_000)["returned"] == 62


def test_market_closure_rows_are_flagged_and_left_out_of_the_statistics(total, fx):
    result = ix.shape_index_history(fx("indices_history_closure")["indexB2"], total, granularity="daily")
    flat = [r["date"] for r in result["rows"] if r.get("flat")]
    assert flat == ["2025-06-15", "2025-06-16", "2025-06-18", "2025-06-21", "2025-06-22", "2025-06-23", "2025-06-24", "2025-06-25"]
    s = result["summary"]
    assert (s["trading_days"], s["flat_run_days"]) == (10, 8)  # 18 rows, 8 of them carry the 06-11 close
    assert s["flat_runs"] == [{"from": "2025-06-15", "to": "2025-06-25", "days": 8}]
    assert (s["up_days"], s["down_days"], s["flat_days"]) == (0, 9, 0)  # the flat rows are not counted as "unchanged days"
    reopening = next(r for r in result["rows"] if r["date"] == "2025-06-28")
    assert reopening["change_pct"] == -2.08  # 2922629.1 / 2984605.4 - 1, against the carried close
    assert "8 rows are flat" in result["note"]
    # volatility only from the nine real changes
    real = [3041620.2, 3035752.3, 2989578.7, 2988256.4, 2984605.4, 2922629.1, 2844743.3, 2789093.8, 2731754.0, 2689643.0]
    moves = [(b / a - 1) * 100 for a, b in zip(real, real[1:], strict=False)]
    assert s["volatility_estimate"]["daily_stdev_pct"] == round(statistics.stdev(moves), 2)
    weekly = ix.shape_index_history(fx("indices_history_closure")["indexB2"], total, granularity="weekly")
    assert [(r["date"], r["days"]) for r in weekly["rows"]] == [("2025-06-11", 5), ("2025-06-18", 0), ("2025-06-25", 0), ("2025-07-02", 5)]
    assert weekly["rows"][1]["change_pct"] == 0.0


def test_unrelated_repeated_closes_are_not_flat_runs(total):
    rows = [row(20260103, 100.0, 99.0, 101.0), row(20260104, 100.0, 99.5, 100.5), row(20260105, 101.0, 100.0, 102.0)]
    result = ix.shape_index_history(rows, total, granularity="daily")
    assert result["summary"]["flat_run_days"] == 0 and result["summary"]["flat_days"] == 1
    assert not any(r.get("flat") for r in result["rows"])


def test_published_low_and_high_are_widened_to_the_close_and_dropped_when_garbage(total, fx):
    # real rows around 2020-06-02: the low there is 9,960,190 for a close of 1,028,537.8 (a slipped digit)
    result = ix.shape_index_history(fx("indices_history_slip")["indexB2"], total, granularity="daily")
    by_date = {r["date"]: r for r in result["rows"]}
    slipped = by_date["2020-06-02"]
    assert slipped["low"] is None and slipped["high"] == 1028537.8  # published high 1,028,530 is 7.8 points under the close
    assert by_date["2020-06-01"]["low"] == 971214.0 and by_date["2020-06-01"]["high"] == 988120.6  # high 988,120 widened to the close
    assert result["data_quality"] == {"rows_dropped_no_close": 0, "rows_with_unusable_low_high": 1}
    assert result["summary"]["intraday_low"]["value"] == 939162.0  # the garbage low is not the range's low


def test_rows_without_a_date_or_a_positive_close_are_dropped_and_counted(total):
    rows = [row(20260103, 100.0), {"dEven": 20260104, "xNivInuClMresIbs": 0}, {"xNivInuClMresIbs": 5.0}, row(20260105, 102.0), row(20260105, 103.0)]
    result = ix.shape_index_history(rows, total, granularity="daily")
    assert [(r["date"], r["close"]) for r in result["rows"]] == [("2026-01-03", 100.0), ("2026-01-05", 103.0)]  # a repeated day keeps the later row
    assert result["data_quality"]["rows_dropped_no_close"] == 2


def test_empty_range_explains_what_data_exists(total, history):
    result = ix.shape_index_history(history, total, from_date="2030-01-01")
    assert result["rows"] == [] and result["summary"] is None and result["rows_in_range"] == 0
    assert "2025-02-02 to 2025-05-11" in result["note"]
    nothing = ix.shape_index_history([], total)
    assert nothing["rows"] == [] and nothing["data_available"] is None


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"granularity": "hourly"}, "granularity must be one of"),
        ({"from_date": "2025-04-01", "to_date": "2025-03-01"}, "after to_date"),
        ({"from_date": "yesterday"}, "from_date: Cannot parse date"),
        ({"to_date": "1404/13/40"}, "to_date: "),
        ({"limit": "many"}, "limit must be a whole number"),
    ],
)
def test_bad_arguments_raise_value_errors_an_agent_can_act_on(total, history, kwargs, needle):
    with pytest.raises(ValueError, match=needle):
        ix.shape_index_history(history, total, **kwargs)


# ------------------------------------------------------------------------------------ today's path


def test_intraday_path_of_the_total_index(total, fx):
    rows = fx("indices_intraday_total")["indexB1"]
    result = ix.shape_index_intraday(rows, total, today=20261104)
    assert (result["date"], result["jdate"], result["is_today"]) == ("2026-11-04", "1405/08/13", True)
    s = result["summary"]
    assert (s["raw_points"], s["session_points"]) == (126, 119)  # 08:30-09:00 carry yesterday's close with no range
    assert s["previous_close"] == 7824603.39 and "published" in s["previous_close_source"]
    assert s["value"] == 7912741.15 and s["change_points"] == 88137.76  # 7912741.15 - 7824603.39
    assert s["change_pct"] == 1.1264  # published; 88137.76 / 7824603.39 = 1.1264%
    assert (s["day_high"], s["time_of_high"], s["day_low"], s["time_of_low"]) == (7922838.76, "09:05", 7869318.25, "10:05")
    assert s["last_update"] == "19:23:18"
    assert result["rows"][0] == {"time": "09:05", "value": 7922838.76, "change_pct": 1.2555}
    assert result["rows"][-1] == {"time": "19:23", "value": 7912741.15, "change_pct": 1.1264}
    values = [r["value"] for r in result["rows"]]
    assert all(a != b for a, b in zip(values[:-1], values[1:-1], strict=False))  # runs of equal values collapse to their first row; the last row always stays
    assert result["returned"] == len(result["rows"]) < s["session_points"]
    assert "Every" not in result["note"]


def test_intraday_limit_keeps_first_and_last_and_says_so(total, fx):
    rows = fx("indices_intraday_total")["indexB1"]
    result = ix.shape_index_intraday(rows, total, limit=20)
    assert result["returned"] <= 20 and result["rows"][0]["time"] == "09:05" and result["rows"][-1]["time"] == "19:23"
    assert "respect limit=20" in result["note"]


def test_intraday_of_an_earlier_session_is_labelled(total, fx):
    result = ix.shape_index_intraday(fx("indices_intraday_total")["indexB1"], total, today=20261105)
    assert result["is_today"] is False and "not today (2026-11-05)" in result["note"]
    assert ix.shape_index_intraday(fx("indices_intraday_total")["indexB1"], total)["is_today"] is None


def test_intraday_before_the_first_trade_only_carries_the_previous_close(total):
    carried = [{"dEven": 20261105, "hEven": h, "xDrNivJIdx004": 7912741.15, "xPhNivJIdx004": 0.0, "xPbNivJIdx004": 0.0, "xVarIdxJRfV": 0.0, "last": False} for h in (83000, 83500)]
    result = ix.shape_index_intraday(carried, total)
    assert result["rows"] == [] and result["summary"]["previous_close"] == 7912741.15 and "pre-open" in result["note"]
    assert result["summary"]["day_high"] is None


def test_previous_close_is_derived_when_no_carried_rows_exist(total):
    # value 101.0 at +1.0% -> previous close 101 / 1.01 = 100.0
    rows = [{"dEven": 20261104, "hEven": 90500, "xDrNivJIdx004": 101.0, "xPhNivJIdx004": 101.0, "xPbNivJIdx004": 101.0, "xVarIdxJRfV": 1.0, "last": True}]
    s = ix.shape_index_intraday(rows, total)["summary"]
    assert s["previous_close"] == 100.0 and "derived" in s["previous_close_source"] and s["change_points"] == 1.0


def test_intraday_with_no_points(total):
    result = ix.shape_index_intraday([], total)
    assert result["rows"] == [] and result["summary"] is None and "no intraday points" in result["note"]


# ------------------------------------------------------------------------------------ members


@pytest.fixture()
def members(fx):
    return fx("indices_constituents_total")["indexCompany"]


@pytest.fixture()
def effects(fx):
    return fx("indices_effects_total")["instEffect"]


@pytest.fixture()
def unchecked(total):
    """The total index without a known market move, so the trimmed effect table is used as given."""
    return {**total, "market_total_change": None}


def symbols(result):
    return [r["symbol"] for r in result["rows"]]


def test_members_sorted_by_effect_with_totals(unchecked, members, effects):
    result = ix.shape_index_constituents(members, unchecked, effects=effects, limit=50)
    # biggest positive first; members absent from the effect table (unchanged close or untraded) are 0 and tie on traded value
    assert symbols(result) == ["فملی", "تابان", "فولاد", "خودرو", "آباد", "ثنوسا", "پلاسک", "چاپ", "دابور", "شبندر", "شپنا", "فارس"]
    assert [r["effect_on_total_index"] for r in result["rows"]] == [37692.86, 6922.76, 5331.56, 618.1, 22.06, 0.0, 0.0, 0.0, -160.57, -4939.27, -5184.7, -16790.27]
    t = result["totals"]
    assert (t["members"], t["traded_today"], t["advancers"], t["decliners"], t["unchanged"]) == (12, 11, 5, 4, 2)
    assert t["total_value"] == 58673307720544 and t["total_volume"] == 6630984431
    # 37692.86 + 6922.76 + 5331.56 + 618.1 + 22.06 = 50587.34 up; 160.57 + 4939.27 + 5184.7 + 16790.27 = 27074.81 down
    assert (t["positive_effects"], t["negative_effects"], t["sum_of_effects"]) == (50587.34, -27074.81, 23512.53)
    assert result["sorted_by"] == "effect" and result["index"]["ins_code"] == TOTAL and result["index"]["change"] == 88137.76


def test_default_limit_and_descending_flag(unchecked, members, effects):
    worst_first = ix.shape_index_constituents(members, unchecked, effects=effects, descending=False, limit=2)
    assert symbols(worst_first) == ["فارس", "شپنا"] and worst_first["returned"] == 2
    assert len(ix.shape_index_constituents(members, unchecked, effects=effects)["rows"]) == 12  # default 25 is above the 12 members


def test_member_prices_and_changes(unchecked, members, effects):
    by = {r["symbol"]: r for r in ix.shape_index_constituents(members, unchecked, effects=effects, limit=50)["rows"]}
    melli = by["فملی"]
    assert (melli["close"], melli["last"], melli["yesterday"]) == (29090.0, 29170.0, 28330.0)
    assert melli["close_pct"] == 2.68  # (29090 - 28330) / 28330
    assert melli["last_pct"] == 2.97  # (29170 - 28330) / 28330
    assert (melli["volume"], melli["value"], melli["trades"]) == (943595048, 27446282810280, 50858)
    assert melli["name"].replace("‌", "") == "ملی صنایع مس ایران" and melli["ins_code"] == "35425587644337450"  # letters normalised
    unchanged = by["ثنوسا"]
    assert unchanged["close_pct"] == 0.0 and unchanged["last_pct"] == 2.93 and unchanged["effect_on_total_index"] == 0.0
    untraded = by["چاپ"]  # the feed repeats stale prices for a stock that did not trade
    assert (untraded["close"], untraded["close_pct"], untraded["last"], untraded["last_pct"]) == (None, None, None, None)
    assert untraded["yesterday"] == 11430.0 and untraded["trades"] == 0 and untraded["value"] == 0


@pytest.mark.parametrize(
    ("sort_by", "descending", "expected"),
    [
        ("value", True, ["فملی", "شبندر", "فولاد", "شپنا", "تابان", "فارس"]),
        ("volume", True, ["خودرو", "فولاد", "شبندر", "فملی", "شپنا", "فارس"]),
        ("trades", True, ["فملی", "شبندر", "شپنا", "فولاد", "خودرو", "فارس"]),
        ("change", True, ["آباد", "تابان", "فملی", "فولاد", "خودرو", "ثنوسا"]),
        ("change_pct", False, ["دابور", "شبندر", "فارس", "شپنا", "پلاسک", "ثنوسا"]),
        ("abs_effect", True, ["فملی", "فارس", "تابان", "فولاد", "شپنا", "شبندر"]),
    ],
)
def test_other_sort_orders(unchecked, members, effects, sort_by, descending, expected):
    result = ix.shape_index_constituents(members, unchecked, effects=effects, sort_by=sort_by, descending=descending, limit=6)
    assert symbols(result) == expected


def test_untraded_members_sort_last_by_change(unchecked, members, effects):
    rows = ix.shape_index_constituents(members, unchecked, effects=effects, sort_by="change", limit=50)["rows"]
    assert rows[-1]["symbol"] == "چاپ" and rows[-1]["close_pct"] is None
    assert ix.shape_index_constituents(members, unchecked, effects=effects, sort_by="change", descending=False, limit=50)["rows"][-1]["symbol"] == "چاپ"


def test_market_cap_needs_caps_and_cap_share_is_derived(unchecked, members, effects):
    with pytest.raises(ValueError, match="needs market caps"):
        ix.shape_index_constituents(members, unchecked, effects=effects, sort_by="market_cap")
    caps = {"35425587644337450": 1e15, "25244329144808274": 3e15}  # فملی, فارس
    result = ix.shape_index_constituents(members, unchecked, effects=effects, sort_by="cap", market_caps=caps, limit=3)
    assert symbols(result)[:2] == ["فارس", "فملی"] and result["rows"][0]["market_cap"] == 3_000_000_000_000_000
    assert [r["cap_share_pct"] for r in result["rows"][:2]] == [75.0, 25.0]  # 3e15 / 4e15 and 1e15 / 4e15
    assert result["rows"][2]["market_cap"] is None and result["rows"][2]["cap_share_pct"] is None
    assert "derived" in result["note"] and "no index weights" in result["note"]


def test_an_effect_table_that_does_not_add_up_to_the_index_move_is_withheld(total, members, effects):
    # the trimmed table adds up to 29,930.18 points while the total index moved 88,137.76 (like the previous session's table served in the evening)
    result = ix.shape_index_constituents(members, total, effects=effects)
    check = result["effect_check"]
    assert check["sum_over_all_stocks"] == 29930.18 and check["total_index_change_points"] == 88137.76
    assert check["covers_pct_of_change"] == 33.96  # 29930.18 / 88137.76
    assert check["used"] is False and "withheld" in check["warning"]
    assert check["scope"] == "effect on this index (it is the market's total index)"
    assert all(r["effect_on_total_index"] is None for r in result["rows"]) and "sum_of_effects" not in result["totals"]
    assert result["sorted_by"] == "value" and symbols(result)[:2] == ["فملی", "شبندر"]  # an effect sort falls back to traded value
    assert "sorted by traded value" in result["note"]
    assert ix.shape_index_constituents(members, total, effects=effects, sort_by="change")["sorted_by"] == "change"  # other sorts are untouched


def test_an_effect_table_within_five_percent_of_the_move_is_used(total, members, effects):
    no_level = {**total, "market_total_value": None}  # only the relative rule applies
    close = {**no_level, "market_total_change": 29930.18 * 1.04}  # 4% apart
    result = ix.shape_index_constituents(members, close, effects=effects)
    assert result["effect_check"]["used"] is True and "warning" not in result["effect_check"]
    assert result["rows"][0]["effect_on_total_index"] == 37692.86 and result["sorted_by"] == "effect"
    far = {**no_level, "market_total_change": 29930.18 * 1.06}  # 6% apart
    assert ix.shape_index_constituents(members, far, effects=effects)["effect_check"]["used"] is False
    doubled = [{**e, "instEffectValue": e["instEffectValue"] * 2} for e in effects]
    assert ix.shape_index_constituents(members, {**total, "market_total_change": 29930.18}, effects=doubled)["effect_check"]["used"] is False


def test_a_tiny_index_move_tolerates_small_absolute_differences(total, members):
    table = [{"insCode": "35425587644337450", "instEffectValue": 130.0}]
    entry = {**total, "market_total_change": 100.0, "market_total_value": 7_912_741.15}
    # 130 vs 100 is 30% apart but only 30 points: under 0.05% of the 7.9 million level (3,956 points)
    assert ix.shape_index_constituents(members, entry, effects=table)["effect_check"]["used"] is True
    assert ix.shape_index_constituents(members, {**entry, "market_total_value": 1000.0}, effects=table)["effect_check"]["used"] is False


def test_effects_usable_follows_the_same_check(total, effects):
    assert ix.effects_usable(effects, total) is False  # 29,930.18 against a move of 88,137.76
    assert ix.effects_usable(effects, {**total, "market_total_change": 29930.18}) is True
    assert ix.effects_usable(effects, {**total, "market_total_change": None}) is True  # nothing to compare with
    assert ix.effects_usable(None, total) is False and ix.effects_usable([], total) is False


def test_gateway_figures_make_a_second_effect_source(total, members):
    market_rows = [
        {"ins_code": "35425587644337450", "flow": 1, "effect_on_index": 37692.86}, {"ins_code": "25244329144808274", "flow": 1, "effect_on_index": -16790.27},
        {"ins_code": "111", "flow": 2, "effect_on_index": 5.0}, {"ins_code": "222", "flow": 1, "effect_on_index": None}, {"ins_code": None, "flow": 1, "effect_on_index": 1.0},
    ]
    table = ix.effects_from_market_rows(market_rows, 1)
    assert table == [{"insCode": "35425587644337450", "instEffectValue": 37692.86}, {"insCode": "25244329144808274", "instEffectValue": -16790.27}]
    assert ix.effects_from_market_rows(market_rows, 2) == [{"insCode": "111", "instEffectValue": 5.0}]
    entry = {**total, "market_total_change": 20902.59 * 1.02}  # 37692.86 - 16790.27 = 20902.59, within 5%
    result = ix.shape_index_constituents(members, entry, effects=table, effects_source="TSE gateway (effectonIndex)", limit=2)
    assert result["effect_check"]["source"] == "TSE gateway (effectonIndex)" and result["effect_check"]["used"] is True
    assert [(r["symbol"], r["effect_on_total_index"]) for r in result["rows"]] == [("فملی", 37692.86), ("شبندر", 0.0)]  # members absent from the table are 0; ties go to the larger traded value
    assert "TSE gateway" in result["note"]


def test_sector_index_effect_is_labelled_as_total_index_effect(lists, effects, fx):
    metals = ix.resolve_index("فلزات", *lists)
    result = ix.shape_index_constituents(fx("indices_constituents_total")["indexCompany"][:3], metals, effects=effects)
    assert result["index"]["ins_code"] == "32453344048876642"
    assert result["effect_check"]["scope"] == "effect on the market's total index, not on this index"
    assert all("effect_on_total_index" in r for r in result["rows"])


def test_without_an_effect_table_effects_are_null(total, members):
    result = ix.shape_index_constituents(members, total, effects=None, limit=3)
    assert all(r["effect_on_total_index"] is None for r in result["rows"])
    assert result["effect_check"] is None and "sum_of_effects" not in result["totals"] and "not available" in result["note"]
    assert result["sorted_by"] == "value" and symbols(result) == ["فملی", "شبندر", "فولاد"]
    assert ix.shape_index_constituents(members, total, effects=[])["effect_check"] is None


def test_index_without_members(total):
    result = ix.shape_index_constituents([], total)
    assert result["members"] == 0 and result["rows"] == [] and "no member stocks" in result["note"]
    assert ix.shape_index_constituents(None, total)["members"] == 0


def test_bad_member_arguments(total, members):
    with pytest.raises(ValueError, match="sort_by must be one of"):
        ix.shape_index_constituents(members, total, sort_by="weight")
    with pytest.raises(ValueError, match="limit must be a whole number"):
        ix.shape_index_constituents(members, total, limit="all")
