"""Versioned, read-only data for research clients."""

from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from exports import MarketData, NewsData, ReadReport
from study import DAILY, StudySymbol
from timeline import TimelineEntry, ticker_timeline

RESEARCH_SCHEMA = "thetahound.research/1"


def source_quality(directory: Path, report: ReadReport) -> dict[str, Any]:
    return {
        "found": directory.is_dir(),
        "files": report.files,
        "records": report.records,
        "duplicates": report.duplicates,
        "skipped": dict(sorted(report.skipped.items())),
    }


def feed_id(url: str | None) -> str | None:
    return sha256(url.encode("utf-8")).hexdigest()[:24] if url else None


def article_link(link: str) -> str | None:
    try:
        parts = urlsplit(link)
        if parts.scheme in {"http", "https"} and parts.hostname and parts.username is None:
            return link
    except ValueError:
        pass
    return None


def check_data(data: dict[str, Any]) -> dict[str, Any]:
    feeds = [
        {**{key: value for key, value in feed.items() if key not in {"url", "detail"}},
         "feed_id": feed_id(feed["url"])}
        for feed in data["feeds"]
    ]
    return {**data, "feeds": feeds}


def detection_data(data: dict[str, Any]) -> dict[str, Any]:
    article = {key: value for key, value in data.items() if key not in {"feed_url", "topics", "first_detected_at"}}
    return {**article, "link": article_link(data["link"]), "feed_id": feed_id(data["feed_url"]), "matches": {}}


def add_entry(records: dict[str, dict[str, Any]], symbol: str, entry: TimelineEntry) -> None:
    if entry.id not in records:
        data = entry.data
        if entry.kind == "check":
            data = check_data(data)
        elif entry.kind == "detection":
            data = detection_data(data)
        records[entry.id] = {
            "id": entry.id,
            "kind": entry.kind,
            "producer": "thetadesk" if entry.kind in {"bar", "lookup"} else "hounddog",
            "observed_at": entry.observed_at,
            "symbols": [],
            "data": data,
        }
    record = records[entry.id]
    record["symbols"].append(symbol)
    if entry.kind == "detection":
        record["data"]["matches"][symbol] = {
            "first_detected_at": entry.data["first_detected_at"],
            "topics": [
                {**{key: value for key, value in match.items() if key != "feed_url"},
                 "feed_id": feed_id(match["feed_url"])}
                for match in entry.data["topics"]
            ],
        }


def research_bundle(
    tickers: tuple[StudySymbol, ...],
    news: NewsData,
    market: MarketData,
    start_at: datetime,
    end_at: datetime,
    sessions: tuple[date, date] | None,
) -> dict[str, Any]:
    records: dict[str, dict[str, Any]] = {}
    series = []
    for ticker in tickers:
        timeline = ticker_timeline(ticker, news, market, start_at, end_at)
        for entry in timeline.entries:
            add_entry(records, ticker.symbol, entry)
        series.append({
            "symbol": ticker.symbol,
            "topics": ticker.topics,
            "unknown_timestamps": timeline.unknown_timestamps,
        })

    reference = None
    if sessions is not None:
        first, last = sessions
        symbols = {ticker.symbol for ticker in tickers}
        bars = [bar for bar in market.bars if (
            bar.interval == DAILY and bar.symbol in symbols and first <= bar.session_date <= last
        )]
        reference = {
            "start_date": first, "end_date": last,
            "bars": sorted(bars, key=lambda bar: (bar.symbol, bar.session_date, bar.start_at)),
        }
    return {
        "schema": RESEARCH_SCHEMA,
        "start_at": start_at,
        "end_at": end_at,
        "series": series,
        "entries": sorted(records.values(), key=lambda row: (row["observed_at"], row["kind"], row["id"])),
        "reference_bars": reference,
    }
