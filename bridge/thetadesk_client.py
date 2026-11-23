"""Local calls to the ThetaDesk API. ThetaDesk owns the market store and pins."""

from __future__ import annotations

import json
from contextlib import closing
from datetime import date
from http.client import HTTPConnection, HTTPException
from typing import Any
from urllib.parse import quote, urlencode, urlsplit


class ThetaDeskError(RuntimeError):
    def __init__(self, detail: str, status: int, retry_after: str | None = None) -> None:
        super().__init__(detail)
        self.status = status
        self.retry_after = retry_after


class ThetaDeskClient:
    def __init__(self, url: str) -> None:
        target = urlsplit(url)
        self.host = target.hostname
        self.port = target.port

    def fetch_bars(self, symbol: str, first: date, last: date, refresh: bool) -> dict[str, Any]:
        payload = {"start_date": first.isoformat(), "end_date": last.isoformat(), "refresh": refresh}
        result = self._request("POST", f"/api/v1/stocks/{quote(symbol, safe='')}/bars/fetch", payload, timeout=90)
        if not isinstance(result.get("data"), list):
            raise ThetaDeskError("ThetaDesk returned an unexpected bar response.", 502)
        return {
            "bars": len(result["data"]), "added": result.get("added"),
            "covered_through": result.get("covered_through"),
            "latest_bar": result["data"][-1]["session_date"] if result["data"] else None,
        }

    def stored_bars(self, symbol: str, first: date, last: date) -> list[dict[str, Any]]:
        query = urlencode({"start_date": first.isoformat(), "end_date": last.isoformat()})
        result = self._request("GET", f"/api/v1/stocks/{quote(symbol, safe='')}/bars?{query}")
        if not isinstance(result.get("data"), list):
            raise ThetaDeskError("ThetaDesk returned an unexpected bar response.", 502)
        return result["data"]

    def pins(self) -> list[dict[str, Any]]:
        result = self._request("GET", "/api/v1/pins")
        if not isinstance(result.get("pins"), list):
            raise ThetaDeskError("ThetaDesk returned an unexpected pin response.", 502)
        return result["pins"]

    def add_pin(self, symbol: str, first: date, last: date) -> dict[str, Any]:
        return self._request("POST", "/api/v1/pins", {
            "symbol": symbol, "start_date": first.isoformat(), "end_date": last.isoformat(),
        })

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None, *, timeout: int = 5,
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode()
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        try:
            with closing(HTTPConnection(self.host, self.port, timeout=timeout)) as connection:
                connection.request(method, path, body, headers)
                response = connection.getresponse()
                raw = response.read()
        except TimeoutError as error:
            raise ThetaDeskError("ThetaDesk did not answer in time. Refresh to check for saved progress.", 504) from error
        except (OSError, HTTPException) as error:
            raise ThetaDeskError("ThetaDesk is unavailable. Start it and try again.", 503) from error
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            result = None
        if response.status >= 400:
            detail = result.get("detail") if isinstance(result, dict) else None
            if not isinstance(detail, str):
                detail = f"ThetaDesk returned HTTP {response.status}."
            retry_after = response.getheader("Retry-After")
            raise ThetaDeskError(detail, response.status, retry_after if retry_after and retry_after.isascii()
                                 and retry_after.isdecimal() else None)
        if not 200 <= response.status < 300 or not isinstance(result, dict):
            raise ThetaDeskError("ThetaDesk returned an unexpected response.", 502)
        return result
