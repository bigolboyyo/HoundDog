from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

IS_FROZEN = getattr(sys, "frozen", False)
PROJECT_ROOT = (
    Path(sys.executable).resolve().parent
    if IS_FROZEN
    else Path(__file__).resolve().parent
)
VENV_DIRECTORY = PROJECT_ROOT / ".venv"
VENV_PYTHON = VENV_DIRECTORY / "Scripts" / "python.exe"
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"
REQUIREMENTS_HASH_FILE = VENV_DIRECTORY / ".requirements.sha256"
TERMINAL_JAR = PROJECT_ROOT / "ThetaTerminal.jar"
API_HOST = "127.0.0.1"
API_PORT = 8000
# Seconds the API may take to finish its requests after Ctrl+C before it is stopped.
API_SHUTDOWN_GRACE_SECONDS = 60
TERMINAL_HOST = "127.0.0.1"
TERMINAL_PORT = 25510
TERMINAL_STARTUP_TIMEOUT = 60
# The pinned thetadata SDK declares Requires-Python >= 3.12.
MINIMUM_PYTHON = (3, 12)


def _python_version_supported() -> bool:
    version = tuple(int(part) for part in platform.python_version_tuple()[:2])
    return version >= MINIMUM_PYTHON


def _run_checked(command: list[str]) -> None:
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def _ensure_environment() -> None:
    if not VENV_PYTHON.exists():
        print("Creating the project virtual environment...")
        _run_checked([sys.executable, "-m", "venv", str(VENV_DIRECTORY)])

    requirements_hash = hashlib.sha256(REQUIREMENTS_FILE.read_bytes()).hexdigest()
    installed_hash = (
        REQUIREMENTS_HASH_FILE.read_text(encoding="utf-8").strip()
        if REQUIREMENTS_HASH_FILE.exists()
        else ""
    )
    if installed_hash == requirements_hash:
        return

    print("Installing project dependencies...")
    _run_checked(
        [
            str(VENV_PYTHON),
            "-m",
            "pip",
            "install",
            "--quiet",
            "-r",
            str(REQUIREMENTS_FILE),
        ]
    )
    REQUIREMENTS_HASH_FILE.write_text(requirements_hash, encoding="utf-8")


def _is_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _dotenv_value(path: Path, key: str) -> str:
    """One value from a .env file, standard library only: the launcher runs in
    the system Python, before the venv with python-dotenv exists. Reads the
    KEY=value lines that python-dotenv's set_key writes, quoted or not."""
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.strip().removeprefix("export ").partition("=")
        if separator and name.strip() == key:
            return value.strip().strip("'\"")
    return ""


def _terminal_credentials_available() -> bool:
    if os.getenv("THETADATA_API_KEY"):
        return True

    if _dotenv_value(PROJECT_ROOT / ".env", "THETADATA_API_KEY"):
        return True

    credentials_file = PROJECT_ROOT / "creds.txt"
    if not credentials_file.is_file():
        return False
    credentials = credentials_file.read_text(encoding="utf-8").splitlines()
    return len(credentials) >= 2 and all(
        credential.strip() for credential in credentials[:2]
    )


def _ask_to_start_terminal() -> bool:
    try:
        answer = input(
            "Start ThetaData Terminal as the REST backup? [y/N]: "
        ).strip().lower()
    except EOFError:
        print("No interactive console; continuing without the REST backup.")
        return False
    return answer in {"y", "yes"}


def _stop_process(process: subprocess.Popen[bytes], grace_seconds: float = 0) -> None:
    """Stop a child process. With a grace period it may first exit by itself:
    on Ctrl+C the console interrupts the API too, and the API then finishes
    its requests in progress. A second Ctrl+C stops it at once."""
    if grace_seconds and process.poll() is None:
        print("Waiting for the API to finish requests in progress (Ctrl+C again to stop now)...")
        try:
            process.wait(timeout=grace_seconds)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            pass
    if process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _start_terminal_if_needed() -> subprocess.Popen[bytes] | None:
    if _is_port_open(TERMINAL_HOST, TERMINAL_PORT):
        print("ThetaData Terminal is already running.")
        return None
    if not TERMINAL_JAR.is_file():
        raise RuntimeError(f"ThetaData Terminal JAR not found: {TERMINAL_JAR}")

    java = shutil.which("java")
    if java is None:
        raise RuntimeError("Java is required to start ThetaTerminal.jar.")

    command = [java, "-jar", str(TERMINAL_JAR)]
    credentials_file = PROJECT_ROOT / "creds.txt"
    if credentials_file.is_file():
        command.extend(["--creds-file", str(credentials_file)])

    print("Starting ThetaData Terminal...")
    terminal_process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )
    ready = False
    try:
        deadline = time.monotonic() + TERMINAL_STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if _is_port_open(TERMINAL_HOST, TERMINAL_PORT):
                ready = True
                print("ThetaData Terminal is ready.")
                return terminal_process
            exit_code = terminal_process.poll()
            if exit_code is not None:
                raise RuntimeError(
                    "ThetaData Terminal exited before its REST API became ready "
                    f"(exit code {exit_code})."
                )
            time.sleep(1)

        raise RuntimeError(
            "ThetaData Terminal did not open port 25510 within "
            f"{TERMINAL_STARTUP_TIMEOUT} seconds."
        )
    finally:
        if not ready:
            _stop_process(terminal_process)


def _open_browser_when_ready() -> None:
    deadline = time.monotonic() + TERMINAL_STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if _is_port_open(API_HOST, API_PORT):
            webbrowser.open(f"http://{API_HOST}:{API_PORT}/")
            return
        time.sleep(0.25)


def main(*, ask_terminal: bool = True, open_browser: bool = True, setup_only: bool = False) -> int:
    if setup_only and IS_FROZEN:
        print("Run start_project.py from source to prepare the build environment.")
        return 1
    if not IS_FROZEN and not _python_version_supported():
        print(f"Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer is required to start this project.")
        return 1

    api_process: subprocess.Popen[bytes] | None = None
    interrupted = False
    terminal_process: subprocess.Popen[bytes] | None = None
    try:
        if not IS_FROZEN:
            _ensure_environment()
        if setup_only:
            print("ThetaDesk build environment is ready.")
            return 0
        if _is_port_open(API_HOST, API_PORT):
            raise RuntimeError(
                f"Port {API_PORT} is already in use; stop its process first."
            )

        fallback_enabled = _is_port_open(TERMINAL_HOST, TERMINAL_PORT)
        if fallback_enabled:
            print("ThetaData Terminal is already running; REST backup is ready.")
        elif not ask_terminal:
            print("Continuing with the Python client only.")
        elif not _terminal_credentials_available():
            print(
                "No ThetaData API key or valid creds.txt found; "
                "continuing with the Python client only."
            )
        elif _ask_to_start_terminal():
            try:
                terminal_process = _start_terminal_if_needed()
                fallback_enabled = True
            except (OSError, RuntimeError) as error:
                print(f"REST backup could not start: {error}")
                print("Continuing with the Python client only.")
        else:
            print("Continuing with the Python client only.")

        print(f"Starting the API. Docs will be at http://{API_HOST}:{API_PORT}/docs")
        api_environment = os.environ.copy()
        api_environment["THETADATA_REST_FALLBACK_ENABLED"] = (
            "1" if fallback_enabled else "0"
        )
        if IS_FROZEN:
            os.environ["THETADATA_REST_FALLBACK_ENABLED"] = (
                api_environment["THETADATA_REST_FALLBACK_ENABLED"]
            )
            os.chdir(PROJECT_ROOT)
            from api import serve

            if open_browser:
                threading.Thread(
                    target=_open_browser_when_ready,
                    daemon=True,
                ).start()
            print(f"Starting the API. Opening http://{API_HOST}:{API_PORT}/")
            serve(API_HOST, API_PORT)
            return 0

        api_process = subprocess.Popen(
            [
                str(VENV_PYTHON),
                "api.py",
                "--host",
                API_HOST,
                "--port",
                str(API_PORT),
            ],
            cwd=PROJECT_ROOT,
            env=api_environment,
        )
        return api_process.wait()
    except KeyboardInterrupt:
        interrupted = True
        print("\nStopping the project...")
        return 130
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Could not start the project: {error}")
        return 1
    finally:
        if api_process is not None:
            _stop_process(api_process, API_SHUTDOWN_GRACE_SECONDS if interrupted else 0)
        if terminal_process is not None:
            _stop_process(terminal_process)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start the ThetaDesk dashboard.")
    parser.add_argument("--no-terminal-prompt", action="store_true",
                        help="Use a running Terminal if available and skip the startup prompt.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser in the packaged app.")
    parser.add_argument("--setup-only", action="store_true", help="Prepare the source environment without starting services.")
    options = parser.parse_args()
    raise SystemExit(main(
        ask_terminal=not options.no_terminal_prompt,
        open_browser=not options.no_browser,
        setup_only=options.setup_only,
    ))
