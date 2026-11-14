"""Open the "Add screenshots" window, where folders, screenshots, or both can be chosen.

The window (picker_dialog.py) runs in a separate Python process because Tk must own
its main thread, which Streamlit's script thread is not. Like "Open original", it
appears on the computer running the app.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Windows gets its own modern Explorer dialog; other systems get the Tk window.
_DIALOG = Path(__file__).with_name("windows_picker.py" if sys.platform.startswith("win") else "picker_dialog.py")


class FolderPickerError(RuntimeError):
    pass


def default_start() -> str:
    for candidate in (Path.home() / "Pictures" / "Screenshots", Path.home() / "Pictures", Path.home()):
        if candidate.is_dir():
            return str(candidate)
    return ""


def pick_screenshots(start: str | None = None) -> list[str]:
    """Show the window. Returns the chosen folders and files (empty if cancelled)."""
    try:
        result = subprocess.run(
            [sys.executable, str(_DIALOG), start or default_start()],
            capture_output=True, text=True, encoding="utf-8", timeout=900,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FolderPickerError("The screenshot picker couldn't be opened.") from exc
    if result.returncode != 0:
        raise FolderPickerError("The screenshot picker couldn't be opened.")
    return [str(Path(line)) for line in result.stdout.splitlines() if line.strip()]
