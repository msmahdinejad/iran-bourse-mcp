"""Date/time helpers: Jalali <-> Gregorian, TSETMC ``dEven``/``hEven`` integers, Tehran clock."""

from __future__ import annotations

import datetime as dt
import re

from .text import ascii_digits

TEHRAN_UTC_OFFSET = dt.timedelta(hours=3, minutes=30)  # Iran has no DST since 2022
# Trading days: Saturday..Wednesday. Python: Monday=0 ... Sunday=6
TRADING_WEEKDAYS = {5, 6, 0, 1, 2}
OPEN_TIME = 90000
CLOSE_TIME = 123000


class DateError(ValueError):
    pass


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666
        + (365 * gy)
        + ((gy2 + 3) // 4)
        - ((gy2 + 99) // 100)
        + ((gy2 + 399) // 400)
        + gd
        + g_d_m[gm - 1]
    )
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    jy += 1595
    days = -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd
    days += (jm - 1) * 31 if jm < 7 else ((jm - 7) * 30) + 186
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0
    sal_a = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 13 and gd > sal_a[gm]:
        gd -= sal_a[gm]
        gm += 1
    return gy, gm, gd


_DATE_RE = re.compile(r"^(\d{4})[-/.]?(\d{1,2})[-/.]?(\d{1,2})$")


def parse_date(value: str | int) -> int:
    """Parse a date into a Gregorian ``YYYYMMDD`` integer (TSETMC ``dEven``).

    Accepts Gregorian (``2026-11-03``, ``20261103``) and Jalali (``1405/08/12``,
    ``14050812``, Persian digits). A year below 1700 is treated as Jalali.
    """
    text = ascii_digits(str(value).strip())
    match = _DATE_RE.match(text)
    if not match:
        raise DateError(
            f"Cannot parse date {value!r}. Use YYYY-MM-DD, YYYYMMDD (Gregorian) "
            "or 1405/08/12, 14050812 (Jalali)."
        )
    y, m, d = (int(g) for g in match.groups())
    if y < 1700:
        jalali = (y, m, d)
        if not (1 <= m <= 12 and 1 <= d <= 31):
            raise DateError(f"Invalid Jalali date {value!r}")
        y, m, d = jalali_to_gregorian(y, m, d)
        if gregorian_to_jalali(y, m, d) != jalali:  # e.g. day 31 of a 30-day month, or 30 Esfand in a common year
            raise DateError(f"Invalid Jalali date {value!r}")
    try:
        dt.date(y, m, d)
    except ValueError as exc:
        raise DateError(f"Invalid date {value!r}: {exc}") from exc
    return y * 10000 + m * 100 + d


def to_date(deven: int) -> dt.date:
    return dt.date(deven // 10000, (deven // 100) % 100, deven % 100)


def from_date(day: dt.date) -> int:
    return day.year * 10000 + day.month * 100 + day.day


def fmt_date(deven: int | None) -> str | None:
    if not deven:
        return None
    return to_date(int(deven)).isoformat()


def jdate(deven: int | None) -> str | None:
    """Jalali date string ``1405/08/12`` for a ``YYYYMMDD`` integer."""
    if not deven:
        return None
    d = to_date(int(deven))
    jy, jm, jd = gregorian_to_jalali(d.year, d.month, d.day)
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


def parse_time(value: str | int | None, *, default: int | None = None) -> int | None:
    """Parse ``09:30``, ``09:30:15``, ``0930``, ``93015`` into ``HHMMSS`` (int)."""
    if value is None or value == "":
        return default
    text = ascii_digits(str(value).strip())
    if ":" in text:
        parts = [int(p) for p in text.split(":")]
        while len(parts) < 3:
            parts.append(0)
        h, m, s = parts[:3]
    else:
        digits = text.zfill(6) if len(text) > 4 else text.zfill(4) + "00"
        h, m, s = int(digits[0:2]), int(digits[2:4]), int(digits[4:6])
    if not (0 <= h < 24 and 0 <= m < 60 and 0 <= s < 60):
        raise DateError(f"Invalid time {value!r}")
    return h * 10000 + m * 100 + s


def fmt_time(heven: int | None) -> str | None:
    if heven is None:
        return None
    text = f"{int(heven):06d}"
    return f"{text[0:2]}:{text[2:4]}:{text[4:6]}"


def seconds_of_day(heven: int) -> int:
    return (heven // 10000) * 3600 + ((heven // 100) % 100) * 60 + heven % 100


def tehran_now(now_utc: dt.datetime | None = None) -> dt.datetime:
    base = now_utc or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    if base.tzinfo is not None:
        base = base.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return base + TEHRAN_UTC_OFFSET


def is_trading_weekday(day: dt.date) -> bool:
    return day.weekday() in TRADING_WEEKDAYS


# ---- public holidays -------------------------------------------------------------------------
# The exchange trades Saturday to Wednesday except on official public holidays. Two sources, in order of trust:
#
# * PUBLISHED_HOLIDAYS: the official calendar as published by time.ir (Iran's calendar portal), one entry per
#   holiday that does not fall on a Friday, for each year in PUBLISHED_YEARS. Religious holidays follow the moon
#   and are announced year by year, so they can only come from a published calendar.
# * SOLAR_HOLIDAYS: the holidays fixed in the Solar Hijri calendar, valid for any year, used when a year has not
#   been published into this table yet (religious holidays are then unknown and the output says so).
#
# Neither covers days the exchange closes without a holiday (heat, air pollution, energy saving, emergencies).
# The tests compare both tables with the exchange's own history of non-trading days.
SOLAR_HOLIDAYS: dict[tuple[int, int], str] = {
    (1, 1): "عید نوروز",
    (1, 2): "عید نوروز",
    (1, 3): "عید نوروز",
    (1, 4): "عید نوروز",
    (1, 12): "روز جمهوری اسلامی",
    (1, 13): "روز طبیعت (سیزده‌به‌در)",
    (3, 14): "رحلت امام خمینی",
    (3, 15): "قیام ۱۵ خرداد",
    (11, 22): "پیروزی انقلاب اسلامی",
    (12, 29): "روز ملی شدن صنعت نفت ایران",
}

PUBLISHED_YEARS = frozenset({1405})
PUBLISHED_HOLIDAYS: dict[dt.date, str] = {
    dt.date(2026, 3, 21): "عید نوروز / عید سعید فطر",
    dt.date(2026, 3, 22): "عید نوروز / عید سعید فطر",
    dt.date(2026, 3, 23): "عید نوروز",
    dt.date(2026, 3, 24): "عید نوروز",
    dt.date(2026, 4, 1): "روز جمهوری اسلامی",
    dt.date(2026, 4, 2): "روز طبیعت (سیزده‌به‌در)",
    dt.date(2026, 4, 14): "شهادت امام جعفر صادق (ع)",
    dt.date(2026, 5, 27): "عید سعید قربان",
    dt.date(2026, 6, 4): "رحلت امام خمینی / عید سعید غدیر خم",
    dt.date(2026, 6, 24): "تاسوعای حسینی",
    dt.date(2026, 6, 25): "عاشورای حسینی",
    dt.date(2026, 8, 4): "اربعین حسینی",
    dt.date(2026, 8, 12): "رحلت پیامبر اکرم (ص) و شهادت امام حسن مجتبی (ع)",
    dt.date(2026, 8, 13): "شهادت امام رضا (ع)",
    dt.date(2026, 8, 30): "میلاد پیامبر اکرم (ص) و امام جعفر صادق (ع)",
    dt.date(2026, 12, 23): "ولادت امام علی (ع) و روز پدر",
    dt.date(2027, 1, 6): "مبعث پیامبر اکرم (ص)",
    dt.date(2027, 1, 24): "ولادت حضرت قائم (عج) و نیمه شعبان",
    dt.date(2027, 2, 11): "پیروزی انقلاب اسلامی",
    dt.date(2027, 2, 28): "شهادت امام علی (ع)",
    dt.date(2027, 3, 10): "عید سعید فطر",
    dt.date(2027, 3, 11): "عید سعید فطر",
    dt.date(2027, 3, 20): "روز ملی شدن صنعت نفت ایران",
}
HOLIDAY_SOURCE = "time.ir official calendar of 1405, read 2026-11-05"


def holiday_name(day: dt.date) -> str | None:
    """Persian name of the official public holiday on ``day``, or ``None``.

    Years in ``PUBLISHED_YEARS`` use the published calendar (Fridays are not listed in it); other years only know
    the fixed Solar Hijri holidays.
    """
    jy, jm, jd = gregorian_to_jalali(day.year, day.month, day.day)
    if jy in PUBLISHED_YEARS:
        return PUBLISHED_HOLIDAYS.get(day)
    return SOLAR_HOLIDAYS.get((jm, jd))


def holidays_published_for(day: dt.date) -> bool:
    """True when the whole Jalali year of ``day`` is in the published table (religious holidays included)."""
    return gregorian_to_jalali(day.year, day.month, day.day)[0] in PUBLISHED_YEARS


def is_trading_day(day: dt.date) -> bool:
    """Saturday to Wednesday and not an official public holiday (exceptional closures are not predictable)."""
    return is_trading_weekday(day) and holiday_name(day) is None


def next_trading_day(day: dt.date, *, include_today: bool = False) -> dt.date:
    cursor = day if include_today else day + dt.timedelta(days=1)
    for _ in range(400):
        if is_trading_day(cursor):
            return cursor
        cursor += dt.timedelta(days=1)
    raise DateError(f"No trading day found after {day}")


def upcoming_holidays(day: dt.date, count: int = 3, horizon_days: int = 400) -> list[dict]:
    """The next ``count`` public holidays that close the market (Saturday to Wednesday), after ``day``."""
    found: list[dict] = []
    for step in range(1, horizon_days + 1):
        cursor = day + dt.timedelta(days=step)
        name = holiday_name(cursor) if is_trading_weekday(cursor) else None
        if name:
            found.append(_day_entry(cursor, name))
            if len(found) >= count:
                break
    return found


def _day_entry(day: dt.date, name: str | None = None) -> dict:
    entry = {"date": day.isoformat(), "jdate": jdate(from_date(day)), "weekday": day.strftime("%A")}
    if name is not None:
        entry["name"] = name
    return entry


def day_status(now_tehran: dt.datetime) -> str:
    """``open``, ``before_open``, ``after_close`` (trading day), ``holiday`` (weekday closure) or ``weekend``."""
    day = now_tehran.date()
    if not is_trading_weekday(day):
        return "weekend"
    if holiday_name(day):
        return "holiday"
    hhmmss = now_tehran.hour * 10000 + now_tehran.minute * 100 + now_tehran.second
    if hhmmss < OPEN_TIME:
        return "before_open"
    return "open" if hhmmss <= CLOSE_TIME else "after_close"


def next_session(now_tehran: dt.datetime) -> dict:
    """The next time the market is expected to open: today if it has not opened yet, otherwise the next trading day.

    ``skipped_holidays`` lists the public holidays that fall between now and that day, so a long closure explains itself.
    """
    today = now_tehran.date()
    status = day_status(now_tehran)
    day = today if status == "before_open" else next_trading_day(today)
    skipped = [
        _day_entry(today + dt.timedelta(days=step), holiday_name(today + dt.timedelta(days=step)))
        for step in range(0, (day - today).days)
        if is_trading_weekday(today + dt.timedelta(days=step)) and holiday_name(today + dt.timedelta(days=step))
    ]
    return {
        **_day_entry(day),
        "opens_at": fmt_time(OPEN_TIME)[:5],
        "closes_at": fmt_time(CLOSE_TIME)[:5],
        "days_ahead": (day - today).days,
        "skipped_holidays": skipped,
    }


def is_session_hours(now_tehran: dt.datetime) -> bool:
    return day_status(now_tehran) == "open"
