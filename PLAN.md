# theta_hound handoff

Current behavior and open issues from the November 22, 2026 review.
The [workspace README](README.md) covers setup, startup, builds, and shutdown.

## What runs where

| App | Startup and ownership |
| --- | --- |
| [HoundDog](HoundDog/README.md) | The launcher opens `HoundDog/HoundDog.exe` on 8080. The source server is `HoundDog/watcher_server.py`. The app and the scheduled job use the config, History database, and news exports beside the executable or source. |
| [ThetaDesk](ThetaDesk/README.md) | The launcher opens `ThetaDesk/dist/ThetaDesk/ThetaDesk.exe` on 8000. The source wrapper prepares a venv and starts `api.py`. Source and package share the database, pins, and exports in `%LOCALAPPDATA%/ThetaDesk`. Each reads credentials from its own app directory. |
| [Bridge](bridge/README.md) | The launcher runs `bridge/server.py` on 8090. Bridge reads both export directories. It adds topics through HoundDog's API and loads bars and shares pins through ThetaDesk's API. The study works from saved exports with both producers stopped. |

`build.bat --no-pause` builds both Windows packages and returns a nonzero
status if either build fails. Shut down their running dashboards before
replacing the installed executables. Bridge runs from source. The packaged
HoundDog task uses `HoundDogScheduled.exe` and continues independently of
the dashboard. A build can upgrade the old task's executable for the same
checkout while preserving the task's settings and triggers.

## Data and dashboard behavior

- HoundDog commits saved History rows, the check log, and export queue
  entries in one SQLite transaction. A History clear invalidates checks
  already in progress and keeps existing research exports. Preview checks
  can affect feed backoff and activity without saving new matches. Dashboard
  auto-check sends at most one desktop notification per run with new
  articles, with counts for topic matches and distinct articles.
  [Export contract](HoundDog/INTEGRATION.md)
- ThetaDesk caches lookups and preserves the original value of a stored bar.
  Today's bar is eligible to be stored from 6 p.m. ET. Stored bars and
  shared pins open locally. Pin changes stay in the database.
  [Market storage](ThetaDesk/README.md#store-and-export-daily-bars)
- Bridge's weekly news shows live detections before prices arrive. Friday
  at or after the NYSE close through Sunday appears under **Full week** in
  **Weekend news**. Monday through Thursday after-close detections belong
  to the next trading session. Quiet sessions need a calculable move and
  a successful feed read from a check watching the ticker outside the
  weekend window. The activity strip shows weekend checks too, on their
  New York calendar dates, with success and failure proportions.
  [Study rules](bridge/README.md#what-the-report-means)
- Ticker cards can load about a year of prices and fetch missing recent
  sessions. A daily bar that's still pending keeps the normal incremental
  update available. The chosen date range applies to the chart and ticker
  detail. Weekly news navigates by detection week and the main summary uses
  the full saved sample. Chart markers open the corresponding session and
  its articles. Shared pins save and restore fixed date ranges.
  [Dashboard](bridge/README.md#dashboard)
- `HoundDog/watch.toml` and `bridge/bridge.toml` are tracked settings that
  the dashboards can modify. The current working copy includes HoundDog's
  expanded feed and topic lists and Bridge's expanded ticker mappings.
  Databases, exports, build outputs, logs, and credentials stay local.

## Open issues and operational limits

| Item | Current behavior |
| --- | --- |
| Provider quota | Simultaneous ThetaDesk lookups for the same gap can each call the provider. CLI and API rate limits are independent. The store deduplicates the resulting bars. |
| Partial ThetaDesk fetch | A request can save earlier ranges before a later range fails. A normal retry picks up the remaining gaps. A blocked export can delay later fetches even though committed bars remain readable. |
| Credentials and restore | ThetaDesk serializes credential saves and replaces each file atomically. Changes to the key and the account still span two files. HoundDog's combined restore can commit History before a config write fails. Retrying merges History without duplicating it. |
| Launcher readiness | The chooser checks prerequisites and port availability, then starts the processes. A later startup failure is reported in the console or `logs/<app>.log`. |
| External feeds | Some feeds intermittently fail or rate-limit checks. HoundDog's Health panel shows feed outcomes and backoff. Bridge's activity graph shows successful attempts, failures, and skipped feeds separately. |
| Study sample | A comparison needs enough overlapping live news, quiet checks, and saved prices. Use the [demo](bridge/README.md#demo) for a populated example. The comparison describes the sample and supports no conclusion about causation or timing within the day. |

## Pre-commit verification

- HoundDog: 131 Python tests. ThetaDesk: 75 Python tests. Bridge: 62 Python
  tests. The two dashboard JavaScript suites pass 81 tests together.
- Specific regressions covered include desktop notification failure after a
  saved check, a pending daily bar retrying only the remaining history,
  weekend checks appearing only as activity, mixed backfill/live detections,
  and Bridge skipping malformed bar prices while keeping valid records.
- Native batch fixtures exercise both successful builds and each failure
  path in a checkout with spaces. A fixture for the ThetaDesk raw CLI
  verifies that SDK INFO authentication payloads stay out of its output
  while warnings and lookup results still appear.
- A full offline build in an isolated copy booted both packages. The
  windowless runner saved and exported a local RSS match, the packaged
  HoundDog dashboard read it, and ThetaDesk preserved its fixture
  credential files and saved a pin. Both dashboard shutdown routes
  stopped their processes.
- An isolated Edge test covered the weekly split, the 995-of-1,003 feed
  success ratio, keyboard controls, a 360 px layout, and incremental
  price retries while the last bar was pending. Live dashboards answered
  their status requests, and the installed HoundDog job reported Ready
  with the windowless runner.

<details>
<summary>Implementation history from November 22, 2026</summary>

## Review of the offline work (2026-11-22)

Read on 2026-11-22 at 14:00. HoundDog's suite passes, 121 Python and 66 Node
tests, after the fixes below. ThetaDesk's suite cannot run in Claude's
workspace (FastAPI and the SDK are not installed there), so its tests were read
rather than run.

Fixed in this review:

- **The launcher could not start ThetaDesk.** `launch.py`, the workspace
  README, and the ThetaDesk README still pointed at `ThetaData\`, which no
  longer exists after the rename.
- **Three HoundDog export fixes were lost.** The offline work started from a
  `watcher.py` older than the final review pass, so they were reapplied with
  their tests:
  - escaping U+2028 and U+2029, so `splitlines()` readers keep records whole;
  - catching `sqlite3.Error` from the export flush, so a busy `watcher.db`
    delays the export instead of failing a check that already saved;
  - recording revisions for new topic rows of known articles (the test now
    covers a headline only the new topic matches).

Kept from the offline work (improvements):

- HoundDog saves History, the check log, and the export queue in one
  transaction, which closes the crash gap between them.
- A History generation counter: a check that overlaps Clear history is
  discarded.
- Backoff ordering by observation time (`retry_observed_at`).
- `run_id` on export records, plus per-topic `feed_url` and `backfill`.
- Recovery of an interrupted final line in both apps' exports.
- ThetaDesk's market store: a transactional outbox, coverage ranges,
  validation of every provider row, and an Origin check on the fetch endpoint.

Real data, checked: `HoundDog/exports/hounddog-2026-11-22.jsonl` holds 521
records with no duplicates and a coverage record for every saved check. 515 of
its 517 events are backfill, from the feeds and topics added at 11:38, so the
first live sample is 2 events.

Open, not changed (decide or verify):

1. **Two ThetaDesk data locations. Fixed (14:35):** the source app and the
   executable now share `%LOCALAPPDATA%\ThetaDesk` for `market.db` and
   `exports/`, which survives rebuilds. The bridge reads
   `%LOCALAPPDATA%\ThetaDesk\exports`. The source folder held no data, so
   nothing moved. The real store there checks out: 251 AAPL daily bars
   (2025-11-21 to 2026-11-20), no duplicates, no weekend sessions, and
   consistent OHLC values.
2. **A bar for today may be provisional.** `fetch_daily_bars` records a range
   as covered once a bar for its last day exists, and stored bars are never
   updated (`ON CONFLICT DO NOTHING`, even with `--refresh`). If the provider
   returns a bar for today before the end-of-day report is final, that bar
   stays forever. Assumption to verify: whether ThetaData returns today's
   bar during the session. A safe rule: treat today as covered, or store its
   bar, only after a set time in the evening (Eastern).
3. **Empty answers are cached as coverage.** `NoDataFoundError` becomes `[]`,
   and a past range with no rows is recorded as fetched. That is right for
   holidays. For a typo or a symbol the free tier refuses, it is wrong until
   `--refresh`.
4. **`YYYYMMDD` needed Python 3.11. Fixed in the second pass:** the normalizer
   parses it explicitly, as the launcher still accepts 3.10.
5. **`fetch.py` stopped at the first failing symbol. Fixed in the second
   pass:** it reports each failure, fetches the rest, and exits 1 if any
   failed.
6. **SDK internals.** `theta_data._python_client` wraps
   `client.stub.GetStockHistoryEod` to add a timeout. This works with the
   pinned SDK but breaks silently if a release renames the stub. The pin
   protects it; keep the test that covers it.
7. **The HoundDog executable's background job opened a console window (fixed).**
   The packaged task now uses `HoundDogScheduled.exe`. The build switches
   a legacy task for the same checkout to the new action and preserves its
   schedule and settings. Source installs continue to use `pythonw.exe` when
   available.
8. **Credentials stay beside the running app. Decided (14:31).** The user puts
   `.env` and `creds.txt` beside `dist\ThetaDesk\ThetaDesk.exe`, or saves them
   from Settings; rebuilds carry them over. A source run reads its own
   `ThetaDesk\.env`, which is a developer setup.
9. **CORS default.** CORS allows `localhost:3000` by default
   (`FRONTEND_ORIGIN`). The current review above supersedes the earlier
   assessment of the credential route.

### Second pass (2026-11-22, 14:15)

Fixed, each with a test that fails on the previous code:

- **HoundDog's tab auto-check stopped silently when the background job could
  not be read.** Auto-check refreshes the job first, so a job installed
  elsewhere pauses the tab, and a failed refresh made every later run skip.
  It now decides by the last known mode, and the job panel still shows the
  error.
- **ThetaDesk:** `YYYYMMDD` parsing on Python 3.10, and `fetch.py` continuing
  past a failing ticker (items 4 and 5 above).
- **The ThetaDesk frontend** showed a JSON parse error instead of the real
  message when the server answered with a non-JSON error page.

Test status:

- HoundDog: 121 Python and 67 Node tests pass.
- ThetaDesk: Claude's workspace has no FastAPI, SDK, or Polars, so only the
  market store tests ran, with small stand-ins: 11 of 12 pass, and the twelfth
  needs real Polars. Run the full suite in the venv:
  `python -m unittest discover -s tests`.

## Order of work

1. **Done.** ThetaData fixes: the credential leak (1), pinned versions (4),
   and checking the REST date format (3). These are small and independent.
2. **Done.** ThetaData: normalizer and `theta.bar/1`, then `market.db`, the fetch command,
   and the export. Tests with recorded SDK and REST responses, like HoundDog's
   fakes.
3. **Done.** Bridge reader: `bridge.toml`, symbols with their HoundDog topics,
   deduplicated loading of both exports, and an NYSE calendar
   (`market_calendar.py`) that matches all 251 real AAPL sessions.
4. **Done.** Daily study and report (`bridge.py report`, `--json`). Quiet
   sessions count only when HoundDog watched the symbol's topic. Decisions
   made in building it:
   - the standard library only, plus `tzdata`; no pandas or Polars yet;
   - no bridge database; it rereads the daily files, which are small;
   - a session counts as watched after one check in its window.
5. **Done.** Bridge dashboard (FastAPI, `bridge/server.py`, port 8090): both
   apps' status, the study per ticker and group, a price chart with news
   sessions marked, and "watch tickers". Watching creates one HoundDog topic
   per ticker through HoundDog's API and records the ticker, and any group, in
   `bridge.toml`. A group is a bridge-only set of tickers whose sessions are
   pooled. It is never a single HoundDog topic, so news about one company
   never counts for another.
6. **Done.** Cleanup pass on the bridge and launcher. Fixed:
   - a ticker listed twice replaced or double-counted silently;
   - rewriting `bridge.toml` dropped unknown tables;
   - existing HoundDog topics were recognised by message text; now by status
     409;
   - the browser could keep a stale `app.js`; assets are now versioned by
     content hash;
   - the watched-session test scanned every check (now a binary search);
   - prices without coverage records produced an empty study with no
     explanation.
7. **Done.** Demo dataset (`bridge/make_demo.py`, output in `bridge/demo/`,
   not in git): a year of `[DEMO]` news and checks around real ThetaDesk
   prices, planted on big-move days. Its config has no HoundDog connection
   (`[hounddog] url = ""`) and shows a banner (`[display] banner`).

Workspace work after step 7 (2026-11-22, afternoon):

- **Start menu.** Each app has a "Show terminal" box (on by default). A hidden
  app runs with no console window, its output in `logs\<app>.log`, and no
  stdin, so a prompt fails instead of waiting unseen.
- **Shut down from each page.** HoundDog (last toolbar tool, with a confirm
  flyout), ThetaDesk and the bridge (top bar). Each finishes requests in
  progress, then exits; Ctrl+C does the same. ThetaDesk and the bridge set
  uvicorn's `should_exit`; HoundDog counts requests from their headers to
  their answer, so an idle browser connection does not hold it up. ThetaDesk
  now always starts through `api.serve()` (`python api.py` from source).
- **ThetaDesk pins and loaded tickers.** Pins (ticker plus fixed dates) are
  saved in `market.db` and redrawn from stored bars. "Loaded tickers" lists
  every ticker with stored bars and opens its latest year without calling
  ThetaData. Pins are not exported.
- **Cleanup pass.** Found and fixed: HoundDog's shutdown waited for idle
  browser connections, so it could hang. A bridge test pinned `bridge.toml` to
  AAPL, which broke once tickers were added from the dashboard.

8. **Done.** Making the study obvious on the dashboard:
   - a session-by-session table with the reason for each label;
   - a count breakdown per ticker;
   - plain-language article placement, including excluded articles;
   - a one-line verdict per ticker;
   - a "how to read this" box.

Later, outside the MVP:

- intraday bars and short windows (5 and 30 minutes), with a paid plan;
- related-company topics;
- a local research agent driving the watchlist and the study through the CLI
  and HTTP interfaces.

</details>
