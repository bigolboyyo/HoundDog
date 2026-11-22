# theta_hound

Double-click `start.bat`, select **Start HoundDog**, **Start ThetaDesk**, or
both, and click **Start**. Each app runs in its own console. Press Ctrl+C
in an app's console to stop it.

| App | Dashboard | Run directly |
| --- | --- | --- |
| HoundDog | [localhost:8080](http://127.0.0.1:8080) | `HoundDog\HoundDog.exe` |
| ThetaDesk | [localhost:8000](http://127.0.0.1:8000) | `ThetaDesk\dist\ThetaDesk\ThetaDesk.exe` |

The chooser uses the installed Windows Python with Tk. Both executables
bundle their runtimes. To launch without the chooser, run any of these from
the workspace folder.

```powershell
python launch.py --hounddog
python launch.py --thetadesk
python launch.py --hounddog --thetadesk
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

The apps can still be run from source using their own guides.
[HoundDog](HoundDog/README.md) · [ThetaDesk](ThetaDesk/README.md)
