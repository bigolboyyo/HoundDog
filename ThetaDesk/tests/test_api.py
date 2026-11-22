import os
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values
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

    def test_reads_credentials_from_active_app_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            dotenv_path = Path(temporary_directory) / ".env"
            dotenv_path.write_text(
                "THETADATA_API_KEY=test-api-key\n",
                encoding="utf-8",
            )
            (dotenv_path.parent / "creds.txt").write_text(
                "user@example.test\ntest-password\n",
                encoding="utf-8",
            )
            with (
                patch("api.get_dotenv_path", return_value=dotenv_path),
                patch.dict(os.environ, {"THETADATA_API_KEY": ""}),
            ):
                response = self.client.get("/api/v1/settings/credentials")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "api_key": "test-api-key",
                "email": "user@example.test",
                "password": "test-password",
            },
        )
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_saves_and_clears_credentials_in_active_app_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            dotenv_path = Path(temporary_directory) / ".env"
            credentials_path = dotenv_path.with_name("creds.txt")
            with (
                patch("api.get_dotenv_path", return_value=dotenv_path),
                patch.dict(os.environ, {"THETADATA_API_KEY": ""}),
            ):
                saved = self.client.put(
                    "/api/v1/settings/credentials",
                    json={
                        "api_key": "test-api-key",
                        "email": "user@example.test",
                        "password": "test-password",
                    },
                )
                self.assertEqual(saved.status_code, 200)
                self.assertEqual(
                    dotenv_values(dotenv_path)["THETADATA_API_KEY"],
                    "test-api-key",
                )
                self.assertEqual(
                    credentials_path.read_text(encoding="utf-8").splitlines(),
                    ["user@example.test", "test-password"],
                )

                cleared = self.client.put(
                    "/api/v1/settings/credentials",
                    json={"api_key": "", "email": "", "password": ""},
                )

            self.assertEqual(cleared.status_code, 200)
            self.assertFalse(credentials_path.exists())
            self.assertNotIn(
                "THETADATA_API_KEY",
                dotenv_values(dotenv_path),
            )

    def test_rejects_incomplete_email_password_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            dotenv_path = Path(temporary_directory) / ".env"
            with patch("api.get_dotenv_path", return_value=dotenv_path):
                response = self.client.put(
                    "/api/v1/settings/credentials",
                    json={
                        "api_key": "",
                        "email": "user@example.test",
                        "password": "",
                    },
                )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"],
            "Provide both email and password, or leave both blank.",
        )
        self.assertFalse(dotenv_path.exists())

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
