import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from math import isfinite
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from theta_data import (
    StockHistory,
    fetch_stock_history,
    records_from_history,
    validate_history_range,
)


EASTERN = ZoneInfo("America/New_York")
ONE_DAY = timedelta(days=1)
# A bar for today is stored only from this time (Eastern), once ThetaData's
# end-of-day report should be final; an earlier one may be provisional, and a
# stored bar is never replaced. Assumption: the report is published at about
# 17:15 ET, so this leaves a margin.
DAILY_BAR_FINAL_AT = time(18, 0)


def _now() -> datetime:
    return datetime.now(EASTERN)
INTERVAL = "1d"
BAR_SCHEMA = "theta.bar/1"
COVERAGE_SCHEMA = "theta.coverage/1"
EXPORT_STREAMS = {BAR_SCHEMA: "theta-bars", COVERAGE_SCHEMA: "theta-coverage"}

_DATABASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    session_date TEXT NOT NULL,
    start_at TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    provider TEXT NOT NULL,
    PRIMARY KEY (symbol, interval, start_at)
);
CREATE INDEX IF NOT EXISTS bars_by_session ON bars (symbol, interval, session_date);
CREATE TABLE IF NOT EXISTS fetched_ranges (
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    PRIMARY KEY (symbol, interval, start_date, end_date)
);
CREATE TABLE IF NOT EXISTS pins (
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    pinned_at TEXT NOT NULL,
    PRIMARY KEY (symbol, interval, start_date, end_date)
);
CREATE TABLE IF NOT EXISTS export_outbox (
    id INTEGER PRIMARY KEY,
    utc_day TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


class HistoryFormatError(RuntimeError):
    """A provider response cannot safely be stored as daily bars."""


@dataclass
class BarFetchResult:
    symbol: str
    interval: str
    start_date: date
    end_date: date
    covered_through: date | None
    added: int
    data: list[dict[str, Any]]


@dataclass(frozen=True)
class LoadedSymbol:
    """A ticker with daily bars in the store, and the sessions they span."""

    symbol: str
    interval: str
    bars: int
    first_session: date
    last_session: date


@dataclass(frozen=True)
class Pin:
    """A pinned summary: a ticker over fixed dates, redrawn from stored bars."""

    symbol: str
    start_date: date
    end_date: date


def _session_date(row: dict[str, Any]) -> date:
    if row.get("date") is not None:
        value = row["date"]
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value)
        if len(text) == 8 and text.isdigit():
            # Terminal v2 REST sends YYYYMMDD; date.fromisoformat reads that
            # form only from Python 3.11, and the launcher accepts 3.10.
            return date(int(text[:4]), int(text[4:6]), int(text[6:]))
        if len(text) == 10:
            return date.fromisoformat(text)
        return datetime.fromisoformat(text).date()

    created = row["created"]
    if not isinstance(created, datetime):
        created = datetime.fromisoformat(created)
    if created.utcoffset() is not None:
        created = created.astimezone(EASTERN)
    return created.date()


def normalize_daily_bars(
    symbol: str, history: StockHistory, start_date: date, end_date: date
) -> list[dict[str, Any]]:
    try:
        raw = history.data
        if hasattr(raw, "to_dicts"):
            rows = raw.to_dicts()
        elif hasattr(raw, "to_dict"):
            rows = raw.to_dict(orient="records")
        else:
            rows = records_from_history(raw)
    except (TypeError, ValueError) as error:
        raise HistoryFormatError(f"Unsupported {history.provider} history response") from error

    bars = []
    for index, raw_row in enumerate(rows, start=1):
        try:
            row = {key.lower(): value for key, value in raw_row.items()}
            session = _session_date(row)
            if not start_date <= session <= end_date:
                raise ValueError("session date is outside the requested range")
            prices = {field: float(row[field]) for field in ("open", "high", "low", "close")}
            if not all(isfinite(price) for price in prices.values()):
                raise ValueError("nonfinite price")
            if not all(price > 0 for price in prices.values()):
                raise ValueError("prices must be positive")
            if not prices["low"] <= min(prices["open"], prices["close"]) <= max(
                prices["open"], prices["close"]
            ) <= prices["high"]:
                raise ValueError("open and close must lie between low and high")
            raw_volume = row["volume"]
            volume = int(raw_volume)
            if isinstance(raw_volume, str):
                raw_volume = volume  # int() rejected noninteger strings.
            if volume != raw_volume or not 0 <= volume <= 2**63 - 1:
                raise ValueError("volume must be a nonnegative integer")
            session_open = datetime.combine(session, time(9, 30), tzinfo=EASTERN)
        except (AttributeError, KeyError, OverflowError, TypeError, ValueError) as error:
            raise HistoryFormatError(
                f"Invalid {history.provider} daily bar at row {index}: {error}"
            ) from error
        bars.append({
            "schema": BAR_SCHEMA,
            "symbol": symbol,
            "interval": INTERVAL,
            "session_date": session.isoformat(),
            "start_at": session_open.astimezone(timezone.utc).isoformat(),
            **prices,
            "volume": volume,
            "provider": history.provider,
        })
    return sorted(bars, key=lambda bar: bar["start_at"])


def _missing_ranges(
    connection: sqlite3.Connection, symbol: str, start_date: date, end_date: date
) -> list[tuple[date, date]]:
    covered = connection.execute(
        """
        SELECT start_date, end_date FROM fetched_ranges
        WHERE symbol = ? AND interval = ? AND end_date >= ? AND start_date <= ?
        ORDER BY start_date
        """,
        (symbol, INTERVAL, start_date.isoformat(), end_date.isoformat()),
    ).fetchall()
    missing = []
    next_date = start_date
    for first, last in covered:
        first_date = date.fromisoformat(first)
        last_date = date.fromisoformat(last)
        if first_date > next_date:
            missing.append((next_date, first_date - ONE_DAY))
        if last_date >= end_date:
            return missing
        next_date = max(next_date, last_date + ONE_DAY)
    missing.append((next_date, end_date))
    return missing


def _queue_export(connection: sqlite3.Connection, utc_day: str, record: dict[str, Any]) -> None:
    connection.execute(
        "INSERT INTO export_outbox (utc_day, payload) VALUES (?, ?)",
        (utc_day, json.dumps(record, separators=(",", ":"), allow_nan=False)),
    )


def _coverage_record(symbol: str, interval: str, start_date: str, end_date: str) -> dict[str, str]:
    return {
        "schema": COVERAGE_SCHEMA, "symbol": symbol, "interval": interval,
        "start_date": start_date, "end_date": end_date,
    }


def _queue_existing_coverage(connection: sqlite3.Connection) -> None:
    if connection.execute("PRAGMA user_version").fetchone()[0] >= 1:
        return
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("PRAGMA user_version").fetchone()[0] >= 1:
            return
        utc_day = datetime.now(timezone.utc).date().isoformat()
        for row in connection.execute("SELECT symbol, interval, start_date, end_date FROM fetched_ranges"):
            _queue_export(connection, utc_day, _coverage_record(*row))
        connection.execute("PRAGMA user_version = 1")


def _save_fetch(
    connection: sqlite3.Connection,
    symbol: str,
    first: date,
    covered_end: date,
    bars: list[dict[str, Any]],
) -> int:
    utc_day = datetime.now(timezone.utc).date().isoformat()
    added = 0
    with connection:
        for bar in bars:
            inserted = connection.execute(
                """
                INSERT INTO bars (symbol, interval, session_date, start_at, open,
                                  high, low, close, volume, provider)
                VALUES (:symbol, :interval, :session_date, :start_at, :open,
                        :high, :low, :close, :volume, :provider)
                ON CONFLICT (symbol, interval, start_at) DO NOTHING
                """,
                bar,
            )
            if inserted.rowcount:
                _queue_export(connection, utc_day, bar)
                added += 1
        if first <= covered_end:
            first_text = first.isoformat()
            end_text = covered_end.isoformat()
            inserted = connection.execute(
                "INSERT OR IGNORE INTO fetched_ranges VALUES (?, ?, ?, ?)",
                (symbol, INTERVAL, first_text, end_text),
            )
            if inserted.rowcount:
                _queue_export(connection, utc_day, _coverage_record(symbol, INTERVAL, first_text, end_text))
    return added


def _append_jsonl(path: Path, payload: bytes) -> None:
    with path.open("a+b", buffering=0) as stream:
        end = stream.seek(0, os.SEEK_END)
        if end:
            stream.seek(end - 1)
            if stream.read(1) != b"\n":
                # A crashed writer can leave an incomplete final record. Keep
                # complete lines and retry the pending entry from SQLite.
                position = end
                while position:
                    start = max(0, position - 4096)
                    stream.seek(start)
                    last_newline = stream.read(position - start).rfind(b"\n")
                    if last_newline >= 0:
                        position = start + last_newline + 1
                        break
                    position = start
                stream.truncate(position)
        if stream.write(payload) != len(payload):
            raise OSError("Incomplete market export write")
        os.fsync(stream.fileno())


def _flush_exports(connection: sqlite3.Connection, directory: Path) -> None:
    # Serialize file writers across CLI and API processes. A failed append
    # retains the outbox, so retries may repeat complete records.
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        pending = connection.execute(
            "SELECT id, utc_day, payload FROM export_outbox ORDER BY utc_day, id"
        ).fetchall()
        if not pending:
            return
        directory.mkdir(parents=True, exist_ok=True)
        by_file: dict[str, list[sqlite3.Row]] = {}
        for row in pending:
            stream = EXPORT_STREAMS[json.loads(row["payload"])["schema"]]
            filename = f"{stream}-{row['utc_day']}.jsonl"
            by_file.setdefault(filename, []).append(row)
        for filename, rows in by_file.items():
            payload = "".join(row["payload"] + "\n" for row in rows).encode("utf-8")
            _append_jsonl(directory / filename, payload)
            connection.executemany(
                "DELETE FROM export_outbox WHERE id = ?", [(row["id"],) for row in rows]
            )


def default_data_directory() -> Path:
    """Where market.db and exports/ live, the same for the source app and the
    executable, so neither splits the bar history and rebuilds keep it.
    Credentials are separate: they stay beside the running app (theta_data.get_dotenv_path)."""
    local_app_data = os.getenv("LOCALAPPDATA")
    return Path(local_app_data) / "ThetaDesk" if local_app_data else Path.home() / ".thetadesk"


def _open_store(directory: Path) -> sqlite3.Connection:
    directory.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(directory / "market.db", timeout=30)
    connection.row_factory = sqlite3.Row
    connection.executescript(_DATABASE_SCHEMA)
    return connection


def _stored_rows(connection: sqlite3.Connection, symbol: str, start_date: date, end_date: date) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT symbol, interval, session_date, start_at, open, high, low, close, volume, provider
        FROM bars WHERE symbol = ? AND interval = ? AND session_date BETWEEN ? AND ?
        ORDER BY session_date
        """,
        (symbol, INTERVAL, start_date.isoformat(), end_date.isoformat()),
    )
    return [{"schema": BAR_SCHEMA, **dict(row)} for row in rows]


def _normalize_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("symbol must not be empty")
    return symbol


def stored_daily_bars(
    symbol: str, start_date: date, end_date: date, *, data_dir: Path | None = None
) -> list[dict[str, Any]]:
    """Daily bars already in the store; never calls ThetaData."""
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    with closing(_open_store(data_dir if data_dir is not None else default_data_directory())) as connection:
        return _stored_rows(connection, _normalize_symbol(symbol), start_date, end_date)


def loaded_symbols(*, data_dir: Path | None = None) -> list[LoadedSymbol]:
    with closing(_open_store(data_dir if data_dir is not None else default_data_directory())) as connection:
        rows = connection.execute(
            """
            SELECT symbol, COUNT(*), MIN(session_date), MAX(session_date)
            FROM bars WHERE interval = ? GROUP BY symbol ORDER BY symbol
            """,
            (INTERVAL,),
        ).fetchall()
    return [
        LoadedSymbol(symbol, INTERVAL, count, date.fromisoformat(first), date.fromisoformat(last))
        for symbol, count, first, last in rows
    ]


def list_pins(*, data_dir: Path | None = None) -> list[Pin]:
    """Pins in the order they were made."""
    with closing(_open_store(data_dir if data_dir is not None else default_data_directory())) as connection:
        rows = connection.execute(
            "SELECT symbol, start_date, end_date FROM pins WHERE interval = ? ORDER BY pinned_at, rowid",
            (INTERVAL,),
        ).fetchall()
    return [Pin(symbol, date.fromisoformat(start), date.fromisoformat(end)) for symbol, start, end in rows]


def add_pin(symbol: str, start_date: date, end_date: date, *, data_dir: Path | None = None) -> Pin:
    """Pin a ticker over fixed dates; pinning the same dates again changes nothing."""
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    pin = Pin(_normalize_symbol(symbol), start_date, end_date)
    with closing(_open_store(data_dir if data_dir is not None else default_data_directory())) as connection:
        with connection:
            connection.execute(
                "INSERT OR IGNORE INTO pins (symbol, interval, start_date, end_date, pinned_at) VALUES (?, ?, ?, ?, ?)",
                (pin.symbol, INTERVAL, start_date.isoformat(), end_date.isoformat(),
                 datetime.now(timezone.utc).isoformat()),
            )
    return pin


def remove_pins(pin: Pin | None = None, *, data_dir: Path | None = None) -> int:
    """Remove one pin, or every pin when pin is None; return how many were removed."""
    with closing(_open_store(data_dir if data_dir is not None else default_data_directory())) as connection:
        with connection:
            if pin is None:
                cursor = connection.execute("DELETE FROM pins WHERE interval = ?", (INTERVAL,))
            else:
                cursor = connection.execute(
                    "DELETE FROM pins WHERE symbol = ? AND interval = ? AND start_date = ? AND end_date = ?",
                    (_normalize_symbol(pin.symbol), INTERVAL, pin.start_date.isoformat(), pin.end_date.isoformat()),
                )
            return cursor.rowcount


def fetch_daily_bars(
    symbol: str,
    start_date: date,
    end_date: date,
    *,
    data_dir: Path | None = None,
    refresh: bool = False,
) -> BarFetchResult:
    symbol = _normalize_symbol(symbol)
    validate_history_range(start_date, end_date)
    now = _now()
    today = now.date()
    final_today = now.time() >= DAILY_BAR_FINAL_AT
    if end_date > today:
        raise ValueError("end_date must not be in the future (America/New_York)")

    directory = data_dir if data_dir is not None else default_data_directory()
    covered_through = min(end_date, today - ONE_DAY)
    with closing(_open_store(directory)) as connection:
        _queue_existing_coverage(connection)
        _flush_exports(connection, directory / "exports")
        added = 0
        ranges = [(start_date, end_date)] if refresh else _missing_ranges(connection, symbol, start_date, end_date)
        for first, last in ranges:
            history = fetch_stock_history(symbol, first, last)
            bars = normalize_daily_bars(symbol, history, first, last)
            if not final_today:
                # Possibly provisional; a later fetch stores the final bar.
                bars = [bar for bar in bars if bar["session_date"] != today.isoformat()]
            # An empty response for today might arrive before the EOD report.
            # Cache coverage for past sessions and for today once its bar exists.
            completed = min(last, covered_through)
            if bars and bars[-1]["session_date"] == last.isoformat():
                completed = last
            added += _save_fetch(connection, symbol, first, completed, bars)
            _flush_exports(connection, directory / "exports")
        data = _stored_rows(connection, symbol, start_date, end_date)
    if data and data[-1]["session_date"] == end_date.isoformat():
        covered_through = end_date
    return BarFetchResult(
        symbol, INTERVAL, start_date, end_date,
        covered_through if covered_through >= start_date else None,
        added, data,
    )
