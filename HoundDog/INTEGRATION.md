# ThetaHound export contract

HoundDog exports news and check coverage. ThetaDesk exports daily bars and
the dates it looked up. Bridge reads both exports for the daily study.

## Ownership

Each producer owns its database and exports. Bridge joins the exported data,
maps topics to tickers, and assigns trading sessions in New York time.
HoundDog's History is its reading list, with retention and read state. The
export keeps a research archive of saved checks, detections, and revisions.

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

With export enabled, every saved check appends records to
`exports/hounddog-YYYY-MM-DD.jsonl` beside `watcher.db`. The filename uses
the UTC date when the check started. Previews and dry runs appear in the
local check log.

- On by default; `event_export = false` in `[settings]` (or Settings > Data in
  the dashboard) turns it off.
- Text is UTF-8; U+2028 and U+2029 inside strings are escaped, so every line
  break is a record break.
- Records are queued in `watcher.db` (`export_outbox`) in the same transaction
  that saves History and the check log, then appended. If delivery fails,
  the committed rows stay queued for a later check. The dashboard's check
  notice and `background-job.log` report delivery errors.
- HoundDog preserves all complete lines. A retry repairs an interrupted final line.
- A check's records come in this order: one coverage record, then its events,
  then its revisions.
- New records share one `run_id` per saved check. It survives export retries
  and remains unique when `watcher.db` is replaced. `check_id` identifies the
  check inside its original database. Legacy records have only the numeric ID,
  which can be ambiguous across database resets.

### `hounddog.coverage/1`: one per saved check

Coverage records show which topics and feeds a saved check used. A record
can contain only failures or skipped feeds. Gaps show where the reader has
no exported coverage. Previews, disabled export, or delayed writes can
also leave gaps.

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
- `items` counts items returned for that feed. `new_matches` counts its
  new topic matches.
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
- The event-level `backfill` describes the feed represented at the top
  level. A per-topic `backfill` describes that match's own feed. The flag
  means the feed had no saved check under the current rules, as when a
  feed or topic is added, matching rules change, or History is cleared.
  The first download can find old and newly published items together.
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

## Consumer notes

- Coverage item counts describe each feed response. HoundDog tracks links
  for articles that match a topic. A count of all newly published feed
  items requires tracking the full feed.
- Article IDs identify canonical URLs. Different publishers' URLs can
  describe the same story and still have distinct IDs.
- Bridge deduplicates records by schema and record ID. It uses
  `check_id` as a fallback for legacy records with no `run_id`.

## How Bridge reads these records

Bridge keeps its topic-to-ticker mappings in `bridge.toml`. When a user
adds a ticker, Bridge asks HoundDog's local API to create the topic.

The study uses the earliest detection that matched any of the ticker's
topics. A live match takes priority if that detection also includes
backfill matches. If all its matching topics are backfill, Bridge
excludes the article for that ticker. Friday at or after the close
through Sunday goes into the weekend list. Other detections go to the
current session before the close or the next trading session after it.
Quiet sessions need a calculable return and a qualifying check outside
the weekend window. Revision records are counted in export status.
Placement uses the original detection event.

The CLI and dashboard use the same report. Rules and examples are in the
[Bridge guide](../bridge/README.md#what-the-report-means).
