"""Start the workspace's Windows desktop apps."""

import argparse
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APPS = {
    "hounddog": ("HoundDog", ROOT / "HoundDog" / "HoundDog.exe", 8080),
    "thetadesk": ("ThetaDesk", ROOT / "ThetaDesk" / "dist" / "ThetaDesk" / "ThetaDesk.exe", 8000),
}


def launch_selected(selected: list[str]) -> dict[str, str]:
    errors = {}
    for app in selected:
        name, executable, port = APPS[app]
        if not executable.is_file():
            errors[app] = f"{name}: missing {executable.relative_to(ROOT)}. See README.md for build instructions."
            continue
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                pass
        except OSError:
            pass
        else:
            errors[app] = f"{name}: port {port} is already in use."
            continue
        try:
            command = [str(executable)]
            if app == "thetadesk":
                command.append("--no-terminal-prompt")
            subprocess.Popen(
                command,
                cwd=executable.parent,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        except OSError as error:
            errors[app] = f"{name}: {error}"
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
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 4)
    )
    ttk.Label(panel, text="Choose one or both apps to start.").grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(0, 14)
    )

    choices = {}
    for row, (key, (name, _, port)) in enumerate(APPS.items(), start=2):
        choice = choices[key] = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            panel, text=f"Start {name}", variable=choice, command=lambda: update_button()
        ).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Label(panel, text=f"Port {port}").grid(row=row, column=1, sticky="e", padx=(32, 0))

    def start() -> None:
        selected = [key for key, choice in choices.items() if choice.get()]
        if not selected:
            return
        errors = launch_selected(selected)
        if not errors:
            window.destroy()
            return
        for key in selected:
            choices[key].set(key in errors)
        update_button()
        messagebox.showerror("Could not start selected apps", "\n\n".join(errors.values()), parent=window)

    def update_button() -> None:
        start_button.state(["!disabled"] if any(choice.get() for choice in choices.values()) else ["disabled"])

    buttons = ttk.Frame(panel)
    buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(20, 0))
    ttk.Button(buttons, text="Cancel", command=window.destroy).pack(side="left", padx=(0, 8))
    start_button = ttk.Button(buttons, text="Start", command=start, default="active")
    start_button.pack(side="left")
    start_button.focus_set()
    window.bind("<Return>", lambda _: start())
    window.bind("<Escape>", lambda _: window.destroy())
    window.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for key, (name, _, _) in APPS.items():
        parser.add_argument(f"--{key}", action="store_true", help=f"Start {name} without the dialog.")
    options = parser.parse_args()
    selected = [key for key in APPS if getattr(options, key)]
    if not selected:
        show_dialog()
        return 0

    errors = launch_selected(selected)
    for error in errors.values():
        print(error, file=sys.stderr)
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
