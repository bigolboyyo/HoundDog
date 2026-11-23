# HoundDog and ThetaDesk integration

HoundDog exports news and check coverage. ThetaDesk exports daily bars and
the dates it looked up. Bridge reads both exports for the daily study.

## Decisions

Made on 2026-11-22:

1. **The bridge contains it all.** A third program reads each app's output and
   does the joining, the topic-to-symbol mapping, time zone conversion, the
   analysis, and the combined dashboard. HoundDog and ThetaDesk each own
   their output and keep working independently.
2. **One output per app, with shared conventions** (below), so the bridge reads
   both the same way.
3. **First seen is fixed.** An article keeps the headline and date it had when
   HoundDog first saw it. Later changes are recorded separately, as revisions.
4. **History and the export are separate.** History is the dashboard's reading
   list and keeps its retention setting. The export is the research archive;
   retention never touches it.

## Shared output conventions

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

ThetaDesk converts the regular session open to UTC before export and retains
the New York session date. Its market and coverage records are specified in
the [ThetaDesk guide](../ThetaDesk/README.md#store-and-export-daily-bars).

## HoundDog's output

Every saved check (command line, background job, or dashboard) appends records
to `exports/hounddog-YYYY-MM-DD.jsonl` beside `watcher.db`. The day is the UTC
day the check started. Previews and dry runs do not write to this export.

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
  "topics": [{"name": "Breaking", "fingerprint": "d0244e1330b0823c"}],
  "feeds": [
    {"name": "BBC News", "url": "https://feeds.bbci.co.uk/news/rss.xml",
     "status": "ok", "items": 33, "new_matches": 1, "detail": "", "backfill": false}
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
  "topics": [
    {"name": "Breaking", "keywords": ["outage"],
     "feed_url": "https://feeds.bbci.co.uk/news/rss.xml", "backfill": false}
  ],
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

## How Bridge reads these records

Bridge rereads the export folders and deduplicates records by schema key. It
keeps its topic-to-ticker mappings in `bridge.toml`. When a user adds a ticker
from the Bridge dashboard, Bridge asks HoundDog's local API to create the topic.
HoundDog still owns the resulting configuration.

The study assigns each article by its first matching detection in New York
time. If that first detection was backfill, the article is excluded for that
ticker. On a trading day, detections before the scheduled close go to that
session. Detections at or after the close, or on a closed day, go to the next
trading session. The analysis uses close-to-close returns and compares news
sessions with sessions that have a return and a qualifying HoundDog check
without an eligible article. Revision records are counted in export status.
Article placement uses the detection event.

The CLI and dashboard use the same report. Rules and examples are in the
[Bridge guide](../bridge/README.md#what-the-report-means).

## Review notes (2026-11-22)

Fixed in the review before this work:

- Feed dates with an unknown time zone were stored as UTC (hours off). They are
  now stored as "no usable date".
- `watcher.py --interval` stopped at the first database error, such as
  "database is locked". It now warns and tries again at the next interval.
- Turning feed images on or off did not redraw the Inbox.
- Importing a backup let the backup's read state override an article that was
  unread here. Local state now wins for articles already in History.

Known limits:

- An open dashboard tab does not reload while the background job saves new
  matches, so its Inbox goes stale until the page refreshes.
- The check log behind Health and Log keeps 1,000 checks; coverage in the
  export is the complete record.
- Conditional requests depend on each feed. The Health view reports whether
  the last saved download supplied a usable validator.
