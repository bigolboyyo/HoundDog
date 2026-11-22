import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date
from functools import partial
from pathlib import Path
from typing import Any

from rate_limit import RateLimitExceeded, SlidingWindowRateLimiter
from theta_manual_requests import get_eod


logger = logging.getLogger(__name__)
MAX_HISTORY_DAYS = 365
SDK_REQUEST_TIMEOUT_SECONDS = 30
THETADATA_RATE_LIMITER = SlidingWindowRateLimiter(limit=20, window_seconds=60)


@dataclass(frozen=True)
class StockHistory:
    provider: str
    data: Any


def records_from_history(history: Any) -> list[dict[str, Any]]:
    if isinstance(history, dict) and "header" in history and "response" in history:
        headers = history["header"]
        rows = history["response"]
        if isinstance(headers, dict):
            if headers.get("error_type"):
                raise ValueError("Terminal returned an error in the history header")
            headers = headers.get("format")
        if (
            not isinstance(headers, list)
            or not all(isinstance(name, str) for name in headers)
            or len(set(headers)) != len(headers)
            or not isinstance(rows, list)
        ):
            raise ValueError("REST history must contain a column list and a row list")
        if any(not isinstance(row, list) or len(row) != len(headers) for row in rows):
            raise ValueError("REST history row width does not match its header")
        return [dict(zip(headers, row)) for row in rows]

    if isinstance(history, list) and all(isinstance(row, dict) for row in history):
        return history
    if hasattr(history, "write_json"):
        return json.loads(history.write_json())
    if hasattr(history, "to_json"):
        return json.loads(history.to_json(orient="records", date_format="iso"))
    raise ValueError(f"Unsupported history response type: {type(history).__name__}")


def get_dotenv_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / ".env"
    return Path(__file__).resolve().parent / ".env"


def _python_client():
    from thetadata import ThetaClient

    client = ThetaClient(dotenv_path=get_dotenv_path())
    # The pinned SDK doesn't expose a deadline on these methods. Set it on
    # the per-client RPC callables so gRPC cancels the underlying stream.
    client.stub.GetStockHistoryEod = partial(
        client.stub.GetStockHistoryEod, timeout=SDK_REQUEST_TIMEOUT_SECONDS
    )
    client.stub.GetStockListSymbols = partial(
        client.stub.GetStockListSymbols, timeout=SDK_REQUEST_TIMEOUT_SECONDS
    )
    return client


def _get_python_history(symbol: str, start_date: date, end_date: date) -> Any:
    from thetadata.errors import NoDataFoundError

    client = _python_client()
    try:
        return client.stock_history_eod(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )
    except NoDataFoundError:
        return []


def get_stock_symbols() -> Any:
    THETADATA_RATE_LIMITER.acquire()
    try:
        return _python_client().stock_list_symbols()
    except RateLimitExceeded:
        raise
    except Exception as error:
        logger.exception("ThetaData Python client failed to load stock symbols")
        raise RuntimeError("ThetaData could not load the stock symbol list.") from error


def get_eod_stock_history(
    symbol: str,
    start_date: date,
    end_date: date,
) -> Any:
    return fetch_stock_history(symbol, start_date, end_date).data


def validate_history_range(start_date: date, end_date: date) -> None:
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    if (end_date - start_date).days > MAX_HISTORY_DAYS:
        raise ValueError(f"date range must not exceed {MAX_HISTORY_DAYS} days")


def fetch_stock_history(symbol: str, start_date: date, end_date: date) -> StockHistory:
    if not symbol or not symbol.strip():
        raise ValueError("symbol must not be empty")
    validate_history_range(start_date, end_date)

    THETADATA_RATE_LIMITER.acquire()
    try:
        return StockHistory("sdk", _get_python_history(symbol.strip(), start_date, end_date))
    except RateLimitExceeded:
        raise
    except Exception as python_error:
        python_failure = python_error
        logger.warning(
            "ThetaData Python client failed; trying the local REST API: %s",
            python_failure,
            exc_info=True,
        )

    fallback_enabled = os.getenv(
        "THETADATA_REST_FALLBACK_ENABLED", "true"
    ).strip().lower() in {"1", "true", "yes", "on"}
    if not fallback_enabled:
        raise RuntimeError(
            "The ThetaData Python client failed and REST fallback is disabled. "
            "Restart the project and opt in to start Theta Terminal as backup."
        ) from python_failure

    THETADATA_RATE_LIMITER.acquire()
    try:
        return StockHistory("rest", get_eod(symbol.strip(), start_date, end_date))
    except RateLimitExceeded:
        raise
    except Exception as rest_error:
        raise RuntimeError(
            "ThetaData Python client and local REST fallback both failed. "
            f"Python client error: {python_failure!r}. "
            f"REST API error: {rest_error!r}. "
            "Check your ThetaData credentials and local Terminal."
        ) from rest_error
