"""Start ThetaHound's apps: HoundDog, ThetaDesk, and the bridge dashboard."""

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


@dataclass(frozen=True)
class LaunchOptions:
    port: int
    show_terminal: bool


def start_app(app: App, options: LaunchOptions, extra_args: list[str]) -> None:
    """Start the app in its own console window, or with no window and its output
    in logs\\<key>.log. A hidden app has no stdin, so a prompt fails instead of
    waiting where nobody can answer it."""
    command, folder = app.command()
    if options.port != app.port:
        command.extend(["--port", str(options.port)])
    command.extend(extra_args)
    if options.show_terminal:
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


def launch_selected(
    selected: dict[str, LaunchOptions], *, launched_ports: dict[str, int] | None = None,
) -> dict[str, str]:
    """Start the chosen apps and return the errors keyed by app."""
    ports = {**(launched_ports or {}), **{key: options.port for key, options in selected.items()}}
    bridge_args = []
    for app in APPS:
        port = ports.get(app.key, app.port)
        if app.key in ("hounddog", "thetadesk") and port != app.port:
            bridge_args.extend([f"--{app.key}-port", str(port)])

    errors = {}
    for app in APPS:
        options = selected.get(app.key)
        if options is None:
            continue
        problem = app.problem() or (f"port {options.port} is already in use." if port_in_use(options.port) else "")
        if problem:
            errors[app.key] = f"{app.name}: {problem}"
            continue
        try:
            start_app(app, options, bridge_args if app.key == "bridge" else [])
        except OSError as error:
            errors[app.key] = f"{app.name}: {error}"
    return errors


def use_checkmark_indicator(window, style, *, background: str, border: str, accent: str, ink: str, muted: str):
    import tkinter as tk

    size = round(window.winfo_fpixels("12p"))
    mark = ("........##", ".......##.", "......##..", "##...##...", ".##.##....", "..###.....", "...#......")

    def indicator(fill: str, outline: str, tick: str = ""):
        image = tk.PhotoImage(master=window, width=size + 6, height=size)

        def paint(color: str, bounds: tuple[int, int, int, int]) -> None:
            image.put(color, to=tuple(round(value * size / 16) for value in bounds))

        paint(outline, (0, 0, 16, 16))
        paint(fill, (1, 1, 15, 15))
        if tick:
            for y, line in enumerate(mark, start=4):
                for x, pixel in enumerate(line, start=3):
                    if pixel == "#":
                        paint(tick, (x, y, x + 1, y + 1))
        return image

    images = (
        indicator(background, border),
        indicator(accent, accent, ink),
        indicator(background, border, muted),
        indicator("#080c13", accent),
        indicator("#31558b", accent, accent),
    )
    unchecked, checked, disabled_checked, hover_unchecked, hover_checked = images
    style.element_create(
        "Checkmark.indicator", "image", unchecked,
        ("disabled", "selected", disabled_checked),
        ("disabled", unchecked),
        ("active", "selected", hover_checked),
        ("active", hover_unchecked),
        ("selected", checked),
    )
    layout = style.layout("TCheckbutton")
    children = layout[0][1]["children"]
    children[0] = ("Checkmark.indicator", {"side": "left", "sticky": ""})
    style.layout("TCheckbutton", layout)
    return images


def show_dialog() -> None:
    import tkinter as tk
    from tkinter import messagebox, ttk

    window = tk.Tk()
    window.withdraw()
    window.title("ThetaHound")
    window.resizable(False, False)

    background = "#11151d"
    surface = "#1b2230"
    border = "#374357"
    text = "#eff3fa"
    muted = "#aab7ca"
    accent = "#8db4ff"
    ink = "#101a2c"
    style = ttk.Style(window)
    style.theme_use("clam")
    window.configure(background=background)
    style.configure("TFrame", background=background)
    style.configure("Card.TFrame", background=surface, bordercolor=border)
    style.configure("TLabel", background=background, foreground=muted, font=("Segoe UI", 10))
    style.configure("Title.TLabel", foreground=text, font=("Segoe UI", 25, "bold"))
    style.configure("AppInfo.TLabel", background=surface)
    style.configure(
        "TCheckbutton", background=surface, foreground=text, focuscolor=accent,
        font=("Segoe UI", 10),
    )
    style.configure("App.TCheckbutton", font=("Segoe UI", 11, "bold"))
    style.map(
        "TCheckbutton",
        background=[("disabled", surface), ("active", background)],
        foreground=[("disabled", muted)],
    )
    # Tk styles refer to these images by name, so keep them alive with the window.
    checkmark_images = use_checkmark_indicator(
        window, style, background=background, border=border, accent=accent, ink=ink, muted=muted,
    )
    style.configure(
        "Port.TEntry", fieldbackground=background, foreground=text, insertcolor=text, bordercolor=border,
        lightcolor=background, darkcolor=background, padding=(8, 3), font=("Segoe UI", 10),
    )
    style.map("Port.TEntry", foreground=[("disabled", muted)],
              fieldbackground=[("disabled", surface)], bordercolor=[("focus", accent)])
    style.configure("TSeparator", background=border)
    style.configure(
        "TButton", background=surface, foreground=text, bordercolor=border,
        lightcolor=surface, darkcolor=surface, focuscolor=accent, padding=(18, 7), font=("Segoe UI", 10),
    )
    style.map("TButton", background=[("pressed", background), ("active", "#2a3548")])
    style.configure(
        "Start.TButton", background=accent, foreground=ink, bordercolor=accent,
        lightcolor=accent, darkcolor=accent, focuscolor=ink, font=("Segoe UI", 10, "bold"),
    )
    style.map("Start.TButton",
        background=[("disabled", surface), ("pressed", "#73a1f5"), ("active", "#adcaff")],
        foreground=[("disabled", muted)],
        bordercolor=[("disabled", border)],
        lightcolor=[("disabled", surface)],
        darkcolor=[("disabled", surface)],
    )

    panel = ttk.Frame(window, padding=(26, 22))
    panel.grid(sticky="nsew")
    panel.columnconfigure(0, minsize=468)
    ttk.Label(panel, text="ThetaHound", style="Title.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(panel, text="Choose which apps to start.").grid(
        row=1, column=0, sticky="w", pady=(2, 18),
    )
    card = ttk.Frame(panel, padding=(16, 4), style="Card.TFrame", borderwidth=1, relief="solid")
    card.grid(row=2, column=0, sticky="ew")
    card.columnconfigure(0, weight=1)
    descriptions = {
        "hounddog": "Feed checks and news inbox",
        "thetadesk": "Market data and saved charts",
        "bridge": "News and price studies",
    }
    choices: dict[str, tk.BooleanVar] = {}
    terminals: dict[str, tuple[tk.BooleanVar, ttk.Checkbutton]] = {}
    port_fields: dict[str, ttk.Entry] = {}
    launched_ports: dict[str, int] = {}
    for index, app in enumerate(APPS):
        row = index * 3
        choice = choices[app.key] = tk.BooleanVar(value=True)
        terminal = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            card, text=app.name, style="App.TCheckbutton", variable=choice, command=lambda: update_controls(),
        ).grid(row=row, column=0, sticky="w", pady=(10, 1))
        ttk.Label(card, text=descriptions[app.key], style="AppInfo.TLabel").grid(
            row=row + 1, column=0, sticky="w", padx=(21, 12), pady=(0, 12),
        )
        ttk.Label(card, text="Port", style="AppInfo.TLabel").grid(
            row=row, column=1, sticky="w", padx=(0, 18), pady=(8, 0),
        )
        entry = port_fields[app.key] = ttk.Entry(card, style="Port.TEntry", width=7)
        entry.insert(0, str(app.port))
        entry.grid(row=row + 1, column=1, sticky="w", padx=(0, 18), pady=(0, 10))
        terminal_box = ttk.Checkbutton(card, text="Show terminal", variable=terminal)
        terminal_box.grid(row=row, column=2, rowspan=2, sticky="e")
        terminals[app.key] = terminal, terminal_box
        if index < len(APPS) - 1:
            ttk.Separator(card).grid(row=row + 2, column=0, columnspan=3, sticky="ew")

    def start() -> None:
        selected = {}
        used_ports: dict[int, str] = {}
        for app in APPS:
            if not choices[app.key].get():
                continue
            entry = port_fields[app.key]
            try:
                port = int(entry.get())
            except ValueError:
                port = 0
            problem = ""
            if not 1 <= port <= 65535:
                problem = f"Enter a port from 1 to 65535 for {app.name}."
            elif port in used_ports:
                problem = f"{app.name} and {used_ports[port]} both use port {port}. Choose a different port."
            if problem:
                messagebox.showerror("Check launcher ports", problem, parent=window)
                entry.focus_set()
                entry.selection_range(0, "end")
                return
            used_ports[port] = app.name
            selected[app.key] = LaunchOptions(port, terminals[app.key][0].get())
        if not selected:
            return
        errors = launch_selected(selected, launched_ports=launched_ports)
        if not errors:
            window.destroy()
            return
        for key, options in selected.items():
            choices[key].set(key in errors)
            if key not in errors:
                launched_ports[key] = options.port
        update_controls()
        messagebox.showerror("Could not start selected apps", "\n\n".join(errors.values()), parent=window)

    def update_controls() -> None:
        for key, (_, box) in terminals.items():
            states = ["!disabled"] if choices[key].get() else ["disabled"]
            box.state(states)
            port_fields[key].state(states)
        start_button.state(["!disabled"] if any(choice.get() for choice in choices.values()) else ["disabled"])

    footer = ttk.Frame(panel)
    footer.grid(row=3, column=0, sticky="ew", pady=(18, 0))
    ttk.Label(footer, text="Hidden terminals write to logs/").pack(side="left")
    buttons = ttk.Frame(footer)
    buttons.pack(side="right")
    ttk.Button(buttons, text="Cancel", command=window.destroy).pack(side="left", padx=(0, 8))
    start_button = ttk.Button(buttons, text="Start", style="Start.TButton", command=start, default="active")
    start_button.pack(side="left")
    window.bind("<Return>", lambda _: start())
    window.bind("<Escape>", lambda _: window.destroy())

    window.update_idletasks()
    x = max(0, (window.winfo_screenwidth() - window.winfo_reqwidth()) // 2)
    y = max(0, (window.winfo_screenheight() - window.winfo_reqheight()) // 2)
    window.geometry(f"+{x}+{y}")
    window.deiconify()
    window.update_idletasks()
    if sys.platform == "win32":
        from ctypes import byref, c_int, sizeof, windll, wintypes

        dark = c_int(1)
        # Attribute 20 enables the dark title bar on supported Windows versions.
        windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(int(window.frame(), 0)), 20, byref(dark), sizeof(dark))
    start_button.focus_set()
    window.mainloop()
    del checkmark_images


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
    selected = {
        app.key: LaunchOptions(app.port, not options.hide_terminals)
        for app in APPS if getattr(options, app.key)
    }
    if not selected:
        show_dialog()
        return 0

    errors = launch_selected(selected)
    for error in errors.values():
        print(error, file=sys.stderr)
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
