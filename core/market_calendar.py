"""NYSE trading calendar and Eastern-time helpers.

Regular sessions only. Early-close days (1 pm) are treated as normal days.
"""
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
# Yahoo's daily bar isn't final right at 4:00 pm, so wait 15 minutes.
CLOSE_SETTLED = time(16, 15)

WINDOW_MESSAGE = (
    "The market is open. Trading is closed from 9:30 am to 4:15 pm ET "
    "on trading days so nobody can trade on stale prices."
)


SETTLING_MESSAGE = (
    "The closing prices are being finalized. Trading reopens at 4:15 pm ET."
)


def now_eastern():
    return datetime.now(EASTERN)


def today_eastern():
    return now_eastern().date()


def _nth_weekday(year, month, weekday, n):
    """n-th weekday of a month (Monday=0). n=-1 means the last one."""
    if n > 0:
        first = date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return first + timedelta(days=offset + 7 * (n - 1))

    last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _easter(year):
    """Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _observed(holiday):
    """Saturday holidays are observed Friday, Sunday ones Monday."""
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


@lru_cache(maxsize=None)
def holidays(year):
    days = {
        _nth_weekday(year, 1, 0, 3),              # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),              # Presidents Day
        _easter(year) - timedelta(days=2),        # Good Friday
        _nth_weekday(year, 5, 0, -1),             # Memorial Day
        _observed(date(year, 7, 4)),              # Independence Day
        _nth_weekday(year, 9, 0, 1),              # Labor Day
        _nth_weekday(year, 11, 3, 4),             # Thanksgiving
        _observed(date(year, 12, 25)),            # Christmas
    }

    if year >= 2022:
        days.add(_observed(date(year, 6, 19)))    # Juneteenth

    # New Year's Day on a Saturday is not observed on the Friday before.
    new_year = date(year, 1, 1)
    if new_year.weekday() != 5:
        days.add(_observed(new_year))

    return frozenset(days)


def is_trading_day(day):
    return day.weekday() < 5 and day not in holidays(day.year)


def previous_trading_day(day):
    day -= timedelta(days=1)
    while not is_trading_day(day):
        day -= timedelta(days=1)
    return day


def trading_days_between(start, end):
    """Every trading day from start to end, inclusive."""
    days = []
    day = start
    while day <= end:
        if is_trading_day(day):
            days.append(day)
        day += timedelta(days=1)
    return days


def last_completed_session(now=None):
    """Most recent trading day whose closing price is final."""
    now = now or now_eastern()
    today = now.date()

    if is_trading_day(today) and now.time() >= CLOSE_SETTLED:
        return today

    return previous_trading_day(today)


def market_in_session(now=None):
    now = now or now_eastern()
    return is_trading_day(now.date()) and MARKET_OPEN <= now.time() < MARKET_CLOSE


def closing_prices_settling(now=None):
    """The 15 minutes after the close, before the official close is final."""
    now = now or now_eastern()
    return is_trading_day(now.date()) and MARKET_CLOSE <= now.time() < CLOSE_SETTLED


def trading_window_open(now=None):
    """True when orders are allowed under the 'daily_close' model."""
    return not (market_in_session(now) or closing_prices_settling(now))
