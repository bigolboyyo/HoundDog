"""Report unseen RSS/Atom items that match keyword topics."""

from __future__ import annotations

import argparse
import email.utils
import hashlib
import html
import io
import json
import os
import re
import sqlite3
import sys
import time
import traceback
import tomllib
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import xml.parsers.expat
import zlib
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from http.client import HTTPException, HTTPMessage, HTTPResponse
from pathlib import Path
from types import MappingProxyType
from typing import IO, Any
from urllib.parse import unquote, urlparse, urlsplit, urlunsplit
from uuid import uuid4

READ_CHUNK_BYTES = 64 * 1024
MAX_PARALLEL_FETCHES = 8
ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"
TAG_PATTERN = re.compile(r"<[^>]+>")
SPACE_PATTERN = re.compile(r"\s+")
CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# Query parameters that only identify where a click came from. utm_* is matched
# by prefix. Removing them gives one link per article (see canonical_link).
TRACKING_PARAMS = frozenset({
    "at_campaign", "at_medium", "dclid", "fbclid", "gbraid", "gclid", "igshid",
    "mc_cid", "mc_eid", "mkt_tok", "msclkid", "wbraid", "yclid", "_hsenc", "_hsmi",
})
DEFAULT_PORTS = {"http": ":80", "https": ":443"}


class ConfigError(ValueError):
    pass


def strip_controls(text: str) -> str:
    """Replace C0/C1 control characters, which can drive terminal escape sequences."""
    return CONTROL_PATTERN.sub(" ", text)


def clean_text(raw: str | None) -> str:
    if not raw:
        return ""
    text = strip_controls(html.unescape(TAG_PATTERN.sub(" ", raw)))
    return SPACE_PATTERN.sub(" ", text).strip()


def canonical_link(link: str) -> str:
    """One spelling per article, so a tracking parameter or #fragment does not make
    the same item look new. Only http(s) links change; the path and the remaining
    query are kept byte for byte. History is keyed by this value: changing the
    rule needs a new SEEN_SCHEMA_VERSION that migrates stored links.
    """
    link = link.strip()
    parts = urlsplit(link)
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORTS or not parts.netloc:
        return link
    userinfo, at, host = parts.netloc.rpartition("@")
    host = host.lower().removesuffix(DEFAULT_PORTS[scheme])
    query = "&".join(
        pair for pair in parts.query.split("&")
        if pair and not is_tracking_param(unquote(pair.split("=", 1)[0]).lower())
    )
    return urlunsplit((scheme, f"{userinfo}{at}{host}", parts.path, query, ""))


def is_tracking_param(name: str) -> bool:
    return name.startswith("utm_") or name in TRACKING_PARAMS


def normalize_published(raw: str) -> str:
    """A feed date (RFC 822 in RSS, ISO 8601 in Atom) as a UTC timestamp, or ""
    when it has none or its time zone is unknown. An abbreviation such as CET or
    IST, "-0000", or an ISO date without an offset gives no zone; guessing UTC
    would put the item hours away from when it was published."""
    if not raw:
        return ""
    try:
        moment = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        try:
            moment = datetime.fromisoformat(raw)
        except ValueError:
            return ""
    if moment.tzinfo is None:
        return ""
    try:
        return utc_timestamp(moment)
    except (OverflowError, ValueError):
        return ""


def child_text(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    return clean_text("".join(child.itertext())) if child is not None else ""


class ImageSourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.src = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "img" and not self.src:
            self.src = dict(attrs).get("src") or ""


def item_image(node: ET.Element) -> str:
    for child in node.iter():
        name = child.tag.rsplit("}", 1)[-1].lower()
        url = child.get("url") or child.get("href") or child.get("src")
        media_type = child.get("type", "").lower()
        is_image = media_type.startswith("image/") or child.get("medium") == "image"
        if url and (
            name == "thumbnail"
            or (name in {"content", "enclosure", "link"} and is_image)
        ):
            return clean_text(url)

    for child in node.iter():
        name = child.tag.rsplit("}", 1)[-1].lower()
        if name not in {"content", "description", "encoded", "summary"}:
            continue
        parser = ImageSourceParser()
        parser.feed(html.unescape("".join(child.itertext())))
        if parser.src:
            return clean_text(parser.src)
    return ""


# PRAGMA user_version of watcher.db. Each step rewrites stored data once.
#   1: canonical_link on stored links (merging duplicates), published_at backfill.
SEEN_SCHEMA_VERSION = 3


def ensure_seen_schema(db: sqlite3.Connection) -> None:
    """Create or upgrade the History tables; call inside a transaction."""
    if db.execute("PRAGMA user_version").fetchone()[0] < SEEN_SCHEMA_VERSION and not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    db.execute(
        "CREATE TABLE IF NOT EXISTS seen ("
        "topic TEXT NOT NULL, link TEXT NOT NULL, first_seen TEXT NOT NULL, "
        "PRIMARY KEY (topic, link))"
    )
    existing = {row[1] for row in db.execute("PRAGMA table_info(seen)")}
    for column in ("source", "title", "summary", "published", "author", "image_url", "published_at"):
        if column not in existing:
            db.execute(f"ALTER TABLE seen ADD COLUMN {column} TEXT")
    # The primary key leads with topic; article-level lookups need link alone.
    db.execute("CREATE INDEX IF NOT EXISTS seen_by_link ON seen (link)")
    # Read and starred belong to the article, not to each topic that matched it.
    db.execute(
        "CREATE TABLE IF NOT EXISTS item_state ("
        "link TEXT PRIMARY KEY, read_at TEXT, starred_at TEXT)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS history_reset ("
        "id INTEGER PRIMARY KEY CHECK (id = 1), generation INTEGER NOT NULL)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS feed_state ("
        "url TEXT PRIMARY KEY, etag TEXT NOT NULL, last_modified TEXT NOT NULL, "
        "fingerprint TEXT NOT NULL, saved_at TEXT NOT NULL, retry_at TEXT NOT NULL, "
        "retry_observed_at TEXT NOT NULL DEFAULT '')"
    )
    # Later headlines and dates of an article; seen keeps the first-seen ones.
    db.execute(
        "CREATE TABLE IF NOT EXISTS item_revisions ("
        "link TEXT NOT NULL, observed_at TEXT NOT NULL, title TEXT NOT NULL, "
        "published TEXT NOT NULL, published_at TEXT NOT NULL)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS item_revisions_by_link ON item_revisions (link)")
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version < 1:
        normalize_stored_history(db)
    if version < 2:
        feed_columns = {row[1] for row in db.execute("PRAGMA table_info(feed_state)")}
        if "retry_observed_at" not in feed_columns:
            db.execute("ALTER TABLE feed_state ADD COLUMN retry_observed_at TEXT NOT NULL DEFAULT ''")
    if version < SEEN_SCHEMA_VERSION:
        db.execute(f"PRAGMA user_version = {SEEN_SCHEMA_VERSION}")


def normalize_stored_history(db: sqlite3.Connection) -> None:
    """Schema 1: rewrite links stored before canonical_link and fill published_at.

    Two spellings of one article under the same topic become one row that keeps
    the earlier first_seen.
    """
    rows = db.execute("SELECT rowid, topic, link, first_seen, published FROM seen").fetchall()
    for rowid, topic, link, first_seen, published in rows:
        canonical = canonical_link(link)
        if canonical != link:
            duplicate = db.execute(
                "SELECT rowid FROM seen WHERE topic = ? AND link = ?", (topic, canonical)
            ).fetchone()
            if duplicate:
                db.execute(
                    "UPDATE seen SET first_seen = MIN(first_seen, ?) WHERE rowid = ?",
                    (first_seen, duplicate[0]),
                )
                db.execute("DELETE FROM seen WHERE rowid = ?", (rowid,))
                continue
            db.execute("UPDATE seen SET link = ? WHERE rowid = ?", (canonical, rowid))
        db.execute(
            "UPDATE seen SET published_at = ? WHERE rowid = ?",
            (normalize_published(published or "") or None, rowid),
        )


@dataclass(frozen=True)
class Item:
    source: str
    title: str
    link: str
    summary: str
    published: str
    author: str = ""
    image_url: str = ""
    published_at: str = ""  # normalize_published(published)

    @property
    def searchable_text(self) -> str:
        return f"{self.title} {self.summary}"


def parse_rss(root: ET.Element, source: str) -> list[Item]:
    items = []
    for node in root.iterfind("./channel/item"):
        published = child_text(node, "pubDate")
        items.append(Item(
            source=source,
            title=child_text(node, "title"),
            link=canonical_link(child_text(node, "link") or child_text(node, "guid")),
            summary=child_text(node, "description"),
            published=published,
            author=child_text(node, "author") or child_text(node, f"{DC}creator"),
            image_url=item_image(node),
            published_at=normalize_published(published),
        ))
    return items


def atom_link(node: ET.Element) -> str:
    for link in node.iterfind(f"{ATOM}link"):
        href = link.get("href")
        if href and link.get("rel", "alternate") == "alternate":
            return clean_text(href)
    return child_text(node, f"{ATOM}id")


def parse_atom(root: ET.Element, source: str) -> list[Item]:
    items = []
    for node in root.iterfind(f"{ATOM}entry"):
        published = child_text(node, f"{ATOM}published") or child_text(node, f"{ATOM}updated")
        items.append(Item(
            source=source,
            title=child_text(node, f"{ATOM}title"),
            link=canonical_link(atom_link(node)),
            summary=child_text(node, f"{ATOM}summary") or child_text(node, f"{ATOM}content"),
            published=published,
            author=child_text(node, f"{ATOM}author/{ATOM}name"),
            image_url=item_image(node),
            published_at=normalize_published(published),
        ))
    return items


class HttpOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to http(s); urllib's default also allows ftp."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        if urlparse(newurl).scheme not in ("http", "https"):
            raise urllib.error.HTTPError(
                newurl, code, f"redirect to non-HTTP URL refused: {newurl}", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(HttpOnlyRedirectHandler)


def parse_feed_xml(payload: bytes) -> ET.Element:
    """Parse feed XML, refusing any document that declares entities.

    This is defusedxml's default policy in a stdlib pre-pass. Declarations come
    before the root element, so the pre-pass stops before anything expands,
    which blocks billion-laughs and quadratic-blowup payloads on any Expat
    version. A DOCTYPE without entity declarations is still accepted.
    """

    def refuse(*_args: object) -> None:
        raise ET.ParseError("feed declares XML entities; refusing to parse")

    guard = xml.parsers.expat.ParserCreate()
    guard.EntityDeclHandler = refuse
    guard.UnparsedEntityDeclHandler = refuse
    try:
        guard.Parse(payload, True)
    except xml.parsers.expat.ExpatError as error:
        raise ET.ParseError(str(error)) from error
    return ET.fromstring(payload)


def setting_int(table: dict[str, Any], key: str, default: int, minimum: int, maximum: int) -> int:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ConfigError(f"settings: '{key}' must be a whole number from {minimum} to {maximum}")
    return value


def setting_bool(table: dict[str, Any], key: str, default: bool) -> bool:
    value = table.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"settings: '{key}' must be true or false")
    return value


@dataclass(frozen=True)
class Settings:
    """The optional [settings] table in watch.toml, shared by the CLI and dashboard."""

    fetch_timeout_seconds: int = 15
    max_feed_megabytes: int = 5
    user_agent: str = "keyword-watcher/0.1"
    history_retention_days: int = 90
    max_item_age_days: int = 0
    event_export: bool = True  # EventExport files for other programs

    @property
    def max_feed_bytes(self) -> int:
        return self.max_feed_megabytes * 1_000_000

    @property
    def fetch_deadline_seconds(self) -> int:
        """Total time allowed for one feed download, however slowly it trickles in."""
        return self.fetch_timeout_seconds * 4

    @classmethod
    def from_table(cls, table: object) -> Settings:
        if not isinstance(table, dict):
            raise ConfigError("'settings' must be a table ([settings])")
        known = {field.name for field in fields(cls)}
        unknown = sorted(set(table) - known)
        if unknown:
            raise ConfigError(f"settings: unknown key(s): {', '.join(unknown)}")
        defaults = cls()
        user_agent = table.get("user_agent", defaults.user_agent)
        if (
            not isinstance(user_agent, str)
            or not user_agent.strip()
            or len(user_agent) > 200
            or CONTROL_PATTERN.search(user_agent)
        ):
            raise ConfigError("settings: 'user_agent' must be 1-200 printable characters")
        return cls(
            fetch_timeout_seconds=setting_int(table, "fetch_timeout_seconds", defaults.fetch_timeout_seconds, 1, 120),
            max_feed_megabytes=setting_int(table, "max_feed_megabytes", defaults.max_feed_megabytes, 1, 50),
            user_agent=user_agent.strip(),
            history_retention_days=setting_int(table, "history_retention_days", defaults.history_retention_days, 0, 3650),
            max_item_age_days=setting_int(table, "max_item_age_days", defaults.max_item_age_days, 0, 3650),
            event_export=setting_bool(table, "event_export", defaults.event_export),
        )

    def oldest_published_at(self, now: datetime) -> str:
        """Items published before this are ignored ("" when max_item_age_days is 0)."""
        if self.max_item_age_days <= 0:
            return ""
        return utc_timestamp(now - timedelta(days=self.max_item_age_days))

    def to_table(self) -> dict[str, Any]:
        return asdict(self)


def read_limited(response: HTTPResponse, max_bytes: int, deadline_seconds: int) -> bytes:
    """Read at most max_bytes, giving up if the whole body takes too long.

    The socket timeout only bounds each individual read, so a server that
    trickles bytes could otherwise stall a check indefinitely.
    """
    deadline = time.monotonic() + deadline_seconds
    chunks: list[bytes] = []
    total = 0
    while total < max_bytes:
        if time.monotonic() > deadline:
            raise TimeoutError(f"feed download exceeded {deadline_seconds}s")
        chunk = response.read1(min(READ_CHUNK_BYTES, max_bytes - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    if total >= max_bytes and response.read1(1):
        raise ValueError(f"feed is larger than {max_bytes:,} bytes")
    return b"".join(chunks)


MAX_BACKOFF = timedelta(hours=24)
DEFAULT_BACKOFF = timedelta(minutes=30)
MAX_VALIDATOR_LENGTH = 512


class RateLimited(OSError):
    """The feed answered 429 or 503; retry_at is when it may be fetched again."""

    def __init__(self, status: int, retry_at: datetime) -> None:
        super().__init__(f"HTTP Error {status}: asked to wait until {utc_timestamp(retry_at)}")
        self.retry_at = retry_at


def retry_time(retry_after: str | None, now: datetime) -> datetime:
    """When to fetch again after 429/503, from Retry-After (seconds or an HTTP
    date) or DEFAULT_BACKOFF, capped at MAX_BACKOFF."""
    delay = DEFAULT_BACKOFF
    value = (retry_after or "").strip()
    if value.isdigit():
        delay = timedelta(seconds=int(value))
    elif value:
        try:
            moment = email.utils.parsedate_to_datetime(value)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            delay = moment - now
        except (TypeError, ValueError, IndexError, OverflowError):
            pass
    return now + min(max(delay, timedelta(0)), MAX_BACKOFF)


def gunzip_limited(payload: bytes, max_bytes: int) -> bytes:
    """Inflate a gzip body, refusing to grow past max_bytes (a gzip bomb)."""
    inflater = zlib.decompressobj(wbits=zlib.MAX_WBITS | 16)
    try:
        body = inflater.decompress(payload, max_bytes + 1)
    except zlib.error as error:
        raise ValueError(f"invalid gzip body: {error}") from None
    if len(body) > max_bytes:
        raise ValueError(f"feed is larger than {max_bytes:,} bytes when decompressed")
    return body


def validator_header(value: str | None) -> str:
    """An ETag or Last-Modified to send back later; unusable values are dropped."""
    value = (value or "").strip()
    return "" if len(value) > MAX_VALIDATOR_LENGTH or CONTROL_PATTERN.search(value) else value


@dataclass(frozen=True)
class FeedState:
    """What watcher.db remembers about one feed URL between checks.

    etag and last_modified come from the last fetch a saved check processed
    (saved_at), with topics matching fingerprint; they are only sent while the
    current topics have the same fingerprint. retry_at is set when the server
    asked to be left alone, by any check.
    """

    etag: str = ""
    last_modified: str = ""
    fingerprint: str = ""
    saved_at: str = ""
    retry_at: str = ""


NO_FEED_STATES: Mapping[str, FeedState] = MappingProxyType({})


@dataclass(frozen=True)
class FeedResponse:
    items: list[Item]
    etag: str
    last_modified: str
    not_modified: bool


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    check_every_minutes: int | None = None

    def fetch(self, settings: Settings, validators: FeedState = FeedState()) -> FeedResponse:
        """Download and parse the feed. With validators, an unchanged feed answers
        304 and comes back as not_modified with no items."""
        headers = {"User-Agent": settings.user_agent, "Accept-Encoding": "gzip"}
        if validators.etag:
            headers["If-None-Match"] = validators.etag
        if validators.last_modified:
            headers["If-Modified-Since"] = validators.last_modified
        request = urllib.request.Request(self.url, headers=headers)
        try:
            with OPENER.open(request, timeout=settings.fetch_timeout_seconds) as response:
                payload = read_limited(response, settings.max_feed_bytes, settings.fetch_deadline_seconds)
                encoding = response.headers.get("Content-Encoding", "").strip().lower()
                etag = validator_header(response.headers.get("ETag"))
                last_modified = validator_header(response.headers.get("Last-Modified"))
        except urllib.error.HTTPError as error:
            with error:
                if error.code == 304:
                    return FeedResponse([], validators.etag, validators.last_modified, not_modified=True)
                if error.code in (429, 503):
                    retry_at = retry_time(error.headers.get("Retry-After"), datetime.now(timezone.utc))
                    raise RateLimited(error.code, retry_at) from None
                raise
        if encoding == "gzip":
            payload = gunzip_limited(payload, settings.max_feed_bytes)
        elif encoding not in ("", "identity"):
            raise ValueError(f"unsupported Content-Encoding: {encoding}")
        root = parse_feed_xml(payload)
        if root.tag == "rss":
            items = parse_rss(root, self.name)
        elif root.tag == f"{ATOM}feed":
            items = parse_atom(root, self.name)
        else:
            raise ValueError(f"unsupported feed format <{root.tag}>")
        return FeedResponse(items, etag, last_modified, not_modified=False)


def term_pattern(term: str) -> re.Pattern[str]:
    prefix_only = term.endswith("*")
    escaped = re.escape(term.rstrip("*"))
    suffix = "" if prefix_only else r"(?!\w)"
    return re.compile(rf"(?<!\w){escaped}{suffix}", re.IGNORECASE)


@dataclass(frozen=True)
class TopicEvaluation:
    """Which include keywords hit, and which exclude terms (if any) vetoed them."""

    keywords: tuple[str, ...]
    excluded_by: tuple[str, ...]

    @property
    def matched(self) -> bool:
        return bool(self.keywords) and not self.excluded_by


class Topic:
    def __init__(self, name: str, keywords: Sequence[str], exclude: Sequence[str]) -> None:
        self.name = name
        self.keywords = tuple(keywords)
        self.exclude = tuple(exclude)
        self._include = [(term, term_pattern(term)) for term in keywords]
        self._exclude = [(term, term_pattern(term)) for term in exclude]

    def evaluate(self, text: str) -> TopicEvaluation:
        return TopicEvaluation(
            keywords=tuple(term for term, pattern in self._include if pattern.search(text)),
            excluded_by=tuple(term for term, pattern in self._exclude if pattern.search(text)),
        )

    def matched_keywords(self, text: str) -> list[str]:
        evaluation = self.evaluate(text)
        return list(evaluation.keywords) if evaluation.matched else []


@dataclass(frozen=True)
class Match:
    topic: str
    item: Item
    keywords: tuple[str, ...]
    feed_url: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.topic, self.item.link)


def utc_timestamp(moment: datetime | None = None) -> str:
    """The one timestamp format stored in watcher.db; retention compares these strings."""
    return (moment or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")


def elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


@dataclass(frozen=True)
class Revision:
    """A later headline or published date of an article already in History."""

    link: str
    observed_at: str
    changed: tuple[str, ...]  # "title" and/or "released_at"
    title: str
    published: str
    published_at: str
    previous_title: str
    previous_published_at: str


@dataclass(frozen=True)
class SavedCheck:
    """What SeenStore.save_check wrote: saved_at is every new row's first_seen."""

    saved_at: str
    revisions: tuple[Revision, ...]


class SeenStore:
    """watcher.db's History (seen items and their read/starred state) and the
    per-feed state that conditional requests and backoff rely on."""

    def __init__(self, path: Path) -> None:
        self._db = sqlite3.connect(path)
        with self._db:
            ensure_seen_schema(self._db)

    def contains(self, topic: str, link: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM seen WHERE topic = ? AND link = ?", (topic, link)
        ).fetchone()
        return row is not None

    def mark_seen(self, matches: Iterable[Match]) -> None:
        with self._db:
            self._insert_matches(matches, utc_timestamp())

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            yield self._db

    def history_generation(self) -> int:
        row = self._db.execute("SELECT generation FROM history_reset WHERE id = 1").fetchone()
        return row[0] if row else 0

    def clear_history(self) -> None:
        with self.transaction() as db:
            db.execute("DELETE FROM seen")
            db.execute("DELETE FROM item_state")
            db.execute("DELETE FROM item_revisions")
            # The validators describe deleted History. Preserve feed backoff.
            db.execute("UPDATE feed_state SET etag = '', last_modified = '', fingerprint = '', saved_at = ''")
            db.execute(
                "INSERT INTO history_reset (id, generation) VALUES (1, 1) "
                "ON CONFLICT(id) DO UPDATE SET generation = generation + 1"
            )

    def save_check(self, result: CheckResult, *, commit: bool = True) -> SavedCheck:
        """Store a saved check: its matches, any change to the headline or date of
        articles already seen, and, in the same transaction, the feed validators
        that describe what it processed."""
        saved_at = utc_timestamp()
        with self._db if commit else nullcontext():
            # Before the insert, so a new topic row of a known article is compared too.
            revisions = self._record_revisions([*result.matches, *result.seen_updates], saved_at)
            self._insert_matches([*result.matches, *result.seen_updates], saved_at)
            self._db.executemany(
                "INSERT INTO feed_state (url, etag, last_modified, fingerprint, saved_at, retry_at) "
                "VALUES (?, ?, ?, ?, ?, '') ON CONFLICT(url) DO UPDATE SET "
                "etag = excluded.etag, last_modified = excluded.last_modified, "
                "fingerprint = excluded.fingerprint, saved_at = excluded.saved_at "
                "WHERE excluded.saved_at > feed_state.saved_at OR julianday(feed_state.saved_at) IS NULL",
                [
                    (url, state.etag, state.last_modified, state.fingerprint, state.saved_at)
                    for url, state in result.feed_updates.items()
                ],
            )
            self._save_retry_updates(result)
        return SavedCheck(saved_at, tuple(revisions))

    def save_backoff(self, result: CheckResult, *, commit: bool = True) -> None:
        """Store only when each feed may be fetched again. A preview must not move
        the validators: the next saved check would get 304 for items it never saw."""
        with self._db if commit else nullcontext():
            self._save_retry_updates(result)

    def _save_retry_updates(self, result: CheckResult) -> None:
        self._db.executemany(
            "INSERT INTO feed_state (url, etag, last_modified, fingerprint, saved_at, retry_at, retry_observed_at) "
            "SELECT ?, '', '', '', '', ?, ? "
            "WHERE ? != '' OR EXISTS (SELECT 1 FROM feed_state WHERE url = ?) "
            "ON CONFLICT(url) DO UPDATE SET "
            "retry_at = excluded.retry_at, retry_observed_at = excluded.retry_observed_at "
            "WHERE excluded.retry_observed_at > feed_state.retry_observed_at",
            [(url, retry_at, result.checked_at, retry_at, url) for url, retry_at in result.retry_updates.items()],
        )

    def feed_states(self) -> dict[str, FeedState]:
        return {
            url: FeedState(etag, last_modified, fingerprint, saved_at, retry_at)
            for url, etag, last_modified, fingerprint, saved_at, retry_at in self._db.execute(
                "SELECT url, etag, last_modified, fingerprint, saved_at, retry_at FROM feed_state"
            )
        }

    def _latest_version(self, link: str) -> tuple[str, str, str] | None:
        """(title, published, published_at) of the article as last recorded: its
        newest revision, else its first-seen row."""
        row = self._db.execute(
            "SELECT title, published, published_at FROM item_revisions WHERE link = ? "
            "ORDER BY rowid DESC LIMIT 1",
            (link,),
        ).fetchone() or self._db.execute(
            "SELECT title, published, published_at FROM seen WHERE link = ? "
            "ORDER BY first_seen, rowid LIMIT 1",
            (link,),
        ).fetchone()
        return None if row is None else (row[0] or "", row[1] or "", row[2] or "")

    def _record_revisions(self, updates: Iterable[Match], observed_at: str) -> list[Revision]:
        """Store a new version of each article already in History whose feed now
        gives a different headline or published date. A value the feed leaves out
        is not a change; articles not in History yet are skipped."""
        revisions = []
        for item in {match.item.link: match.item for match in updates}.values():
            latest = self._latest_version(item.link)
            if latest is None:
                continue
            title, published, published_at = latest
            changed = []
            if item.title and item.title != title:
                changed.append("title")
            if item.published_at and item.published_at != published_at:
                changed.append("released_at")
            if not changed:
                continue
            revision = Revision(
                link=item.link,
                observed_at=observed_at,
                changed=tuple(changed),
                title=item.title or title,
                published=item.published if "released_at" in changed else published,
                published_at=item.published_at or published_at,
                previous_title=title,
                previous_published_at=published_at,
            )
            self._db.execute(
                "INSERT INTO item_revisions (link, observed_at, title, published, published_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (revision.link, observed_at, revision.title, revision.published, revision.published_at),
            )
            revisions.append(revision)
        return revisions

    def _insert_matches(self, matches: Iterable[Match], now: str) -> None:
        # An article keeps what it looked like when first seen; later checks only
        # fill in what was missing (older rows predate some columns). Changes are
        # recorded by _record_revisions. published and published_at stay a pair.
        self._db.executemany(
            "INSERT INTO seen ("
            "topic, link, first_seen, source, title, summary, published, author, image_url, published_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(topic, link) DO UPDATE SET "
            "source = COALESCE(NULLIF(seen.source, ''), excluded.source), "
            "title = COALESCE(NULLIF(seen.title, ''), excluded.title), "
            "summary = COALESCE(NULLIF(seen.summary, ''), excluded.summary), "
            "published = CASE WHEN COALESCE(seen.published, '') = '' "
            "THEN excluded.published ELSE seen.published END, "
            "author = COALESCE(NULLIF(seen.author, ''), excluded.author), "
            "image_url = COALESCE(NULLIF(seen.image_url, ''), excluded.image_url), "
            "published_at = CASE WHEN COALESCE(seen.published, '') = '' "
            "THEN excluded.published_at ELSE seen.published_at END",
            [
                (
                    match.topic,
                    match.item.link,
                    now,
                    match.item.source,
                    match.item.title,
                    match.item.summary,
                    match.item.published,
                    match.item.author,
                    match.item.image_url,
                    match.item.published_at or None,
                )
                for match in matches
            ],
        )

    def set_item_state(self, links: Iterable[str], read: bool | None, starred: bool | None) -> None:
        """Mark History articles read/unread and starred/unstarred. None leaves that
        flag alone; links that are not in History are ignored."""
        unique = list(dict.fromkeys(links))
        now = utc_timestamp()
        with self._db:
            self._db.executemany(
                "INSERT INTO item_state (link) SELECT ? WHERE EXISTS (SELECT 1 FROM seen WHERE link = ?) "
                "ON CONFLICT(link) DO NOTHING",
                [(link, link) for link in unique],
            )
            for column, value in (("read_at", read), ("starred_at", starred)):
                if value is None:
                    continue
                # The column name comes from the fixed tuple above, never from input.
                assignment = f"{column} = COALESCE({column}, ?)" if value else f"{column} = NULL"
                self._db.executemany(
                    f"UPDATE item_state SET {assignment} WHERE link = ?",
                    [(now, link) if value else (link,) for link in unique],
                )
            self._db.execute("DELETE FROM item_state WHERE read_at IS NULL AND starred_at IS NULL")

    def prune(self, retention_days: int, *, commit: bool = True) -> int:
        """Forget items first seen more than retention_days ago, except starred
        articles; 0 keeps everything."""
        if retention_days <= 0:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        with self._db if commit else nullcontext():
            cursor = self._db.execute(
                "DELETE FROM seen WHERE first_seen < ? AND link NOT IN "
                "(SELECT link FROM item_state WHERE starred_at IS NOT NULL)",
                (utc_timestamp(cutoff),),
            )
            self._db.execute("DELETE FROM item_state WHERE link NOT IN (SELECT link FROM seen)")
            self._db.execute("DELETE FROM item_revisions WHERE link NOT IN (SELECT link FROM seen)")
        return cursor.rowcount

    def close(self) -> None:
        self._db.close()


MAX_LOGGED_CHECKS = 1000
CHECK_TRIGGERS = ("cli", "scheduled", "dashboard", "auto")


@dataclass(frozen=True)
class SourceResult:
    """Outcome of fetching one source during a check, for feed health and the log."""

    name: str
    url: str
    ok: bool
    error: str
    item_count: int
    new_matches: int
    duration_ms: int
    not_modified: bool = False  # answered 304; only meaningful when ok


def ensure_check_log_schema(db: sqlite3.Connection) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS checks ("
        "id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, duration_ms INTEGER NOT NULL, "
        "trigger TEXT NOT NULL, saved INTEGER NOT NULL, new_matches INTEGER NOT NULL, "
        "pruned INTEGER NOT NULL)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS check_sources ("
        "check_id INTEGER NOT NULL, name TEXT NOT NULL, url TEXT NOT NULL, ok INTEGER NOT NULL, "
        "error TEXT NOT NULL, item_count INTEGER NOT NULL, new_matches INTEGER NOT NULL, "
        "duration_ms INTEGER NOT NULL)"
    )
    columns = {row[1] for row in db.execute("PRAGMA table_info(check_sources)")}
    if "not_modified" not in columns:
        db.execute("ALTER TABLE check_sources ADD COLUMN not_modified INTEGER NOT NULL DEFAULT 0")
    db.execute("CREATE INDEX IF NOT EXISTS check_sources_by_url ON check_sources (url, check_id)")
    db.execute("CREATE INDEX IF NOT EXISTS check_sources_by_check ON check_sources (check_id)")


class CheckLog:
    """History of checks and per-source fetch results, behind Feed health and the Activity log.

    Every check is recorded, previews and dry runs included; they never touch
    the seen table. Only the newest MAX_LOGGED_CHECKS checks are kept.
    """

    def __init__(self, path: Path) -> None:
        self._db = sqlite3.connect(path)
        with self._db:
            ensure_check_log_schema(self._db)

    def record(
        self,
        started_at: str,
        duration_ms: int,
        trigger: str,
        saved: bool,
        new_matches: int,
        pruned: int,
        results: Sequence[SourceResult],
        *,
        connection: sqlite3.Connection | None = None,
    ) -> int:
        """Log one check and return its id."""
        if trigger not in CHECK_TRIGGERS:
            raise ValueError(f"unknown check trigger: {trigger}")
        db = self._db if connection is None else connection
        with db if connection is None else nullcontext():
            cursor = db.execute(
                "INSERT INTO checks (started_at, duration_ms, trigger, saved, new_matches, pruned) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (started_at, duration_ms, trigger, int(saved), new_matches, pruned),
            )
            db.executemany(
                "INSERT INTO check_sources "
                "(check_id, name, url, ok, error, item_count, new_matches, duration_ms, not_modified) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (cursor.lastrowid, result.name, result.url, int(result.ok), result.error,
                     result.item_count, result.new_matches, result.duration_ms, int(result.not_modified))
                    for result in results
                ],
            )
            # The new row has the highest id; anything at or below this is past the limit.
            cutoff_id = cursor.lastrowid - MAX_LOGGED_CHECKS
            db.execute("DELETE FROM checks WHERE id <= ?", (cutoff_id,))
            db.execute("DELETE FROM check_sources WHERE check_id <= ?", (cutoff_id,))
        return cursor.lastrowid

    def recent(self, limit: int) -> list[dict[str, Any]]:
        checks = [
            {
                "id": row[0], "started_at": row[1], "duration_ms": row[2], "trigger": row[3],
                "saved": bool(row[4]), "new_matches": row[5], "pruned": row[6],
                "source_count": 0, "failed": [],
            }
            for row in self._db.execute(
                "SELECT id, started_at, duration_ms, trigger, saved, new_matches, pruned "
                "FROM checks ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        ]
        by_id = {check["id"]: check for check in checks}
        if by_id:
            placeholders = ", ".join("?" for _ in by_id)
            for check_id, name, ok, error in self._db.execute(
                f"SELECT check_id, name, ok, error FROM check_sources WHERE check_id IN ({placeholders})",
                tuple(by_id),
            ):
                by_id[check_id]["source_count"] += 1
                if not ok:
                    by_id[check_id]["failed"].append({"name": name, "error": error})
        return checks

    def source_health(self, sources: Sequence[tuple[str, str]]) -> list[dict[str, Any]]:
        """Latest status per configured (name, url); sources are identified by URL.

        Only logged checks count, so "last success" and the failure streak cover
        the newest MAX_LOGGED_CHECKS checks.
        """
        health = []
        for name, url in sources:
            latest = self._db.execute(
                "SELECT checks.started_at, check_sources.ok, check_sources.error, "
                "check_sources.item_count, check_sources.duration_ms, check_sources.not_modified "
                "FROM check_sources JOIN checks ON checks.id = check_sources.check_id "
                "WHERE check_sources.url = ? ORDER BY check_sources.check_id DESC LIMIT 1",
                (url,),
            ).fetchone()
            last_success, last_new_match, failure_streak = self._db.execute(
                "SELECT MAX(CASE WHEN check_sources.ok THEN checks.started_at END), "
                "MAX(CASE WHEN check_sources.new_matches > 0 THEN checks.started_at END), "
                "COUNT(CASE WHEN check_sources.check_id > COALESCE("
                "(SELECT MAX(check_id) FROM check_sources WHERE url = ? AND ok), 0) THEN 1 END) "
                "FROM check_sources JOIN checks ON checks.id = check_sources.check_id "
                "WHERE check_sources.url = ?",
                (url, url),
            ).fetchone()
            entry: dict[str, Any] = {
                "name": name, "url": url, "status": "unchecked", "last_checked": None,
                "last_success": last_success, "last_new_match": last_new_match,
                "item_count": None, "duration_ms": None, "error": "", "failure_streak": failure_streak,
                "not_modified": False,
            }
            if latest:
                started_at, ok, error, item_count, duration_ms, not_modified = latest
                entry.update(
                    status="failing" if not ok else "ok" if not_modified or item_count else "empty",
                    last_checked=started_at, item_count=item_count,
                    duration_ms=duration_ms, error=error, not_modified=bool(not_modified),
                )
            health.append(entry)
        return health

    def close(self) -> None:
        self._db.close()


def error_text(error: Exception) -> str:
    """One printable line describing a fetch failure.

    Not clean_text: error messages are not HTML, and URLError's
    "<urlopen error ...>" would be stripped as a tag, leaving no reason at all.
    """
    is_url_error = isinstance(error, urllib.error.URLError) and not isinstance(error, urllib.error.HTTPError)
    detail = error.reason if is_url_error else error
    text = SPACE_PATTERN.sub(" ", strip_controls(str(detail))).strip()
    return text[:500] or type(error).__name__


@dataclass(frozen=True)
class SourceFetch:
    """One source's fetch: response is None when it failed, and retry_at is set
    when the server asked to be left alone."""

    result: SourceResult
    response: FeedResponse | None
    retry_at: str = ""

    @property
    def items(self) -> list[Item]:
        return self.response.items if self.response else []


def fetch_source(source: Source, settings: Settings, validators: FeedState = FeedState()) -> SourceFetch:
    """Fetch one source; failures become a SourceResult instead of an exception."""
    started = time.monotonic()
    try:
        response = source.fetch(settings, validators)
    except RateLimited as error:
        result = SourceResult(source.name, source.url, False, error_text(error), 0, 0, elapsed_ms(started))
        return SourceFetch(result, None, utc_timestamp(error.retry_at))
    except (OSError, HTTPException, ET.ParseError, ValueError) as error:
        return SourceFetch(SourceResult(source.name, source.url, False, error_text(error), 0, 0, elapsed_ms(started)), None)
    result = SourceResult(
        source.name, source.url, True, "", len(response.items), 0, elapsed_ms(started),
        not_modified=response.not_modified,
    )
    return SourceFetch(result, response)


def fetch_all(
    sources: Sequence[Source],
    settings: Settings,
    validators: Mapping[str, FeedState] = NO_FEED_STATES,
) -> list[SourceFetch]:
    """Fetch sources in parallel, so a check takes as long as its slowest feed
    rather than the sum of all of them. Results keep the order of sources."""
    if not sources:
        return []
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_FETCHES, len(sources))) as pool:
        return list(pool.map(
            lambda source: fetch_source(source, settings, validators.get(source.url, FeedState())),
            sources,
        ))


# A feed counts as due this close to its interval, so a check that runs a few
# seconds early does not push it back a whole extra auto-check period.
DUE_SLACK = timedelta(minutes=1)


def skip_reason(source: Source, state: FeedState, now: datetime) -> str:
    """Why this source is not fetched this check, or "" if it is due."""
    if state.retry_at and state.retry_at > utc_timestamp(now):
        return f"the server asked to wait until {state.retry_at}"
    if source.check_every_minutes and state.saved_at:
        try:
            due_at = datetime.fromisoformat(state.saved_at) + timedelta(minutes=source.check_every_minutes)
        except ValueError:
            return ""  # unreadable (hand-edited) state: fetch rather than fail the check
        if due_at - DUE_SLACK > now:
            return f"checked every {source.check_every_minutes} min; next due {utc_timestamp(due_at)}"
    return ""


@dataclass(frozen=True)
class SkippedSource:
    name: str
    url: str
    reason: str


@dataclass(frozen=True)
class CheckResult:
    """Everything one check found; saving it is the caller's decision.

    matches are new (not in the seen table); seen_updates are already seen and
    only refresh metadata when saved. fetched_items holds each downloaded
    source's items by URL (not 304s). feed_updates holds validator state after
    a successful fetch. Saved checks and previews apply retry_updates separately.
    backfill_sources are the downloaded
    sources with no saved check under the current topics (new feed, new or
    edited topic, cleared History): their matches may be old items.
    """

    matches: tuple[Match, ...]
    seen_updates: tuple[Match, ...]
    source_results: tuple[SourceResult, ...]
    fetched_items: Mapping[str, list[Item]]
    feed_updates: Mapping[str, FeedState]
    retry_updates: Mapping[str, str]
    checked_at: str
    skipped: tuple[SkippedSource, ...]
    backfill_sources: frozenset[str]

    @property
    def failed_sources(self) -> list[str]:
        return [result.name for result in self.source_results if not result.ok]


def topics_fingerprint(topics: Sequence[Topic], settings: Settings) -> str:
    """Identifies what matching would find in a feed. Validators saved under a
    different fingerprint are not sent, so a new or edited topic sees every item
    the feed still has instead of a 304."""
    rules = [[topic.name, list(topic.keywords), list(topic.exclude)] for topic in topics]
    document = json.dumps([rules, settings.max_item_age_days], ensure_ascii=False)
    return hashlib.sha256(document.encode("utf-8")).hexdigest()[:16]


class Watcher:
    def __init__(
        self,
        sources: Sequence[Source],
        topics: Sequence[Topic],
        store: SeenStore,
        settings: Settings,
    ) -> None:
        self._sources = sources
        self._topics = topics
        self._store = store
        self._settings = settings

    def collect(self, feed_states: Mapping[str, FeedState] = NO_FEED_STATES) -> CheckResult:
        """Run one check. feed_states (SeenStore.feed_states) decides which feeds
        are due and which can answer 304; without it every feed is downloaded."""
        now = datetime.now(timezone.utc)
        checked_at = now.isoformat(timespec="microseconds")
        fingerprint = topics_fingerprint(self._topics, self._settings)
        oldest_published_at = self._settings.oldest_published_at(now)

        due: list[Source] = []
        skipped: list[SkippedSource] = []
        for source in self._sources:
            reason = skip_reason(source, feed_states.get(source.url, FeedState()), now)
            if reason:
                skipped.append(SkippedSource(source.name, source.url, reason))
            else:
                due.append(source)
        validators = {
            url: state for url, state in feed_states.items() if state.fingerprint == fingerprint
        }

        pending: dict[tuple[str, str], Match] = {}
        seen_updates: dict[tuple[str, str], Match] = {}
        source_results: list[SourceResult] = []
        fetched_items: dict[str, list[Item]] = {}
        feed_updates: dict[str, FeedState] = {}
        retry_updates: dict[str, str] = {}
        backfill_sources: set[str] = set()
        for source, fetch in zip(due, fetch_all(due, self._settings, validators)):
            previous = feed_states.get(source.url, FeedState())
            if fetch.response is None:
                source_results.append(fetch.result)
                if fetch.retry_at:
                    retry_updates[source.url] = fetch.retry_at
                print(f"warning: {source.name}: {fetch.result.error}", file=sys.stderr)
                continue
            feed_updates[source.url] = FeedState(
                fetch.response.etag, fetch.response.last_modified, fingerprint, checked_at, ""
            )
            retry_updates[source.url] = ""
            if fetch.response.not_modified:
                source_results.append(fetch.result)
                continue
            fetched_items[source.url] = fetch.items
            if previous.fingerprint != fingerprint or not previous.saved_at:
                backfill_sources.add(source.url)
            new_matches = 0
            for match in self._match(fetch.items, oldest_published_at):
                match = replace(match, feed_url=source.url)
                if self._store.contains(match.topic, match.item.link):
                    seen_updates.setdefault(match.key, match)
                elif match.key not in pending:
                    pending[match.key] = match
                    new_matches += 1
            source_results.append(replace(fetch.result, new_matches=new_matches))
        return CheckResult(
            matches=tuple(pending.values()),
            seen_updates=tuple(seen_updates.values()),
            source_results=tuple(source_results),
            fetched_items=fetched_items,
            feed_updates=feed_updates,
            retry_updates=retry_updates,
            checked_at=checked_at,
            skipped=tuple(skipped),
            backfill_sources=frozenset(backfill_sources),
        )

    def _match(self, items: Iterable[Item], oldest_published_at: str) -> Iterable[Match]:
        for item in items:
            if not item.link or not is_recent(item, oldest_published_at):
                continue
            for topic in self._topics:
                keywords = topic.matched_keywords(item.searchable_text)
                if keywords:
                    yield Match(topic.name, item, tuple(keywords))


def is_recent(item: Item, oldest_published_at: str) -> bool:
    """False only for items with a known date before the cutoff; undated items pass."""
    return not (oldest_published_at and item.published_at and item.published_at < oldest_published_at)


# The versioned records other programs read (INTEGRATION.md). Bump a version
# when a field changes meaning or goes away; adding a field does not.
EVENT_SCHEMA = "hounddog.event/1"
COVERAGE_SCHEMA = "hounddog.coverage/1"
REVISION_SCHEMA = "hounddog.revision/1"
EXPORT_DIR_NAME = "exports"


def event_id(link: str) -> str:
    """Identifies an article across checks, topics, and exports."""
    return hashlib.sha256(link.encode("utf-8")).hexdigest()[:16]


def feed_status(result: SourceResult) -> str:
    if not result.ok:
        return "failed"
    return "unchanged" if result.not_modified else "ok"


def export_records(
    check_id: int, trigger: str, started_at: str, saved: SavedCheck, result: CheckResult, config: Config
) -> list[dict[str, Any]]:
    """One saved check as export records: its coverage, then one event per
    article it found new for at least one topic, then the revisions it saw."""
    run_id = uuid4().hex
    coverage: dict[str, Any] = {
        "schema": COVERAGE_SCHEMA,
        "check_id": check_id,
        "run_id": run_id,
        "trigger": trigger,
        "started_at": started_at,
        "finished_at": saved.saved_at,
        "topics": [
            {"name": topic.name, "fingerprint": topics_fingerprint([topic], config.settings)}
            for topic in config.topics
        ],
        "feeds": [
            *(
                {"name": source.name, "url": source.url, "status": feed_status(source),
                 "items": source.item_count, "new_matches": source.new_matches, "detail": source.error,
                 "backfill": source.url in result.backfill_sources}
                for source in result.source_results
            ),
            *(
                {"name": skip.name, "url": skip.url, "status": "skipped",
                 "items": 0, "new_matches": 0, "detail": skip.reason}
                for skip in result.skipped
            ),
        ],
    }
    by_link: dict[str, list[Match]] = {}
    for match in result.matches:
        by_link.setdefault(match.item.link, []).append(match)
    events = []
    for link, matches in by_link.items():
        item = matches[0].item
        feed_url = matches[0].feed_url
        events.append({
            "schema": EVENT_SCHEMA,
            "event_id": event_id(link),
            "check_id": check_id,
            "run_id": run_id,
            "trigger": trigger,
            "detected_at": saved.saved_at,
            "released_at": item.published_at or None,
            "released_raw": item.published,
            "source": item.source,
            "feed_url": feed_url,
            "link": link,
            "title": item.title,
            "summary": item.summary,
            "author": item.author,
            "topics": [
                {"name": match.topic, "keywords": list(match.keywords), "feed_url": match.feed_url,
                 "backfill": match.feed_url in result.backfill_sources}
                for match in matches
            ],
            "backfill": feed_url in result.backfill_sources,
        })
    revisions = [
        {
            "schema": REVISION_SCHEMA,
            "event_id": event_id(revision.link),
            "check_id": check_id,
            "run_id": run_id,
            "observed_at": revision.observed_at,
            "link": revision.link,
            "changed": list(revision.changed),
            "title": revision.title,
            "released_at": revision.published_at or None,
            "released_raw": revision.published,
            "previous_title": revision.previous_title,
            "previous_released_at": revision.previous_published_at or None,
        }
        for revision in saved.revisions
    ]
    return [coverage, *events, *revisions]


def export_line(record: dict[str, Any]) -> str:
    """One JSON Lines line. U+2028 and U+2029 are valid inside JSON strings, but
    str.splitlines() and similar readers break lines at them."""
    text = json.dumps(record, ensure_ascii=False)
    return text.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def ensure_export_schema(db: sqlite3.Connection) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS export_outbox ("
        "id INTEGER PRIMARY KEY, day TEXT NOT NULL, line TEXT NOT NULL)"
    )


def append_jsonl(path: Path, payload: bytes) -> None:
    """Recover an incomplete final line and durably append complete records."""
    with path.open("a+b", buffering=0) as stream:
        end = stream.seek(0, os.SEEK_END)
        if end:
            stream.seek(end - 1)
            if stream.read(1) != b"\n":
                position = end
                while position:
                    start = max(0, position - 4096)
                    stream.seek(start)
                    newline = stream.read(position - start).rfind(b"\n")
                    if newline >= 0:
                        position = start + newline + 1
                        break
                    position = start
                stream.truncate(position)
        if stream.write(payload) != len(payload):
            raise OSError("Incomplete HoundDog export write")
        os.fsync(stream.fileno())


class EventExport:
    """Append-only JSON Lines files for other programs, one per UTC day:
    directory/hounddog-YYYY-MM-DD.jsonl, written for every saved check.

    Records wait in watcher.db's export_outbox until they are written, so a file
    that cannot be written now (locked, disk full) is written by a later check.
    HoundDog never rewrites or deletes these files; History retention does not
    reach them. Delivery is at least once: a crash between writing a file and
    clearing the outbox repeats those lines, so readers deduplicate by schema,
    run_id, and event_id where present.
    """

    def __init__(self, db_path: Path, directory: Path) -> None:
        self._db = sqlite3.connect(db_path)
        self._directory = directory
        with self._db:
            ensure_export_schema(self._db)

    def queue(
        self, day: str, records: Iterable[dict[str, Any]], *, connection: sqlite3.Connection | None = None
    ) -> None:
        db = self._db if connection is None else connection
        with db if connection is None else nullcontext():
            db.executemany(
                "INSERT INTO export_outbox (day, line) VALUES (?, ?)",
                [(day, export_line(record)) for record in records],
            )

    def pending(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM export_outbox").fetchone()[0]

    def flush(self) -> int:
        """Append every queued record to its day's file, oldest first, and return
        how many were written. Raises OSError (a file) or sqlite3.Error (watcher.db
        busy), leaving the records queued.

        BEGIN IMMEDIATE takes watcher.db's write lock first, so the dashboard and
        the background job never write the same records twice."""
        self._db.execute("BEGIN IMMEDIATE")
        try:
            rows = self._db.execute("SELECT id, day, line FROM export_outbox ORDER BY id").fetchall()
            if rows:
                self._directory.mkdir(parents=True, exist_ok=True)
                by_day: dict[str, list[str]] = {}
                for _id, day, line in rows:
                    by_day.setdefault(day, []).append(line)
                for day, lines in by_day.items():
                    path = self._directory / f"hounddog-{day}.jsonl"
                    append_jsonl(path, ("\n".join(lines) + "\n").encode("utf-8"))
                self._db.execute("DELETE FROM export_outbox WHERE id <= ?", (rows[-1][0],))
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise
        return len(rows)

    def close(self) -> None:
        self._db.close()


def render(matches: Sequence[Match]) -> str:
    if not matches:
        return "No new matches."
    lines: list[str] = []
    for topic in dict.fromkeys(match.topic for match in matches):
        lines.append(f"== {topic} ==")
        for match in matches:
            if match.topic != topic:
                continue
            item = match.item
            published = f"{item.published} | " if item.published else ""
            lines.append(f"[{item.source}] {item.title}")
            lines.append(f"  {item.link}")
            lines.append(f"  {published}matched: {', '.join(match.keywords)}")
        lines.append("")
    return "\n".join(lines).rstrip()


def is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.hostname)


def tables(raw: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(entry, dict) for entry in value):
        raise ConfigError(f"'{key}' must be an array of tables ([[{key}]])")
    return value


def require_text(entry: dict[str, Any], key: str, context: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{context}: '{key}' must be a non-empty string")
    return value.strip()


def string_list(entry: dict[str, Any], key: str, context: str, required: bool) -> list[str]:
    value = entry.get(key, [])
    valid = isinstance(value, list) and all(
        isinstance(term, str) and term.strip("* ") for term in value
    )
    if not valid:
        raise ConfigError(f"{context}: '{key}' must be a list of non-empty strings")
    if required and not value:
        raise ConfigError(f"{context}: '{key}' must not be empty")
    return [term.strip() for term in value]


MIN_SOURCE_INTERVAL = 1
MAX_SOURCE_INTERVAL = 7 * 24 * 60


@dataclass(frozen=True)
class Config:
    sources: tuple[Source, ...]
    topics: tuple[Topic, ...]
    settings: Settings

    @classmethod
    def load(cls, path: Path) -> Config:
        try:
            with path.open("rb") as handle:
                raw: dict[str, Any] = tomllib.load(handle)
        except OSError as error:
            raise ConfigError(f"cannot read {path}: {error.strerror or error}") from error
        except tomllib.TOMLDecodeError as error:
            raise ConfigError(f"invalid TOML in {path}: {error}") from error

        sources = tuple(
            cls._parse_source(entry, index)
            for index, entry in enumerate(tables(raw, "sources"), start=1)
        )
        topics = tuple(
            cls._parse_topic(entry, index)
            for index, entry in enumerate(tables(raw, "topics"), start=1)
        )
        if not sources or not topics:
            raise ConfigError("need at least one [[sources]] and one [[topics]] entry")
        names = [topic.name for topic in topics]
        if len(set(names)) != len(names):
            raise ConfigError("topic names must be unique")
        return cls(sources, topics, Settings.from_table(raw.get("settings", {})))

    @staticmethod
    def _parse_source(entry: dict[str, Any], index: int) -> Source:
        context = f"sources #{index}"
        url = require_text(entry, "url", context)
        if not is_http_url(url):
            raise ConfigError(f"{context}: url must be an http:// or https:// URL with a host")
        interval = entry.get("check_every_minutes")
        if interval is not None and (
            isinstance(interval, bool) or not isinstance(interval, int)
            or not MIN_SOURCE_INTERVAL <= interval <= MAX_SOURCE_INTERVAL
        ):
            raise ConfigError(
                f"{context}: 'check_every_minutes' must be a whole number from "
                f"{MIN_SOURCE_INTERVAL} to {MAX_SOURCE_INTERVAL}"
            )
        return Source(name=require_text(entry, "name", context), url=url, check_every_minutes=interval)

    @staticmethod
    def _parse_topic(entry: dict[str, Any], index: int) -> Topic:
        context = f"topics #{index}"
        return Topic(
            name=require_text(entry, "name", context),
            keywords=string_list(entry, "keywords", context, required=True),
            exclude=string_list(entry, "exclude", context, required=False),
        )


def configure_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")


def data_directory() -> Path:
    program = sys.executable if getattr(sys, "frozen", False) else __file__
    return Path(program).resolve().parent


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    program_dir = data_directory()
    parser = argparse.ArgumentParser(
        description="HoundDog checks RSS/Atom feeds for new items matching your topics.",
        epilog="Examples:\n"
        "  python watcher.py --dry-run\n"
        "  python watcher.py --interval 15",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=program_dir / "watch.toml",
        help="TOML configuration file (default: watch.toml beside the app)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=program_dir / "watcher.db",
        help="SQLite seen-items database (default: watcher.db beside the app)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print matches without marking them seen"
    )
    parser.add_argument(
        "--interval",
        type=float,
        metavar="MINUTES",
        help="check repeatedly every MINUTES (stop with Ctrl+C)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="validate the configuration and exit",
    )
    parser.add_argument(
        "--scheduled",
        action="store_true",
        help="one saved check, logged as Scheduled (used by the Windows task the dashboard installs)",
    )
    return parser.parse_args(argv)


def reload_config(path: Path, current: Config) -> Config:
    """Pick up edits (e.g. from the dashboard) between interval checks."""
    try:
        return Config.load(path)
    except ConfigError as error:
        print(f"warning: keeping previous configuration: {error}", file=sys.stderr)
        return current


@dataclass(frozen=True)
class CheckOutcome:
    """A finished check. export_error is why the event export is behind ("" when
    it is up to date or turned off); its records stay queued for the next check."""

    result: CheckResult
    pruned: int
    export_error: str
    history_reset: bool = False


HISTORY_RESET_DURING_CHECK = "History was cleared during the check. Run the check again."


def perform_check(
    config: Config, store: SeenStore, check_log: CheckLog, export: EventExport, save: bool, trigger: str
) -> CheckOutcome:
    """One check, as the CLI, the background job, and the dashboard all run it:
    collect; then save, prune, and log it, and export it if saved."""
    started_at, started = utc_timestamp(), time.monotonic()
    generation = store.history_generation()
    result = Watcher(config.sources, config.topics, store, config.settings).collect(store.feed_states())
    with store.transaction() as db:
        if store.history_generation() != generation:
            return CheckOutcome(result, 0, "", history_reset=True)
        if not save:
            store.save_backoff(result, commit=False)
            check_log.record(
                started_at, elapsed_ms(started), trigger, False, len(result.matches), 0,
                result.source_results, connection=db,
            )
            return CheckOutcome(result, 0, "")
        matches = tuple(match for match in result.matches if not store.contains(*match.key))
        if len(matches) != len(result.matches):
            counts = Counter(match.feed_url for match in matches)
            result = replace(result, matches=matches, source_results=tuple(
                replace(source, new_matches=counts[source.url]) for source in result.source_results
            ))
        saved = store.save_check(result, commit=False)
        pruned = store.prune(config.settings.history_retention_days, commit=False)
        check_id = check_log.record(
            started_at, elapsed_ms(started), trigger, True, len(result.matches), pruned, result.source_results,
            connection=db,
        )
        if config.settings.event_export:
            export.queue(
                started_at[:10], export_records(check_id, trigger, started_at, saved, result, config), connection=db
            )
    export_error = ""
    if config.settings.event_export:
        try:
            export.flush()
        except (OSError, sqlite3.Error) as error:
            export_error = f"{error} (records are queued for the next saved check)"
    return CheckOutcome(result, pruned, export_error)


def export_directory(db_path: Path) -> Path:
    return db_path.with_name(EXPORT_DIR_NAME)


def run_cli_check(
    config: Config, store: SeenStore, check_log: CheckLog, export: EventExport, dry_run: bool, trigger: str = "cli"
) -> CheckResult:
    outcome = perform_check(config, store, check_log, export, not dry_run, trigger)
    if outcome.history_reset:
        print(f"warning: {HISTORY_RESET_DURING_CHECK}", file=sys.stderr)
        return replace(outcome.result, matches=(), source_results=())
    for skipped in outcome.result.skipped:
        # Informational, so stdout: the background job log keeps only problems.
        print(f"skipped: {skipped.name}: {skipped.reason}")
    print(render(outcome.result.matches))
    if dry_run:
        print("\nDry run: matches were not marked as seen.")
    elif outcome.pruned:
        print(f"\nForgot {outcome.pruned} item(s) older than "
              f"{config.settings.history_retention_days} day(s).")
    if outcome.export_error:
        print(f"warning: event export not written yet: {outcome.export_error}", file=sys.stderr)
    return outcome.result


# Exit codes. Task Scheduler shows them as the task's last result.
EXIT_OK = 0
EXIT_ALL_FEEDS_FAILED = 1
EXIT_USAGE_OR_CONFIG = 2
EXIT_CRASHED = 3

JOB_LOG_NAME = "background-job.log"
MAX_JOB_LOG_BYTES = 256 * 1024


def append_job_log(path: Path, heading: str, text: str) -> None:
    """Add one entry to the background job's log, keeping roughly the newest
    MAX_JOB_LOG_BYTES. A log that cannot be written must not fail the check."""
    entry = f"{heading}\n{text.rstrip()}\n"
    try:
        old = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        combined = old + entry
        if len(combined.encode("utf-8")) > MAX_JOB_LOG_BYTES:
            combined = combined[-(MAX_JOB_LOG_BYTES // 2):]
            combined = combined[combined.find("\n") + 1:]
        path.write_text(combined, encoding="utf-8")
    except OSError:
        pass


def run_scheduled(args: argparse.Namespace) -> int:
    """One --scheduled run. Under pythonw.exe nothing reaches a console, so
    whatever would have gone to stderr (failed feeds, configuration errors, a
    traceback) is written to JOB_LOG_NAME beside the database instead."""
    captured = io.StringIO()
    previous_stdout, previous_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = io.StringIO(), captured
    try:
        code = run(args)
    except Exception:
        traceback.print_exc(file=captured)
        code = EXIT_CRASHED
    finally:
        sys.stdout, sys.stderr = previous_stdout, previous_stderr
    if captured.getvalue().strip():
        append_job_log(args.db.with_name(JOB_LOG_NAME), f"{utc_timestamp()} exit {code}", captured.getvalue())
    return code


def main(argv: Sequence[str] | None = None) -> int:
    configure_output()
    args = parse_args(argv)
    if args.scheduled and (args.dry_run or args.interval is not None or args.validate):
        print("error: --scheduled runs one saved check; it cannot be combined with "
              "--dry-run, --interval, or --validate", file=sys.stderr)
        return EXIT_USAGE_OR_CONFIG
    if args.interval is not None and args.interval <= 0:
        print("error: --interval must be greater than zero", file=sys.stderr)
        return EXIT_USAGE_OR_CONFIG
    return run_scheduled(args) if args.scheduled else run(args)


def run(args: argparse.Namespace) -> int:
    try:
        config = Config.load(args.config)
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE_OR_CONFIG

    if args.validate:
        print(
            f"Valid configuration: {len(config.sources)} source(s), "
            f"{len(config.topics)} topic(s)."
        )
        print(f"XML parser: {xml.parsers.expat.EXPAT_VERSION}")
        return EXIT_OK

    store = SeenStore(args.db)
    check_log = CheckLog(args.db)
    export = EventExport(args.db, export_directory(args.db))
    try:
        if args.interval is None:
            trigger = "scheduled" if args.scheduled else "cli"
            result = run_cli_check(config, store, check_log, export, args.dry_run, trigger)
            attempted = len(result.source_results)
            return EXIT_ALL_FEEDS_FAILED if attempted and len(result.failed_sources) == attempted else EXIT_OK

        print(
            f"Watching {len(config.sources)} source(s) every "
            f"{args.interval:g} minute(s). Stop with Ctrl+C."
        )
        try:
            while True:
                config = reload_config(args.config, config)
                try:
                    run_cli_check(config, store, check_log, export, args.dry_run)
                except (sqlite3.Error, OSError) as error:
                    # A locked or briefly unavailable database skips one check
                    # instead of stopping the watcher.
                    print(f"warning: check failed, retrying next interval: {error}", file=sys.stderr)
                time.sleep(args.interval * 60)
        except KeyboardInterrupt:
            print("\nWatcher stopped.")
            return EXIT_OK
    finally:
        store.close()
        check_log.close()
        export.close()


if __name__ == "__main__":
    sys.exit(main())
