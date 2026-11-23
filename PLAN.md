# ThetaHound handoff

Start with the [workspace README](README.md) for setup, launch, rebuilds,
and shutdown. Use this guide to pick up development or transfer a checkout.

## Project map

| Component | Entry points | Owns |
| --- | --- | --- |
| Launcher | `start.bat` opens `launch.py`. `build.bat` prepares the build environments and packages both Windows apps. | Default ports, per-launch port overrides, and terminal visibility. Hidden starts write to `logs`. |
| [HoundDog](HoundDog/README.md) | `watcher.py` is the CLI. `watcher_server.py` serves the dashboard on 8080. `HoundDog.exe` packages both. | `watch.toml`, `watcher.db`, and `exports` beside the app. `HoundDogScheduled.exe` runs the Windows saved-check task and shares this checkout's data. |
| [ThetaDesk](ThetaDesk/README.md) | `start_project.py` prepares the venv and starts `api.py` on 8000. The installed executable is `ThetaDesk\dist\ThetaDesk\ThetaDesk.exe`. | `market.db` and `exports` in `%LOCALAPPDATA%\ThetaDesk`, shared by source and packaged starts. Pins live in the database. Credentials live beside the active app. |
| [Bridge](bridge/README.md) | `server.py` serves the dashboard on 8090. `bridge.py status` and `report` read the same exports. | `bridge.toml` stores export paths, local API URLs, ticker-to-topic mappings, and groups. |

HoundDog and ThetaDesk commit data and export queue entries in SQLite before
appending JSON Lines. Bridge reads the exports. Live calls go through
HoundDog's API for topic setup and ThetaDesk's API for price loads and pins.
The [export contract](HoundDog/INTEGRATION.md) defines record IDs, timestamps,
and retry behavior.

## Behavior to preserve

- **HoundDog.** Saved checks write History and coverage. Previews log activity
  and can update backoff. The Inbox shows the last recorded check. Reload it
  to pick up background runs. Dashboard auto-check can show one desktop
  notification per run, with article and match counts. The Windows background
  job uses a separate windowless runner.
- **ThetaDesk.** A normal load fills lookup gaps. A retry can fill bars that
  arrived late while preserving the first stored bar. Today's bar can be
  saved from 6 p.m. ET when the provider returns it. Opening loaded tickers
  and pins reads local data.
- **Bridge.** Weekly news uses first detection time in New York. Friday at or
  after the close through Sunday appears under **Full week** in **Weekend
  news**. Monday through Thursday after-close news goes to the next trading
  session. A quiet session needs a return, a qualifying check outside the
  weekend window, and no eligible article. **Study details** shows feed
  success, failure, and skipped counts by calendar day. Date controls apply
  to the chart and ticker detail. Weekly news and the full comparison table
  have their own scope.

## Transfer a checkout

1. Share the source and the intended `HoundDog/watch.toml` and
   `bridge/bridge.toml` changes. Both TOML files are tracked and can be
   edited by their dashboards. Review them for machine-specific paths and
   private feed URLs before sharing.
2. Rebuild on the destination from the [startup guide](README.md#start-on-windows).
   Configure ThetaDesk credentials locally. Keep `.env`, `creds.txt`,
   databases, exports, backups, and logs out of commits. Set up HoundDog's
   background job on the destination if needed.
3. For a study-only handoff, provide both export folders through the
   appropriate private channel. Copy `bridge/bridge.toml` so the ticker
   mappings travel with the data. Point its `[inputs]` at the export copies,
   set both API URLs to an empty string, and start Bridge with `--config PATH`.
4. For a full state move, stop the dashboards and background writers
   before copying HoundDog's `watch.toml`, `watcher.db`, and `exports`, and
   ThetaDesk's market store. Keep any SQLite journal files with the database
   they belong to. HoundDog's JSON backup can transfer config and History
   by itself. Copy its exports too when transferring research history.

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

The latest pass covered 131 HoundDog, 76 ThetaDesk, and 63 Bridge Python
tests and 81 dashboard JavaScript tests. It also built both Windows
packages, started all three apps on alternate ports, verified Bridge could
read HoundDog topics and a ThetaDesk pin, and checked desktop and phone
layouts in Edge.

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
