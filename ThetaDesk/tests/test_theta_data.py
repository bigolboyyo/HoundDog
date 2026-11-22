import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import grpc
from thetadata.errors import NoDataFoundError

import theta_data
from rate_limit import RateLimitExceeded


class GetEodStockHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start_date = date(2024, 1, 1)
        self.end_date = date(2024, 1, 31)
        limiter_patcher = patch("theta_data.THETADATA_RATE_LIMITER.acquire")
        self.acquire_request_slot = limiter_patcher.start()
        self.addCleanup(limiter_patcher.stop)

    def test_dotenv_path_is_next_to_packaged_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            executable = Path(temporary_directory) / "ThetaDesk.exe"
            with (
                patch.object(theta_data.sys, "frozen", True, create=True),
                patch.object(theta_data.sys, "executable", str(executable)),
            ):
                self.assertEqual(
                    theta_data.get_dotenv_path(),
                    executable.parent / ".env",
                )

    @patch.dict("os.environ", {"THETADATA_REST_FALLBACK_ENABLED": "true"})
    @patch("theta_data.get_eod", return_value=[{"date": 20240102}])
    @patch("thetadata.ThetaClient")
    def test_sdk_deadline_is_applied_to_the_stream_and_falls_back(self, sdk, rest) -> None:
        client = sdk.return_value
        rpc = client.stub.GetStockHistoryEod
        rpc.side_effect = grpc.RpcError("deadline exceeded")
        client.stock_history_eod.side_effect = lambda **kwargs: client.stub.GetStockHistoryEod("request")

        with self.assertLogs("theta_data", level="WARNING"):
            history = theta_data.fetch_stock_history("AAPL", self.start_date, self.end_date)

        rpc.assert_called_once_with("request", timeout=theta_data.SDK_REQUEST_TIMEOUT_SECONDS)
        rest.assert_called_once_with("AAPL", self.start_date, self.end_date)
        self.assertEqual(history.provider, "rest")

    @patch("thetadata.ThetaClient")
    def test_symbol_lookup_also_sets_a_transport_deadline(self, sdk) -> None:
        client = sdk.return_value
        rpc = client.stub.GetStockListSymbols
        client.stock_list_symbols.side_effect = lambda: client.stub.GetStockListSymbols("request")
        theta_data.get_stock_symbols()
        rpc.assert_called_once_with("request", timeout=theta_data.SDK_REQUEST_TIMEOUT_SECONDS)

    @patch("theta_data.get_eod")
    @patch("theta_data._get_python_history")
    def test_uses_rest_when_python_client_fails(
        self,
        python_history: unittest.mock.Mock,
        rest_history: unittest.mock.Mock,
    ) -> None:
        python_history.side_effect = RuntimeError("SDK unavailable")
        rest_history.return_value = {"response": []}

        with self.assertLogs("theta_data", level="WARNING"):
            result = theta_data.get_eod_stock_history(
                "AAPL",
                self.start_date,
                self.end_date,
            )

        self.assertEqual(result, {"response": []})
        rest_history.assert_called_once_with("AAPL", self.start_date, self.end_date)
        self.assertEqual(self.acquire_request_slot.call_count, 2)

    @patch("theta_data._get_python_history")
    def test_rejects_empty_symbol_before_request(
        self,
        python_history: unittest.mock.Mock,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "symbol must not be empty"):
            theta_data.get_eod_stock_history(
                " ",
                self.start_date,
                self.end_date,
            )

        python_history.assert_not_called()
        self.acquire_request_slot.assert_not_called()

    @patch("theta_data._get_python_history")
    def test_rejects_history_range_over_365_days_before_request(
        self,
        python_history: unittest.mock.Mock,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "365 days"):
            theta_data.get_eod_stock_history(
                "AAPL",
                self.start_date,
                self.start_date + timedelta(days=366),
            )

        python_history.assert_not_called()
        self.acquire_request_slot.assert_not_called()

    @patch("theta_data.get_eod")
    @patch("thetadata.ThetaClient")
    def test_returns_empty_rows_without_rest_fallback_when_no_data_exists(
        self,
        theta_client: unittest.mock.Mock,
        rest_history: unittest.mock.Mock,
    ) -> None:
        theta_client.return_value.stock_history_eod.side_effect = NoDataFoundError(
            "No data found"
        )

        result = theta_data.get_eod_stock_history(
            "AAIN",
            self.start_date,
            self.end_date,
        )

        self.assertEqual(result, [])
        theta_client.assert_called_once_with(
            dotenv_path=theta_data.get_dotenv_path()
        )
        rest_history.assert_not_called()
        self.assertEqual(self.acquire_request_slot.call_count, 1)

    @patch("thetadata.ThetaClient")
    def test_symbol_client_uses_explicit_dotenv_path(
        self,
        theta_client: unittest.mock.Mock,
    ) -> None:
        theta_data.get_stock_symbols()

        theta_client.assert_called_once_with(
            dotenv_path=theta_data.get_dotenv_path()
        )

    @patch("theta_data.get_eod")
    @patch("theta_data._get_python_history")
    def test_reports_both_provider_failures(
        self,
        python_history: unittest.mock.Mock,
        rest_history: unittest.mock.Mock,
    ) -> None:
        python_history.side_effect = RuntimeError("SDK unavailable")
        rest_history.side_effect = RuntimeError("Terminal unavailable")

        with self.assertLogs("theta_data", level="WARNING"):
            with self.assertRaisesRegex(RuntimeError, "both failed") as raised:
                theta_data.get_eod_stock_history(
                    "AAPL",
                    self.start_date,
                    self.end_date,
                )

        self.assertIn("SDK unavailable", str(raised.exception))
        self.assertIn("Terminal unavailable", str(raised.exception))

    @patch("theta_data.get_eod")
    @patch("theta_data._get_python_history")
    def test_rate_limit_can_block_a_fallback_attempt(
        self,
        python_history: unittest.mock.Mock,
        rest_history: unittest.mock.Mock,
    ) -> None:
        python_history.side_effect = RuntimeError("SDK unavailable")
        self.acquire_request_slot.side_effect = [None, RateLimitExceeded(5)]

        with self.assertLogs("theta_data", level="WARNING"):
            with self.assertRaises(RateLimitExceeded):
                theta_data.get_eod_stock_history(
                    "AAPL",
                    self.start_date,
                    self.end_date,
                )

        rest_history.assert_not_called()
        self.assertEqual(self.acquire_request_slot.call_count, 2)

    @patch.dict("os.environ", {"THETADATA_REST_FALLBACK_ENABLED": "0"})
    @patch("theta_data.get_eod")
    @patch("theta_data._get_python_history")
    def test_does_not_attempt_rest_when_backup_was_declined(
        self,
        python_history: unittest.mock.Mock,
        rest_history: unittest.mock.Mock,
    ) -> None:
        python_history.side_effect = RuntimeError("SDK unavailable")

        with self.assertLogs("theta_data", level="WARNING"):
            with self.assertRaisesRegex(RuntimeError, "fallback is disabled"):
                theta_data.get_eod_stock_history(
                    "AAPL",
                    self.start_date,
                    self.end_date,
                )

        rest_history.assert_not_called()
        self.assertEqual(self.acquire_request_slot.call_count, 1)
