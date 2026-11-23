"""Read HoundDog's and ThetaDesk's export files into typed records.

Both apps append JSON Lines, one file per UTC day, delivered at least once
(HoundDog/INTEGRATION.md, ThetaDesk/README.md). The readers keep the first copy
of each record by the key its schema names, and skip what they cannot use (an
unknown schema, an interrupted final line, a malformed record), counting why.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from math import isfinite
from pathlib import Path
from typing import Any

FEED_READ_STATUSES = frozenset({"ok", "unchanged"})


@dataclass(frozen=True)
class TopicMatch:
    name: str
    keywords: tuple[str, ...]
    backfill: bool


@dataclass(frozen=True)
class NewsEvent:
    """hounddog.event/1: an article a check found new for one or more topics."""

    event_id: str
    check_key: str
    detected_at: datetime
    released_at: datetime | None
    source: str
    link: str
    title: str
    topics: tuple[TopicMatch, ...]


@dataclass(frozen=True)
class NewsCheck:
    """hounddog.coverage/1: one saved check. topics is None for records written
    before HoundDog listed each check's topics, so what they watched is unknown."""

    check_key: str
    started_at: datetime
    topics: frozenset[str] | None
    read_any_feed: bool
    feeds_read: int
    feeds_failed: int
    feeds_skipped: int


@dataclass(frozen=True)
class Bar:
    """theta.bar/1: one session of one symbol."""

    symbol: str
    interval: str
    session_date: date
    start_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class BarCoverage:
    """theta.coverage/1: an inclusive range of session dates ThetaDesk looked up."""

    symbol: str
    interval: str
    start_date: date
    end_date: date


@dataclass
class ReadReport:
    files: int = 0
    records: int = 0
    duplicates: int = 0
    skipped: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True)
class NewsData:
    events: tuple[NewsEvent, ...]
    checks: tuple[NewsCheck, ...]
    revisions: int
    report: ReadReport


@dataclass(frozen=True)
class MarketData:
    bars: tuple[Bar, ...]
    coverage: tuple[BarCoverage, ...]
    report: ReadReport


class MalformedRecord(ValueError):
    pass


def json_lines(directory: Path, prefix: str, report: ReadReport) -> Iterator[dict[str, Any]]:
    """Every complete record in directory/prefix-*.jsonl, oldest file first."""
    for path in sorted(directory.glob(f"{prefix}-*.jsonl")):
        report.files += 1
        lines = path.read_bytes().split(b"\n")
        if lines[-1]:
            # A writer was interrupted mid-line; the app rewrites it on its next run.
            report.skipped["incomplete final line"] += 1
        for line in lines[:-1]:
            if not line.strip():
                continue
            try:
                record = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                report.skipped["invalid JSON"] += 1
                continue
            if not isinstance(record, dict):
                report.skipped["not a JSON object"] += 1
                continue
            report.records += 1
            yield record


def utc_moment(value: Any) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.utcoffset() is None:
        raise MalformedRecord(f"time without an offset: {value!r}")
    return moment


def optional_utc_moment(value: Any) -> datetime | None:
    return None if value is None else utc_moment(value)


def check_key(record: dict[str, Any]) -> str:
    """run_id identifies a check across database resets; records written before
    HoundDog added it carry only the numeric check_id."""
    run_id = record.get("run_id")
    return str(run_id) if run_id else f"check:{int(record['check_id'])}"


def news_event(record: dict[str, Any]) -> NewsEvent:
    event_backfill = bool(record["backfill"])
    return NewsEvent(
        event_id=str(record["event_id"]),
        check_key=check_key(record),
        detected_at=utc_moment(record["detected_at"]),
        released_at=optional_utc_moment(record.get("released_at")),
        source=str(record["source"]),
        link=str(record["link"]),
        title=str(record["title"]),
        topics=tuple(
            TopicMatch(
                name=str(topic["name"]),
                keywords=tuple(str(keyword) for keyword in topic["keywords"]),
                backfill=bool(topic.get("backfill", event_backfill)),
            )
            for topic in record["topics"]
        ),
    )


def news_check(record: dict[str, Any]) -> NewsCheck:
    topics = record.get("topics")
    statuses = Counter(feed["status"] for feed in record["feeds"])
    reads = sum(statuses[status] for status in FEED_READ_STATUSES)
    return NewsCheck(
        check_key=check_key(record),
        started_at=utc_moment(record["started_at"]),
        topics=None if topics is None else frozenset(str(topic["name"]) for topic in topics),
        read_any_feed=bool(reads),
        feeds_read=reads,
        feeds_failed=statuses["failed"],
        feeds_skipped=statuses["skipped"],
    )


def bar(record: dict[str, Any]) -> Bar:
    open_price, high, low, close = (float(record[key]) for key in ("open", "high", "low", "close"))
    if not all(isfinite(price) for price in (open_price, high, low, close)):
        raise MalformedRecord("bar prices must be finite")
    return Bar(
        symbol=str(record["symbol"]).upper(),
        interval=str(record["interval"]),
        session_date=date.fromisoformat(record["session_date"]),
        start_at=utc_moment(record["start_at"]),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=int(record["volume"]),
    )


def bar_coverage(record: dict[str, Any]) -> BarCoverage:
    return BarCoverage(
        symbol=str(record["symbol"]).upper(),
        interval=str(record["interval"]),
        start_date=date.fromisoformat(record["start_date"]),
        end_date=date.fromisoformat(record["end_date"]),
    )


class FirstCopies:
    """Keeps the first record seen for each key; counts the repeats."""

    def __init__(self, report: ReadReport) -> None:
        self._report = report
        self._keys: set[tuple[Any, ...]] = set()

    def is_new(self, key: tuple[Any, ...]) -> bool:
        if key in self._keys:
            self._report.duplicates += 1
            return False
        self._keys.add(key)
        return True


def read_news(directory: Path) -> NewsData:
    report = ReadReport()
    seen = FirstCopies(report)
    events: list[NewsEvent] = []
    checks: list[NewsCheck] = []
    revisions = 0
    for record in json_lines(directory, "hounddog", report):
        schema = record.get("schema")
        try:
            if schema == "hounddog.event/1":
                event = news_event(record)
                if seen.is_new((schema, event.event_id, event.check_key)):
                    events.append(event)
            elif schema == "hounddog.coverage/1":
                check = news_check(record)
                if seen.is_new((schema, check.check_key)):
                    checks.append(check)
            elif schema == "hounddog.revision/1":
                if seen.is_new((schema, str(record["event_id"]), check_key(record))):
                    revisions += 1
            else:
                report.skipped[f"unknown schema {schema!r}"] += 1
        except (KeyError, TypeError, ValueError):
            report.skipped[f"malformed {schema}"] += 1
    return NewsData(tuple(events), tuple(checks), revisions, report)


def read_market(directory: Path) -> MarketData:
    report = ReadReport()
    seen = FirstCopies(report)
    bars: list[Bar] = []
    coverage: list[BarCoverage] = []
    for record in json_lines(directory, "theta-bars", report):
        try:
            if record.get("schema") != "theta.bar/1":
                report.skipped[f"unknown schema {record.get('schema')!r}"] += 1
                continue
            parsed = bar(record)
            if seen.is_new(("bar", parsed.symbol, parsed.interval, parsed.start_at)):
                bars.append(parsed)
        except (KeyError, TypeError, ValueError, OverflowError):
            report.skipped["malformed theta.bar/1"] += 1
    for record in json_lines(directory, "theta-coverage", report):
        try:
            if record.get("schema") != "theta.coverage/1":
                report.skipped[f"unknown schema {record.get('schema')!r}"] += 1
                continue
            parsed_range = bar_coverage(record)
            key = ("coverage", parsed_range.symbol, parsed_range.interval, parsed_range.start_date, parsed_range.end_date)
            if seen.is_new(key):
                coverage.append(parsed_range)
        except (KeyError, TypeError, ValueError):
            report.skipped["malformed theta.coverage/1"] += 1
    return MarketData(tuple(bars), tuple(coverage), report)
