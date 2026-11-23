import unittest
from datetime import date, datetime, time, timezone

from market_calendar import NyseCalendar, easter_sunday

UTC = timezone.utc


class NyseCalendarTests(unittest.TestCase):
    def setUp(self):
        self.calendar = NyseCalendar()

    def test_2026_holidays_match_the_published_nyse_schedule(self):
        closed = [
            date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25),
            date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25),
        ]
        weekdays_2026 = [day for day in (date.fromordinal(n) for n in range(date(2026, 1, 1).toordinal(),
                                                                             date(2027, 1, 1).toordinal()))
                         if day.weekday() < 5]

        self.assertEqual([day for day in weekdays_2026 if not self.calendar.is_trading_day(day)], closed)

    def test_observed_days_and_a_saturday_new_year(self):
        self.assertFalse(self.calendar.is_trading_day(date(2026, 7, 3)), "July 4 2026 is a Saturday")
        self.assertFalse(self.calendar.is_trading_day(date(2022, 12, 26)), "Christmas 2022 was a Sunday")
        self.assertTrue(self.calendar.is_trading_day(date(2021, 12, 31)), "New Year 2022 on Saturday is not moved")
        self.assertFalse(self.calendar.is_trading_day(date(2025, 1, 9)), "national day of mourning")
        self.assertTrue(self.calendar.is_trading_day(date(2021, 6, 18)), "Juneteenth starts in 2022")

    def test_easter_dates(self):
        self.assertEqual([easter_sunday(year) for year in (2024, 2025, 2026, 2027)],
                         [date(2024, 3, 31), date(2025, 4, 20), date(2026, 4, 5), date(2027, 3, 28)])

    def test_early_closes(self):
        self.assertEqual(self.calendar.session(date(2025, 11, 28)).close_at.time(), time(13, 0))
        self.assertEqual(self.calendar.session(date(2025, 12, 24)).close_at.time(), time(13, 0))
        self.assertEqual(self.calendar.session(date(2025, 7, 3)).close_at.time(), time(13, 0))
        self.assertEqual(self.calendar.session(date(2026, 7, 2)).close_at.time(), time(16, 0),
                         "July 3 2026 is the observed holiday, so July 2 is a full day")

    def test_session_times_follow_daylight_saving(self):
        self.assertEqual(self.calendar.session(date(2026, 7, 1)).open_at.astimezone(UTC).hour, 13)
        self.assertEqual(self.calendar.session(date(2026, 1, 2)).open_at.astimezone(UTC).hour, 14)

    def test_latest_completed_session_respects_early_close(self):
        for moment, day in (
            ("2026-11-27T17:59:00+00:00", date(2026, 11, 25)),
            ("2026-11-27T18:00:00+00:00", date(2026, 11, 27)),
            ("2026-11-28T21:00:00+00:00", date(2026, 11, 27)),
        ):
            with self.subTest(moment=moment):
                self.assertEqual(self.calendar.latest_closed_session(datetime.fromisoformat(moment)), day)

    def test_news_belongs_to_the_session_whose_close_follows_it(self):
        cases = {
            "2026-11-16T14:00:00+00:00": date(2026, 11, 16),  # Monday 09:00 ET, pre-market
            "2026-11-16T20:59:00+00:00": date(2026, 11, 16),  # 15:59 ET
            "2026-11-16T21:00:00+00:00": date(2026, 11, 17),  # at the close: next session
            "2026-11-21T15:00:00+00:00": date(2026, 11, 23),  # Saturday
            "2026-11-26T15:00:00+00:00": date(2026, 11, 27),  # Thanksgiving
            "2026-11-27T18:30:00+00:00": date(2026, 11, 30),  # after the 13:00 early close
        }
        for moment, session in cases.items():
            with self.subTest(moment):
                self.assertEqual(self.calendar.session_for(datetime.fromisoformat(moment)).day, session)


if __name__ == "__main__":
    unittest.main()
