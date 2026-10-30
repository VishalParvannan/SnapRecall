"""Open the system's native folder chooser (File Explorer on Windows).

The dialog runs in a separate Python process because Tk must own its main
thread, which Streamlit's script thread is not. Like "Open original", it
appears on the computer running the app.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_DIALOG = """
import sys, tkinter as tk
from tkinter import filedialog
root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)
path = filedialog.askdirectory(title="Choose a screenshot folder",
                               initialdir=sys.argv[1] or None, mustexist=True)
root.destroy()
sys.stdout.write(path or "")
"""


class FolderPickerError(RuntimeError):
    pass


def default_start() -> str:
    for candidate in (Path.home() / "Pictures" / "Screenshots", Path.home() / "Pictures", Path.home()):
        if candidate.is_dir():
            return str(candidate)
    return ""


def pick_folder(start: str | None = None) -> str | None:
    """Show the folder dialog. Returns the chosen path, or None if cancelled."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", _DIALOG, start or default_start()],
            capture_output=True, text=True, encoding="utf-8", timeout=900,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FolderPickerError("The folder picker couldn't be opened.") from exc
    if result.returncode != 0:
        raise FolderPickerError("The folder picker couldn't be opened.")
    return str(Path(result.stdout.strip())) if result.stdout.strip() else None
