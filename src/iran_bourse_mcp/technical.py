"""Technical indicators computed from a daily price series (pure functions, no I/O).

The exchange publishes none of these: they are computed here from its daily prices, by the textbook definitions
below, so an agent can quote them without re-doing the arithmetic.

* Every series function takes plain lists (oldest first) and returns a list of the same length, with ``None``
  where the window is not full yet.
* ``sma`` is the arithmetic mean of the last ``n`` values. ``ema`` uses ``alpha = 2 / (n + 1)`` and is seeded with
  the SMA of its first ``n`` values (the convention of TradingView, StockCharts and TA-Lib).
* ``rsi`` is Wilder's: the first average gain and loss are the means of the first ``n`` changes, later ones are
  smoothed with ``(previous * (n - 1) + current) / n``; ``RSI = 100 - 100 / (1 + avg_gain / avg_loss)``, 100 when there
  was no loss.
* ``macd`` is ``EMA12 - EMA26`` of the close, the signal line the 9-period EMA of that line, the histogram their
  difference.
* ``bollinger`` is the 20-period SMA plus and minus 2 population standard deviations (as Bollinger defines it);
  ``%B = (close - lower) / (upper - lower)``, ``bandwidth = (upper - lower) / middle``.
* ``atr`` is Wilder's average true range: the first value is the mean of the first ``n`` true ranges (the very first
  true range is high - low), then Wilder smoothing.
* ``stochastic`` is the fast oscillator: ``%K = (close - lowest low) / (highest high - lowest low) * 100`` over 14
  sessions, ``%D`` the 3-session SMA of ``%K``.
* ``obv`` adds the session's volume when the close rose, subtracts it when it fell.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence

Series = list[float | None]

SWING_WINDOW = 3  # a swing high is the highest high of the 3 sessions on either side of it
SWING_LOOKBACK = 120  # sessions searched for swing highs and lows
LEVEL_MERGE_PCT = 1.0  # swing levels closer than this (percent) count as one level
MAX_LEVELS = 3
CROSS_LOOKBACK = 20  # crosses older than this many sessions are not reported as recent


def _r(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def sma(values: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(values)
    total = 0.0
    for i, value in enumerate(values):
        total += value
        if i >= n:
            total -= values[i - n]
        if i >= n - 1:
            out[i] = total / n
    return out


def ema(values: Sequence[float | None], n: int) -> Series:
    """EMA of ``values``; leading ``None`` entries are skipped (so the EMA of a series that starts late starts late)."""
    out: Series = [None] * len(values)
    alpha = 2 / (n + 1)
    start = next((i for i, v in enumerate(values) if v is not None), len(values))
    if len(values) - start < n:
        return out
    seed_end = start + n - 1
    out[seed_end] = sum(values[start : seed_end + 1]) / n  # type: ignore[arg-type]
    for i in range(seed_end + 1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]  # type: ignore[operator]
    return out


def rsi(closes: Sequence[float], n: int = 14) -> Series:
    out: Series = [None] * len(closes)
    if len(closes) <= n:
        return out
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gain = sum(max(c, 0.0) for c in changes[:n]) / n
    loss = sum(max(-c, 0.0) for c in changes[:n]) / n

    def value(g: float, lo: float) -> float:
        return 100.0 if lo == 0 else 100 - 100 / (1 + g / lo)

    out[n] = value(gain, loss)
    for i in range(n + 1, len(closes)):
        change = changes[i - 1]
        gain = (gain * (n - 1) + max(change, 0.0)) / n
        loss = (loss * (n - 1) + max(-change, 0.0)) / n
        out[i] = value(gain, loss)
    return out


def macd(closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[Series, Series, Series]:
    fast_ema, slow_ema = ema(closes, fast), ema(closes, slow)
    line: Series = [f - s if f is not None and s is not None else None for f, s in zip(fast_ema, slow_ema, strict=True)]
    sig = ema(line, signal)
    hist: Series = [m - s if m is not None and s is not None else None for m, s in zip(line, sig, strict=True)]
    return line, sig, hist


def bollinger(closes: Sequence[float], n: int = 20, k: float = 2.0) -> dict[str, Series]:
    middle = sma(closes, n)
    upper: Series = [None] * len(closes)
    lower: Series = [None] * len(closes)
    percent_b: Series = [None] * len(closes)
    bandwidth: Series = [None] * len(closes)
    for i, mid in enumerate(middle):
        if mid is None:
            continue
        window = closes[i - n + 1 : i + 1]
        sd = math.sqrt(sum((x - mid) ** 2 for x in window) / n)
        upper[i], lower[i] = mid + k * sd, mid - k * sd
        width = upper[i] - lower[i]  # type: ignore[operator]
        percent_b[i] = (closes[i] - lower[i]) / width if width else None  # type: ignore[operator]
        bandwidth[i] = width / mid if mid else None
    return {"middle": middle, "upper": upper, "lower": lower, "percent_b": percent_b, "bandwidth": bandwidth}


def true_range(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> list[float]:
    out = []
    for i, (high, low) in enumerate(zip(highs, lows, strict=True)):
        if i == 0:
            out.append(high - low)
        else:
            prev = closes[i - 1]
            out.append(max(high - low, abs(high - prev), abs(low - prev)))
    return out


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], n: int = 14) -> Series:
    tr = true_range(highs, lows, closes)
    out: Series = [None] * len(tr)
    if len(tr) < n:
        return out
    out[n - 1] = sum(tr[:n]) / n
    for i in range(n, len(tr)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n  # type: ignore[operator]
    return out


def stochastic(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], n: int = 14, d: int = 3
) -> tuple[Series, Series]:
    k: Series = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        hh, ll = max(highs[i - n + 1 : i + 1]), min(lows[i - n + 1 : i + 1])
        k[i] = (closes[i] - ll) / (hh - ll) * 100 if hh > ll else None  # a locked range has no defined %K
    d_line: Series = [None] * len(closes)
    for i in range(len(closes)):
        window = k[i - d + 1 : i + 1] if i >= d - 1 else []
        if len(window) == d and all(v is not None for v in window):
            d_line[i] = sum(window) / d  # type: ignore[arg-type]
    return k, d_line


def obv(closes: Sequence[float], volumes: Sequence[float]) -> list[float]:
    out: list[float] = []
    total = 0.0
    for i, (close, volume) in enumerate(zip(closes, volumes, strict=True)):
        if i:
            if close > closes[i - 1]:
                total += volume
            elif close < closes[i - 1]:
                total -= volume
        out.append(total)
    return out


def volume_ratio(volumes: Sequence[float], n: int = 20) -> tuple[Series, Series]:
    """Each session's volume over the mean volume of the ``n`` sessions before it (the session itself excluded)."""
    avg: Series = [None] * len(volumes)
    ratio: Series = [None] * len(volumes)
    for i in range(n, len(volumes)):
        mean = sum(volumes[i - n : i]) / n
        avg[i] = mean
        ratio[i] = volumes[i] / mean if mean else None
    return avg, ratio


def swing_points(highs: Sequence[float], lows: Sequence[float], window: int = SWING_WINDOW) -> tuple[list[int], list[int]]:
    """Indexes of swing highs and lows: the extreme of the ``window`` sessions on each side (ties: the first one counts)."""
    tops, bottoms = [], []
    for i in range(window, len(highs) - window):
        left_h, right_h = highs[i - window : i], highs[i + 1 : i + window + 1]
        if highs[i] > max(left_h) and highs[i] >= max(right_h):
            tops.append(i)
        left_l, right_l = lows[i - window : i], lows[i + 1 : i + window + 1]
        if lows[i] < min(left_l) and lows[i] <= min(right_l):
            bottoms.append(i)
    return tops, bottoms


def _levels(points: list[tuple[float, str]], close: float, above: bool) -> list[dict]:
    """The nearest distinct levels on one side of ``close``; ``points`` are (price, date), newest first."""
    side = [(p, d) for p, d in points if (p > close if above else p < close)]
    side.sort(key=lambda item: abs(item[0] - close))
    chosen: list[dict] = []
    for price, date in side:
        if any(abs(price / c["price"] - 1) * 100 < LEVEL_MERGE_PCT for c in chosen):
            continue
        chosen.append({"price": _r(price), "date": date, "distance_pct": _r((price / close - 1) * 100)})
        if len(chosen) == MAX_LEVELS:
            break
    return chosen


def support_resistance(
    dates: Sequence[str],
    highs: Sequence[float],
    lows: Sequence[float],
    close: float,
    lookback: int = SWING_LOOKBACK,
    window: int = SWING_WINDOW,
) -> dict:
    """Up to three resistance levels (swing highs above ``close``) and supports (swing lows below), nearest first."""
    start = max(0, len(highs) - lookback)
    tops, bottoms = swing_points(highs[start:], lows[start:], window)
    top_points = [(highs[start + i], dates[start + i]) for i in reversed(tops)]
    bottom_points = [(lows[start + i], dates[start + i]) for i in reversed(bottoms)]
    return {
        "resistance": _levels(top_points, close, above=True),
        "support": _levels(bottom_points, close, above=False),
    }


def last_cross(a: Series, b: Series, lookback: int = CROSS_LOOKBACK) -> tuple[str, int] | None:
    """The most recent crossing of ``a`` over ``b`` within ``lookback`` sessions: ('above' | 'below', sessions ago)."""
    last = len(a) - 1
    for i in range(last, max(last - lookback, 0), -1):
        now_a, now_b, prev_a, prev_b = a[i], b[i], a[i - 1], b[i - 1]
        if None in (now_a, now_b, prev_a, prev_b):
            return None
        if prev_a <= prev_b and now_a > now_b:  # type: ignore[operator]
            return "above", last - i
        if prev_a >= prev_b and now_a < now_b:  # type: ignore[operator]
            return "below", last - i
    return None


def range_52w(dates: Sequence[str], highs: Sequence[float], lows: Sequence[float], close: float) -> dict:
    """Highest high and lowest low of the sessions in the 365 days up to the latest one."""
    latest = dt.date.fromisoformat(dates[-1])
    first = latest - dt.timedelta(days=365)
    idx = [i for i, d in enumerate(dates) if dt.date.fromisoformat(d) > first]
    hi = max(idx, key=lambda i: (highs[i], i))
    lo = min(idx, key=lambda i: (lows[i], -i))
    return {
        "high": _r(highs[hi]),
        "high_date": dates[hi],
        "low": _r(lows[lo]),
        "low_date": dates[lo],
        "from_high_pct": _r((close / highs[hi] - 1) * 100),
        "from_low_pct": _r((close / lows[lo] - 1) * 100),
        "sessions": len(idx),
        "full_year": dt.date.fromisoformat(dates[0]) <= first,
    }


def _ago(sessions: int) -> str:
    return "in the latest session" if sessions == 0 else f"{sessions} session{'s' if sessions > 1 else ''} ago"


def summarize(latest: dict, crosses: dict) -> list[str]:
    """Plain-language reading of the latest values (thresholds: RSI 70/30, stochastic 80/20, volume 1.5x/0.5x)."""
    out: list[str] = []
    rsi_value = latest["rsi_14"]
    if rsi_value is not None:
        zone = "overbought" if rsi_value >= 70 else "oversold" if rsi_value <= 30 else "neutral"
        out.append(f"RSI {rsi_value:.0f}: {zone}")
    close, sma50, sma200 = latest["close"], latest["sma"]["50"], latest["sma"]["200"]
    if sma50 is not None and sma200 is not None:
        where = {
            (True, True): "price above SMA50 and SMA200",
            (False, False): "price below SMA50 and SMA200",
            (True, False): "price above SMA50, below SMA200",
            (False, True): "price below SMA50, above SMA200",
        }[(close > sma50, close > sma200)]
        out.append(where)
    elif sma50 is not None:
        out.append(f"price {'above' if close > sma50 else 'below'} SMA50 (fewer than 200 sessions: no SMA200)")
    if crosses.get("sma50_sma200"):
        direction, ago = crosses["sma50_sma200"]
        name = "golden cross: SMA50 crossed above SMA200" if direction == "above" else "death cross: SMA50 crossed below SMA200"
        out.append(f"{name} {_ago(ago)}")
    m = latest["macd"]
    if crosses.get("macd_signal"):
        direction, ago = crosses["macd_signal"]
        out.append(f"MACD crossed {direction} signal {_ago(ago)}")
    elif m["macd"] is not None and m["signal"] is not None:
        out.append(f"MACD {'above' if m['macd'] > m['signal'] else 'below'} signal")
    b = latest["bollinger"]["percent_b"]
    if b is not None and b > 1:
        out.append("close above the upper Bollinger band")
    elif b is not None and b < 0:
        out.append("close below the lower Bollinger band")
    k = latest["stochastic"]["k"]
    if k is not None and (k >= 80 or k <= 20):
        out.append(f"stochastic %K {k:.0f}: {'overbought' if k >= 80 else 'oversold'} zone")
    ratio = latest["volume"]["ratio"]
    if ratio is not None and (ratio >= 1.5 or ratio <= 0.5):
        out.append(f"volume {ratio:.1f}x its 20-session average")
    trend = latest["obv"]["trend"]
    if trend in ("rising", "falling"):
        out.append(f"OBV {trend} over 20 sessions")
    r52 = latest["range_52w"]
    if r52["from_high_pct"] is not None and r52["from_high_pct"] >= -3:
        out.append("at the 52-week high" if r52["from_high_pct"] >= 0 else f"{-r52['from_high_pct']:.1f}% below the 52-week high")
    elif r52["from_low_pct"] is not None and r52["from_low_pct"] <= 5:
        out.append(f"{r52['from_low_pct']:.1f}% above the 52-week low")
    return out


MIN_SESSIONS = 2


def compute(rows: Sequence[dict], days: int = 5) -> dict:
    """Every indicator for a daily series (ascending, one dict per traded session with date/close/high/low/volume).

    Returns ``latest`` values, the newest ``days`` rows of each series and a plain-language ``summary``.
    """
    if len(rows) < MIN_SESSIONS:
        raise ValueError(f"at least {MIN_SESSIONS} traded sessions are needed, got {len(rows)}")
    dates = [r["date"] for r in rows]
    closes = [float(r["close"]) for r in rows]
    highs = [float(r["high"]) for r in rows]
    lows = [float(r["low"]) for r in rows]
    volumes = [float(r["volume"] or 0) for r in rows]

    sma20, sma50, sma200 = sma(closes, 20), sma(closes, 50), sma(closes, 200)
    ema12, ema26 = ema(closes, 12), ema(closes, 26)
    rsi14 = rsi(closes, 14)
    macd_line, macd_signal, macd_hist = macd(closes)
    bands = bollinger(closes)
    atr14 = atr(highs, lows, closes, 14)
    stoch_k, stoch_d = stochastic(highs, lows, closes)
    obv_line = obv(closes, volumes)
    obv_sma20 = sma(obv_line, 20)
    vol_avg, vol_ratio = volume_ratio(volumes)

    i = len(rows) - 1
    close = closes[i]
    obv_change = obv_line[i] - obv_line[i - 20] if i >= 20 else None
    if obv_change is None or obv_sma20[i] is None:
        trend = None
    elif obv_change > 0 and obv_line[i] > obv_sma20[i]:
        trend = "rising"
    elif obv_change < 0 and obv_line[i] < obv_sma20[i]:
        trend = "falling"
    else:
        trend = "mixed"

    latest = {
        "date": dates[i],
        "close": _r(close),
        "sma": {"20": _r(sma20[i]), "50": _r(sma50[i]), "200": _r(sma200[i])},
        "ema": {"12": _r(ema12[i]), "26": _r(ema26[i])},
        "rsi_14": _r(rsi14[i]),
        "macd": {"macd": _r(macd_line[i]), "signal": _r(macd_signal[i]), "histogram": _r(macd_hist[i])},
        "bollinger": {
            "upper": _r(bands["upper"][i]),
            "middle": _r(bands["middle"][i]),
            "lower": _r(bands["lower"][i]),
            "percent_b": _r(bands["percent_b"][i], 3),
            "bandwidth_pct": _r(bands["bandwidth"][i] * 100 if bands["bandwidth"][i] is not None else None),
        },
        "atr_14": {"value": _r(atr14[i]), "pct_of_close": _r(atr14[i] / close * 100 if atr14[i] is not None and close else None)},
        "stochastic": {"k": _r(stoch_k[i]), "d": _r(stoch_d[i])},
        "obv": {"value": int(obv_line[i]), "change_20_sessions": None if obv_change is None else int(obv_change), "trend": trend},
        "volume": {"latest": int(volumes[i]), "avg_20": None if vol_avg[i] is None else int(round(vol_avg[i])), "ratio": _r(vol_ratio[i])},
        "range_52w": range_52w(dates, highs, lows, close),
        **support_resistance(dates, highs, lows, close),
    }
    crosses = {
        "sma50_sma200": last_cross(sma50, sma200),
        "macd_signal": last_cross(macd_line, macd_signal),
    }
    days = max(0, min(int(days), len(rows)))
    series = [
        {
            "date": dates[j],
            "close": _r(closes[j]),
            "volume": int(volumes[j]),
            "sma_20": _r(sma20[j]),
            "sma_50": _r(sma50[j]),
            "sma_200": _r(sma200[j]),
            "ema_12": _r(ema12[j]),
            "ema_26": _r(ema26[j]),
            "rsi_14": _r(rsi14[j]),
            "macd": _r(macd_line[j]),
            "macd_signal": _r(macd_signal[j]),
            "macd_histogram": _r(macd_hist[j]),
            "bb_upper": _r(bands["upper"][j]),
            "bb_lower": _r(bands["lower"][j]),
            "bb_percent_b": _r(bands["percent_b"][j], 3),
            "atr_14": _r(atr14[j]),
            "stoch_k": _r(stoch_k[j]),
            "stoch_d": _r(stoch_d[j]),
            "obv": int(obv_line[j]),
            "volume_ratio_20": _r(vol_ratio[j]),
        }
        for j in range(len(rows) - days, len(rows))
    ]
    return {
        "latest": latest,
        "recent_crosses": {
            name: None if value is None else {"direction": value[0], "sessions_ago": value[1]} for name, value in crosses.items()
        },
        "summary": summarize(latest, crosses),
        "series": series,
    }
