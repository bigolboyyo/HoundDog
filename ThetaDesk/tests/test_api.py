import os
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values
import httpx
import pandas as pd
import polars as pl
from fastapi.testclient import TestClient

from api import app
from rate_limit import RateLimitExceeded
from theta_data import StockHistory


class StockHistoryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
        from api import _cached_stock_symbols

        _cached_stock_symbols.cache_clear()
        self.url = (
            "/api/v1/stocks/AAPL/history"
            "?start_date=2024-01-01&end_date=2024-01-31"
        )

    def test_serves_frontend_at_root(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Look closer.", response.text)
        self.assertEqual(self.client.get("/app.js").status_code, 200)
        self.assertEqual(self.client.get("/styles.css").status_code, 200)

    def test_dashboard_versions_assets_and_revalidates_html(self) -> None:
        from hashlib import sha256

        for path in ("/", "/index.html"):
            response = self.client.get(path)
            self.assertEqual(response.headers["Cache-Control"], "no-cache")
            for name in ("app.js", "styles.css"):
                match = re.search(rf'"/{re.escape(name)}\?v=([a-f0-9]{{16}})"', response.text)
                self.assertIsNotNone(match)
                asset = self.client.get(f"/{name}?v={match.group(1)}")
                self.assertEqual(asset.status_code, 200)
                self.assertEqual(match.group(1), sha256(asset.content).hexdigest()[:16])

    @patch("api.get_stock_symbols")
    def test_lists_and_caches_available_symbols(
        self,
        get_symbols: unittest.mock.Mock,
    ) -> None:
        get_symbols.return_value = pl.DataFrame(
            [{"symbol": "AAPL"}, {"symbol": "MSFT"}]
        )

        first_response = self.client.get("/api/v1/stocks/symbols")
        second_response = self.client.get("/api/v1/stocks/symbols")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(
            first_response.json()["symbols"],
            ["AAPL", "MSFT"],
        )
        self.assertEqual(second_response.status_code, 200)
        get_symbols.assert_called_once_with()

    @patch("api.get_eod_stock_history")
    def test_returns_polars_data_as_json_records(
        self,
        get_history: unittest.mock.Mock,
    ) -> None:
        get_history.return_value = pl.DataFrame(
            [{"date": date(2024, 1, 2), "close": 185.64}]
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "symbol": "AAPL",
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
                "data": [{"date": "2024-01-02", "close": 185.64}],
            },
        )
        self.assertEqual(response.headers["X-RateLimit-Limit"], "20")
        self.assertEqual(response.headers["X-RateLimit-Remaining"], "20")

    @patch("api.get_eod_stock_history")
    def test_returns_empty_data_when_no_history_is_available(
        self,
        get_history: unittest.mock.Mock,
    ) -> None:
        get_history.return_value = []

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"], [])

    @patch("market_store.fetch_stock_history")
    def test_post_bars_returns_normalized_records_and_reuses_store(self, provider) -> None:
        provider.return_value = StockHistory("sdk", [{
            "date": date(2024, 1, 2), "open": 187.03, "high": 188.44,
            "low": 183.885, "close": 185.64, "volume": 80680243,
        }])
        body = {"start_date": "2024-01-02", "end_date": "2024-01-05"}
        url = "/api/v1/stocks/aapl/bars/fetch"
        with tempfile.TemporaryDirectory() as directory:
            with patch("market_store.default_data_directory", return_value=Path(directory)):
                response = self.client.post(url, json=body)
                cached = self.client.post(url, json=body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(cached.status_code, 200)
        self.assertEqual(response.json()["data"][0]["schema"], "theta.bar/1")
        self.assertEqual(response.json()["data"][0]["symbol"], "AAPL")
        self.assertEqual(response.json()["added"], 1)
        self.assertEqual(cached.json()["added"], 0)
        self.assertEqual(cached.json()["data"], response.json()["data"])
        provider.assert_called_once_with("AAPL", date(2024, 1, 2), date(2024, 1, 5))

    @patch("api.fetch_daily_bars")
    def test_post_bars_refuses_a_cross_origin_write(self, fetch_bars) -> None:
        response = self.client.post(
            "/api/v1/stocks/AAPL/bars/fetch",
            json={"start_date": "2024-01-02", "end_date": "2024-01-05"},
            headers={"Origin": "http://elsewhere.example"},
        )
        self.assertEqual(response.status_code, 403)
        fetch_bars.assert_not_called()

    def test_rejects_requests_addressed_to_another_host_name(self) -> None:
        # What a DNS-rebinding page sends: a loopback client, a foreign Host.
        rebound = TestClient(app, base_url="http://attacker.example:8000", client=("127.0.0.1", 50000))

        response = rebound.get("/api/v1/settings/credentials")

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("api_key", response.text)

    def credentials_folder(self) -> tuple[Path, Path]:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        dotenv_path = Path(directory.name) / ".env"
        for patcher in (
            patch("api.get_dotenv_path", return_value=dotenv_path),
            patch.dict(os.environ, {"THETADATA_API_KEY": ""}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        return dotenv_path, dotenv_path.with_name("creds.txt")

    def save(self, **fields: object) -> httpx.Response:
        return self.client.put("/api/v1/settings/credentials", json=fields)

    def test_reports_what_is_saved_without_sending_secrets(self) -> None:
        dotenv_path, credentials_path = self.credentials_folder()
        dotenv_path.write_text("THETADATA_API_KEY=test-api-key\n", encoding="utf-8")
        credentials_path.write_text("user@example.test\ntest-password\n", encoding="utf-8")

        response = self.client.get("/api/v1/settings/credentials")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "api_key_configured": True, "credentials_configured": True, "email": "user@example.test",
        })
        self.assertNotIn("test-api-key", response.text)
        self.assertNotIn("test-password", response.text)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_blank_fields_keep_what_is_saved(self) -> None:
        dotenv_path, credentials_path = self.credentials_folder()
        self.assertEqual(self.save(api_key="test-api-key", email="user@example.test", password="test-password")
                         .status_code, 200)

        kept = self.save(api_key="", email="", password="")

        self.assertEqual(kept.status_code, 200)
        self.assertEqual(kept.json(), {
            "saved": True, "api_key_configured": True, "credentials_configured": True, "email": "user@example.test",
        })
        self.assertEqual(dotenv_values(dotenv_path)["THETADATA_API_KEY"], "test-api-key")
        self.assertEqual(credentials_path.read_text(encoding="utf-8").splitlines(),
                         ["user@example.test", "test-password"])

    def test_changing_the_email_keeps_the_saved_password(self) -> None:
        _, credentials_path = self.credentials_folder()
        self.save(email="user@example.test", password="test-password")

        changed = self.save(email="other@example.test")

        self.assertEqual(changed.status_code, 200)
        self.assertEqual(credentials_path.read_text(encoding="utf-8").splitlines(),
                         ["other@example.test", "test-password"])
        self.assertFalse(credentials_path.with_name("creds.txt.tmp").exists())

    def test_clearing_removes_only_what_was_asked(self) -> None:
        dotenv_path, credentials_path = self.credentials_folder()
        self.save(api_key="test-api-key", email="user@example.test", password="test-password")

        without_account = self.save(clear_credentials=True)
        self.assertFalse(credentials_path.exists())
        self.assertEqual(dotenv_values(dotenv_path)["THETADATA_API_KEY"], "test-api-key")
        without_key = self.save(clear_api_key=True)

        self.assertEqual(without_account.json()["credentials_configured"], False)
        self.assertEqual(without_key.json(), {
            "saved": True, "api_key_configured": False, "credentials_configured": False, "email": "",
        })
        self.assertNotIn("THETADATA_API_KEY", dotenv_values(dotenv_path))

    def test_refuses_incomplete_or_contradictory_changes(self) -> None:
        dotenv_path, _ = self.credentials_folder()

        cases = {
            "an email with no saved password": {"email": "user@example.test"},
            "a password with no email": {"password": "test-password"},
            "a new key and a clear": {"api_key": "test-api-key", "clear_api_key": True},
            "new account details and a clear": {"email": "user@example.test", "password": "x", "clear_credentials": True},
            "a key on two lines": {"api_key": "one\ntwo"},
        }
        for case, fields in cases.items():
            with self.subTest(case):
                self.assertEqual(self.save(**fields).status_code, 422)
        self.assertFalse(dotenv_path.exists())

    def test_credentials_are_not_readable_or_writable_from_another_site(self) -> None:
        # A page from a local dev server (Next.js and others default to port 3000).
        other_site = {"Origin": "http://localhost:3000"}
        with tempfile.TemporaryDirectory() as temporary_directory:
            dotenv_path = Path(temporary_directory) / ".env"
            dotenv_path.write_text("THETADATA_API_KEY=test-api-key\n", encoding="utf-8")
            with (
                patch("api.get_dotenv_path", return_value=dotenv_path),
                patch.dict(os.environ, {"THETADATA_API_KEY": ""}),
            ):
                read = self.client.get("/api/v1/settings/credentials", headers=other_site)
                write = self.client.put(
                    "/api/v1/settings/credentials",
                    json={"api_key": "attacker-key", "email": "", "password": ""},
                    headers=other_site,
                )
                same_site = self.client.get(
                    "/api/v1/settings/credentials", headers={"Origin": "http://127.0.0.1:8000"},
                )
            saved = dotenv_path.read_text(encoding="utf-8")

        self.assertEqual(read.status_code, 403)
        self.assertNotIn("test-api-key", read.text)
        self.assertNotIn("access-control-allow-origin", read.headers)
        self.assertEqual(write.status_code, 403)
        self.assertIn("test-api-key", saved)
        self.assertEqual(same_site.status_code, 200)

    def test_denies_credential_settings_to_non_loopback_clients(self) -> None:
        client = TestClient(app, base_url="http://127.0.0.1:8000", client=("192.0.2.1", 50000))

        response = client.get("/api/v1/settings/credentials")

        self.assertEqual(response.status_code, 403)

    @patch("api.get_eod_stock_history")
    def test_returns_pandas_data_as_json_records(
        self,
        get_history: unittest.mock.Mock,
    ) -> None:
        get_history.return_value = pd.DataFrame(
            [{"date": date(2024, 1, 2), "close": 185.64}]
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"],
            [{"date": "2024-01-02T00:00:00.000", "close": 185.64}],
        )

    @patch("api.get_eod_stock_history")
    def test_rejects_reversed_date_range(
        self,
        get_history: unittest.mock.Mock,
    ) -> None:
        response = self.client.get(
            "/api/v1/stocks/AAPL/history"
            "?start_date=2024-01-31&end_date=2024-01-01"
        )

        self.assertEqual(response.status_code, 422)
        get_history.assert_not_called()

    @patch("api.get_eod_stock_history")
    def test_rejects_history_range_over_365_days(
        self,
        get_history: unittest.mock.Mock,
    ) -> None:
        response = self.client.get(
            "/api/v1/stocks/AAPL/history"
            "?start_date=2025-10-29&end_date=2026-11-19"
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("365 days", response.json()["detail"])
        get_history.assert_not_called()

    @patch("api.get_eod_stock_history")
    def test_accepts_history_range_of_365_days(
        self,
        get_history: unittest.mock.Mock,
    ) -> None:
        get_history.return_value = [{"close": 185.64}]

        response = self.client.get(
            "/api/v1/stocks/AAPL/history"
            "?start_date=2023-01-01&end_date=2024-01-01"
        )

        self.assertEqual(response.status_code, 200)
        get_history.assert_called_once()

    @patch("api.get_eod_stock_history")
    def test_returns_retry_headers_when_rate_limited(
        self,
        get_history: unittest.mock.Mock,
    ) -> None:
        get_history.side_effect = RateLimitExceeded(4.5)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "5")
        self.assertEqual(response.headers["X-RateLimit-Limit"], "20")


class ShutdownApiTests(unittest.TestCase):
    def setUp(self) -> None:
        import api
        import uvicorn

        self.stop = api.ServerStop()
        patcher = patch.object(api, "SERVER_STOP", self.stop)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server = uvicorn.Server(uvicorn.Config(app))
        self.client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))

    def test_stops_a_server_started_by_serve(self) -> None:
        self.stop.attach(self.server)

        response = self.client.post("/api/v1/shutdown", headers={"Origin": "http://127.0.0.1:8000"})

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {"stopping": True})
        self.assertTrue(self.server.should_exit)

    def test_says_how_to_stop_a_server_started_another_way(self) -> None:
        response = self.client.post("/api/v1/shutdown")

        self.assertEqual(response.status_code, 409)
        self.assertIn("Ctrl+C", response.json()["detail"])

    def test_refuses_cross_origin_and_remote_callers(self) -> None:
        self.stop.attach(self.server)
        remote = TestClient(app, base_url="http://127.0.0.1:8000", client=("203.0.113.5", 50000))

        cross_origin = self.client.post("/api/v1/shutdown", headers={"Origin": "https://example.com"})
        from_elsewhere = remote.post("/api/v1/shutdown")

        self.assertEqual(cross_origin.status_code, 403)
        self.assertEqual(from_elsewhere.status_code, 403)
        self.assertFalse(self.server.should_exit)


class StoredDataAndPinApiTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch("market_store.default_data_directory", return_value=Path(directory.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
        self.origin = {"Origin": "http://127.0.0.1:8000"}

    def load_bars(self) -> None:
        rows = [{"date": date(2024, 1, day), "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10}
                for day in (2, 3, 5)]
        with patch("market_store.fetch_stock_history", return_value=StockHistory("sdk", rows)):
            response = self.client.post(
                "/api/v1/stocks/AAPL/bars/fetch",
                json={"start_date": "2024-01-02", "end_date": "2024-01-05"}, headers=self.origin,
            )
        self.assertEqual(response.status_code, 200)

    def test_lists_loaded_tickers_and_serves_their_stored_bars(self) -> None:
        self.assertEqual(self.client.get("/api/v1/stocks/loaded").json(), {"symbols": []})
        self.load_bars()

        loaded = self.client.get("/api/v1/stocks/loaded").json()["symbols"]
        with patch("market_store.fetch_stock_history") as provider:
            bars = self.client.get("/api/v1/stocks/aapl/bars?start_date=2024-01-03&end_date=2024-01-05")

        provider.assert_not_called()
        self.assertEqual(loaded, [{"symbol": "AAPL", "interval": "1d", "bars": 3,
                                   "first_session": "2024-01-02", "last_session": "2024-01-05"}])
        self.assertEqual(bars.status_code, 200)
        self.assertEqual(bars.json()["symbol"], "AAPL")
        self.assertEqual([row["session_date"] for row in bars.json()["data"]], ["2024-01-03", "2024-01-05"])
        self.assertEqual(
            self.client.get("/api/v1/stocks/AAPL/bars?start_date=2024-01-05&end_date=2024-01-02").status_code, 422
        )

    def test_pins_are_saved_listed_and_removed(self) -> None:
        pin = {"symbol": "aapl", "start_date": "2024-01-02", "end_date": "2024-01-05"}

        created = self.client.post("/api/v1/pins", json=pin, headers=self.origin)
        self.client.post("/api/v1/pins", json={**pin, "symbol": "MSFT"}, headers=self.origin)

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json(), {**pin, "symbol": "AAPL"})
        self.assertEqual([item["symbol"] for item in self.client.get("/api/v1/pins").json()["pins"]], ["AAPL", "MSFT"])
        removed = self.client.delete("/api/v1/pins/AAPL/2024-01-02/2024-01-05", headers=self.origin)
        self.assertEqual(removed.json(), {"removed": 1})
        self.assertEqual(self.client.delete("/api/v1/pins", headers=self.origin).json(), {"removed": 1})
        self.assertEqual(self.client.get("/api/v1/pins").json(), {"pins": []})

    def test_pin_changes_refuse_other_sites_and_machines(self) -> None:
        pin = {"symbol": "AAPL", "start_date": "2024-01-02", "end_date": "2024-01-05"}
        remote = TestClient(app, base_url="http://127.0.0.1:8000", client=("203.0.113.5", 50000))
        cross_site = {"Origin": "https://example.com"}

        self.assertEqual(self.client.post("/api/v1/pins", json=pin, headers=cross_site).status_code, 403)
        self.assertEqual(remote.post("/api/v1/pins", json=pin).status_code, 403)
        self.client.post("/api/v1/pins", json=pin, headers=self.origin)
        self.assertEqual(self.client.delete("/api/v1/pins", headers=cross_site).status_code, 403)
        self.assertEqual(remote.delete("/api/v1/pins/AAPL/2024-01-02/2024-01-05").status_code, 403)
        self.assertEqual(len(self.client.get("/api/v1/pins").json()["pins"]), 1)

    def test_a_pin_with_reversed_dates_is_refused(self) -> None:
        response = self.client.post(
            "/api/v1/pins", json={"symbol": "AAPL", "start_date": "2024-01-05", "end_date": "2024-01-02"},
            headers=self.origin,
        )
        self.assertEqual(response.status_code, 422)

