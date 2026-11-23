import argparse
import ipaddress
import logging
import os
import sqlite3
import threading
from datetime import date
from functools import lru_cache
from hashlib import sha256
from math import ceil
from pathlib import Path as FilePath
from typing import Any

import uvicorn
from dotenv import dotenv_values, load_dotenv, set_key, unset_key
from fastapi import FastAPI, HTTPException, Path, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from market_store import (
    BarFetchResult,
    HistoryFormatError,
    LoadedSymbol,
    Pin,
    add_pin,
    fetch_daily_bars,
    list_pins,
    loaded_symbols,
    remove_pins,
    stored_daily_bars,
)
from rate_limit import RateLimitExceeded
from theta_data import (
    THETADATA_RATE_LIMITER,
    get_eod_stock_history,
    get_dotenv_path,
    get_stock_symbols,
    records_from_history,
    validate_history_range,
)


logger = logging.getLogger(__name__)
load_dotenv(get_dotenv_path())

app = FastAPI(title="ThetaData API", version="0.1.0")
# DNS rebinding: a remote page can reach this server through the browser under
# its own host name, and the loopback check on the credential endpoints cannot
# tell. Only requests addressed to this machine by name are served.
LOCAL_HOSTS = ["127.0.0.1", "localhost"]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOCAL_HOSTS)
# The dashboard is served from this server, so no other origin needs access.
# FRONTEND_ORIGIN can allow a separate development frontend to GET data; the
# credential routes refuse other origins regardless.
frontend_origins = [
    origin.strip()
    for origin in os.getenv("FRONTEND_ORIGIN", "").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
    expose_headers=[
        "Retry-After",
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset-After",
    ],
)


class StockHistoryResponse(BaseModel):
    symbol: str
    start_date: date
    end_date: date
    data: list[dict[str, Any]]


class StockSymbolListResponse(BaseModel):
    symbols: list[str]


class DailyBarFetchRequest(BaseModel):
    start_date: date
    end_date: date
    refresh: bool = False


class CredentialStatusResponse(BaseModel):
    """What is saved, never the secrets themselves. The email address is shown
    so the user can see which account is saved."""

    api_key_configured: bool
    credentials_configured: bool
    email: str


class CredentialSettingsUpdate(BaseModel):
    """Blank fields keep what is saved; removing needs an explicit clear flag."""

    api_key: str = ""
    email: str = ""
    password: str = ""
    clear_api_key: bool = False
    clear_credentials: bool = False


class CredentialSettingsSavedResponse(CredentialStatusResponse):
    saved: bool


class ShutdownResponse(BaseModel):
    stopping: bool


class LoadedSymbolListResponse(BaseModel):
    symbols: list[LoadedSymbol]


class PinListResponse(BaseModel):
    pins: list[Pin]


class PinRemovedResponse(BaseModel):
    removed: int


class ServerStop:
    """Lets the dashboard stop the server it is served by. uvicorn then finishes
    the requests in progress, a bar fetch included, before exiting, as on Ctrl+C."""

    def __init__(self) -> None:
        self._server: uvicorn.Server | None = None

    def attach(self, server: uvicorn.Server) -> None:
        self._server = server

    def request(self) -> bool:
        """Ask the server to stop; False if it was not started by serve()."""
        if self._server is None:
            return False
        self._server.should_exit = True
        return True


SERVER_STOP = ServerStop()


@lru_cache(maxsize=1)
def _cached_stock_symbols() -> tuple[str, ...]:
    records = records_from_history(get_stock_symbols())
    symbols = []
    for record in records:
        normalized_fields = {
            name.lower().replace("_", "").replace("-", ""): name
            for name in record
        }
        field = next(
            (
                normalized_fields[name]
                for name in ("symbol", "root", "ticker", "underlying")
                if name in normalized_fields
            ),
            None,
        )
        if field is None and len(record) == 1:
            field = next(iter(record))
        if field is None:
            raise ValueError("Stock symbol data has no recognizable symbol column")
        value = record[field]
        if value is not None and str(value).strip():
            symbols.append(str(value).strip().upper())
    return tuple(sorted(set(symbols)))


def _rate_limit_headers() -> dict[str, str]:
    status = THETADATA_RATE_LIMITER.snapshot()
    return {
        "X-RateLimit-Limit": str(status.limit),
        "X-RateLimit-Remaining": str(status.remaining),
        "X-RateLimit-Reset-After": str(ceil(status.reset_after_seconds)),
    }


def _set_rate_limit_headers(response: Response) -> None:
    response.headers.update(_rate_limit_headers())


def _rate_limit_error(error: RateLimitExceeded) -> HTTPException:
    headers = _rate_limit_headers()
    headers["Retry-After"] = str(max(1, ceil(error.retry_after_seconds)))
    return HTTPException(status_code=429, detail=str(error), headers=headers)


def _require_loopback_client(request: Request, operation: str = "Credential settings") -> None:
    client = request.client
    try:
        is_loopback = client is not None and ipaddress.ip_address(
            client.host
        ).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise HTTPException(
            status_code=403,
            detail=f"{operation} are available only from this device.",
        )


def _refuse_cross_origin(request: Request, detail: str) -> None:
    origin = request.headers.get("origin")
    if origin is not None and origin != f"{request.url.scheme}://{request.headers['host']}":
        raise HTTPException(status_code=403, detail=detail)


@app.get(
    "/api/v1/stocks/{symbol}/history",
    response_model=StockHistoryResponse,
)
def stock_history(
    response: Response,
    symbol: str = Path(min_length=1),
    start_date: date = Query(),
    end_date: date = Query(),
) -> StockHistoryResponse:
    try:
        validate_history_range(start_date, end_date)
        history = get_eod_stock_history(symbol, start_date, end_date)
    except RateLimitExceeded as error:
        raise _rate_limit_error(error) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        logger.exception("ThetaData history request failed")
        raise HTTPException(
            status_code=502,
            detail="ThetaData request failed; check backend logs for details.",
        ) from error

    try:
        records = records_from_history(history)
    except ValueError as error:
        logger.exception("Could not serialize ThetaData history")
        raise HTTPException(
            status_code=502,
            detail="ThetaData returned an unsupported history format.",
        ) from error

    _set_rate_limit_headers(response)
    return StockHistoryResponse(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        data=records,
    )


@app.post("/api/v1/stocks/{symbol}/bars/fetch")
def fetch_bars(
    options: DailyBarFetchRequest,
    request: Request,
    response: Response,
    symbol: str = Path(min_length=1),
) -> BarFetchResult:
    _require_loopback_client(request, "Daily bar fetches")
    _refuse_cross_origin(request, "Cross-origin bar fetches are refused.")

    try:
        result = fetch_daily_bars(symbol, options.start_date, options.end_date, refresh=options.refresh)
    except RateLimitExceeded as error:
        raise _rate_limit_error(error) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (OSError, sqlite3.Error) as error:
        logger.exception("Could not write the local market store or export")
        raise HTTPException(status_code=500, detail="Could not write the local market store or export.") from error
    except HistoryFormatError as error:
        logger.exception("Could not normalize ThetaData history")
        raise HTTPException(status_code=502, detail="ThetaData returned an unsupported history format.") from error
    except RuntimeError as error:
        logger.exception("ThetaData bar fetch failed")
        raise HTTPException(status_code=502, detail="ThetaData request failed; check backend logs for details.") from error

    _set_rate_limit_headers(response)
    return result


@app.get("/api/v1/stocks/symbols", response_model=StockSymbolListResponse)
def stock_symbols(response: Response) -> StockSymbolListResponse:
    try:
        symbols = _cached_stock_symbols()
    except RateLimitExceeded as error:
        raise _rate_limit_error(error) from error
    except (RuntimeError, ValueError) as error:
        logger.exception("Could not load stock symbols")
        raise HTTPException(
            status_code=502,
            detail="ThetaData could not load the stock symbol list.",
        ) from error

    _set_rate_limit_headers(response)
    return StockSymbolListResponse(symbols=list(symbols))


def _store_error() -> HTTPException:
    logger.exception("Could not use the local market store")
    return HTTPException(status_code=500, detail="Could not use the local market store.")


@app.get("/api/v1/stocks/loaded", response_model=LoadedSymbolListResponse)
def stock_loaded() -> LoadedSymbolListResponse:
    """Tickers with bars already stored, so they open without a ThetaData call."""
    try:
        return LoadedSymbolListResponse(symbols=loaded_symbols())
    except (OSError, sqlite3.Error) as error:
        raise _store_error() from error


@app.get("/api/v1/stocks/{symbol}/bars", response_model=StockHistoryResponse)
def stored_bars(
    symbol: str = Path(min_length=1),
    start_date: date = Query(),
    end_date: date = Query(),
) -> StockHistoryResponse:
    """Stored daily bars only; never calls ThetaData."""
    try:
        rows = stored_daily_bars(symbol, start_date, end_date)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (OSError, sqlite3.Error) as error:
        raise _store_error() from error
    return StockHistoryResponse(symbol=symbol.strip().upper(), start_date=start_date, end_date=end_date, data=rows)


@app.get("/api/v1/pins", response_model=PinListResponse)
def pins() -> PinListResponse:
    try:
        return PinListResponse(pins=list_pins())
    except (OSError, sqlite3.Error) as error:
        raise _store_error() from error


@app.post("/api/v1/pins", response_model=Pin, status_code=201)
def pin(body: Pin, request: Request) -> Pin:
    _require_loopback_client(request, "Pin changes")
    _refuse_cross_origin(request, "Cross-origin pin changes are refused.")
    try:
        return add_pin(body.symbol, body.start_date, body.end_date)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (OSError, sqlite3.Error) as error:
        raise _store_error() from error


@app.delete("/api/v1/pins/{symbol}/{start_date}/{end_date}", response_model=PinRemovedResponse)
def unpin(request: Request, symbol: str, start_date: date, end_date: date) -> PinRemovedResponse:
    _require_loopback_client(request, "Pin changes")
    _refuse_cross_origin(request, "Cross-origin pin changes are refused.")
    try:
        return PinRemovedResponse(removed=remove_pins(Pin(symbol, start_date, end_date)))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (OSError, sqlite3.Error) as error:
        raise _store_error() from error


@app.delete("/api/v1/pins", response_model=PinRemovedResponse)
def unpin_all(request: Request) -> PinRemovedResponse:
    _require_loopback_client(request, "Pin changes")
    _refuse_cross_origin(request, "Cross-origin pin changes are refused.")
    try:
        return PinRemovedResponse(removed=remove_pins())
    except (OSError, sqlite3.Error) as error:
        raise _store_error() from error


# One credential change at a time, so two saves cannot interleave their files.
CREDENTIALS_LOCK = threading.Lock()


def _saved_credentials(dotenv_path: FilePath) -> tuple[str, str, str]:
    """The saved API key, email and password; blanks where none is saved."""
    api_key = os.getenv("THETADATA_API_KEY") or dotenv_values(dotenv_path).get("THETADATA_API_KEY") or ""
    credentials_path = dotenv_path.with_name("creds.txt")
    if credentials_path.is_file():
        lines = credentials_path.read_text(encoding="utf-8").splitlines()
        if len(lines) >= 2 and lines[0].strip() and lines[1].strip():
            return api_key, lines[0].strip(), lines[1].strip()
    return api_key, "", ""


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@app.get(
    "/api/v1/settings/credentials",
    response_model=CredentialStatusResponse,
)
def get_credential_settings(
    request: Request,
    response: Response,
) -> CredentialStatusResponse:
    _require_loopback_client(request)
    _refuse_cross_origin(request, "Credentials are available only to this dashboard.")
    try:
        api_key, email, password = _saved_credentials(get_dotenv_path())
    except OSError as error:
        logger.exception("Could not read local credential settings")
        raise HTTPException(
            status_code=500,
            detail="Could not read credential settings from the app folder.",
        ) from error

    _no_store(response)
    return CredentialStatusResponse(
        api_key_configured=bool(api_key),
        credentials_configured=bool(email and password),
        email=email,
    )


@app.put(
    "/api/v1/settings/credentials",
    response_model=CredentialSettingsSavedResponse,
)
def save_credential_settings(
    settings: CredentialSettingsUpdate,
    request: Request,
    response: Response,
) -> CredentialSettingsSavedResponse:
    _require_loopback_client(request)
    _refuse_cross_origin(request, "Credentials can be changed only from this dashboard.")
    for label, value in (("API key", settings.api_key), ("Email", settings.email), ("Password", settings.password)):
        if "\n" in value or "\r" in value:
            raise HTTPException(status_code=422, detail=f"{label} must be a single line.")
    new_key = settings.api_key.strip()
    new_email = settings.email.strip()
    new_password = settings.password.strip()
    if settings.clear_api_key and new_key:
        raise HTTPException(status_code=422, detail="Enter a new API key or remove the saved one, not both.")
    if settings.clear_credentials and (new_email or new_password):
        raise HTTPException(status_code=422, detail="Enter new account details or remove the saved ones, not both.")

    dotenv_path = get_dotenv_path()
    credentials_path = dotenv_path.with_name("creds.txt")
    with CREDENTIALS_LOCK:
        try:
            api_key, email, password = _saved_credentials(dotenv_path)
        except OSError as error:
            logger.exception("Could not read local credential settings")
            raise HTTPException(
                status_code=500,
                detail="Could not read credential settings from the app folder.",
            ) from error
        if settings.clear_credentials:
            email = password = ""
        elif new_password:
            if not new_email and not email:
                raise HTTPException(status_code=422, detail="Enter the email address for this password.")
            email, password = new_email or email, new_password
        elif new_email:
            if not password:
                raise HTTPException(status_code=422, detail="Enter the password for this email address.")
            email = new_email
        if settings.clear_api_key:
            api_key = ""
        elif new_key:
            api_key = new_key

        try:
            if settings.clear_api_key:
                if dotenv_path.is_file():
                    unset_key(str(dotenv_path), "THETADATA_API_KEY")
                os.environ.pop("THETADATA_API_KEY", None)
            elif new_key:
                set_key(str(dotenv_path), "THETADATA_API_KEY", new_key)
                os.environ["THETADATA_API_KEY"] = new_key
            if settings.clear_credentials:
                credentials_path.unlink(missing_ok=True)
            elif new_email or new_password:
                # Written whole and then swapped in, so a failure leaves the old file.
                partial = credentials_path.with_name("creds.txt.tmp")
                partial.write_text(f"{email}\n{password}\n", encoding="utf-8")
                os.replace(partial, credentials_path)
        except OSError as error:
            logger.exception("Could not save local credential settings")
            raise HTTPException(
                status_code=500,
                detail="Could not save credential settings to the app folder.",
            ) from error

    _no_store(response)
    return CredentialSettingsSavedResponse(
        saved=True,
        api_key_configured=bool(api_key),
        credentials_configured=bool(email and password),
        email=email,
    )


@app.post("/api/v1/shutdown", status_code=202)
def shutdown(request: Request) -> ShutdownResponse:
    _require_loopback_client(request, "Shutdowns")
    _refuse_cross_origin(request, "Cross-origin shutdowns are refused.")
    if not SERVER_STOP.request():
        raise HTTPException(
            status_code=409,
            detail="This server was not started by ThetaDesk; stop it with Ctrl+C.",
        )
    return ShutdownResponse(stopping=True)


FRONTEND = FilePath(__file__).resolve().parent / "frontend"


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/index.html", methods=["GET", "HEAD"], include_in_schema=False)
def dashboard_page() -> HTMLResponse:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    for name in ("app.js", "styles.css"):
        version = sha256((FRONTEND / name).read_bytes()).hexdigest()[:16]
        html = html.replace(f'"/{name}"', f'"/{name}?v={version}"')
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")


def serve(host: str, port: int) -> None:
    """Run the dashboard until Ctrl+C or its Shut down button."""
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info"))
    SERVER_STOP.attach(server)
    server.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Serve the ThetaDesk API and dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    options = parser.parse_args()
    serve(options.host, options.port)
