"""The first daily study: do a symbol's sessions move more, or trade more, when
HoundDog found news about it?

For each symbol:
- A session's move is its close against the previous session's close, so news
  from the prior close up to this close (overnight, pre-market, or during the
  session) belongs to it (NyseCalendar.session_for).
- A news session has at least one live (not backfill) article for one of the
  symbol's HoundDog topics. Each article counts once, at its first detection.
- A quiet session has none, and HoundDog was watching: at least one check that
  read a feed and listed one of the symbol's topics ran between the previous
  close and this close. Sessions HoundDog did not watch are left out, because
  "no news found" there means nothing.
- Volume is compared as a ratio to the symbol's median session volume.

A group pools its members' sessions: each member's news and quiet sessions
count once per member, against that member's own median volume.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime
from statistics import mean, median

from exports import Bar, BarCoverage, NewsCheck, NewsEvent
from market_calendar import NyseCalendar

DAILY = "1d"
SMALL_SAMPLE = 10
NEWS, QUIET, UNWATCHED = "news", "quiet", "unwatched"


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
class PlacedEvent:
    """An article, the topic it matched first, and the session it belongs to."""

    event_id: str
    topic: str
    title: str
    link: str
    detected_at: datetime
    session: date
    has_move: bool


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
    sessions: tuple[SessionPoint, ...]
    notes: tuple[str, ...]


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


class DailyStudy:
    def __init__(
        self,
        calendar: NyseCalendar,
        events: tuple[NewsEvent, ...],
        checks: tuple[NewsCheck, ...],
        bars: tuple[Bar, ...],
        coverage: tuple[BarCoverage, ...],
    ) -> None:
        self._calendar = calendar
        self._events = events
        self._checks = sorted((check for check in checks if check.read_any_feed), key=lambda c: c.started_at)
        self._bars = bars
        self._coverage = coverage

    def run(self, symbol: StudySymbol) -> SymbolStudy:
        bars = {bar.session_date: bar for bar in self._bars if bar.symbol == symbol.symbol and bar.interval == DAILY}
        scheduled = self._scheduled_sessions(symbol.symbol)
        moved = [day for day in scheduled if self._has_move(day, bars)]
        events = self._placed_events(symbol, set(moved))
        news_days = {event.session for event in events}
        watching = self._check_times(symbol.topics)
        median_volume = median(bars[day].volume for day in moved) if moved else 0
        points = tuple(
            SessionPoint(
                session=day,
                close=bars[day].close,
                change=bars[day].close / bars[self._calendar.previous_trading_day(day)].close - 1,
                volume_ratio=bars[day].volume / median_volume if median_volume else None,
                kind=NEWS if day in news_days else QUIET if self._watched(day, watching) else UNWATCHED,
            )
            for day in moved
        )
        news = [point for point in points if point.kind == NEWS]
        notes = self._notes(symbol, bars, scheduled, events) + small_sample_note(len(news))
        return SymbolStudy(
            symbol=symbol.symbol,
            topics=symbol.topics,
            news=group_stats(news),
            quiet=group_stats([point for point in points if point.kind == QUIET]),
            unwatched_sessions=sum(1 for point in points if point.kind == UNWATCHED),
            missing_bars=tuple(day for day in scheduled if day not in bars),
            events=tuple(events),
            sessions=points,
            notes=tuple(notes),
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

    def _scheduled_sessions(self, symbol: str) -> list[date]:
        """Trading days ThetaDesk looked up; outside these, a missing bar is unknown."""
        days: set[date] = set()
        for covered in self._coverage:
            if covered.symbol == symbol and covered.interval == DAILY:
                days.update(self._calendar.trading_days(covered.start_date, covered.end_date))
        return sorted(days)

    def _has_move(self, day: date, bars: dict[date, Bar]) -> bool:
        previous = bars.get(self._calendar.previous_trading_day(day))
        return day in bars and previous is not None and previous.close > 0

    def _placed_events(self, symbol: StudySymbol, moved: set[date]) -> list[PlacedEvent]:
        """Each article once, at its earliest detection for any of the symbol's
        topics; dropped if that first detection was backfill."""
        first: dict[str, tuple[NewsEvent, str, bool]] = {}
        for event in self._events:
            for match in event.topics:
                if match.name not in symbol.topics:
                    continue
                known = first.get(event.event_id)
                if known is None or event.detected_at < known[0].detected_at:
                    first[event.event_id] = (event, match.name, match.backfill)
        placed = []
        for event, topic, backfill in sorted(first.values(), key=lambda entry: entry[0].detected_at):
            if backfill:
                continue
            session = self._calendar.session_for(event.detected_at).day
            placed.append(PlacedEvent(
                event.event_id, topic, event.title, event.link, event.detected_at, session, session in moved,
            ))
        return placed

    def _check_times(self, topics: tuple[str, ...]) -> list[datetime]:
        """Start times, in order, of the checks that read a feed and listed one of
        these topics."""
        return [
            check.started_at for check in self._checks
            if check.topics is not None and not check.topics.isdisjoint(topics)
        ]

    def _watched(self, day: date, check_times: list[datetime]) -> bool:
        """At least one such check ran after the previous close, up to this close."""
        window_end = self._calendar.session(day).close_at
        window_start = self._calendar.session(self._calendar.previous_trading_day(day)).close_at
        return bisect_right(check_times, window_end) > bisect_right(check_times, window_start)

    def _notes(
        self, symbol: StudySymbol, bars: dict[date, Bar], scheduled: list[date], events: list[PlacedEvent],
    ) -> list[str]:
        notes = []
        if not bars:
            notes.append(f"No ThetaDesk bars for {symbol.symbol}. Load its history in ThetaDesk first.")
        elif not scheduled:
            notes.append(
                f"ThetaDesk has bars for {symbol.symbol} but no record of which dates it looked up "
                "(its theta-coverage files), so its sessions cannot be checked for gaps and are left out."
            )
        if not any(check.topics is not None and not check.topics.isdisjoint(symbol.topics) for check in self._checks):
            names = ", ".join(symbol.topics)
            notes.append(
                f"No HoundDog check has watched {names} yet. Add a HoundDog topic with that name, "
                "and the study starts counting from its first check."
            )
        pending = sum(1 for event in events if not event.has_move)
        if pending:
            notes.append(f"{pending} article(s) belong to sessions without a stored move yet (future or missing bars).")
        return notes
