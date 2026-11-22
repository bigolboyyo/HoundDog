import os
from datetime import date
from typing import Any

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:25510/v2"


def get_eod(root: str, start_date: date, end_date: date) -> Any:
    """Fetch end-of-day stock data from the local ThetaData Terminal."""
    if not root or not root.strip():
        raise ValueError("root must not be empty")
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")

    base_url = os.getenv("THETADATA_REST_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    params = {
        "root": root.strip(),
        "start_date": start_date.strftime("%Y%m%d"),
        "end_date": end_date.strftime("%Y%m%d"),
    }
    response = requests.get(
        f"{base_url}/hist/stock/eod",
        params=params,
        timeout=30,
    )
    if response.status_code == 472:  # Terminal's NO_DATA response.
        return []
    response.raise_for_status()
    return response.json()
