"""NYSE regular sessions, from the exchange's holiday and early-close rules.

Rules (NYSE, current since 2022, when Juneteenth was added):
- Closed: New Year's Day, Martin Luther King Jr. Day (3rd Monday of January),
  Washington's Birthday (3rd Monday of February), Good Friday, Memorial Day
  (last Monday of May), Juneteenth, Independence Day, Labor Day (1st Monday of
  September), Thanksgiving (4th Thursday of November), Christmas.
- A fixed-date holiday on Saturday is observed the Friday before, on Sunday the
  Monday after. New Year's Day on a Saturday is not observed.
- Early close at 13:00 on July 3, the day after Thanksgiving, and December 24,
  when each is a trading day.
- One-off closures (national days of mourning, storms) are listed by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

EASTERN_ZONE = "America/New_York"
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)
ONE_DAY = timedelta(days=1)
JUNETEENTH_FIRST_YEAR = 2022
SPECIAL_CLOSURES = frozenset({
    date(2025, 1, 9),  # National day of mourning for President Carter
})


@dataclass(frozen=True)
class Session:
    day: date
    open_at: datetime
    close_at: datetime


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def last_weekday(year: int, month: int, weekday: int) -> date:
    following = date(year + month // 12, month % 12 + 1, 1)
    last = following - ONE_DAY
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm (Meeus, Jones, Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def observed(holiday: date) -> date:
    if holiday.weekday() == 5:
        return holiday - ONE_DAY
    if holiday.weekday() == 6:
        return holiday + ONE_DAY
    return holiday


MONDAY, THURSDAY = 0, 3


def holidays(year: int) -> frozenset[date]:
    days = {
        nth_weekday(year, 1, MONDAY, 3),
        nth_weekday(year, 2, MONDAY, 3),
        easter_sunday(year) - timedelta(days=2),
        last_weekday(year, 5, MONDAY),
        observed(date(year, 7, 4)),
        nth_weekday(year, 9, MONDAY, 1),
        nth_weekday(year, 11, THURSDAY, 4),
        observed(date(year, 12, 25)),
    }
    new_year = date(year, 1, 1)
    if new_year.weekday() != 5:
        days.add(observed(new_year))
    if year >= JUNETEENTH_FIRST_YEAR:
        days.add(observed(date(year, 6, 19)))
    return frozenset(days)


class NyseCalendar:
    def __init__(self) -> None:
        # Raises ZoneInfoNotFoundError on Windows without the tzdata package.
        self.zone = ZoneInfo(EASTERN_ZONE)
        self._holidays: dict[int, frozenset[date]] = {}

    def is_trading_day(self, day: date) -> bool:
        if day.weekday() >= 5 or day in SPECIAL_CLOSURES:
            return False
        if day.year not in self._holidays:
            self._holidays[day.year] = holidays(day.year)
        return day not in self._holidays[day.year]

    def closes_early(self, day: date) -> bool:
        thanksgiving = nth_weekday(day.year, 11, THURSDAY, 4)
        return self.is_trading_day(day) and day in {
            date(day.year, 7, 3), thanksgiving + ONE_DAY, date(day.year, 12, 24),
        }

    def session(self, day: date) -> Session:
        if not self.is_trading_day(day):
            raise ValueError(f"{day} is not an NYSE trading day")
        close = EARLY_CLOSE if self.closes_early(day) else REGULAR_CLOSE
        return Session(
            day,
            datetime.combine(day, REGULAR_OPEN, self.zone),
            datetime.combine(day, close, self.zone),
        )

    def next_trading_day(self, day: date) -> date:
        day += ONE_DAY
        while not self.is_trading_day(day):
            day += ONE_DAY
        return day

    def previous_trading_day(self, day: date) -> date:
        day -= ONE_DAY
        while not self.is_trading_day(day):
            day -= ONE_DAY
        return day

    def latest_closed_session(self, moment: datetime) -> date:
        local = moment.astimezone(self.zone)
        day = local.date()
        if self.is_trading_day(day) and local >= self.session(day).close_at:
            return day
        return self.previous_trading_day(day)

    def trading_days(self, first: date, last: date) -> list[date]:
        days = []
        day = first
        while day <= last:
            if self.is_trading_day(day):
                days.append(day)
            day += ONE_DAY
        return days

    def session_for(self, moment: datetime) -> Session:
        """The session whose prior-close-to-close move includes news at this
        moment: that day's, if it trades and the moment is before its close;
        otherwise the next trading day's."""
        local = moment.astimezone(self.zone)
        day = local.date()
        if self.is_trading_day(day) and local < self.session(day).close_at:
            return self.session(day)
        return self.session(self.next_trading_day(day))
