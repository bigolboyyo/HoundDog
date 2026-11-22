"""HoundDog's dashboard API, used to add topics. HoundDog owns watch.toml; the
bridge never edits it directly, so HoundDog must be running."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

TIMEOUT_SECONDS = 5
CONFLICT = 409  # HoundDog's answer to a topic name that already exists


class HoundDogUnavailable(RuntimeError):
    pass


class HoundDogRefused(ValueError):
    """HoundDog answered, but refused the request; the message is its reason."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class TopicResult:
    name: str
    created: bool  # False: a topic with that name already existed and was left alone


class HoundDogClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def topic_names(self) -> list[str]:
        dashboard = self._request("GET", "/api/dashboard")
        return [str(topic["name"]) for topic in dashboard.get("topics", [])]

    def add_topic(self, name: str, keywords: list[str]) -> TopicResult:
        try:
            self._request("POST", "/api/topics", {"name": name, "keywords": keywords, "exclude": []})
        except HoundDogRefused as refusal:
            if refusal.status == CONFLICT:
                return TopicResult(name, created=False)
            raise
        return TopicResult(name, created=True)

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        request = urllib.request.Request(
            self.base_url + path,
            method=method,
            data=None if body is None else json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            try:
                message = json.loads(error.read()).get("error", "")
            except (json.JSONDecodeError, AttributeError):
                message = ""
            raise HoundDogRefused(message or f"HoundDog answered {error.code}", error.code) from error
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            raise HoundDogUnavailable(
                f"HoundDog is not reachable at {self.base_url}. Start HoundDog, then try again."
            ) from error
