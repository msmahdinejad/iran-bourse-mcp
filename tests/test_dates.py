import datetime as dt

import pytest

from iran_bourse_mcp import dates


@pytest.mark.parametrize(
    ("greg", "jalali"),
    [
        ((2026, 11, 3), (1405, 8, 12)),
        ((2026, 10, 28), (1405, 8, 6)),
        ((2026, 3, 21), (1405, 1, 1)),
        ((2025, 3, 21), (1404, 1, 1)),
        ((2024, 3, 20), (1403, 1, 1)),
    ],
)
def test_jalali_known_pairs(greg, jalali):
    assert dates.gregorian_to_jalali(*greg) == jalali
    assert dates.jalali_to_gregorian(*jalali) == greg


def test_every_day_roundtrips_over_a_decade():
    day = dt.date(2018, 1, 1)
    while day < dt.date(2028, 1, 1):
        j = dates.gregorian_to_jalali(day.year, day.month, day.day)
        assert dates.jalali_to_gregorian(*j) == (day.year, day.month, day.day)
        day += dt.timedelta(days=1)


@pytest.mark.parametrize("text", ["2026-11-03", "20261103", "1405/08/12", "14050812", "۱۴۰۵/۰۸/۱۲", "1405-8-12"])
def test_parse_date_accepts_both_calendars(text):
    assert dates.parse_date(text) == 20261103


@pytest.mark.parametrize("bad", ["", "abc", "2026-13-01", "1405/13/40", "2026/02/30", "1405/07/31", "1405/12/30"])
def test_parse_date_rejects_garbage(bad):
    with pytest.raises(dates.DateError):
        dates.parse_date(bad)


def test_formatting():
    assert dates.fmt_date(20261103) == "2026-11-03"
    assert dates.jdate(20261103) == "1405/08/12"
    assert dates.fmt_time(90013) == "09:00:13"
    assert dates.fmt_time(123000) == "12:30:00"
    assert dates.fmt_date(0) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [("09:30", 93000), ("09:30:15", 93015), ("0930", 93000), ("093015", 93015), ("12:30", 123000)],
)
def test_parse_time(text, expected):
    assert dates.parse_time(text) == expected


def test_parse_time_rejects_invalid():
    with pytest.raises(dates.DateError):
        dates.parse_time("25:00")


def test_session_hours():
    # 2026-11-04 is a Wednesday (trading); Thursday and Friday are not.
    assert dates.is_session_hours(dt.datetime(2026, 11, 4, 10, 0))
    assert not dates.is_session_hours(dt.datetime(2026, 11, 4, 13, 0))
    assert not dates.is_session_hours(dt.datetime(2026, 11, 5, 10, 0))
    assert not dates.is_session_hours(dt.datetime(2026, 11, 6, 10, 0))


def test_tehran_offset():
    assert dates.tehran_now(dt.datetime(2026, 11, 4, 6, 30)) == dt.datetime(2026, 11, 4, 10, 0)


# ---- public holidays ------------------------------------------------------------------------

import json  # noqa: E402
from pathlib import Path  # noqa: E402

EXCHANGE = json.loads((Path(__file__).parent / "fixtures" / "exchange_closed_weekdays.json").read_text(encoding="utf-8"))
CLOSED = {dt.date.fromisoformat(d) for d in EXCHANGE["closed_weekdays"]}
FIRST = dt.date.fromisoformat(EXCHANGE["from"])
LAST = dt.date.fromisoformat(EXCHANGE["last_traded"])


def test_session_hours_follow_holidays():
    assert dates.is_session_hours(dt.datetime(2026, 11, 4, 10, 0))
    assert not dates.is_session_hours(dt.datetime(2026, 12, 23, 10, 0))  # Wednesday, 13 Rajab
    assert not dates.is_session_hours(dt.datetime(2026, 3, 22, 10, 0))  # Nowruz


def test_holiday_names_and_trading_days():
    assert dates.holiday_name(dt.date(2026, 4, 1)) == "روز جمهوری اسلامی"
    assert dates.holiday_name(dt.date(2026, 11, 4)) is None
    assert not dates.is_trading_day(dt.date(2026, 12, 23))
    assert dates.is_trading_day(dt.date(2026, 11, 7))  # Saturday
    assert not dates.is_trading_day(dt.date(2026, 11, 5))  # Thursday: weekend, not a holiday
    assert dates.holiday_name(dt.date(2026, 11, 5)) is None


def test_published_table_is_consistent_with_the_solar_rules():
    for day, name in dates.PUBLISHED_HOLIDAYS.items():
        assert name
        assert day.weekday() != 4, f"Fridays are not listed ({day})"
        assert dates.gregorian_to_jalali(day.year, day.month, day.day)[0] in dates.PUBLISHED_YEARS
    for (month, dom), name in dates.SOLAR_HOLIDAYS.items():
        for year in dates.PUBLISHED_YEARS:
            day = dt.date(*dates.jalali_to_gregorian(year, month, dom))
            if day.weekday() != 4:
                assert dates.PUBLISHED_HOLIDAYS.get(day), f"{name} {day} is missing from the published table"


def test_fixed_solar_holidays_match_the_exchange_history():
    """Every fixed holiday that falls on a trading weekday between 1398 and now was a day without any trading."""
    checked = 0
    for jy in range(1398, 1406):
        for (month, dom), name in dates.SOLAR_HOLIDAYS.items():
            day = dt.date(*dates.jalali_to_gregorian(jy, month, dom))
            if FIRST <= day <= LAST and dates.is_trading_weekday(day):
                assert day in CLOSED, f"{name} {day} traded"
                checked += 1
    assert checked > 25


def test_published_holidays_match_the_exchange_history():
    checked = 0
    for day in dates.PUBLISHED_HOLIDAYS:
        if day <= LAST and dates.is_trading_weekday(day):
            assert day in CLOSED, f"{day} {dates.PUBLISHED_HOLIDAYS[day]} traded"
            checked += 1
    assert checked >= 8


def test_closures_without_a_holiday_are_the_exchange_own_decisions():
    """Documented limit: the exchange also closes on days that are not holidays; the calendar cannot predict them."""
    since = dt.date(2026, 3, 21)
    unexplained = sorted(d for d in CLOSED if d >= since and dates.holiday_name(d) is None)
    assert unexplained == [dt.date(2026, 7, 4), dt.date(2026, 7, 5), dt.date(2026, 7, 6)]


def test_next_trading_day_skips_holidays_and_weekends():
    assert dates.next_trading_day(dt.date(2026, 11, 4)) == dt.date(2026, 11, 7)
    assert dates.next_trading_day(dt.date(2026, 12, 22)) == dt.date(2026, 12, 26)  # 13 Rajab is a Wednesday
    assert dates.next_trading_day(dt.date(2026, 3, 20), include_today=True) == dt.date(2026, 3, 25)  # Nowruz 1405 starts Saturday
    # 1406 is not published yet: only the fixed holidays are known (Nowruz Sunday-Wednesday)
    assert dates.next_trading_day(dt.date(2027, 3, 20)) == dt.date(2027, 3, 27)


def test_day_status():
    assert dates.day_status(dt.datetime(2026, 11, 4, 8, 0)) == "before_open"
    assert dates.day_status(dt.datetime(2026, 11, 4, 9, 0)) == "open"
    assert dates.day_status(dt.datetime(2026, 11, 4, 12, 30)) == "open"
    assert dates.day_status(dt.datetime(2026, 11, 4, 12, 31)) == "after_close"
    assert dates.day_status(dt.datetime(2026, 12, 23, 10, 0)) == "holiday"
    assert dates.day_status(dt.datetime(2026, 11, 6, 10, 0)) == "weekend"


def test_next_session():
    before = dates.next_session(dt.datetime(2026, 11, 4, 7, 45))
    assert (before["date"], before["days_ahead"], before["opens_at"], before["closes_at"]) == ("2026-11-04", 0, "09:00", "12:30")
    during = dates.next_session(dt.datetime(2026, 11, 4, 10, 0))
    assert during["date"] == "2026-11-07" and during["weekday"] == "Saturday" and during["jdate"] == "1405/08/16"
    assert during["skipped_holidays"] == []
    eve = dates.next_session(dt.datetime(2026, 3, 31, 17, 0))  # Tuesday before 12 Farvardin (Wednesday)
    assert eve["date"] == "2026-04-04"
    assert [h["date"] for h in eve["skipped_holidays"]] == ["2026-04-01"]
    assert eve["skipped_holidays"][0]["name"] == "روز جمهوری اسلامی"
    on_holiday = dates.next_session(dt.datetime(2026, 12, 23, 8, 0))
    assert on_holiday["date"] == "2026-12-26" and [h["date"] for h in on_holiday["skipped_holidays"]] == ["2026-12-23"]


def test_upcoming_holidays_only_lists_days_the_market_would_have_traded():
    got = dates.upcoming_holidays(dt.date(2026, 11, 5), 3)
    assert [h["date"] for h in got] == ["2026-12-23", "2027-01-06", "2027-01-24"]
    assert got[0]["weekday"] == "Wednesday" and got[0]["jdate"] == "1405/10/02"
    assert all(dates.is_trading_weekday(dt.date.fromisoformat(h["date"])) for h in dates.upcoming_holidays(dt.date(2026, 1, 1), 40))


def test_unpublished_year_falls_back_to_fixed_holidays():
    assert not dates.holidays_published_for(dt.date(2027, 6, 1))
    assert dates.holidays_published_for(dt.date(2026, 11, 5))
    assert dates.holiday_name(dt.date(2027, 4, 1)) == "روز جمهوری اسلامی"  # 12 Farvardin 1406
    assert dates.holiday_name(dt.date(2027, 8, 4)) is None  # religious holidays of 1406 are unknown, never guessed
    assert dates.holiday_name(dt.date(2028, 2, 11)) == "پیروزی انقلاب اسلامی"  # 22 Bahman 1406
