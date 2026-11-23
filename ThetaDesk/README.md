# ThetaDesk

## Setup

Use Python 3.12 or newer for source runs; the pinned ThetaData SDK requires
it, and `start_project.py` refuses older versions. From the `ThetaDesk`
folder:

```text
python start_project.py
```

The launcher creates `.venv` when needed, installs dependencies when
`requirements.txt` changes, then runs the API using the ThetaData Python
client. If the Terminal is already running, its REST fallback is available.
Otherwise, the launcher asks whether to start the bundled Terminal as a
backup. When `creds.txt` is present, it passes that file explicitly to the
Terminal. If declined, the API uses the Python client only for that run. To
stop the API and any Terminal process it started, click **Shut down** at the
top of the dashboard. The API finishes requests in progress. Ctrl+C in the
source wrapper can end the API before those requests finish. A Terminal that
was already running continues on its own. Open the source dashboard at
`http://127.0.0.1:8000` manually. The optional Terminal runs in a separate
window and requires Java.

Use `python start_project.py --no-terminal-prompt` to skip the prompt. With
dependencies installed, you can start only the API on an alternate port:

```powershell
.\.venv\Scripts\python.exe api.py --port 8001
```

The direct API start skips the environment and Terminal startup checks.
Set `THETADATA_REST_FALLBACK_ENABLED=0` in the process environment to disable
fallback for that run.

## Windows executable

Build a portable Windows app folder after running the project at least once:

```powershell
.\build_exe.ps1
```

Run `dist\ThetaDesk\ThetaDesk.exe`. The executable starts the local API and
opens the dashboard in your browser. Keep `.env` or `creds.txt` beside the
executable for authentication; credentials are not bundled, and existing
credential files beside the executable are preserved when rebuilding. The
optional `ThetaTerminal.jar` is copied beside it. Distribute the whole
`dist\ThetaDesk` folder, not only the `.exe`. The packaged app only loads `.env`
from beside the executable; it does not search parent folders.

Set `THETADATA_API_KEY` in `.env` for API-key authentication. The launcher
checks for the key in the environment or `.env`, or for a valid `creds.txt`
when using email/password authentication. `creds.txt` is not needed when an
API key is configured; it is ignored by git.

## Raw provider lookup

```powershell
.\.venv\Scripts\python.exe main.py --symbol AAPL --start-date 2024-01-01 --end-date 2024-01-31
```

The Python SDK is tried first. Stock history and symbol-list requests have
a 30-second deadline on the SDK's data RPCs. If REST fallback is enabled
and the SDK raises an error, the app logs that error and tries the local
ThetaData Terminal REST endpoint at
`http://127.0.0.1:25510/v2`. Set `THETADATA_REST_BASE_URL` in `.env` to
override that base URL. If both providers fail, the command reports both
provider failures. The raw CLI and the raw history endpoint do not store or
export bars.

## Store and export daily bars

Run the CLI from the `ThetaDesk` folder, using its virtual environment. Its
dependencies, including the time-zone database for Windows, are pinned in
`requirements.txt`. The CLI reads the API key from the environment or the
source `.env`. By default the SDK looks for `creds.txt` in the working
directory when using email/password. The packaged dashboard keeps its own
credential settings.

```powershell
.\.venv\Scripts\python.exe fetch.py --symbols AAPL,NVDA,MSFT --from 2024-01-02 --to 2024-01-05
```

Dates are inclusive, with a maximum span of 365 days. The command prints a JSON
summary for each symbol, including the total bars available and the number added.
Bars are saved in `market.db` in `%LOCALAPPDATA%\ThetaDesk`, with its
`exports` folder beside it. The source app and the executable share this one
store, outside the release folder, so rebuilding keeps it and other programs
read one place. Use `--data-dir PATH` to select another folder for both the
database and its exports. Credentials are separate: they stay beside the
running app (`.env` and `creds.txt`).
The raw and stored lookups both use a rate limiter scoped to their process.
Separate CLI and dashboard processes have separate budgets.

Repeat requests fetch only gaps in previously covered ranges. SQLite tracks
successful empty ranges as well, such as weekends. For the current New York
date, an empty response stays eligible for a later fetch while the EOD report
is pending. The CLI reports the last covered date as `covered_through`. A
past empty range is remembered as a completed lookup, including for a ticker
that returned no data. Use `--refresh` to fetch the full range again and fill
bars that arrived late. Existing bars keep their original values.

Each new bar is appended to `exports/theta-bars-YYYY-MM-DD.jsonl`, named for the
UTC date it was stored. These UTF-8 records use `theta.bar/1` and contain the
symbol, interval (`1d`), New York session date, regular session open in UTC
(`start_at`), OHLCV, and provider (`sdk` or `rest`). The prices and volume
come from the provider's EOD report. [ThetaData EOD report documentation](https://http-docs.thetadata.us/operations/get-v2-hist-stock-eod.html)

The bar key is `(symbol, interval, start_at)`. The store keeps the first
successfully recorded bar for each key, so two rules keep bad values out:

- A response with an impossible bar is refused whole: a price of zero or less,
  or an open or close outside the day's low-to-high range.
- Today's bar is stored only from 18:00 New York time
  (`DAILY_BAR_FINAL_AT`), after ThetaData's end-of-day report should be final.
  An earlier fetch skips it, and the next fetch after 18:00 stores it.
  Assumption: the report is published at about 17:15 New York time.

Failed exports remain queued in SQLite and are retried before the next fetch, even for another ticker.
While the export is blocked, stored bars remain available for local reads.
If a later range hits the rate limit, earlier completed ranges remain saved.
An ordinary retry fetches the remaining gaps. Consumers should deduplicate
by the bar key in case a write was interrupted before SQLite could record
delivery.

Completed fetch ranges are exported to
`exports/theta-coverage-YYYY-MM-DD.jsonl` as `theta.coverage/1`. Each record
contains `symbol`, `interval`, and inclusive New York dates `start_date` and
`end_date`. Coverage marks a completed provider lookup, which can return zero
bars. Dates outside those ranges have unknown coverage. The next fetch from an
existing database exports its previously stored ranges without fetching them
again. Consumers can deduplicate coverage by symbol, interval, and both dates.

## HTTP API

The API and dashboard share `http://127.0.0.1:8000`. Interactive API docs
are at [the local API docs](http://127.0.0.1:8000/docs).

| Method and path | Behavior |
| --- | --- |
| `GET /api/v1/stocks/{symbol}/history` | Reads provider history in its original field layout. Pass `start_date` and `end_date` in the query. |
| `GET /api/v1/stocks/symbols` | Reads the provider's symbol list and caches it until restart. |
| `POST /api/v1/stocks/{symbol}/bars/fetch` | JSON `start_date`, `end_date`, optional `refresh`. Fills coverage gaps and returns normalized stored bars plus `added` and `covered_through`. |
| `GET /api/v1/stocks/loaded` | Lists tickers with stored bars and gives their bar counts and date spans. |
| `GET /api/v1/stocks/{symbol}/bars` | Reads normalized stored bars for the query's `start_date` and `end_date` without calling the provider. |
| `GET /api/v1/pins`, `POST /api/v1/pins` | Lists pins or adds a pin by `symbol`, `start_date`, and `end_date`. Adding the same pin again is safe. |
| `DELETE /api/v1/pins/{symbol}/{start_date}/{end_date}`, `DELETE /api/v1/pins` | Removes one pin or clears all pins. Pins live in SQLite and are omitted from exports. |
| `GET /api/v1/settings/credentials`, `PUT /api/v1/settings/credentials` | GET reports what is saved (`api_key_configured`, `credentials_configured`, `email`), never the secrets. PUT changes them: blank fields keep, `clear_api_key` and `clear_credentials` remove. Same-origin and loopback only. |
| `POST /api/v1/shutdown` | Requests shutdown on a server started by ThetaDesk. |

## Frontend

The frontend is a lightweight HTML/CSS/JavaScript app with ticker/date lookup,
a closing-price timeline chart, tabular results, summary metrics, and a sticky
area for pinned timeline summaries. Each pin groups the chart with latest close,
period high, and period low. A pin keeps its ticker and fixed dates in
`market.db`, so it survives reloads, restarts and rebuilds, and is redrawn from
stored bars. **Loaded tickers** lists every ticker with stored bars; opening one
shows its latest year (or all of it, if shorter) without calling ThetaData.
**Load history** uses the same stored bars and
exports as the CLI. Select **Retry missing bars** to recheck the range with
the provider. The raw `GET /api/v1/stocks/{symbol}/history` endpoint remains
available to existing API clients.
Symbols with no history in the requested period return an empty data array.
Use **Browse list** to load ThetaData's stock symbols from
`/api/v1/stocks/symbols`; the backend caches that list until restart, and the
picker lets you search and select a ticker. Loading it uses one API request the
first time. The lookup defaults to the previous 365 days of EOD data. History
requests longer than 365 days are rejected before reaching ThetaData.

Use the settings button in the top bar to update the API key and
email/password credentials. They are saved to `.env` and `creds.txt` beside the
active app (beside the executable when packaged), never in browser storage. The
dialog shows what is saved and the saved email address, but never the key or
password: the server does not send them back. A blank field keeps the saved
value; a new password needs an email (typed or already saved), and a new email
keeps the saved password. **Remove saved API key** and **Remove saved account**
delete them. The SDK tries the API key first. Restart ThetaData Terminal after
changing credentials if you use the REST backup.

The backend enforces a process-wide sliding-window limit of 20 outbound
ThetaData attempts per 60 seconds, including REST fallback attempts. Successful
history, fetch, and symbol-list responses include `X-RateLimit-Limit`,
`X-RateLimit-Remaining`, and
`X-RateLimit-Reset-After` (seconds); rejected calls return HTTP 429 with
`Retry-After`. This in-memory limit resets when the backend restarts, so keep
the API bound to localhost. The dashboard itself has no separate sign-in.

## Tests

Run these from the `ThetaDesk` folder. The tests use fakes for provider calls.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
node --test tests\dashboard.test.js
```
