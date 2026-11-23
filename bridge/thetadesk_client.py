"""Local calls to the ThetaDesk API. ThetaDesk owns the market store and pins."""

from __future__ import annotations

import json
from contextlib import closing
from datetime import date
from http.client import HTTPConnection, HTTPException
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from exports import bar, nonnegative_integer, object_array, text_field


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
        rows = self._bars(result, symbol, first, last)
        try:
            added = nonnegative_integer(result["added"])
            covered = result["covered_through"]
            covered = date.fromisoformat(covered) if covered is not None else None
            if covered is not None and not first <= covered <= last:
                raise ValueError("coverage outside the requested window")
        except (KeyError, ValueError, TypeError, OverflowError) as error:
            raise ThetaDeskError("ThetaDesk returned an invalid bar fetch summary.", 502) from error
        return {
            "bars": len(rows), "added": added,
            "covered_through": covered.isoformat() if covered is not None else None,
            "latest_bar": rows[-1]["session_date"] if rows else None,
        }

    def stored_bars(self, symbol: str, first: date, last: date) -> list[dict[str, Any]]:
        query = urlencode({"start_date": first.isoformat(), "end_date": last.isoformat()})
        result = self._request("GET", f"/api/v1/stocks/{quote(symbol, safe='')}/bars?{query}")
        return self._bars(result, symbol, first, last)

    @staticmethod
    def _bars(result: dict[str, Any], symbol: str, first: date, last: date) -> list[dict[str, Any]]:
        try:
            rows = {}
            for row in object_array(result["data"]):
                parsed = bar(row)
                if parsed.symbol != symbol or parsed.interval != "1d" or not first <= parsed.session_date <= last:
                    raise ValueError("unexpected symbol, interval or day")
                if parsed.session_date in rows:
                    raise ValueError("duplicate daily bar")
                rows[parsed.session_date] = {**row, "session_date": parsed.session_date.isoformat(), "close": parsed.close}
            return [rows[day] for day in sorted(rows)]
        except (KeyError, ValueError, TypeError, OverflowError) as error:
            raise ThetaDeskError("ThetaDesk returned an invalid daily bar response.", 502) from error

    def pins(self) -> list[dict[str, Any]]:
        result = self._request("GET", "/api/v1/pins")
        try:
            pins = object_array(result["pins"])
        except (KeyError, ValueError) as error:
            raise ThetaDeskError("ThetaDesk returned an invalid pin list.", 502) from error
        return [self._pin(pin) for pin in pins]

    def add_pin(self, symbol: str, first: date, last: date) -> dict[str, Any]:
        result = self._request("POST", "/api/v1/pins", {
            "symbol": symbol, "start_date": first.isoformat(), "end_date": last.isoformat(),
        })
        return self._pin(result)

    @staticmethod
    def _pin(result: dict[str, Any]) -> dict[str, Any]:
        try:
            symbol = text_field(result["symbol"], required=True).strip().upper()
            first, last = (date.fromisoformat(result[key]) for key in ("start_date", "end_date"))
            if first > last:
                raise ValueError("pin dates out of order")
        except (KeyError, ValueError, TypeError) as error:
            raise ThetaDeskError("ThetaDesk returned an invalid pin.", 502) from error
        return {"symbol": symbol, "start_date": first.isoformat(), "end_date": last.isoformat()}

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
        except (ValueError, RecursionError):
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
