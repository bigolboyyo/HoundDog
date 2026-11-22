"""What the CLI prints and the dashboard shows: both read it from here."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from config import BridgeConfig
from exports import MarketData, NewsData, ReadReport, read_market, read_news
from market_calendar import NyseCalendar
from study import DailyStudy, GroupStudy, SymbolStudy


@dataclass(frozen=True)
class SymbolBars:
    symbol: str
    bars: int
    first: date
    last: date


@dataclass(frozen=True)
class NewsStatus:
    folder: Path
    found: bool
    events: int
    live_events: int
    checks: int
    first_check: datetime | None
    last_check: datetime | None
    topics_watched: tuple[str, ...]
    revisions: int
    read: ReadReport


@dataclass(frozen=True)
class MarketStatus:
    folder: Path
    found: bool
    symbols: tuple[SymbolBars, ...]
    read: ReadReport


@dataclass(frozen=True)
class Status:
    hounddog: NewsStatus
    thetadesk: MarketStatus


@dataclass(frozen=True)
class Report:
    symbols: tuple[SymbolStudy, ...]
    groups: tuple[GroupStudy, ...]


class Overview:
    """Both exports, read once."""

    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self.news: NewsData = read_news(config.hounddog_exports)
        self.market: MarketData = read_market(config.thetadesk_exports)

    def status(self) -> Status:
        news, market = self.news, self.market
        checks = [check.started_at for check in news.checks]
        symbols = []
        for symbol in sorted({bar.symbol for bar in market.bars}):
            days = [bar.session_date for bar in market.bars if bar.symbol == symbol]
            symbols.append(SymbolBars(symbol, len(days), min(days), max(days)))
        return Status(
            NewsStatus(
                folder=self.config.hounddog_exports,
                found=self.config.hounddog_exports.is_dir(),
                events=len(news.events),
                live_events=sum(1 for event in news.events if not all(match.backfill for match in event.topics)),
                checks=len(news.checks),
                first_check=min(checks, default=None),
                last_check=max(checks, default=None),
                topics_watched=tuple(sorted({topic for check in news.checks if check.topics for topic in check.topics})),
                revisions=news.revisions,
                read=news.report,
            ),
            MarketStatus(
                folder=self.config.thetadesk_exports,
                found=self.config.thetadesk_exports.is_dir(),
                symbols=tuple(symbols),
                read=market.report,
            ),
        )

    def report(self) -> Report:
        study = DailyStudy(NyseCalendar(), self.news.events, self.news.checks, self.market.bars, self.market.coverage)
        symbols = {symbol.symbol: study.run(symbol) for symbol in self.config.symbols}
        groups = tuple(DailyStudy.run_group(group, symbols) for group in self.config.groups)
        return Report(tuple(symbols.values()), groups)


def plain(value: Any) -> Any:
    """JSON-ready copy of the bridge's dataclasses, dates, paths, and counters."""
    if is_dataclass(value) and not isinstance(value, type):
        return plain(asdict(value))
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [plain(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value
