# HoundDog project guide

HoundDog is a local RSS/Atom keyword watcher with a terminal interface and a
small browser dashboard. The README has the user-facing setup and command
instructions; this file is a quick architecture and maintenance map.

## Project layout

- `watcher.py`: feed parsing, keyword matching, SQLite seen-item storage, and
  the CLI. Uses only the Python standard library (Python 3.11+).
- `watcher_server.py`: standard-library HTTP server and JSON API for the
  dashboard. It reads and writes the project files beside itself.
- `hounddog_app.py` and `build_exe.ps1`: Windows executable entry point and
  build. The bundle provides dashboard assets. Configuration, SQLite, and
  exports live beside the executable. Scheduled runs use `watch --scheduled`.
- `scheduled_task.py`: the Windows Task Scheduler job (`\HoundDog\Saved check`)
  that runs `watcher.py --scheduled`, managed by the server's `/api/schedule`
  endpoints through PowerShell's ScheduledTasks cmdlets.
- `watch.toml`: source-of-truth configuration for feeds, topics, and the
  optional `[settings]` table (`watcher.Settings`).
- `watcher.db`: source-of-truth SQLite database for seen items, their saved
  feed metadata, per-article read/starred state (`item_state`), per-feed fetch
  state (`feed_state`), later headlines and dates (`item_revisions`), export
  records not yet written (`export_outbox`), and the check log.
- `exports/`: the event export, created beside `watcher.db` by the first saved
  check (see `INTEGRATION.md`). Output for other programs, not a data store
  HoundDog reads back.
- `index.html`, `styles.css`, `app.js`: dependency-light dashboard frontend.
- `pico-main/css/pico.min.css`: local Pico CSS used by the dashboard.
- `kongtext/kongtext.ttf`: local font used by the NES theme; NES.css itself is
  loaded from a pinned CDN release.
- `INTEGRATION.md`: the event export's record formats (`hounddog.coverage/1`,
  `hounddog.event/1`, `hounddog.revision/1`) and how Bridge joins them with
  ThetaDesk's market data. The formats are a
  contract other programs read: read it before changing what History stores,
  how timestamps are recorded, or any exported field.
- `tests/dashboard.test.js`: Node built-in tests for dashboard rendering and
  preferences.
- `tests/test_watcher.py`: Python `unittest` coverage for parsing, persistence,
  and database migration.
- `tests/test_server.py`: `unittest` coverage for the dashboard server's
  request guards, static allowlist, input validation, the tool endpoints, and
  startup.
- `tests/test_scheduled_task.py`: the task definition and every PowerShell call,
  with a fake runner (`FakePowerShell`) instead of PowerShell.

## Data behavior

- `watcher.perform_check` is the one check sequence the CLI, the background job,
  and the dashboard's `/api/check` share: `Watcher.collect` (a frozen
  `CheckResult`), then `save_check`, `prune`, `CheckLog.record` (which returns
  the check id), and the event export; or, for a preview, `save_backoff` and the
  log only. Change the sequence there, not in a caller.
- A saved check stores newly matched items. Rows already seen keep their
  first-seen values (`_insert_matches` only fills blanks, keeping `published`
  and `published_at` as a pair); a new non-empty title or `published_at` is
  stored in `item_revisions` by `_record_revisions`, compared against the
  article's newest revision, else its earliest row. Prune and Clear history
  remove revisions with their articles.
- The event export (`EventExport`, `export_records`): a saved check's records
  are queued in `export_outbox` and appended to
  `exports/hounddog-YYYY-MM-DD.jsonl` (`export_directory`) by `flush`, which
  holds `BEGIN IMMEDIATE` so two processes never write the same rows. A failed
  write leaves them queued and becomes `CheckOutcome.export_error` (dashboard
  notice, job log). A saved check commits History, validators, the check log,
  and the outbox together. Preserve all complete export lines. A retry may
  discard an interrupted final fragment before appending synced records. Schema names
  (`EVENT_SCHEMA` and the others) change version only when a field changes
  meaning or goes away. `backfill` comes from `CheckResult.backfill_sources`:
  feeds downloaded with no saved check under the current fingerprint.
- Sources are fetched in parallel by `watcher.fetch_all` (up to
  `MAX_PARALLEL_FETCHES`), so a check takes as long as its slowest feed.
  Results keep source order. The SQLite connection stays on the calling thread.
- The server runs one `/api/check` at a time (`CHECK_LOCK`), so two tabs cannot
  both report the same items as new. The CLI and the background job are
  separate processes and share the saved-check SQLite transaction. It rechecks
  pending matches under the write lock to avoid duplicate detections.
- `POST /api/shutdown` (the toolbar's Shut down tool) ends `serve_forever`.
  `main` then calls `DashboardServer.wait_for_requests()`, on Ctrl+C too, so a
  check or config write in progress finishes before the process exits. A
  request counts from `parse_request` (headers read) until
  `handle_one_request` returns. Idle connections, which browsers open
  speculatively, are not counted; their daemon threads end with the process.
  `DashboardHandler.timeout` (15 seconds per socket read or write) ends a
  request whose client stops sending, so it cannot hold up a shutdown.
  The background job is a separate process and keeps running.
- The background job: `TaskScheduler` (in `scheduled_task.py`) builds the task
  XML (`task_xml`: TimeTrigger repetition with no Duration, so indefinite;
  `IgnoreNew` so runs never overlap; allowed on battery; `StartWhenAvailable`)
  and drives PowerShell. `GET /api/schedule` reports `JobStatus`; `PUT` with
  `interval_minutes` (one of `JOB_INTERVALS`) creates or replaces the task;
  `POST /api/schedule/run` starts it; `DELETE` removes it. Every answer is the
  task's status afterwards. Off Windows, `supported` is false and changes
  answer 501; Task Scheduler failures answer 502 with PowerShell's message.
  `runs_this_folder` is false when the task points at another HoundDog copy.
- `watcher.py --scheduled` is one saved check logged with the `scheduled`
  trigger. `run_scheduled` captures what `run` writes to stderr (and any
  traceback) and appends it to `JOB_LOG_NAME` (`background-job.log`) beside the
  database, trimmed to about `MAX_JOB_LOG_BYTES`; a clean run writes nothing.
  Exit codes are `EXIT_OK` 0, `EXIT_ALL_FEEDS_FAILED` 1, `EXIT_USAGE_OR_CONFIG`
  2, `EXIT_CRASHED` 3, and become the task's last result. Informational output
  (skipped feeds) goes to stdout so the log holds only problems.
- `JobOptions` (`interval_minutes` from `JOB_INTERVALS`, `run_on_battery`,
  `catch_up`, `require_network`) is the `PUT /api/schedule` body and becomes the
  task's conditions. `JobStatus.options` is read back from the task, `None` if
  it was edited to something the dashboard cannot show; `command_found` is
  false when the task's program no longer exists. Every `/api/schedule`
  answer adds `log` (`job_log_tail`); `DELETE /api/schedule/log` empties it.
- Automatic checks have one mode (`CheckingMode` in `app.js`): "background"
  whenever the task is installed (Task Scheduler is the source of truth, shared
  by every browser), otherwise this browser's `keyword-watcher-check-mode`
  ("off" or "dashboard"). Mode changes are explicit transitions: install or
  remove the task, then store the browser's choice; choosing the job stores
  "off". While the task exists the tab's `AutoChecker` is configured to 0, so
  two schedulers never run. Before the mode key existed, an
  `auto-check-interval` of "0" meant off; `readStoredMode` converts it once.
  On a failed change the job is re-read, so the panel shows what Task
  Scheduler really has.
- `/api/health` adds `conditional` per feed: whether its last saved download
  had an ETag or Last-Modified (`feed_validators`), or null before one.
- Fetch errors go through `watcher.error_text`, not `clean_text`: error strings
  are not HTML, and `URLError`'s `<urlopen error ...>` would be stripped as a tag.
- `--dry-run` and the dashboard's Preview only action must preserve History
  and saved feed validators. They can write check logs and feed backoff.
- The database migration in `watcher.ensure_seen_schema` adds metadata columns
  while preserving existing seen rows. Steps that rewrite stored data are
  versioned with `PRAGMA user_version` (`SEEN_SCHEMA_VERSION`) and run once;
  version 1 (`normalize_stored_history`) canonicalized links, merging
  duplicates, and filled `published_at`.
- History is keyed by `watcher.canonical_link` (tracking parameters and
  fragments removed, host lowercased, path and other parameters kept byte for
  byte). Feed parsing, the migration, and import all apply it. Changing its
  rules changes keys: add a schema version that migrates stored links.
- `published` is the feed's raw date for display; `published_at` is
  `normalize_published(published)` (UTC, or NULL), for sorting and
  `max_item_age_days`. Import recomputes it rather than trusting the file. A
  date without a usable time zone (CET, IST, `-0000`, an ISO time without an
  offset) is NULL, never assumed UTC: market correlation depends on these
  times, and a guessed zone is hours wrong.
- Article-level lookups (`item_state` joins, retention's starred check) go
  through the `seen_by_link` index; the primary key leads with topic.
- The dashboard calls starred articles "favorites" (the star button, the
  Favorites filter); the data, API, and code keep `starred` / `starred_at`.
- Read and starred state belongs to the article: `item_state` is keyed by link,
  so every topic row of an article shares it, and topics matching it later
  inherit it. Rows with neither flag are deleted. `/api/items/state` takes an
  explicit list of links (the dashboard sends what it rendered), never "all
  unread", so an article arriving between render and click is not marked read
  unseen. `SeenStore.prune` keeps starred articles and removes state of
  articles it deletes; Clear history removes all state.
- `feed_state` holds each feed's validators (`ETag`, `Last-Modified`), the
  topic `fingerprint` they were saved under, `saved_at`, and `retry_at`:
  - Overlapping checks only advance validator state. Retry backoff tracks its
    own observation time so an older request cannot undo a newer outcome.
  - Validators are written only by `SeenStore.save_check` (a saved check, in the
    same transaction as its matches). Previews use `save_backoff`, which writes
    only `retry_at`. If a preview moved the validators, the next saved check
    would get 304 for items it never stored.
  - Validators are sent only while `topics_fingerprint` (topics and
    `max_item_age_days`) matches the one they were saved with, so a new or
    edited topic sees every item instead of a 304.
  - `retry_at` comes from 429/503 `Retry-After` (`retry_time`, capped at
    `MAX_BACKOFF`) and applies to every check. `check_every_minutes` on a
    source skips it until `saved_at` plus that interval (`skip_reason`).
    Skipped sources are reported in `CheckResult.skipped` and the
    `/api/check` response, not in the check log.
  - Clear history blanks the validators and `saved_at` (keeping `retry_at`), so
    the next check downloads everything again.
  - The tester's refresh never sends validators; it needs the items, not a 304.
    A 304 never replaces `LATEST_ITEMS` for that feed.
- Blank columns of existing rows can be filled only while their feed items are
  still available; do not delete or recreate the database as part of routine
  changes.
- The dashboard calls seen items "History". The database table, CLI, and API
  (`seen_items`, `seen_count`, `/api/seen`) keep the `seen` name.
- `/api/dashboard` returns the full history; search and pagination run in the
  browser (`PagedList` in `app.js`). Move both server-side if history grows
  past roughly 10,000 items.
- Settings live in one of two places. Anything the CLI needs (fetch limits,
  user agent, history retention) goes in `[settings]` in `watch.toml`,
  validated by `watcher.Settings.from_table`, which rejects unknown keys.
  Dashboard-only preferences (theme, images, auto-check, notifications, page
  sizes, open tab) go in browser `localStorage` under `keyword-watcher-*`.
- `SeenStore.prune` runs after every saved check (CLI and dashboard), never on
  a dry run. Retention compares `first_seen` strings, so every writer must use
  UTC `isoformat(timespec="seconds")`; import normalizes to that.
- Every check (CLI, dashboard, auto-check; saved or dry run) is recorded by
  `watcher.CheckLog` in the `checks` and `check_sources` tables, trimmed to the
  newest `MAX_LOGGED_CHECKS` (1000). The log never touches `seen` rows. The
  trigger is one of `CHECK_TRIGGERS`; the dashboard sends it in the
  `/api/check` body. Feed health (`/api/health`) and the activity log
  (`/api/activity`) are read from these tables.
- `/api/topic-test` evaluates keywords server-side with `Topic.evaluate`, so
  the tester matches real checks exactly (Python regex, not JS, and the same
  `max_item_age_days` filter through `watcher.is_recent`). Its "latest"
  corpus is `LATEST_ITEMS`, an in-memory cache filled by every check and by the
  tester's refresh; it is empty after a server restart until one of those runs.
  A source that fails keeps its previous items, so each source keeps its own
  fetch time and the tester reports the oldest one in use.
- Feeds and topics are edited by position (`/api/feeds/<n>`, `/api/topics/<n>`),
  and positions shift when another tab or a hand edit changes the list. Every
  `PUT` and `DELETE` must send `expected` (the entry as the client last saw it),
  compared on every editable field by `ConfigList.fields`: name, URL and
  interval for feeds; name, keywords and excludes for topics. The server
  answers 409 if that position now holds something else, including the same
  entry changed by another tab, so a stale tab cannot overwrite it. The
  dashboard keeps the original entry being edited (`editingFeed`,
  `editingTopic`, the tester's name-keyed `<select>`), looks up its current
  position before saving, and reloads the list on a 409. Never store a bare
  index as edit state.
- `/api/import` validates the whole document before writing anything, replaces
  the config only through `write_config`, and merges history with
  `ON CONFLICT DO NOTHING`. A backup's read/favorite state applies only to
  articles not already in History (inserted before the rows, guarded by
  `NOT EXISTS`); for articles already here, local state wins. It is the only
  endpoint with a larger body limit (`MAX_IMPORT_BYTES`).
- `watcher.py --interval` survives a failed check (`sqlite3.Error`, `OSError`):
  it warns and tries again at the next interval.

## Dashboard structure

- The left toolbar holds tools. A tool is a `.tool-button[data-tool="name"]`
  plus a `#tool-name` flyout section in `index.html`; the `Toolbar` class in
  `app.js` opens one flyout at a time. Add tools there rather than placing
  actions in the page header. Tools stack from the top; Settings is pinned to
  the bottom with `.tool-button-bottom` and opens upward (`.tool-flyout-bottom`).
  Tools that load data when opened register a callback in the `onOpen` map
  passed to `Toolbar` (Tester, Health, Log). `.tool-button.has-alert` draws the
  red dot used by Health.
- Settings sections are `.settings-nav-button[data-panel="name"]` plus a
  `#settings-name` section inside `#tool-settings`. The main tabs and these
  sections both use the `TabGroup` class, which remembers the last choice.
- The UI size slider zooms the root element. Size fixed panels with
  `--app-viewport-width` / `--app-viewport-height` rather than raw `vw`/`vh`,
  or they overflow the window when zoomed in.
- Matches, Inbox, and History share `renderArticleCard` and the `PagedList`
  class. Page sizes are multiples of 12 so rows stay full at 1 to 4 grid columns.
  `PagedList.setFilter` narrows entries before search (History's All / Unread /
  Starred). The Inbox's entries are articles (`unreadArticles` groups History
  rows by link and lists their topics); History's are rows.
- Cards for saved articles get `article.state`, which adds `data-link`,
  `data-read`, `data-starred`, the read button, and the ★/☆ favorite button
  (`aria-pressed`, labelled "Add to/Remove from favorites"); Matches cards have no
  state. `handleSavedItemClick` handles those buttons and marks an article
  read when it is opened (click or middle-click on either `ARTICLE_LINKS`).
- The card banner (`a.article-media`) is a second link to the article, only
  when `safeHttpUrl` accepts the link (otherwise a plain `div`). It duplicates
  the text link, so it has `tabindex="-1"` and `aria-hidden="true"`.
- `refresh()` can overlap with itself (an auto-check finishing during an edit);
  only the newest `/api/dashboard` response renders (`refreshRequestId`), like
  the tester's `testerRequestId`.

## Security invariants

- The server answers only allowlisted `Host` headers (DNS rebinding) and
  refuses requests whose `Origin` is not the dashboard itself.
- `POST`/`PUT` require `Content-Type: application/json`, which forces a CORS
  preflight that the server never grants. Keep it that way; do not add CORS
  headers or an `OPTIONS` handler.
- Only files listed in `STATIC_FILES` are served. Add new frontend assets
  there explicitly; never serve the project directory generically.
- Every response carries the CSP and related headers from `SECURITY_HEADERS`.
  Keep the frontend free of inline scripts and inline `style` attributes.
- Feed text and URLs pass through `watcher.clean_text`, which strips control
  characters; dashboard links and images go through `safeHttpUrl`.
- `watch.toml` is written atomically under `CONFIG_LOCK`. Every write starts
  from `read_raw_config`, which raises on a malformed `sources` or `topics`
  value (`watcher.tables`) so a save can never silently drop entries.
- `DashboardServer` binds its port exclusively on Windows
  (`SO_EXCLUSIVEADDRUSE`, no `SO_REUSEADDR`). With reuse on, a second server
  shares the port and a forgotten old process keeps answering with stale code.
- Feed XML is parsed only through `watcher.parse_feed_xml`, which refuses entity
  declarations; never call `ET.fromstring` on fetched bytes directly.
- PowerShell scripts in `scheduled_task.py` are fixed strings, sent with
  `-EncodedCommand`; their inputs (task path, name, XML) travel in `HOUNDDOG_*`
  environment variables. Never format request data into a script. The task
  command is built only from `sys.executable` and the project path.
- Gzip bodies are inflated only through `watcher.gunzip_limited`, which stops at
  `max_feed_bytes` (gzip bombs). `ETag`/`Last-Modified` values are sent back only
  after `validator_header` drops long or control-character values.
- If the NES.css version changes, update its `integrity` hash in `app.js`.
- The CSV export prefixes values starting with `=`, `+`, `-`, `@`, tab, or
  carriage return with `'` (`spreadsheet_safe`), because feed text is
  untrusted and spreadsheets would otherwise evaluate it as a formula.
- Feed images are opt-in (`show-images`), since loading one reveals the
  user's IP address to the publisher.

## Theme gotchas

- NES.css loads after `styles.css` and sets `position: relative`, padding, and
  (for `.is-dark`) a margin on every `.nes-container`. Anything fixed or
  absolutely positioned that `applyTheme` gives `nes-container` (currently the
  toolbar flyouts) needs an `html[data-app-theme="nes"]` override to keep its
  positioning. Kongtext is 1em per character, so check label widths in NES.

## Run and verify

```powershell
python watcher.py --validate
python watcher.py --dry-run
python watcher.py
python watcher_server.py
```

On Windows, `start_server.bat` starts the dashboard server from the project
folder and forwards optional server arguments.

Open `http://127.0.0.1:8080` for the dashboard. Run the focused test suites
after relevant changes:

```powershell
node --test tests\dashboard.test.js
python -m unittest discover -s tests -p "test_*.py"
```

Keep the frontend dependency-light and preserve `watch.toml` and `watcher.db`
as the authoritative data stores. Restart the dashboard server after changing
Python server code.
