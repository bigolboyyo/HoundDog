# ThetaHound handoff

Start with the [workspace README](README.md) for setup, launch, rebuilds,
and shutdown. Use this guide to pick up development or transfer a checkout.

## Resume this checkout

1. Open `start.bat` after signing in to Windows. The current HoundDog and
   ThetaDesk executables can be reused. Bridge loads its files from the
   checkout, so reload its browser tab for the current layout.
2. In Bridge, use the ticker strip and **Week**, **1M**, **3M**, **6M**, or
   **1Y**. Use **Dates & pins** for a custom range or a saved pin. **Service**
   opens source diagnostics and the shutdown control.
3. The chart pairs news with completed daily returns. The watchlist's
   **Update** action loads a new close after ThetaDesk can save it at
   6 p.m. ET. A ticker with news can accrue a news session before it has a
   quiet session for comparison.
4. In HoundDog, **Settings → Checking** shows the saved-check task.
   **Settings → Notifications** shows Windows delivery status, **Send test**,
   and the opt-in for automatic summaries.

## Project map

| Component | Entry points | Owns |
| --- | --- | --- |
| Launcher | `start.bat` opens `launch.py`. `build.bat` prepares the build environments and packages both Windows apps. | Default ports, per-launch port overrides, occupied-port checks, confirmed force shutdown, and terminal visibility. Hidden starts write to `logs`. |
| [HoundDog](HoundDog/README.md) | `watcher.py` is the CLI. `watcher_server.py` serves the dashboard on 8080. `HoundDog.exe` packages both. | `watch.toml`, `watcher.db`, and `exports` beside the app. `HoundDogScheduled.exe` runs the Windows saved-check task and shares this checkout's data. |
| [ThetaDesk](ThetaDesk/README.md) | `start_project.py` prepares the venv and starts `api.py` on 8000. The installed executable is `ThetaDesk\dist\ThetaDesk\ThetaDesk.exe`. | `market.db` and `exports` in `%LOCALAPPDATA%\ThetaDesk`, shared by source and packaged starts. Pins live in the database. Credentials live beside the active app. |
| [Bridge](bridge/README.md) | `server.py` serves the dashboard on 8090. `bridge.py status` and `report` read the same exports. | `bridge.toml` stores export paths, local API URLs, ticker-to-topic mappings, and groups. |

HoundDog and ThetaDesk commit data and export queue entries in SQLite before
appending JSON Lines. Bridge reads the exports. Live calls go through
HoundDog's API for topic setup and ThetaDesk's API for price loads and pins.
The [export contract](HoundDog/INTEGRATION.md) defines record IDs, timestamps,
and retry behavior.

Bridge's [research feed](bridge/README.md#research-feed) is the read-only
multi-ticker interface for models and other local apps. It uses news detection,
check completion, revision observation, and market save times. The per-ticker
timeline reads those same observations. New ThetaDesk exports stamp when data
was saved. Legacy bar times remain unknown and those bars can be read as
reference prices by session date. Bridge uses HoundDog's lightweight topic
endpoint for the dashboard connection check.

## Behavior to preserve

- **HoundDog.** Saved checks write History and coverage. Previews log activity
  and can update backoff. The Inbox shows the last recorded check. Reload it
  to pick up background runs. When enabled in Settings, native Windows
  notifications summarize qualifying saved checks from the dashboard or
  background job. The Windows job uses a separate windowless runner.
- **ThetaDesk.** A normal load fills lookup gaps. A retry can fill bars that
  arrived late while preserving the first stored bar. Today's bar can be
  saved from 6 p.m. ET when the provider returns it. Opening loaded tickers
  and pins reads local data.
- **Bridge.** Weekly news uses first detection time in New York. Friday at or
  after the close through Sunday appears under **Full week** in **Weekend
  news**. Monday through Thursday after-close news goes to the next trading
  session. A quiet session needs a return, a qualifying check outside the
  weekend window, and no eligible article. **Study details** shows feed
  success, failure, and skipped counts by calendar day. The compact watchlist
  switches tickers while keeping the selected period. Week navigation moves
  the charts and news together. Longer presets show rolling ranges through
  today in New York alongside current-week news. The full comparison table
  uses the available sample. The first saved close starts each ticker's gap
  checks and supplies the first comparison baseline.
  **Data notes** breaks down saved live detections by ticker,
  showing pending closes, price gaps, included articles, and weekend news.

## Before resetting or moving Windows

A regular restart uses the saved files in place. For **Reset this PC**,
a reinstall, or a move, stop the dashboards and background writers for a
consistent copy, then back up these locations to another drive:

| What to copy | Location |
| --- | --- |
| Project and current edits | The checkout, including new files and both `HoundDog/watch.toml` and `bridge/bridge.toml`. |
| HoundDog History, check log, and research archive | `HoundDog/watcher.db` with any SQLite sidecar files, plus `HoundDog/exports`. Copy `notification-status.json` if you want the most recent delivery result. |
| ThetaDesk bars, pins, and research archive | `%LOCALAPPDATA%\ThetaDesk` including `market.db` and `exports`. Use the actual configured export/store folders if different. |
| ThetaDesk credentials | `.env` and `creds.txt` beside the active executable or source app, if present. Keep this copy private. |

For a full move, restore the data to those locations and rebuild from the
[startup guide](README.md#start-on-windows). Configure credentials and
HoundDog's scheduled job on the destination. For a study-only handoff,
copy both export folders and `bridge/bridge.toml`. Point its `[inputs]`
at the export copies, set both API URLs to an empty string, and start
Bridge with `--config PATH`.

The dashboards can edit both tracked TOML files. Review private feed URLs
and machine-specific paths before sharing a checkout. Databases, exports,
credentials, and local delivery results are kept out of commits.

## Verify the checkout

Run these from the repository root after setup. Use Node.js for the dashboard
tests. The automated tests use feed and provider fixtures.

```powershell
python HoundDog\watcher.py --validate
python bridge\bridge.py status
python bridge\bridge.py report --json

Push-Location HoundDog
python -m unittest discover -s tests
Pop-Location

Push-Location ThetaDesk
.\.venv\Scripts\python.exe -m unittest discover -s tests
Pop-Location

Push-Location bridge
python -m unittest discover -s tests
Pop-Location

node --test HoundDog/tests/dashboard.test.js ThetaDesk/tests/dashboard.test.js
```

The Nov 23, 2026 handoff passed 135 HoundDog, 77 ThetaDesk, and 71 Bridge
Python tests, plus 83 dashboard JavaScript tests. The current packages
were built and launched locally. The notification check verified exactly
one scheduled summary in Windows Notification Center using a test feed.
The launcher check used a disposable listener for forced shutdown.
Bridge's research feed was verified against saved exports, and the weekly
workspace, range buttons, and shared pins were checked in the browser.

## Known limits

| Area | What to expect |
| --- | --- |
| Startup | A successful spawn can still fail before the dashboard is ready. Check the console or hidden-start log. If the scheduled HoundDog runner is locked during a build, retry after the check finishes. |
| Provider quota | CLI and API processes have separate budgets. Simultaneous lookups for the same gap can each call the provider. SQLite deduplicates the resulting bars. |
| Partial fetches | A request can save earlier ranges before a later range fails. A normal retry fetches remaining gaps. A blocked export can delay further fetches while saved bars remain readable. |
| Credentials and restore | ThetaDesk writes each credential file atomically. A save spanning both files can partly succeed. HoundDog's combined restore can merge History before a config write fails. Retrying the restore merges without duplicating History. |
| Coverage | Feed failures and backoff are visible in HoundDog's Health view. Bridge needs both saved prices and overlapping live checks. Use the [demo](bridge/README.md#demo) for a populated example. The daily study describes the sample. |

Earlier implementation notes are available in Git history with
`git show cee1cb3:PLAN.md`.
