import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import start_project


class StartProjectTests(unittest.TestCase):
    def test_terminal_command_uses_credentials_file_from_app_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            terminal_jar = project_root / "ThetaTerminal.jar"
            credentials_file = project_root / "creds.txt"
            terminal_jar.touch()
            credentials_file.write_text(
                "person@example.test\nexample-password\n",
                encoding="utf-8",
            )
            terminal_process = Mock()
            with (
                patch("start_project.PROJECT_ROOT", project_root),
                patch("start_project.TERMINAL_JAR", terminal_jar),
                patch("start_project.shutil.which", return_value="java.exe"),
                patch("start_project._is_port_open", side_effect=[False, True]),
                patch(
                    "start_project.subprocess.Popen",
                    return_value=terminal_process,
                ) as popen,
            ):
                result = start_project._start_terminal_if_needed()

        self.assertIs(result, terminal_process)
        self.assertEqual(
            popen.call_args.args[0],
            [
                "java.exe",
                "-jar",
                str(terminal_jar),
                "--creds-file",
                str(credentials_file),
            ],
        )
        self.assertEqual(popen.call_args.kwargs["cwd"], project_root)

    @patch("start_project.subprocess.Popen")
    @patch("start_project._ensure_environment")
    @patch("start_project._is_port_open", side_effect=[False, False])
    @patch("start_project._terminal_credentials_available", return_value=True)
    @patch("start_project._ask_to_start_terminal", return_value=True)
    @patch("start_project._start_terminal_if_needed")
    def test_starts_api_after_environment_and_terminal(
        self,
        start_terminal: Mock,
        ask_to_start_terminal: Mock,
        credentials_available: Mock,
        is_port_open: Mock,
        ensure_environment: Mock,
        popen: Mock,
    ) -> None:
        api_process = Mock()
        api_process.wait.return_value = 0
        api_process.poll.return_value = 0
        terminal_process = Mock()
        terminal_process.poll.return_value = 0
        popen.return_value = api_process
        start_terminal.return_value = terminal_process

        result = start_project.main()

        self.assertEqual(result, 0)
        ensure_environment.assert_called_once_with()
        credentials_available.assert_called_once_with()
        ask_to_start_terminal.assert_called_once_with()
        start_terminal.assert_called_once_with()
        self.assertEqual(is_port_open.call_count, 2)
        self.assertEqual(
            popen.call_args.kwargs["env"]["THETADATA_REST_FALLBACK_ENABLED"],
            "1",
        )
        command = popen.call_args.args[0]
        self.assertEqual(command[1:], ["api.py", "--host", "127.0.0.1", "--port", "8000"])

    @patch.dict("os.environ", {"THETADATA_API_KEY": "test-key"})
    def test_api_key_does_not_require_creds_file(self) -> None:
        self.assertTrue(start_project._terminal_credentials_available())

    @patch.dict("os.environ", {"THETADATA_API_KEY": ""})
    def test_accepts_creds_file_without_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            (project_root / "creds.txt").write_text(
                "person@example.test\nexample-password\n",
                encoding="utf-8",
            )
            with patch("start_project.PROJECT_ROOT", project_root):
                self.assertTrue(start_project._terminal_credentials_available())

    @patch.dict("os.environ", {"THETADATA_API_KEY": ""})
    def test_accepts_api_key_from_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            (project_root / ".env").write_text(
                "THETADATA_API_KEY=test-key\n",
                encoding="utf-8",
            )
            with patch("start_project.PROJECT_ROOT", project_root):
                self.assertTrue(start_project._terminal_credentials_available())

    @patch("start_project.subprocess.Popen")
    @patch("start_project._ensure_environment")
    @patch("start_project._is_port_open", side_effect=[False, False])
    @patch("start_project._terminal_credentials_available", return_value=True)
    @patch("start_project._ask_to_start_terminal", return_value=False)
    @patch("start_project._start_terminal_if_needed")
    def test_declining_terminal_disables_rest_fallback(
        self,
        start_terminal: Mock,
        ask_to_start_terminal: Mock,
        credentials_available: Mock,
        is_port_open: Mock,
        ensure_environment: Mock,
        popen: Mock,
    ) -> None:
        api_process = Mock()
        api_process.wait.return_value = 0
        api_process.poll.return_value = 0
        popen.return_value = api_process

        result = start_project.main()

        self.assertEqual(result, 0)
        credentials_available.assert_called_once_with()
        is_port_open.assert_called()
        ensure_environment.assert_called_once_with()
        ask_to_start_terminal.assert_called_once_with()
        start_terminal.assert_not_called()
        self.assertEqual(
            popen.call_args.kwargs["env"]["THETADATA_REST_FALLBACK_ENABLED"],
            "0",
        )


class FakeChild:
    """A child process that either exits when waited for, or keeps running."""

    def __init__(self, exits_on_wait: bool) -> None:
        self.exits_on_wait = exits_on_wait
        self.exited = False
        self.terminated = False

    def poll(self) -> int | None:
        return 0 if self.exited or self.terminated else None

    def wait(self, timeout: float | None = None) -> int:
        if self.exits_on_wait or self.terminated:
            self.exited = True
            return 0
        raise start_project.subprocess.TimeoutExpired("api.py", timeout)

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.terminated = True


class StopProcessTests(unittest.TestCase):
    def test_a_child_that_finishes_within_the_grace_period_is_not_killed(self) -> None:
        child = FakeChild(exits_on_wait=True)

        start_project._stop_process(child, grace_seconds=60)

        self.assertTrue(child.exited)
        self.assertFalse(child.terminated)

    def test_a_child_still_running_after_the_grace_period_is_stopped(self) -> None:
        child = FakeChild(exits_on_wait=False)

        start_project._stop_process(child, grace_seconds=0.01)

        self.assertTrue(child.terminated)

    def test_without_a_grace_period_a_running_child_is_stopped_at_once(self) -> None:
        child = FakeChild(exits_on_wait=False)

        start_project._stop_process(child)

        self.assertTrue(child.terminated)

    @patch("start_project._stop_process")
    @patch("start_project.subprocess.Popen")
    @patch("start_project._ensure_environment")
    @patch("start_project._is_port_open", return_value=False)
    def test_ctrl_c_gives_the_api_time_to_finish(
        self, is_port_open: Mock, ensure_environment: Mock, popen: Mock, stop_process: Mock,
    ) -> None:
        api_process = Mock()
        api_process.wait.side_effect = KeyboardInterrupt
        popen.return_value = api_process

        result = start_project.main(ask_terminal=False)

        self.assertEqual(result, 130)
        stop_process.assert_called_once_with(api_process, start_project.API_SHUTDOWN_GRACE_SECONDS)


class PythonVersionTests(unittest.TestCase):
    def test_python_older_than_the_sdk_needs_is_refused(self) -> None:
        with patch("start_project.platform.python_version_tuple", return_value=("3", "11", "9")):
            self.assertFalse(start_project._python_version_supported())
        with patch("start_project.platform.python_version_tuple", return_value=("3", "12", "0")):
            self.assertTrue(start_project._python_version_supported())

