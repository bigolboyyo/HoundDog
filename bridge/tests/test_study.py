import tempfile
import unittest
from datetime import date
from pathlib import Path

from exports import read_market, read_news
from fixtures import bar, bar_coverage, coverage, event, write_lines
from market_calendar import NyseCalendar
from study import CheckDay, DailyStudy, StudySymbol

MON, TUE, WED, THU, FRI = (date(2026, 11, day) for day in (16, 17, 18, 19, 20))
PREVIOUS_FRI = date(2026, 11, 13)
AAPL = StudySymbol("AAPL", ("AAPL",))


class DailyStudyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        # Closes: Fri 100, Mon 110 (+10%), Tue 110 (0%), Wed 99 (-10%), Thu 99 (0%), Fri 99 (0%).
        closes = {PREVIOUS_FRI: 100.0, MON: 110.0, TUE: 110.0, WED: 99.0, THU: 99.0, FRI: 99.0}
        volumes = {MON: 3000, WED: 2000}
        write_lines(self.folder / "theta-bars-2026-11-22.jsonl",
                    [bar("AAPL", day, close, volumes.get(day, 1000)) for day, close in closes.items()])
        write_lines(self.folder / "theta-coverage-2026-11-22.jsonl", [bar_coverage("AAPL", PREVIOUS_FRI, FRI)])

    def run_study(self, news_records, symbol=AAPL, *, latest_closed=FRI):
        write_lines(self.folder / "hounddog-2026-11-16.jsonl", news_records)
        news = read_news(self.folder)
        market = read_market(self.folder)
        return DailyStudy(
            NyseCalendar(), news.events, news.checks, market.bars, market.coverage,
            latest_closed_session=latest_closed,
        ).run(symbol)

    def hourly_checks(self, topics=("AAPL",)):
        """One check per weekday at 15:00 UTC (10:00 ET), Mon to Fri."""
        return [coverage(n, f"{day.isoformat()} 15:00", list(topics)) for n, day in enumerate((MON, TUE, WED, THU, FRI), 1)]

    def test_news_sessions_are_compared_with_watched_quiet_sessions(self):
        records = self.hourly_checks() + [
            event(1, "2026-11-16 15:00", "https://x/mon", ["AAPL"]),
            event(3, "2026-11-18 15:00", "https://x/wed", ["AAPL"]),
        ]

        study = self.run_study(records)

        self.assertEqual(study.news.sessions, 2)
        self.assertAlmostEqual(study.news.mean_abs_change, 0.10)
        self.assertEqual(study.quiet.sessions, 3)
        self.assertAlmostEqual(study.quiet.mean_abs_change, 0.0)
        self.assertAlmostEqual(study.news.mean_volume_ratio, 2.5, msg="(3000 + 2000) / 2 over a median of 1000")
        self.assertEqual(study.unwatched_sessions, 0)
        self.assertEqual(study.verdict, "Small sample. Average moves were larger on news days.")

    def test_sessions_hounddog_did_not_watch_are_not_quiet(self):
        records = [coverage(1, "2026-11-16 15:00", ["AAPL"]), event(1, "2026-11-16 15:00", "https://x/mon", ["AAPL"])]

        study = self.run_study(records)

        self.assertEqual((study.news.sessions, study.quiet.sessions, study.unwatched_sessions), (1, 0, 4))

    def test_checks_without_the_symbol_topic_or_with_unknown_topics_do_not_count(self):
        records = [coverage(1, "2026-11-16 15:00", ["Breaking"]), coverage(2, "2026-11-17 15:00", None)]

        study = self.run_study(records)

        self.assertEqual((study.quiet.sessions, study.unwatched_sessions), (0, 5))
        self.assertTrue(any("No HoundDog check has watched AAPL" in note for note in study.notes))

    def test_checks_that_read_no_feed_do_not_count(self):
        study = self.run_study([coverage(1, "2026-11-16 15:00", ["AAPL"], status="failed")])

        self.assertEqual(study.quiet.sessions, 0)

    def test_check_days_include_weekend_attempts_and_group_by_eastern_date(self):
        records = [
            coverage(1, "2026-11-22 21:00", ["AAPL"], "failed"),
            coverage(2, "2026-11-23 02:00", ["AAPL", "Apple"], "unchanged"),
            coverage(3, "2026-11-23 03:00", ["Apple"], "skipped"),
            coverage(4, "2026-11-24 15:00", ["AAPL"]),
            coverage(5, "2026-11-16 15:00", None),
            coverage(6, "2026-11-20 15:00", ["Other"]),
        ]
        study = self.run_study(records, StudySymbol("AAPL", ("AAPL", "Apple")))

        self.assertEqual(study.check_days, (
            CheckDay(date(2026, 11, 22), 3, 1, 1, 1),
            CheckDay(date(2026, 11, 24), 1, 1, 0, 0),
        ))
        self.assertEqual(study.first_check_session, date(2026, 11, 24))
        self.assertEqual(study.quiet.sessions, 0, "The stored price range ends before these checks")

    def test_backfill_and_repeat_detections_are_excluded(self):
        records = self.hourly_checks() + [
            event(1, "2026-11-16 15:00", "https://x/old", ["AAPL"], backfill=True),
            event(3, "2026-11-18 15:00", "https://x/old", ["AAPL"]),
            event(2, "2026-11-17 15:00", "https://x/tue", ["AAPL"]),
            event(4, "2026-11-19 15:00", "https://x/tue", ["AAPL"]),
        ]

        study = self.run_study(records)

        self.assertEqual([(placed.event_id, placed.session) for placed in study.events], [("tue", TUE)])
        self.assertEqual([(entry.event_id, entry.reason) for entry in study.excluded_events], [
            ("old", "backfill"), ("old", "repeat_detection"), ("tue", "repeat_detection"),
        ])

    def test_mixed_detection_uses_the_live_topic_regardless_of_topic_order(self):
        record = event(1, "2026-11-16 15:00", "https://x/mixed", ["New Apple Topic", "AAPL"])
        record["topics"][0]["backfill"] = True
        study = self.run_study([record], StudySymbol("AAPL", ("New Apple Topic", "AAPL")))

        self.assertEqual([(entry.topic, entry.session) for entry in study.events], [("AAPL", MON)])
        self.assertEqual(study.excluded_events, ())
        self.assertEqual(study.news.sessions, 1)

    def test_weekend_news_and_checks_are_separate_from_monday(self):
        records = [
            event(1, "2026-11-13 21:00", "https://x/fri", ["AAPL"]),
            coverage(2, "2026-11-14 15:00", ["AAPL"]),
            event(2, "2026-11-14 15:00", "https://x/sat", ["AAPL"]),
            event(3, "2026-11-16 04:59", "https://x/sun", ["AAPL"]),
            event(4, "2026-11-16 15:00", "https://x/sat", ["AAPL"]),
        ]

        study = self.run_study(records)

        self.assertEqual([entry.event_id for entry in study.weekend_events], ["fri", "sat", "sun"])
        self.assertEqual(study.events, ())
        self.assertEqual((study.news.sessions, study.quiet.sessions), (0, 0))
        self.assertEqual(study.check_days[0].day, date(2026, 11, 14))
        self.assertIsNone(study.first_check_session)

    def test_monday_after_close_counts_toward_tuesday(self):
        study = self.run_study([
            event(1, "2026-11-16 05:00", "https://x/pre-market", ["AAPL"]),
            event(2, "2026-11-16 22:00", "https://x/after-close", ["AAPL"]),
        ])

        self.assertEqual([(event.session, event.placement) for event in study.events], [
            (MON, "before_close"), (TUE, "at_or_after_close"),
        ])
        self.assertTrue(all(event.price_status == "in_study" for event in study.events))

    def test_news_without_price_coverage_changes_status_once_the_session_closes(self):
        records = [event(9, "2026-11-23 22:00", "https://x/late", ["AAPL"])]
        next_session = date(2026, 11, 24)

        study = self.run_study(records)

        self.assertEqual(study.events[0].session, next_session)
        self.assertEqual(study.events[0].placement, "at_or_after_close")
        self.assertEqual(study.events[0].exclusion, "outside_coverage")
        self.assertFalse(study.events[0].has_move)
        self.assertEqual(study.events[0].price_status, "awaiting_close")

        after_close = self.run_study(records, latest_closed=next_session)
        self.assertEqual(after_close.events[0].price_status, "outside_coverage")

        prior = date(2026, 11, 23)
        write_lines(self.folder / "theta-bars-2026-11-22.jsonl", [
            bar("AAPL", prior, 100.0), bar("AAPL", next_session, 102.0),
        ])
        write_lines(self.folder / "theta-coverage-2026-11-22.jsonl",
                    [bar_coverage("AAPL", prior, next_session)])
        with_prices = self.run_study(records, latest_closed=next_session)
        self.assertEqual(with_prices.events[0].price_status, "in_study")
        self.assertEqual(with_prices.news.sessions, 1)

    def test_a_missing_bar_is_a_gap_not_a_move(self):
        write_lines(self.folder / "theta-bars-2026-11-22.jsonl",
                    [bar("AAPL", day, 100.0) for day in (PREVIOUS_FRI, MON, WED, THU, FRI)])

        study = self.run_study(self.hourly_checks() + [
            event(2, "2026-11-17 15:00", "https://x/tue", ["AAPL"]),
            event(3, "2026-11-18 15:00", "https://x/wed", ["AAPL"]),
        ])

        self.assertEqual(study.missing_bars, (TUE,))
        self.assertEqual(study.quiet.sessions, 3, "Tuesday and Wednesday have no move")
        self.assertEqual([(entry.session, entry.close, entry.reason) for entry in study.excluded_sessions], [
            (PREVIOUS_FRI, 100.0, "first_price_session"),
            (TUE, None, "missing_bar"),
            (WED, 100.0, "missing_previous_bar"),
        ])
        self.assertEqual([(entry.placement, entry.exclusion) for entry in study.events], [
            ("before_close", "missing_bar"), ("before_close", "missing_previous_bar"),
        ])
        self.assertEqual([entry.price_status for entry in study.events], ["missing_bar", "missing_previous_bar"])
        self.assertEqual(study.news.sessions, 0)

    def test_first_saved_close_bounds_gap_checks_and_moves_with_earlier_history(self):
        bar_file = self.folder / "theta-bars-2026-11-22.jsonl"
        closes = [bar("AAPL", THU, 100.0), bar("AAPL", FRI, 102.0)]
        write_lines(bar_file, closes)
        write_lines(self.folder / "theta-coverage-2026-11-22.jsonl",
                    [bar_coverage("AAPL", date(2025, 11, 20), FRI)])
        records = [
            event(1, "2026-11-18 15:00", "https://x/early", ["AAPL"]),
            event(2, "2026-11-19 15:00", "https://x/first", ["AAPL"]),
            event(3, "2026-11-20 15:00", "https://x/second", ["AAPL"]),
        ]

        study = self.run_study(records)

        self.assertEqual(study.missing_bars, ())
        self.assertEqual([entry.session for entry in study.excluded_sessions], [THU])
        self.assertEqual([entry.price_status for entry in study.events], [
            "before_price_history", "first_price_session", "in_study",
        ])
        self.assertEqual(study.news.sessions, 1)

        write_lines(bar_file, [bar("AAPL", TUE, 98.0), *closes])
        study = self.run_study(records)
        self.assertEqual(study.missing_bars, (WED,))
        self.assertEqual([entry.price_status for entry in study.events], [
            "missing_bar", "missing_previous_bar", "in_study",
        ])

    def test_no_saved_closes_means_no_established_price_history(self):
        write_lines(self.folder / "theta-bars-2026-11-22.jsonl", [])
        study = self.run_study([
            event(1, "2026-11-20 15:00", "https://x/closed", ["AAPL"]),
            event(2, "2026-11-23 15:00", "https://x/upcoming", ["AAPL"]),
        ])

        self.assertEqual(study.missing_bars, ())
        self.assertEqual([entry.price_status for entry in study.events], ["no_price_history", "awaiting_close"])

    def test_a_check_at_the_close_belongs_to_that_session(self):
        # 21:00 UTC is 16:00 ET in November: Monday's close.
        study = self.run_study([coverage(1, "2026-11-16 21:00", ["AAPL"])])

        kinds = {point.session: point.kind for point in study.sessions}
        self.assertEqual((kinds[MON], kinds[TUE]), ("quiet", "unwatched"))
        self.assertEqual(study.first_check_session, MON)

    def test_bars_without_coverage_records_are_explained(self):
        write_lines(self.folder / "theta-coverage-2026-11-22.jsonl", [])

        study = self.run_study(self.hourly_checks())

        self.assertEqual(study.sessions, ())
        self.assertTrue(any("no record of which dates it looked up" in note for note in study.notes))

    def test_a_symbol_can_use_several_topics(self):
        records = self.hourly_checks(("Apple",)) + [event(1, "2026-11-16 15:00", "https://x/mon", ["Apple"])]

        study = self.run_study(records, StudySymbol("AAPL", ("AAPL", "Apple")))

        self.assertEqual(study.news.sessions, 1)


if __name__ == "__main__":
    unittest.main()
