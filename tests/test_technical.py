"""Technical indicators against values worked out by hand (the arithmetic is written next to each expectation)."""

from __future__ import annotations

import datetime as dt
import math

import pytest

from iran_bourse_mcp import technical as ta

approx = pytest.approx


def test_sma():
    assert ta.sma([1, 2, 3, 4, 5], 3) == [None, None, 2, 3, 4]
    assert ta.sma([5, 5], 3) == [None, None]


def test_ema_is_seeded_with_the_sma_then_smoothed():
    # n=3 -> alpha 0.5; seed (2+4+6)/3 = 4; then 0.5*8 + 0.5*4 = 6; then 0.5*4 + 0.5*6 = 5
    assert ta.ema([2, 4, 6, 8, 4], 3) == [None, None, 4, 6, 5]
    # leading gaps (a MACD line before the slow EMA exists) are skipped
    assert ta.ema([None, 2, 4, 6, 8], 3) == [None, None, None, 4, 6]
    assert ta.ema([1, 2], 3) == [None, None]


def test_rsi_uses_wilder_smoothing():
    closes = [10, 11, 10, 12, 13, 12]  # changes +1 -1 +2 +1 -1
    out = ta.rsi(closes, 3)
    assert out[:3] == [None, None, None]
    # first averages: gain (1+0+2)/3 = 1, loss (0+1+0)/3 = 1/3 -> RS 3 -> 75
    assert out[3] == approx(75.0)
    # +1: gain (1*2+1)/3 = 1, loss (1/3*2)/3 = 2/9 -> RS 4.5 -> 100 - 100/5.5
    assert out[4] == approx(100 - 100 / 5.5)
    # -1: gain (1*2)/3 = 2/3, loss (2/9*2+1)/3 = 13/27 -> RS 18/13 -> 100 - 1300/31
    assert out[5] == approx(100 - 1300 / 31)
    assert ta.rsi([1, 2, 3, 4, 5], 3)[-1] == 100.0  # no loss at all
    assert ta.rsi([5, 4, 3, 2, 1], 3)[-1] == approx(0.0)
    assert ta.rsi([1, 2, 3], 3) == [None, None, None]


def test_macd_line_signal_and_histogram():
    closes = [1, 3, 2, 5, 4, 6]
    line, signal, hist = ta.macd(closes, fast=2, slow=3, signal=2)
    # EMA2 (alpha 2/3): -, 2, 2, 4, 4, 16/3. EMA3 (alpha 1/2): -, -, 2, 3.5, 3.75, 4.875
    assert line[:2] == [None, None]
    assert line[2:] == approx([0.0, 0.5, 0.25, 16 / 3 - 4.875])
    # signal = EMA2 of the line from its first value: seed (0 + 0.5)/2 = 0.25, then 0.25, then 2/3*0.458333 + 1/3*0.25
    assert signal[:3] == [None, None, None]
    assert signal[3:] == approx([0.25, 0.25, 2 / 3 * (16 / 3 - 4.875) + 0.25 / 3])
    assert hist[3:] == approx([0.25, 0.0, (16 / 3 - 4.875) - (2 / 3 * (16 / 3 - 4.875) + 0.25 / 3)])


def test_bollinger_uses_the_population_standard_deviation():
    out = ta.bollinger([1, 2, 3, 4, 5], n=5, k=2)
    sd = math.sqrt(2)  # variance (4+1+0+1+4)/5 = 2
    assert out["middle"][-1] == 3
    assert out["upper"][-1] == approx(3 + 2 * sd) and out["lower"][-1] == approx(3 - 2 * sd)
    assert out["percent_b"][-1] == approx((5 - (3 - 2 * sd)) / (4 * sd))  # 0.8536
    assert out["bandwidth"][-1] == approx(4 * sd / 3)
    flat = ta.bollinger([7, 7, 7], n=3)
    assert flat["upper"][-1] == flat["lower"][-1] == 7 and flat["percent_b"][-1] is None


def test_atr_true_range_and_wilder_average():
    highs, lows, closes = [10, 12, 11, 13], [8, 9, 9, 10], [9, 11, 10, 12]
    # true ranges: 10-8 = 2; max(3, |12-9|, |9-9|) = 3; max(2, 0, 2) = 2; max(3, 3, 0) = 3
    assert ta.true_range(highs, lows, closes) == [2, 3, 2, 3]
    # first ATR (2+3)/2 = 2.5; then (2.5+2)/2 = 2.25; then (2.25+3)/2 = 2.625
    assert ta.atr(highs, lows, closes, 2) == [None, 2.5, 2.25, 2.625]
    assert ta.true_range([10, 15], [9, 14], [9.5, 14.5])[1] == 5.5  # a gap counts from the previous close


def test_stochastic_k_and_d():
    highs, lows, closes = [5, 6, 7, 8], [1, 2, 3, 4], [3, 5, 4, 8]
    k, d = ta.stochastic(highs, lows, closes, n=3, d=2)
    # day 3: (4 - 1) / (7 - 1) = 50%; day 4: (8 - 2) / (8 - 2) = 100%
    assert k == [None, None, 50.0, 100.0]
    assert d == [None, None, None, 75.0]
    k_flat, d_flat = ta.stochastic([5, 5, 5], [5, 5, 5], [5, 5, 5], n=3, d=1)
    assert k_flat == [None, None, None] and d_flat == [None, None, None]  # a locked range has no %K


def test_obv_and_volume_ratio():
    assert ta.obv([10, 11, 11, 9, 12], [100, 200, 300, 400, 500]) == [0, 200, 200, -200, 300]
    avg, ratio = ta.volume_ratio([10, 20, 30, 60], n=2)
    # the session itself is excluded: (10+20)/2 = 15 -> 30/15; (20+30)/2 = 25 -> 60/25
    assert avg == [None, None, 15, 25] and ratio == [None, None, 2, 2.4]


def test_swing_points_and_support_resistance():
    highs = [10, 11, 15, 12, 11, 10, 9, 10, 13, 12, 11, 10, 11]
    lows = [9, 8, 9, 10, 9, 7, 6, 8, 9, 8, 7, 9, 10]
    tops, bottoms = ta.swing_points(highs, lows, window=2)
    assert tops == [2, 8] and bottoms == [6, 10]
    assert ta.swing_points(highs, lows, window=3) == ([8], [6])  # a wider window needs more sessions on each side
    dates = [(dt.date(2026, 1, 1) + dt.timedelta(days=i)).isoformat() for i in range(len(highs))]
    levels = ta.support_resistance(dates, highs, lows, close=10.5, window=2)
    assert levels["resistance"][0] == {"price": 13, "date": dates[8], "distance_pct": round((13 / 10.5 - 1) * 100, 2)}
    assert [lv["price"] for lv in levels["resistance"]] == [13, 15]  # nearest first
    assert [lv["price"] for lv in levels["support"]] == [7, 6]


def test_nearby_levels_are_merged():
    points = [(100.0, "2026-01-03"), (100.5, "2026-01-02"), (104.0, "2026-01-01")]
    out = ta._levels(points, close=90.0, above=True)
    assert [lv["price"] for lv in out] == [100.0, 104.0]  # 100.5 is within 1% of 100


def test_last_cross():
    a = [1, 2, 3, 4, 5]
    b = [3, 3, 3, 3, 3]
    assert ta.last_cross(a, b) == ("above", 1)  # 3 <= 3, then 4 > 3: one session before the last
    assert ta.last_cross([5, 4, 2], [3, 3, 3]) == ("below", 0)
    assert ta.last_cross([None, 5, 6], [None, 3, 3]) is None
    assert ta.last_cross([1, 2, 3, 4, 5], [3, 3, 3, 3, 3], lookback=1) is None


def test_range_52w_keeps_the_last_365_days():
    dates = ["2025-01-01", "2025-11-10", "2026-03-01", "2026-11-10"]
    highs, lows = [500, 120, 140, 110], [10, 90, 100, 105]
    out = ta.range_52w(dates, highs, lows, close=110)
    assert (out["high"], out["high_date"], out["low"], out["low_date"]) == (140, "2026-03-01", 100, "2026-03-01")
    assert out["from_high_pct"] == round((110 / 140 - 1) * 100, 2) and out["from_low_pct"] == 10.0
    assert out["sessions"] == 2 and out["full_year"] is True


def _series(closes, *, volume=1000, start=dt.date(2025, 1, 1)):
    return [
        {"date": (start + dt.timedelta(days=i)).isoformat(), "close": c, "high": c + 1, "low": c - 1, "volume": volume}
        for i, c in enumerate(closes)
    ]


def test_compute_on_a_steady_uptrend():
    rows = _series([100 + i for i in range(260)])
    out = ta.compute(rows, days=3)
    latest = out["latest"]
    assert latest["close"] == 359 and latest["date"] == rows[-1]["date"]
    assert latest["sma"] == {"20": 349.5, "50": 334.5, "200": 259.5}
    assert latest["rsi_14"] == 100.0
    assert latest["macd"]["macd"] > 0 and latest["atr_14"]["value"] == 2.0  # every true range is |high - prev close| = 2
    assert latest["stochastic"]["k"] == approx(100 * (359 - 345) / (360 - 345), abs=0.01)
    assert latest["obv"]["trend"] == "rising" and latest["volume"]["ratio"] == 1.0
    assert latest["range_52w"]["from_high_pct"] == round((359 / 360 - 1) * 100, 2)
    assert latest["resistance"] == [] and latest["support"] == []  # a straight line has no swing points
    assert [r["date"] for r in out["series"]] == [r["date"] for r in rows[-3:]]
    assert out["series"][-1]["sma_20"] == latest["sma"]["20"] and out["series"][-1]["rsi_14"] == 100.0
    assert out["summary"][:2] == ["RSI 100: overbought", "price above SMA50 and SMA200"]
    assert "stochastic %K 93: overbought zone" in out["summary"]
    assert "OBV rising over 20 sessions" in out["summary"]
    assert ta.compute(rows, days=0)["series"] == []


def test_compute_with_a_short_history_leaves_long_windows_empty():
    out = ta.compute(_series([10, 11, 12, 11, 10, 9, 10, 11, 12, 13]), days=1)
    assert out["latest"]["sma"] == {"20": None, "50": None, "200": None}
    assert out["latest"]["rsi_14"] is None and out["latest"]["macd"]["macd"] is None
    assert out["latest"]["obv"]["trend"] is None and out["latest"]["volume"]["ratio"] is None
    assert out["recent_crosses"] == {"sma50_sma200": None, "macd_signal": None}
    with pytest.raises(ValueError):
        ta.compute(_series([10]))


def test_summary_phrases():
    latest = {
        "close": 90, "rsi_14": 25.4, "sma": {"20": 95, "50": 100, "200": 80},
        "macd": {"macd": -1, "signal": 0.5}, "bollinger": {"percent_b": -0.1}, "stochastic": {"k": 12},
        "volume": {"ratio": 2.34}, "obv": {"trend": "falling"},
        "range_52w": {"from_high_pct": -40, "from_low_pct": 3.2},
    }
    crosses = {"sma50_sma200": ("below", 4), "macd_signal": ("below", 2)}
    assert ta.summarize(latest, crosses) == [
        "RSI 25: oversold",
        "price below SMA50, above SMA200",
        "death cross: SMA50 crossed below SMA200 4 sessions ago",
        "MACD crossed below signal 2 sessions ago",
        "close below the lower Bollinger band",
        "stochastic %K 12: oversold zone",
        "volume 2.3x its 20-session average",
        "OBV falling over 20 sessions",
        "3.2% above the 52-week low",
    ]
    latest.update(rsi_14=72.0, sma={"20": 1, "50": 80, "200": None})
    out = ta.summarize(latest, {"sma50_sma200": None, "macd_signal": ("above", 0)})
    assert out[:3] == ["RSI 72: overbought", "price above SMA50 (fewer than 200 sessions: no SMA200)", "MACD crossed above signal in the latest session"]
