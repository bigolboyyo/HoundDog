"""The first daily study: do a symbol's sessions move more, or trade more, when
HoundDog found news about it?

For each symbol:
- A session's move is its close against the previous session's close. News
  from the prior close up to this close belongs to it (NyseCalendar.session_for).
  Friday at or after the close through Sunday is displayed as weekend news.
- A news session has at least one live (not backfill) article for one of the
  symbol's HoundDog topics. Each article counts once, at its first detection.
- A quiet session has none, and HoundDog was watching: at least one check that
  read a feed and listed one of the symbol's topics ran outside the weekend
  between the previous close and this close. Sessions HoundDog did not watch
  are left out.
- Volume is compared as a ratio to the symbol's median session volume.

A group pools its members' sessions: each member's news and quiet sessions
count once per member, against that member's own median volume.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from math import isfinite
from statistics import mean, median

from exports import Bar, BarCoverage, NewsCheck, NewsEvent
from market_calendar import NyseCalendar

DAILY = "1d"
SMALL_SAMPLE = 10
NEWS, QUIET, UNWATCHED = "news", "quiet", "unwatched"
MISSING_BAR, MISSING_PREVIOUS_BAR = "missing_bar", "missing_previous_bar"
INVALID_PREVIOUS_CLOSE, OUTSIDE_COVERAGE = "invalid_previous_close", "outside_coverage"
BEFORE_PRICE_HISTORY, FIRST_PRICE_SESSION = "before_price_history", "first_price_session"
NO_PRICE_HISTORY = "no_price_history"
IN_STUDY, AWAITING_CLOSE = "in_study", "awaiting_close"


@dataclass(frozen=True)
class StudySymbol:
    symbol: str
    topics: tuple[str, ...]


@dataclass(frozen=True)
class SymbolGroup:
    name: str
    symbols: tuple[str, ...]


@dataclass(frozen=True)
class SessionPoint:
    """One session with a move: its close, the move, and how the study counts it."""

    session: date
    close: float
    change: float
    volume_ratio: float | None
    kind: str


@dataclass(frozen=True)
class ClosingPrice:
    session: date
    close: float


@dataclass(frozen=True)
class CheckDay:
    day: date
    checks: int
    feeds_read: int
    feeds_failed: int
    feeds_skipped: int


@dataclass(frozen=True)
class ExcludedSession:
    session: date
    close: float | None
    reason: str


@dataclass(frozen=True)
class ArticleDetection:
    event_id: str
    topic: str
    title: str
    link: str
    detected_at: datetime


@dataclass(frozen=True)
class PlacedEvent(ArticleDetection):
    """An article and its trading session."""

    session: date
    has_move: bool
    placement: str
    exclusion: str | None
    price_status: str


@dataclass(frozen=True)
class ExcludedEvent(ArticleDetection):
    reason: str


@dataclass(frozen=True)
class GroupStats:
    sessions: int
    mean_abs_change: float | None
    mean_volume_ratio: float | None


@dataclass(frozen=True)
class SymbolStudy:
    symbol: str
    topics: tuple[str, ...]
    news: GroupStats
    quiet: GroupStats
    unwatched_sessions: int
    missing_bars: tuple[date, ...]
    events: tuple[PlacedEvent, ...]
    weekend_events: tuple[ArticleDetection, ...]
    sessions: tuple[SessionPoint, ...]
    notes: tuple[str, ...]
    excluded_sessions: tuple[ExcludedSession, ...]
    excluded_events: tuple[ExcludedEvent, ...]
    verdict: str
    prices: tuple[ClosingPrice, ...]
    check_days: tuple[CheckDay, ...]
    first_check_session: date | None


@dataclass(frozen=True)
class GroupStudy:
    name: str
    symbols: tuple[str, ...]
    news: GroupStats
    quiet: GroupStats
    unwatched_sessions: int
    notes: tuple[str, ...]


def group_stats(points: list[SessionPoint]) -> GroupStats:
    if not points:
        return GroupStats(0, None, None)
    ratios = [point.volume_ratio for point in points if point.volume_ratio is not None]
    return GroupStats(len(points), mean(abs(point.change) for point in points), mean(ratios) if ratios else None)


def small_sample_note(news_sessions: int) -> list[str]:
    if 0 < news_sessions < SMALL_SAMPLE:
        return [f"Only {news_sessions} news session(s): far too few to tell a real effect from chance."]
    return []


def move_verdict(news: GroupStats, quiet: GroupStats) -> str:
    if news.mean_abs_change is None or quiet.mean_abs_change is None:
        return "Need both news and quiet sessions to compare moves."
    news_move = f"{news.mean_abs_change:.2%}"
    quiet_move = f"{quiet.mean_abs_change:.2%}"
    if news_move == quiet_move:
        comparison = "Average moves were equal at the displayed precision."
    else:
        direction = "larger" if news.mean_abs_change > quiet.mean_abs_change else "smaller"
        comparison = f"Average moves were {direction} on news days."
    if min(news.sessions, quiet.sessions) < SMALL_SAMPLE:
        return f"Small sample. {comparison}"
    return comparison


class DailyStudy:
    def __init__(
        self,
        calendar: NyseCalendar,
        events: tuple[NewsEvent, ...],
        checks: tuple[NewsCheck, ...],
        bars: tuple[Bar, ...],
        coverage: tuple[BarCoverage, ...],
        *,
        latest_closed_session: date | None = None,
    ) -> None:
        self._calendar = calendar
        self._latest_closed_session = latest_closed_session or calendar.latest_closed_session(datetime.now(timezone.utc))
        self._events = sorted(events, key=lambda event: event.detected_at)
        self._checks = sorted(checks, key=lambda check: check.started_at)
        self._bars = bars
        self._coverage = coverage

    def run(self, symbol: StudySymbol) -> SymbolStudy:
        bars = {bar.session_date: bar for bar in self._bars if bar.symbol == symbol.symbol and bar.interval == DAILY}
        first_price = min(bars, default=None)
        scheduled = self._scheduled_sessions(symbol.symbol, first_price) if first_price is not None else []
        moved: dict[date, Bar] = {}
        excluded: dict[date, ExcludedSession] = {}
        for day in scheduled:
            bar = bars.get(day)
            previous = bars.get(self._calendar.previous_trading_day(day))
            if bar is None:
                excluded[day] = ExcludedSession(day, None, MISSING_BAR)
            elif previous is None:
                reason = FIRST_PRICE_SESSION if day == first_price else MISSING_PREVIOUS_BAR
                excluded[day] = ExcludedSession(day, bar.close, reason)
            elif previous.close <= 0 or not isfinite(bar.close / previous.close):
                excluded[day] = ExcludedSession(day, bar.close, INVALID_PREVIOUS_CLOSE)
            else:
                moved[day] = previous
        events, weekend_events, excluded_events = self._place_events(symbol, moved, excluded, first_price)
        news_days = {event.session for event in events}
        checks = [
            check for check in self._checks
            if check.topics is not None and not check.topics.isdisjoint(symbol.topics)
        ]
        weekday_checks = [check for check in checks if not self._calendar.is_weekend_window(check.started_at)]
        watching = [check.started_at for check in weekday_checks if check.read_any_feed]
        median_volume = median(bars[day].volume for day in moved) if moved else 0
        points = tuple(
            SessionPoint(
                session=day,
                close=bars[day].close,
                change=bars[day].close / previous.close - 1,
                volume_ratio=bars[day].volume / median_volume if median_volume else None,
                kind=NEWS if day in news_days else QUIET if self._watched(day, watching) else UNWATCHED,
            )
            for day, previous in moved.items()
        )
        news = group_stats([point for point in points if point.kind == NEWS])
        quiet = group_stats([point for point in points if point.kind == QUIET])
        notes = self._notes(symbol, bars, scheduled, bool(checks), bool(watching))
        notes += small_sample_note(news.sessions)
        return SymbolStudy(
            symbol=symbol.symbol,
            topics=symbol.topics,
            news=news,
            quiet=quiet,
            unwatched_sessions=sum(1 for point in points if point.kind == UNWATCHED),
            missing_bars=tuple(day for day, entry in excluded.items() if entry.reason == MISSING_BAR),
            events=tuple(events),
            weekend_events=tuple(weekend_events),
            sessions=points,
            notes=tuple(notes),
            excluded_sessions=tuple(excluded.values()),
            excluded_events=tuple(excluded_events),
            verdict=move_verdict(news, quiet),
            prices=tuple(ClosingPrice(day, bar.close) for day, bar in sorted(bars.items())),
            check_days=self._check_days(checks),
            first_check_session=self._check_session(weekday_checks[0].started_at) if weekday_checks else None,
        )

    @staticmethod
    def run_group(group: SymbolGroup, studies: dict[str, SymbolStudy]) -> GroupStudy:
        members = [studies[symbol] for symbol in group.symbols if symbol in studies]
        points = [point for study in members for point in study.sessions]
        news = [point for point in points if point.kind == NEWS]
        notes = []
        absent = [symbol for symbol in group.symbols if symbol not in studies]
        if absent:
            notes.append(f"Not studied, so left out: {', '.join(absent)}. Add them as [[symbols]] in bridge.toml.")
        return GroupStudy(
            name=group.name,
            symbols=group.symbols,
            news=group_stats(news),
            quiet=group_stats([point for point in points if point.kind == QUIET]),
            unwatched_sessions=sum(1 for point in points if point.kind == UNWATCHED),
            notes=tuple(notes + small_sample_note(len(news))),
        )

    def _scheduled_sessions(self, symbol: str, first_price: date) -> list[date]:
        """Trading days ThetaDesk looked up from the first saved close onward."""
        days: set[date] = set()
        for covered in self._coverage:
            if covered.symbol == symbol and covered.interval == DAILY:
                days.update(self._calendar.trading_days(max(first_price, covered.start_date), covered.end_date))
        return sorted(days)

    def _place_events(
        self, symbol: StudySymbol, moved: dict[date, Bar], excluded: dict[date, ExcludedSession], first_price: date | None,
    ) -> tuple[list[PlacedEvent], list[ArticleDetection], list[ExcludedEvent]]:
        """Keep the earliest match per article in its trading session or weekend."""
        placed = []
        weekend = []
        excluded_events = []
        seen: set[str] = set()
        for event in self._events:
            # One check can find the article through both a new feed/topic and
            # a live one. Prefer a live match from that same first detection.
            match = min(
                (match for match in event.topics if match.name in symbol.topics),
                key=lambda match: match.backfill,
                default=None,
            )
            if match is None:
                continue
            details = (event.event_id, match.name, event.title, event.link, event.detected_at)
            repeated = event.event_id in seen
            seen.add(event.event_id)
            if repeated or match.backfill:
                excluded_events.append(ExcludedEvent(
                    *details, "repeat_detection" if repeated else "backfill",
                ))
                continue
            if self._calendar.is_weekend_window(event.detected_at):
                weekend.append(ArticleDetection(*details))
                continue
            session = self._calendar.session_for(event.detected_at).day
            detected_day = event.detected_at.astimezone(self._calendar.zone).date()
            if session == detected_day:
                placement = "before_close"
            elif self._calendar.is_trading_day(detected_day):
                placement = "at_or_after_close"
            else:
                placement = "market_closed"
            if session in moved:
                exclusion = None
            elif first_price is None:
                exclusion = NO_PRICE_HISTORY
            elif session < first_price:
                exclusion = BEFORE_PRICE_HISTORY
            elif session == first_price:
                exclusion = FIRST_PRICE_SESSION
            else:
                exclusion = excluded[session].reason if session in excluded else OUTSIDE_COVERAGE
            if exclusion is None:
                price_status = IN_STUDY
            else:
                price_status = AWAITING_CLOSE if session > self._latest_closed_session else exclusion
            placed.append(PlacedEvent(
                *details, session, exclusion is None, placement, exclusion, price_status,
            ))
        return placed, weekend, excluded_events

    def _check_days(self, checks: list[NewsCheck]) -> tuple[CheckDay, ...]:
        by_day: dict[date, list[NewsCheck]] = defaultdict(list)
        for check in checks:
            by_day[check.started_at.astimezone(self._calendar.zone).date()].append(check)
        return tuple(
            CheckDay(
                day=day,
                checks=len(entries),
                feeds_read=sum(check.feeds_read for check in entries),
                feeds_failed=sum(check.feeds_failed for check in entries),
                feeds_skipped=sum(check.feeds_skipped for check in entries),
            )
            for day, entries in sorted(by_day.items())
        )

    def _check_session(self, moment: datetime) -> date:
        local = moment.astimezone(self._calendar.zone)
        day = local.date()
        if self._calendar.is_trading_day(day) and local <= self._calendar.session(day).close_at:
            return day
        return self._calendar.next_trading_day(day)

    def _watched(self, day: date, check_times: list[datetime]) -> bool:
        """At least one such check ran after the previous close, up to this close."""
        window_end = self._calendar.session(day).close_at
        window_start = self._calendar.session(self._calendar.previous_trading_day(day)).close_at
        return bisect_right(check_times, window_end) > bisect_right(check_times, window_start)

    def _notes(
        self, symbol: StudySymbol, bars: dict[date, Bar], scheduled: list[date],
        has_checks: bool, has_weekday_coverage: bool,
    ) -> list[str]:
        notes = []
        if not bars:
            notes.append(f"No ThetaDesk bars for {symbol.symbol}. Load its history in ThetaDesk first.")
        elif not scheduled:
            notes.append(
                f"ThetaDesk has bars for {symbol.symbol} but no record of which dates it looked up in that price history "
                "(its theta-coverage files), so its sessions cannot be checked for gaps and are left out."
            )
        if not has_weekday_coverage:
            names = ", ".join(symbol.topics)
            if has_checks:
                notes.append(f"No qualifying weekday HoundDog check for {names} yet.")
            else:
                notes.append(
                    f"No HoundDog check has watched {names} yet. Add a HoundDog topic with that name, "
                    "and the study starts counting from its first check."
                )
        return notes
