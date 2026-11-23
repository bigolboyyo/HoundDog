"""What the CLI prints and the dashboard shows: both read it from here."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from config import BridgeConfig
from exports import MarketData, NewsData, ReadReport, read_market, read_news
from market_calendar import NyseCalendar
from research import research_bundle, source_quality
from study import DAILY, DailyStudy, GroupStudy, StudySymbol, SymbolStudy
from timeline import Timeline, ticker_timeline


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


@dataclass(frozen=True)
class WatchlistEntry:
    symbol: str
    last_close: float | None
    price_session: date | None
    last_check: datetime | None
    news: int
    quiet: int
    missing_bars: int


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
                revisions=len(news.revisions),
                read=news.report,
            ),
            MarketStatus(
                folder=self.config.thetadesk_exports,
                found=self.config.thetadesk_exports.is_dir(),
                symbols=tuple(symbols),
                read=market.report,
            ),
        )

    def report(self, *, latest_closed_session: date | None = None) -> Report:
        study = self.daily_study(latest_closed_session=latest_closed_session)
        symbols = {symbol.symbol: study.run(symbol) for symbol in self.config.symbols}
        groups = tuple(DailyStudy.run_group(group, symbols) for group in self.config.groups)
        return Report(tuple(symbols.values()), groups)

    def daily_study(self, *, latest_closed_session: date | None = None) -> DailyStudy:
        return DailyStudy(
            NyseCalendar(), self.news.events, self.news.checks, self.market.bars, self.market.coverage,
            latest_closed_session=latest_closed_session,
        )

    def ticker(self, symbol: str) -> SymbolStudy:
        return self.daily_study().run(self._study_symbol(symbol))

    def timeline(self, symbol: str, start_at: datetime, end_at: datetime) -> Timeline:
        return ticker_timeline(self._study_symbol(symbol), self.news, self.market, start_at, end_at)

    def research(
        self, symbols: tuple[str, ...], start_at: datetime, end_at: datetime, sessions: tuple[date, date] | None,
    ) -> dict[str, Any]:
        tickers = tuple(self._study_symbol(symbol) for symbol in symbols) if symbols else self.config.symbols
        return {
            **research_bundle(tickers, self.news, self.market, start_at, end_at, sessions),
            "quality": {
                "hounddog": {
                    **source_quality(self.config.hounddog_exports, self.news.report),
                    "checks_with_unknown_topics": sum(check.topics is None for check in self.news.checks),
                },
                "thetadesk": source_quality(self.config.thetadesk_exports, self.market.report),
            },
        }

    def _study_symbol(self, symbol: str) -> StudySymbol:
        configured = next((entry for entry in self.config.symbols if entry.symbol == symbol), None)
        return configured or StudySymbol(symbol, (symbol,))

    def watchlist(self, report: Report, first: date, last: date) -> tuple[WatchlistEntry, ...]:
        latest = {}
        for bar in self.market.bars:
            current = latest.get(bar.symbol)
            if bar.interval == DAILY and (current is None or bar.session_date > current.session_date):
                latest[bar.symbol] = bar
        last_checks = {}
        for check in self.news.checks:
            if check.read_any_feed:
                for topic in check.topics or ():
                    if topic not in last_checks or check.started_at > last_checks[topic]:
                        last_checks[topic] = check.started_at
        return tuple(
            WatchlistEntry(
                study.symbol, latest[study.symbol].close if study.symbol in latest else None,
                latest[study.symbol].session_date if study.symbol in latest else None,
                max((last_checks[topic] for topic in study.topics if topic in last_checks), default=None),
                study.news.sessions, study.quiet.sessions,
                sum(first <= day <= last for day in study.missing_bars),
            )
            for study in report.symbols
        )


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
