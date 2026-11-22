"""Small export files in the shape HoundDog and ThetaDesk write."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc


def moment(text: str) -> str:
    """'2026-11-16 15:00' in UTC, as the exports write it."""
    return datetime.fromisoformat(text).replace(tzinfo=UTC).isoformat()


def coverage(check_id: int, started: str, topics: list[str] | None, status: str = "ok") -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema": "hounddog.coverage/1", "check_id": check_id, "run_id": f"run{check_id}",
        "trigger": "scheduled", "started_at": moment(started), "finished_at": moment(started),
        "feeds": [{"name": "Wire", "url": "https://wire.example/rss", "status": status,
                   "items": 10, "new_matches": 0, "detail": ""}],
    }
    if topics is not None:
        record["topics"] = [{"name": name, "fingerprint": "f"} for name in topics]
    return record


def event(
    check_id: int, detected: str, link: str, topics: list[str], backfill: bool = False, title: str = "Headline",
) -> dict[str, Any]:
    return {
        "schema": "hounddog.event/1", "event_id": link.rsplit("/", 1)[-1], "check_id": check_id,
        "run_id": f"run{check_id}", "trigger": "scheduled", "detected_at": moment(detected),
        "released_at": None, "released_raw": "", "source": "Wire", "feed_url": "https://wire.example/rss",
        "link": link, "title": title, "summary": "", "author": "",
        "topics": [{"name": name, "keywords": [name.lower()], "feed_url": "https://wire.example/rss",
                    "backfill": backfill} for name in topics],
        "backfill": backfill,
    }


def bar(symbol: str, session: date, close: float, volume: int = 1000) -> dict[str, Any]:
    return {
        "schema": "theta.bar/1", "symbol": symbol, "interval": "1d", "session_date": session.isoformat(),
        "start_at": f"{session.isoformat()}T14:30:00+00:00", "open": close, "high": close, "low": close,
        "close": close, "volume": volume, "provider": "sdk",
    }


def bar_coverage(symbol: str, first: date, last: date) -> dict[str, Any]:
    return {"schema": "theta.coverage/1", "symbol": symbol, "interval": "1d",
            "start_date": first.isoformat(), "end_date": last.isoformat()}


def write_lines(path: Path, records: list[dict[str, Any]], tail: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records) + tail, encoding="utf-8")
