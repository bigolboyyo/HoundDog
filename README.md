# ThetaHound

HoundDog watches news feeds and saves keyword matches. ThetaDesk stores daily
stock prices and pinned ranges. Bridge uses both apps' exports to compare
price and volume on news and quiet trading sessions.

## Start on Windows

Use Python 3.12 or newer on your PATH with Tk installed. From the
repository root, install Bridge's dependencies and build the Windows apps.

```powershell
python -m pip install -r .\bridge\requirements.txt
.\build.bat --no-pause
```

Double-click `start.bat`, then select **Start** in the ThetaHound launcher.
All three apps are selected by default. Each opens its dashboard.

| App | Default dashboard | Guide |
| --- | --- | --- |
| HoundDog | [127.0.0.1:8080](http://127.0.0.1:8080) | [Feeds, checking, and Inbox](HoundDog/README.md) |
| ThetaDesk | [127.0.0.1:8000](http://127.0.0.1:8000) | [Price history, credentials, and pins](ThetaDesk/README.md) |
| Bridge | [127.0.0.1:8090](http://127.0.0.1:8090) | [Watchlist, daily study, and demo](bridge/README.md) |

The **Port** fields apply to one launch. The chooser fills in the defaults
each time it opens. Bridge follows custom HoundDog and ThetaDesk ports
when launched with them. For producers started separately, set their URLs
in [Bridge's settings](bridge/README.md#settings-bridgetoml).

Clear **Show terminal** to send an app's output to `logs\<app>.log`.
The log is overwritten on the app's next hidden start. The chooser checks
for required files, Bridge dependencies, and occupied ports. If a process
exits after launch, check its console or log.

From the repository root, launch selected apps on their default ports
with `launch.py`.

```powershell
python launch.py --hounddog --thetadesk --bridge
python launch.py --bridge --hide-terminals
```

## Shut down and rebuild

Use **Shut down** in HoundDog's left toolbar or in the top bar of ThetaDesk
and Bridge. The servers finish requests in progress before exiting. Ctrl+C
is available in a visible console. HoundDog's scheduled job runs independently
of the dashboard.

Run `build.bat` again after editing packaged HoundDog or ThetaDesk code or
assets. Close both packaged dashboards first. If a scheduled HoundDog check
has its runner open, let it finish and retry. Double-clicking the batch file
leaves its summary visible. Use `--no-pause` to return to the terminal with
a nonzero exit code if either build fails.

The launcher uses `HoundDog\HoundDog.exe` and
`ThetaDesk\dist\ThetaDesk\ThetaDesk.exe`. Bridge runs directly from
`bridge\server.py`. For source runs and single-app builds, use the component
guides above.

## Work with saved data

Bridge's chart, weekly news, and study work from saved JSON Lines exports.
Adding tickers uses HoundDog's local API. Loading prices and sharing pins
use ThetaDesk's local API.

```powershell
python bridge\bridge.py status
python bridge\bridge.py report --json
```

Use the [Bridge demo](bridge/README.md#demo) to explore a populated study.
It uses generated news alongside saved prices. ThetaDesk needs its own
[provider credentials](ThetaDesk/README.md#credentials) to request new prices.

For data locations, transfer instructions, and test commands, see the
[handoff](PLAN.md). The [export contract](HoundDog/INTEGRATION.md) documents
what the two apps publish for Bridge.
