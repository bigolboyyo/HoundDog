# ThetaData starter

## Setup

From the project directory, start the local services with one command:

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
top of the dashboard or press Ctrl+C; a price load in progress finishes first.
The Terminal opens in a separate window.

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

## Run

```powershell
python main.py --symbol AAPL --start-date 2024-01-01 --end-date 2024-01-31
```

The Python SDK is tried first. Stock history and symbol-list requests have
a 30-second SDK deadline. If REST fallback was enabled at startup
and the SDK raises an error, the app logs that error and tries the local
ThetaData Terminal REST endpoint at
`http://127.0.0.1:25510/v2`. Set `THETADATA_REST_BASE_URL` in `.env` to
override that base URL. If both providers fail, the command reports both
provider failures.

## Store and export daily bars

Use ThetaData's existing virtual environment. Its dependencies, including the
time-zone database for Windows, are pinned in `requirements.txt`. HoundDog can
run in its own folder with standard Python. The CLI uses credentials configured
for this source folder or the `THETADATA_API_KEY` environment variable. The
packaged dashboard has its own credential settings.

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
It uses the same credentials and per-process rate limit as the history lookup.

Repeat requests fetch only gaps in previously covered ranges. SQLite tracks
successful empty ranges as well, such as weekends. For the current New York
date, an empty response stays eligible for a later fetch while the EOD report
is pending. The CLI reports the last covered date as `covered_through`. Use
`--refresh` to fetch the full range again and fill bars that arrived late.

Each new bar is appended to `exports/theta-bars-YYYY-MM-DD.jsonl`, named for the
UTC date it was stored. These UTF-8 records use `theta.bar/1` and contain the
symbol, interval (`1d`), New York session date, regular session open in UTC
(`start_at`), OHLCV, and provider (`sdk` or `rest`). The prices and volume
come from the provider's EOD report. [ThetaData EOD report documentation](https://http-docs.thetadata.us/operations/get-v2-hist-stock-eod.html)

The bar key is `(symbol, interval, start_at)`. The store keeps the first
successfully recorded bar for each key. Failed exports remain queued in
SQLite and are retried by the next fetch. Consumers should deduplicate by the
bar key in case a write was interrupted before SQLite could record delivery.

Completed fetch ranges are exported to
`exports/theta-coverage-YYYY-MM-DD.jsonl` as `theta.coverage/1`. Each record
contains `symbol`, `interval`, and inclusive New York dates `start_date` and
`end_date`. Coverage marks a completed provider lookup, which can return zero
bars. Dates outside those ranges have unknown coverage. The next fetch from an
existing database exports its previously stored ranges without fetching them
again. Consumers can deduplicate coverage by symbol, interval, and both dates.

For HTTP clients, `POST /api/v1/stocks/{symbol}/bars/fetch` accepts a JSON body
with `start_date`, `end_date`, and an optional `refresh` flag, and returns the stored bars along with
`added` and `covered_through`. It uses the same store as the CLI and the
executable.

## Frontend

The launcher serves the frontend at `http://127.0.0.1:8000` and interactive
API docs at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

The frontend is a lightweight HTML/CSS/JavaScript app with ticker/date lookup,
a closing-price timeline chart, tabular results, summary metrics, and a sticky
area for pinned timeline summaries. Each pin groups the chart with latest close,
period high, and period low. **Load history** uses the same stored bars and
exports as the CLI. Select **Retry missing bars** to recheck the range with
the provider. The raw `GET /api/v1/stocks/{symbol}/history` endpoint remains
available to existing API clients.
Symbols with no history in the requested period return an empty data array.
Use **Browse list** to load ThetaData's overnight-updated stock symbols from
`/api/v1/stocks/symbols`; the backend caches that list until restart, and the
picker lets you search and select a ticker. Loading it uses one API request the
first time. The lookup defaults to the previous 365 days of EOD data. History
requests longer than 365 days are rejected before reaching ThetaData.

Use the settings button in the top bar to view or update the API key and
email/password credentials. The local settings dialog loads existing values
into masked fields and saves them to `.env` and `creds.txt` beside the active
app (beside the executable when packaged). The values are not stored in browser
storage. The API key takes precedence; restart ThetaData Terminal after changing
credentials if you use the REST backup.

The backend enforces a process-wide sliding-window limit of 20 outbound
ThetaData attempts per 60 seconds, including REST fallback attempts. Responses
include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and
`X-RateLimit-Reset-After` (seconds); rejected calls return HTTP 429 with
`Retry-After`. This in-memory limit resets when the backend restarts, so keep
the API bound to localhost until authentication is added before any public
deployment.

## Tests

Run these from the ThetaData folder.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
node --test tests\dashboard.test.js
```
