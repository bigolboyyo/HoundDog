# theta_hound

## Start on Windows

Use Python 3.12 with Tk for the workspace launcher and install Bridge's
dependencies once from the repository root:

```powershell
python -m pip install -r bridge\requirements.txt
```

Build the two executables if this is a fresh checkout. Double-click
`start.bat` and click **Start**. All three apps are selected by default. Each
opens its dashboard in your browser. Clear **Show terminal** to send that
app's output to `logs\<app>.log`, which is overwritten on its next hidden
start. The chooser checks for the required files, Bridge dependencies, and
occupied ports before launching. If an app opens and then exits, check its
console or log for the startup error.

| App | Dashboard | What it does | Direct start |
| --- | --- | --- | --- |
| HoundDog | [127.0.0.1:8080](http://127.0.0.1:8080) | Checks feeds, edits topics, and manages the news inbox | `HoundDog\HoundDog.exe` |
| ThetaDesk | [127.0.0.1:8000](http://127.0.0.1:8000) | Loads and stores daily stock bars and chart pins | `ThetaDesk\dist\ThetaDesk\ThetaDesk.exe` |
| Bridge | [127.0.0.1:8090](http://127.0.0.1:8090) | Compares news and quiet trading sessions and configures tickers for the study | `python bridge\server.py` |

To launch without the chooser, run from the repository root:

```powershell
python launch.py --hounddog --thetadesk --bridge
python launch.py --bridge --hide-terminals
```

Use **Shut down** in HoundDog's left toolbar or in the top bar of ThetaDesk
and Bridge to let requests in progress finish. Ctrl+C is also available in
a visible console. HoundDog's Windows scheduled job, when enabled,
continues on its own.

## Source, builds, and local data

- **HoundDog.** Run `python HoundDog\watcher_server.py` from source and open
  its dashboard manually. To build the executable, run
  `.\HoundDog\build_exe.ps1`. Source and packaged starts use the same
  `watch.toml`, `watcher.db`, and exports when run from this checkout. The
  scheduled job also uses those files when configured for this copy. See the
  [HoundDog guide](HoundDog/README.md).
- **ThetaDesk.** Run `python ThetaDesk\start_project.py` from source and open
  its dashboard manually. This prepares the Python environment used by
  `.\ThetaDesk\build_exe.ps1`. Source and packaged starts share
  `%LOCALAPPDATA%\ThetaDesk\market.db` and its export folder. Credentials
  live beside the active app, so the source and packaged starts use separate
  files. Workspace startup skips the prompt to start ThetaData Terminal and
  can use an existing Terminal as an SDK fallback. See the
  [ThetaDesk guide](ThetaDesk/README.md).

`start.bat` uses the executables already on disk. Rebuild the affected app to
pick up source changes. Bridge runs directly from source. See the
[review and handoff](PLAN.md) for verification and open issues.

## Bridge

`bridge\` reads the two apps' JSON Lines exports without opening either
database. Neither app needs to be running to view the study. Adding a ticker
calls HoundDog's local HTTP API and updates Bridge's configuration. The
watchlist can load prices through a running ThetaDesk, and both dashboards
share ThetaDesk's saved pins.

```powershell
python bridge\server.py           # dashboard at http://127.0.0.1:8090
python bridge\bridge.py report    # the same study on the command line
```

From the dashboard, watch tickers, alone or as a named group: each becomes a
HoundDog topic (HoundDog must be running) and joins the study. Load each
ticker's history in ThetaDesk too. See [the bridge guide](bridge/README.md).

Real results take weeks of HoundDog watching. To see the dashboard filled in
now, with made-up news around your real prices (clearly marked as a demo):

```powershell
python bridge\make_demo.py
python bridge\server.py --config bridge\demo\demo.toml --port 8091
```
