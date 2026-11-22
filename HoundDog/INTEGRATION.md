# HoundDog and ThetaData: integration plan

Status: HoundDog's side is built (2026-11-22). The bridge and the ThetaData
app's output are next, once that app joins this workspace.

Goal: find correlations between the news HoundDog collects and market data
from a separate ThetaData app, while each program keeps working on its own.

## Decisions

Made on 2026-11-22:

1. **The bridge contains it all.** A third program reads each app's output and
   does the joining, the topic-to-symbol mapping, time zone conversion, the
   analysis, and the combined dashboard. HoundDog and the ThetaData app only
   produce their own output; neither reads or writes the other's files.
2. **One output per app, with shared conventions** (below), so the bridge reads
   both the same way.
3. **First seen is fixed.** An article keeps the headline and date it had when
   HoundDog first saw it. Later changes are recorded separately, as revisions.
4. **History and the export are separate.** History is the dashboard's reading
   list and keeps its retention setting. The export is the research archive;
   retention never touches it.

## Shared output conventions

What each app's output should follow, so the bridge treats them alike:

- JSON Lines (one JSON object per line), UTF-8, LF line endings.
- Append-only files, one per UTC day, in a folder owned by that app.
- Every record has a `schema` field naming its type and version, such as
  `hounddog.event/1`. A version changes only when a field changes meaning or is
  removed; new fields can appear at any time, so readers ignore what they do
  not know.
- Times are ISO 8601 in UTC with an explicit offset (`+00:00`), or `null` when
  unknown. Never a local time without an offset.
- Records can repeat (delivery is at least once); each schema names the fields
  that identify a record.

ThetaData's v2 API gives times as `ms_of_day` (milliseconds since midnight,
US Eastern) plus a `date`
([ThetaData HTTP docs](https://http-docs.thetadata.us/operations/get-v2-snapshot-stock-ohlc.html)).
Whether the ThetaData app converts them to UTC in its own output, or the bridge
does, is still open; converting in the app keeps the bridge to joining only.

## HoundDog's output

Every saved check (command line, background job, or dashboard) appends records
to `exports/hounddog-YYYY-MM-DD.jsonl` beside `watcher.db`. The day is the UTC
day the check started. Previews and dry runs write nothing.

- On by default; `event_export = false` in `[settings]` (or Settings > Data in
  the dashboard) turns it off.
- Text is UTF-8; U+2028 and U+2029 inside strings are escaped, so every line
  break is a record break.
- Records are queued in `watcher.db` (`export_outbox`) in the same transaction
  that saves History and the check log, then appended. If a file cannot be written (open elsewhere
  with a lock, disk full), the records stay queued and a later check writes
  them, in order. That includes a database too busy to write in time. The
  dashboard's check notice and `background-job.log` say when that happens.
- HoundDog preserves all complete lines. A retry repairs an interrupted final line.
- A check's records come in this order: one coverage record, then its events,
  then its revisions.
- New records share one `run_id` per saved check. It survives export retries
  and remains unique when `watcher.db` is replaced. `check_id` identifies the
  check inside its original database. Legacy records have only the numeric ID,
  which can be ambiguous across database resets.

### `hounddog.coverage/1`: one per saved check

Answers "was HoundDog watching, and which feeds did it read?" A gap between
coverage records is a time HoundDog was not checking (PC off or asleep, server
stopped, a failed check). "No events" is only meaningful inside coverage.

```json
{
  "schema": "hounddog.coverage/1",
  "check_id": 33,
  "run_id": "22212b1dce7b416a80e03bdd980e3df8",
  "trigger": "scheduled",
  "started_at": "2026-11-22T15:33:00+00:00",
  "finished_at": "2026-11-22T15:33:02+00:00",
  "feeds": [
    {"name": "BBC News", "url": "https://feeds.bbci.co.uk/news/rss.xml",
     "status": "ok", "items": 33, "new_matches": 1, "detail": ""}
  ]
}
```

- `trigger`: `cli`, `scheduled` (background job), `dashboard`, or `auto`
  (dashboard tab auto-check).
- `status`: `ok`, `unchanged` (answered 304), `failed` (`detail` has the
  error), or `skipped` (not due, or backing off; `detail` says why).
- `items`: how many items the feed had; not how many were new to it.
- Identified by `run_id` when present.
- New records include `topics`, with a name and matching-rule fingerprint for
  each active topic. Older records have unknown topic coverage. Fetched feeds
  also include `backfill`, which flags the first download under the current rules.

### `hounddog.event/1`: one per article a check found new

```json
{
  "schema": "hounddog.event/1",
  "event_id": "3f6c1d0a9b2e4c71",
  "check_id": 33,
  "run_id": "22212b1dce7b416a80e03bdd980e3df8",
  "trigger": "scheduled",
  "detected_at": "2026-11-22T15:33:02+00:00",
  "released_at": "2026-11-22T15:20:11+00:00",
  "released_raw": "Sun, 22 Nov 2026 15:20:11 GMT",
  "source": "BBC News",
  "feed_url": "https://feeds.bbci.co.uk/news/rss.xml",
  "link": "https://www.bbc.co.uk/news/articles/c6ly5w40eg07o",
  "title": "Headline as first seen",
  "summary": "Summary as first seen",
  "author": "",
  "topics": [{"name": "Breaking", "keywords": ["outage"]}],
  "backfill": false
}
```

- `event_id`: identifies the article (the first 16 hex digits of the SHA-256
  of its canonical link), the same in every record about it.
- `detected_at`: when HoundDog knew; equal to History's `first_seen`. Use it for
  anything that could be acted on.
- `released_at`: when the source says it came out (RSS `pubDate`, Atom
  `published`, else Atom `updated`), in UTC; `null` when the feed gives no date
  or no usable time zone. `released_raw` is the feed's text.
- `topics`: every topic that matched the article for the first time in this
  check, with the keywords that matched.
- Each new topic match also includes its own `feed_url` and `backfill`. Use
  these fields for per-topic analysis when several feeds matched the same article.
- `backfill`: true when this feed had no saved check under the current topics
  (a new feed, a new or edited topic, `max_item_age_days` changed, or History
  cleared). Such items may have been in the feed long before HoundDog looked,
  so they are not live detections. A genuinely new item that arrives in the
  same check is flagged too.
- Identified by `event_id` and `run_id` when present.

An article can have more than one event:

- A topic added later that matches it gives a later event with only that topic.
- After History retention removes an article, it can be found again and gets a
  new event, with a `detected_at` long after `released_at`.

For "when did HoundDog first know about this article", use its earliest
`detected_at`.

### `hounddog.revision/1`: an article's headline or date changed

```json
{
  "schema": "hounddog.revision/1",
  "event_id": "3f6c1d0a9b2e4c71",
  "check_id": 41,
  "run_id": "73f25ee3cba154a3846eebafa2ab1b97",
  "observed_at": "2026-11-22T16:13:01+00:00",
  "link": "https://www.bbc.co.uk/news/articles/c6ly5w40eg07o",
  "changed": ["title"],
  "title": "New headline",
  "released_at": "2026-11-22T15:20:11+00:00",
  "released_raw": "Sun, 22 Nov 2026 15:20:11 GMT",
  "previous_title": "Headline as first seen",
  "previous_released_at": "2026-11-22T15:20:11+00:00"
}
```

- `changed` holds `title`, `released_at`, or both. A value the feed leaves out is
  not a change; summaries are not tracked.
- Changes are seen only while the article is still in its feed and still
  matches a topic (any topic, including one added later), and only when its
  feed is downloaded (not on a 304).
- Identified by `event_id` and `run_id` when present.

## What HoundDog does not provide

- **News volume (base rates).** Coverage gives each feed's item count per
  check, not how many items were new, because HoundDog only remembers matched
  items. Counting all new items would mean storing every link of every feed.
- **One story across outlets.** The same story from three outlets is three
  events with different `event_id`s. Grouping them belongs in the bridge (or in
  HoundDog's planned story grouping).
- **Symbols.** Topics are mapped to tickers in the bridge.
- **Market time.** HoundDog stays UTC-only and dependency-free.

## The bridge (next)

- Reads both apps' output folders. It can keep its own index of what it has
  read, or simply reread the daily files.
- Deduplicates records by the fields each schema names.
- Holds the topic-to-symbol mapping, for example `Breaking → AMZN`.
- Converts to market time with daylight saving time. On Windows, Python's
  `zoneinfo` needs the `tzdata` package for that; that is fine in the bridge.
- Maps news outside regular trading hours to the next session's open, keeping
  the original time too.
- First study (event study): for each event and symbol, the return (and, with
  options data, implied volatility and volume) over fixed windows after the
  event, such as 5 and 30 minutes and 1 day. Compare against the same windows
  at random covered times, or at the same time of day on days without events.
- Pitfalls to plan for:
  - look-ahead (use `detected_at` for anything tradeable);
  - many keyword and symbol pairs tested at once (expect false positives;
    hold data out);
  - overlapping events;
  - backfill events;
  - small samples. With three feeds and two topics, History held 35 articles
    after about a day, so per-keyword samples will take weeks.

## Combined dashboard (eventually)

Part of the bridge, never part of HoundDog's dashboard:

- a price (or implied volatility) chart per symbol with news events as markers;
- an event-study table per topic and keyword (average move after events against
  baseline, with counts);
- a coverage strip showing when HoundDog was and was not watching;
- filters by topic, source, and released or detected time.

## Open questions about the ThetaData app

- Language and stack, and where it keeps its data (files, a database, or live
  terminal requests only).
- ThetaData API version (v2 or v3), and which instruments: stocks, options,
  indices.
- Which measures to correlate (price returns, volume, implied volatility), and
  at what resolution (ticks, minute bars, daily).
- Research on past data, live monitoring, or both.
- Its output: what it writes today, and what it should write under the shared
  conventions above.

## Review notes (2026-11-22)

Fixed in the review before this work:

- Feed dates with an unknown time zone were stored as UTC (hours off). They are
  now stored as "no usable date".
- `watcher.py --interval` stopped at the first database error, such as
  "database is locked". It now warns and tries again at the next interval.
- Turning feed images on or off did not redraw the Inbox.
- Importing a backup let the backup's read state override an article that was
  unread here. Local state now wins for articles already in History.

Known, not changed:

- An open dashboard tab does not reload while the background job saves new
  matches, so its Inbox goes stale until the page refreshes.
- The check log behind Health and Log keeps 1,000 checks; coverage in the
  export is the complete record.
- None of the current feeds supports conditional requests, so each check
  downloads them in full; gzip and per-feed intervals still help.
