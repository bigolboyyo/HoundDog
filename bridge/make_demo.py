"""Make a demo for the bridge dashboard: a year of made-up news and HoundDog
checks around real ThetaDesk prices, to see the study before real data exists.

    python bridge\\make_demo.py
    python bridge\\server.py --config bridge\\demo\\demo.toml

Everything goes in bridge\\demo\\ (rewritten each run): a HoundDog-format export
and demo.toml, which reads ThetaDesk's real store and has no HoundDog
connection. Every headline starts with [DEMO]. The news is planted: the bigger
a session's real move, the likelier it gets a demo article. So the demo shows
what a real effect looks like on the dashboard; it says nothing about markets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import ConfigError, default_thetadesk_exports, normalize_symbol, render_raw
from exports import Bar, read_market
from market_calendar import NyseCalendar

DEMO_DIR = Path(__file__).resolve().with_name("demo")
DEFAULT_SYMBOLS = ("AAPL", "MSFT", "TSLA")
COMPANIES = {"AAPL": "Apple", "MSFT": "Microsoft", "TSLA": "Tesla", "NVDA": "Nvidia", "AMZN": "Amazon"}
CHECK_EVERY = timedelta(hours=2)
OFF_STRETCH = timedelta(days=14)  # "the PC was off": no checks, so those sessions are not watched
BASE_CHANCE = 0.05
CHANCE_PER_MOVE = 12.0  # a 1% move adds 12 points of chance; a 4% move, 48
MAX_CHANCE = 0.9
BACKFILL_PER_SYMBOL = 8
UTC = timezone.utc

UP = ("{} shares climb after upbeat analyst note", "{} rallies on strong demand reports", "{} jumps as new product draws praise")
DOWN = ("{} slides after supply worries", "{} falls on regulatory concerns", "{} drops as a rival cuts prices")
FLAT = ("{} executives speak at industry conference", "{} announces leadership change", "{} updates its product roadmap")


@dataclass(frozen=True)
class DemoCheck:
    number: int
    started_at: datetime

    @property
    def run_id(self) -> str:
        return f"demo{self.number:06d}"


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def demo_event_id(link: str) -> str:
    return hashlib.sha256(link.encode("utf-8")).hexdigest()[:16]


class DemoBuilder:
    def __init__(self, symbols: Sequence[str], bars: dict[str, list[Bar]], seed: int) -> None:
        self._symbols = tuple(symbols)
        self._bars = bars
        self._random = random.Random(seed)
        self._calendar = NyseCalendar()
        self._articles = 0

    def build(self) -> list[dict[str, Any]]:
        first = min(series[0].session_date for series in self._bars.values())
        last = max(series[-1].session_date for series in self._bars.values())
        checks = self._checks(first, last)
        records: list[dict[str, Any]] = [self._coverage(check) for check in checks]
        records += self._backfill(checks[0])
        live = [article for symbol in self._symbols for article in self._live_articles(symbol, checks)]
        records += live
        records += self._repeat_detection(live, checks)
        return records

    def _checks(self, first: date, last: date) -> list[DemoCheck]:
        start = self._calendar.session(self._calendar.previous_trading_day(first)).close_at.astimezone(UTC)
        end = self._calendar.session(last).close_at.astimezone(UTC)
        off_start = start + (end - start) * 0.4
        checks, moment = [], start + timedelta(minutes=17)
        while moment <= end:
            if not off_start <= moment < off_start + OFF_STRETCH:
                checks.append(DemoCheck(len(checks) + 1, moment))
            moment += CHECK_EVERY
        return checks

    def _coverage(self, check: DemoCheck) -> dict[str, Any]:
        return {
            "schema": "hounddog.coverage/1", "check_id": check.number, "run_id": check.run_id,
            "trigger": "scheduled", "started_at": iso(check.started_at), "finished_at": iso(check.started_at),
            "topics": [{"name": symbol, "fingerprint": "demo"} for symbol in self._symbols],
            "feeds": [{"name": "Demo Wire", "url": "https://example.com/demo/rss", "status": "ok",
                       "items": 40, "new_matches": 0, "detail": ""}],
        }

    def _article(self, symbol: str, title: str, check: DemoCheck, released: datetime, backfill: bool) -> dict[str, Any]:
        self._articles += 1
        link = f"https://example.com/demo/{symbol.lower()}/{self._articles}"
        return {
            "schema": "hounddog.event/1", "event_id": demo_event_id(link), "check_id": check.number,
            "run_id": check.run_id, "trigger": "scheduled", "detected_at": iso(check.started_at),
            "released_at": iso(released), "released_raw": "", "source": "Demo Wire",
            "feed_url": "https://example.com/demo/rss", "link": link, "title": f"[DEMO] {title}",
            "summary": "Made-up article for the bridge demo.", "author": "",
            "topics": [{"name": symbol, "keywords": [COMPANIES.get(symbol, symbol)],
                        "feed_url": "https://example.com/demo/rss", "backfill": backfill}],
            "backfill": backfill,
        }

    def _backfill(self, first_check: DemoCheck) -> list[dict[str, Any]]:
        """What a feed already held when HoundDog first read it: old, so the study leaves it out."""
        return [
            self._article(
                symbol, self._random.choice(FLAT).format(COMPANIES.get(symbol, symbol)), first_check,
                first_check.started_at - timedelta(days=self._random.randint(2, 40)), backfill=True,
            )
            for symbol in self._symbols for _ in range(BACKFILL_PER_SYMBOL)
        ]

    def _live_articles(self, symbol: str, checks: list[DemoCheck]) -> list[dict[str, Any]]:
        articles = []
        times = [check.started_at for check in checks]
        series = self._bars[symbol]
        name = COMPANIES.get(symbol, symbol)
        for previous, current in zip(series, series[1:]):
            if self._calendar.previous_trading_day(current.session_date) != previous.session_date:
                continue
            change = current.close / previous.close - 1
            chance = min(MAX_CHANCE, BASE_CHANCE + CHANCE_PER_MOVE * abs(change))
            if self._random.random() >= chance:
                continue
            window_start = self._calendar.session(previous.session_date).close_at.astimezone(UTC)
            window_end = self._calendar.session(current.session_date).close_at.astimezone(UTC)
            in_window = [check for check, at in zip(checks, times) if window_start < at <= window_end]
            if not in_window:
                continue  # HoundDog was off: no one saw this session's news
            templates = UP if change > 0.01 else DOWN if change < -0.01 else FLAT
            for _ in range(self._random.randint(1, 3)):
                check = self._random.choice(in_window)
                released = check.started_at - timedelta(minutes=self._random.randint(5, 110))
                articles.append(self._article(symbol, self._random.choice(templates).format(name), check, released, False))
        return articles

    def _repeat_detection(self, live: list[dict[str, Any]], checks: list[DemoCheck]) -> list[dict[str, Any]]:
        """One article seen again by a later check, as after History retention.
        The study counts each article once, at its first detection."""
        if not live:
            return []
        original = live[len(live) // 2]
        later = next((check for check in checks
                      if check.started_at > datetime.fromisoformat(original["detected_at"]) + timedelta(days=3)), None)
        if later is None:
            return []
        repeat = dict(original, check_id=later.number, run_id=later.run_id, detected_at=iso(later.started_at))
        return [repeat]


def demo_config(symbols: Sequence[str], thetadesk_exports: str) -> dict[str, Any]:
    return {
        "inputs": {"hounddog_exports": "exports", "thetadesk_exports": thetadesk_exports},
        "hounddog": {"url": ""},
        "display": {"banner": "DEMO DATA: real ThetaDesk prices with made-up news. The demo news is planted "
                              "on big-move days, so these results show the dashboard, not the market."},
        "symbols": [{"symbol": symbol, "topics": [symbol]} for symbol in symbols],
        "groups": [{"name": "Demo group", "symbols": list(symbols)}],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the bridge demo (made-up news around real prices).")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS), help="Comma-separated tickers.")
    parser.add_argument("--seed", type=int, default=7, help="Same seed, same demo.")
    parser.add_argument("--thetadesk", type=Path, help="ThetaDesk's exports folder (default: its store).")
    parser.add_argument("--out", type=Path, default=DEMO_DIR, help="Folder for the demo (default: bridge/demo).")
    args = parser.parse_args(argv)
    try:
        symbols = list(dict.fromkeys(normalize_symbol(symbol) for symbol in args.symbols.split(",")))
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    thetadesk = args.thetadesk or default_thetadesk_exports()
    market = read_market(thetadesk)
    bars = {symbol: sorted((bar for bar in market.bars if bar.symbol == symbol and bar.interval == "1d"),
                           key=lambda bar: bar.session_date) for symbol in symbols}
    missing = [symbol for symbol, series in bars.items() if len(series) < 2]
    if missing:
        print(f"error: no ThetaDesk prices for {', '.join(missing)} in {thetadesk}. "
              "Load their history in ThetaDesk first.", file=sys.stderr)
        return 1

    records = DemoBuilder(symbols, bars, args.seed).build()
    exports = args.out / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    for old in exports.glob("hounddog-*.jsonl"):
        old.unlink()
    (exports / "hounddog-demo.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8",
    )
    config = demo_config(symbols, str(args.thetadesk.resolve()) if args.thetadesk else "")
    (args.out / "demo.toml").write_text(render_raw(config), encoding="utf-8")
    live = sum(1 for record in records if record["schema"] == "hounddog.event/1" and not record["backfill"])
    print(f"Demo written to {args.out}: {live} live articles for {', '.join(symbols)}.")
    print(f"View it: python {Path(__file__).with_name('server.py')} --config {args.out / 'demo.toml'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
