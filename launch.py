"""Start the workspace's apps: HoundDog, ThetaDesk, and the bridge dashboard."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "logs"
BRIDGE_PACKAGES = "fastapi, uvicorn, tzdata"


def console_python() -> Path:
    """python.exe beside the running interpreter. start.bat runs this chooser with
    pythonw.exe, which has no console, but the bridge needs one to show its
    address and to stop with Ctrl+C when its terminal is shown."""
    interpreter = Path(sys.executable)
    console = interpreter.with_name("python.exe")
    return console if console.is_file() else interpreter


@dataclass(frozen=True)
class App(ABC):
    key: str
    name: str
    port: int

    @abstractmethod
    def problem(self) -> str:
        """Why the app cannot start, or "" if it can."""

    @abstractmethod
    def command(self) -> tuple[list[str], Path]:
        """The command line and the folder to run it in."""


@dataclass(frozen=True)
class ExecutableApp(App):
    executable: Path
    arguments: tuple[str, ...] = ()

    def problem(self) -> str:
        if self.executable.is_file():
            return ""
        return f"missing {self.executable.relative_to(ROOT)}. See README.md for build instructions."

    def command(self) -> tuple[list[str], Path]:
        return [str(self.executable), *self.arguments], self.executable.parent


@dataclass(frozen=True)
class BridgeApp(App):
    script: Path

    def problem(self) -> str:
        if not self.script.is_file():
            return f"missing {self.script.relative_to(ROOT)}."
        try:
            check = subprocess.run(
                [str(console_python()), "-c", f"import {BRIDGE_PACKAGES}"],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return f"could not check its packages: {error}"
        if check.returncode != 0:
            return "its packages are not installed. Run: python -m pip install -r bridge\\requirements.txt"
        return ""

    def command(self) -> tuple[list[str], Path]:
        return [str(console_python()), str(self.script)], self.script.parent


APPS: tuple[App, ...] = (
    ExecutableApp("hounddog", "HoundDog", 8080, ROOT / "HoundDog" / "HoundDog.exe"),
    ExecutableApp(
        "thetadesk", "ThetaDesk", 8000, ROOT / "ThetaDesk" / "dist" / "ThetaDesk" / "ThetaDesk.exe",
        ("--no-terminal-prompt",),
    ),
    BridgeApp("bridge", "Bridge dashboard", 8090, ROOT / "bridge" / "server.py"),
)


def port_in_use(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def log_path(app: App) -> Path:
    return LOGS / f"{app.key}.log"


def start_app(app: App, show_terminal: bool) -> None:
    """Start the app in its own console window, or with no window and its output
    in logs\\<key>.log. A hidden app has no stdin, so a prompt fails instead of
    waiting where nobody can answer it."""
    command, folder = app.command()
    if show_terminal:
        subprocess.Popen(command, cwd=folder, creationflags=subprocess.CREATE_NEW_CONSOLE)
        return
    LOGS.mkdir(exist_ok=True)
    with log_path(app).open("w", encoding="utf-8") as log:
        subprocess.Popen(
            command,
            cwd=folder,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            creationflags=subprocess.CREATE_NO_WINDOW,
        )


def launch_selected(selected: dict[str, bool]) -> dict[str, str]:
    """Start each selected app, keyed by app key with whether to show its terminal;
    return the ones that could not start."""
    errors = {}
    for app in APPS:
        if app.key not in selected:
            continue
        problem = app.problem() or (f"port {app.port} is already in use." if port_in_use(app.port) else "")
        if problem:
            errors[app.key] = f"{app.name}: {problem}"
            continue
        try:
            start_app(app, selected[app.key])
        except OSError as error:
            errors[app.key] = f"{app.name}: {error}"
    return errors


def show_dialog() -> None:
    import tkinter as tk
    from tkinter import messagebox, ttk

    window = tk.Tk()
    window.title("theta_hound")
    window.resizable(False, False)
    panel = ttk.Frame(window, padding=(24, 20))
    panel.grid(sticky="nsew")
    ttk.Label(panel, text="Start your apps", font=("Segoe UI", 16, "bold")).grid(
        row=0, column=0, columnspan=3, sticky="w", pady=(0, 4)
    )
    ttk.Label(panel, text="Choose which apps to start. A hidden app writes to the logs folder.").grid(
        row=1, column=0, columnspan=3, sticky="w", pady=(0, 14)
    )

    choices: dict[str, tk.BooleanVar] = {}
    terminals: dict[str, tk.BooleanVar] = {}
    terminal_boxes: dict[str, ttk.Checkbutton] = {}
    for row, app in enumerate(APPS, start=2):
        choice = choices[app.key] = tk.BooleanVar(value=True)
        terminal = terminals[app.key] = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            panel, text=f"Start {app.name}", variable=choice, command=lambda: update_controls()
        ).grid(row=row, column=0, sticky="w", pady=5)
        terminal_boxes[app.key] = ttk.Checkbutton(panel, text="Show terminal", variable=terminal)
        terminal_boxes[app.key].grid(row=row, column=1, sticky="w", padx=(24, 0))
        ttk.Label(panel, text=f"Port {app.port}").grid(row=row, column=2, sticky="e", padx=(24, 0))

    def start() -> None:
        selected = {key: terminals[key].get() for key, choice in choices.items() if choice.get()}
        if not selected:
            return
        errors = launch_selected(selected)
        if not errors:
            window.destroy()
            return
        for key in selected:
            choices[key].set(key in errors)
        update_controls()
        messagebox.showerror("Could not start selected apps", "\n\n".join(errors.values()), parent=window)

    def update_controls() -> None:
        for key, box in terminal_boxes.items():
            box.state(["!disabled"] if choices[key].get() else ["disabled"])
        start_button.state(["!disabled"] if any(choice.get() for choice in choices.values()) else ["disabled"])

    buttons = ttk.Frame(panel)
    buttons.grid(row=len(APPS) + 2, column=0, columnspan=3, sticky="e", pady=(20, 0))
    ttk.Button(buttons, text="Cancel", command=window.destroy).pack(side="left", padx=(0, 8))
    start_button = ttk.Button(buttons, text="Start", command=start, default="active")
    start_button.pack(side="left")
    start_button.focus_set()
    window.bind("<Return>", lambda _: start())
    window.bind("<Escape>", lambda _: window.destroy())
    window.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for app in APPS:
        parser.add_argument(f"--{app.key}", action="store_true", help=f"Start {app.name} without the dialog.")
    parser.add_argument(
        "--hide-terminals",
        action="store_true",
        help="Run the chosen apps without console windows; their output goes to logs\\.",
    )
    options = parser.parse_args()
    selected = {app.key: not options.hide_terminals for app in APPS if getattr(options, app.key)}
    if not selected:
        show_dialog()
        return 0

    errors = launch_selected(selected)
    for error in errors.values():
        print(error, file=sys.stderr)
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
