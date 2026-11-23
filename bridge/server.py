"""The bridge dashboard: both apps' exports, the study, and adding tickers.

    python server.py [--port 8090] [--no-browser]

Serves http://127.0.0.1:8090 until Ctrl+C or the page's Shut down button. Adding a ticker creates its HoundDog topic
through HoundDog's own API (HoundDog must be running) and adds it to
bridge.toml.
"""

from __future__ import annotations

import argparse
import hashlib
import threading
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import DEFAULT_CONFIG, BridgeConfig, ConfigError, add_watched, normalize_symbol
from hounddog_client import HoundDogClient, HoundDogRefused, HoundDogUnavailable
from market_calendar import NyseCalendar
from overview import Overview, plain
from thetadesk_client import ThetaDeskClient, ThetaDeskError

DEFAULT_PORT = 8090
LOCAL_HOSTS = ["127.0.0.1", "localhost"]
STATIC = Path(__file__).resolve().with_name("static")
MAX_KEYWORDS = 20
MAX_NAME_LENGTH = 80
PRICE_HISTORY_DAYS = 365


class TickerRequest(BaseModel):
    symbol: str
    keywords: list[str] = Field(min_length=1, max_length=MAX_KEYWORDS)


class WatchRequest(BaseModel):
    tickers: list[TickerRequest] = Field(min_length=1, max_length=50)
    group: str | None = None


class PriceFetchRequest(BaseModel):
    refresh: bool = False
    after: date | None = None


class PinRequest(BaseModel):
    symbol: str
    start_date: date
    end_date: date


@dataclass(frozen=True)
class WatchResult:
    symbol: str
    status: str  # "created", "existing" (the HoundDog topic was already there), or "failed"
    detail: str


class ServerStop:
    """Lets the page stop the server it is served by. uvicorn then finishes the
    requests in progress, a bridge.toml update included, before exiting, as on Ctrl+C."""

    def __init__(self) -> None:
        self._server: uvicorn.Server | None = None

    def attach(self, server: uvicorn.Server) -> None:
        self._server = server

    def request(self) -> bool:
        """Ask the server to stop; False if it was not started by main()."""
        if self._server is None:
            return False
        self._server.should_exit = True
        return True


def refuse_cross_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is not None and origin != f"{request.url.scheme}://{request.headers['host']}":
        raise HTTPException(status_code=403, detail="Cross-origin requests are refused.")


def versioned_page() -> str:
    """index.html with its script and stylesheet addressed by content, so a
    browser never keeps an old copy after an update."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for name in ("app.js", "styles.css"):
        version = hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:16]
        html = html.replace(f'"/{name}"', f'"/{name}?v={version}"')
    return html


def clean_keywords(keywords: list[str]) -> list[str]:
    cleaned = [keyword.strip() for keyword in keywords if keyword.strip().strip("*")]
    if not cleaned:
        raise HTTPException(status_code=422, detail="Each ticker needs at least one keyword.")
    if any(len(keyword) > MAX_NAME_LENGTH for keyword in cleaned):
        raise HTTPException(status_code=422, detail=f"Keywords must be at most {MAX_NAME_LENGTH} characters.")
    return cleaned


def require_symbol(value: str) -> str:
    try:
        return normalize_symbol(value)
    except ConfigError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def validate_date_range(first: date, last: date) -> None:
    if first > last:
        raise HTTPException(status_code=422, detail="Start date must be on or before end date.")


def latest_closed_session() -> date:
    return NyseCalendar().latest_closed_session(datetime.now(timezone.utc))


def price_range() -> tuple[date, date]:
    last = latest_closed_session()
    return last - timedelta(days=PRICE_HISTORY_DAYS), last


def upstream_error(error: ThetaDeskError) -> HTTPException:
    headers = {"Retry-After": error.retry_after} if error.retry_after else None
    return HTTPException(status_code=error.status, detail=str(error), headers=headers)


def create_app(
    config_path: Path = DEFAULT_CONFIG,
    hounddog: Callable[[str], HoundDogClient] = HoundDogClient,
    server_stop: ServerStop | None = None,
    thetadesk: Callable[[str], ThetaDeskClient] = ThetaDeskClient,
) -> FastAPI:
    stop = server_stop if server_stop is not None else ServerStop()
    app = FastAPI(title="theta_hound bridge")
    # DNS rebinding: only requests addressed to this machine by name are served.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOCAL_HOSTS)

    def load_config() -> BridgeConfig:
        try:
            return BridgeConfig.load(config_path)
        except ConfigError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error

    def live_hounddog(config: BridgeConfig) -> dict[str, Any]:
        if not config.hounddog_url:
            return {"reachable": False, "topics": None, "error": "This config has no HoundDog connection."}
        try:
            return {"reachable": True, "topics": hounddog(config.hounddog_url).topic_names(), "error": ""}
        except (HoundDogUnavailable, HoundDogRefused) as error:
            return {"reachable": False, "topics": None, "error": str(error)}

    def market_client(config: BridgeConfig) -> ThetaDeskClient:
        if not config.thetadesk_url:
            raise HTTPException(status_code=409, detail="ThetaDesk actions are off for this Bridge configuration.")
        return thetadesk(config.thetadesk_url)

    @app.get("/api/overview")
    def overview() -> dict[str, Any]:
        config = load_config()
        data = Overview(config)
        report = data.report()
        first, last = price_range()
        return plain({
            "status": data.status(),
            "report": report,
            "watchlist": data.watchlist(report, first, last),
            "thetadesk": {"enabled": bool(config.thetadesk_url), "latest_session": last},
            "hounddog": {"url": config.hounddog_url, "enabled": bool(config.hounddog_url), **live_hounddog(config)},
            "config": {"path": config_path, "symbols": config.symbols, "groups": config.groups},
            "display": {"banner": config.banner},
        })

    @app.post("/api/watch")
    def watch(request: Request, body: WatchRequest) -> dict[str, Any]:
        refuse_cross_origin(request)
        group = (body.group or "").strip() or None
        if group is not None and len(group) > MAX_NAME_LENGTH:
            raise HTTPException(status_code=422, detail=f"Group names must be at most {MAX_NAME_LENGTH} characters.")
        try:
            tickers = [(normalize_symbol(ticker.symbol), clean_keywords(ticker.keywords)) for ticker in body.tickers]
        except ConfigError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        hounddog_url = load_config().hounddog_url
        if not hounddog_url:
            raise HTTPException(
                status_code=409, detail="Watching tickers is off: this config has no HoundDog connection.",
            )
        client = hounddog(hounddog_url)
        results: list[WatchResult] = []
        for symbol, keywords in dict(tickers).items():
            try:
                topic = client.add_topic(symbol, keywords)
            except HoundDogUnavailable as error:
                if not results:
                    raise HTTPException(status_code=502, detail=str(error)) from error
                results.append(WatchResult(symbol, "failed", str(error)))
                continue
            except HoundDogRefused as error:
                results.append(WatchResult(symbol, "failed", str(error)))
                continue
            results.append(WatchResult(
                symbol,
                "created" if topic.created else "existing",
                f"HoundDog topic {symbol} {'created' if topic.created else 'already existed; left unchanged'}.",
            ))
        watched = [result.symbol for result in results if result.status != "failed"]
        if not watched:
            raise HTTPException(status_code=400, detail="; ".join(result.detail for result in results))
        try:
            config = add_watched(config_path, watched, group)
        except (ConfigError, OSError) as error:
            raise HTTPException(status_code=500, detail=f"Could not update bridge.toml: {error}") from error
        return plain({"results": results, "config": {"symbols": config.symbols, "groups": config.groups}})

    @app.post("/api/prices/{symbol}/fetch")
    def fetch_prices(symbol: str, body: PriceFetchRequest, request: Request) -> dict[str, Any]:
        refuse_cross_origin(request)
        symbol = require_symbol(symbol)
        config = load_config()
        client = market_client(config)
        if not any(entry.symbol == symbol for entry in config.symbols):
            raise HTTPException(status_code=404, detail="Add this ticker to the Bridge watchlist first.")
        first, last = price_range()
        if body.after is not None:
            if body.after >= last:
                raise HTTPException(status_code=422, detail="The latest NYSE close is already in the requested history.")
            first = max(first, body.after + timedelta(days=1))
        try:
            result = client.fetch_bars(symbol, first, last, body.refresh)
        except ThetaDeskError as error:
            raise upstream_error(error) from error
        return plain({"symbol": symbol, "start_date": first, "end_date": last, **result})

    @app.get("/api/pins")
    def pins() -> dict[str, Any]:
        try:
            return {"pins": market_client(load_config()).pins()}
        except ThetaDeskError as error:
            raise upstream_error(error) from error

    @app.post("/api/pins", status_code=201)
    def pin(body: PinRequest, request: Request) -> dict[str, Any]:
        refuse_cross_origin(request)
        symbol = require_symbol(body.symbol)
        validate_date_range(body.start_date, body.end_date)
        try:
            return market_client(load_config()).add_pin(symbol, body.start_date, body.end_date)
        except ThetaDeskError as error:
            raise upstream_error(error) from error

    @app.get("/api/tickers/{symbol}")
    def ticker(symbol: str, start_date: date, end_date: date) -> dict[str, Any]:
        symbol = require_symbol(symbol)
        validate_date_range(start_date, end_date)
        config = load_config()
        try:
            rows = market_client(config).stored_bars(symbol, start_date, end_date)
        except ThetaDeskError as error:
            raise upstream_error(error) from error
        return {
            "study": plain(Overview(config).ticker(symbol)),
            "prices": [{"session": row["session_date"], "close": row["close"]} for row in rows],
        }

    @app.post("/api/shutdown", status_code=202)
    def shutdown(request: Request) -> dict[str, bool]:
        refuse_cross_origin(request)
        if not stop.request():
            raise HTTPException(
                status_code=409, detail="This server was not started by server.py; stop it with Ctrl+C.",
            )
        return {"stopping": True}

    @app.get("/", include_in_schema=False)
    def index() -> HTMLResponse:
        return HTMLResponse(versioned_page(), headers={"Cache-Control": "no-cache"})

    app.mount("/", StaticFiles(directory=STATIC), name="static")
    return app


def main() -> int:
    parser = argparse.ArgumentParser(description="The theta_hound bridge dashboard.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--no-browser", action="store_true", help="Do not open the dashboard in a browser.")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    print(f"Bridge dashboard: {url}")
    print("Stop with Shut down on the page, or Ctrl+C.")
    stop = ServerStop()
    server = uvicorn.Server(uvicorn.Config(
        create_app(args.config, server_stop=stop), host="127.0.0.1", port=args.port, log_level="warning",
    ))
    stop.attach(server)
    server.run()
    print("Bridge dashboard stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
