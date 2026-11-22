import unittest
from datetime import date
from unittest.mock import patch

from theta_manual_requests import get_eod


class GetEodTests(unittest.TestCase):
    @patch("theta_manual_requests.requests.get")
    def test_terminal_no_data_is_an_empty_result(self, request: unittest.mock.Mock) -> None:
        request.return_value.status_code = 472
        self.assertEqual(get_eod("AAPL", date(2024, 1, 6), date(2024, 1, 7)), [])
        request.return_value.raise_for_status.assert_not_called()

    @patch("theta_manual_requests.requests.get")
    def test_formats_dates_for_local_terminal(self, request: unittest.mock.Mock) -> None:
        response = request.return_value
        response.json.return_value = {"response": []}

        result = get_eod("AAPL", date(2024, 1, 1), date(2024, 1, 31))

        self.assertEqual(result, {"response": []})
        request.assert_called_once_with(
            "http://127.0.0.1:25510/v2/hist/stock/eod",
            params={
                "root": "AAPL",
                "start_date": "20240101",
                "end_date": "20240131",
            },
            timeout=30,
        )
        response.raise_for_status.assert_called_once_with()

    @patch("theta_manual_requests.requests.get")
    def test_rejects_reversed_dates_before_request(
        self,
        request: unittest.mock.Mock,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "start_date must be"):
            get_eod("AAPL", date(2024, 1, 31), date(2024, 1, 1))

        request.assert_not_called()
