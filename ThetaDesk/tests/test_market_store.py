import io
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stderr, redirect_stdout
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import polars as pl

import fetch
import market_store
from theta_data import StockHistory


JAN_2 = date(2024, 1, 2)
JAN_3 = date(2024, 1, 3)
JAN_4 = date(2024, 1, 4)
JAN_5 = date(2024, 1, 5)
PRICES = {"open": 187.03, "high": 188.44, "low": 183.885, "close": 185.64, "volume": 80680243}


def sdk_row(session: date) -> dict:
    return {"date": session, **PRICES}


class DailyBarFormatTests(unittest.TestCase):
    def test_sdk_created_timestamp_is_a_new_york_session_in_both_dataframes(self):
        session = date(2024, 7, 2)
        row = {"created": datetime(2024, 7, 3, 0, 15, tzinfo=timezone.utc), **PRICES}
        for dataframe_type in (pd.DataFrame, pl.DataFrame):
            with self.subTest(dataframe=dataframe_type.__name__):
                [bar] = market_store.normalize_daily_bars(
                    "AAPL", StockHistory("sdk", dataframe_type([row])), session, session
                )
                self.assertEqual(bar, {
                    "schema": "theta.bar/1",
                    "symbol": "AAPL",
                    "interval": "1d",
                    "session_date": "2024-07-02",
                    "start_at": "2024-07-02T13:30:00+00:00",
                    **PRICES,
                    "provider": "sdk",
                })

    def test_terminal_v2_header_object_and_numeric_date(self):
        history = StockHistory("rest", {
            "header": {
                "error_type": None,
                "format": ["ms_of_day", "open", "high", "low", "close", "volume", "date"],
            },
            "response": [[62273606, 187.03, 188.44, 183.885, 185.64, 80680243, 20240102]],
        })
        [bar] = market_store.normalize_daily_bars("AAPL", history, JAN_2, JAN_5)
        self.assertEqual(bar["start_at"], "2024-01-02T14:30:00+00:00")
        self.assertEqual(bar["provider"], "rest")
        self.assertEqual({key: bar[key] for key in PRICES}, PRICES)

    def test_source_app_and_executable_share_one_store_outside_the_release_folder(self):
        for frozen in (False, True):
            with (
                self.subTest(frozen=frozen),
                patch.object(sys, "frozen", frozen, create=True),
                patch.dict("os.environ", {"LOCALAPPDATA": "example-app-data"}),
            ):
                self.assertEqual(
                    market_store.default_data_directory(), Path("example-app-data") / "ThetaDesk"
                )


class MarketStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def fetch(self, first=JAN_2, last=JAN_5):
        return market_store.fetch_daily_bars(" aapl ", first, last, data_dir=self.directory)

    def exports(self):
        return sorted((self.directory / "exports").glob("theta-bars-*.jsonl"))

    def exported_bars(self):
        return [
            json.loads(line)
            for path in self.exports()
            for line in path.read_bytes().splitlines()
        ]

    def exported_coverage(self):
        return [
            json.loads(line)
            for path in sorted((self.directory / "exports").glob("theta-coverage-*.jsonl"))
            for line in path.read_bytes().splitlines()
        ]

    @patch("market_store.fetch_stock_history")
    def test_fetches_only_gaps_and_caches_confirmed_empty_ranges(self, provider):
        provider.side_effect = [
            StockHistory("sdk", [sdk_row(JAN_4)]),
            StockHistory("sdk", []),
            StockHistory("sdk", [sdk_row(JAN_5)]),
        ]
        self.assertEqual(self.fetch(JAN_3, JAN_4).added, 1)
        result = self.fetch()
        self.assertEqual(result.added, 1)
        self.assertEqual(result.covered_through, JAN_5)
        self.assertEqual([call.args for call in provider.call_args_list], [
            ("AAPL", JAN_3, JAN_4), ("AAPL", JAN_2, JAN_2), ("AAPL", JAN_5, JAN_5),
        ])
        cached = self.fetch()
        self.assertEqual(cached.data, result.data)
        self.assertEqual(cached.added, 0)
        self.assertEqual(provider.call_count, 3)
        self.assertEqual(self.exported_bars(), result.data)
        self.assertTrue(all(b"\r" not in path.read_bytes() for path in self.exports()))
        self.assertEqual(sorted((row["start_date"], row["end_date"]) for row in self.exported_coverage()),
                         [("2024-01-02", "2024-01-02"), ("2024-01-03", "2024-01-04"),
                          ("2024-01-05", "2024-01-05")])

    @patch("market_store.fetch_stock_history")
    def test_bad_row_leaves_the_range_fetchable(self, provider):
        provider.return_value = StockHistory("sdk", [sdk_row(JAN_2), {"date": "invalid"}])
        with self.assertRaises(market_store.HistoryFormatError):
            self.fetch()
        self.assertEqual(self.exports(), [])
        self.assertEqual(self.exported_coverage(), [])
        provider.return_value = StockHistory("sdk", [sdk_row(JAN_2)])
        self.assertEqual(self.fetch().added, 1)
        self.assertEqual(provider.call_count, 2)

    @patch("market_store.fetch_stock_history")
    def test_refresh_fills_a_previously_empty_session_without_duplicate_bars(self, provider):
        provider.side_effect = [
            StockHistory("sdk", []),
            StockHistory("sdk", [sdk_row(JAN_2)]),
            StockHistory("sdk", [sdk_row(JAN_2)]),
        ]
        self.assertEqual(self.fetch().data, [])
        self.assertEqual(self.fetch().data, [])
        refreshed = market_store.fetch_daily_bars("AAPL", JAN_2, JAN_5, data_dir=self.directory, refresh=True)
        self.assertEqual(refreshed.added, 1)
        self.assertEqual(self.fetch().data, refreshed.data)
        repeated = market_store.fetch_daily_bars("AAPL", JAN_2, JAN_5, data_dir=self.directory, refresh=True)
        self.assertEqual(repeated.added, 0)
        self.assertEqual(len(self.exported_bars()), 1)

    @patch("market_store.fetch_stock_history")
    def test_empty_current_day_is_retried_when_the_report_arrives(self, provider):
        today = datetime.now(market_store.EASTERN).date()
        provider.side_effect = [
            StockHistory("sdk", []),
            StockHistory("sdk", [sdk_row(today)]),
        ]
        self.assertIsNone(self.fetch(today, today).covered_through)
        self.assertEqual(self.exported_coverage(), [])
        self.assertEqual(self.fetch(today, today).covered_through, today)
        self.assertEqual(self.fetch(today, today).added, 0)
        self.assertEqual(provider.call_count, 2)

    @patch("market_store.fetch_stock_history")
    def test_existing_database_exports_previously_fetched_ranges_once(self, provider):
        with closing(sqlite3.connect(self.directory / "market.db")) as connection, connection:
            connection.executescript(market_store._DATABASE_SCHEMA)
            connection.execute("INSERT INTO fetched_ranges VALUES ('AAPL', '1d', '2024-01-02', '2024-01-05')")

        self.assertEqual(self.fetch().data, [])
        self.assertEqual(self.fetch().data, [])
        provider.assert_not_called()
        self.assertEqual(self.exported_coverage(), [{
            "schema": "theta.coverage/1", "symbol": "AAPL", "interval": "1d",
            "start_date": "2024-01-02", "end_date": "2024-01-05",
        }])

    @patch("market_store.fetch_stock_history")
    def test_recovers_pending_export_and_repairs_partial_line(self, provider):
        provider.side_effect = [
            StockHistory("sdk", [sdk_row(JAN_2)]),
            StockHistory("sdk", [sdk_row(JAN_3)]),
        ]
        self.fetch(JAN_2, JAN_2)
        [path] = self.exports()
        original = path.read_bytes()

        def interrupted_append(target, payload):
            with target.open("ab") as stream:
                stream.write(payload[:20])
            raise OSError("interrupted append")

        with patch("market_store._append_jsonl", side_effect=interrupted_append):
            with self.assertRaisesRegex(OSError, "interrupted append"):
                self.fetch(JAN_3, JAN_3)

        cached = self.fetch(JAN_2, JAN_3)
        self.assertEqual(cached.added, 0)
        self.assertEqual(provider.call_count, 2)
        self.assertTrue(path.read_bytes().startswith(original))
        self.assertEqual(self.exported_bars(), cached.data)

    @patch("market_store.fetch_stock_history")
    def test_concurrent_fetches_write_one_bar_and_export_record(self, provider):
        gate = threading.Barrier(2)

        def provider_response(*args):
            gate.wait(timeout=5)
            return StockHistory("sdk", [sdk_row(JAN_2)])

        provider.side_effect = provider_response
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(self.fetch)
            second = executor.submit(self.fetch)
            results = [first.result(), second.result()]
        self.assertEqual([len(result.data) for result in results], [1, 1])
        self.assertEqual(sum(result.added for result in results), 1)
        self.assertEqual(len(self.exported_bars()), 1)

    @patch("market_store.fetch_stock_history")
    def test_cli_writes_one_json_summary_per_unique_symbol(self, provider):
        provider.return_value = StockHistory("sdk", [sdk_row(JAN_2)])
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = fetch.main([
                "--symbols", "AAPL,nvda,MSFT,aapl",
                "--from", JAN_2.isoformat(), "--to", JAN_5.isoformat(),
                "--data-dir", str(self.directory),
            ])
        self.assertEqual(exit_code, 0)
        summaries = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual([summary["symbol"] for summary in summaries], ["AAPL", "NVDA", "MSFT"])
        self.assertEqual([summary["added"] for summary in summaries], [1, 1, 1])
        self.assertEqual(len(self.exported_bars()), 3)

    @patch("market_store.fetch_stock_history")
    def test_cli_reports_a_failing_symbol_and_still_fetches_the_rest(self, provider):
        def answer(symbol, first, last):
            if symbol == "BAD":
                raise RuntimeError("no such ticker")
            return StockHistory("sdk", [sdk_row(JAN_2)])

        provider.side_effect = answer
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = fetch.main([
                "--symbols", "AAPL,BAD,MSFT",
                "--from", JAN_2.isoformat(), "--to", JAN_5.isoformat(),
                "--data-dir", str(self.directory),
            ])
        self.assertEqual(exit_code, 1)
        self.assertEqual([json.loads(line)["symbol"] for line in stdout.getvalue().splitlines()], ["AAPL", "MSFT"])
        self.assertIn("BAD: no such ticker", stderr.getvalue())
