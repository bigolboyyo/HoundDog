# theta_hound

Double-click `start.bat` and click **Start**. All three apps are ticked; untick
any you don't need. Each app opens its page in your browser.

Each app also has a **Show terminal** box, ticked by default. Untick it to run
the app with no window; its output then goes to `logs\<app>.log` (rewritten at
each start).

To stop an app, click **Shut down** at the top of its page, or press Ctrl+C in
its console. Either way it finishes any request in progress first, such as a
news check or a price load, then exits. HoundDog's background job, if on, keeps
running.

| App | Page | What it is for | Run directly |
| --- | --- | --- | --- |
| HoundDog | [localhost:8080](http://127.0.0.1:8080) | Reading news, editing topics | `HoundDog\HoundDog.exe` |
| ThetaDesk | [localhost:8000](http://127.0.0.1:8000) | Loading and updating prices | `ThetaDesk\dist\ThetaDesk\ThetaDesk.exe` |
| Bridge | [localhost:8090](http://127.0.0.1:8090) | The study; watching tickers | `python bridge\server.py` |

What keeps running without them:

- **News** comes in through HoundDog's background job (Task Scheduler), once
  it is turned on, whether or not any app is open.
- **Prices** only update when you load them in ThetaDesk; it fetches just the
  missing days.
- The bridge only reads the other two apps' exports. To view results, only the
  bridge needs to run; HoundDog must also run to add tickers.

The chooser uses the installed Windows Python with Tk. Both executables bundle
their runtimes; the bridge runs on that same Python and needs its packages once
(`python -m pip install -r bridge\requirements.txt`). The chooser says so if
they are missing. To launch without the chooser, run any of these from the
workspace folder:

```powershell
python launch.py --hounddog --thetadesk --bridge
python launch.py --bridge --hide-terminals
```

## Build the executables

- **HoundDog**. Run `.\HoundDog\build_exe.ps1`. The build uses a separate
  `.venv-build`. The executable sits beside the existing `watch.toml`,
  `watcher.db`, and exports so the source and Windows app use the same data.
- **ThetaDesk**. Run `.\ThetaDesk\build_exe.ps1` from the workspace root.
  Follow the [ThetaDesk setup guide](ThetaDesk/README.md) to prepare its `.venv`
  before rebuilding. The launcher uses the executable currently in `dist`
  with its existing configuration. Workspace startup uses a running ThetaData
  Terminal when available and otherwise uses the SDK. Start ThetaDesk directly
  to get the optional Terminal startup prompt.

## Bridge

`bridge\` joins the two apps' exports and runs the daily news-versus-market
study. It reads their export folders only; neither app needs to be running to
view results.

```powershell
python -m pip install -r bridge\requirements.txt
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
python bridge\server.py --config bridge\demo\demo.toml
```

The apps can still be run from source using their own guides.
[HoundDog](HoundDog/README.md) · [ThetaDesk](ThetaDesk/README.md)
