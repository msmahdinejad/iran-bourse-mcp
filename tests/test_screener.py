"""The filter language: parsing, safety, semantics, history building and the self-documentation."""

from __future__ import annotations

import pytest

from iran_bourse_mcp import screener as S


def ctx(today=None, days=()):
    return S.Ctx(today or {}, days)


def run(text, today=None, days=()):
    return S.compile_expression(text).fn(ctx(today, days), 0)


def ok(text, today=None, days=()):
    return S.passes(S.compile_filter(text), ctx(today, days))


# ----------------------------------------------------------------------------- normalisation


def test_normalise_handles_persian_digits_symbols_and_suffixes():
    assert S.normalise("حجم > ۵B && !x") == "حجم > 5000000000.0  and   not x"
    assert S.normalise("a=1") == "a==1" and S.normalise("a>=1 and b<=2 and c!=3") == "a>=1 and b<=2 and c!=3"
    assert S.normalise("a <> 1") == "a != 1"
    assert S.normalise("x > 2.5k") == "x > 2500.0"
    assert S.normalise("« بانک » == x") == '" بانک " == x'


def test_string_literals_are_never_rewritten():
    assert S.normalise("has(industry, 'a&&b || 5B')") == "has(industry, 'a&&b || 5B')"


# -------------------------------------------------------------------------------------- safety


@pytest.mark.parametrize(
    "text",
    [
        "__import__('os').system('x')",
        "close.real > 1",
        "(lambda: 1)() > 0",
        "[x for x in volume]",
        "close ** 99999999 > 1",
        "open('f') == 1",
        "eval('1') > 0",
        "close[1:3] > 1",
        "'a'.upper() == 'A'",
        "{1: 2}",
        "volume > 1; 2",
        "await x",
        "f'{close}' == 'a'",
    ],
)
def test_dangerous_or_unsupported_syntax_is_rejected(text):
    with pytest.raises(S.FilterError):
        S.compile_expression(text)


def test_limits_on_size_and_depth():
    with pytest.raises(S.FilterError, match="too long"):
        S.compile_expression("volume > 1 and " * 200 + "volume > 1")
    with pytest.raises(S.FilterError):
        S.compile_expression("(" * 500 + "volume" + ")" * 500 + " > 1")
    with pytest.raises(S.FilterError, match="complex"):
        S.compile_expression(" + ".join(["last"] * 210) + " > 1")
    with pytest.raises(S.FilterError, match="empty"):
        S.compile_expression("   ")


# ------------------------------------------------------------------------------------- errors


def test_unknown_names_come_with_suggestions():
    with pytest.raises(S.FilterError, match="Did you mean 'volume'"):
        S.compile_filter("volum > 1")
    with pytest.raises(S.FilterError, match="Did you mean.*avg"):
        S.compile_filter("averge(volume, 3) > 1")


def test_type_mistakes_are_explained():
    with pytest.raises(S.FilterError, match="condition"):
        S.compile_filter("volume")
    with pytest.raises(S.FilterError, match="text with a number"):
        S.compile_filter("symbol > 5")
    with pytest.raises(S.FilterError, match="== / !="):
        S.compile_filter("symbol > 'a'")
    with pytest.raises(S.FilterError, match="Arithmetic needs numbers"):
        S.compile_filter("symbol + 1 > 1")
    with pytest.raises(S.FilterError, match="Only \\+"):
        S.compile_filter("volume ** 2 > 1")
    with pytest.raises(S.FilterError, match="takes 2"):
        S.compile_filter("pct(close) > 1")


def test_history_rules():
    with pytest.raises(S.FilterError, match="no daily history"):
        S.compile_filter("pe[1] > 3")
    with pytest.raises(S.FilterError, match="no daily history"):
        S.compile_filter("avg(pe, 5) > 3")
    with pytest.raises(S.FilterError, match="Nested aggregates"):
        S.compile_filter("avg(avg(volume, 3), 3) > 1")
    with pytest.raises(S.FilterError, match="1 to 60"):
        S.compile_filter("avg(volume, 61) > 1")
    with pytest.raises(S.FilterError, match="1 to 60"):
        S.compile_filter("avg(volume, 0) > 1")
    with pytest.raises(S.FilterError, match="reaches"):
        S.compile_filter("avg(close[30], 40) > 1")
    with pytest.raises(S.FilterError, match="whole number"):
        S.compile_filter("close[x] > 1")


def test_syntax_error_message_is_actionable():
    with pytest.raises(S.FilterError, match="Syntax error.*and / or / not"):
        S.compile_filter("volume > 1 and")


def test_in_lists_need_literals_of_one_kind():
    with pytest.raises(S.FilterError, match="list"):
        S.compile_filter("industry in industry")
    with pytest.raises(S.FilterError, match="same kind"):
        S.compile_filter("industry in (1, 2)")
    with pytest.raises(S.FilterError, match="plain"):
        S.compile_filter("volume in (volume, 2)")


# ----------------------------------------------------------------------------------- semantics


def test_arithmetic_comparison_and_precedence():
    assert ok("volume * 2 + 1 > 20 and volume / 4 == 2.5", {"volume": 10})
    assert ok("1 < volume <= 10", {"volume": 10}) and not ok("1 < volume < 10", {"volume": 10})
    assert run("-volume + 3", {"volume": 10}) == -7
    assert run("volume % 3", {"volume": 10}) == 1 and run("volume // 3", {"volume": 10}) == 3
    assert ok("volume > 5B", {"volume": 6e9}) and not ok("volume > 5B", {"volume": 4e9})


def test_division_by_zero_and_domain_errors_are_unknown_not_crashes():
    assert run("volume / value", {"volume": 1, "value": 0}) is None
    assert run("sqrt(close)", {"close": -4}) is None
    assert run("log(close)", {"close": 0}) is None
    assert not ok("volume / value > 0", {"volume": 1, "value": 0})


def test_three_valued_logic_with_missing_data():
    row = {"pe": None, "volume": 10}
    assert not ok("pe > 5", row)
    assert not ok("not (pe > 5)", row)  # unknown stays unknown, so the row does not match
    assert ok("volume > 5 or pe > 5", row)
    assert not ok("volume > 50 or pe > 5", row)
    assert not ok("volume > 5 and pe > 5", row)
    assert ok("isnull(pe)", row) and ok("coalesce(pe, 7) == 7", row)


def test_booleans_flags_and_constants():
    row = {"at_upper_limit": True, "buy_queue": False}
    assert ok("at_upper_limit", row) and not ok("buy_queue", row) and ok("not buy_queue", row)
    assert ok("at_upper_limit == true and buy_queue == false", row)
    assert ok("pe == null", {"pe": None}) is False  # comparisons with a missing value are unknown


def test_text_comparisons_ignore_persian_arabic_variants():
    row = {"industry": "بانکها و موسسات اعتباری", "symbol": "کیش", "market": "فرابورس"}
    assert ok("symbol == 'كيش'", row)  # Arabic letters in the query
    assert ok("has(industry, 'بانک')", row) and ok("has(industry, 'بانك')", row) and not ok("has(industry, 'خودرو')", row)
    assert ok("startswith(industry, 'بانک')", row)
    assert ok("industry in ('خودرو', 'بانکها و موسسات اعتباری')", row)
    assert ok("market not in ('بورس',)", row)
    assert ok("symbol != 'فولاد'", row)


def test_scalar_functions():
    row = {"close": 110.0, "open": 100.0}
    assert run("pct(close, open)", row) == pytest.approx(10.0)
    assert run("abs(open - close)", row) == 10 and run("round(close / 3, 1)", row) == 36.7
    assert run("min(close, open, 105)", row) == 100 and run("max(close, open, 105)", row) == 110
    assert ok("between(close, 100, 120)", row) and not ok("between(close, 111, 120)", row)
    assert run("iff(close > open, 1, 2)", row) == 1 and run("2 if close < open else 3", row) == 3
    assert run("min(close, pe)", {"close": 5, "pe": None}) == 5  # missing values are skipped


# ---------------------------------------------------------------------------- history windows


DAYS = [  # newest first: yesterday, 2 days ago, 3 days ago
    {"close": 100.0, "high": 104.0, "low": 96.0, "volume": 10.0, "close_pct": 1.0, "open": 98.0, "trades": 5.0},
    {"close": 99.0, "high": 103.0, "low": 95.0, "volume": 20.0, "close_pct": -1.0, "open": 100.0, "trades": 6.0},
    {"close": 100.0, "high": 105.0, "low": 97.0, "volume": 30.0, "close_pct": 2.0, "open": 97.0, "trades": 7.0},
]
TODAY = {"close": 101.0, "volume": 90.0, "close_pct": 1.0}


def test_lag_and_window_functions():
    assert run("close[1]", TODAY, DAYS) == 100 and run("close[2]", TODAY, DAYS) == 99 and run("close[0]", TODAY, DAYS) == 101
    assert run("close[9]", TODAY, DAYS) is None  # beyond the history that exists
    assert run("avg(volume, 3)", TODAY, DAYS) == 20 and run("sum(volume, 2)", TODAY, DAYS) == 30
    assert run("highest(high, 3)", TODAY, DAYS) == 105 and run("lowest(low, 2)", TODAY, DAYS) == 95
    assert run("stdev(volume, 3)", TODAY, DAYS) == pytest.approx(8.1650, abs=1e-3)
    assert run("avg(volume, 10)", TODAY, DAYS) == 20  # averages what exists
    assert ok("volume > 2 * avg(volume, 3)", TODAY, DAYS)  # the classic volume surge
    assert run("ago(close, 2)", TODAY, DAYS) == 99


def test_conditional_windows_evaluate_each_day_in_its_own_context():
    assert run("count(close_pct > 0, 3)", TODAY, DAYS) == 2
    assert run("count(close > open, 3)", TODAY, DAYS) == 2 and run("count(close < open, 3)", TODAY, DAYS) == 1
    assert run("all(close_pct > -5, 3)", TODAY, DAYS) is True and run("all(close_pct > 0, 3)", TODAY, DAYS) is False
    assert run("any(close_pct < 0, 3)", TODAY, DAYS) is True
    # close[1] inside a window looks one more day back: day 1 is 100 vs 99, day 2 is 99 vs 100
    assert run("count(close > close[1], 2)", TODAY, DAYS) == 1
    assert run("count(close < close[1], 2)", TODAY, DAYS) == 1


def test_windows_without_enough_history_cannot_be_satisfied():
    assert run("all(close_pct > -5, 5)", TODAY, DAYS) is False
    assert not ok("all(close_pct > -5, 5)", TODAY, DAYS)
    assert run("avg(volume, 3)", TODAY, ()) is None and not ok("volume > avg(volume, 3)", TODAY, ())


def test_lookback_and_evidence_are_reported_for_the_planner():
    c = S.compile_filter("volume > 2 * avg(volume, 20) and close[5] < close and real_net_value > 0")
    assert c.lookback == 20 and c.uses_flows and "volume" in c.fields
    assert [t for t, _ in c.evidence] == ["avg(volume, 20)", "close[5]"]
    assert S.compile_filter("close > 1").lookback == 0
    assert S.compile_filter("count(close > close[2], 5) > 1").lookback == 7  # 5 days, each looking 2 back


# ----------------------------------------------------------------------------- data builders


def test_build_history_day_and_today():
    day = S.build_history_day({"pClosing": 110.0, "priceYesterday": 100.0, "pDrCotVal": 108.0, "priceFirst": 101.0, "priceMax": 111.0,
                               "priceMin": 99.0, "qTotTran5J": 1000.0, "qTotCap": 105000.0, "zTotTran": 12.0})
    assert day["close_pct"] == pytest.approx(10.0) and day["last_pct"] == pytest.approx(8.0) and day["vwap"] == 105.0
    assert S.build_history_day({"pClosing": 0.0})["close"] is None

    row = {"symbol": "الف", "last": 1030.0, "high": 1030.0, "low": 1000.0, "open": 1010.0, "yesterday": 1000.0, "volume": 10, "value": 1e6,
           "vwap": 1020.0, "price_limits": {"upper": 1030.0, "lower": 970.0}, "best_bid": {"price": 1030.0, "volume": 500, "orders": 7},
           "best_ask": {"price": None, "volume": None, "orders": None}, "at_upper_limit": True, "buy_queue_probable": True}
    flow = {"buy_I_Volume": 600.0, "sell_I_Volume": 200.0, "buy_N_Volume": 100.0, "sell_N_Volume": 500.0, "buy_CountI": 3, "sell_CountI": 4}
    today = S.build_today(row, flow)
    assert today["gap_pct"] == pytest.approx(1.0) and today["range_pct"] == pytest.approx(3.0) and today["from_high_pct"] == 0
    assert today["bid_value"] == 500 * 1030 and today["ask_value"] is None and today["buy_queue"] is True
    assert today["real_net_volume"] == 400 and today["real_net_value"] == 400 * 1020 and today["legal_net_volume"] == -400
    assert today["real_buyer_power"] == pytest.approx((600 / 3) / (200 / 4)) and today["real_buy_share"] == pytest.approx(600 / 700 * 100)
    assert "real_net_volume" not in S.build_today(row)  # no flow row, no flow fields


def test_flow_count_keys_vary_across_endpoints():
    flow = {"buy_I_Volume": 10.0, "sell_I_Volume": 10.0, "buy_I_Count": 2, "sell_I_Count": 5}
    assert S.build_today({"vwap": 1.0}, flow)["real_buy_count"] == 2


def test_adjust_history_restores_continuity_across_a_capital_increase():
    # today's reference price is 500 (a 100% bonus issue halved the price); yesterday closed at 1000.
    days = [
        {"close": 1000.0, "open": 990.0, "high": 1010.0, "low": 980.0, "last": 1000.0, "yesterday": 980.0, "vwap": 995.0, "volume": 1.0},
        {"close": 980.0, "open": 970.0, "high": 985.0, "low": 960.0, "last": 980.0, "yesterday": 960.0, "vwap": 975.0, "volume": 2.0},
    ]
    S.adjust_history(500.0, days)
    assert days[0]["close"] == 500.0 and days[1]["close"] == 490.0 and days[0]["high"] == 505.0
    assert days[0]["volume"] == 1.0  # volumes are not adjusted


def test_adjust_history_ignores_tick_rounding_and_gaps():
    days = [{"close": 1000.0, "yesterday": 990.0, "high": 1000.0}, {}, {"close": 990.0, "yesterday": 980.0, "high": 991.0}]
    S.adjust_history(1000.4, days)  # 0.04% off: rounding, not an event
    assert days[0]["close"] == 1000.0 and days[2]["close"] == 990.0


# ---------------------------------------------------------------------------- presets and docs


@pytest.mark.parametrize("preset", S.PRESETS, ids=lambda p: p.name)
def test_every_preset_compiles_and_evaluates(preset):
    condition, key = S.compile_filter(preset.filter), S.compile_expression(preset.sort)
    assert condition.lookback <= S.MAX_LOOKBACK
    row = S.build_today({"symbol": "x", "last": 100.0, "close": 100.0, "yesterday": 99.0, "high": 100.0, "low": 98.0, "open": 99.0,
                         "volume": 100, "value": 1e10, "price_limits": {}, "best_bid": {}, "best_ask": {}}, {"buy_I_Volume": 5.0})
    context = ctx(row, [dict(DAYS[0])] * condition.lookback)
    S.passes(condition, context)
    key.fn(context, 0)


def test_preset_lookup_suggests_names():
    assert S.preset("Volume-Surge").name == "volume_surge"
    with pytest.raises(S.FilterError, match="volume_surge"):
        S.preset("volume_surg")


def test_reference_topics():
    brief = S.reference()
    assert {"syntax", "fields", "functions", "presets", "examples"} <= set(brief) and brief["fields"]["volume"].startswith("shares")
    assert all(isinstance(f, dict) and "meaning" in f for f in S.reference("fields")["fields"])
    assert "presets" in S.reference("presets") and "filter" in S.reference("presets")["presets"][0]
    assert set(S.reference("all")) >= {"syntax", "fields", "functions", "presets", "examples", "history_fields"}
    with pytest.raises(S.FilterError):
        S.reference("nonsense")


def test_every_example_in_the_reference_compiles():
    for _, expression in S.EXAMPLES:
        S.compile_filter(expression)


def test_tidy_cells():
    assert S.tidy(5.0) == 5 and S.tidy(1.23456789) == 1.2346 and S.tidy(float("nan")) is None and S.tidy("x") == "x" and S.tidy(True) is True
