# theta_hound: plan

Written 2026-11-22 after a first review of `ThetaData/`. `HoundDog/` is covered
by `HoundDog/INTEGRATION.md`, which this plan builds on.

Status (2026-11-22, evening): steps 1 to 5 are done.
- The ThetaData app was renamed `ThetaDesk/`. It has a daily bar store, a fetch
  CLI, an HTTP fetch endpoint, and a JSON Lines export.
- A workspace launcher and Windows executables for both apps were added.
- `bridge/` reads both exports, maps news to NYSE sessions, and runs the daily
  study, from the command line or its dashboard (`server.py`, port 8090),
  which also adds tickers and groups (see its README).

- `start.bat` starts all three apps by default.
- A demo (`bridge/make_demo.py`) shows the dashboard working with made-up news
  around real prices, while real HoundDog data builds up.

Next: let real data accumulate (the AAPL, MSFT, and TSLA topics exist since
2026-11-22), and make the study's working visible on the dashboard (see
"Making the study obvious" below). Older sections below say `ThetaData/`; read it as
`ThetaDesk/`.

## Layout

```text
theta_hound/
  HoundDog/     news producer (exports/hounddog-*.jsonl)
  ThetaDesk/    market data producer (exports/theta-bars-*.jsonl and theta-coverage-*.jsonl)
  launch.py     start.bat's chooser: starts either app's executable
  bridge/       reads both exports, maps news to NYSE sessions, daily study; CLI and dashboard (port 8090)
```

Each producer can run on its own. The bridge joins their exports.

## Product direction

- ThetaDesk is where users choose their watchlist, load a year of daily history,
  and have the saved prices updated daily.
- After looking up a ticker in ThetaDesk, users should be able to explicitly
  add it as a HoundDog topic. HoundDog owns its topic configuration and is
  where users spend their time reading and researching articles.
- Voice reading and voice search are later HoundDog work. This phase keeps the
  existing apps and their export contracts stable.

## ThetaData app at the initial review

Facts, from the code:

- Stack: Python, FastAPI and uvicorn on `127.0.0.1:8000`, the `thetadata`
  Python SDK (`ThetaClient.stock_history_eod`, `stock_list_symbols`), with the
  Terminal's v2 REST API (`127.0.0.1:25510/v2/hist/stock/eod`) as a fallback.
  `start_project.py` manages the venv and the Terminal; `build_exe.ps1` makes a
  PyInstaller app.
- Data: end-of-day stock history only, at most 365 days per request. No
  intraday bars, options, or indices.
- Storage: none. Every lookup goes live to ThetaData, limited to 20 calls per
  60 seconds in memory. The symbol list is cached until restart.
- Output: `GET /api/v1/stocks/{symbol}/history` returns whatever the provider
  returned, as JSON records. The SDK path (a pandas or Polars dataframe) and the
  REST path (`header` and `response`) give different column names. The
  frontend copes by guessing field names (`findField`).
- Ports: 8000 here, 8080 for HoundDog, 25510 for the Terminal. No conflict.

## Decisions (2026-11-22)

- **Free tier only, for the MVP.** Build on the endpoints ThetaData's free tier
  gives (end-of-day stock history and the symbol list), so the first study is
  daily. Keep the bar schema and store ready for intraday later
  (`interval`, `start_at`), but build nothing for it now.
- **ThetaDesk will own the market watchlist.** Adding a ticker as a news
  topic is an explicit action. HoundDog owns and edits the resulting topic.
- **Analysis uses pandas or Polars**, which the ThetaData app already
  installs.
- **The bridge server is FastAPI**, like the ThetaData app.
- **Later, not now:** a local AI that researches on its own and uses this
  tooling. Design consequence today: every action is available as a CLI
  command or an HTTP endpoint with JSON in and out, never only as a dashboard
  button, so a program can do what the user does.

## Issues found

In order of importance:

1. **Credentials could leak to any website (security). Fixed on
   2026-11-22.**
   - The problem: the credential endpoints only checked that the caller's
     address was loopback. With DNS rebinding, a page on another site could
     make the browser call `127.0.0.1:8000` under the attacker's host name,
     and `GET /api/v1/settings/credentials` would return the API key and the
     password.
   - The fix: `TrustedHostMiddleware` in `api.py` now serves only requests
     addressed to `127.0.0.1` or `localhost`, as HoundDog does. The tests use
     that host and cover a rebound request.
   - Still worth doing later: stop sending stored secrets back to the browser
     at all. That needs a "blank means keep" rule in the settings form, so it
     is a design change rather than a quick fix.
2. **No stable output shape. Fixed:** `market_store.normalize_daily_bars`
   maps both providers to `theta.bar/1`, and the frontend charts those rows.
   Originally: SDK and REST records differ, so nothing
   downstream can rely on field names. A bridge needs one schema (below).
3. **REST dates broke the chart. Fixed, then superseded.** `Date.parse("20240102")`
   is `NaN`. The chart now uses the normalized `session_date` (ISO), and the
   normalizer parses `YYYYMMDD` with `date.fromisoformat`. See the review below
   for that function's Python version requirement.
4. **Unpinned `thetadata`. Fixed:** exact pins, plus `tzdata`.
   Originally: `requirements.txt` had no versions. An SDK release
   can change method names or the dataframe columns under you. Pin it (and
   FastAPI) once the working versions are known (`pip freeze` in `.venv`).
5. **Smaller issues:**
   - `CORSMiddleware` allows `http://localhost:3000`, which looks like a
     leftover; the frontend is same-origin.
   - The 365-day check exists in both `api.py` and `theta_data.py`.
   - A new `ThetaClient` is created per request. Assumption: this costs a
     login or connection each time; worth checking.

## What the correlation needs from market data

- **Resolution decides the study.** With daily bars, the question can only be
  "did the stock move more on news days than on other days?" (close-to-close
  or open-to-close). Effects within minutes or hours of a headline need
  intraday bars (1 to 5 minutes) and a ThetaData plan that includes them.
- **Reproducibility.** Analyses must rerun on the same data without new API
  calls, so bars are stored locally once fetched.
- **Coverage.** As with HoundDog, "no bar" must be distinguishable from "not
  fetched".

## Proposed design

### ThetaData app: a bar store and an export

- **Store.** SQLite `market.db`, keyed by (symbol, interval, start time). A
  fetch writes bars there, and a repeat request for stored data makes no API
  call.
- **One record shape for both providers.** A normalizer maps SDK and REST rows
  into the same fields. This also fixes issue 2 for the existing frontend.
- **Export.** It follows the shared conventions in `HoundDog/INTEGRATION.md`:
  JSON Lines, a `schema` field, UTC times, append-only daily files. It is
  written to `ThetaData/exports/theta-bars-YYYY-MM-DD.jsonl`:

  ```json
  {"schema": "theta.bar/1", "symbol": "AMZN", "interval": "1d",
   "session_date": "2026-11-20", "start_at": "2026-11-20T14:30:00+00:00",
   "open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0, "volume": 0,
   "provider": "sdk"}
  ```

  Conversion from Eastern time to UTC happens here, in the app that knows its
  data's time zone, so the bridge only joins.
- **A fetch command.** For example `python fetch.py --symbols AMZN,NVDA --from
  2026-10-01 --to 2026-11-21 --interval 1d`, which fetches what is missing,
  respects the rate limit, and exports. The bridge can call it, and the
  dashboard can trigger it through a new API endpoint.

### bridge/

- **Inputs.** `HoundDog/exports/*.jsonl` and `ThetaData/exports/*.jsonl`, by
  path from its config. It never opens either app's database.
- **Topic-to-symbol mapping.** The first study can join ticker-named HoundDog
  topics with matching market symbols. For example, the `NVDA` topic can use
  `Nvidia` as a keyword. Topic creation stays a user action.
- **Config, also in `bridge.toml`.** The two export folders, the study windows,
  and the symbols included in the study.
- **Store.** Its own SQLite file: deduplicated events and bars, read progress,
  and results.
- **Market calendar.** Use exchange session dates and trading hours in
  America/New_York, including holidays and early closes. A scheduled trading
  day with a missing bar stays a data gap. Keep the original detection time
  and the assigned session.
- **First study (daily).**
  - For each non-backfill event and mapped symbol, take the event's session
    return.
  - Compare it with the symbol's returns on covered days without events,
    keeping only days when HoundDog's coverage shows it was watching.
  - Report a count, the mean absolute move, and the difference against the
    baseline per topic and keyword.
  - The sample will be small for weeks; the report must say so rather than
    hide it.
- **Combined dashboard.** A local page with:
  - a price chart per symbol, with event markers;
  - the study table;
  - a coverage strip;
  - topic and source filters.

  Same approach as both apps: one local server, no build step.

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
9. **CORS default.** CORS still allows `localhost:3000` by default
   (`FRONTEND_ORIGIN`). It is harmless after the host check, but remove it if
   no separate dev frontend is used.

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
8. **Next.** Making the study obvious on the dashboard:
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

## Daily study on free-tier data: what it can and cannot show

- **It can show** whether a ticker's session return, or its absolute move, is
  larger on days with news about it than on covered days without.
- **It cannot show** reaction speed or direction within a day. With daily bars,
  a 09:31 headline and a 15:59 headline land in the same bar.
- **Session assignment.** An event detected before that day's scheduled close
  belongs to that session. Events at or after the close, or on a weekend or
  holiday, belong to the next trading session. Compare prior close to close.
- **Volume.** End-of-day volume is a second signal at no extra cost: is volume
  unusual on news days?
- **Assumption to verify early.** That the free tier returns end-of-day history
  for the tickers you pick, with no delay that matters at daily resolution.
  Step 2's tests should record a real response.

## Open questions

1. Polars or pandas in the bridge? The SDK can return either, so the ThetaData
   normalizer handles both regardless. My preference is Polars: explicit
   schemas and stricter types fit how you like code. pandas has more examples
   to lean on. Your call.
2. The first tickers to watch. The live run used AAPL, NVDA, and MSFT, and
   HoundDog has no ticker topics yet (only `AI tooling` and `Breaking`), so the
   study has nothing to join until some exist.
3. Version control. HoundDog is a git repo; `ThetaDesk/` and `theta_hound/`
   are not. The offline work regressing three fixes is the kind of thing a
   shared repo with commits would have caught. One repo for the workspace
   would let one change span apps.
