# theta_hound handoff

This handoff covers current dashboard behavior and the open review findings
from November 22, 2026.

## What is running

| Component | Startup and ownership |
| --- | --- |
| HoundDog | The launcher runs `HoundDog/HoundDog.exe` on 8080. The source server is `HoundDog/watcher_server.py`. Both use the configuration, SQLite database, and news exports beside the running app. A Windows scheduled task can save checks separately. |
| ThetaDesk | The launcher runs `ThetaDesk/dist/ThetaDesk/ThetaDesk.exe` on 8000 with the Terminal prompt disabled. The source wrapper starts `api.py` in its venv. Both use the same market database and export directory in `%LOCALAPPDATA%/ThetaDesk`. Each start reads credentials from its own app directory. |
| Bridge | The launcher runs `bridge/server.py` on 8090. It rereads both exports for its CLI and dashboard and writes its own ticker mappings. It uses HoundDog's API to add topics. |

Use the [workspace startup guide](README.md) for launch, rebuild, and shutdown.
The app guides document their endpoints and storage.
[HoundDog](HoundDog/README.md), [ThetaDesk](ThetaDesk/README.md), [Bridge](bridge/README.md)

## Current behavior and data

- HoundDog saves History, check logs, and export queue entries in one SQLite
  transaction. Clearing History invalidates overlapping checks and preserves
  the research exports. Dashboard previews can record check activity and
  backoff without saving new History. [Export contract](HoundDog/INTEGRATION.md)
- ThetaDesk normalizes daily bars from the SDK and the optional Terminal REST
  fallback. Normal loads fill lookup gaps. Refresh can add missing bars, and
  stored bars retain their original values. Loaded tickers and fixed-range
  pins use local data. Pins are outside the integration exports.
- Bridge groups eligible articles by NYSE session using first detection time.
  A quiet session needs both a return and a qualifying HoundDog check. The CLI
  and dashboard use the same report. The dashboard shows session counts,
  reasons, article placement and exclusions, and a short verdict per ticker.
- Bridge's watchlist can now load or update prices through ThetaDesk. The
  chart opens session evidence from news markers and a coverage strip. Date
  ranges can be saved and reopened through ThetaDesk's shared pins.
- The live export snapshot had 251 daily bars each for AAPL, MSFT, and TSLA
  through November 20. Each ticker had 250 calculable returns and zero news
  or quiet sessions. HoundDog started watching the ticker topics after the
  last stored close. The sample needs overlapping price data and live checks.
  The demo is available for inspecting a populated report.

## Review findings

1. **ThetaDesk credentials can be sent to an allowed CORS origin. Fixed
   (evening):** the credential GET and PUT refuse other origins, and CORS
   allows none by default (`FRONTEND_ORIGIN` is empty). Verified in Chrome:
   before, a page on `localhost:3000` read the API key; now it is blocked.
   The GET now reports only what is saved (and the email address), never the
   key or password; on save a blank field keeps the saved value, and
   `clear_api_key` / `clear_credentials` remove them. Still open: the raw
   CLI's INFO logging. Originally: the
   credentials GET returns the API key and password. CORS allows configured
   origins for GET, including the default development origin, and the
   credential route checks the network peer without checking Origin.
   Prefer configuration status in the response, explicit keep and clear
   operations on save, and same-origin checks for settings. The raw CLI also
   enables INFO logging, where the installed SDK logs the authentication
   response, including the session identifier.
   [API implementation](ThetaDesk/api.py), [Raw CLI](ThetaDesk/main.py)
2. **ThetaDesk's source wrapper can terminate a working API on Ctrl+C. Fixed
   (evening):** on Ctrl+C the wrapper waits up to 60 seconds for the API to
   finish and exit; a second Ctrl+C stops it at once. Originally: the
   parent immediately calls `terminate()` on a running child from
   `finally`. A check with a fake child confirmed that path. Give the API time
   to finish after the console interrupt before terminating it. The dashboard
   shutdown endpoint separately passed its graceful shutdown smoke test.
   [Startup implementation](ThetaDesk/start_project.py)
3. **HoundDog's executable predates the latest shutdown source. Body read
   fixed (evening):** each socket read or write now times out after 15
   seconds, so a stalled body ends after that instead of holding up shutdown
   (verified: still running after 25 seconds before, exited after 15 after).
   Rebuild the executable to include it. Originally: the existing
   binary starts and shuts down during an ordinary smoke test. Its build time
   is earlier than the request-tracking changes in the worktree. Rebuild and
   retest the package before relying on the current shutdown behavior there.
   Separately, current source counts a request before reading its body, and
   the body read has no socket timeout. A client that stops sending can leave
   shutdown waiting. Bound the read while preserving valid in-progress work.
   [Server implementation](HoundDog/watcher_server.py)
4. **ThetaDesk can show a ticker different from the current form selection.
   Fixed (evening):** both paths take a lookup number, and only the most
   recent may draw the result; a test holds a late answer back. Originally:
   verified with a delayed history response and a more recent **Loaded tickers**
   selection. Both paths write the same result panel, so a late response can
   replace the newer choice. Track the most recent lookup across both paths.
   [Dashboard implementation](ThetaDesk/frontend/app.js)
5. **HoundDog accepts stale edits to the same topic or feed. Fixed
   (evening):** `expected` is compared on every editable field
   (`ConfigList.fields`), so a save or delete from a tab that missed another
   tab's change gets 409 and the page reloads the list. Originally: verified with
   two ordinary topic edits based on the same input snapshot. The second
   save overwrote the first. The existing guard checks the topic name, or the
   feed name and URL. It catches shifted list entries but misses edits to
   keywords, excludes, and feed intervals. Compare the editable snapshot or
   add a revision check.
   [Server implementation](HoundDog/watcher_server.py)
6. **ThetaDesk's source version check is weaker than its dependency floor.
   Fixed (evening):** `start_project.py` requires 3.12, matching thetadata
   1.0.18's `Requires-Python`. Originally: `start_project.py` accepts Python 3.10. Installed package metadata for
   the pinned SDK requires 3.12. The setup guide now states the effective
   minimum. Align the early check and its message with that minimum.
   [Startup implementation](ThetaDesk/start_project.py)
7. **Simultaneous ThetaDesk fetches can spend provider quota twice.** The
   existing concurrency test forces two provider calls and confirms that
   the store and export still keep one bar. Coalescing requests in one API
   process would save quota. The CLI and API currently have independent
   in-memory rate limits.
   [Store concurrency test](ThetaDesk/tests/test_market_store.py)
8. **The chooser checks launch prerequisites but not server readiness.** A
   successful spawn closes the chooser. If a child exits during startup,
   the visible console or hidden log carries the error.
   [Launcher](launch.py)
9. **ThetaDesk credential updates can partly succeed. Partly fixed
   (evening):** saves now hold one lock and replace `creds.txt` atomically;
   the key and the account are still two files. Originally: the key and password
   files are updated separately without a lock across requests. A failure
   during the second write can leave a new key with old password credentials.
   The SDK's default email/password lookup also follows the caller's working
   directory. Keep credential ownership tied to the active app.
   [Credentials](ThetaDesk/api.py), [SDK setup](ThetaDesk/theta_data.py)

**Fixed (evening):** impossible bars (a price of zero or less, or an open or
close outside the low-to-high range) are refused, and today's bar is stored
only from 18:00 New York time, after the end-of-day report should be final.
Stored bars still never change. Originally: ThetaDesk normalizes types and
dates but accepts inconsistent OHLC values.
A fixture with a high below the low passed normalization. The store keeps
the first value for each bar key, so a bad or provisional value cannot be
replaced with refresh. Historical empty answers also count as completed
lookups. Validate price bounds and establish a correction policy before
depending on refresh for data repair. Provider timing and correction
behavior were outside this review. [Market store](ThetaDesk/market_store.py)

## Follow-up review of failures and retries

1. **HoundDog can reject a backup it exported. Fixed (evening):** import
   has no per-field or per-row limit, and export and import share one 1 GiB
   size limit, so export refuses a backup import could not accept. A test
   round-trips a 21,012-character summary. Originally: a saved feed summary of
   21,012 characters exported normally, then failed History import because
   the importer caps each field at 20,000 characters. Export also has no
   matching 25 MiB or 100,000-row cap. The restore path needs to accept the
   data the app itself can save, or the export must produce restorable parts.
   [Backup and restore](HoundDog/watcher_server.py)
2. **Bridge could replace valid settings with unreadable TOML (fixed).** A configuration
   with a quoted custom table name and key loaded correctly. Adding a ticker
   reported success, then the next load failed because the writer emitted the
   name and key without quotes. The writer now quotes these keys and parses
   the rendered config before replacing the file.
   [Bridge config writer](bridge/config.py)
3. **ThetaDesk can save bars before returning an error.** When a later range
   was rate limited, the first gap stayed committed and a normal retry fetched
   only the remaining gap. A separate test found that a blocked export left
   its committed bar available for local reads but stopped a later fetch for
   another ticker before it reached the provider. Decide whether storing bars
   should depend on export availability and report saved progress explicitly.
   [ThetaDesk fetch and export](ThetaDesk/market_store.py)
4. **Bridge cleared the retry form after a partial watch result (fixed).** In a
   two-ticker fixture, the server reported one success and one failure.
   The dashboard displayed both results and cleared the failed ticker's
   selection, keywords, and group. Failed entries now stay selected for retry.
   [Bridge watch form](bridge/static/app.js)

HoundDog's combined restore also has two commit steps. An injected config
write failure left History merged, and retrying restored the config without
duplicating History. The guides now describe these partial outcomes.

## Verification

- Evening passes: 130 HoundDog, 74 ThetaDesk, and 57 Bridge Python tests,
  plus 69 HoundDog and 10 ThetaDesk dashboard tests, all pass; pyflakes is
  clean. Each fix above has a test that fails without it. Chrome checks:
  ThetaDesk Settings sends no secret and keeps blanks; a stale HoundDog tab's
  save gets 409 and the first tab's change stays.
- The Bridge dashboard update passed all 57 Bridge tests and an isolated
  Edge workflow using ThetaDesk's real API and a fixture provider. It
  covered price updates, rate-limit retry, session evidence, shared pins,
  and layout at 360 px.
- Passed 125 HoundDog, 63 ThetaDesk, and 54 Bridge Python tests, plus 76
  dashboard JavaScript tests during the earlier review. The HTTP tests used
  local loopback access.
- Isolated copies of HoundDog source and the existing executable served
  dashboard endpoints and exited through the shutdown endpoint. ThetaDesk's
  direct API and source wrapper did the same, including a pin round trip
  against a temporary store. The wrapper used the preinstalled environment
  and an alternate port. Bridge likewise served its overview and shut down.
- With fixture feeds and bars, the actual producer save and export paths
  yielded one news session and two quiet sessions in Bridge. The initial
  backfill was excluded.
- The launcher started an isolated Bridge instance with no console, captured
  its output, and refused a second start once the port was occupied.
- The running ThetaDesk executable on 8000 served matching frontend assets
  and exposed the expected stored bars, pins, and shutdown routes. Port 8000
  was occupied, so a separate packaged startup and shutdown was skipped.
- The live exports parsed without skipped or duplicate records in the
  review snapshot. Verification used fixture provider responses and a fake
  Task Scheduler in the automated suite. No real feeds, provider endpoints,
  credential writes, or scheduled-task changes were exercised.
- The source and the binaries already on disk are separate. The review
  updated documentation. The earlier ThetaDesk changes are staged. The
  HoundDog shutdown changes, Bridge detail work, and review documentation
  are unstaged. The staged diff flags a trailing blank line in
  `ThetaDesk/tests/test_api.py`.
- `HoundDog/watch.toml` and `bridge/bridge.toml` are tracked, and dashboard
  edits can change them. Databases, JSON Lines exports, logs, demo output,
  credentials, and build directories are local artifacts.

## Product decisions to carry forward

- Use daily stock bars for the first study. The report describes the sample
  and supports no conclusion about causation or intraday reaction speed.
- Keep each producer independently usable by CLI or localhost dashboard.
  Bridge continues to use the export contracts and does not share producer
  databases. The existing study needs only the standard library and
  timezone data.
- Add ticker topics explicitly through HoundDog. Groups pool their members'
  sessions, and each member's volume is compared with its own median.
- Live coverage is the next source of useful results. Intraday event windows,
  related-company topics, voice tooling, and a research agent remain future
  work.

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
7. **The HoundDog executable's background job opens a console window.** The
   task runs as the signed-in user (`InteractiveToken`), and `HoundDog.exe` is
   a console program. So each scheduled run of the executable opens a window,
   and may steal focus. The source install avoids this with `pythonw.exe`.
   Options:
   - build a second, windowless executable for the job;
   - or keep installing the job from source.

   Not observed yet; the job is the user's choice and stays installed until
   changed. Watch for a console window when the job runs from the executable.
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
