"""theta_hound bridge: joins HoundDog's news export with ThetaDesk's market export.

    python bridge.py status [--config PATH] [--json]
    python bridge.py report [--config PATH] [--json]

It only reads the two apps' export folders, never their databases. The
dashboard (server.py) shows the same results.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from zoneinfo import ZoneInfoNotFoundError

from config import DEFAULT_CONFIG, BridgeConfig, ConfigError
from exports import ReadReport
from overview import Overview, Report, Status, plain
from study import GroupStats

EXIT_OK, EXIT_CONFIG = 0, 2


def percent(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.2f}%"


def ratio(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}x"


def read_summary(read: ReadReport) -> str:
    skipped = ", ".join(f"{count} {reason}" for reason, count in read.skipped.items()) or "none"
    return f"{read.records} records in {read.files} file(s); {read.duplicates} duplicate(s); skipped: {skipped}"


def print_status(status: Status) -> None:
    news, market = status.hounddog, status.thetadesk
    for name, folder, found, read in (
        ("HoundDog", news.folder, news.found, news.read), ("ThetaDesk", market.folder, market.found, market.read),
    ):
        print(f"{name}: {folder}{'' if found else '  (folder not found)'}")
        print(f"  {read_summary(read)}")
    print(f"  News: {news.events} article events ({news.live_events} live), "
          f"{news.checks} checks, {news.revisions} revisions")
    if news.first_check and news.last_check:
        print(f"  Checks from {news.first_check:%Y-%m-%d %H:%M} to {news.last_check:%Y-%m-%d %H:%M} UTC")
    print(f"  Topics watched: {', '.join(news.topics_watched) or 'none listed yet'}")
    for symbol in market.symbols:
        print(f"  Bars: {symbol.symbol} {symbol.bars} sessions, {symbol.first} to {symbol.last}")
    if not market.symbols:
        print("  Bars: none yet")


def print_stats_table(rows: tuple[tuple[str, GroupStats], ...]) -> None:
    print(f"  {'':16}{'sessions':>9}{'avg |move|':>12}{'volume':>9}")
    for label, group in rows:
        print(f"  {label:16}{group.sessions:>9}{percent(group.mean_abs_change):>12}{ratio(group.mean_volume_ratio):>9}")


def print_report(report: Report) -> None:
    if not report.symbols:
        print("No symbols configured. Add [[symbols]] entries to bridge.toml.")
    for study in report.symbols:
        print(f"{study.symbol} (HoundDog topics: {', '.join(study.topics)})")
        print_stats_table((("news sessions", study.news), ("quiet sessions", study.quiet)))
        print(f"  Not watched by HoundDog: {study.unwatched_sessions} session(s). Missing bars: {len(study.missing_bars)}.")
        for event in study.events[-5:]:
            print(f"  - {event.session}: [{event.topic}] {event.title}")
        for note in study.notes:
            print(f"  Note: {note}")
        print()
    for group in report.groups:
        print(f"Group {group.name} ({', '.join(group.symbols)})")
        print_stats_table((("news sessions", group.news), ("quiet sessions", group.quiet)))
        print(f"  Not watched by HoundDog: {group.unwatched_sessions} session(s).")
        for note in group.notes:
            print(f"  Note: {note}")
        print()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Join HoundDog news with ThetaDesk market data.")
    parser.add_argument("command", choices=["status", "report"])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    args = parser.parse_args(argv)
    try:
        overview = Overview(BridgeConfig.load(args.config))
        result = overview.status() if args.command == "status" else overview.report()
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_CONFIG
    except ZoneInfoNotFoundError:
        print("error: no time zone data. Install it with: python -m pip install -r requirements.txt", file=sys.stderr)
        return EXIT_CONFIG
    if args.json:
        print(json.dumps(plain(result), indent=2))
    elif isinstance(result, Status):
        print_status(result)
    else:
        print_report(result)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
