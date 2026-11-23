import tempfile
import unittest
from datetime import date
from pathlib import Path

from exports import read_market, read_news
from fixtures import bar, bar_coverage, coverage, event, write_lines


class ReadNewsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)

    def test_repeated_records_are_kept_once(self):
        records = [coverage(1, "2026-11-16 15:00", ["AAPL"]), event(1, "2026-11-16 15:00", "https://x/a", ["AAPL"])]
        write_lines(self.folder / "hounddog-2026-11-16.jsonl", records + records)

        news = read_news(self.folder)

        self.assertEqual((len(news.events), len(news.checks)), (1, 1))
        self.assertEqual(news.report.duplicates, 2)

    def test_an_interrupted_final_line_and_unknown_schemas_are_skipped_and_counted(self):
        write_lines(
            self.folder / "hounddog-2026-11-16.jsonl",
            [{"schema": "hounddog.event/2", "event_id": "x"}, coverage(1, "2026-11-16 15:00", ["AAPL"])],
            tail='{"schema": "hounddog.event/1", "event_',
        )

        news = read_news(self.folder)

        self.assertEqual(len(news.checks), 1)
        self.assertEqual(news.report.skipped["incomplete final line"], 1)
        self.assertEqual(news.report.skipped["unknown schema 'hounddog.event/2'"], 1)

    def test_legacy_coverage_without_topics_means_unknown_topics(self):
        legacy = coverage(1, "2026-11-16 15:00", None)
        del legacy["run_id"]
        write_lines(self.folder / "hounddog-2026-11-16.jsonl", [legacy])

        [check] = read_news(self.folder).checks

        self.assertIsNone(check.topics)
        self.assertEqual(check.check_key, "check:1")

    def test_a_check_whose_feeds_all_failed_read_nothing(self):
        write_lines(self.folder / "hounddog-2026-11-16.jsonl", [coverage(1, "2026-11-16 15:00", ["AAPL"], "failed")])

        [check] = read_news(self.folder).checks

        self.assertFalse(check.read_any_feed)

    def test_per_topic_backfill_is_read_for_each_topic(self):
        record = event(1, "2026-11-16 15:00", "https://x/a", ["AAPL", "Breaking"])
        record["topics"][1]["backfill"] = True
        write_lines(self.folder / "hounddog-2026-11-16.jsonl", [record])

        [news_event] = read_news(self.folder).events

        self.assertEqual([(topic.name, topic.backfill) for topic in news_event.topics],
                         [("AAPL", False), ("Breaking", True)])

    def test_a_missing_folder_reads_as_empty(self):
        news = read_news(self.folder / "absent")

        self.assertEqual((news.events, news.checks, news.report.files), ((), (), 0))


class ReadMarketTests(unittest.TestCase):
    def test_bars_are_kept_once_per_key_and_coverage_is_read(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            first = bar("aapl", date(2026, 11, 16), 100.0)
            write_lines(folder / "theta-bars-2026-11-22.jsonl", [first, first, bar("AAPL", date(2026, 11, 17), 101.0)])
            write_lines(folder / "theta-coverage-2026-11-22.jsonl",
                        [bar_coverage("AAPL", date(2026, 11, 16), date(2026, 11, 17))])

            market = read_market(folder)

        self.assertEqual([(b.symbol, b.close) for b in market.bars], [("AAPL", 100.0), ("AAPL", 101.0)])
        self.assertEqual(market.report.duplicates, 1)
        self.assertEqual(market.coverage[0].end_date, date(2026, 11, 17))

    def test_a_malformed_bar_is_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            broken = bar("AAPL", date(2026, 11, 16), 100.0)
            broken["start_at"] = "2026-11-16T14:30:00"
            write_lines(folder / "theta-bars-2026-11-22.jsonl", [broken])

            market = read_market(folder)

        self.assertEqual(market.bars, ())
        self.assertEqual(market.report.skipped["malformed theta.bar/1"], 1)

    def test_non_finite_prices_do_not_hide_valid_bars(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            valid = bar("AAPL", date(2026, 11, 16), 100.0)
            write_lines(folder / "theta-bars-2026-11-22.jsonl", [
                {**valid, "close": "NaN"},
                {**valid, "open": float("inf")},
                {**valid, "high": 10**400},
                valid,
            ])

            market = read_market(folder)
            self.assertEqual([row.close for row in market.bars], [100.0])
            self.assertEqual(market.report.skipped["malformed theta.bar/1"], 3)


if __name__ == "__main__":
    unittest.main()
