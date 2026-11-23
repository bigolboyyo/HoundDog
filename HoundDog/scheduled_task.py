"""The Windows Task Scheduler job that runs saved checks while the dashboard is closed.

The dashboard manages one task, \\HoundDog\\Saved check, through PowerShell's
built-in ScheduledTasks cmdlets. Every PowerShell script here is a fixed
string; the values it needs (task name, task XML) arrive in environment
variables, so nothing from a request is ever spliced into a command.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

TASK_PATH = "\\HoundDog\\"
TASK_NAME = "Saved check"
WINDOWLESS_RUNNER = "HoundDogScheduled.exe"
LEGACY_ARGUMENTS = "watch --scheduled"
JOB_INTERVALS = (5, 15, 30, 60, 120, 240, 720, 1440)
POWERSHELL_TIMEOUT_SECONDS = 60
# A check is bounded by its fetch deadlines; this only stops a hung process.
EXECUTION_LIMIT = "PT30M"
# Task Scheduler's "has not run yet" result (SCHED_S_TASK_HAS_NOT_RUN).
NEVER_RAN = 0x41303

Runner = Callable[..., subprocess.CompletedProcess]


class ScheduleError(RuntimeError):
    pass


@dataclass(frozen=True)
class JobOptions:
    """How the task runs. The three flags are Task Scheduler conditions:
    run_on_battery (off: skipped on battery), catch_up (run a missed check
    after sleep or shutdown), require_network (skip while offline)."""

    interval_minutes: int
    run_on_battery: bool = True
    catch_up: bool = True
    require_network: bool = True

    def __post_init__(self) -> None:
        if self.interval_minutes not in JOB_INTERVALS:
            raise ValueError(f"interval must be one of {', '.join(map(str, JOB_INTERVALS))} minutes")

    @classmethod
    def from_json(cls, body: Mapping[str, object]) -> JobOptions:
        interval = body.get("interval_minutes")
        if isinstance(interval, bool) or not isinstance(interval, int):
            raise ValueError("interval_minutes must be a whole number")
        flags = {}
        for name in ("run_on_battery", "catch_up", "require_network"):
            value = body.get(name, getattr(cls, name))
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be true or false")
            flags[name] = value
        return cls(interval, **flags)


@dataclass(frozen=True)
class JobStatus:
    """What the dashboard shows about the task. state is Task Scheduler's own
    (Ready, Running, Disabled, ...), or "" when the task is not installed.
    options is read back from the task, so it reflects edits made in Task
    Scheduler too. command_found is false when the task's program is gone
    (Python moved or upgraded); runs_this_folder when it runs another copy."""

    supported: bool
    installed: bool
    state: str = ""
    options: JobOptions | None = None
    next_run: str | None = None
    last_run: str | None = None
    last_result: int | None = None
    runs_this_folder: bool = False
    command_found: bool = False
    command: str = ""
    opens_console: bool = False

    def to_json(self) -> dict:
        return asdict(self)


def interval_minutes(duration: str) -> int | None:
    """Minutes in an ISO 8601 duration as Task Scheduler writes it (PT15M, PT1H, P1D)."""
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", duration or "")
    if not match or not any(match.groups()):
        return None
    days, hours, minutes = (int(part or 0) for part in match.groups())
    return days * 1440 + hours * 60 + minutes


def task_duration(minutes: int) -> str:
    return f"P{minutes // 1440}D" if minutes % 1440 == 0 else f"PT{minutes}M"


def python_for_jobs(executable: str) -> str:
    """pythonw.exe beside the running interpreter, so the job opens no console
    window; python.exe if there is none (a virtual environment without it)."""
    path = Path(executable)
    windowless = path.with_name("pythonw.exe")
    return str(windowless) if windowless.exists() else str(path)


def xml_bool(value: bool) -> str:
    return "true" if value else "false"


def task_xml(options: JobOptions, command: str, arguments: str, working_directory: str, start: datetime) -> str:
    """Task definition: every interval from start, indefinitely (no Duration),
    as the signed-in user, never two runs at once, with options' conditions."""
    values = {
        "interval": task_duration(options.interval_minutes),
        "start": start.strftime("%Y-%m-%dT%H:%M:%S"),
        "limit": EXECUTION_LIMIT,
        "command": escape(command),
        "arguments": f"      <Arguments>{escape(arguments)}</Arguments>\n" if arguments else "",
        "directory": escape(working_directory),
        "minutes": options.interval_minutes,
        "battery": xml_bool(not options.run_on_battery),
        "catch_up": xml_bool(options.catch_up),
        "network": xml_bool(options.require_network),
    }
    return """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>HoundDog: a saved check of your feeds every {minutes} minutes. Managed from the HoundDog dashboard (Settings, Checking).</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition>
        <Interval>{interval}</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>{battery}</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>{catch_up}</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>{network}</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>{limit}</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
{arguments}      <WorkingDirectory>{directory}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
""".format(**values)


# Each script reads its inputs from HOUNDDOG_* environment variables. Progress
# output is silenced, and errors are reduced to their message, so stderr holds
# one readable line instead of progress records or "At line:1 char:1" noise.
def powershell_script(body: str) -> str:
    return (
        "$ErrorActionPreference = 'Stop'\n"
        "$ProgressPreference = 'SilentlyContinue'\n"
        # UTF-8 without a BOM, for paths outside the console code page; a
        # process without a console handle keeps the default rather than fail.
        "try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { }\n"
        f"try {{\n{body.strip()}\n}} catch {{ [Console]::Error.WriteLine($_.Exception.Message); exit 1 }}\n"
    )


STATUS_SCRIPT = powershell_script(r"""
$task = Get-ScheduledTask -TaskPath $env:HOUNDDOG_TASK_PATH -TaskName $env:HOUNDDOG_TASK_NAME -ErrorAction SilentlyContinue
if (-not $task) { '{"installed":false}'; exit 0 }
$info = $task | Get-ScheduledTaskInfo
# Task Scheduler reports "never" as 1999-11-30. 's' is culture-invariant.
function Stamp($moment) { if ($moment -and $moment.Year -gt 2000) { $moment.ToUniversalTime().ToString('s') + 'Z' } else { $null } }
$action = $task.Actions | Select-Object -First 1
$trigger = $task.Triggers | Select-Object -First 1
[ordered]@{
  installed = $true
  state = [string]$task.State
  interval = [string]$trigger.Repetition.Interval
  disallow_on_battery = [bool]$task.Settings.DisallowStartIfOnBatteries
  start_when_available = [bool]$task.Settings.StartWhenAvailable
  require_network = [bool]$task.Settings.RunOnlyIfNetworkAvailable
  next_run = Stamp $info.NextRunTime
  last_run = Stamp $info.LastRunTime
  last_result = [int64]$info.LastTaskResult
  execute = [string]$action.Execute
  arguments = [string]$action.Arguments
} | ConvertTo-Json -Compress
""")
INSTALL_SCRIPT = powershell_script(r"""
Register-ScheduledTask -TaskPath $env:HOUNDDOG_TASK_PATH -TaskName $env:HOUNDDOG_TASK_NAME -Xml $env:HOUNDDOG_TASK_XML -Force | Out-Null
""")
UPGRADE_SCRIPT = powershell_script(r"""
$task = Get-ScheduledTask -TaskPath $env:HOUNDDOG_TASK_PATH -TaskName $env:HOUNDDOG_TASK_NAME -ErrorAction SilentlyContinue
if (-not $task -or @($task.Actions).Count -ne 1) { return }
$old = $task.Actions[0]
if ($old.Execute -ne $env:HOUNDDOG_OLD_COMMAND -or $old.Arguments -ne $env:HOUNDDOG_OLD_ARGUMENTS -or
    $old.WorkingDirectory -ne $env:HOUNDDOG_WORKING_DIRECTORY) { return }
$action = New-ScheduledTaskAction -Execute $env:HOUNDDOG_NEW_COMMAND -WorkingDirectory $old.WorkingDirectory
Set-ScheduledTask -TaskPath $env:HOUNDDOG_TASK_PATH -TaskName $env:HOUNDDOG_TASK_NAME -Action $action | Out-Null
'updated'
""")
RUN_SCRIPT = powershell_script(r"""
Start-ScheduledTask -TaskPath $env:HOUNDDOG_TASK_PATH -TaskName $env:HOUNDDOG_TASK_NAME
""")
REMOVE_SCRIPT = powershell_script(r"""
$task = Get-ScheduledTask -TaskPath $env:HOUNDDOG_TASK_PATH -TaskName $env:HOUNDDOG_TASK_NAME -ErrorAction SilentlyContinue
if ($task) { $task | Unregister-ScheduledTask -Confirm:$false }
""")


class TaskScheduler:
    """Installs, inspects, runs, and removes the job for the HoundDog folder at root."""

    def __init__(
        self,
        root: Path,
        run: Runner = subprocess.run,
        supported: bool = os.name == "nt",
        executable: str = sys.executable,
        frozen: bool = getattr(sys, "frozen", False),
    ) -> None:
        self._root = root
        self._run = run
        self.supported = supported
        self._source_arguments = f'"{root / "watcher.py"}" --scheduled'
        self._windowless = root / WINDOWLESS_RUNNER
        self._frozen = frozen
        self._command = str(self._windowless) if frozen else python_for_jobs(executable)
        self._arguments = "" if frozen else self._source_arguments

    @property
    def command_line(self) -> str:
        return f'"{self._command}" {self._arguments}'.rstrip()

    def status(self) -> JobStatus:
        if not self.supported:
            return JobStatus(supported=False, installed=False)
        try:
            found = json.loads(self._powershell(STATUS_SCRIPT) or "{}")
        except json.JSONDecodeError as error:
            raise ScheduleError(f"unexpected answer from Task Scheduler: {error}") from None
        if not found.get("installed"):
            return JobStatus(supported=True, installed=False, command=self.command_line)
        execute = str(found.get("execute") or "")
        arguments = str(found.get("arguments") or "")
        program = Path(execute)
        legacy = program == self._root / "HoundDog.exe" and arguments == LEGACY_ARGUMENTS
        source = arguments == self._source_arguments and program.name.lower() in {"python.exe", "pythonw.exe"}
        # Either dashboard can manage a job that uses the same watch.toml.
        runs_this_folder = (
            (execute, arguments) == (self._command, self._arguments)
            or source or legacy or (program == self._windowless and not arguments)
        )
        return JobStatus(
            supported=True,
            installed=True,
            state=str(found.get("state") or ""),
            options=self._read_options(found),
            next_run=found.get("next_run"),
            last_run=found.get("last_run"),
            last_result=found.get("last_result"),
            runs_this_folder=runs_this_folder,
            command_found=bool(execute) and Path(execute).is_file(),
            command=f'"{execute}" {arguments}'.rstrip(),
            opens_console=legacy or (source and program.name.lower() == "python.exe"),
        )

    @staticmethod
    def _read_options(found: Mapping[str, object]) -> JobOptions | None:
        """The task's options, or None if it was edited to something the
        dashboard cannot represent (another interval, no repetition)."""
        try:
            return JobOptions(
                interval_minutes(str(found.get("interval") or "")) or 0,
                run_on_battery=not found.get("disallow_on_battery"),
                catch_up=bool(found.get("start_when_available")),
                require_network=bool(found.get("require_network")),
            )
        except ValueError:
            return None

    def install(self, options: JobOptions, now: datetime | None = None) -> JobStatus:
        """Create the task, or replace it: new options, enabled, this folder,
        and the Python running this server."""
        self._require_support()
        if self._frozen:
            self._require_windowless_runner()
        # First run a minute from now, on the minute, so later runs line up.
        start = (now or datetime.now()).replace(second=0, microsecond=0) + timedelta(minutes=1)
        xml = task_xml(options, self._command, self._arguments, str(self._root), start)
        self._powershell(INSTALL_SCRIPT, {"HOUNDDOG_TASK_XML": xml})
        return self.status()

    def upgrade_windowless(self) -> bool:
        """Change only the action of an existing legacy task for this checkout."""
        self._require_support()
        self._require_windowless_runner()
        return self._powershell(UPGRADE_SCRIPT, {
            "HOUNDDOG_OLD_COMMAND": str(self._root / "HoundDog.exe"),
            "HOUNDDOG_OLD_ARGUMENTS": LEGACY_ARGUMENTS,
            "HOUNDDOG_WORKING_DIRECTORY": str(self._root),
            "HOUNDDOG_NEW_COMMAND": str(self._windowless),
        }) == "updated"

    def _require_windowless_runner(self) -> None:
        if not self._windowless.is_file():
            raise ScheduleError(f"Missing {WINDOWLESS_RUNNER} beside HoundDog.exe. Rebuild HoundDog.")

    def run_now(self) -> JobStatus:
        self._require_support()
        self._powershell(RUN_SCRIPT)
        return self.status()

    def remove(self) -> JobStatus:
        self._require_support()
        self._powershell(REMOVE_SCRIPT)
        return self.status()

    def _require_support(self) -> None:
        if not self.supported:
            raise ScheduleError("The background job uses Windows Task Scheduler and is only available on Windows")

    def _powershell(self, script: str, values: Mapping[str, str] | None = None) -> str:
        environment = {
            **os.environ,
            "HOUNDDOG_TASK_PATH": TASK_PATH,
            "HOUNDDOG_TASK_NAME": TASK_NAME,
            **(values or {}),
        }
        try:
            completed = self._run(
                # -EncodedCommand (base64 UTF-16LE) sidesteps powershell.exe's
                # command-line quoting rules for the quotes inside the script.
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-EncodedCommand", base64.b64encode(script.encode("utf-16-le")).decode("ascii")],
                env=environment,
                capture_output=True,
                timeout=POWERSHELL_TIMEOUT_SECONDS,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ScheduleError(f"could not run PowerShell: {error}") from None
        stdout = completed.stdout.decode("utf-8-sig", "replace").strip()
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", "replace").strip()
            first_line = next((line for line in stderr.splitlines() if line.strip()), "")
            raise ScheduleError(first_line or f"PowerShell exited with code {completed.returncode}")
        return stdout


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upgrade the installed background task to HoundDog's windowless runner.")
    parser.add_argument("--upgrade-windowless", action="store_true", required=True)
    parser.parse_args()
    try:
        if TaskScheduler(Path(__file__).resolve().parent).upgrade_windowless():
            print("Updated the installed HoundDog task to run without a console window.")
    except ScheduleError as error:
        raise SystemExit(str(error)) from error
