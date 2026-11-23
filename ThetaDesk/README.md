# ThetaDesk

ThetaDesk loads daily stock prices from ThetaData, saves them in SQLite, and
serves charts and pinned date ranges from the local store.

## Setup

Use Python 3.12 or newer for the pinned SDK. Run this from the `ThetaDesk`
folder.

```powershell
python start_project.py
```

The wrapper creates `.venv` when needed, installs dependencies when
`requirements.txt` changes, and starts the API. Open the dashboard at
[127.0.0.1:8000](http://127.0.0.1:8000). Use `--port` to choose another port.
Use `--setup-only` to prepare the environment for tests or a build.

The API tries the Python SDK first. The wrapper can use a running ThetaData
Terminal as a REST fallback. When credentials are available, it offers to
start the bundled Terminal if needed. Java is required for that option.
Use `--no-terminal-prompt` to skip the offer and use the SDK with any
Terminal already running.

Use **Shut down** to finish active API requests and stop a Terminal that
ThetaDesk started. Ctrl+C in the source wrapper gives the API up to 60
seconds to exit. A second Ctrl+C ends the wait. A separately started
Terminal keeps running.

With the venv prepared, run the API directly to skip the environment and
Terminal startup checks.

```powershell
.\.venv\Scripts\python.exe api.py --port 8001
```

Set `THETADATA_REST_FALLBACK_ENABLED=0` in the process environment to disable
fallback for that run.

## Windows executable

Use `build.bat` from the repository root to build both apps. To build only
ThetaDesk from this folder, close the packaged app and run the build script.

```powershell
python start_project.py --setup-only
.\build_exe.ps1
```

Run `dist\ThetaDesk\ThetaDesk.exe` to start the API and open the dashboard.
The executable accepts `--port`, `--no-browser`, and `--no-terminal-prompt`.
Distribute the whole `dist\ThetaDesk` folder, including its runtime files.
The build copies the optional `ThetaTerminal.jar` and carries forward
the installed copy's `.env` and `creds.txt`.

## Credentials

Use the dashboard's **Settings** to save credentials beside the active app.
For source runs, this directory is `ThetaDesk`. For the executable, it is
`dist\ThetaDesk` inside that project. The source and packaged runs share
market data and have separate credential files.

- API key goes in `.env` as `THETADATA_API_KEY`, or in the process environment.
- Email and password go on the first two lines of `creds.txt`. Run the raw
  source commands from the `ThetaDesk` directory so the SDK finds that file.
  The packaged wrapper runs from the executable's directory.

The SDK tries the API key first. The settings dialog shows credential
status and the saved email. Blank fields keep saved values. A new password
requires an email, and changing the email alone keeps the password. Use
**Remove saved API key** or **Remove saved account** to clear them.
Restart ThetaData Terminal after changing credentials if you use the REST
fallback. Keep credential files local.

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
provider failures. The raw CLI prints results and uses warning-level
logging. Use `fetch.py` to store and export the bars.

## Store and export daily bars

Run the CLI from the `ThetaDesk` folder with its virtual environment.

```powershell
.\.venv\Scripts\python.exe fetch.py --symbols AAPL,NVDA,MSFT --from 2024-01-02 --to 2024-01-05
```

Dates are inclusive, with a maximum span of 365 days. The end date can be
up to today in New York. The command prints a JSON summary for each
successful ticker and continues through failures. Exit status 1 means
at least one ticker failed.
Bars are saved in `market.db` in `%LOCALAPPDATA%\ThetaDesk`, with its
`exports` folder beside it. The source app and the executable share this one
store, outside the release folder, so rebuilding keeps it and other programs
read one place. Use `--data-dir PATH` to select another folder for both the
database and its exports. When `LOCALAPPDATA` is absent, the default
store is `~/.thetadesk`.

For a Windows reset or a move, copy the market store folder to another
drive. `market.db` holds bars and pins. The `exports` folder holds the
research archive that Bridge reads, and credentials live beside the active
app. See the [handoff data locations](../PLAN.md#before-resetting-or-moving-windows).

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

New exports also include `recorded_at`, the actual UTC time assigned when
ThetaDesk saves the bar. The session's open can be days or months earlier
when loading history. The queued export keeps its original timestamp if
delivery is retried. Older exports without this field have unknown save times.

The bar key is `(symbol, interval, start_at)`. The store keeps the first
successfully recorded bar for each key, so two rules keep bad values out:

- A response must contain finite positive prices, a consistent low-to-high
  range, and nonnegative integer volumes.
- Today's bar is eligible to be stored from 18:00 New York time
  (`DAILY_BAR_FINAL_AT`). The date stays eligible for later fetches until
  the provider supplies a bar.

Failed exports remain queued in SQLite and are retried before the next fetch, even for another ticker.
While the export is blocked, stored bars remain available for local reads.
If a later range hits the rate limit, earlier completed ranges remain saved.
An ordinary retry fetches the remaining gaps. Consumers should deduplicate
by the bar key in case a write was interrupted before SQLite could record
delivery.

Completed fetch ranges are exported to
`exports/theta-coverage-YYYY-MM-DD.jsonl` as `theta.coverage/1`. Each record
contains `symbol`, `interval`, and inclusive New York dates `start_date` and
`end_date`. Newly saved ranges also carry `recorded_at`. Coverage marks a
completed provider lookup, which can return zero bars. Dates outside those ranges
have unknown coverage. The next fetch from an existing database exports its
previously stored ranges without fetching them again. These older ranges have
unknown original save times. Consumers can deduplicate coverage by symbol,
interval, and both dates.

## HTTP API

The API and dashboard share localhost port 8000 by default. Interactive
API docs are at [/docs](http://127.0.0.1:8000/docs) on the selected port.

| Method and path | Behavior |
| --- | --- |
| `GET /api/v1/stocks/{symbol}/history` | Reads provider history in its original field layout with an uppercase ticker. Missing numeric values are JSON `null`. Pass `start_date` and `end_date` in the query. |
| `GET /api/v1/stocks/symbols` | Reads the provider's symbol list and caches it until restart. |
| `POST /api/v1/stocks/{symbol}/bars/fetch` | JSON `start_date`, `end_date`, optional `refresh`. Fills coverage gaps and returns normalized stored bars plus `added` and `covered_through`. |
| `GET /api/v1/stocks/loaded` | Lists tickers with stored bars and gives their bar counts and date spans. |
| `GET /api/v1/stocks/{symbol}/bars` | Reads normalized stored bars for the query's `start_date` and `end_date` without calling the provider. |
| `GET /api/v1/pins`, `POST /api/v1/pins` | Lists pins or adds a pin by `symbol`, `start_date`, and `end_date`. Adding the same pin again is safe. |
| `DELETE /api/v1/pins/{symbol}/{start_date}/{end_date}`, `DELETE /api/v1/pins` | Removes one pin or clears all pins. Pins live in SQLite and are omitted from exports. |
| `GET /api/v1/settings/credentials`, `PUT /api/v1/settings/credentials` | Read credential status (`api_key_configured`, `credentials_configured`, and `email`) or update credentials. `clear_api_key` and `clear_credentials` remove saved values. These routes require a same-origin loopback request. |
| `POST /api/v1/shutdown` | Requests shutdown on a server started by ThetaDesk. |

## Frontend

**Find a ticker** opens the daily history lookup. Use **Browse symbols** to
search the provider's stock directory, which the API caches until restart.
**Load history** uses the same store and export path as the CLI.
**Retry missing bars** rechecks the selected dates with the provider.

**Loaded tickers** and **Pinned summaries** sit beside the lookup on wide
screens and above **History** on narrow screens. A loaded ticker opens the
latest year available in the local store. A pin keeps its ticker and fixed
dates in `market.db` and redraws the chart, latest close, period high, and
period low from the stored bars.

The backend enforces a process-wide sliding-window limit of 20 outbound
ThetaData attempts per 60 seconds, including REST fallback attempts. Successful
history, fetch, and symbol-list responses include `X-RateLimit-Limit`,
`X-RateLimit-Remaining`, and
`X-RateLimit-Reset-After` (seconds); rejected calls return HTTP 429 with
`Retry-After`. Each CLI or API process has its own budget, which resets
when that process restarts. Keep the dashboard bound to localhost.

## Tests

Run these from the `ThetaDesk` folder after preparing its environment.
The tests use fake provider responses.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
node --test tests\dashboard.test.js
```
