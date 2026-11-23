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
from datetime import date, datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any

from market_calendar import NyseCalendar

FEED_READ_STATUSES = frozenset({"ok", "unchanged"})
FEED_STATUSES = FEED_READ_STATUSES | {"failed", "skipped"}
MAX_STORE_INTEGER = 2**63 - 1


@dataclass(frozen=True)
class TopicMatch:
    name: str
    keywords: tuple[str, ...]
    backfill: bool
    feed_url: str | None = None


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
    feed_url: str | None = None


@dataclass(frozen=True)
class NewsRevision:
    event_id: str
    check_key: str
    observed_at: datetime
    title: str
    released_at: datetime | None
    previous_title: str
    previous_released_at: datetime | None
    changed: tuple[str, ...]


@dataclass(frozen=True)
class FeedCheck:
    name: str | None
    url: str | None
    status: str
    items: int | None
    new_matches: int | None
    backfill: bool | None
    detail: str | None


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
    finished_at: datetime | None = None
    trigger: str | None = None
    feeds: tuple[FeedCheck, ...] = ()
    topic_fingerprints: dict[str, str] = field(default_factory=dict)


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
    recorded_at: datetime | None = None


@dataclass(frozen=True)
class BarCoverage:
    """theta.coverage/1: an inclusive range of session dates ThetaDesk looked up."""

    symbol: str
    interval: str
    start_date: date
    end_date: date
    recorded_at: datetime | None = None


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
    revisions: tuple[NewsRevision, ...]
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
        try:
            lines = path.read_bytes().split(b"\n")
        except OSError:
            report.skipped["unreadable file"] += 1
            continue
        if lines[-1]:
            # A writer was interrupted mid-line; the app rewrites it on its next run.
            report.skipped["incomplete final line"] += 1
        for line in lines[:-1]:
            if not line.strip():
                continue
            try:
                record = json.loads(line.decode("utf-8"))
            except (ValueError, RecursionError):
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
    return moment.astimezone(timezone.utc)


def optional_utc_moment(value: Any) -> datetime | None:
    return None if value is None else utc_moment(value)


def text_field(value: Any, *, required: bool = False) -> str:
    if not isinstance(value, str) or (required and not value.strip()):
        raise MalformedRecord("expected text")
    # Reject lone escaped surrogates that a consumer cannot encode as UTF-8.
    value.encode("utf-8")
    return value


def optional_text(value: Any) -> str | None:
    return None if value is None else text_field(value)


def array_field(value: Any) -> list:
    if not isinstance(value, list):
        raise MalformedRecord("expected an array")
    return value


def object_array(value: Any) -> list[dict]:
    entries = array_field(value)
    if not all(isinstance(entry, dict) for entry in entries):
        raise MalformedRecord("expected an array of objects")
    return entries


def nonnegative_integer(value: Any) -> int:
    number = int(value)
    if (
        isinstance(value, bool) or not 0 <= number <= MAX_STORE_INTEGER
        or (not isinstance(value, str) and value != number)
    ):
        raise MalformedRecord("expected a nonnegative integer")
    return number


def boolean_field(value: Any) -> bool:
    if not isinstance(value, bool):
        raise MalformedRecord("expected a boolean")
    return value


def check_key(record: dict[str, Any]) -> str:
    """run_id identifies a check across database resets; records written before
    HoundDog added it carry only the numeric check_id."""
    run_id = record.get("run_id")
    if run_id is None or run_id == "":
        return f"check:{nonnegative_integer(record['check_id'])}"
    return text_field(run_id, required=True)


def news_event(record: dict[str, Any]) -> NewsEvent:
    event_backfill = boolean_field(record["backfill"])
    return NewsEvent(
        event_id=text_field(record["event_id"], required=True),
        check_key=check_key(record),
        detected_at=utc_moment(record["detected_at"]),
        released_at=optional_utc_moment(record.get("released_at")),
        source=text_field(record["source"]),
        link=text_field(record["link"], required=True),
        title=text_field(record["title"]),
        topics=tuple(
            TopicMatch(
                name=text_field(topic["name"], required=True),
                keywords=tuple(text_field(keyword) for keyword in array_field(topic["keywords"])),
                backfill=boolean_field(topic.get("backfill", event_backfill)),
                feed_url=optional_text(topic.get("feed_url")),
            )
            for topic in object_array(record["topics"])
        ),
        feed_url=optional_text(record.get("feed_url")),
    )


def news_revision(record: dict[str, Any]) -> NewsRevision:
    return NewsRevision(
        event_id=text_field(record["event_id"], required=True),
        check_key=check_key(record),
        observed_at=utc_moment(record["observed_at"]),
        title=text_field(record["title"]),
        released_at=optional_utc_moment(record.get("released_at")),
        previous_title=text_field(record["previous_title"]),
        previous_released_at=optional_utc_moment(record.get("previous_released_at")),
        changed=tuple(text_field(name) for name in array_field(record["changed"])),
    )


def feed_check(feed: dict[str, Any]) -> FeedCheck:
    status = text_field(feed["status"])
    if status not in FEED_STATUSES:
        raise MalformedRecord("unknown feed status")
    return FeedCheck(
        status=status, name=optional_text(feed.get("name")), url=optional_text(feed.get("url")),
        items=nonnegative_integer(feed["items"]) if feed.get("items") is not None else None,
        new_matches=nonnegative_integer(feed["new_matches"]) if feed.get("new_matches") is not None else None,
        backfill=boolean_field(feed["backfill"]) if feed.get("backfill") is not None else None,
        detail=optional_text(feed.get("detail")),
    )


def news_check(record: dict[str, Any]) -> NewsCheck:
    topics = None if record.get("topics") is None else object_array(record["topics"])
    feeds = tuple(feed_check(feed) for feed in object_array(record["feeds"]))
    statuses = Counter(feed.status for feed in feeds)
    reads = sum(statuses[status] for status in FEED_READ_STATUSES)
    return NewsCheck(
        check_key=check_key(record),
        started_at=utc_moment(record["started_at"]),
        topics=None if topics is None else frozenset(text_field(topic["name"], required=True) for topic in topics),
        read_any_feed=bool(reads),
        feeds_read=reads,
        feeds_failed=statuses["failed"],
        feeds_skipped=statuses["skipped"],
        finished_at=optional_utc_moment(record.get("finished_at")),
        trigger=optional_text(record.get("trigger")),
        feeds=feeds,
        topic_fingerprints={
            text_field(topic["name"], required=True): text_field(topic["fingerprint"])
            for topic in topics or () if topic.get("fingerprint") is not None
        },
    )


def bar(record: dict[str, Any]) -> Bar:
    raw_prices = [record[key] for key in ("open", "high", "low", "close")]
    if any(isinstance(value, bool) for value in raw_prices):
        raise MalformedRecord("bar prices must be numeric")
    open_price, high, low, close = (float(value) for value in raw_prices)
    if not all(isfinite(price) and price > 0 for price in (open_price, high, low, close)):
        raise MalformedRecord("bar prices must be finite and positive")
    if not low <= min(open_price, close) <= max(open_price, close) <= high:
        raise MalformedRecord("bar prices are outside the low-to-high range")
    return Bar(
        symbol=text_field(record["symbol"], required=True).strip().upper(),
        interval=text_field(record["interval"], required=True),
        session_date=date.fromisoformat(record["session_date"]),
        start_at=utc_moment(record["start_at"]),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=nonnegative_integer(record["volume"]),
        recorded_at=optional_utc_moment(record.get("recorded_at")),
    )


def bar_coverage(record: dict[str, Any]) -> BarCoverage:
    first = date.fromisoformat(record["start_date"])
    last = date.fromisoformat(record["end_date"])
    if first > last:
        raise MalformedRecord("start_date must be on or before end_date")
    return BarCoverage(
        symbol=text_field(record["symbol"], required=True).strip().upper(),
        interval=text_field(record["interval"], required=True),
        start_date=first,
        end_date=last,
        recorded_at=optional_utc_moment(record.get("recorded_at")),
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
    revisions: list[NewsRevision] = []
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
                revision = news_revision(record)
                if seen.is_new((schema, revision.event_id, revision.check_key)):
                    revisions.append(revision)
            else:
                report.skipped[f"unknown schema {schema!r}"] += 1
        except (KeyError, TypeError, ValueError, OverflowError):
            report.skipped[f"malformed {schema}"] += 1
    return NewsData(tuple(events), tuple(checks), tuple(revisions), report)


def read_market(directory: Path) -> MarketData:
    report = ReadReport()
    seen = FirstCopies(report)
    calendar = NyseCalendar()
    bars: list[Bar] = []
    coverage: list[BarCoverage] = []
    for record in json_lines(directory, "theta-bars", report):
        try:
            if record.get("schema") != "theta.bar/1":
                report.skipped[f"unknown schema {record.get('schema')!r}"] += 1
                continue
            parsed = bar(record)
            if parsed.interval == "1d":
                if parsed.start_at.astimezone(calendar.zone).date() != parsed.session_date:
                    raise MalformedRecord("daily open does not match the New York session date")
                if parsed.recorded_at is not None:
                    earliest = parsed.start_at
                    if calendar.is_trading_day(parsed.session_date):
                        earliest = calendar.session(parsed.session_date).close_at
                    if parsed.recorded_at < earliest:
                        raise MalformedRecord("daily bar was recorded before its session ended")
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
            if (
                parsed_range.recorded_at is not None
                and parsed_range.recorded_at.astimezone(calendar.zone).date() < parsed_range.end_date
            ):
                raise MalformedRecord("lookup was recorded before its covered range ended")
            key = ("coverage", parsed_range.symbol, parsed_range.interval, parsed_range.start_date, parsed_range.end_date)
            if seen.is_new(key):
                coverage.append(parsed_range)
        except (KeyError, TypeError, ValueError, OverflowError):
            report.skipped["malformed theta.coverage/1"] += 1
    return MarketData(tuple(bars), tuple(coverage), report)
