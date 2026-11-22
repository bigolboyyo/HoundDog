import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

import make_demo
from config import BridgeConfig
from fixtures import bar, bar_coverage, write_lines
from market_calendar import NyseCalendar
from overview import Overview
from server import create_app


def priced_sessions(first: date, count: int) -> list[date]:
    calendar, days, day = NyseCalendar(), [], first
    while len(days) < count:
        if calendar.is_trading_day(day):
            days.append(day)
        day += timedelta(days=1)
    return days


class MakeDemoTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.market = root / "market"
        self.out = root / "demo"
        days = priced_sessions(date(2026, 1, 5), 120)
        # Alternating 0% and 3% moves, so planted news has something to follow.
        closes = [100.0 * (1.03 if index % 2 else 1.0) for index in range(len(days))]
        write_lines(self.market / "theta-bars-2026-11-22.jsonl",
                    [bar(symbol, day, close) for symbol in ("AAPL", "MSFT") for day, close in zip(days, closes)])
        write_lines(self.market / "theta-coverage-2026-11-22.jsonl",
                    [bar_coverage(symbol, days[0], days[-1]) for symbol in ("AAPL", "MSFT")])

    def make(self, *args, symbols="AAPL,MSFT"):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = make_demo.main(
                ["--thetadesk", str(self.market), "--out", str(self.out), "--symbols", symbols, *args]
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_the_demo_feeds_every_kind_of_session_and_marks_itself(self):
        code, out, _ = self.make(symbols="aapl,MSFT")

        config = BridgeConfig.load(self.out / "demo.toml")
        report = Overview(config).report()
        self.assertEqual(code, 0)
        self.assertIn("live articles for AAPL, MSFT", out)
        self.assertEqual(config.hounddog_url, "", "a demo never talks to the real HoundDog")
        self.assertIn("DEMO DATA", config.banner)
        for study in report.symbols:
            with self.subTest(study.symbol):
                self.assertGreater(study.news.sessions, 0)
                self.assertGreater(study.quiet.sessions, 0)
                self.assertGreater(study.unwatched_sessions, 0, "the stretch with HoundDog off")
                self.assertTrue(all(event.title.startswith("[DEMO] ") for event in study.events))
        self.assertEqual(report.groups[0].symbols, ("AAPL", "MSFT"))

    def test_backfill_and_a_repeat_detection_are_in_the_data_and_left_out_of_the_study(self):
        self.make()

        records = [json.loads(line) for line in (self.out / "exports" / "hounddog-demo.jsonl").open()]
        events = [record for record in records if record["schema"] == "hounddog.event/1"]
        live_ids = [record["event_id"] for record in events if not record["backfill"]]
        report = Overview(BridgeConfig.load(self.out / "demo.toml")).report()
        self.assertTrue(any(record["backfill"] for record in events))
        self.assertEqual(len(live_ids) - len(set(live_ids)), 1, "one article is detected twice")
        self.assertEqual(sum(len(study.events) for study in report.symbols), len(set(live_ids)))

    def test_the_same_seed_makes_the_same_demo(self):
        self.make("--seed", "3")
        first = (self.out / "exports" / "hounddog-demo.jsonl").read_bytes()
        self.make("--seed", "3")

        self.assertEqual((self.out / "exports" / "hounddog-demo.jsonl").read_bytes(), first)

    def test_a_ticker_without_prices_is_refused(self):
        code, _, err = self.make(symbols="AAPL,TSLA")

        self.assertEqual(code, 1)
        self.assertIn("no ThetaDesk prices for TSLA", err)
        self.assertFalse((self.out / "demo.toml").exists())

    def test_the_dashboard_reads_the_demo_and_refuses_to_watch_tickers(self):
        self.make()
        client = TestClient(create_app(self.out / "demo.toml"), base_url="http://127.0.0.1:8090")

        overview = client.get("/api/overview").json()
        watch = client.post("/api/watch", json={"tickers": [{"symbol": "NVDA", "keywords": ["Nvidia"]}]})

        self.assertFalse(overview["hounddog"]["enabled"])
        self.assertIn("DEMO DATA", overview["display"]["banner"])
        self.assertEqual(watch.status_code, 409)
        self.assertIn("no HoundDog connection", watch.json()["detail"])


if __name__ == "__main__":
    unittest.main()
