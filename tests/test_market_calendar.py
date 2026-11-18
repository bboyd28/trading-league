from datetime import date, datetime

import pytest

from core.market_calendar import (
    EASTERN,
    holidays,
    is_trading_day,
    closing_prices_settling,
    last_completed_session,
    market_in_session,
    previous_trading_day,
    trading_days_between,
    trading_window_open,
)


def eastern(year, month, day, hour=12, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=EASTERN)


def test_2026_holidays():
    assert holidays(2026) == {
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),   # July 4 is a Saturday, observed Friday
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
    }


def test_new_year_on_saturday_is_not_observed():
    # Jan 1, 2022 was a Saturday. NYSE stayed open Dec 31, 2021.
    assert is_trading_day(date(2021, 12, 31))
    assert date(2022, 1, 1) not in holidays(2022)


def test_weekends_and_holidays_are_closed():
    assert not is_trading_day(date(2026, 11, 14))   # Saturday
    assert not is_trading_day(date(2026, 11, 26))   # Thanksgiving
    assert is_trading_day(date(2026, 11, 16))       # Monday


def test_previous_trading_day_skips_weekend_and_holiday():
    assert previous_trading_day(date(2026, 11, 16)) == date(2026, 11, 13)
    assert previous_trading_day(date(2026, 11, 27)) == date(2026, 11, 25)


def test_trading_days_between_is_inclusive():
    assert trading_days_between(date(2026, 11, 12), date(2026, 11, 17)) == [
        date(2026, 11, 12),
        date(2026, 11, 13),
        date(2026, 11, 16),
        date(2026, 11, 17),
    ]


@pytest.mark.parametrize("now, expected", [
    (eastern(2026, 11, 16, 10, 0), date(2026, 11, 13)),   # mid-session
    (eastern(2026, 11, 16, 16, 5), date(2026, 11, 13)),   # close not settled yet
    (eastern(2026, 11, 16, 16, 15), date(2026, 11, 16)),
    (eastern(2026, 11, 14, 12, 0), date(2026, 11, 13)),   # Saturday
    (eastern(2026, 11, 16, 8, 0), date(2026, 11, 13)),    # before the open
])
def test_last_completed_session(now, expected):
    assert last_completed_session(now) == expected


@pytest.mark.parametrize("now, open_for_orders", [
    (eastern(2026, 11, 16, 9, 29), True),
    (eastern(2026, 11, 16, 9, 30), False),
    (eastern(2026, 11, 16, 16, 14), False),
    (eastern(2026, 11, 16, 16, 15), True),
    (eastern(2026, 11, 14, 11, 0), True),                 # Saturday
    (eastern(2026, 11, 26, 11, 0), True),                 # Thanksgiving
])
def test_trading_window(now, open_for_orders):
    assert trading_window_open(now) is open_for_orders


@pytest.mark.parametrize("now, in_session, settling", [
    (eastern(2026, 11, 16, 9, 29), False, False),
    (eastern(2026, 11, 16, 9, 30), True, False),
    (eastern(2026, 11, 16, 15, 59), True, False),
    (eastern(2026, 11, 16, 16, 0), False, True),
    (eastern(2026, 11, 16, 16, 14), False, True),
    (eastern(2026, 11, 16, 16, 15), False, False),
    (eastern(2026, 11, 14, 11, 0), False, False),     # Saturday
    (eastern(2026, 11, 26, 16, 5), False, False),     # Thanksgiving
])
def test_session_and_settling_windows(now, in_session, settling):
    assert market_in_session(now) is in_session
    assert closing_prices_settling(now) is settling
