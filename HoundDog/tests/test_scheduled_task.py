import base64
import json
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import scheduled_task

TASK = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"


class FakePowerShell:
    """Records each PowerShell call and answers with canned output."""

    def __init__(self, stdout="", returncode=0, stderr=""):
        self.calls = []
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr

    def __call__(self, args, env, **kwargs):
        self.calls.append({"args": args, "env": env, **kwargs})
        return subprocess.CompletedProcess(args, self.returncode, self.stdout.encode(), self.stderr.encode())

    @property
    def scripts(self):
        return [base64.b64decode(call["args"][-1]).decode("utf-16-le") for call in self.calls]


def scheduler(runner, root=Path("C:/Users/me/HoundDog & Co"), supported=True):
    return scheduled_task.TaskScheduler(root, run=runner, supported=supported, executable="C:/Python312/python.exe")


class TaskDefinitionTests(unittest.TestCase):
    def test_durations_round_trip(self):
        for minutes, duration in ((5, "PT5M"), (90, "PT90M"), (1440, "P1D")):
            with self.subTest(minutes=minutes):
                self.assertEqual(scheduled_task.task_duration(minutes), duration)
                self.assertEqual(scheduled_task.interval_minutes(duration), minutes)
        self.assertEqual(scheduled_task.interval_minutes("PT1H"), 60)
        self.assertEqual(scheduled_task.interval_minutes("P1DT2H"), 1560)
        for value in ("", "P", "PT", "15 minutes"):
            self.assertIsNone(scheduled_task.interval_minutes(value))

    def test_task_repeats_forever_and_runs_on_battery_without_overlapping(self):
        xml = scheduled_task.task_xml(
            scheduled_task.JobOptions(15), 'C:\\Py <3>\\pythonw.exe', '"C:\\A & B\\watcher.py" --scheduled',
            "C:\\A & B", datetime(2026, 11, 22, 10, 1),
        )
        root = ET.fromstring(xml.split("?>", 1)[1])
        repetition = root.find(f"{TASK}Triggers/{TASK}TimeTrigger/{TASK}Repetition")
        self.assertEqual(repetition.findtext(f"{TASK}Interval"), "PT15M")
        self.assertIsNone(repetition.find(f"{TASK}Duration"), "no Duration means repeat indefinitely")
        self.assertEqual(root.findtext(f"{TASK}Triggers/{TASK}TimeTrigger/{TASK}StartBoundary"), "2026-11-22T10:01:00")
        settings = root.find(f"{TASK}Settings")
        self.assertEqual(
            {name: settings.findtext(f"{TASK}{name}") for name in (
                "MultipleInstancesPolicy", "DisallowStartIfOnBatteries", "StopIfGoingOnBatteries", "StartWhenAvailable",
            )},
            {"MultipleInstancesPolicy": "IgnoreNew", "DisallowStartIfOnBatteries": "false",
             "StopIfGoingOnBatteries": "false", "StartWhenAvailable": "true"},
        )
        exec_ = root.find(f"{TASK}Actions/{TASK}Exec")
        self.assertEqual(exec_.findtext(f"{TASK}Command"), "C:\\Py <3>\\pythonw.exe")
        self.assertEqual(exec_.findtext(f"{TASK}Arguments"), '"C:\\A & B\\watcher.py" --scheduled')
        self.assertEqual(root.findtext(f"{TASK}Principals/{TASK}Principal/{TASK}LogonType"), "InteractiveToken")

    def test_options_become_task_conditions(self):
        options = scheduled_task.JobOptions(60, run_on_battery=False, catch_up=False, require_network=False)
        root = ET.fromstring(scheduled_task.task_xml(options, "p", "a", "d", datetime(2026, 1, 1)).split("?>", 1)[1])
        settings = root.find(f"{TASK}Settings")
        self.assertEqual(
            [settings.findtext(f"{TASK}{name}") for name in
             ("DisallowStartIfOnBatteries", "StartWhenAvailable", "RunOnlyIfNetworkAvailable")],
            ["true", "false", "false"],
        )

    def test_options_from_json_are_validated(self):
        self.assertEqual(scheduled_task.JobOptions.from_json({"interval_minutes": 30}), scheduled_task.JobOptions(30))
        for body in ({}, {"interval_minutes": "30"}, {"interval_minutes": True}, {"interval_minutes": 7},
                     {"interval_minutes": 30, "catch_up": "yes"}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                scheduled_task.JobOptions.from_json(body)

    def test_jobs_prefer_the_windowless_interpreter(self):
        with tempfile.TemporaryDirectory() as directory:
            python = Path(directory) / "python.exe"
            python.touch()
            self.assertEqual(scheduled_task.python_for_jobs(str(python)), str(python))
            (Path(directory) / "pythonw.exe").touch()
            self.assertEqual(scheduled_task.python_for_jobs(str(python)), str(Path(directory) / "pythonw.exe"))


class TaskSchedulerTests(unittest.TestCase):
    def test_executable_task_runs_the_bundled_watcher_in_the_same_folder(self):
        root = Path("C:/Users/me/HoundDog & Co")
        executable = str(root / "HoundDog.exe")
        runner = FakePowerShell(stdout=json.dumps({
            "installed": True, "state": "Ready", "interval": "PT15M",
            "execute": executable, "arguments": "watch --scheduled",
        }))
        bundled = scheduled_task.TaskScheduler(
            root, run=runner, supported=True, executable=executable, frozen=True
        )
        status = bundled.install(scheduled_task.JobOptions(15))
        task_xml = runner.calls[0]["env"]["HOUNDDOG_TASK_XML"]
        action = ET.fromstring(task_xml.split("?>", 1)[1]).find(f"{TASK}Actions/{TASK}Exec")
        self.assertEqual(action.findtext(f"{TASK}Command"), executable)
        self.assertEqual(action.findtext(f"{TASK}Arguments"), "watch --scheduled")
        self.assertEqual(action.findtext(f"{TASK}WorkingDirectory"), str(root))
        self.assertTrue(status.runs_this_folder)
        self.assertTrue(scheduler(runner, root=root).status().runs_this_folder)

        runner.stdout = json.dumps({
            "installed": True, "state": "Ready", "interval": "PT15M",
            "execute": "C:/Python312/pythonw.exe", "arguments": f'"{root / "watcher.py"}" --scheduled',
        })
        self.assertTrue(bundled.status().runs_this_folder)

    def test_every_script_reports_errors_as_one_line(self):
        for script in (scheduled_task.STATUS_SCRIPT, scheduled_task.INSTALL_SCRIPT,
                       scheduled_task.RUN_SCRIPT, scheduled_task.REMOVE_SCRIPT):
            self.assertIn("$ProgressPreference = 'SilentlyContinue'", script)
            self.assertTrue(script.rstrip().endswith(
                "} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }"))
            self.assertNotIn("HoundDog", script, "values come from the environment, not the script")

    def test_scripts_are_fixed_and_values_travel_in_the_environment(self):
        runner = FakePowerShell(stdout='{"installed":false}')
        scheduler(runner).install(scheduled_task.JobOptions(30), now=datetime(2026, 11, 22, 9, 59, 42))
        install = runner.calls[0]
        self.assertEqual(install["args"][:-1], [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand",
        ])
        self.assertEqual(runner.scripts[0], scheduled_task.INSTALL_SCRIPT)
        self.assertEqual((install["env"]["HOUNDDOG_TASK_PATH"], install["env"]["HOUNDDOG_TASK_NAME"]),
                         ("\\HoundDog\\", "Saved check"))
        xml = install["env"]["HOUNDDOG_TASK_XML"]
        self.assertIn("<Interval>PT30M</Interval>", xml)
        self.assertIn("<StartBoundary>2026-11-22T10:00:00</StartBoundary>", xml)
        self.assertIn("HoundDog &amp; Co", xml)
        self.assertEqual(runner.scripts[1], scheduled_task.STATUS_SCRIPT, "install answers with the new status")

    def test_only_listed_intervals_are_accepted(self):
        for interval in (0, 7, 100000):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                scheduled_task.JobOptions(interval)

    def test_status_reports_the_installed_task(self):
        job = scheduler(None)
        runner = FakePowerShell(stdout=json.dumps({
            "installed": True, "state": "Ready", "interval": "PT1H",
            "disallow_on_battery": True, "start_when_available": True, "require_network": False,
            "next_run": "2026-11-22T16:00:00Z", "last_run": "2026-11-22T15:00:00Z",
            "last_result": 0, "execute": job._command, "arguments": job._arguments,
        }))
        status = scheduler(runner).status()
        self.assertEqual(
            (status.installed, status.state, status.last_result, status.runs_this_folder),
            (True, "Ready", 0, True),
        )
        self.assertEqual(status.options, scheduled_task.JobOptions(60, run_on_battery=False, catch_up=True, require_network=False))
        self.assertEqual(status.next_run, "2026-11-22T16:00:00Z")
        self.assertFalse(status.command_found, "C:/Python312/pythonw.exe does not exist here")

    def test_status_flags_a_missing_program_and_unrepresentable_intervals(self):
        with tempfile.TemporaryDirectory() as directory:
            program = Path(directory) / "pythonw.exe"
            program.touch()
            runner = FakePowerShell(stdout=json.dumps({
                "installed": True, "state": "Ready", "interval": "PT7M", "execute": str(program), "arguments": "x",
            }))
            status = scheduler(runner).status()
        self.assertTrue(status.command_found)
        self.assertIsNone(status.options, "7 minutes was set in Task Scheduler, not offered by the dashboard")

    def test_status_notices_a_task_for_another_folder(self):
        runner = FakePowerShell(stdout=json.dumps({
            "installed": True, "state": "Disabled", "interval": "PT15M", "next_run": None, "last_run": None,
            "last_result": 267011, "execute": "C:\\Other\\pythonw.exe", "arguments": '"C:\\Other\\watcher.py" --scheduled',
        }))
        status = scheduler(runner).status()
        self.assertEqual((status.runs_this_folder, status.state), (False, "Disabled"))
        self.assertIn("C:\\Other\\watcher.py", status.command)

    def test_not_installed_and_unsupported(self):
        self.assertFalse(scheduler(FakePowerShell(stdout='{"installed":false}')).status().installed)
        runner = FakePowerShell()
        unsupported = scheduler(runner, supported=False)
        self.assertEqual(unsupported.status(), scheduled_task.JobStatus(supported=False, installed=False))
        for action in (lambda: unsupported.install(scheduled_task.JobOptions(15)), unsupported.run_now, unsupported.remove):
            with self.assertRaises(scheduled_task.ScheduleError):
                action()
        self.assertEqual(runner.calls, [], "PowerShell is never started off Windows")

    def test_powershell_failures_become_schedule_errors(self):
        runner = FakePowerShell(returncode=1, stderr="\nAccess is denied.\r\n")
        with self.assertRaisesRegex(scheduled_task.ScheduleError, "^Access is denied.$"):
            scheduler(runner).install(scheduled_task.JobOptions(15))

        def missing(*args, **kwargs):
            raise FileNotFoundError("powershell.exe")

        with self.assertRaisesRegex(scheduled_task.ScheduleError, "could not run PowerShell"):
            scheduler(missing).status()

    def test_run_now_and_remove_use_their_scripts(self):
        runner = FakePowerShell(stdout='{"installed":false}')
        scheduler(runner).run_now()
        scheduler(runner).remove()
        self.assertEqual(runner.scripts, [
            scheduled_task.RUN_SCRIPT, scheduled_task.STATUS_SCRIPT,
            scheduled_task.REMOVE_SCRIPT, scheduled_task.STATUS_SCRIPT,
        ])


if __name__ == "__main__":
    unittest.main()
