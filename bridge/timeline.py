"""Replay the producer timestamps for a ticker from saved exports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Any

from exports import Bar, BarCoverage, MarketData, NewsData, NewsRevision
from study import DAILY, StudySymbol

TIMELINE_SCHEMA = "thetahound.timeline/1"


@dataclass(frozen=True)
class TimelineEntry:
    id: str
    kind: str
    observed_at: datetime
    data: Bar | BarCoverage | NewsRevision | dict[str, Any]


@dataclass(frozen=True)
class Timeline:
    schema: str
    symbol: str
    topics: tuple[str, ...]
    start_at: datetime
    end_at: datetime
    entries: tuple[TimelineEntry, ...]
    unknown_timestamps: dict[str, int]


def ticker_timeline(
    ticker: StudySymbol, news: NewsData, market: MarketData, start_at: datetime, end_at: datetime,
) -> Timeline:
    entries: list[TimelineEntry] = []
    unknown = {"check": 0, "bar": 0, "lookup": 0}
    topics = set(ticker.topics)
    first_detection: dict[str, datetime] = {}

    for event in sorted(news.events, key=lambda event: event.detected_at):
        if event.detected_at >= end_at:
            break
        matches = tuple(match for match in event.topics if match.name in topics)
        if not matches:
            continue
        first = first_detection.setdefault(event.event_id, event.detected_at)
        if event.detected_at >= start_at:
            entries.append(TimelineEntry(
                f"detection:{event.event_id}:{event.check_key}", "detection", event.detected_at,
                {**asdict(replace(event, topics=matches)), "first_detected_at": first},
            ))

    for revision in news.revisions:
        first = first_detection.get(revision.event_id)
        if first is not None and first <= revision.observed_at and start_at <= revision.observed_at < end_at:
            entries.append(TimelineEntry(
                f"revision:{revision.event_id}:{revision.check_key}", "revision", revision.observed_at, revision,
            ))

    for check in news.checks:
        if check.topics is None or check.topics.isdisjoint(topics):
            continue
        if check.finished_at is None or check.finished_at < check.started_at:
            unknown["check"] += 1
        elif start_at <= check.finished_at < end_at:
            entries.append(TimelineEntry(
                f"check:{check.check_key}", "check", check.finished_at,
                {**asdict(check), "topics": sorted(check.topics)},
            ))

    for bar in market.bars:
        if bar.symbol != ticker.symbol or bar.interval != DAILY:
            continue
        if bar.recorded_at is None:
            unknown["bar"] += 1
        elif start_at <= bar.recorded_at < end_at:
            entries.append(TimelineEntry(
                f"bar:{bar.symbol}:{bar.interval}:{bar.start_at.isoformat()}", "bar", bar.recorded_at, bar,
            ))

    for lookup in market.coverage:
        if lookup.symbol != ticker.symbol or lookup.interval != DAILY:
            continue
        if lookup.recorded_at is None:
            unknown["lookup"] += 1
        elif start_at <= lookup.recorded_at < end_at:
            entries.append(TimelineEntry(
                f"lookup:{lookup.symbol}:{lookup.interval}:{lookup.start_date}:{lookup.end_date}",
                "lookup", lookup.recorded_at, lookup,
            ))

    entries.sort(key=lambda entry: (entry.observed_at, entry.kind, entry.id))
    return Timeline(TIMELINE_SCHEMA, ticker.symbol, ticker.topics, start_at, end_at, tuple(entries), unknown)
